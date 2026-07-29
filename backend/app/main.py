"""StalZone Craft Helper — точка входа FastAPI.

Backend авторитетен: отдаёт данные и считает выгоду. Frontend только рисует.
Сервис самодостаточен: сам раздаёт фронт и иконки, поэтому за nginx его можно
повесить на любой префикс (напр. /mvp) простым proxy_pass.
"""
import asyncio
import logging
import mimetypes

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import (chat, craft_tuning, guides, loader, mapobjects, market, news,
                    operations, promos, quests, users)
from app.db.index import db
from app.routers.api import router as api_router
from app.routers.auth import router as auth_router
from app.routers.pages import router as pages_router
from app.services import exchange, fuel, oauth
from app.services.artefact_lots import artlots
from app.services.artefact_watch import artwatch
from app.services.ingredient_watch import watch
from app.services.market_scan import scan
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
    users.init()
    chat.init()
    market.init()
    news.init()
    mapobjects.init()
    guides.init()
    quests.init()
    promos.init()
    operations.init()
    craft_tuning.init()
    db.load()
    store.load()
    # цены: крафт-граф + бартер-граф; история продаж — результаты обоих
    store.set_base(sorted(set(db.priceable_ids()) | db.barter_item_ids()))
    store.set_results(sorted(set(db.recipe_by_result) | set(db.barter_by_result)))
    fuel.warm()   # цены и история продаж топлива генератора — в ротацию воркера
    exchange.load()  # обменки Перекупщика (ручной JSON) — предметы в ротацию цен
    scan.seed()   # ДЕВ-сканер выгодных лотов: настройки + посев из кэшей цен
    rankings.load()
    watch.load()
    oauth.load()  # кэшированный app-токен (если работаем по клиентским кредам)
    auth_mode = ("oauth" if oauth.enabled()
                 else "static" if config.API_TOKEN else "MISSING")
    logger.info("API base=%s region=%s auth=%s | priceable=%d cached=%d",
                config.API_BASE, config.REGION, auth_mode,
                len(store.base), len(store.prices))
    if config.PRICE_REFRESH_ENABLED:
        asyncio.create_task(store.refresh_loop())  # фоновое обновление цен
        asyncio.create_task(watch.loop())          # биржа ингредиентов (2 раза/сутки)
        asyncio.create_task(scan.sweep_loop())     # ДЕВ-сканер: снятие протухших сделок
    if config.ART_WATCH_ENABLED:
        asyncio.create_task(artwatch.loop())       # биржа артефактов (корзины qlt×ptn)
    if config.ART_LOTS_ENABLED:
        asyncio.create_task(artlots.loop())        # живые лоты (цены сборок первой недели)
    if config.EMISSION_WATCH_ENABLED:
        from app.services.emission_watch import ewatch
        asyncio.create_task(ewatch.loop())         # история выбросов для дашборда
    if config.SALES_STATS_ENABLED:
        from app.services.sales_stats import sstats
        asyncio.create_task(sstats.loop())         # снапшоты продаж (топ за неделю)
    if config.PATCH_WATCH_ENABLED:
        from app.services.patch_watch import pwatch
        asyncio.create_task(pwatch.loop())         # патчноуты с форума EXBO
    if config.OPS_WATCH_ENABLED:
        from app.services.operations_watch import opswatch
        asyncio.create_task(opswatch.loop())       # сессии PvE-режима «Операции»


# API и SSR-страницы — ДО статики, чтобы не перекрылись catch-all маунтом.
# pages отдаёт index.html с мета-тегами для SPA-путей (/item/{id}, /auction, …)
# и генерит /sitemap.xml; статика (app.js, styles.css, иконки) — маунтом ниже.
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(pages_router)

# Иконки-зеркало и фронт. html=True отдаёт index.html на корне.
# Каталог иконок на первом старте пуст (данные скачает startup-событие в volume),
# поэтому создаём его заранее и монтируем безусловно — StaticFiles отдаёт
# файлы, которые появятся позже (проверка существования — только на mount).
# .webp и .woff2 регистрируем явно: на части ОС mimetypes их не знает и отдаёт
# text/plain — вебп не покажется, а шрифт браузер вообще отвергнет.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
config.ICONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/icons", StaticFiles(directory=str(config.ICONS_DIR)), name="icons")
# зеркало картинок патчноутов (заполняет patch_watch в volume)
config.NEWS_IMG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/news-img", StaticFiles(directory=str(config.NEWS_IMG_DIR)), name="news_img")
# картинки гайдов, загруженные админом (в volume) — префикс НЕ конфликтует с /guides/{slug}
config.GUIDE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/guide-uploads", StaticFiles(directory=str(config.GUIDE_UPLOADS_DIR)), name="guide_uploads")
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
