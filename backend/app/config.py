"""Конфигурация StalZone Craft Helper.

Всё настраивается через переменные окружения. Значения по умолчанию рассчитаны
на демо-API (dapi) с публичным токеном из документации — сервис работает "из коробки".
Переключение на реальные цены = задать API_BASE + API_TOKEN на production-значения.
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))  # кэш скачанной БД
ICONS_DIR = DATA_DIR / "icons"                                # зеркало иконок
ITEMS_DIR = DATA_DIR / "items"                                # json-файлы предметов (описания)
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", BACKEND_DIR.parent / "frontend"))

# --- STALZONE auction API ---
# Демо:  https://dapi.stalcraft.net  (фейковые цены, публичный токен)
# Prod:  https://eapi.stalcraft.net  (реальные цены, одобренный app-token)
API_BASE = os.getenv("API_BASE", "https://dapi.stalcraft.net").rstrip("/")
REGION = os.getenv("REGION", "RU").upper()


def _load_token() -> str:
    tok = os.getenv("API_TOKEN", "").strip()
    if tok:
        return tok
    # fallback: демо-токен, сохранённый рядом с бэкендом
    f = BACKEND_DIR / ".demo_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return ""


API_TOKEN = _load_token()

# --- OAuth client-credentials (prod) ---
# Если заданы — бэкенд сам получает app-токен у OAuth-сервера EXBO и обновляет его
# (services/oauth.py). API_TOKEN тогда не нужен (остаётся fallback для демо).
OAUTH_TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "https://exbo.net/oauth/token")
API_CLIENT_ID = os.getenv("API_CLIENT_ID", "").strip()
API_CLIENT_SECRET = os.getenv("API_CLIENT_SECRET", "").strip()

# --- Авторизация пользователей (OAuth 2.0 authorization code через аккаунт EXBO) ---
# Использует те же клиентские креды (API_CLIENT_ID/API_CLIENT_SECRET), что и app-токен.
# PUBLIC_BASE_URL — ВНЕШНИЙ адрес приложения за прокси (напр. https://stalzone-helper.ru/mvp);
# redirect_uri по умолчанию = PUBLIC_BASE_URL + /auth/callback и ДОЛЖЕН быть
# зарегистрирован в настройках приложения на exbo.net. Локально (без прокси)
# PUBLIC_BASE_URL можно не задавать — адрес возьмётся из запроса.
OAUTH_AUTHORIZE_URL = os.getenv("OAUTH_AUTHORIZE_URL", "https://exbo.net/oauth/authorize")
OAUTH_USERINFO_URL = os.getenv("OAUTH_USERINFO_URL", "https://exbo.net/oauth/user")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
OAUTH_REDIRECT_URI = os.getenv(
    "OAUTH_REDIRECT_URI", f"{PUBLIC_BASE_URL}/auth/callback" if PUBLIC_BASE_URL else "")
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))  # срок жизни сессии в куке/БД

# --- Локальная авторизация (email + пароль) ---
# Работает всегда (не требует кред EXBO). EXBO-вход остаётся альтернативой в модале.
PASSWORD_MIN_LEN = int(os.getenv("PASSWORD_MIN_LEN", "8"))
# Локальные админы по email (в дополнение к ADMIN_USER_IDS по exbo_id ниже)
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}

# --- Почта (верификация email + сброс пароля) ---
# Пока SMTP не задан — регистрация работает, аккаунт активен сразу, но письма
# (подтверждение email, сброс пароля) не отправляются. Задать на проде, когда
# поднимем почтовый сервис на домене (см. DEPLOY.md).
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()  # starttls | ssl | none
MAIL_FROM = os.getenv("MAIL_FROM", "").strip()          # напр. noreply@stalzone-helper.ru
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "StalZone Helper")
EMAIL_TOKEN_TTL_HOURS = int(os.getenv("EMAIL_TOKEN_TTL_HOURS", "24"))  # жизнь ссылок verify/reset

# --- Источник игровой БД (рецепты, предметы, иконки) ---
DB_REPO_ZIP = os.getenv(
    "DB_REPO_ZIP",
    "https://codeload.github.com/EXBO-Studio/stalzone-database/zip/refs/heads/main",
)
DB_LANG = os.getenv("DB_LANG", "ru")  # ветка данных в репо: ru / global

# --- Троттлинг аукциона (единственный источник вызовов API — фоновый воркер) ---
# 100 лотов за тот же бюджет лимита (любой limit = 2 единицы) — даёт глубину
# стакана для честной цены закупки партии
AUCTION_LOTS_LIMIT = int(os.getenv("AUCTION_LOTS_LIMIT", "100"))
AUCTION_FEE = float(os.getenv("AUCTION_FEE", "0.05"))  # комиссия аука при продаже
AUCTION_MIN_INTERVAL = float(os.getenv("AUCTION_MIN_INTERVAL", "0.5"))  # сек между запросами (демо держит ~2/с без 429)
AUCTION_MAX_RETRIES = int(os.getenv("AUCTION_MAX_RETRIES", "2"))        # ретраи на 429

# --- Фоновое обновление цен (масштабируемость: нагрузка на API не зависит от трафика) ---
PRICE_REFRESH_ENABLED = os.getenv("PRICE_REFRESH_ENABLED", "1") not in ("0", "false", "False")
PRICE_REFRESH_PAUSE = int(os.getenv("PRICE_REFRESH_PAUSE", "30"))  # пауза между полными циклами, сек
PRICE_STALE_AFTER = int(os.getenv("PRICE_STALE_AFTER", "1800"))    # для UI: считать цену устаревшей, сек

# --- Биржа ингредиентов на главной ---
# Цены снимаются ТОЛЬКО в назначенные часы (МСК) — дважды в сутки, между
# замерами API не дёргается. Показываем среднюю цену продаж из истории аука.
WATCH_IDS = [s.strip() for s in os.getenv(
    "WATCH_IDS", "7l127,9mmq,g00n,404p,y7po,zy32").split(",") if s.strip()]
WATCH_HOURS = sorted({int(h) for h in os.getenv("WATCH_HOURS", "1,11").split(",")})
WATCH_KEEP = int(os.getenv("WATCH_KEEP", "60"))  # точек в серии (~месяц при 2/сутки)

# --- Биржа артефактов: снапшоты продаж по корзинам качество(qlt)×заточка(ptn) ---
# История продаж каждого артефакта раскладывается по корзинам (item, qlt, ptn)
# в SQLite data/market.db (services/artefact_watch.py). Средняя за неделю
# по корзине устойчива к манипуляциям моментальными лотами.
ART_WATCH_ENABLED = os.getenv("ART_WATCH_ENABLED", "1") not in ("0", "false", "False")
ART_WATCH_HOURS = sorted({int(h) for h in os.getenv("ART_WATCH_HOURS", "1,7,13,19").split(",")})
ART_WATCH_MAX_PAGES = int(os.getenv("ART_WATCH_MAX_PAGES", "3"))  # страниц истории (по 200) на артефакт за снапшот
ART_MIN_SALES = int(os.getenv("ART_MIN_SALES", "5"))   # мин. продаж в окне, чтобы верить средней
ART_KEEP_DAYS = int(os.getenv("ART_KEEP_DAYS", "35"))  # ретенция агрегатов, дней

# --- Живые лоты артефактов (цены сборок до накопления недели истории) ---
ART_LOTS_ENABLED = os.getenv("ART_LOTS_ENABLED", "1") not in ("0", "false", "False")
ART_LOTS_MINUTES = int(os.getenv("ART_LOTS_MINUTES", "30"))    # период цикла обновления лотов
ART_LOTS_MAX_PAGES = int(os.getenv("ART_LOTS_MAX_PAGES", "2"))  # страниц лотов (по 200) на артефакт
ART_LOTS_TOP = int(os.getenv("ART_LOTS_TOP", "5"))  # средняя из N самых дешёвых лотов корзины
# Источник цен калькулятора: auto — лоты, пока история < 7 дней, дальше avg7d;
# lots / avg7d — принудительно.
BUILD_PRICE_SOURCE = os.getenv("BUILD_PRICE_SOURCE", "auto")

# --- Вотчер выбросов (история стартов для дашборда) ---
EMISSION_WATCH_ENABLED = os.getenv("EMISSION_WATCH_ENABLED", "1") not in ("0", "false", "False")
EMISSION_POLL_SEC = int(os.getenv("EMISSION_POLL_SEC", "60"))

# --- Статистика продаж (топ продаваемых: сегодня/неделя) ---
SALES_STATS_ENABLED = os.getenv("SALES_STATS_ENABLED", "1") not in ("0", "false", "False")
SALES_SNAP_HOURS = int(os.getenv("SALES_SNAP_HOURS", "6"))

# --- Актуальный ящик сезона на дашборде ---
# «Тактический резерв» ОТСУТСТВУЕТ в базе EXBO (сезонные ящики туда не попадают) —
# как узнаем item-id, впишем сюда (env или прямо тут), карточка оживёт.
DASH_BOX_ID = os.getenv("DASH_BOX_ID", "")
DASH_BOX_NAME = os.getenv("DASH_BOX_NAME", "Тактический резерв")

# --- Полный аукцион (живые лоты/история по запросу, кэш) ---
MARKET_CACHE_SEC = int(os.getenv("MARKET_CACHE_SEC", "90"))

# --- Годовая история продаж предметов (график в карточке полного аука) ---
# Пассивный сбор: каждый ответ /auction/{id}/history агрегируется по часовым
# слотам МСК в market.db (services/sales_log.py). Часы храним окно, старше —
# роллап в дневные агрегаты; дни живут год.
ITEM_SALES_HOURLY_DAYS = int(os.getenv("ITEM_SALES_HOURLY_DAYS", "35"))
ITEM_SALES_KEEP_DAYS = int(os.getenv("ITEM_SALES_KEEP_DAYS", "365"))

# --- Патчноуты с форума EXBO (forum.exbo.net — Flarum с открытым JSON API) ---
PATCH_WATCH_ENABLED = os.getenv("PATCH_WATCH_ENABLED", "1") not in ("0", "false", "False")
FORUM_API = os.getenv("FORUM_API", "https://forum.exbo.net").rstrip("/")
PATCH_TAG = os.getenv("PATCH_TAG", "news-updates")   # тег «Обновления» (патчноуты)
PATCH_POLL_MIN = int(os.getenv("PATCH_POLL_MIN", "30"))
PATCH_BACKFILL_MAX = int(os.getenv("PATCH_BACKFILL_MAX", "1000"))  # предохранитель бэкфилла
NEWS_IMG_DIR = DATA_DIR / "news_img"                 # зеркало картинок патчноутов

# --- Гайды (авторские статьи; админ-редактор) ---
# Хранилище — SQLite data/guides.db в volume (переживает редеплой). Бандл
# content/guides/*.json+html сидится в БД при старте (insert-if-absent). Картинки,
# загруженные админом, лежат в volume DATA_DIR/guide_uploads и раздаются с /guide-uploads.
GUIDE_UPLOADS_DIR = DATA_DIR / "guide_uploads"
GUIDE_SEED_DIR = BACKEND_DIR / "content" / "guides"
GUIDE_HTML_MAX = int(os.getenv("GUIDE_HTML_MAX", "80000"))     # потолок размера тела гайда
GUIDE_IMG_MAX_MB = float(os.getenv("GUIDE_IMG_MAX_MB", "6"))   # лимит одной картинки

# --- Комментарии под статьями ---
# EXBO user id админов через запятую — могут удалять чужие комментарии
ADMIN_USER_IDS = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}

# --- A/B-тест дизайна (серверный cookie-сплит) ---
# Включён → части посетителей отдаётся вариант B: поверх базовой styles.css
# подключается frontend/styles-b.css («Биржевой терминал»), а на <html>
# ставится data-ab="B". Вариант липкий (cookie AB_TEST_COOKIE, TTL AB_TEST_TTL_DAYS)
# и уходит в Я.Метрику параметром визита ym('params',{ab_design}) — отчёты
# сегментируются по варианту. Боты/краулеры и выключенный тест → всегда A
# (стабильная индексация, без сплита). Выключен по умолчанию — деплой без риска.
AB_TEST_DESIGN = os.getenv("AB_TEST_DESIGN", "0") not in ("0", "false", "False", "")
AB_TEST_COOKIE = os.getenv("AB_TEST_COOKIE", "sz_ab").strip() or "sz_ab"
# доля варианта B, 0..1 (0.5 = поровну)
AB_TEST_SPLIT = min(1.0, max(0.0, float(os.getenv("AB_TEST_SPLIT", "0.5"))))
AB_TEST_TTL_DAYS = int(os.getenv("AB_TEST_TTL_DAYS", "90"))  # срок липкости варианта
# Админский форс-предпросмотр: cookie ставит POST /api/dev/ab (только админ).
# render_index уважает её ВСЕГДА (даже при выключенном тесте) и помечает вариант
# как предпросмотр (в статистику Метрики не идёт).
AB_TEST_FORCE_COOKIE = os.getenv("AB_TEST_FORCE_COOKIE", "sz_ab_force").strip() or "sz_ab_force"

# --- Расчёт дерева крафта ---
# На демо-API (лимит ~2 запроса/с) глубина×ветвление = долгий холодный запрос.
# С prod-токеном лимиты выше — можно поднять глубину/варианты через env.
CRAFT_MAX_DEPTH = int(os.getenv("CRAFT_MAX_DEPTH", "4"))      # глубина рекурсии
CRAFT_MAX_VARIANTS = int(os.getenv("CRAFT_MAX_VARIANTS", "3"))  # сколько вариантов рецепта оценивать
