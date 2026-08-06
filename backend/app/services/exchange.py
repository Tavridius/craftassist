"""Обменки: что выгодно брать у Перекупщика за обменные монеты.

Ассортимента Перекупщика нет ни в публичном API, ни в базе EXBO, ни в клиенте
(проверено 14.07.2026) — позиции вносятся вручную в JSON. Источник — seed-файл
в репозитории (backend/seed/reseller_exchange.json), при старте копируется в
DATA_DIR; файл в volume можно править прямо на сервере (hot-reload по mtime),
при деплое побеждает тот, чей updated_at новее.

Курс позиции — рублей за 1 монету, по трём каналам:
  аук:      rate_auction = продажа(предмет)×кол-во×(1−комиссия) / монеты
  скупщик:  rate_vendor  = vendor×кол-во / монеты  (мгновенно, без комиссии)
  разбор:   rate_market  = цена замещения×кол-во / монеты  (см. _via_parent)
Основной rate = лучший из известных. Цены аука — тёплый кэш PriceStore,
vendor — ручное поле позиции (цена скупщика фиксирована игрой).

Почему нужен третий канал: ВСЕ позиции Перекупщика имеют игровой статус
PERSONAL_DROP_ON_GET (личные при получении) — на аук их не выставить, поэтому
колонка «аук» у них пустая всегда. Их ценность — не выручка, а экономия: тот же
ресурс иначе добывается разбором родителя, который на ауке торгуется (NON_DROP).
"""
import json
import logging
import math
import os
import shutil
import time
from datetime import datetime, timezone

from app import config
from app.db.index import db
from app.services import craft
from app.services.price_store import store

logger = logging.getLogger(__name__)

SEED = config.BACKEND_DIR / "seed" / "reseller_exchange.json"
# та же граница свежести, что и у бартера (см. barter.BARTER_SELL_FRESH_DAYS) —
# без неё неликвид с последней продажей год+ назад (напр. папоротник, сделки
# 2023 года) выдаётся за текущую цену и попадает в топ выгодности (баг benqerrrr)
SELL_FRESH_DAYS = float(os.getenv("BARTER_SELL_FRESH_DAYS", "14"))

_doc: dict = {"updated_at": None, "positions": []}
_mtime = 0.0


def _path():
    return config.DATA_DIR / "reseller_exchange.json"


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _sale_age_days(ts: str | None) -> float | None:
    """Сколько дней прошло с последней сделки (None — время неизвестно)."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _via_parent(iid: str, amount: int) -> dict | None:
    """Цена замещения: во сколько обошлось бы добыть предмет без Перекупщика.

    Предметы обменок личные (PERSONAL_DROP_ON_GET) — продать их нельзя, но тот же
    ресурс достаётся разбором родителя с аука: 1 разбор даёт count штук. Столько
    игрок НЕ потратит, взяв позицию за монеты, — это и есть её ценность.

    Зеркало barter._obtain (barter.py:74-83): берём ту же цену ЗАКУПКИ родителя по
    стакану, поэтому барахолка и обменки оценивают один ресурс одинаково. Комиссию
    аука не вычитаем — это не выручка от продажи, а избежанная покупка.
    """
    dz = db.disassembly.get(iid)
    if not dz or not store.get(dz["parent"])["available"]:
        return None
    blocks = max(1, math.ceil(amount / dz["count"]))
    parent_unit = craft.unit_buy_price(dz["parent"], blocks)
    if parent_unit is None:
        return None
    return {"parent": dz["parent"],
            "parent_name": (db.item(dz["parent"]) or {}).get("name", dz["parent"]),
            "count": dz["count"], "blocks": blocks,
            "parent_unit": round(parent_unit),   # для UI, как в barter.py:83
            "unit": parent_unit / dz["count"]}   # float — округляем один раз на выходе


def load() -> None:
    """Разложить seed в DATA_DIR (если новее или файла нет) и прочитать."""
    live = _path()
    try:
        if SEED.exists():
            seed_doc = json.loads(SEED.read_text(encoding="utf-8"))
            live_doc = (json.loads(live.read_text(encoding="utf-8"))
                        if live.exists() else None)
            seed_dt, live_dt = (_parse_dt(seed_doc.get("updated_at")),
                                _parse_dt((live_doc or {}).get("updated_at")))
            if live_doc is None or (seed_dt and (live_dt is None or seed_dt > live_dt)):
                shutil.copyfile(SEED, live)
                logger.info("exchange: seed -> %s", live)
    except Exception:
        logger.exception("exchange: seed copy failed")
    _read()
    # предметы позиций — воркеру в ротацию цен (extra), сразу приоритетно.
    # Вместе с ними родители разбора: сами позиции на ауке не торгуются, и вся
    # оценка (_via_parent) держится на стакане родителя.
    ids = [p.get("item") for p in _doc.get("positions", []) if p.get("item")]
    parents = [db.disassembly[i]["parent"] for i in ids if i in db.disassembly]
    if ids or parents:
        store.request(ids + sorted(set(parents)))


def _read() -> None:
    global _doc, _mtime
    live = _path()
    if not live.exists():
        return
    try:
        m = live.stat().st_mtime
        if m == _mtime:
            return
        _doc = json.loads(live.read_text(encoding="utf-8"))
        _mtime = m
        logger.info("exchange: loaded %d positions (updated_at=%s)",
                    len(_doc.get("positions", [])), _doc.get("updated_at"))
    except Exception:
        logger.exception("exchange: failed to read %s", live)


def by_item() -> dict:
    """{item_id: {"coins", "amount", "limit"}} — позиции Перекупщика для
    подсказок в других разделах (напр. корзина бартеров), hot-reload."""
    _read()
    out = {}
    for p in _doc.get("positions", []):
        iid = p.get("item")
        if iid and (p.get("coins") or 0) > 0:
            out[iid] = {"coins": p["coins"], "amount": p.get("amount") or 1,
                        "limit": p.get("limit")}
    return out


def snapshot() -> dict:
    """Позиции с курсами (руб/монета), отсортированы по выгодности."""
    _read()  # hot-reload, если файл правили
    rows = []
    for p in _doc.get("positions", []):
        iid = p.get("item")
        coins = p.get("coins") or 0
        amount = p.get("amount") or 1
        vendor = p.get("vendor")
        it = db.item(iid) or {}
        sp = craft.sell_price(iid)
        age = _sale_age_days((store.history.get(iid) or {}).get("last_sale_ts"))
        sp_fresh = sp if sp is not None and age is not None and age <= SELL_FRESH_DAYS else None
        buyout = (store.prices.get(iid) or {}).get("min_buyout")
        base = sp_fresh if sp_fresh is not None else buyout
        value_auc = round(base * amount * (1 - config.AUCTION_FEE)) if base else None
        value_ven = round(vendor * amount) if vendor else None
        mk = _via_parent(iid, amount)
        value_mkt = round(mk["unit"] * amount) if mk else None
        rate_auc = round(value_auc / coins, 2) if value_auc and coins else None
        rate_ven = round(value_ven / coins, 2) if value_ven and coins else None
        rate_mkt = round(value_mkt / coins, 2) if value_mkt and coins else None
        # Основной курс — только РЕАЛИЗУЕМЫЕ каналы (аук/скупщик): по нему идёт
        # сортировка и корзина, а монеты невозобновляемы — советовать по ним
        # ценность, которую нельзя обратить в деньги, нельзя. Курс через разбор
        # (rate_market) считаем и отдаём справочно, в выбор канала он не входит.
        cands = [(rate_auc, "auction", value_auc), (rate_ven, "vendor", value_ven)]
        live = [c for c in cands if c[0] is not None]
        rate, basis, value = (max(live, key=lambda c: c[0]) if live
                              else (None, None, None))
        rows.append({
            "id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"),
            "amount": amount, "coins": coins, "limit": p.get("limit"),
            "note": p.get("note"),
            "sell_price": sp_fresh, "min_buyout": buyout,
            "sale_age_days": round(age, 1) if age is not None else None,
            "sell_basis": "sales" if sp_fresh is not None else ("buyout" if buyout else None),
            "vendor": vendor,
            "value_auction": value_auc,   # ₽ за покупку через аук (нетто)
            "value_vendor": value_ven,    # ₽ за покупку через скупщика (мгновенно)
            "value_market": value_mkt,    # ₽ цены замещения (разбор родителя)
            "rate_auction": rate_auc,
            "rate_vendor": rate_ven,
            "rate_market": rate_mkt,
            "disasm": mk,                 # {parent, parent_name, count, parent_unit} | None
            "value": value,               # ₽ по каналу basis (в него смотрит корзина)
            "rate": rate,                 # ₽ за 1 монету, лучший ДЕНЕЖНЫЙ канал
            "basis": basis,               # auction | vendor
        })
    rows.sort(key=lambda r: (r["rate"] is None, -(r["rate"] or 0)))
    top_vendor = sorted((r for r in rows if r["rate_vendor"]),
                        key=lambda r: -r["rate_vendor"])[:3]
    return {
        "updated_at": _doc.get("updated_at"),
        "positions": rows,
        "top_vendor": [{"id": r["id"], "name": r["name"], "rate": r["rate_vendor"]}
                       for r in top_vendor],
        "fee_pct": round(config.AUCTION_FEE * 100),
        "empty": not rows,
    }


def plan(coins: int) -> dict:
    """Жадная корзина: тратим монеты по лучшему курсу с учётом лимитов.

    value — живые деньги (курс идёт по реализуемым каналам, см. snapshot); market —
    та же корзина по цене замещения, справочно: ресурсы под бартер стоят кратно
    дороже своей сдачи скупщику, но обратить их в рубли нельзя.
    """
    snap = snapshot()
    left = max(0, int(coins))
    basket = []
    total_value = 0
    total_market = 0
    for r in snap["positions"]:
        if not r["rate"] or not r["coins"]:
            continue
        can = left // r["coins"]
        if r["limit"]:
            can = min(can, int(r["limit"]))
        if can <= 0:
            continue
        spend = can * r["coins"]
        value = round(can * (r["value"] or 0))
        market = round(can * (r["value_market"] or 0))
        basket.append({**r, "buys": can, "spend": spend, "total_value": value,
                       "total_market": market})
        left -= spend
        total_value += value
        total_market += market
        if left <= 0:
            break
    return {"coins": int(coins), "spent": int(coins) - left, "left": left,
            "value": total_value, "market": total_market, "basket": basket,
            "updated_at": snap["updated_at"], "empty": snap["empty"]}
