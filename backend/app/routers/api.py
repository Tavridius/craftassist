"""HTTP API: поиск, инфо о предмете, цена, расчёт крафта, рейтинги.

Данные — из тёплых кэшей (GameDB + PriceStore); исключение — /market/item/{id}
(живые лоты полного аукциона): внешний запрос по требованию с коротким кэшем.
"""
import asyncio
import base64
import binascii
import re
import secrets
import time
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import config
from app.db import chat, guides, mapobjects, market, news, promos, quests, users
from app.db.index import db
from app.routers.auth import current_user, is_admin
from app.services import (auction, barter, builds, craft, exchange,
                          hideout, oauth, sales_log)
from app.services import fuel as fuel_svc
from app.services.artefact_lots import artlots
from app.services.artefact_watch import MSK
from app.services.emission_watch import ewatch
from app.services.ingredient_watch import watch
from app.services.sales_stats import sstats
from app.services.price_store import store
from app.services.rankings import rankings

router = APIRouter(prefix="/api")


def _profile_of(request: Request) -> dict | None:
    """Профиль убежища текущего пользователя (None — не авторизован)."""
    user = current_user(request)
    return users.get_profile(user["id"]) if user else None


@router.get("/search")
async def search(request: Request, q: str = Query(..., min_length=1),
                 limit: int = 30, available: int = 0):
    if not available:
        return {"query": q, "results": db.search(q, limit)}
    # фильтр «доступные рецепты»: только крафтящееся, на что хватает прокачки.
    # Ищем с запасом — часть результатов отсеется профилем.
    prof = _profile_of(request)
    if prof is None:
        return {"query": q, "results": db.search(q, limit)}
    results = [it for it in db.search(q, limit * 4)
               if it["id"] in db.recipe_by_result and hideout.item_available(it["id"], prof)]
    return {"query": q, "results": results[:limit], "available_only": True}


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
async def craft_analyze(item_id: str, request: Request, fuel: int = 0):
    # fuel=1 — учесть топливо генератора: авторизованному — самый выгодный из
    # ДОСТУПНЫХ ему источников (по улучшениям в профиле), гостю — самый выгодный
    prof = _profile_of(request)
    fuel_src = fuel_svc.best(prof) if fuel else None
    res = craft.analyze(item_id, fuel_src=fuel_src)
    if fuel and not fuel_src:   # цены топлива ещё не посчитаны фоном
        res["fuel"] = {"enabled": True, "source": None}
    if res.get("craftable"):
        rankings.bump(item_id)  # статистика популярности
        if prof is not None:
            chosen = (res.get("tree") or {}).get("recipe")
            if chosen:
                res["req_check"] = hideout.check(chosen.get("requirements") or {}, prof)
            res["available"] = hideout.item_available(item_id, prof)
    return res


@router.get("/top")
async def top(request: Request, available: int = 0):
    data = rankings.compute()
    if available:
        prof = _profile_of(request)
        if prof is not None:
            def ok(r):
                return hideout.item_available(r["id"], prof)
            data = {**data, "available_only": True,
                    "popular": [r for r in data["popular"] if ok(r)],
                    "profitable": [r for r in data["profitable"] if ok(r)],
                    "liquid": [r for r in data["liquid"] if ok(r)]}
    return data


@router.get("/hideout")
async def hideout_dict():
    """Справочник для страницы профиля: перки, станки/фичи из рецептов
    + пристройки генератора (газ/фильтр/инвертор/шкаф — не требуются рецептами,
    но газовая станция открывает топливо, см. services/fuel)."""
    return {"perks": db.hideout_perks,
            "features": sorted(set(db.hideout_features) | set(fuel_svc.EXTRA_PROFILE_FEATURES)),
            "feature_icons": {**fuel_svc.feature_icons(), **db.hideout_feature_icons},
            "feature_bench": db.hideout_feature_bench,
            "perk_max": hideout.PERK_MAX}


@router.get("/profile")
async def get_profile(request: Request):
    prof = _profile_of(request)
    if prof is None:
        raise HTTPException(401, "не авторизован")
    return prof


@router.put("/profile")
async def put_profile(request: Request, payload: dict = Body(...)):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "не авторизован")
    prof = hideout.validate_profile(payload)
    users.save_profile(user["id"], prof)
    return prof


@router.get("/watch")
async def watch_prices():
    """Биржа ингредиентов: серии средних цен (замеры по расписанию, 2 раза/сутки)."""
    items = []
    for iid in config.WATCH_IDS:
        it = db.item(iid) or {}
        s = watch.series.get(iid, [])
        latest = s[-1] if s else {}
        prev = s[-2] if len(s) > 1 else {}
        delta_pct = None
        if latest.get("avg") and prev.get("avg"):
            delta_pct = round((latest["avg"] - prev["avg"]) / prev["avg"] * 100, 1)
        items.append({
            "id": iid,
            "name": it.get("name", iid),
            "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"),
            "avg": latest.get("avg"),
            "min_buyout": latest.get("min_buyout"),
            "sales_per_hour": latest.get("sales_per_hour"),
            "delta_pct": delta_pct,
            "series": [{"slot": e.get("slot"), "avg": e.get("avg")} for e in s],
        })
    return {"hours": config.WATCH_HOURS, "last_slot": watch.last_slot, "items": items}


# ---------- биржа артефактов: корзины качество(qlt)×заточка(ptn) ----------

def _slot_ago(**delta) -> str:
    """Слот-ключ 'now - delta' по МСК — для окон агрегатов."""
    return (datetime.now(MSK) - timedelta(**delta)).strftime("%Y-%m-%dT%H:00")


@router.get("/artmarket/top")
async def artmarket_top(window: str = "7d", qlt: int = -1, ptn: int = -1):
    """Топ роста/падения средней цены по корзинам артефактов.

    window=7d: неделя против предыдущей недели; 24h: сутки против недели до них.
    qlt/ptn = -1 — любые. Корзины с < ART_MIN_SALES продаж в любом окне не участвуют.
    """
    if window == "24h":
        cur_since, prev_since = _slot_ago(days=1), _slot_ago(days=8)
    else:
        window = "7d"
        cur_since, prev_since = _slot_ago(days=7), _slot_ago(days=14)
    cur = {(r["item"], r["qlt"], r["ptn"]): r for r in market.window_avgs(cur_since)}
    prev = {(r["item"], r["qlt"], r["ptn"]): r
            for r in market.window_avgs(prev_since, cur_since)}

    rows = []
    for key, c in cur.items():
        p = prev.get(key)
        if not p or c["n"] < config.ART_MIN_SALES or p["n"] < config.ART_MIN_SALES:
            continue
        if (qlt >= 0 and key[1] != qlt) or (ptn >= 0 and key[2] != ptn):
            continue
        it = db.item(key[0]) or {}
        rows.append({
            "id": key[0], "name": it.get("name", key[0]), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"), "qlt": key[1], "ptn": key[2],
            "avg": round(c["avg"]), "prev_avg": round(p["avg"]),
            "pct": round((c["avg"] - p["avg"]) / p["avg"] * 100, 1), "n": c["n"],
        })
    rows.sort(key=lambda r: r["pct"], reverse=True)
    m = market.stats()
    return {"window": window, "min_sales": config.ART_MIN_SALES,
            "up": [r for r in rows if r["pct"] > 0][:20],
            "down": sorted((r for r in rows if r["pct"] < 0), key=lambda r: r["pct"])[:20],
            "buckets_ranked": len(rows), "buckets_tracked": len(cur),
            "first_slot": m.get("first_slot"), "last_slot": m.get("last_slot"),
            "hours": config.ART_WATCH_HOURS}


@router.get("/artmarket/{item_id}")
async def artmarket_item(item_id: str):
    """Карточка артефакта на бирже: все корзины с сериями по слотам и avg7d."""
    it = db.item(item_id)
    if not it:
        raise HTTPException(404, "item not found")
    week_since = _slot_ago(days=7)
    buckets: dict[tuple[int, int], dict] = {}
    for r in market.item_series(item_id):
        b = buckets.setdefault((r["qlt"], r["ptn"]), {
            "qlt": r["qlt"], "ptn": r["ptn"], "series": [], "n7": 0, "sum7": 0.0})
        b["series"].append({"slot": r["slot"], "avg": round(r["avg"]), "n": r["n"]})
        if r["slot"] >= week_since:
            b["n7"] += r["n"]
            b["sum7"] += r["avg"] * r["n"]
    # эффективные цены калькулятора (лоты, пока история не созрела) —
    # добавляют и корзины, которых в истории ещё нет
    prices = builds.bucket_prices()
    for (iid, qlt, ptn), p in prices.items():
        if iid == item_id:
            buckets.setdefault((qlt, ptn), {"qlt": qlt, "ptn": ptn, "series": [],
                                            "n7": 0, "sum7": 0.0})
    out = []
    for b in sorted(buckets.values(), key=lambda b: (b["qlt"], b["ptn"])):
        b["avg7d"] = round(b["sum7"] / b["n7"]) if b["n7"] else None
        del b["sum7"]
        b["price"] = prices.get((item_id, b["qlt"], b["ptn"]))
        out.append(b)
    return {"item": it, "buckets": out, "min_sales": config.ART_MIN_SALES,
            "last_slot": market.get_meta("last_slot")}


# ---------- выбросы ----------

@router.get("/emission")
async def emission():
    """Текущий/последние выбросы (история копится вотчером, API отдаёт только 2)."""
    return ewatch.snapshot()


# ---------- бартер: рейтинг обменов и способы получения ----------

@router.get("/barter/top")
async def barter_top(settlement: str = "", cat: str = "", max_level: int = 0,
                     pure: int = 0, q: str = "", rank: str = ""):
    """Рейтинг бартеров из тёплого кэша. Фильтры: поселение, категория, ранг
    (цвет), уровень поселения ≤ max_level, pure=1 — только покупаемые входы."""
    data = barter.compute_top()
    rows = data["rows"]
    if settlement:
        rows = [r for r in rows if r["settlement"] == settlement]
    if cat:
        rows = [r for r in rows if r["category"] == cat]
    if rank:
        rows = [r for r in rows if r["color"] == rank]
    if max_level:
        rows = [r for r in rows if (r["level"] or 0) <= max_level]
    if pure:  # полностью покупаемые: без фарм-входов и не за спец-валюту
        rows = [r for r in rows if not r["missing"] and r["cost"] is not None]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["name"].lower()]
    # объединяем одинаковые предметы, доступные в разных поселениях: одна строка
    # на предмет (лучшая по выгоде — rows уже отсортированы), n_places — сколько мест
    seen: dict = {}
    deduped = []
    for r in rows:
        prev = seen.get(r["id"])
        if prev is not None:
            prev["n_places"] += 1
            continue
        r = {**r, "n_places": 1}
        seen[r["id"]] = r
        deduped.append(r)
    return {**data, "rows": deduped, "total": len(deduped)}


@router.get("/barter/item/{item_id}")
async def barter_item(item_id: str):
    """Способы получить предмет бартером (с раскрытием входов) + где сдаётся."""
    if not db.item(item_id):
        raise HTTPException(404, "item not found")
    return barter.analyze(item_id)


@router.post("/barter/basket")
async def barter_basket(payload: dict = Body(...)):
    """Корзина бартеров: суммарная стоимость выбранного набора обменов.

    payload: {"items": [{"id": str, "qty": int}]} — до 300 позиций, qty 1..99.
    """
    raw = payload.get("items")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "items required")
    items, seen = [], set()
    for it in raw[:300]:
        iid = str((it or {}).get("id") or "")
        if not iid or iid in seen or not db.item(iid):
            continue
        seen.add(iid)
        try:
            qty = max(1, min(99, int(it.get("qty") or 1)))
        except (TypeError, ValueError):
            qty = 1
        items.append({"id": iid, "qty": qty})
    if not items:
        raise HTTPException(400, "no valid items")
    return barter.basket(items)


# ---------- патчноуты игры ----------

@router.get("/patches")
async def patches_list(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    """Список патчей (заголовок, дата, анонс) — свежие сверху."""
    items, total = news.list_patches(offset, limit)
    return {"items": items, "total": total, "offset": offset}


@router.get("/patches/{pid}")
async def patch_get(pid: int):
    """Полный патч: санитизированный HTML с локальными картинками."""
    p = news.get_patch(pid)
    if not p:
        raise HTTPException(404, "patch not found")
    p.pop("fetched_at", None)
    return p


# ---------- гайды (статьи по игре, авторский контент) ----------

@router.get("/guides")
async def guides_list():
    """Список гайдов (без тела) — свежие сверху."""
    items = guides.list_guides()
    return {"items": items, "total": len(items)}


@router.get("/guides/{slug}")
async def guide_get(slug: str):
    """Полный гайд: заголовок, мета и доверенный HTML тела (только опубликованный)."""
    g = guides.get_guide(slug)
    if not g:
        raise HTTPException(404, "guide not found")
    return g


# ---------- гайды: админ-редактор (создание/правка/удаление, загрузка картинок) ----------

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _clean_guide(payload: dict) -> dict:
    """Санитайз/валидация тела гайда из редактора (форма шлёт объект целиком)."""
    slug = str(payload.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug) or len(slug) > 64:
        raise HTTPException(422, "адрес (slug): только латиница, цифры и дефис")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "нужен заголовок")
    html = str(payload.get("html") or "")
    if len(html) > config.GUIDE_HTML_MAX:
        raise HTTPException(422, f"тело гайда длиннее {config.GUIDE_HTML_MAX} символов")
    created = str(payload.get("created_at") or "").strip()[:10]
    if created and not re.match(r"^\d{4}-\d{2}-\d{2}$", created):
        raise HTTPException(422, "дата: YYYY-MM-DD")
    tags_raw = payload.get("tags") or []
    if isinstance(tags_raw, str):
        tags_raw = tags_raw.split(",")
    tags = [str(t).strip()[:40] for t in tags_raw if str(t).strip()][:8]
    return {
        "slug": slug, "title": title[:200],
        "description": str(payload.get("description") or "").strip()[:400],
        "tags": tags, "cover": str(payload.get("cover") or "").strip()[:400],
        "html": html, "created_at": created,
        "published": bool(payload.get("published", True)),
    }


def _sniff_image(b: bytes) -> str | None:
    """Расширение по магическим байтам (png/jpg/webp/gif) или None."""
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


@router.get("/admin/guides")
async def admin_guides_list(request: Request):
    """Все гайды, включая черновики (только админ)."""
    _require_admin(request)
    return {"items": guides.list_guides(include_drafts=True)}


@router.get("/admin/guides/{slug}")
async def admin_guide_get(request: Request, slug: str):
    """Полный гайд для редактирования, включая черновик (только админ)."""
    _require_admin(request)
    g = guides.get_guide(slug, include_drafts=True)
    if not g:
        raise HTTPException(404, "guide not found")
    return g


@router.post("/admin/guides")
async def admin_guide_save(request: Request, payload: dict = Body(...)):
    """Создать/сохранить гайд (только админ). is_new=true — запрет на занятый slug."""
    _require_admin(request)
    data = _clean_guide(payload)
    if payload.get("is_new") and guides.has(data["slug"]):
        raise HTTPException(409, "гайд с таким адресом уже существует")
    return guides.upsert(data)


@router.delete("/admin/guides/{slug}")
async def admin_guide_delete(request: Request, slug: str):
    """Удалить гайд (только админ) — страница уходит с сайта и из sitemap."""
    _require_admin(request)
    if not guides.delete(slug):
        raise HTTPException(404, "guide not found")
    return {"ok": True}


@router.post("/admin/guides/image")
async def admin_guide_image(request: Request, payload: dict = Body(...)):
    """Загрузка картинки гайда (base64 в JSON, без multipart). Кладёт в volume,
    возвращает {url: /guide-uploads/...} для вставки в тело/обложку."""
    _require_admin(request)
    raw = str(payload.get("data") or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "картинка: битый base64")
    if not blob:
        raise HTTPException(422, "пустой файл")
    if len(blob) > int(config.GUIDE_IMG_MAX_MB * 1024 * 1024):
        raise HTTPException(413, f"картинка больше {config.GUIDE_IMG_MAX_MB:g} МБ")
    ext = _sniff_image(blob)
    if not ext:
        raise HTTPException(422, "формат не поддержан (png, jpg, webp, gif)")
    name = f"{int(time.time())}-{secrets.token_hex(4)}.{ext}"
    config.GUIDE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (config.GUIDE_UPLOADS_DIR / name).write_bytes(blob)
    return {"url": f"/guide-uploads/{name}"}


# ---------- промокоды: модуль на главной + страница /promo (см. db/promos) ----------

@router.get("/promos")
async def promos_list():
    """Активные промокоды: реферальный первым, истёкшие удалены (по дате МСК)."""
    items = promos.list_promos()
    return {"items": items, "total": len(items)}


def _clean_promo(payload: dict) -> dict:
    """Санитайз/валидация промокода из DEV-редактора (форма шлёт объект целиком)."""
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "нужно название")
    code = " ".join(str(payload.get("code") or "").split())
    if not code:
        raise HTTPException(422, "нужен сам промокод")
    expires = str(payload.get("expires_at") or "").strip()[:16]
    if expires:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", expires):
            expires += "T23:59"     # дата без времени = до конца дня включительно
        elif not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", expires):
            raise HTTPException(422, "срок: YYYY-MM-DD или YYYY-MM-DDTHH:MM (МСК)")
    # описание — доверенный HTML (пишут админы), рендерится в карточке на /promo
    return {
        "title": title[:200], "code": code[:64],
        "description": str(payload.get("description") or "").strip()[:8000],
        "image": str(payload.get("image") or "").strip()[:400],
        "expires_at": expires,
        "is_ref": bool(payload.get("is_ref")),
    }


@router.post("/admin/promos")
async def admin_promo_save(request: Request, payload: dict = Body(...)):
    """Создать (без id) или сохранить (с id) промокод — только админ."""
    _require_admin(request)
    pid = payload.get("id")
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "id: число")
    saved = promos.save(pid, _clean_promo(payload))
    if not saved:
        raise HTTPException(404, "promo not found")
    return saved


@router.delete("/admin/promos/{pid}")
async def admin_promo_delete(request: Request, pid: int):
    """Удалить промокод (только админ)."""
    _require_admin(request)
    if not promos.delete(pid):
        raise HTTPException(404, "promo not found")
    return {"ok": True}


# ---------- квесты: блок-схемы линеек + прохождение (см. db/quests) ----------

# Линейки квестов. Фронт рисует вкладки и цвета из этого списка — расширяется
# свободно (id менять нельзя — они записаны в строках quests.faction).
QUEST_FACTIONS = [
    {"id": "stalkers", "name": "Сталкеры", "color": "#7ce68e"},
    {"id": "bandits",  "name": "Бандиты",  "color": "#ffb84d"},
    {"id": "covenant", "name": "Завет",    "color": "#5fa8ff"},
    {"id": "dawn",     "name": "Заря",     "color": "#e8d44d"},
    {"id": "duty",     "name": "Долг",     "color": "#ff6b5e"},
    {"id": "mercs",    "name": "Наёмники", "color": "#9ecbff"},
]
_QUEST_FACTION_IDS = {f["id"] for f in QUEST_FACTIONS}
_QUEST_KINDS = {"main", "side"}
_QUEST_MAX_POINTS = 50


@router.get("/quests")
async def quests_list(request: Request):
    """Мета всех квестов для блок-схемы (без тел). Админ видит и черновики."""
    admin = is_admin(current_user(request))
    return {"factions": QUEST_FACTIONS,
            "items": quests.list_quests(include_drafts=admin),
            "is_admin": admin}


@router.get("/quests/{qid}")
async def quest_get(qid: int, request: Request):
    """Полный квест: прохождение (HTML), награда, точки карты."""
    q = quests.get(qid, include_drafts=is_admin(current_user(request)))
    if not q:
        raise HTTPException(404, "quest not found")
    return q


def _quest_makes_cycle(qid: int | None, parents: list[int]) -> bool:
    """Появится ли цикл, если квесту qid назначить таких родителей.
    Цикл ломает раскладку схемы (уровень = max(уровень родителей)+1)."""
    if qid is None:
        return False        # новый квест: на него ещё никто не ссылается
    pmap = quests.parent_map()
    seen: set[int] = set()
    stack = list(parents)
    while stack:
        p = stack.pop()
        if p == qid:
            return True
        if p in seen:
            continue
        seen.add(p)
        stack.extend(pmap.get(p, []))
    return False


def _clean_quest(payload: dict, qid: int | None) -> dict:
    """Санитайз/валидация квеста из DEV-редактора (форма шлёт объект целиком)."""
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "нужно название квеста")
    faction = str(payload.get("faction") or "")
    if faction not in _QUEST_FACTION_IDS:
        raise HTTPException(422, "линейка: " + ", ".join(sorted(_QUEST_FACTION_IDS)))
    kind = str(payload.get("kind") or "main")
    if kind not in _QUEST_KINDS:
        raise HTTPException(422, "тип: main|side")
    html = str(payload.get("html") or "")
    if len(html) > config.GUIDE_HTML_MAX:
        raise HTTPException(422, f"прохождение длиннее {config.GUIDE_HTML_MAX} символов")

    parents: list[int] = []
    for p in (payload.get("parents") or []):
        try:
            p = int(p)
        except (TypeError, ValueError):
            raise HTTPException(422, "parents: список id")
        if p == qid or p in parents:
            continue
        if not quests.exists(p):
            raise HTTPException(422, f"родитель #{p} не найден")
        parents.append(p)
    if _quest_makes_cycle(qid, parents):
        raise HTTPException(422, "цикл в связях: квест не может открываться после самого себя")

    map_layer = str(payload.get("map_layer") or "")
    if map_layer not in ("", "global", "detail"):
        raise HTTPException(422, "map_layer: global|detail или пусто")
    pts = []
    if map_layer:
        raw = payload.get("map_points") or []
        if not isinstance(raw, list) or len(raw) > _QUEST_MAX_POINTS:
            raise HTTPException(422, f"точек карты — не больше {_QUEST_MAX_POINTS}")
        for p in raw:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                raise HTTPException(422, "точка карты: [x, y, подпись]")
            try:
                x, y = round(float(p[0]), 2), round(float(p[1]), 2)
            except (TypeError, ValueError):
                raise HTTPException(422, "точка карты: координаты — числа")
            name = str(p[2]).strip()[:120] if len(p) > 2 and p[2] else ""
            pts.append([x, y, name])

    try:
        sort = max(-999, min(999, int(payload.get("sort") or 0)))
    except (TypeError, ValueError):
        sort = 0
    return {
        "title": title[:200], "faction": faction, "kind": kind,
        "summary": str(payload.get("summary") or "").strip()[:400],
        "reward": str(payload.get("reward") or "").strip()[:400],
        "html": html, "parents": parents,
        "map_layer": map_layer if pts else "", "map_points": pts,
        "sort": sort, "published": bool(payload.get("published", False)),
    }


@router.post("/admin/quests")
async def admin_quest_save(request: Request, payload: dict = Body(...)):
    """Создать (без id) или сохранить (с id) квест — только админ."""
    _require_admin(request)
    qid = payload.get("id")
    qid = int(qid) if qid is not None else None
    data = _clean_quest(payload, qid)
    if qid is None:
        return quests.create(data)
    saved = quests.update(qid, data)
    if not saved:
        raise HTTPException(404, "quest not found")
    return saved


@router.delete("/admin/quests/{qid}")
async def admin_quest_delete(request: Request, qid: int):
    """Удалить квест (только админ). Связи на него у остальных чистятся."""
    _require_admin(request)
    if not quests.delete(qid):
        raise HTTPException(404, "quest not found")
    return {"ok": True}


# ---------- комментарии под статьями (патчи/гайды; page_key универсальный) ----------

_comment_last_post: dict[int, float] = {}   # антифлуд, как в чате

_PAGE_KEY_RE = re.compile(r"^(patch|guide|item):[\w.-]{1,64}$")


def _valid_page(page: str) -> bool:
    """Ключ страницы валиден и указывает на существующий объект."""
    if not _PAGE_KEY_RE.match(page or ""):
        return False
    kind, _, ref = page.partition(":")
    if kind == "patch":
        return ref.isdigit() and news.patch_meta(int(ref)) is not None
    if kind == "item":
        return db.item(ref) is not None
    if kind == "guide":
        return guides.exists(ref)
    return True


@router.get("/comments")
async def comments_list(page: str, after: int = 0):
    """Комментарии страницы (читать может любой)."""
    if not _PAGE_KEY_RE.match(page or ""):
        raise HTTPException(422, "bad page key")
    msgs = news.list_comments(page, after=after)
    return {"comments": msgs, "last_id": msgs[-1]["id"] if msgs else after}


@router.post("/comments")
async def comments_post(request: Request, payload: dict = Body(...)):
    """Оставить комментарий — только вошедшим через EXBO. Антифлуд 3с."""
    user = current_user(request)
    if not user:
        raise HTTPException(401, "не авторизован")
    page = str(payload.get("page") or "")
    if not _valid_page(page):
        raise HTTPException(422, "bad page key")
    text = "\n".join(line.rstrip() for line in
                     str(payload.get("text") or "").strip().splitlines())[:news.COMMENT_MAX_LEN]
    if not text.strip():
        raise HTTPException(422, "пустой комментарий")
    now = time.time()
    if now - _comment_last_post.get(user["id"], 0) < 3:
        raise HTTPException(429, "слишком часто — подожди пару секунд")
    _comment_last_post[user["id"]] = now
    cid = news.add_comment(page, user["id"],
                           user.get("display_login") or user["login"], text)
    return {"ok": True, "id": cid}


@router.delete("/comments/{cid}")
async def comments_delete(cid: int, request: Request):
    """Удалить комментарий: свой — всегда, чужой — только админ (ADMIN_USER_IDS)."""
    user = current_user(request)
    if not user:
        raise HTTPException(401, "не авторизован")
    ok = news.delete_comment(cid, user["id"], is_admin(user))
    if not ok:
        raise HTTPException(403, "нельзя удалить этот комментарий")
    return {"ok": True}


# ---------- обменки: монеты Перекупщика ----------

@router.get("/exchange")
async def exchange_snapshot():
    """Позиции Перекупщика с курсом руб/монета (ручной JSON + живые цены)."""
    return exchange.snapshot()


@router.get("/exchange/plan")
async def exchange_plan(coins: int = Query(..., ge=1, le=100_000_000)):
    """Оптимальная корзина на N монет (жадно по курсу, с лимитами позиций)."""
    return exchange.plan(coins)


# ---------- чаты: общий и баги/предложения ----------

_chat_last_post: dict[int, float] = {}      # антифлуд: user_id -> ts последнего поста


@router.get("/chat/{room}")
async def chat_fetch(room: str, after: int = 0):
    """Сообщения комнаты (читать может любой). after — инкрементальная догрузка."""
    if room not in chat.ROOMS:
        raise HTTPException(404, "no such room")
    msgs = chat.fetch(room, after=after)
    return {"messages": msgs, "last_id": msgs[-1]["id"] if msgs else after}


@router.post("/chat/{room}")
async def chat_post(room: str, request: Request, payload: dict = Body(...)):
    """Отправка сообщения — только вошедшим через EXBO. Антифлуд 3с."""
    if room not in chat.ROOMS:
        raise HTTPException(404, "no such room")
    user = current_user(request)
    if not user:
        raise HTTPException(401, "не авторизован")
    text = " ".join(str(payload.get("text") or "").split())[:chat.MAX_LEN]
    if not text:
        raise HTTPException(422, "пустое сообщение")
    now = datetime.now().timestamp()
    if now - _chat_last_post.get(user["id"], 0) < 3:
        raise HTTPException(429, "слишком часто — подожди пару секунд")
    _chat_last_post[user["id"]] = now
    mid = chat.post(room, user["id"], user.get("display_login") or user["login"], text)
    return {"ok": True, "id": mid}


# ---------- топливо генератора: выгодные источники заправки (дашборд) ----------

@router.get("/fuel/top")
async def fuel_top(n: int = Query(5, ge=1, le=20)):
    """Самые выгодные источники энергии (₽ за 1000 ед.), по 50 последним продажам."""
    src = fuel_svc.sources()
    return {"sources": src[:n], "total": len(src)}


# ---------- топ продаваемых (дашборд) ----------

@router.get("/sales/top")
async def sales_top(n: int = 10):
    """Самые продаваемые предметы: сейчас (последние сделки) и в среднем за неделю."""
    def rows(pairs):
        return [{**_item_brief(iid), "per_day": round(rate * 24)} for iid, rate in pairs]
    return {"today": rows(sstats.today_top(n)),
            "week": rows(sstats.week_top(n)),
            "snapshots": len(sstats.snaps)}


# ---------- актуальный ящик сезона (дашборд) ----------

@router.get("/box")
async def season_box():
    """Карточка актуального ящика. Пока item-id не известен — missing:true."""
    if not config.DASH_BOX_ID or not db.item(config.DASH_BOX_ID):
        return {"missing": True, "name": config.DASH_BOX_NAME}
    store.request([config.DASH_BOX_ID])          # греть цену приоритетно
    return {"missing": False, **_item_brief(config.DASH_BOX_ID)}


# ---------- полный аукцион: живые лоты и история по предмету ----------

_market_cache: dict[str, tuple[float, dict]] = {}
_market_lock = asyncio.Lock()


def _item_brief(iid: str) -> dict:
    it = db.item(iid) or {}
    p = store.prices.get(iid) or {}
    h = store.history.get(iid) or {}
    return {"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT"),
            "min_buyout": p.get("min_buyout"), "avg": h.get("avg_unit_price"),
            "sales_per_hour": h.get("sales_per_hour")}


@router.get("/market/overview")
async def market_overview():
    """Подборки полного аукциона из тёплого кэша цен (без внешних запросов)."""
    rows = [_item_brief(iid) for iid in store.prices]
    liquid = sorted((r for r in rows if r["sales_per_hour"]),
                    key=lambda r: -r["sales_per_hour"])[:15]
    expensive = sorted((r for r in rows if r["min_buyout"]),
                       key=lambda r: -r["min_buyout"])[:15]
    return {"liquid": liquid, "expensive": expensive,
            "tracked": len(rows)}


@router.get("/market/item/{item_id}")
async def market_item(item_id: str):
    """Живые лоты + недавние продажи предмета. Внешний API, кэш MARKET_CACHE_SEC."""
    it = db.item(item_id)
    if not it:
        raise HTTPException(404, "item not found")
    now = time.monotonic()
    cached = _market_cache.get(item_id)
    if cached and now - cached[0] < config.MARKET_CACHE_SEC:
        return cached[1]
    async with _market_lock:                     # не дублируем внешние запросы
        cached = _market_cache.get(item_id)
        if cached and time.monotonic() - cached[0] < config.MARKET_CACHE_SEC:
            return cached[1]
        async with httpx.AsyncClient(trust_env=False) as client:
            lots_raw = await auction.fetch_lots_page(client, item_id, limit=50)
            hist_raw = await auction.fetch_history_page(client, item_id, limit=50,
                                                        additional=False)
    sales_log.record(item_id, hist_raw.get("prices") or [])  # копим годовой график
    store.request_history(item_id)   # воркер продолжит снимать историю предмета
    lots = []
    for lot in (lots_raw.get("lots") or []):
        amount = lot.get("amount") or 1
        bp = lot.get("buyoutPrice")
        lots.append({
            "amount": amount,
            "buyout": bp,
            "unit": round(bp / amount) if bp else None,
            "current": lot.get("currentPrice") or lot.get("startPrice"),
            "end": lot.get("endTime"),
        })
    sales = [{"time": e.get("time"),
              "amount": e.get("amount") or 1,
              "price": e.get("price"),
              "unit": round(e["price"] / (e.get("amount") or 1)) if e.get("price") else None}
             for e in (hist_raw.get("prices") or [])]
    res = {"item": _item_brief(item_id),
           "lots_total": lots_raw.get("total"),
           "lots": lots, "sales": sales,
           "error": lots_raw.get("error") or hist_raw.get("error")}
    _market_cache[item_id] = (time.monotonic(), res)
    if len(_market_cache) > 500:                 # не разъедаемся
        oldest = min(_market_cache, key=lambda k: _market_cache[k][0])
        del _market_cache[oldest]
    return res


@router.get("/market/item/{item_id}/sales")
async def market_item_sales(item_id: str,
                            days: float = Query(7.0, ge=0.04, le=366.0),
                            since: str | None = None, until: str | None = None):
    """Серия продаж предмета для графика: часы в свежем окне, дальше — дни.

    Данные копятся пассивно из ответов истории аука (sales_log), ретенция —
    год. since/until — 'YYYY-MM-DDTHH:00' МСК (масштабирование выделением);
    без них окно = последние `days` суток.
    """
    if not db.item(item_id):
        raise HTTPException(404, "item not found")

    def _pdt(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).replace(tzinfo=MSK)
        except ValueError:
            return None

    now = datetime.now(MSK)
    u = min(_pdt(until) or now, now)
    s = _pdt(since) or (u - timedelta(days=days))
    s = max(s, now - timedelta(days=config.ITEM_SALES_KEEP_DAYS))
    if s >= u:
        s = u - timedelta(hours=1)
    hourly = (u - s <= timedelta(days=33)
              and s >= now - timedelta(days=config.ITEM_SALES_HOURLY_DAYS))
    u_slot = u.strftime("%Y-%m-%dT%H:59")
    if hourly:
        rows = market.item_sales_hourly(item_id, s.strftime("%Y-%m-%dT%H:00"), u_slot)
    else:  # окно ровняем на начало дня — не терять частичный первый день
        rows = market.item_sales_daily(item_id, s.strftime("%Y-%m-%dT00:00"), u_slot)
    for r in rows:
        r["avg"] = round(r["avg"])
        r["min"] = round(r["min"])
        r["max"] = round(r["max"])
    return {"granularity": "h" if hourly else "d",
            "since": s.strftime("%Y-%m-%dT%H:00"), "until": u.strftime("%Y-%m-%dT%H:00"),
            "first": market.item_sales_first(item_id),
            "hourly_days": config.ITEM_SALES_HOURLY_DAYS,
            "keep_days": config.ITEM_SALES_KEEP_DAYS,
            "series": rows}


# ---------- интерактивная карта ----------

# Двухуровневая карта как в игре: глобальная (pda/global_map, стилизованный
# коллаж миров 18432×8192) и детальная (pda/map, общий план 1px=1блок,
# начало — регион (-86,-38)). Пирамиды: scripts/gen_map_pyramid.py и
# scripts/gen_detail_pyramid.py. Клик по территории на глобальной открывает
# её фрагмент детальной.
#
# label — px на глобальной; bbox — регионы детального плана (x0,y0,x1,y1 вкл.).
# Позиции получены сопоставлением планов (FFT-корреляция, якоря Бар и Кузня-11,
# масштаб глобальной ≈ 1.7 блока/px) + визуальной привязкой. closed — территория
# сейчас закрыта в игре (как на игровой глобальной карте).
_DETAIL_X0, _DETAIL_Y0 = -86, -38                  # регион (0,0) детальной пирамиды


def _bbox_px(x0: int, y0: int, x1: int, y1: int) -> list[int]:
    """Регионы (вкл.) → px детального плана."""
    return [(x0 - _DETAIL_X0) * 512, (y0 - _DETAIL_Y0) * 512,
            (x1 - _DETAIL_X0 + 1) * 512, (y1 - _DETAIL_Y0 + 1) * 512]


MAP_TERRITORIES = [
    {"id": "south", "name": "Южная Зона", "label": [8490, 4700],
     "bbox": _bbox_px(-14, -3, -4, 13)},
    {"id": "sever", "name": "Северная Зона", "label": [6000, 3000],
     "bbox": _bbox_px(-27, 0, -13, 10)},
    {"id": "wnorth", "name": "Дикий Север", "label": [9900, 3450],
     "bbox": _bbox_px(12, -3, 18, 3)},
    {"id": "limansk", "name": "Любеч-3", "label": [7050, 5250],
     "bbox": _bbox_px(-4, -2, 0, 2)},
    {"id": "dmz", "name": "Бораль", "label": [5700, 6200],
     "bbox": _bbox_px(6, -3, 11, 3), "closed": True},
    {"id": "pripyat", "name": "Припять", "label": [8670, 1340], "closed": True},
    {"id": "cnpp", "name": "ЧАЭС", "label": [9750, 2150], "closed": True},
]

# Категории меток DEV-редактора: id → значок (emoji) + цвет. Расширяется свободно;
# фронт рисует иконку/цвет и фильтры-слои из этого списка (приходит в /map/meta).
MAP_CATEGORIES = [
    {"id": "stash",      "name": "Тайник",         "emoji": "🧰", "color": "#ffb84d"},
    {"id": "loot",       "name": "Контейнер / лут", "emoji": "📦", "color": "#7ce68e"},
    {"id": "anomaly",    "name": "Аномалия",       "emoji": "☢",  "color": "#b48cff"},
    {"id": "danger",     "name": "Опасность",      "emoji": "☠",  "color": "#ff6b5e"},
    {"id": "npc",        "name": "NPC / Торговец",  "emoji": "👤", "color": "#5fa8ff"},
    {"id": "quest",      "name": "Квест",          "emoji": "❗", "color": "#e8d44d"},
    {"id": "spawn",      "name": "Точка входа",    "emoji": "⚑",  "color": "#5fd67a"},
    {"id": "transition", "name": "Переход",        "emoji": "🚪", "color": "#9ecbff"},
    {"id": "poi",        "name": "Точка интереса", "emoji": "📍", "color": "#dff5df"},
]
_MAP_CAT_IDS = {c["id"] for c in MAP_CATEGORIES}
_MAP_KINDS = {"marker", "area", "line"}
_MAP_LAYERS = {"global", "detail"}

MAP_META = {
    "global": {"w": 18432, "h": 8192, "tile_size": 256, "min_zoom": 0, "max_zoom": 6,
               "tile_url": "wmap/{z}/{x}/{y}.webp"},
    "detail": {"w": 112128, "h": 51712, "tile_size": 256, "min_zoom": 0, "max_zoom": 6,
               "tile_url": "dmap/{z}/{x}/{y}.webp"},
    "territories": MAP_TERRITORIES,
    "categories": MAP_CATEGORIES,
}


@router.get("/map/meta")
async def map_meta():
    """Параметры тайловой карты, территории и категории меток для Leaflet."""
    return MAP_META


def _require_admin(request: Request) -> dict:
    """Пользователь-админ (ADMIN_USER_IDS) или 403 — гейт DEV-инструментов."""
    user = current_user(request)
    if not is_admin(user):
        raise HTTPException(403, "только для админов")
    return user


@router.post("/dev/ab")
async def dev_ab_override(request: Request, payload: dict = Body(...)):
    """Админ форсит себе вариант дизайна для предпросмотра (cookie sz_ab_force).
    variant: 'A'|'B' — показать вариант; иначе — сброс (снять форс). Действует
    только на самого админа (его cookie), сплит обычных посетителей не трогает."""
    _require_admin(request)
    v = str(payload.get("variant") or "").upper()
    resp = JSONResponse({"ok": True, "variant": v if v in ("A", "B") else None})
    if v in ("A", "B"):
        resp.set_cookie(config.AB_TEST_FORCE_COOKIE, v, max_age=30 * 86400,
                        path="/", httponly=True, samesite="lax",
                        secure=str(request.base_url).startswith("https"))
    else:
        resp.delete_cookie(config.AB_TEST_FORCE_COOKIE, path="/")
    return resp


def _clean_map_geometry(kind: str, geom) -> list:
    """Проверка/нормализация геометрии по типу объекта (см. db/mapobjects)."""
    if kind == "marker":
        if not isinstance(geom, (list, tuple)) or len(geom) != 2:
            raise HTTPException(422, "geometry метки: [x, y]")
        try:
            return [round(float(geom[0]), 2), round(float(geom[1]), 2)]
        except (TypeError, ValueError):
            raise HTTPException(422, "geometry: числа")
    min_pts = 3 if kind == "area" else 2
    if not isinstance(geom, (list, tuple)) or len(geom) < min_pts:
        raise HTTPException(422, f"нужно ≥{min_pts} вершин")
    pts = []
    for p in geom:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise HTTPException(422, "вершина: [x, y]")
        try:
            pts.append([round(float(p[0]), 2), round(float(p[1]), 2)])
        except (TypeError, ValueError):
            raise HTTPException(422, "geometry: числа")
    return pts


def _clean_map_payload(payload: dict, *, creating: bool) -> dict:
    """Санитайз тела метки/области; при создании требует kind/layer/geometry."""
    out: dict = {}
    if creating:
        kind = str(payload.get("kind") or "")
        layer = str(payload.get("layer") or "")
        if kind not in _MAP_KINDS:
            raise HTTPException(422, "kind: marker|area|line")
        if layer not in _MAP_LAYERS:
            raise HTTPException(422, "layer: global|detail")
        out["kind"] = kind
        out["layer"] = layer
        out["geometry"] = _clean_map_geometry(kind, payload.get("geometry"))
    elif "geometry" in payload:
        # тип берём из существующего объекта — проверит вызывающий
        out["geometry"] = payload.get("geometry")
    if "category" in payload:
        cat = payload.get("category")
        out["category"] = cat if cat in _MAP_CAT_IDS else None
    if "name" in payload:
        out["name"] = str(payload.get("name") or "").strip()[:120]
    if "description" in payload:
        out["description"] = str(payload.get("description") or "").strip()[:2000]
    if "color" in payload:
        col = str(payload.get("color") or "").strip()
        out["color"] = col[:16] if col else None
    if "published" in payload:
        out["published"] = bool(payload.get("published"))
    return out


@router.get("/map/objects")
async def map_objects_list(request: Request, layer: str | None = None):
    """Метки/области карты. Публично — только опубликованные; админу — с черновиками."""
    user = current_user(request)
    admin = is_admin(user)
    if layer and layer not in _MAP_LAYERS:
        raise HTTPException(422, "layer: global|detail")
    return {"objects": mapobjects.list_objects(layer=layer, include_drafts=admin),
            "is_admin": admin}


@router.post("/map/objects")
async def map_object_create(request: Request, payload: dict = Body(...)):
    """Создать метку/область (только админ). Возвращает созданный объект."""
    user = _require_admin(request)
    obj = _clean_map_payload(payload, creating=True)
    oid = mapobjects.create(obj, user["id"])
    return mapobjects.get(oid)


@router.put("/map/objects/{oid}")
async def map_object_update(oid: int, request: Request, payload: dict = Body(...)):
    """Изменить объект (только админ): любые поля, включая геометрию и публикацию."""
    _require_admin(request)
    existing = mapobjects.get(oid)
    if not existing:
        raise HTTPException(404, "объект не найден")
    fields = _clean_map_payload(payload, creating=False)
    if "geometry" in fields:
        fields["geometry"] = _clean_map_geometry(existing["kind"], fields["geometry"])
    if not mapobjects.update(oid, fields):
        raise HTTPException(422, "нечего обновлять")
    return mapobjects.get(oid)


@router.delete("/map/objects/{oid}")
async def map_object_delete(oid: int, request: Request):
    """Удалить объект (только админ)."""
    _require_admin(request)
    if not mapobjects.delete(oid):
        raise HTTPException(404, "объект не найден")
    return {"ok": True}


# ---------- калькулятор сборок ----------

@router.get("/build/dict")
async def build_dictionary():
    """Справочник: контейнеры, каталог статов, артефакты с окнами статов, модель."""
    return builds.build_dict()


@router.post("/build/auto")
async def build_auto(payload: dict = Body(...)):
    """Автоподбор сборки: {budget, container, stats: [{key, weight 0-100}]}."""
    try:
        budget = float(payload.get("budget", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "budget must be a number")
    res = builds.auto_build(budget, str(payload.get("container", "")),
                            payload.get("stats") or [])
    if res.get("error") in ("container_not_found", "bad_request"):
        raise HTTPException(422, res["error"])
    return res  # включая error=no_priced_variants с подсказкой — фронт покажет


@router.get("/build/daily")
async def build_daily():
    """Случайная «сборка дня» для главной: броня + контейнер топ-редкости, бюджет
    и 1–3 стата — ролл фиксирован датой (МСК), сборка кэшируется раз в сутки."""
    return builds.daily_build()


@router.post("/build/hp")
async def build_hp(payload: dict = Body(...)):
    """Автоподбор на приведённое ХП: {budget, container, armor, armor_ptn}."""
    try:
        budget = float(payload.get("budget", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "budget must be a number")
    res = builds.auto_hp(budget, str(payload.get("container", "")),
                         str(payload.get("armor", "")), int(payload.get("armor_ptn", 0)))
    if res.get("error") in ("container_not_found", "armor_not_found", "bad_request"):
        raise HTTPException(422, res["error"])
    return res


@router.get("/health")
async def health():
    return {"status": "ok", "items": len(db.items),
            "craft_results": len(db.recipe_by_result),
            "region": config.REGION,
            "demo": "dapi." in config.API_BASE,
            "token": bool(oauth.token() or config.API_TOKEN),
            "users": users.stats(),
            "prices": store.stats(),
            "artmarket": market.stats(),
            "item_sales": market.item_sales_stats(),
            "artlots": artlots.stats()}
