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
DEF_TITLE = "Калькулятор крафта STALZONE (Сталкрафт) — цены аукциона и выгода"
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
                 jsonld: dict | list | None = None, image: str | None = None,
                 seo_html: str | None = None) -> HTMLResponse:
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

    if seo_html:
        # серверный контент-блок под конкретный роут: SPA-шелл у всех страниц
        # одинаков, поэтому без этого краулер видит на /builds текст главной.
        # seo_html — авторский (доверенный) HTML, не экранируем. Фронт (route())
        # прячет блок при уходе с data-seo-path, чтобы текст не «залипал».
        s = s.replace(
            '<section id="seoProse" class="seo-prose" hidden></section>',
            f'<section id="seoProse" class="seo-prose" '
            f'data-seo-path="{_html.escape(path, quote=True)}">{seo_html}</section>', 1)

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


# ---------- серверный SEO-контент под инструменты ----------
# Спецификация раздела (заголовок, интро, шаги, FAQ, перелинковка) → видимый
# контент-блок + FAQPage-разметка. Q&A — единый источник для того и другого,
# чтобы текст на странице и в микроразметке не расходились.

def _seo_block(*, h2: str, intro: list[str], steps_title: str, steps: list[str],
               faq: list[tuple[str, str]],
               links: list[tuple[str, str]] | None = None) -> tuple[str, dict]:
    faq_html = "".join(
        f'<div class="seo-faq-item"><h4 class="seo-faq-q">{_html.escape(q)}</h4>'
        f'<p class="seo-faq-a">{_html.escape(a)}</p></div>'
        for q, a in faq)
    paras = "".join(f'<p>{_html.escape(p)}</p>' for p in intro)
    items = "".join(f'<li>{_html.escape(s)}</li>' for s in steps)
    links_html = ""
    if links:
        a = " · ".join(
            f'<a href="{_html.escape(href, quote=True)}">{_html.escape(txt)}</a>'
            for href, txt in links)
        links_html = f'<p class="seo-links">Смотрите также: {a}</p>'
    body = (
        '<div class="seo-inner">'
        f'<h2>{_html.escape(h2)}</h2>'
        f'{paras}'
        f'<h3>{_html.escape(steps_title)}</h3>'
        f'<ol>{items}</ol>'
        '<h3>Частые вопросы</h3>'
        f'{faq_html}'
        f'{links_html}'
        '</div>')
    jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq],
    }
    return body, jsonld


@lru_cache(maxsize=1)
def _builds_seo() -> tuple[str, dict]:
    return _seo_block(
        h2="Калькулятор сборок артефактов в Сталкрафт (STALZONE)",
        intro=[
            "Онлайн-калькулятор сборок артефактов для Сталкрафт (STALZONE, ранее "
            "Stalcraft) помогает собрать оптимальный набор в контейнер: выбираете "
            "хранилище, заполняете слоты — и сразу видите суммарные статы, уровень "
            "заражения и полную стоимость сборки по живым ценам аукциона RU. Работает "
            "в ручном режиме и с автоподбором под бюджет."],
        steps_title="Как собрать сборку",
        steps=[
            "Выберите контейнер — от него зависит число слотов и КПД полезных статов.",
            "Добавьте артефакты в слоты и укажите качество и заточку каждого.",
            "Следите за суммой статов и блоком заражения — оно не должно перекрыть пользу.",
            "Смотрите итоговую цену по аукциону или включите автоподбор под бюджет."],
        faq=[
            ("Что такое сборка артефактов в Сталкрафт?",
             "Сборка — это набор артефактов, уложенный в контейнер (свинцовый контейнер, "
             "пояс и т.п.). Артефакты дают статы — защиту, выносливость, переносимый вес, — "
             "но многие фонят. Задача сборки: набрать максимум полезных статов, удержав "
             "заражение в допустимых пределах."),
            ("Как собрать выгодную сборку под бюджет?",
             "Выберите контейнер и заполните слоты вручную или включите автоподбор: "
             "калькулятор переберёт комбинации артефактов под указанный бюджет по живым "
             "ценам аукциона RU и покажет ту, что даёт лучшие статы за ваши деньги."),
            ("Сколько стоит собрать сборку?",
             "Стоимость считается по актуальному аукциону: для каждого артефакта берётся "
             "цена в нужном качестве и заточке (среднее по 5 дешёвым лотам либо среднее за "
             "7 дней) и суммируется по всем занятым слотам."),
            ("Учитываются ли качество и заточка артефактов?",
             "Да. Для каждого артефакта задаются качество и заточка (+0…+15) — от них "
             "зависят и статы, и цена. Контейнер добавляет свою эффективность: полезные "
             "статы умножаются на его КПД, вредные — учитываются полностью."),
            ("Чем сборка отличается от крафта?",
             "Крафт — изготовление предмета по рецепту верстака; для него на сайте есть "
             "отдельный калькулятор крафта. Сборка — комбинация уже готовых артефактов в "
             "контейнере ради суммарных характеристик персонажа."),
        ],
        links=[("/barter", "калькулятор бартера"),
               ("/obmen", "обменные монеты"),
               ("/craft", "калькулятор крафта")])


@lru_cache(maxsize=1)
def _barter_seo() -> tuple[str, dict]:
    return _seo_block(
        h2="Калькулятор бартера Сталкрафт (STALZONE)",
        intro=[
            "Калькулятор бартера для Сталкрафт (STALZONE, ранее Stalcraft) собирает все "
            "обмены у торговцев поселений в один список и считает выгоду по живым ценам "
            "аукциона RU: стоимость входов и доплату против цены продажи результата. "
            "Сразу видно, что выгодно менять прямо сейчас, а что нет.",
            "Несколько обменов можно отметить галочками и посчитать общий итог с "
            "суммарными ресурсами — удобно спланировать поход к торговцу."],
        steps_title="Как пользоваться",
        steps=[
            "Найдите нужный обмен по названию предмета или поселению.",
            "Калькулятор покажет стоимость входов по аукциону и требуемую доплату.",
            "Сравните с ценой продажи результата — выгодные обмены выше в рейтинге.",
            "Отметьте несколько обменов галочками, чтобы увидеть общий итог по ресурсам."],
        faq=[
            ("Что такое бартер в Сталкрафт?",
             "Бартер — обмен предметов и ресурсов у торговцев в поселениях: отдаёте набор "
             "входов (иногда плюс доплата рублями) и получаете нужный предмет. Часто это "
             "дешевле, чем покупать результат на аукционе."),
            ("Как понять, выгоден ли обмен?",
             "Калькулятор берёт живые цены аукциона: суммирует стоимость всех входов и "
             "доплату и сравнивает с ценой продажи результата. Если результат дороже "
             "входов — обмен выгоден и стоит выше в рейтинге."),
            ("Сколько обменов в калькуляторе?",
             "Более 1400 бартеров из 12 поселений — все, что есть в игре. Список "
             "фильтруется по рангу и пересчитывается по актуальным ценам."),
            ("Можно ли посчитать сразу несколько обменов?",
             "Да. Отметьте нужные обмены галочками — калькулятор соберёт корзину, покажет "
             "суммарные ресурсы, доплаты и общий итог, чтобы спланировать поход к торговцу."),
            ("Учитываются ли доплаты и комиссия аукциона?",
             "Да. В стоимость входит доплата рублями у торговца, а выручка от продажи "
             "результата считается с учётом аукционной комиссии 5%."),
        ],
        links=[("/obmen", "обменные монеты"),
               ("/builds", "калькулятор сборок"),
               ("/craft", "калькулятор крафта")])


@lru_cache(maxsize=1)
def _obmen_seo() -> tuple[str, dict]:
    return _seo_block(
        h2="Калькулятор обменок Сталкрафт (STALZONE) — обменные монеты Перекупщика",
        intro=[
            "Калькулятор обменных монет (обменок) для Сталкрафт (STALZONE, ранее "
            "Stalcraft) показывает курс «рублей за монету» по каждой позиции у Перекупщика "
            "на живых ценах аукциона RU. Сразу видно, что выгоднее всего взять за "
            "обменные монеты и перепродать.",
            "Для каждой позиции считаются два канала сбыта: продажа на аукционе (с учётом "
            "комиссии) и мгновенная сдача скупщику по vendor-цене."],
        steps_title="Как пользоваться",
        steps=[
            "Откройте список ассортимента Перекупщика — все позиции за обменные монеты.",
            "У каждой позиции показан курс «рублей за монету» по текущему аукциону.",
            "Сравните позиции — берите ту, где монета даёт больше рублей.",
            "Учтите канал сбыта: аукцион (с комиссией) или мгновенная скупка по vendor-цене."],
        faq=[
            ("Что такое обменные монеты в Сталкрафт?",
             "Обменные монеты — валюта Перекупщика: на них берут ограниченный ассортимент "
             "предметов. Калькулятор помогает понять, какая позиция даёт максимум рублей "
             "за одну монету."),
            ("Что выгодно брать за обменные монеты?",
             "Калькулятор считает для каждой позиции курс «рублей за монету» по живым ценам "
             "аукциона и сортирует их — берите ту, у которой отдача на монету выше."),
            ("Где продавать взятое за монеты?",
             "Есть два канала: аукцион (цена продажи минус комиссия 5%) и мгновенная сдача "
             "скупщику по фиксированной vendor-цене. Калькулятор показывает оба, чтобы "
             "выбрать выгоднее."),
            ("Откуда берётся ассортимент Перекупщика?",
             "Ассортимента обменок нет в открытых данных игры, поэтому список ведётся "
             "вручную и обновляется по мере изменений у Перекупщика; цены — живые, с аукциона."),
            ("Чем обменки отличаются от бартера?",
             "Бартер — обмен предметов у торговцев поселений; обменки — покупка за особую "
             "валюту у Перекупщика. Для бартера на сайте есть отдельный калькулятор бартера."),
        ],
        links=[("/barter", "калькулятор бартера"),
               ("/builds", "калькулятор сборок"),
               ("/craft", "калькулятор крафта")])


@lru_cache(maxsize=1)
def _operations_seo() -> tuple[str, dict]:
    return _seo_block(
        h2="Операции STALZONE (Сталкрафт) — мета снаряжения и статистика забегов",
        intro=[
            "Раздел «Операции» собирает статистику PvE-режима STALZONE (ранее Stalcraft — "
            "Сталкрафт): проведённые забеги, их сложность, время прохождения и снаряжение "
            "участников — броня и оружие с заточкой. По этим данным видно, с каким сетапом "
            "операции проходят быстрее всего на каждом этапе сложности.",
            "Сложность делится на три этапа. Для каждого этапа и каждого класса брони "
            "считается мета недели: самая ходовая броня и оружие, среднее время прохождения "
            "и самые быстрые комбинации снаряжения по живым забегам игроков. Мета "
            "обновляется еженедельно — сброс по средам."],
        steps_title="Как читать статистику операций",
        steps=[
            "Выберите этап сложности — низкий, средний или высокий: мета на них разная.",
            "Смотрите самые быстрые комбо «броня + оружие» — с ними забеги закрывают быстрее.",
            "Разбивка по классам брони показывает мету под ваш стиль игры.",
            "В ленте истории видно каждый забег: состав, снаряжение, время и K/D участников."],
        faq=[
            ("Что такое Операции в Сталкрафт?",
             "Операции — PvE-режим STALZONE (Сталкрафт): группа игроков зачищает карту на "
             "выбранной сложности. За завершение дают награду, размер которой растёт со "
             "сложностью. Раздел собирает статистику завершённых забегов."),
            ("Какое снаряжение мета в Операциях?",
             "Мета зависит от этапа сложности и класса брони. Раздел считает по реальным "
             "забегам, какая броня и оружие используются чаще всего и с какими сетапами "
             "операции проходят за меньшее время — это и есть актуальная мета."),
            ("Как считается время прохождения?",
             "Для каждой комбинации снаряжения берётся среднее время завершённых забегов на "
             "выбранном этапе сложности за текущую неделю. Комбинации с малой выборкой в мете "
             "не показываются, чтобы случайные забеги не искажали картину. Мета обновляется "
             "еженедельно со сбросом по средам, история забегов остаётся полной."),
            ("Как делится сложность на этапы?",
             f"На три этапа: низкий (0–{config.OPS_TIER_LOW_MAX}), средний "
             f"({config.OPS_TIER_LOW_MAX + 1}–{config.OPS_TIER_MID_MAX}) и высокий "
             f"({config.OPS_TIER_MID_MAX + 1}+). Мета и среднее время считаются по каждому "
             f"этапу отдельно."),
            ("Откуда берутся данные о забегах?",
             "Данные приходят из официального API STALZONE по завершённым сессиям режима "
             "Операции: карта, сложность, длительность и снаряжение каждого участника. "
             "Статистика обновляется автоматически."),
        ],
        links=[("/builds", "калькулятор сборок"),
               ("/market", "аукцион"),
               ("/map", "карта Зоны")])


def _seo_article(h1: str, body_html: str, intro: str | None = None) -> str:
    """Контентная статья (патч/гайд/квест) в серверный SEO-блок — чтобы полный
    текст был в HTML для краулеров без JS. body_html — доверенный санитизированный
    HTML. На клиенте этот блок прячется (интерактивная версия рисуется в #page)."""
    intro_p = f"<p>{_html.escape(intro)}</p>" if intro else ""
    return (f'<article class="seo-article"><h1>{_html.escape(h1)}</h1>'
            f'{intro_p}<div class="seo-article-body">{body_html}</div></article>')


# ---------- маршруты фронта ----------

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_index(
        request, "/",
        title="StalZone Helper — крафт, аукцион, сборки и карта STALZONE (Сталкрафт)",
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
        title="Что выгодно крафтить в STALZONE (Сталкрафт) сегодня — рейтинг выгоды",
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
                     f"в STALZONE (Сталкрафт).")
        p = store.get(item_id) or {}
        buyout = p.get("min_buyout")
        if buyout:
            parts.append(f"Цена на аукционе — от {round(buyout):,} ₽.".replace(",", " "))
        parts.append("Считаем, что выгоднее — скрафтить или купить готовое.")
    else:
        parts.append(f"«{name}» в STALZONE (Сталкрафт): цена аукциона RU и где применяется "
                     f"в крафте. Предмет не крафтится — только найти, выбить или купить.")
    title = f"{name} — крафт, цена и выгода в STALZONE (Сталкрафт) | {SITE}"
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
        title=f"{name} — цена по качеству и заточке, аукцион STALZONE (Сталкрафт)",
        desc=f"Средняя цена продаж «{name}» на аукционе STALZONE (Сталкрафт) по корзинам "
             f"качество × заточка (+0/+5/+10/+15), динамика и активные лоты.")


@router.get("/items", response_class=HTMLResponse)
async def items_page(request: Request):
    return render_index(
        request, "/items",
        title="База предметов STALZONE (Сталкрафт) — оружие, броня, артефакты",
        desc="Полная база предметов STALZONE (ранее Stalcraft — Сталкрафт): оружие, "
             "броня, контейнеры, артефакты и снаряжение с игровыми характеристиками, "
             "ценой аукциона, рецептами крафта и бартерами.")


@router.get("/market", response_class=HTMLResponse)
async def market_page(request: Request):
    return render_index(
        request, "/market",
        title="Аукцион STALZONE (Сталкрафт) — живые лоты и история продаж",
        desc="Полный аукцион STALZONE (ранее Stalcraft — Сталкрафт): активные лоты любого "
             "предмета с ценой за штуку, история продаж, самые продаваемые и самые дорогие "
             "позиции. Живые данные RU-региона.")


@router.get("/auction", response_class=HTMLResponse)
async def auction_page(request: Request):
    return render_index(
        request, "/auction",
        title="Биржа артефактов STALZONE (Сталкрафт) — рост цен по качеству и заточке",
        desc="Какие артефакты STALZONE (ранее Stalcraft) сильнее всего растут и падают "
             "в цене. Средние цены продаж по корзинам качество × заточка, динамика за "
             "сутки и неделю.")


@router.get("/builds", response_class=HTMLResponse)
async def builds_page(request: Request):
    seo_html, faq_ld = _builds_seo()
    return render_index(
        request, "/builds",
        title="Калькулятор сборок Сталкрафт (STALZONE) — подбор артефактов под бюджет",
        desc="Калькулятор сборок артефактов в Сталкрафт (STALZONE, ранее Stalcraft): "
             "собери набор в контейнер вручную или автоподбором под бюджет — качество, "
             "заточка, суммарные статы и стоимость по живым ценам аукциона RU.",
        seo_html=seo_html, jsonld=faq_ld)


@router.get("/barter", response_class=HTMLResponse)
async def barter_page(request: Request):
    seo_html, faq_ld = _barter_seo()
    return render_index(
        request, "/barter",
        title="Калькулятор бартера Сталкрафт (STALZONE) — что выгодно менять у торговцев",
        desc="Все бартеры STALZONE (ранее Stalcraft — Сталкрафт): 1400+ обменов у торговцев "
             "поселений с живыми ценами аукциона. Считаем стоимость входов и доплаты против "
             "цены продажи результата — что выгодно менять прямо сейчас.",
        seo_html=seo_html, jsonld=faq_ld)


@router.get("/obmen", response_class=HTMLResponse)
async def obmen_page(request: Request):
    seo_html, faq_ld = _obmen_seo()
    return render_index(
        request, "/obmen",
        title="Калькулятор обменок Сталкрафт (STALZONE) — обменные монеты Перекупщика",
        desc="Калькулятор обменок Сталкрафт (STALZONE, ранее Stalcraft): курс «рублей за "
             "монету» по каждой позиции Перекупщика на живых ценах аукциона RU — что "
             "выгодно взять за обменные монеты и перепродать.",
        seo_html=seo_html, jsonld=faq_ld)


@router.get("/operations", response_class=HTMLResponse)
async def operations_page(request: Request):
    seo_html, faq_ld = _operations_seo()
    return render_index(
        request, "/operations",
        title="Операции STALZONE (Сталкрафт) — мета снаряжения и статистика забегов",
        desc="Статистика PvE-режима Операции STALZONE (ранее Stalcraft — Сталкрафт): с "
             "каким снаряжением проходят быстрее всего на каждом этапе сложности, мета "
             "брони и оружия по классам и лента забегов игроков.",
        seo_html=seo_html, jsonld=faq_ld)


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
        title="Интерактивная карта мира STALZONE (Сталкрафт) — спутниковый вид",
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
        title=f"{name} — детальная карта STALZONE (Сталкрафт)",
        desc=f"Детальная карта территории «{name}» STALZONE (ранее Stalcraft — Сталкрафт) "
             f"из КПК игры: зум до отдельных зданий, перетаскивание.")


@router.get("/guides", response_class=HTMLResponse)
async def guides_page(request: Request):
    return render_index(
        request, "/guides",
        title="Гайды по STALZONE (Сталкрафт) — задания, крафт, экономика и снаряжение",
        desc="Разборы и гайды по STALZONE (ранее Stalcraft — Сталкрафт): загадочные "
             "предметы и задания, крафт, экономика, снаряжение и события. Простым языком, "
             "с картинками и ссылками на карточки предметов.")


@router.get("/guides/{slug}", response_class=HTMLResponse)
async def guide_page(request: Request, slug: str):
    g = guides.get_guide(slug)
    if not g:
        return render_index(request, f"/guides/{slug}",
                            title=f"Гайд не найден — {SITE}", noindex=True)
    title = f"{g['title']} — STALZONE (Сталкрафт)"
    desc = g.get("description") or f"Гайд по STALZONE (Сталкрафт): {g['title']}."
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
    # тело гайда — в серверный HTML (crawlable без JS)
    seo_html = _seo_article(g["title"], g["html"], g.get("description")) if g.get("html") else None
    return render_index(request, f"/guides/{slug}", title=title, desc=desc,
                        jsonld=jsonld, image=cover, seo_html=seo_html)


@router.get("/promo", response_class=HTMLResponse)
async def promo_page(request: Request):
    return render_index(
        request, "/promo",
        title="Промокоды STALZONE (Сталкрафт) — актуальные рабочие коды",
        desc="Все актуальные промокоды STALZONE (ранее Stalcraft — Сталкрафт) в одном "
             "месте: что даёт код, до какого числа действует, копирование в один клик. "
             "Истёкшие промокоды убираются автоматически — только рабочие.")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return render_index(
        request, "/privacy",
        title=f"Политика обработки персональных данных — {SITE}",
        desc="Как StalZone Helper обрабатывает и защищает персональные данные "
             "пользователей: какие данные собираются, цели, cookie, права субъекта "
             "и контакты. В соответствии с 152-ФЗ.")


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return render_index(
        request, "/terms",
        title=f"Пользовательское соглашение — {SITE}",
        desc="Условия использования StalZone Helper: статус неофициального фан-проекта, "
             "характер справочных данных, регистрация, права и обязанности, "
             "ограничение ответственности, 18+.")


@router.get("/dev", response_class=HTMLResponse)
@router.get("/dev/{_sub}", response_class=HTMLResponse)
async def dev_pages(request: Request, _sub: str = ""):
    """DEV-инструменты (SPA сам проверит права): раньше прямой заход/F5 давал 404."""
    return render_index(request, "/dev", title=f"ДЕВ-инструменты — {SITE}", noindex=True)


@router.get("/quests", response_class=HTMLResponse)
async def quests_page(request: Request):
    return render_index(
        request, "/quests",
        title="Квесты STALZONE (Сталкрафт) — схема линеек и прохождение заданий",
        desc="Все квесты STALZONE (ранее Stalcraft — Сталкрафт) на одной схеме: основные "
             "и побочные задания сталкеров, бандитов и группировок (Завет, Заря, Долг, "
             "Наёмники). Прохождение, награды и точки заданий на карте Зоны.")


@router.get("/quests/{qid}", response_class=HTMLResponse)
async def quest_page(request: Request, qid: str):
    from app.db import quests
    q = quests.get(int(qid)) if qid.isdigit() else None
    if not q:
        return render_index(request, f"/quests/{qid}",
                            title=f"Квест не найден — {SITE}", noindex=True)
    # квесты с прохождением индексируем (тело — в серверный HTML); пустые — noindex,
    # чтобы не плодить тонкие страницы
    has_body = bool((q.get("html") or "").strip())
    seo_html = _seo_article(f"{q['title']} — прохождение", q["html"],
                            q.get("summary")) if has_body else None
    return render_index(
        request, f"/quests/{qid}",
        title=f"{q['title']} — прохождение квеста STALZONE (Сталкрафт)",
        desc=q.get("summary") or f"Прохождение квеста «{q['title']}» в STALZONE "
             f"(ранее Stalcraft): что делать, награда и точки на карте.",
        noindex=not has_body, seo_html=seo_html)


@router.get("/patches", response_class=HTMLResponse)
async def patches_page(request: Request):
    return render_index(
        request, "/patches",
        title="Патчноуты STALZONE (Сталкрафт) — все обновления игры",
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
    title = f"{p['title']} — патчноут STALZONE (Сталкрафт)"
    desc = p["anons"] or f"Обновление STALZONE (Сталкрафт): {p['title']}."
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": p["title"],
        "datePublished": p["created_at"],
        "inLanguage": "ru",
        "publisher": {"@type": "Organization", "name": SITE},
        "mainEntityOfPage": _base_url(request) + f"/patches/{pid}",
    }
    # тело патча — в серверный HTML (иначе краулеры без JS видят только мету)
    seo_html = _seo_article(p["title"], p["html"]) if p.get("html") else None
    return render_index(request, f"/patches/{pid}", title=title, desc=desc,
                        jsonld=jsonld, seo_html=seo_html)


_SITEMAP_RANK_W = {"RANK_LEGEND": 6, "RANK_MASTER": 5, "RANK_VETERAN": 4,
                   "RANK_STALKER": 3, "RANK_NEWBIE": 2, "QUEST_ITEM": 1, "DEFAULT": 0}
_SITEMAP_GAME_CATS = {"weapon", "armor", "artefact", "containers", "backpacks"}


@lru_cache(maxsize=1)
def _sitemap_item_ids() -> tuple:
    """Все id предметов, отсортированные по «ценности для SEO» (индексируем сперва
    самое востребованное): предметы с игровой карточкой (оружие/броня/арты) →
    крафтящиеся → по редкости. Кэш: база предметов статична после старта."""
    def prio(iid: str):
        it = db.items.get(iid) or {}
        return (db.category(iid) in _SITEMAP_GAME_CATS,
                iid in db.recipe_by_result,
                _SITEMAP_RANK_W.get(it.get("color"), 0),
                it.get("name", ""))
    return tuple(sorted(db.items, key=prio, reverse=True))


@router.get("/sitemap.xml")
async def sitemap(request: Request):
    """Карта сайта: только осмысленные посадочные (без тысяч карточек — под спрос)."""
    base = _base_url(request)
    paths = ["/", "/craft", "/vygodno-kraftit", "/auction", "/market", "/builds",
             "/barter", "/obmen", "/operations", "/items", "/patches", "/guides",
             "/quests", "/map", "/promo", "/privacy", "/terms"]
    urls = "".join(
        f"<url><loc>{_html.escape(base + p, quote=True)}</loc>"
        f"<changefreq>{'daily' if p in ('/', '/craft', '/vygodno-kraftit', '/auction', '/market', '/barter', '/operations', '/patches', '/promo') else 'weekly'}</changefreq>"
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
    # квесты — вечнозелёный интент «как пройти квест X сталкрафт»
    from app.db import quests as _quests
    try:
        urls += "".join(
            f"<url><loc>{_html.escape(base + f'/quests/{qid}', quote=True)}</loc>"
            + (f"<lastmod>{mod}</lastmod>" if mod else "")
            + "<changefreq>weekly</changefreq></url>"
            for qid, mod in _quests.all_quest_ids())
    except Exception:
        logger.exception("sitemap: quests skipped")
    # предметы — ПОСТЕПЕННО: растущая пачка приоритетных первыми (см. _sitemap_item_ids),
    # +SEO_ITEMS_PER_DAY в день от даты старта. Не вываливаем всю базу разом.
    try:
        from datetime import date
        days = (date.today() - date.fromisoformat(config.SEO_ITEMS_START)).days + 1
        cap = max(0, days) * config.SEO_ITEMS_PER_DAY
        urls += "".join(
            f"<url><loc>{_html.escape(base + f'/item/{iid}', quote=True)}</loc>"
            "<changefreq>weekly</changefreq></url>"
            for iid in _sitemap_item_ids()[:cap])
    except Exception:
        logger.exception("sitemap: items skipped")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{urls}</urlset>")
    return Response(xml, media_type="application/xml")
