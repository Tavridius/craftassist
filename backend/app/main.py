"""StalZone Craft Helper — точка входа FastAPI.

Backend авторитетен: отдаёт данные и считает выгоду. Frontend только рисует.
Сервис самодостаточен: сам раздаёт фронт и иконки, поэтому за nginx его можно
повесить на любой префикс (напр. /mvp) простым proxy_pass.
"""
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import loader
from app.db.index import db
from app.routers.api import router as api_router
from app.services import oauth
from app.services.price_store import store
from app.services.rankings import rankings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="StalZone Craft Helper")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    loader.ensure_data()
    db.load()
    store.load()
    store.set_base(db.priceable_ids())
    store.set_results(sorted(set(db.recipe_by_result) | set(db.barter_by_result)))
    rankings.load()
    oauth.load()  # кэшированный app-токен (если работаем по клиентским кредам)
    auth_mode = ("oauth" if oauth.enabled()
                 else "static" if config.API_TOKEN else "MISSING")
    logger.info("API base=%s region=%s auth=%s | priceable=%d cached=%d",
                config.API_BASE, config.REGION, auth_mode,
                len(store.base), len(store.prices))
    if config.PRICE_REFRESH_ENABLED:
        asyncio.create_task(store.refresh_loop())  # фоновое обновление цен


# API — регистрируем ДО статики, чтобы не перекрылось catch-all маунтом
app.include_router(api_router)

# Иконки-зеркало и фронт. html=True отдаёт index.html на корне.
# Каталог иконок на первом старте пуст (данные скачает startup-событие в volume),
# поэтому создаём его заранее и монтируем безусловно — StaticFiles отдаёт
# файлы, которые появятся позже (проверка существования — только на mount).
config.ICONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/icons", StaticFiles(directory=str(config.ICONS_DIR)), name="icons")
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
