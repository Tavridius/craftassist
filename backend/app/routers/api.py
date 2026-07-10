"""HTTP API: поиск, инфо о предмете, цена, расчёт крафта, рейтинги.

Все данные — из тёплых кэшей (GameDB + PriceStore); запросы пользователей
НЕ обращаются к внешнему API, поэтому отвечают мгновенно при любом трафике.
"""
from fastapi import APIRouter, HTTPException, Query

from app import config
from app.db.index import db
from app.services import craft, oauth
from app.services.price_store import store
from app.services.rankings import rankings

router = APIRouter(prefix="/api")


@router.get("/search")
async def search(q: str = Query(..., min_length=1), limit: int = 30):
    return {"query": q, "results": db.search(q, limit)}


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
async def craft_analyze(item_id: str):
    res = craft.analyze(item_id)
    if res.get("craftable"):
        rankings.bump(item_id)  # статистика популярности
    return res


@router.get("/top")
async def top():
    return rankings.compute()


@router.get("/health")
async def health():
    return {"status": "ok", "items": len(db.items),
            "craft_results": len(db.recipe_by_result),
            "region": config.REGION,
            "demo": "dapi." in config.API_BASE,
            "token": bool(oauth.token() or config.API_TOKEN),
            "prices": store.stats()}
