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

# --- Источник игровой БД (рецепты, предметы, иконки) ---
DB_REPO_ZIP = os.getenv(
    "DB_REPO_ZIP",
    "https://codeload.github.com/EXBO-Studio/stalzone-database/zip/refs/heads/main",
)
DB_LANG = os.getenv("DB_LANG", "ru")  # ветка данных в репо: ru / global

# --- Троттлинг аукциона (единственный источник вызовов API — фоновый воркер) ---
AUCTION_LOTS_LIMIT = int(os.getenv("AUCTION_LOTS_LIMIT", "20"))
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
    "WATCH_IDS", "7l127,9mmq,g00n,404p,y7po").split(",") if s.strip()]
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

# --- Расчёт дерева крафта ---
# На демо-API (лимит ~2 запроса/с) глубина×ветвление = долгий холодный запрос.
# С prod-токеном лимиты выше — можно поднять глубину/варианты через env.
CRAFT_MAX_DEPTH = int(os.getenv("CRAFT_MAX_DEPTH", "4"))      # глубина рекурсии
CRAFT_MAX_VARIANTS = int(os.getenv("CRAFT_MAX_VARIANTS", "3"))  # сколько вариантов рецепта оценивать
