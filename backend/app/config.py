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

# --- Расчёт дерева крафта ---
# На демо-API (лимит ~2 запроса/с) глубина×ветвление = долгий холодный запрос.
# С prod-токеном лимиты выше — можно поднять глубину/варианты через env.
CRAFT_MAX_DEPTH = int(os.getenv("CRAFT_MAX_DEPTH", "4"))      # глубина рекурсии
CRAFT_MAX_VARIANTS = int(os.getenv("CRAFT_MAX_VARIANTS", "3"))  # сколько вариантов рецепта оценивать
