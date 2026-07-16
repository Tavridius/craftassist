"""Калькулятор бартера: выгодность обменов у торговцев поселений.

Данные — barter_recipes.json (GameDB), цены — тёплый кэш PriceStore, без сети.

    стоимость оффера = деньги + Σ obtain(вход) × кол-во
    obtain(вход)     = min( купить на ауке , собрать бартером ) — рекурсивно,
                       т.к. входы бывают трейд-ином прошлого тира (броня/оружие)

Вход без лотов и без своей бартер-цепочки — «фарм» (флешки, жетоны, растения):
он не участвует в деньгах, оффер помечается missing и в рейтинг «чисто за
деньги» не попадает. Выгода — как в крафте: реальная цена продажи (медиана
свежих сделок, fallback мин. выкуп) минус комиссия аука против стоимости.
"""
import math
import os
import time

from app import config
from app.db.index import db
from app.services import craft
from app.services.price_store import store

BARTER_TTL = int(os.getenv("BARTER_TTL", "60"))          # кэш рейтинга, сек
BARTER_MAX_DEPTH = int(os.getenv("BARTER_MAX_DEPTH", "6"))  # глубина трейд-ин цепочек

_cache: dict | None = None
_cache_ts = 0.0


def _category(iid: str) -> str:
    """items/weapon/... -> weapon (категория результата для фильтра)."""
    rel = db._data_path.get(iid) or ""
    parts = rel.split("/")
    return parts[1] if len(parts) > 2 else "other"


def _obtain(iid: str, path: tuple, memo: dict, needed: int = 1) -> dict:
    """Мин. цена получения 1 шт: аук, разбор родителя с аука или бартер-цепочка.

    -> {"cost": int|None, "source": "market"|"disassembly"|"barter"|None,
        "disasm": {"parent", "count", "parent_unit"}|None}
    """
    key = (iid, needed)
    if key in memo:
        return memo[key]
    market = craft.unit_buy_price(iid, needed) if store.get(iid)["available"] else None
    best, source, disasm = market, ("market" if market is not None else None), None
    # разбор родителя с аука (напр. блок данных «Гамма» -> 20 фрагментов):
    # цена входа = цена родителя на ауке / count
    dz = db.disassembly.get(iid)
    if dz and store.get(dz["parent"])["available"]:
        blocks = max(1, math.ceil(needed / dz["count"]))
        parent_unit = craft.unit_buy_price(dz["parent"], blocks)
        if parent_unit is not None:
            unit = parent_unit / dz["count"]
            if best is None or unit < best:
                best, source = unit, "disassembly"
                disasm = {"parent": dz["parent"], "count": dz["count"],
                          "parent_unit": round(parent_unit)}
    if iid not in path and len(path) < BARTER_MAX_DEPTH:
        for b in db.barter_by_result.get(iid, []):
            for off in b["offers"]:
                cost = _offer_cost(off, path + (iid,), memo)
                if cost["total"] is not None and not cost["missing"] and \
                        (best is None or cost["total"] < best):
                    best, source, disasm = cost["total"], "barter", None
    res = {"cost": best, "source": source, "disasm": disasm}
    memo[key] = res
    return res


CURRENCY_RU = {"money": "Рубли", "sleeves": "Гильзы"}


def _offer_cost(off: dict, path: tuple, memo: dict, qty: int = 1) -> dict:
    """Стоимость оффера (qty повторов): деньги + покупаемые входы; missing — фарм.

    cost в не-рублёвой валюте (гильзы сессионных боёв) в рубли не конвертируется —
    оффер считается «не чисто за деньги» (currency_cost отражается отдельно).
    """
    cash = float(off["cost"] or 0) * qty
    foreign = off["currency"] != "money" and cash > 0
    total = 0.0 if foreign else cash
    missing: list[str] = []
    lines = []
    for ing in off["inputs"]:
        amount = ing["amount"] * qty
        got = _obtain(ing["item"], path, memo, needed=amount)
        unit = got["cost"]
        if unit is None:
            missing.append(ing["item"])
            lines.append({"item": ing["item"], "amount": amount,
                          "unit": None, "line": None, "source": None})
        else:
            lines.append({"item": ing["item"], "amount": amount,
                          "unit": unit, "line": round(unit * amount),
                          "source": got["source"], "disasm": got.get("disasm")})
            total += unit * amount
    # total при missing/чужой валюте — стоимость ПОКУПАЕМОЙ части, не полная
    return {"total": round(total) if not missing and not foreign else None,
            "partial": round(total), "missing": missing, "lines": lines,
            "foreign": foreign}


def _sell_side(iid: str) -> dict:
    """Цена продажи результата: реальные сделки, fallback мин. выкуп."""
    sp = craft.sell_price(iid)
    buyout = (store.prices.get(iid) or {}).get("min_buyout")
    base = sp if sp is not None else buyout
    return {
        "sell_price": sp, "min_buyout": buyout,
        "sell_basis": "sales" if sp is not None else ("buyout" if buyout else None),
        "sell_net": round(base * (1 - config.AUCTION_FEE)) if base else None,
    }


def _brief(iid: str) -> dict:
    it = db.item(iid) or {}
    return {"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT")}


def compute_top() -> dict:
    """Рейтинг всех бартеров (кэш BARTER_TTL): по строке на (поселение, предмет)."""
    global _cache, _cache_ts
    now = time.time()
    if _cache and now - _cache_ts < BARTER_TTL:
        return _cache

    memo: dict = {}
    rows = []
    for iid, barters in db.barter_by_result.items():
        sell = _sell_side(iid)
        hist = store.history.get(iid) or {}
        for b in barters:
            # лучший оффер: сперва полностью покупаемые, дальше — дешевле
            evaluated = [(_offer_cost(off, (iid,), memo), off) for off in b["offers"]]
            evaluated.sort(key=lambda e: (bool(e[0]["missing"]),
                                          e[0]["total"] if e[0]["total"] is not None
                                          else e[0]["partial"]))
            cost, off = evaluated[0]
            pct = None
            if cost["total"] and sell["sell_net"] and cost["total"] > 0:
                pct = round((sell["sell_net"] - cost["total"]) / cost["total"] * 100)
            rows.append({
                **_brief(iid),
                "category": _category(iid),
                "settlement": b["settlement"],
                "settlement_name": b["settlement_name"],
                "level": b["level"],
                "currency": off["currency"],
                "money": off["cost"],
                "cost": cost["total"],
                "cost_partial": cost["partial"],
                "missing": [_brief(m)["name"] for m in cost["missing"]],
                "n_inputs": len(off["inputs"]),
                "n_offers": len(b["offers"]),
                **sell,
                "pct": pct,
                "sales_per_hour": hist.get("sales_per_hour"),
            })
    rows.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))
    _cache = {
        "rows": rows,
        "settlements": [{"key": k, "name": v} for k, v in
                        sorted(db.barter_settlements.items(), key=lambda kv: kv[1])],
        "categories": sorted({r["category"] for r in rows}),
        "fee_pct": round(config.AUCTION_FEE * 100),
        "prices_ready": store.stats()["priced"],
    }
    _cache_ts = now
    return _cache


def basket(items: list[dict]) -> dict:
    """Корзина: суммарная стоимость набора бартеров, по лучшему офферу на предмет.

    items: [{"id", "qty"}] -> постатейные строки + агрегированные ресурсы по всем
    обменам + деньги торговцам по валютам. Лучший оффер — как в compute_top:
    сперва полностью покупаемые, дальше дешевле.
    """
    memo: dict = {}
    rows, agg = [], {}
    money_by_cur: dict[str, float] = {}
    want: set[str] = set()
    for req in items:
        iid, qty = req["id"], req["qty"]
        best = None
        for b in db.barter_by_result.get(iid, []):
            for off in b["offers"]:
                c = _offer_cost(off, (iid,), memo, qty=qty)
                key = (bool(c["missing"]),
                       c["total"] if c["total"] is not None else c["partial"])
                if best is None or key < best[3]:
                    best = (c, off, b, key)
        if best is None:
            rows.append({**_brief(iid), "qty": qty, "no_barter": True})
            continue
        cost, off, b = best[0], best[1], best[2]
        cash = float(off["cost"] or 0) * qty
        if cash:
            money_by_cur[off["currency"]] = money_by_cur.get(off["currency"], 0.0) + cash
        for line in cost["lines"]:
            a = agg.get(line["item"])
            if a is None:
                a = agg[line["item"]] = {**_brief(line["item"]),
                                         "amount": 0, "cost": 0, "farm": False}
            a["amount"] += line["amount"]
            if line["line"] is not None:
                a["cost"] += line["line"]
            else:
                a["farm"] = True
            want.add(line["item"])
        rows.append({**_brief(iid), "qty": qty,
                     "settlement_name": b["settlement_name"], "level": b["level"],
                     "currency": off["currency"], "money": off["cost"],
                     "cost": cost["total"], "cost_partial": cost["partial"],
                     "missing": [_brief(m)["name"] for m in cost["missing"]]})
    if want:
        store.request(want)  # непосчитанное — воркеру вне очереди
    resources = sorted(agg.values(), key=lambda r: -(r["cost"] or 0))
    total = round(sum(r["cost"] for r in resources) + money_by_cur.get("money", 0.0))
    return {
        "items": rows,
        "resources": resources,
        "money": [{"currency": c, "name": CURRENCY_RU.get(c, c), "amount": round(v)}
                  for c, v in sorted(money_by_cur.items())],
        "total": total,
        "has_farm": any(r["farm"] for r in resources),
        "fee_pct": round(config.AUCTION_FEE * 100),
    }


def _expand_offer(off: dict, path: tuple, memo: dict, depth: int = 0) -> dict:
    """Оффер с раскрытыми входами (для карточки): каждый вход — узел с ценой,
    источником (аук/бартер/фарм) и, если выгоден бартер, вложенной цепочкой."""
    cost = _offer_cost(off, path, memo)
    inputs = []
    for line in cost["lines"]:
        node = {**_brief(line["item"]), "amount": line["amount"],
                "unit_price": line["unit"], "line_cost": line["line"],
                "source": line["source"] or "farm"}
        if line.get("disasm"):
            node["disasm"] = {**line["disasm"],
                              "parent_name": _brief(line["disasm"]["parent"])["name"]}
        if line["source"] == "barter" and depth < 2:
            sub_ways = db.barter_by_result.get(line["item"], [])
            best = None
            for sb in sub_ways:
                for soff in sb["offers"]:
                    sc = _offer_cost(soff, path + (line["item"],), memo)
                    if sc["total"] is not None and (best is None or
                                                    sc["total"] < best[0]):
                        best = (sc["total"], sb, soff)
            if best:
                node["via"] = {"settlement_name": best[1]["settlement_name"],
                               "level": best[1]["level"],
                               **_expand_offer(best[2], path + (line["item"],),
                                               memo, depth + 1)}
        inputs.append(node)
    return {"currency": off["currency"], "money": off["cost"],
            "cost": cost["total"], "cost_partial": cost["partial"],
            "missing": [_brief(m) for m in cost["missing"]], "inputs": inputs}


def _same_cat_prev(iid: str):
    """Предыдущий тир: вход-бартер той же категории (трейд-ин прошлого уровня).
    -> (prev_id, поселение, оффер) или (None, None, None)."""
    cat = _category(iid)
    for b in db.barter_by_result.get(iid, []):
        for off in b["offers"]:
            for ing in off["inputs"]:
                if ing["item"] in db.barter_by_result and _category(ing["item"]) == cat:
                    return ing["item"], b, off
    return None, None, None


def _same_cat_next(iid: str, seen: set):
    """Следующий тир: бартер той же категории, куда этот предмет идёт трейд-ином."""
    cat = _category(iid)
    for res_id in db.barter_used_in.get(iid, []):
        if res_id in seen or _category(res_id) != cat:
            continue
        for b in db.barter_by_result.get(res_id, []):
            for off in b["offers"]:
                if any(ing["item"] == iid for ing in off["inputs"]):
                    return res_id, b, off
    return None, None, None


def _step_dict(prev_id: str, b: dict, off: dict, result_id: str) -> dict:
    """Шаг цепочки: что нужно, чтобы из prev_id получить result_id (кроме самого
    prev_id — он трейд-ин). resources — покупаемые/фарм-входы с ценами."""
    memo: dict = {}
    res, prev_amount = [], 1
    for ing in off["inputs"]:
        if ing["item"] == prev_id:
            prev_amount = ing["amount"]
            continue
        got = _obtain(ing["item"], (result_id,), memo, ing["amount"])
        unit = got["cost"]
        res.append({**_brief(ing["item"]), "amount": ing["amount"], "unit_price": unit,
                    "line_cost": round(unit * ing["amount"]) if unit is not None else None,
                    "source": got["source"] or "farm"})
    return {"settlement_name": b["settlement_name"], "level": b["level"],
            "prev": prev_id, "prev_amount": prev_amount, "money": off["cost"],
            "currency": off["currency"], "resources": res}


def _chain(iid: str) -> tuple[list, int]:
    """Полная лестница тиров: база … [открытый предмет] … верх (той же категории).
    У каждого узла (кроме базы своей ветки) step — как получить его из предыдущего.
    -> (nodes, index открытого предмета)."""
    seen = {iid}
    up = []      # (prev, result, поселение, оффер) — вверх к базе
    cur = iid
    while True:
        prev, b, off = _same_cat_prev(cur)
        if not prev or prev in seen:
            break
        up.append((prev, cur, b, off))
        seen.add(prev)
        cur = prev
    down = []    # вниз к верхним тирам
    cur = iid
    while True:
        nxt, b, off = _same_cat_next(cur, seen)
        if not nxt:
            break
        down.append((cur, nxt, b, off))
        seen.add(nxt)
        cur = nxt
    order = [t[0] for t in reversed(up)] + [iid] + [t[1] for t in down]
    steps = {}
    for prev, res_id, b, off in up + down:
        steps[res_id] = _step_dict(prev, b, off, res_id)
    nodes = []
    for it in order:
        n = _brief(it)
        n["buy_price"] = craft.unit_buy_price(it) if store.get(it)["available"] else None
        n["step"] = steps.get(it)
        nodes.append(n)
    return nodes, len(up)


def analyze(iid: str) -> dict:
    """Все способы получить предмет бартером + где он сдаётся (для карточки)."""
    memo: dict = {}
    ways = []
    for b in db.barter_by_result.get(iid, []):
        offers = [_expand_offer(off, (iid,), memo) for off in b["offers"]]
        offers.sort(key=lambda o: (o["cost"] is None,
                                   o["cost"] if o["cost"] is not None else o["cost_partial"]))
        ways.append({"settlement": b["settlement"],
                     "settlement_name": b["settlement_name"],
                     "level": b["level"], "offers": offers})
    ways.sort(key=lambda w: ((w["offers"][0]["cost"] is None,
                              w["offers"][0]["cost"] or 0) if w["offers"]
                             else (True, 0)))
    seen = set()
    for w in ways:
        for o in w["offers"]:
            for i in o["inputs"]:
                seen.add(i["id"])
    store.request(seen | {iid})  # непосчитанное — воркеру вне очереди
    chain, chain_idx = _chain(iid)  # полная лестница тиров (та же категория)
    p = store.get(iid)
    return {
        "item": _brief(iid),
        "buy_price": craft.unit_buy_price(iid) if p["available"] else None,
        **_sell_side(iid),
        "ways": ways,
        "chain": chain,
        "chain_idx": chain_idx,
        "used_in": [_brief(rid) for rid in db.barter_used_in.get(iid, [])],
    }
