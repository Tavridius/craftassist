"""Обменки: что выгодно брать у Перекупщика за обменные монеты.

Ассортимента Перекупщика нет ни в публичном API, ни в базе EXBO, ни в клиенте
(проверено 14.07.2026) — позиции вносятся вручную в JSON. Источник — seed-файл
в репозитории (backend/seed/reseller_exchange.json), при старте копируется в
DATA_DIR; файл в volume можно править прямо на сервере (hot-reload по mtime),
при деплое побеждает тот, чей updated_at новее.

Курс позиции: rate = продажа(предмет)×кол-во×(1−комиссия) / цена в монетах —
сколько рублей приносит одна обменная монета. Цены — тёплый кэш PriceStore.
"""
import json
import logging
import shutil
import time
from datetime import datetime

from app import config
from app.db.index import db
from app.services import craft
from app.services.price_store import store

logger = logging.getLogger(__name__)

SEED = config.BACKEND_DIR / "seed" / "reseller_exchange.json"

_doc: dict = {"updated_at": None, "positions": []}
_mtime = 0.0


def _path():
    return config.DATA_DIR / "reseller_exchange.json"


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


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
    # предметы позиций — воркеру в ротацию цен (extra), сразу приоритетно
    ids = [p.get("item") for p in _doc.get("positions", []) if p.get("item")]
    if ids:
        store.request(ids)


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


def snapshot() -> dict:
    """Позиции с курсами (руб/монета), отсортированы по выгодности."""
    _read()  # hot-reload, если файл правили
    rows = []
    for p in _doc.get("positions", []):
        iid = p.get("item")
        coins = p.get("coins") or 0
        amount = p.get("amount") or 1
        it = db.item(iid) or {}
        sp = craft.sell_price(iid)
        buyout = (store.prices.get(iid) or {}).get("min_buyout")
        base = sp if sp is not None else buyout
        value = round(base * amount * (1 - config.AUCTION_FEE)) if base else None
        rate = round(value / coins, 2) if value and coins else None
        rows.append({
            "id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"),
            "amount": amount, "coins": coins, "limit": p.get("limit"),
            "note": p.get("note"),
            "sell_price": sp, "min_buyout": buyout,
            "sell_basis": "sales" if sp is not None else ("buyout" if buyout else None),
            "value": value,       # рублей за одну покупку (нетто, после комиссии)
            "rate": rate,         # рублей за 1 монету
        })
    rows.sort(key=lambda r: (r["rate"] is None, -(r["rate"] or 0)))
    return {
        "updated_at": _doc.get("updated_at"),
        "positions": rows,
        "fee_pct": round(config.AUCTION_FEE * 100),
        "empty": not rows,
    }


def plan(coins: int) -> dict:
    """Жадная корзина: тратим монеты по лучшему курсу с учётом лимитов."""
    snap = snapshot()
    left = max(0, int(coins))
    basket = []
    total_value = 0
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
        basket.append({**r, "buys": can, "spend": spend, "total_value": value})
        left -= spend
        total_value += value
        if left <= 0:
            break
    return {"coins": int(coins), "spent": int(coins) - left, "left": left,
            "value": total_value, "basket": basket,
            "updated_at": snap["updated_at"], "empty": snap["empty"]}
