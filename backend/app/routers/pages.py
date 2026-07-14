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
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import config
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


def _base_url(request: Request) -> str:
    return config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def _sub(pattern: str, value: str, s: str) -> str:
    """Подставить значение в первый матч, не трогая спецсимволы value."""
    return re.sub(pattern, lambda _m: value, s, count=1, flags=re.S)


def render_index(request: Request, path: str, *, title: str | None = None,
                 desc: str | None = None, noindex: bool = False,
                 jsonld: dict | None = None) -> HTMLResponse:
    title = title or DEF_TITLE
    desc = (desc or DEF_DESC).strip()
    if len(desc) > 300:
        desc = desc[:297].rstrip() + "…"
    url = _base_url(request) + path
    t, d, u = (_html.escape(title, quote=True), _html.escape(desc, quote=True),
               _html.escape(url, quote=True))

    s = _index_template()
    s = s.replace('src="app.js"', f'src="app.js?v={_V_JS}"', 1)
    s = s.replace('href="styles.css"', f'href="styles.css?v={_V_CSS}"', 1)
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
    if noindex:
        s = s.replace('<meta name="theme-color"',
                      '<meta name="robots" content="noindex,follow">\n  <meta name="theme-color"', 1)
    if jsonld:
        # экранируем </ внутри JSON, чтобы не оборвать <script>
        block = json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        s = s.replace("</head>",
                      f'  <script type="application/ld+json">{block}</script>\n</head>', 1)
    return HTMLResponse(s)


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
    return render_index(request, "/guides",
                        title=f"Гайды по STALZONE (Stalcraft) — {SITE}")


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
             "/barter", "/obmen", "/patches", "/map"]
    urls = "".join(
        f"<url><loc>{_html.escape(base + p, quote=True)}</loc>"
        f"<changefreq>{'daily' if p in ('/', '/craft', '/vygodno-kraftit', '/auction', '/market', '/barter', '/patches') else 'weekly'}</changefreq>"
        f"</url>" for p in paths)
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
