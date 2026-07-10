"""Расчёт дерева крафта и вердикта «выгодно ли крафтить».

Цены берём из PriceStore (тёплый кэш, обновляется фоном) — БЕЗ обращений к API
в запросе. Поэтому расчёт синхронный и быстрый даже для больших деревьев.

    obtain(item) = min( купить на ауке , по каждому варианту рецепта: craft(R) )
    craft(R)     = Σ obtain(ingredient) × amount / result_amount

Перебирает все варианты рецепта (дешёвый — выбранный, остальные — альтернативы),
мемоизирует общие поддеревья, рвёт циклы, обрезается по глубине.
"""
from app import config
from app.db.index import db
from app.services.price_store import store


def _result_amount(recipe: dict, item_id: str) -> int:
    for r in recipe.get("result", []):
        if r.get("item") == item_id:
            return r.get("amount") or 1
    return 1


def _item_info(item_id: str) -> dict:
    it = db.item(item_id)
    return {
        "id": item_id,
        "name": it["name"] if it else item_id,
        "icon": it["icon"] if it else "",
        "status": it["status"] if it else None,
    }


def _price(item_id: str, path: tuple, ctx: dict, depth: int, expand: bool) -> dict:
    """Узел с ценой получения 1 штуки предмета (цены из PriceStore, без сети)."""
    ctx["seen"].add(item_id)
    cyclic = item_id in path
    too_deep = depth >= config.CRAFT_MAX_DEPTH
    memo_key = (item_id, expand)
    if not cyclic and not too_deep and memo_key in ctx["memo"]:
        return ctx["memo"][memo_key]

    node = _item_info(item_id)
    mk = store.get(item_id)
    node["market_price"] = mk["min_buyout"] if mk["available"] else None
    node["price_known"] = mk["known"]        # False = цена ещё не посчитана фоном

    variants = db.recipes_for(item_id)
    node["craftable"] = bool(variants)
    node["n_variants"] = len(variants)
    node["craft_cost"] = None
    node["recipe"] = None
    node["alternatives"] = []
    variants = variants[:config.CRAFT_MAX_VARIANTS]

    if not variants or cyclic or too_deep:
        node["best_cost"] = node["market_price"]
        node["best_source"] = "market" if node["market_price"] is not None else None
        node["note"] = "cycle" if cyclic else ("depth" if too_deep else None)
        return node

    child_path = path + (item_id,)
    evaluated = []
    for idx, r in enumerate(variants):
        ramount = _result_amount(r, item_id)
        ings, total, known = [], 0.0, True
        for ing in r.get("ingredients", []):
            cid, amt = ing["item"], ing.get("amount", 1)
            child = _price(cid, child_path, ctx, depth + 1, expand=False)
            cbest = child.get("best_cost")
            if cbest is None:
                known = False
                line = None
            else:
                line = cbest * amt
                total += line
            ings.append({"amount": amt, "line_cost": round(line) if line is not None else None,
                         "node": child})
        recipe_cost = round(total / ramount) if known else None
        evaluated.append((
            recipe_cost if recipe_cost is not None else float("inf"),
            known,
            {"variant": idx + 1, "category": r.get("category"),
             "subcategory": r.get("subcategory"), "bench": r.get("bench"),
             "result_amount": ramount, "energy": r.get("energy"),
             "recipe_cost": recipe_cost, "cost_known": known, "ingredients": ings},
        ))

    evaluated.sort(key=lambda e: e[0])
    known_variants = [e for e in evaluated if e[1]]
    chosen = known_variants[0][2] if known_variants else None
    node["craft_cost"] = chosen["recipe_cost"] if chosen else None

    cands = [c for c in (node["market_price"], node["craft_cost"]) if c is not None]
    node["best_cost"] = min(cands) if cands else None
    if node["best_cost"] is None:
        node["best_source"] = None
    elif node["craft_cost"] is not None and node["best_cost"] == node["craft_cost"]:
        node["best_source"] = "craft"
    else:
        node["best_source"] = "market"

    if chosen and (expand or node["best_source"] == "craft"):
        node["recipe"] = chosen
        node["alternatives"] = [_summ(e[2]) for e in evaluated if e[2] is not chosen][:5]
    elif chosen:
        node["alternatives"] = [_summ(e[2]) for e in evaluated][:5]

    ctx["memo"][memo_key] = node
    return node


def _summ(recipe: dict) -> dict:
    return {
        "variant": recipe["variant"], "recipe_cost": recipe["recipe_cost"],
        "cost_known": recipe["cost_known"], "result_amount": recipe["result_amount"],
        "ingredients": [{"name": i["node"]["name"], "id": i["node"]["id"],
                         "icon": i["node"]["icon"], "amount": i["amount"],
                         "unit_price": i["node"].get("best_cost")} for i in recipe["ingredients"]],
    }


def analyze(item_id: str) -> dict:
    """Полный ответ /api/craft: предмет, дерево крафта, цена готового и вердикт."""
    ctx = {"memo": {}, "seen": set()}
    tree = _price(item_id, tuple(), ctx, 0, expand=True)
    store.request(ctx["seen"])  # приоритетно обновить цены встреченных предметов

    buy_price = tree.get("market_price")
    craft_cost = tree.get("craft_cost")
    return {
        "item": _item_info(item_id),
        "craftable": tree.get("craftable", False),
        "buy_price": buy_price,
        "buy_available": buy_price is not None,
        "craft_cost": craft_cost,
        "tree": tree,
        "verdict": _verdict(tree, buy_price, craft_cost),
    }


def _verdict(tree: dict, buy_price, craft_cost) -> dict:
    if not tree.get("craftable"):
        return {"status": "not_craftable", "text": "Не крафтится"}
    if craft_cost is None:
        return {"status": "unknown", "text": "Цены части ингредиентов ещё считаются"}
    if buy_price is None:
        return {"status": "no_market", "text": "Готового нет на ауке — не с чем сравнить",
                "craft_cost": craft_cost}
    diff = buy_price - craft_cost
    pct = round(diff / buy_price * 100) if buy_price else 0
    profitable = diff > 0
    return {
        "status": "profitable" if profitable else "unprofitable",
        "text": f"{'ВЫГОДНО' if profitable else 'НЕВЫГОДНО'} {pct:+d}%",
        "craft_cost": craft_cost, "buy_price": buy_price, "diff": round(diff), "pct": pct,
    }
