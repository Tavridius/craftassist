"""SSR-лайт: отдаём index.html с подставленными title/description/canonical
под конкретный маршрут (History API-роутинг фронта).

Фронт — SPA на реальных путях (`/item/{id}`, `/auction`, `/builds`, …). Чтобы
поисковики и превью в мессенджерах видели осмысленные мета-теги для каждого
URL (а не один шаблон главной), сервер подставляет их в <head> перед отдачей.
Сама разметка страницы по-прежнему рисуется на клиенте.

Роуты регистрируются ДО StaticFiles-маунта в main.py; статика (app.js, styles.css,
иконки, robots.txt) отдаётся файлами и сюда не попадает.
"""
import html as _html
import json
import logging
import re
import secrets
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import config
from app.db import guides
from app.db.index import db
from app.services.price_store import store

logger = logging.getLogger(__name__)
router = APIRouter()

SITE = "StalZone Helper"
DEF_TITLE = "Калькулятор крафта STALZONE (Stalcraft) — цены аукциона и выгода"
DEF_DESC = ("Помощник крафта STALZONE (ранее Stalcraft — Сталкрафт): дерево крафта, "
            "живые цены аукциона RU и вердикт — выгодно ли крафтить или дешевле купить. "
            "2000+ предметов, 350+ рецептов верстака.")


@lru_cache(maxsize=1)
def _index_template() -> str:
    return (config.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


def _asset_v(name: str) -> str:
    """Версия статики = mtime файла: браузерный кэш сбрасывается сам при деплое
    (без этого юзеры после обновления сидели на старом app.js — «кнопки не работают»)."""
    try:
        return str(int((config.FRONTEND_DIR / name).stat().st_mtime))
    except OSError:
        return "0"


_V_JS, _V_CSS = _asset_v("app.js"), _asset_v("styles.css")
_V_CSS_B = _asset_v("styles-b.css")

# Краулеры/превью — всегда вариант A (стабильная индексация, чистота эксперимента:
# бот-визиты не должны попадать в сплит и портить статистику вовлечённости).
_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|yandex|google|bing|baidu|duckduck|mail\.ru|"
    r"facebookexternalhit|telegrambot|whatsapp|vkshare|twitterbot|discordbot|"
    r"preview|headless|lighthouse|pingdom|uptime|semrush|ahrefs|petalbot",
    re.I,
)


def _ab_variant(request: Request) -> tuple[str | None, bool, bool]:
    """Вернуть (вариант 'A'|'B'|None, ставить_ли_split_cookie, это_предпросмотр).

    Приоритет — админский форс-предпросмотр (cookie AB_TEST_FORCE_COOKIE): работает
    ВСЕГДА, вне сплита, помечается предпросмотром (не идёт в статистику). Дальше —
    обычный сплит, только если тест включён: бот → 'A'; иначе липкий вариант из
    cookie, при первом визите монетка по AB_TEST_SPLIT + просьба поставить cookie.
    None = тест выключен и форса нет → страница как обычный вариант A (без разметки).
    """
    force = request.cookies.get(config.AB_TEST_FORCE_COOKIE)
    if force in ("A", "B"):
        return force, False, True
    if not config.AB_TEST_DESIGN:
        return None, False, False
    if _BOT_RE.search(request.headers.get("user-agent", "")):
        return "A", False, False
    cur = request.cookies.get(config.AB_TEST_COOKIE)
    if cur in ("A", "B"):
        return cur, False, False
    # secrets.randbelow(10000)/10000 ∈ [0,1) — доля B задаётся AB_TEST_SPLIT
    variant = "B" if secrets.randbelow(10000) < config.AB_TEST_SPLIT * 10000 else "A"
    return variant, True, False


def _base_url(request: Request) -> str:
    return config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def _sub(pattern: str, value: str, s: str) -> str:
    """Подставить значение в первый матч, не трогая спецсимволы value."""
    return re.sub(pattern, lambda _m: value, s, count=1, flags=re.S)


def render_index(request: Request, path: str, *, title: str | None = None,
                 desc: str | None = None, noindex: bool = False,
                 jsonld: dict | None = None, image: str | None = None) -> HTMLResponse:
    title = title or DEF_TITLE
    desc = (desc or DEF_DESC).strip()
    if len(desc) > 300:
        desc = desc[:297].rstrip() + "…"
    url = _base_url(request) + path
    t, d, u = (_html.escape(title, quote=True), _html.escape(desc, quote=True),
               _html.escape(url, quote=True))

    s = _index_template()
    # пути к статике — АБСОЛЮТНЫЕ: относительные ломаются на подпутях
    # (/quests/1 → браузер просил /quests/app.js и получал HTML вместо скрипта)
    s = s.replace('src="app.js"', f'src="/app.js?v={_V_JS}"', 1)
    s = s.replace('href="styles.css"', f'href="/styles.css?v={_V_CSS}"', 1)
    # _sub возвращает value через лямбду (без раскрытия \g<N>) — поэтому пишем полный тег
    s = _sub(r"<title>.*?</title>", f"<title>{t}</title>", s)
    s = _sub(r'<meta name="description" content="[^"]*">',
             f'<meta name="description" content="{d}">', s)
    s = _sub(r'<link rel="canonical" href="[^"]*">',
             f'<link rel="canonical" href="{u}">', s)
    s = _sub(r'<meta property="og:title" content="[^"]*">',
             f'<meta property="og:title" content="{t}">', s)
    s = _sub(r'<meta property="og:description" content="[^"]*">',
             f'<meta property="og:description" content="{d}">', s)
    s = _sub(r'<meta property="og:url" content="[^"]*">',
             f'<meta property="og:url" content="{u}">', s)
    s = _sub(r'<meta name="twitter:title" content="[^"]*">',
             f'<meta name="twitter:title" content="{t}">', s)
    s = _sub(r'<meta name="twitter:description" content="[^"]*">',
             f'<meta name="twitter:description" content="{d}">', s)
    if image:
        # в шаблоне og:image нет — добавляем сами (обложка статьи для превью в
        # мессенджерах/соцсетях) и апаем карточку Twitter до крупной
        img = _html.escape(image if image.startswith("http")
                           else _base_url(request) + "/" + image.lstrip("/"), quote=True)
        s = _sub(r'<meta name="twitter:card" content="[^"]*">',
                 '<meta name="twitter:card" content="summary_large_image">', s)
        s = s.replace("</head>",
                      f'  <meta property="og:image" content="{img}">\n'
                      f'  <meta name="twitter:image" content="{img}">\n</head>', 1)
    if noindex:
        s = s.replace('<meta name="theme-color"',
                      '<meta name="robots" content="noindex,follow">\n  <meta name="theme-color"', 1)
    if jsonld:
        # экранируем </ внутри JSON, чтобы не оборвать <script>
        block = json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        s = s.replace("</head>",
                      f'  <script type="application/ld+json">{block}</script>\n</head>', 1)

    # --- A/B-тест дизайна ---
    variant, set_cookie, preview = _ab_variant(request)
    if variant is not None:
        # маркер на <html> — app.js прочитает и (кроме предпросмотра) отправит
        # вариант в Метрику; заодно даёт CSS-хук html[data-ab="B"] для правок стилей.
        attrs = f' data-ab="{variant}"' + (' data-ab-preview="1"' if preview else '')
        s = s.replace('<html lang="ru">', f'<html lang="ru"{attrs}>', 1)
        if variant == "B":
            # styles-b.css подключается ПОСЛЕ базовой (перед </head>) → выше по
            # каскаду, перекрывает нужное. Файла может не быть (v=0) — тогда B
            # визуально = A, эксперимент безопасен.
            s = s.replace(
                "</head>",
                f'  <link rel="stylesheet" href="/styles-b.css?v={_V_CSS_B}">\n</head>', 1)

    # HTML — точка входа, ссылается на app.js?v=<mtime>: сам НЕ кэшируем, иначе
    # браузер держит старый HTML со старой версией и до нового app.js не доходит
    # (эвристическое кэширование ответов без Cache-Control). no-cache = ревалидация.
    headers = {"Cache-Control": "no-cache, must-revalidate"}
    if variant is not None:  # ответ зависит от cookie (важно, если появится кэш-слой)
        headers["Vary"] = "Cookie"
    resp = HTMLResponse(s, headers=headers)
    if set_cookie:
        resp.set_cookie(
            config.AB_TEST_COOKIE, variant,
            max_age=config.AB_TEST_TTL_DAYS * 86400,
            path="/", httponly=True, samesite="lax",
            secure=str(request.base_url).startswith("https"),
        )
    return resp


def _product_jsonld(request: Request, it: dict, url: str, desc: str) -> dict | None:
    """Product+Offer по живой цене аукциона (мин. выкуп). None — если цены нет,
    чтобы не плодить Product без offers (Google помечает такие как неполные)."""
    p = store.get(it["id"]) or {}
    buyout = p.get("min_buyout")
    if not buyout:
        return None
    icon = it.get("icon")
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": it["name"],
        "sku": it["id"],
        "description": desc,
        "brand": {"@type": "Brand", "name": "STALZONE"},
        "offers": {
            "@type": "Offer",
            "priceCurrency": "RUB",
            "price": str(round(buyout)),
            "availability": ("https://schema.org/InStock" if p.get("available")
                             else "https://schema.org/OutOfStock"),
            "url": url,
            "seller": {"@type": "Organization", "name": "Аукцион STALZONE"},
        },
    }
    if it.get("name_en"):
        data["alternateName"] = it["name_en"]
    if icon:
        data["image"] = _base_url(request) + "/" + icon.lstrip("/")
    return data


# ---------- маршруты фронта ----------

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_index(
        request, "/",
        title="StalZone Helper — крафт, аукцион, сборки и карта STALZONE (Stalcraft)",
        desc="Помощник STALZONE (ранее Stalcraft — Сталкрафт): калькулятор крафта с живыми "
             "ценами аукциона, биржа артефактов, автоподбор сборок под бюджет и карта Зоны.")


@router.get("/craft", response_class=HTMLResponse)
async def craft_page(request: Request):
    # крафтовый тайтл переехал с «/» вместе с разделом (главная стала дашбордом)
    return render_index(request, "/craft")


@router.get("/index.html")
async def index_html():
    return RedirectResponse("/", status_code=301)


@router.get("/vygodno-kraftit", response_class=HTMLResponse)
async def landing_profit(request: Request):
    return render_index(
        request, "/vygodno-kraftit",
        title="Что выгодно крафтить в STALZONE (Stalcraft) сегодня — рейтинг выгоды",
        desc="Живой рейтинг: что выгоднее скрафтить, чем купить на аукционе STALZONE "
             "(ранее Stalcraft — Сталкрафт). Считаем себестоимость крафта по дереву "
             "рецептов против цены готового и показываем маржу в реальном времени.")


@router.get("/item/{item_id}", response_class=HTMLResponse)
async def item_page(request: Request, item_id: str):
    it = db.item(item_id)
    if not it:
        return render_index(request, f"/item/{item_id}",
                            title=f"Предмет не найден — {SITE}", noindex=True)
    name = it["name"]
    craftable = bool(db.recipes_for(item_id))
    parts = []
    if craftable:
        parts.append(f"Рецепт крафта, дерево ингредиентов и живая цена аукциона «{name}» "
                     f"в STALZONE (Stalcraft).")
        p = store.get(item_id) or {}
        buyout = p.get("min_buyout")
        if buyout:
            parts.append(f"Цена на аукционе — от {round(buyout):,} ₽.".replace(",", " "))
        parts.append("Считаем, что выгоднее — скрафтить или купить готовое.")
    else:
        parts.append(f"«{name}» в STALZONE (Stalcraft): цена аукциона RU и где применяется "
                     f"в крафте. Предмет не крафтится — только найти, выбить или купить.")
    title = f"{name} — крафт, цена и выгода в STALZONE (Stalcraft) | {SITE}"
    desc = " ".join(parts)
    url = _base_url(request) + f"/item/{item_id}"
    return render_index(request, f"/item/{item_id}", title=title, desc=desc,
                        jsonld=_product_jsonld(request, it, url, desc))


@router.get("/artefact/{item_id}", response_class=HTMLResponse)
async def artefact_page(request: Request, item_id: str):
    it = db.item(item_id)
    if not it:
        return render_index(request, f"/artefact/{item_id}",
                            title=f"Артефакт не найден — {SITE}", noindex=True)
    name = it["name"]
    return render_index(
        request, f"/artefact/{item_id}",
        title=f"{name} — цена по качеству и заточке, аукцион STALZONE (Stalcraft)",
        desc=f"Средняя цена продаж «{name}» на аукционе STALZONE (Stalcraft) по корзинам "
             f"качество × заточка (+0/+5/+10/+15), динамика и активные лоты.")


@router.get("/market", response_class=HTMLResponse)
async def market_page(request: Request):
    return render_index(
        request, "/market",
        title="Аукцион STALZONE (Stalcraft) — живые лоты и история продаж",
        desc="Полный аукцион STALZONE (ранее Stalcraft — Сталкрафт): активные лоты любого "
             "предмета с ценой за штуку, история продаж, самые продаваемые и самые дорогие "
             "позиции. Живые данные RU-региона.")


@router.get("/auction", response_class=HTMLResponse)
async def auction_page(request: Request):
    return render_index(
        request, "/auction",
        title="Биржа артефактов STALZONE (Stalcraft) — рост цен по качеству и заточке",
        desc="Какие артефакты STALZONE (ранее Stalcraft) сильнее всего растут и падают "
             "в цене. Средние цены продаж по корзинам качество × заточка, динамика за "
             "сутки и неделю.")


@router.get("/builds", response_class=HTMLResponse)
async def builds_page(request: Request):
    return render_index(
        request, "/builds",
        title="Калькулятор сборок артефактов STALZONE (Stalcraft) — подбор под бюджет",
        desc="Собери сборку артефактов STALZONE (ранее Stalcraft) вручную или автоподбором "
             "под бюджет: контейнер, качество и заточка, суммарные статы и стоимость по "
             "живым ценам аукциона.")


@router.get("/barter", response_class=HTMLResponse)
async def barter_page(request: Request):
    return render_index(
        request, "/barter",
        title="Калькулятор бартера STALZONE (Stalcraft) — что выгодно менять у торговцев",
        desc="Все бартеры STALZONE (ранее Stalcraft — Сталкрафт): 1400+ обменов у торговцев "
             "поселений с живыми ценами аукциона. Считаем стоимость входов и доплаты против "
             "цены продажи результата — что выгодно менять прямо сейчас.")


@router.get("/obmen", response_class=HTMLResponse)
async def obmen_page(request: Request):
    return render_index(
        request, "/obmen",
        title="Обменные монеты STALZONE (Stalcraft) — что выгодно брать у Перекупщика",
        desc="Куда потратить обменные монеты в STALZONE (ранее Stalcraft — Сталкрафт): "
             "курс «рублей за монету» по каждой позиции Перекупщика на живых ценах "
             "аукциона. Что взять за монеты и продать выгоднее всего.")


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return render_index(request, "/profile", title=f"Профиль убежища — {SITE}",
                        noindex=True)


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return render_index(request, "/search", title=f"Поиск по базе — {SITE}", noindex=True)


@router.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    return render_index(
        request, "/map",
        title="Интерактивная карта мира STALZONE (Stalcraft) — спутниковый вид",
        desc="Интерактивная карта мира STALZONE (ранее Stalcraft — Сталкрафт): глобальный "
             "спутниковый вид Зоны и детальные карты территорий — Южная Зона, Северная "
             "Зона, Дикий Север, Любеч-3. Зум, перетаскивание, как в КПК игры.")


@router.get("/map/{territory_id}", response_class=HTMLResponse)
async def map_territory_page(request: Request, territory_id: str):
    from app.routers.api import MAP_TERRITORIES
    terr = next((t for t in MAP_TERRITORIES
                 if t["id"] == territory_id and t.get("bbox")), None)
    if not terr:
        return render_index(request, f"/map/{territory_id}",
                            title=f"Территория не найдена — {SITE}", noindex=True)
    name = terr["name"]
    return render_index(
        request, f"/map/{territory_id}",
        title=f"{name} — детальная карта STALZONE (Stalcraft)",
        desc=f"Детальная карта территории «{name}» STALZONE (ранее Stalcraft — Сталкрафт) "
             f"из КПК игры: зум до отдельных зданий, перетаскивание.")


@router.get("/guides", response_class=HTMLResponse)
async def guides_page(request: Request):
    return render_index(
        request, "/guides",
        title="Гайды по STALZONE (Stalcraft) — задания, крафт, экономика и снаряжение",
        desc="Разборы и гайды по STALZONE (ранее Stalcraft — Сталкрафт): загадочные "
             "предметы и задания, крафт, экономика, снаряжение и события. Простым языком, "
             "с картинками и ссылками на карточки предметов.")


@router.get("/guides/{slug}", response_class=HTMLResponse)
async def guide_page(request: Request, slug: str):
    g = guides.get_guide(slug)
    if not g:
        return render_index(request, f"/guides/{slug}",
                            title=f"Гайд не найден — {SITE}", noindex=True)
    title = f"{g['title']} — STALZONE (Stalcraft)"
    desc = g.get("description") or f"Гайд по STALZONE (Stalcraft): {g['title']}."
    url = _base_url(request) + f"/guides/{slug}"
    cover = g.get("cover")
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": g["title"],
        "description": desc,
        "datePublished": g.get("created_at", ""),
        "dateModified": g.get("updated_at") or g.get("created_at", ""),
        "inLanguage": "ru",
        "author": {"@type": "Organization", "name": SITE},
        "publisher": {"@type": "Organization", "name": SITE},
        "mainEntityOfPage": url,
    }
    if cover:
        jsonld["image"] = (cover if cover.startswith("http")
                           else _base_url(request) + "/" + cover.lstrip("/"))
    return render_index(request, f"/guides/{slug}", title=title, desc=desc,
                        jsonld=jsonld, image=cover)


@router.get("/dev", response_class=HTMLResponse)
@router.get("/dev/{_sub}", response_class=HTMLResponse)
async def dev_pages(request: Request, _sub: str = ""):
    """DEV-инструменты (SPA сам проверит права): раньше прямой заход/F5 давал 404."""
    return render_index(request, "/dev", title=f"ДЕВ-инструменты — {SITE}", noindex=True)


@router.get("/quests", response_class=HTMLResponse)
async def quests_page(request: Request):
    return render_index(
        request, "/quests",
        title="Квесты STALZONE (Stalcraft) — схема линеек и прохождение заданий",
        desc="Все квесты STALZONE (ранее Stalcraft — Сталкрафт) на одной схеме: основные "
             "и побочные задания сталкеров, бандитов и группировок (Завет, Заря, Долг, "
             "Наёмники). Прохождение, награды и точки заданий на карте Зоны.")


@router.get("/quests/{qid}", response_class=HTMLResponse)
async def quest_page(request: Request, qid: str):
    # отдельные квесты пока noindex,follow — включим индексацию точечно,
    # когда наполнятся и появится подтверждённый спрос (см. политику SEO)
    from app.db import quests
    q = quests.get(int(qid)) if qid.isdigit() else None
    if not q:
        return render_index(request, f"/quests/{qid}",
                            title=f"Квест не найден — {SITE}", noindex=True)
    return render_index(
        request, f"/quests/{qid}",
        title=f"{q['title']} — прохождение квеста STALZONE (Stalcraft)",
        desc=q.get("summary") or f"Прохождение квеста «{q['title']}» в STALZONE "
             f"(ранее Stalcraft): что делать, награда и точки на карте.",
        noindex=True)


@router.get("/patches", response_class=HTMLResponse)
async def patches_page(request: Request):
    return render_index(
        request, "/patches",
        title="Патчноуты STALZONE (Stalcraft) — все обновления игры",
        desc="Все патчноуты и хотфиксы STALZONE (ранее Stalcraft — Сталкрафт) в одном "
             "месте: полный текст обновлений с картинками, свежие сверху. Архив "
             "изменений игры с обсуждением.")


@router.get("/patches/{pid}", response_class=HTMLResponse)
async def patch_page(request: Request, pid: str):
    from app.db import news
    p = news.get_patch(int(pid)) if pid.isdigit() else None
    if not p:
        return render_index(request, f"/patches/{pid}",
                            title=f"Патч не найден — {SITE}", noindex=True)
    title = f"{p['title']} — патчноут STALZONE (Stalcraft)"
    desc = p["anons"] or f"Обновление STALZONE (Stalcraft): {p['title']}."
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": p["title"],
        "datePublished": p["created_at"],
        "inLanguage": "ru",
        "publisher": {"@type": "Organization", "name": SITE},
        "mainEntityOfPage": _base_url(request) + f"/patches/{pid}",
    }
    return render_index(request, f"/patches/{pid}", title=title, desc=desc,
                        jsonld=jsonld)


@router.get("/sitemap.xml")
async def sitemap(request: Request):
    """Карта сайта: только осмысленные посадочные (без тысяч карточек — под спрос)."""
    base = _base_url(request)
    paths = ["/", "/craft", "/vygodno-kraftit", "/auction", "/market", "/builds",
             "/barter", "/obmen", "/patches", "/guides", "/quests", "/map"]
    urls = "".join(
        f"<url><loc>{_html.escape(base + p, quote=True)}</loc>"
        f"<changefreq>{'daily' if p in ('/', '/craft', '/vygodno-kraftit', '/auction', '/market', '/barter', '/patches') else 'weekly'}</changefreq>"
        f"</url>" for p in paths)
    # гайды — контентные посадочные под подтверждённый спрос («конверт с баксами» и т.п.)
    try:
        urls += "".join(
            f"<url><loc>{_html.escape(base + f'/guides/{slug}', quote=True)}</loc>"
            + (f"<lastmod>{_html.escape(mod[:10], quote=True)}</lastmod>" if mod else "")
            + "<changefreq>weekly</changefreq></url>"
            for slug, mod in guides.all_slugs())
    except Exception:
        logger.exception("sitemap: guides skipped")
    # патчноуты — контентные страницы под подтверждённый спрос («сталкрафт патчноут»)
    from app.db import news
    try:
        urls += "".join(
            f"<url><loc>{_html.escape(base + f'/patches/{pid}', quote=True)}</loc>"
            f"<lastmod>{_html.escape(created[:10], quote=True)}</lastmod></url>"
            for pid, created in news.all_patch_ids() if created)
    except Exception:
        logger.exception("sitemap: patches skipped")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{urls}</urlset>")
    return Response(xml, media_type="application/xml")
