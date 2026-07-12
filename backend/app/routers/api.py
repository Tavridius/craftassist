"""HTTP API: поиск, инфо о предмете, цена, расчёт крафта, рейтинги.

Все данные — из тёплых кэшей (GameDB + PriceStore); запросы пользователей
НЕ обращаются к внешнему API, поэтому отвечают мгновенно при любом трафике.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, HTTPException, Query, Request

from app import config
from app.db import market, users
from app.db.index import db
from app.routers.auth import current_user
from app.services import builds, craft, hideout, oauth
from app.services.artefact_lots import artlots
from app.services.artefact_watch import MSK
from app.services.ingredient_watch import watch
from app.services.price_store import store
from app.services.rankings import rankings

router = APIRouter(prefix="/api")


def _profile_of(request: Request) -> dict | None:
    """Профиль убежища текущего пользователя (None — не авторизован)."""
    user = current_user(request)
    return users.get_profile(user["id"]) if user else None


@router.get("/search")
async def search(request: Request, q: str = Query(..., min_length=1),
                 limit: int = 30, available: int = 0):
    if not available:
        return {"query": q, "results": db.search(q, limit)}
    # фильтр «доступные рецепты»: только крафтящееся, на что хватает прокачки.
    # Ищем с запасом — часть результатов отсеется профилем.
    prof = _profile_of(request)
    if prof is None:
        return {"query": q, "results": db.search(q, limit)}
    results = [it for it in db.search(q, limit * 4)
               if it["id"] in db.recipe_by_result and hideout.item_available(it["id"], prof)]
    return {"query": q, "results": results[:limit], "available_only": True}


@router.get("/item/{item_id}")
async def item(item_id: str):
    it = db.item(item_id)
    if not it:
        raise HTTPException(404, "item not found")
    recipes = db.recipes_for(item_id)
    return {"item": it, "craftable": bool(recipes), "recipes": recipes}


@router.get("/price/{item_id}")
async def price(item_id: str):
    p = store.get(item_id)
    store.request([item_id])  # неизвестный — воркер посчитает приоритетно
    return {"item_id": item_id, **p}


@router.get("/craft/{item_id}")
async def craft_analyze(item_id: str, request: Request):
    res = craft.analyze(item_id)
    if res.get("craftable"):
        rankings.bump(item_id)  # статистика популярности
        prof = _profile_of(request)
        if prof is not None:
            chosen = (res.get("tree") or {}).get("recipe")
            if chosen:
                res["req_check"] = hideout.check(chosen.get("requirements") or {}, prof)
            res["available"] = hideout.item_available(item_id, prof)
    return res


@router.get("/top")
async def top(request: Request, available: int = 0):
    data = rankings.compute()
    if available:
        prof = _profile_of(request)
        if prof is not None:
            def ok(r):
                return hideout.item_available(r["id"], prof)
            data = {**data, "available_only": True,
                    "popular": [r for r in data["popular"] if ok(r)],
                    "profitable": [r for r in data["profitable"] if ok(r)],
                    "liquid": [r for r in data["liquid"] if ok(r)]}
    return data


@router.get("/hideout")
async def hideout_dict():
    """Справочник для страницы профиля: перки и все станки/фичи из рецептов."""
    return {"perks": db.hideout_perks, "features": db.hideout_features,
            "feature_icons": db.hideout_feature_icons,
            "perk_max": hideout.PERK_MAX}


@router.get("/profile")
async def get_profile(request: Request):
    prof = _profile_of(request)
    if prof is None:
        raise HTTPException(401, "не авторизован")
    return prof


@router.put("/profile")
async def put_profile(request: Request, payload: dict = Body(...)):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "не авторизован")
    prof = hideout.validate_profile(payload)
    users.save_profile(user["id"], prof)
    return prof


@router.get("/watch")
async def watch_prices():
    """Биржа ингредиентов: серии средних цен (замеры по расписанию, 2 раза/сутки)."""
    items = []
    for iid in config.WATCH_IDS:
        it = db.item(iid) or {}
        s = watch.series.get(iid, [])
        latest = s[-1] if s else {}
        prev = s[-2] if len(s) > 1 else {}
        delta_pct = None
        if latest.get("avg") and prev.get("avg"):
            delta_pct = round((latest["avg"] - prev["avg"]) / prev["avg"] * 100, 1)
        items.append({
            "id": iid,
            "name": it.get("name", iid),
            "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"),
            "avg": latest.get("avg"),
            "min_buyout": latest.get("min_buyout"),
            "sales_per_hour": latest.get("sales_per_hour"),
            "delta_pct": delta_pct,
            "series": [{"slot": e.get("slot"), "avg": e.get("avg")} for e in s],
        })
    return {"hours": config.WATCH_HOURS, "last_slot": watch.last_slot, "items": items}


# ---------- биржа артефактов: корзины качество(qlt)×заточка(ptn) ----------

def _slot_ago(**delta) -> str:
    """Слот-ключ 'now - delta' по МСК — для окон агрегатов."""
    return (datetime.now(MSK) - timedelta(**delta)).strftime("%Y-%m-%dT%H:00")


@router.get("/artmarket/top")
async def artmarket_top(window: str = "7d", qlt: int = -1, ptn: int = -1):
    """Топ роста/падения средней цены по корзинам артефактов.

    window=7d: неделя против предыдущей недели; 24h: сутки против недели до них.
    qlt/ptn = -1 — любые. Корзины с < ART_MIN_SALES продаж в любом окне не участвуют.
    """
    if window == "24h":
        cur_since, prev_since = _slot_ago(days=1), _slot_ago(days=8)
    else:
        window = "7d"
        cur_since, prev_since = _slot_ago(days=7), _slot_ago(days=14)
    cur = {(r["item"], r["qlt"], r["ptn"]): r for r in market.window_avgs(cur_since)}
    prev = {(r["item"], r["qlt"], r["ptn"]): r
            for r in market.window_avgs(prev_since, cur_since)}

    rows = []
    for key, c in cur.items():
        p = prev.get(key)
        if not p or c["n"] < config.ART_MIN_SALES or p["n"] < config.ART_MIN_SALES:
            continue
        if (qlt >= 0 and key[1] != qlt) or (ptn >= 0 and key[2] != ptn):
            continue
        it = db.item(key[0]) or {}
        rows.append({
            "id": key[0], "name": it.get("name", key[0]), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"), "qlt": key[1], "ptn": key[2],
            "avg": round(c["avg"]), "prev_avg": round(p["avg"]),
            "pct": round((c["avg"] - p["avg"]) / p["avg"] * 100, 1), "n": c["n"],
        })
    rows.sort(key=lambda r: r["pct"], reverse=True)
    m = market.stats()
    return {"window": window, "min_sales": config.ART_MIN_SALES,
            "up": [r for r in rows if r["pct"] > 0][:20],
            "down": sorted((r for r in rows if r["pct"] < 0), key=lambda r: r["pct"])[:20],
            "buckets_ranked": len(rows), "buckets_tracked": len(cur),
            "first_slot": m.get("first_slot"), "last_slot": m.get("last_slot"),
            "hours": config.ART_WATCH_HOURS}


@router.get("/artmarket/{item_id}")
async def artmarket_item(item_id: str):
    """Карточка артефакта на бирже: все корзины с сериями по слотам и avg7d."""
    it = db.item(item_id)
    if not it:
        raise HTTPException(404, "item not found")
    week_since = _slot_ago(days=7)
    buckets: dict[tuple[int, int], dict] = {}
    for r in market.item_series(item_id):
        b = buckets.setdefault((r["qlt"], r["ptn"]), {
            "qlt": r["qlt"], "ptn": r["ptn"], "series": [], "n7": 0, "sum7": 0.0})
        b["series"].append({"slot": r["slot"], "avg": round(r["avg"]), "n": r["n"]})
        if r["slot"] >= week_since:
            b["n7"] += r["n"]
            b["sum7"] += r["avg"] * r["n"]
    # эффективные цены калькулятора (лоты, пока история не созрела) —
    # добавляют и корзины, которых в истории ещё нет
    prices = builds.bucket_prices()
    for (iid, qlt, ptn), p in prices.items():
        if iid == item_id:
            buckets.setdefault((qlt, ptn), {"qlt": qlt, "ptn": ptn, "series": [],
                                            "n7": 0, "sum7": 0.0})
    out = []
    for b in sorted(buckets.values(), key=lambda b: (b["qlt"], b["ptn"])):
        b["avg7d"] = round(b["sum7"] / b["n7"]) if b["n7"] else None
        del b["sum7"]
        b["price"] = prices.get((item_id, b["qlt"], b["ptn"]))
        out.append(b)
    return {"item": it, "buckets": out, "min_sales": config.ART_MIN_SALES,
            "last_slot": market.get_meta("last_slot")}


# ---------- калькулятор сборок ----------

@router.get("/build/dict")
async def build_dictionary():
    """Справочник: контейнеры, каталог статов, артефакты с окнами статов, модель."""
    return builds.build_dict()


@router.post("/build/auto")
async def build_auto(payload: dict = Body(...)):
    """Автоподбор сборки: {budget, container, stats: [{key, weight 0-100}]}."""
    try:
        budget = float(payload.get("budget", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "budget must be a number")
    res = builds.auto_build(budget, str(payload.get("container", "")),
                            payload.get("stats") or [])
    if res.get("error") in ("container_not_found", "bad_request"):
        raise HTTPException(422, res["error"])
    return res  # включая error=no_priced_variants с подсказкой — фронт покажет


@router.post("/build/hp")
async def build_hp(payload: dict = Body(...)):
    """Автоподбор на приведённое ХП: {budget, container, armor, armor_ptn}."""
    try:
        budget = float(payload.get("budget", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "budget must be a number")
    res = builds.auto_hp(budget, str(payload.get("container", "")),
                         str(payload.get("armor", "")), int(payload.get("armor_ptn", 0)))
    if res.get("error") in ("container_not_found", "armor_not_found", "bad_request"):
        raise HTTPException(422, res["error"])
    return res


@router.get("/health")
async def health():
    return {"status": "ok", "items": len(db.items),
            "craft_results": len(db.recipe_by_result),
            "region": config.REGION,
            "demo": "dapi." in config.API_BASE,
            "token": bool(oauth.token() or config.API_TOKEN),
            "users": users.stats(),
            "prices": store.stats(),
            "artmarket": market.stats(),
            "artlots": artlots.stats()}
