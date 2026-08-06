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
# y3nmw — Продвинутые запчасти: топ-1 аука по темпу продаж (вместо Батарейки).
WATCH_IDS = [s.strip() for s in os.getenv(
    "WATCH_IDS", "7l127,9mmq,g00n,404p,y7po,y3nmw").split(",") if s.strip()]
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
# Отсечка выбросов, ДВА механизма (см. artefact_watch.finalize_buckets):
#
# 1) Основной — коридор вокруг УСТОЯВШЕЙСЯ цены корзины (медиана медиан слотов
#    за ART_REF_DAYS, нужно минимум ART_REF_MIN_SLOTS слотов). Сделки вне
#    [ref/F, ref×F] в агрегаты не берём. Именно это ловит разовые сделки: старая
#    привязка к минимуму ТОГО ЖЕ снапшота при n=1 бесполезна — минимум и есть
#    сама выбросовая сделка (замер 30.07.2026: 384 выброса ≥2× медианы серии на
#    24810 точек, худший — «Репях» n=1, средняя 15.5 млн против медианы 10 185).
# 2) Резервный, когда истории ещё нет (первые замеры) — прежняя привязка к
#    минимуму корзины в снапшоте: ART_OUTLIER_FACTOR × min.
#
# Если ВСЯ выборка слота вне коридора — это либо реальный сдвиг цены (патч, смена
# меты), либо перевод валюты через аук. Отличаем по ДВУМ признакам сразу, объёма
# одного мало: перевод легко делают в 4-20 сделок (наблюдали «Комету» ×104 при
# n=4). Принимаем новый уровень, только если сделок >= ART_SHIFT_MIN_SALES И
# отклонение меньше ART_SHIFT_MAX_FACTOR. Дороже — не пишем слот вовсе: скачок
# ×10 за один слот у устоявшейся корзины рынком не бывает.
#
# Про заморозку: если цена реально ушла больше чем ×10, корзина замолчит, но не
# навсегда — старые слоты через ART_REF_DAYS выпадут из окна опоры, ref станет
# недоступна, сработает резервный механизм и новый уровень запишется. То есть
# самовосстановление максимум за неделю.
ART_OUTLIER_FACTOR = float(os.getenv("ART_OUTLIER_FACTOR", "6"))
ART_SPIKE_FACTOR = float(os.getenv("ART_SPIKE_FACTOR", "4"))     # ширина коридора вокруг ref
ART_REF_DAYS = int(os.getenv("ART_REF_DAYS", "7"))               # окно истории для ref
ART_REF_MIN_SLOTS = int(os.getenv("ART_REF_MIN_SLOTS", "3"))     # мин. слотов, чтобы верить ref
ART_SHIFT_MIN_SALES = int(os.getenv("ART_SHIFT_MIN_SALES", "4"))    # сделок, чтобы принять сдвиг
ART_SHIFT_MAX_FACTOR = float(os.getenv("ART_SHIFT_MAX_FACTOR", "10"))  # выше — не сдвиг, а перевод

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
# «Тактический резерв» (реестр в клиенте: lootbox.summer26, сезон «Антициклон») —
# сезонный лутбокс. EXBO НЕ выгружает сезонные ящики в автогенерируемую базу
# предметов, поэтому его короткого web-API-id (типа n4np3) нет ни в репозитории,
# ни в файлах клиента — id присваивает сервер. НО eapi отдаёт аук и по id,
# которых нет в базе (issue #23 репо stalcraft-database: ~15k «скрытых» id),
# значит наш ящик, скорее всего, ТОЖЕ пробивается по ауку — просто сам id
# неизвестен. Достать id: перебор аук-API (алфавит 24 симв. 012345679dgjklmnopqrvwyz,
# 4–5 знаков) + опознание по иконке, либо дождаться добавления в базу у ТП EXBO
# (запрошено). Когда id найдём — задать DASH_BOX_ID и вернуть price-логику в
# /box (см. git history).
DASH_BOX_NAME = os.getenv("DASH_BOX_NAME", "Тактический резерв")

# --- Полный аукцион (живые лоты/история по запросу, кэш) ---
MARKET_CACHE_SEC = int(os.getenv("MARKET_CACHE_SEC", "90"))

# --- ДЕВ-сканер выгодных лотов (/dev/scan, services/market_scan.py) ---
# Дефолты порогов; рабочие значения админ меняет с UI на лету (scan_settings.json).
SCAN_ENABLED = os.getenv("SCAN_ENABLED", "1") not in ("0", "false", "False")
SCAN_MIN_SPH = float(os.getenv("SCAN_MIN_SPH", "10"))          # мин. продаж/час
# Броня/оружие/обвесы продаются штучно (десятки продаж в СУТКИ), но дорого —
# под общий порог ликвидности они не проходят, поэтому порог отдельный.
SCAN_MIN_SPH_GEAR = float(os.getenv("SCAN_MIN_SPH_GEAR", "0.5"))
SCAN_DISCOUNT_PCT = float(os.getenv("SCAN_DISCOUNT_PCT", "10"))  # лот дешевле средней на ≥ %
SCAN_AVG_N = int(os.getenv("SCAN_AVG_N", "5"))                 # средняя из последних N продаж
SCAN_MIN_MARGIN = float(os.getenv("SCAN_MIN_MARGIN", "0"))     # мин. маржа ₽/шт после комиссии
# Актуальность: лот, снятый давно, скорее всего уже выкуплен — такие сделки не
# показываем. Всё, что может стать сделкой, лежит в горячем круге (~2 мин),
# поэтому даже жёсткий порог не «моргает» карточками.
SCAN_MAX_AGE_MIN = float(os.getenv("SCAN_MAX_AGE_MIN", "15"))
# Артефакты в выдаче сканера. Выключить = не только скрыть карточки, но и убрать
# арты из обхода цен (их нет в крафт-графе, они там только ради сканера).
SCAN_SHOW_ARTEFACTS = os.getenv("SCAN_SHOW_ARTEFACTS", "1") not in ("0", "false", "False")
# История продаж по всем предметам графа (иначе — только крафт-результаты и
# открывавшиеся карточки). Даёт сканеру полное покрытие.
SCAN_HIST_ALL = os.getenv("SCAN_HIST_ALL", "1") not in ("0", "false", "False")
# Бюджет запросов к ауку фиксирован (~160/мин), поэтому важно КАК он поделён:
# 1) история предмета перечитывается не каждый круг, а раз в SCAN_HIST_TTL_MIN
#    (темп продаж и средняя меняются медленно). Для сверхликвидных интервал
#    сокращается сам — чтобы окно /history (100 продаж) не вытеснило сделки
#    до следующего замера и в годовом графике sales_log не появились дыры;
# 2) лоты ликвидных предметов (только они могут стать сделкой) снимаются
#    отдельным быстрым кругом: SCAN_HOT_RATIO горячих замеров на один холодный.
SCAN_HIST_TTL_MIN = int(os.getenv("SCAN_HIST_TTL_MIN", "45"))
SCAN_HOT_RATIO = float(os.getenv("SCAN_HOT_RATIO", "1.5"))
SCAN_HOT_MAX = int(os.getenv("SCAN_HOT_MAX", "400"))  # потолок горячего списка

# --- Годовая история продаж предметов (график в карточке полного аука) ---
# Пассивный сбор: каждый ответ /auction/{id}/history агрегируется по часовым
# слотам МСК в market.db (services/sales_log.py). Часы храним окно, старше —
# роллап в дневные агрегаты; дни живут год.
ITEM_SALES_HOURLY_DAYS = int(os.getenv("ITEM_SALES_HOURLY_DAYS", "35"))
ITEM_SALES_KEEP_DAYS = int(os.getenv("ITEM_SALES_KEEP_DAYS", "365"))

# --- Операции (PvE-режим): история сессий + мета снаряжения ---
# eapi отдаёт GET /{region}/operations/sessions — список проведённых забегов с
# участниками, их снаряжением (броня/оружие + заточка) и статами (K/D, урон).
# Нужен app-токен (как у аука); demo-API эндпоинт НЕ реализует (404) — данные
# копятся только на проде. Воркер (services/operations_watch.py) тянет свежие
# сессии в data/operations.db, страница /operations читает готовые агрегаты.
OPS_WATCH_ENABLED = os.getenv("OPS_WATCH_ENABLED", "1") not in ("0", "false", "False")
OPS_POLL_MIN = int(os.getenv("OPS_POLL_MIN", "10"))       # период опроса сессий, мин
OPS_PAGE_LIMIT = int(os.getenv("OPS_PAGE_LIMIT", "100"))  # сессий за страницу (API max 100)
OPS_MAX_PAGES = int(os.getenv("OPS_MAX_PAGES", "5"))      # страниц за опрос (догон новых сессий)
OPS_KEEP_DAYS = int(os.getenv("OPS_KEEP_DAYS", "45"))     # ретенция сессий, дней
# Мета (снаряжение и время прохождения) — ЕЖЕНЕДЕЛЬНАЯ: считается по забегам с
# последнего сброса. Сброс по средам (день/час настраиваются, МСК): в среду в
# OPS_WEEK_RESET_HOUR окно обнуляется и мета набирается заново за новую неделю.
# История (лента забегов) при этом остаётся полной (ретенция OPS_KEEP_DAYS).
OPS_WEEK_RESET_DOW = int(os.getenv("OPS_WEEK_RESET_DOW", "2"))    # 0=Пн … 2=Ср … 6=Вс
OPS_WEEK_RESET_HOUR = int(os.getenv("OPS_WEEK_RESET_HOUR", "0"))  # час сброса, МСК
# Мин. выборка, чтобы не показывать случайные комбо/предметы в мете.
OPS_MIN_SAMPLE = int(os.getenv("OPS_MIN_SAMPLE", "8"))
# Три этапа сложности (порог = верхняя граница ВКЛючительно): низкий 0-N,
# средний (N+1)-M, высокий M+1 и выше. По умолчанию 0-15 / 16-29 / 30+
# (запрос юзера «0-15, 10-29, 30+» — перекрытие 10-15 разрешено в пользу
# непересекающихся корзин; меняется env без перекатки).
OPS_TIER_LOW_MAX = int(os.getenv("OPS_TIER_LOW_MAX", "15"))
OPS_TIER_MID_MAX = int(os.getenv("OPS_TIER_MID_MAX", "29"))

# --- SEO: постепенная индексация страниц предметов ---
# Не вываливаем все ~2300 /item/{id} в sitemap разом (риск фильтров за малоценный
# контент на молодом домене). Отдаём растущую пачку: каждый день +SEO_ITEMS_PER_DAY
# приоритетных предметов (по редкости/крафту/типу), пока не раскроется вся база.
# 50/день (≈46 дней на всю базу) — оставляем краул-бюджет на другие новые страницы
SEO_ITEMS_PER_DAY = int(os.getenv("SEO_ITEMS_PER_DAY", "50"))
SEO_ITEMS_START = os.getenv("SEO_ITEMS_START", "2026-07-23")  # дата старта раскрутки

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

# --- Реклама РСЯ ---
# Пустой RSYA_BLOCK_ID = рекламы нет вообще (скрипт Яндекса не грузится) — это
# состояние по умолчанию, деплой без переменной ничего не меняет. Заполнить
# идентификатором блока из интерфейса РСЯ (вид «R-A-1234567-1») и перезапустить.
# Блок показывается ТОЛЬКО на контентных страницах (/guides/*, /patches/*):
# калькуляторы — ядро продукта, там реклама бьёт по возвратам и по метрикам,
# которые чинили в июле-августе.
RSYA_BLOCK_ID = os.getenv("RSYA_BLOCK_ID", "").strip()
# Второй блок — под контентом раздела (списки, калькуляторы, карточки предметов).
# Отдельный идентификатор, а не тот же: два одновременных показа одного блока на
# странице РСЯ считает некорректно, и статистика по местам не разделится.
RSYA_BLOCK_BOTTOM = os.getenv("RSYA_BLOCK_BOTTOM", "").strip()

# --- Расчёт дерева крафта ---
# На демо-API (лимит ~2 запроса/с) глубина×ветвление = долгий холодный запрос.
# С prod-токеном лимиты выше — можно поднять глубину/варианты через env.
CRAFT_MAX_DEPTH = int(os.getenv("CRAFT_MAX_DEPTH", "4"))      # глубина рекурсии
CRAFT_MAX_VARIANTS = int(os.getenv("CRAFT_MAX_VARIANTS", "3"))  # сколько вариантов рецепта оценивать
