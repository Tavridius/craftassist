"""HTTP API: поиск, инфо о предмете, цена, расчёт крафта, рейтинги.

Данные — из тёплых кэшей (GameDB + PriceStore); исключение — /market/item/{id}
(живые лоты полного аукциона): внешний запрос по требованию с коротким кэшем.
"""
import asyncio
import base64
import binascii
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta

import httpx
from fastapi import (APIRouter, Body, HTTPException, Query, Request, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import JSONResponse

from app import config
from app.db import (chat, craft_tuning, guides, mapobjects, market, news,
                    operations as ops, promos, quests, sitenews, users)
from app.db.index import db
from app.routers.auth import SESSION_COOKIE, current_user, is_admin
from app.services import (auction, barter, builds, compare, craft, exchange,
                          hideout, oauth, sales_log)
from app.services import fuel as fuel_svc
from app.services.artefact_lots import artlots
from app.services.artefact_watch import MSK
from app.services.emission_watch import ewatch
from app.services.ingredient_watch import watch
from app.services.market_scan import scan
from app.services.sales_stats import sstats
from app.services.price_store import store
from app.services.rankings import rankings

logger = logging.getLogger(__name__)

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


# ---------- База предметов (вкладка-каталог) ----------
# группы вкладки → категории пути данных (см. db.category)
_ITEM_CAT_GROUPS = {
    "weapon": ["weapon"],
    "armor": ["armor"],
    "container": ["containers", "backpacks"],
    "artefact": ["artefact"],
    "attachment": ["attachment", "weapon_modules"],
    "bullet": ["bullet"],
    "medicine": ["medicine"],
    "grenade": ["grenade"],
    "misc": ["misc", "supply", "device", "other"],
    # псевдогруппа для подбора в сравнение: всё, у чего есть тултип-статы
    "gear": list(compare.COMPARABLE_CATS),
}
_ALL_ITEM_CATS = [c for cs in _ITEM_CAT_GROUPS.values() for c in cs]
_RANK_W = {"RANK_LEGEND": 6, "RANK_MASTER": 5, "RANK_VETERAN": 4, "RANK_STALKER": 3,
           "RANK_NEWBIE": 2, "QUEST_ITEM": 1, "DEFAULT": 0}


def _item_row(iid: str) -> dict:
    it = db.item(iid) or {}
    return {"id": iid, "name": it.get("name", iid), "name_en": it.get("name_en", ""),
            "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
            "category": db.category(iid), "craftable": bool(db.recipe_by_result.get(iid))}


@router.get("/items")
async def items(cat: str = "", q: str = "", limit: int = Query(60, ge=1, le=200),
                offset: int = 0):
    """Каталог предметов для вкладки «База предметов»: фильтр по группе категории
    и/или поиск по имени. Сортировка — по редкости (круче выше), затем имя."""
    cats = _ITEM_CAT_GROUPS.get(cat)
    if q.strip():
        rows = db.search(q, 500)
        ids = [it["id"] for it in rows
               if not cats or db.category(it["id"]) in cats]
    else:
        ids = db.category_ids(*(cats or _ALL_ITEM_CATS))
        ids.sort(key=lambda i: (-_RANK_W.get((db.item(i) or {}).get("color"), 0),
                                (db.item(i) or {}).get("name", "")))
    total = len(ids)
    return {"total": total, "offset": offset, "limit": limit,
            "items": [_item_row(i) for i in ids[offset:offset + limit]]}


@router.get("/compare")
async def compare_items(ids: str = "", ptn: int = Query(0, ge=0, le=compare.MAX_PTN)):
    """Сравнение снаряжения: до MAX_ITEMS предметов, ids через запятую.
    ptn — общий уровень заточки (статы читаются из вариантов игровой базы)."""
    wanted = [s.strip() for s in ids.split(",") if s.strip()][:compare.MAX_ITEMS * 2]
    return compare.build(wanted, ptn)


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
    res = craft.analyze(item_id, fuel_src=fuel_src, profile=prof)
    # характеристики предмета (оружие/броня и т.д.) + категория — для карточки
    res["characteristics"] = db.characteristics(item_id)
    res["category"] = db.category(item_id)
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
    qlt/ptn = -1 — любые. Заточка — корзинами +0/+5/+10/+15 (market.ptn_bucket).
    Корзины с < ART_MIN_SALES продаж в любом окне не участвуют.
    """
    if ptn >= 0:
        ptn = market.ptn_bucket(ptn)
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
    url = str(payload.get("url") or "").strip()
    if url and not re.match(r"^https?://", url):
        raise HTTPException(422, "ссылка должна начинаться с http:// или https://")
    if not code and not url:
        raise HTTPException(422, "нужен сам промокод или ссылка (Steam DLC)")
    expires = str(payload.get("expires_at") or "").strip()[:16]
    if expires:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", expires):
            expires += "T23:59"     # дата без времени = до конца дня включительно
        elif not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", expires):
            raise HTTPException(422, "срок: YYYY-MM-DD или YYYY-MM-DDTHH:MM (МСК)")
    # описание — доверенный HTML (пишут админы), рендерится в карточке на /promo
    return {
        "title": title[:200], "code": code[:64], "url": url[:400],
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


# ---------- поиск прямо из модулей главной ----------
# Обычный /search отдаёт только имя с иконкой — в модулях главной этого мало:
# там строки с цифрой (выгода за цикл / темп продаж), и результат поиска должен
# выглядеть так же, иначе он читается как чужой блок. Цифры берём из тёплых
# кэшей: выгоду — из rankings.rows (полный проход там уже сделан), темп продаж —
# из истории цен. Ни одного обращения к внешнему API.

@router.get("/home/search")
async def home_search(q: str = Query(..., min_length=1), kind: str = "craft",
                      limit: int = Query(8, ge=1, le=20)):
    """Поиск для модуля главной. kind=craft — только крафтящееся, со строкой
    выгоды; kind=market — что угодно, со строкой темпа продаж и ценой."""
    if kind not in ("craft", "market"):
        raise HTTPException(422, "kind: craft или market")
    found = db.search(q, limit * 4)
    out = []
    if kind == "craft":
        rankings.compute()          # прогреть/освежить rows (внутри TTL-кэш)
        for it in found:
            iid = it["id"]
            if iid not in db.recipe_by_result:
                continue            # некрафтящееся в этом модуле бессмысленно
            r = rankings.rows.get(iid) or {}
            out.append({"id": iid, "name": it.get("name", iid),
                        "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
                        "diff": r.get("diff"), "pct": r.get("pct"),
                        "sell_price": r.get("sell_price"), "buy_price": r.get("buy_price")})
            if len(out) >= limit:
                break
    else:
        for it in found[:limit]:
            b = _item_brief(it["id"])
            sph = b.get("sales_per_hour")
            out.append({**b, "per_day": round(sph * 24) if sph else None})
    return {"query": q, "kind": kind, "items": out}


# ---------- новости САЙТА: гибридная лента (ручные посты + автособытия) ----------
# Ручное — db/sitenews. Автособытия НЕ дублируются в базу: берём их из живых
# источников (гайды, промокоды, патчи) прямо на чтении. Так удаление гайда или
# протухание промокода убирает запись из ленты само, без синхронизации.

_NEWS_TAGS = {"guide": "ГАЙД", "promo": "ПРОМОКОД", "patch": "ПАТЧ ИГРЫ"}


def _news_auto() -> list[dict]:
    """Автозаписи ленты из уже готовых разделов. Ошибка любого источника не
    должна ронять колонку на главной — поэтому каждый в своём try."""
    out: list[dict] = []
    try:
        for g in guides.list_guides()[:6]:
            out.append({"kind": "guide", "id": f"guide:{g['slug']}",
                        "title": g["title"], "body": g.get("description", ""),
                        "url": f"/guides/{g['slug']}", "tag": _NEWS_TAGS["guide"],
                        "created_at": g["created_at"], "pinned": False})
    except Exception:
        logger.exception("news feed: guides")
    try:
        for p in promos.list_promos()[:4]:
            body = f"Промокод {p['code']}" if p.get("code") else ""
            if p.get("expires_at"):
                body += f" · действует до {p['expires_at'][:10]}"
            out.append({"kind": "promo", "id": f"promo:{p['id']}",
                        "title": p["title"], "body": body.strip(),
                        "url": "/promo", "tag": _NEWS_TAGS["promo"],
                        "created_at": p["created_at"], "pinned": False})
    except Exception:
        logger.exception("news feed: promos")
    try:
        items, _ = news.list_patches(0, 4)
        for p in items:
            out.append({"kind": "patch", "id": f"patch:{p['id']}",
                        "title": p["title"], "body": (p.get("anons") or "")[:300],
                        "url": f"/patches/{p['id']}", "tag": _NEWS_TAGS["patch"],
                        # у патчей дата с временем — в ленте нужна только дата
                        "created_at": (p.get("created_at") or "")[:10], "pinned": False})
    except Exception:
        logger.exception("news feed: patches")
    return out


@router.get("/news/feed")
async def news_feed(limit: int = Query(14, ge=1, le=50)):
    """Лента новостей сайта для колонки на главной: закреплённое сверху,
    дальше всё вперемешку по дате (свежее первым)."""
    manual = sitenews.list_posts()
    for m in manual:
        m["id"] = f"post:{m['id']}"
    feed = manual + _news_auto()
    feed.sort(key=lambda x: (x.get("pinned", False), x.get("created_at") or ""),
              reverse=True)
    return {"items": feed[:limit], "total": len(feed)}


def _clean_news(payload: dict) -> dict:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "нужен заголовок")
    url = str(payload.get("url") or "").strip()
    if url and not url.startswith("/"):
        raise HTTPException(422, "ссылка: внутренний путь, начинается с /")
    created = str(payload.get("created_at") or "").strip()[:10]
    if created and not re.match(r"^\d{4}-\d{2}-\d{2}$", created):
        raise HTTPException(422, "дата: YYYY-MM-DD")
    return {
        "title": title[:sitenews.TITLE_MAX],
        "body": str(payload.get("body") or "").strip()[:sitenews.BODY_MAX],
        "url": url[:200], "tag": str(payload.get("tag") or "").strip()[:32],
        "pinned": bool(payload.get("pinned")),
        "published": bool(payload.get("published", True)),
        "created_at": created,
    }


@router.get("/admin/news")
async def admin_news_list(request: Request):
    """Все посты, включая черновики (только админ)."""
    _require_admin(request)
    return {"items": sitenews.list_posts(include_drafts=True)}


@router.post("/admin/news")
async def admin_news_save(request: Request, payload: dict = Body(...)):
    """Создать (без id) или сохранить (с id) новость сайта — только админ."""
    _require_admin(request)
    pid = payload.get("id")
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "id: число")
    saved = sitenews.save(pid, _clean_news(payload))
    if not saved:
        raise HTTPException(404, "post not found")
    return saved


@router.delete("/admin/news/{pid}")
async def admin_news_delete(request: Request, pid: int):
    """Удалить новость сайта (только админ)."""
    _require_admin(request)
    if not sitenews.delete(pid):
        raise HTTPException(404, "post not found")
    return {"ok": True}


# ---------- ДЕВ · сверка рецептов верстака с игрой (см. db/craft_tuning) ----------

def _dev_craft_item(iid: str) -> dict:
    it = db.item(iid) or {}
    return {"id": iid, "name": it.get("name", iid), "icon": it.get("icon", "")}


@router.get("/admin/craft/recipes")
async def admin_craft_recipes(request: Request):
    """Все рецепты верстака: исходник EXBO + текущий тюнинг (bonus/правки)."""
    _require_admin(request)
    tuning = craft_tuning.get_all()
    items = []
    for rid in sorted(db.recipe_by_result):
        for r in db.recipe_by_result.get(rid, []):   # исходники, БЕЗ наложения правок
            if r.get("key", "").rsplit(":", 1)[0] != rid:
                continue    # рецепт с несколькими результатами — показываем один раз
            req = r.get("requirements") or {}
            t = tuning.get(r["key"]) or {}
            items.append({
                "key": r["key"],
                "result": {**_dev_craft_item(rid),
                           "amount": next((x.get("amount") or 1 for x in r.get("result", [])
                                           if x.get("item") == rid), 1)},
                "bench": r.get("bench"), "category": r.get("category"),
                "subcategory": r.get("subcategory"),
                "energy": r.get("energy"),
                "perks": req.get("perks") or {},
                "features": req.get("features") or [],
                "ingredients": [{**_dev_craft_item(i["item"]), "amount": i.get("amount", 1)}
                                for i in r.get("ingredients", [])],
                "bonus": t.get("bonus"),
                "tuned": t.get("data") or None,
            })
    checked = sum(1 for i in items if i["bonus"] is not None)
    return {"items": items, "total": len(items), "checked": checked,
            "perk_names": {p["id"]: p["name"] for p in db.hideout_perks}}


@router.put("/admin/craft/recipes/{rkey}")
async def admin_craft_recipe_save(request: Request, rkey: str,
                                  payload: dict = Body(...)):
    """Сохранить сверку рецепта: флаг бонусного крафта + правки данных.

    payload: {bonus: 1|0|null, energy?: число|null, result_amount?: число|null,
    perk_level?: число|null, ingredients?: {item_id: число≥0}|null}.
    Отсутствие поля/None = правки нет (используются данные EXBO)."""
    _require_admin(request)
    known = {r.get("key") for rs in db.recipe_by_result.values() for r in rs}
    if rkey not in known:
        raise HTTPException(404, "recipe not found")
    bonus = payload.get("bonus")
    if bonus not in (None, 0, 1):
        raise HTTPException(422, "bonus: 1, 0 или null")

    def _num(key, lo, hi, integer=False):
        v = payload.get(key)
        if v is None:
            return None
        try:
            v = int(v) if integer else float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{key}: число")
        if not lo <= v <= hi:
            raise HTTPException(422, f"{key}: диапазон {lo}..{hi}")
        return v

    data = {}
    if (v := _num("energy", 0, 10 ** 6)) is not None:
        data["energy"] = v
    if (v := _num("result_amount", 1, 10 ** 4, integer=True)) is not None:
        data["result_amount"] = v
    if (v := _num("perk_level", 1, hideout.PERK_MAX, integer=True)) is not None:
        data["perk_level"] = v
    if isinstance(payload.get("ingredients"), dict):
        ings = {}
        for iid, amt in payload["ingredients"].items():
            try:
                amt = int(amt)
            except (TypeError, ValueError):
                raise HTTPException(422, "ingredients: количества — числа")
            if not 0 <= amt <= 10 ** 4:
                raise HTTPException(422, "ingredients: диапазон 0..10000")
            ings[str(iid)] = amt
        if ings:
            data["ingredients"] = ings
    craft_tuning.save(rkey, bonus, data or None)
    return {"ok": True, "key": rkey, "bonus": bonus, "tuned": data or None}


# ---------- квесты: блок-схемы линеек + прохождение (см. db/quests) ----------

# Линейки квестов. Фронт рисует вкладки и цвета из этого списка — расширяется
# свободно (id менять нельзя — они записаны в строках quests.faction).
QUEST_FACTIONS = [
    {"id": "stalkers", "name": "Сталкеры", "color": "#7ce68e"},
    {"id": "bandits",  "name": "Бандиты",  "color": "#ffb84d"},
    {"id": "covenant", "name": "Завет",    "color": "#5fa8ff"},
    {"id": "dawn",     "name": "Заря",     "color": "#e8d44d"},
    # id остаётся duty (записан в строках квестов), имя — актуальное игровое:
    # патч 10.07.2024 переименовал Долг → Рубеж, Свободу → Заря, Монолит → Шёпот
    {"id": "duty",     "name": "Рубеж",    "color": "#ff6b5e"},
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
            "groups": quests.groups_list(),
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
    # доп. линейки (общий/вступительный квест): показываем ещё и там; primary исключаем
    factions: list[str] = []
    for fx in (payload.get("factions") or []):
        fx = str(fx)
        if fx in _QUEST_FACTION_IDS and fx != faction and fx not in factions:
            factions.append(fx)
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
        "title": title[:200], "faction": faction, "factions": factions, "kind": kind,
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


@router.post("/admin/quests/{qid}/pos")
async def admin_quest_pos(qid: int, request: Request, payload: dict = Body(...)):
    """Сохранить позицию блока на сетке линейки (перетаскивание в схеме)."""
    _require_admin(request)
    faction = str(payload.get("faction") or "")
    if faction not in _QUEST_FACTION_IDS:
        raise HTTPException(422, "неизвестная линейка")
    try:
        col = max(0, min(200, int(payload.get("col"))))
        row = max(0, min(200, int(payload.get("row"))))
    except (TypeError, ValueError):
        raise HTTPException(422, "col/row — целые")
    if not quests.set_pos(qid, faction, col, row):
        raise HTTPException(404, "quest not found")
    return {"ok": True, "col": col, "row": row}


@router.post("/admin/quests/{qid}/parents")
async def admin_quest_parents(qid: int, request: Request, payload: dict = Body(...)):
    """Пересохранить связи «открывается после» — рисование/удаление стрелок на дев-карте."""
    _require_admin(request)
    if not quests.exists(qid):
        raise HTTPException(404, "quest not found")
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
    quests.set_parents(qid, parents)
    return {"ok": True, "parents": parents}


# ---------- группы квестов (сворачиваемый модуль на карте линеек) ----------

def _clean_members(payload: dict) -> list[int]:
    members: list[int] = []
    for m in (payload.get("members") or []):
        try:
            m = int(m)
        except (TypeError, ValueError):
            raise HTTPException(422, "members: список id")
        if m not in members and quests.exists(m):
            members.append(m)
    return members


@router.post("/admin/quest-groups")
async def admin_group_create(request: Request, payload: dict = Body(...)):
    """Создать группу из выбранных на карте квестов (только админ)."""
    _require_admin(request)
    faction = str(payload.get("faction") or "")
    if faction not in _QUEST_FACTION_IDS:
        raise HTTPException(422, "неизвестная линейка")
    members = _clean_members(payload)
    if len(members) < 2:
        raise HTTPException(422, "в группе нужно хотя бы 2 квеста")
    title = str(payload.get("title") or "").strip()[:200] or "Группа квестов"
    return quests.group_create(faction, title, members)


@router.post("/admin/quest-groups/{gid}")
async def admin_group_update(gid: int, request: Request, payload: dict = Body(...)):
    """Переименовать группу / переназначить состав (только админ)."""
    _require_admin(request)
    title = payload.get("title")
    if title is not None:
        title = str(title).strip()[:200] or "Группа квестов"
    members = _clean_members(payload) if payload.get("members") is not None else None
    saved = quests.group_update(gid, title=title, members=members)
    if not saved:
        raise HTTPException(404, "группа не найдена")
    return saved


@router.delete("/admin/quest-groups/{gid}")
async def admin_group_delete(gid: int, request: Request):
    """Разгруппировать (квесты остаются, группа удаляется) — только админ."""
    _require_admin(request)
    if not quests.group_delete(gid):
        raise HTTPException(404, "группа не найдена")
    return {"ok": True}


@router.post("/admin/quest-groups/{gid}/pos")
async def admin_group_pos(gid: int, request: Request, payload: dict = Body(...)):
    """Позиция модуля группы на сетке линейки (перетаскивание) — только админ."""
    _require_admin(request)
    faction = str(payload.get("faction") or "")
    if faction not in _QUEST_FACTION_IDS:
        raise HTTPException(422, "неизвестная линейка")
    try:
        col = max(0, min(200, int(payload.get("col"))))
        row = max(0, min(200, int(payload.get("row"))))
    except (TypeError, ValueError):
        raise HTTPException(422, "col/row — целые")
    if not quests.group_set_pos(gid, faction, col, row):
        raise HTTPException(404, "группа не найдена")
    return {"ok": True, "col": col, "row": row}


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
    """Карточка актуального ящика сезона.

    Сезонные лутбоксы (напр. «Тактический резерв», реестр lootbox.summer26) EXBO
    не выгружает в базу предметов/eapi — web-API-id для них не существует, поэтому
    цену с аука не достать (подробности в config.DASH_BOX_NAME). Отдаём
    missing:true, пока предмет не появится в базе (запрошено у ТП EXBO).
    """
    return {"missing": True, "name": config.DASH_BOX_NAME}


# ---------- Операции (PvE-режим): история сессий + мета снаряжения ----------

def _gear_brief(iid: str | None) -> dict | None:
    """Предмет снаряжения по id → имя/иконка/редкость. None — пусто; unknown=True —
    id не в базе игры (скрытые id EXBO, которых нет в stalzone-database) — фронт
    покажет плейсхолдер вместо битой иконки и мёртвой ссылки."""
    if not iid:
        return None
    it = db.item(iid)
    if it is None:
        return {"id": iid, "name": iid, "icon": "", "color": "DEFAULT", "unknown": True}
    return {"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
            "color": it.get("color", "DEFAULT")}


def _resolve_combo(c: dict) -> dict:
    """Строка меты (комбо/класс) → добавить резолв брони и оружия."""
    return {
        **c,
        "armor": _gear_brief(c.get("armor_item")),
        "weapon": _gear_brief(c.get("prim_item")),
        "avg_dur": round(c["avg_dur"]) if c.get("avg_dur") is not None else None,
        "min_dur": round(c["min_dur"]) if c.get("min_dur") is not None else None,
        # заточка — среднее по забегам; показываем целым (без десятых)
        "armor_lvl": round(c["armor_lvl"]) if c.get("armor_lvl") is not None else None,
        "prim_lvl": round(c["prim_lvl"]) if c.get("prim_lvl") is not None else None,
    }


def _resolve_class(c: dict) -> dict:
    """class_meta-запись → резолв топ-брони и топ-оружия для карточки класса."""
    armors = [{**a, "gear": _gear_brief(a["armor_item"]),
               "avg_dur": round(a["avg_dur"]) if a.get("avg_dur") is not None else None,
               "avg_lvl": round(a["avg_lvl"]) if a.get("avg_lvl") is not None else None}
              for a in c.get("armors", [])]
    weapons = [{**w, "gear": _gear_brief(w["prim_item"]),
                "avg_dur": round(w["avg_dur"]) if w.get("avg_dur") is not None else None,
                "avg_lvl": round(w["avg_lvl"]) if w.get("avg_lvl") is not None else None}
               for w in c.get("weapons", [])]
    return {"armor_class": c["armor_class"], "sessions": c["sessions"],
            "armors": armors, "weapons": weapons}


def _resolve_session(s: dict) -> dict:
    """Сырая сессия из БД → участники с резолвом снаряжения (для ленты/карточки)."""
    parts = []
    for p in s.get("parts", []):
        parts.append({
            **p,
            "armor": _gear_brief(p.get("armor_item")),
            "primary": _gear_brief(p.get("prim_item")),
            "secondary": _gear_brief(p.get("sec_item")),
        })
    return {**s, "parts": parts}


def _tier_arg(tier: str | None) -> int | None:
    """'low'|'mid'|'high' (или число 0/1/2) → int тира; иначе None (все этапы)."""
    if tier is None or tier == "" or tier == "all":
        return None
    if tier in ops.TIER_KEYS:
        return ops.TIER_KEYS.index(tier)
    if tier.isdigit() and int(tier) in (0, 1, 2):
        return int(tier)
    return None


def _meta_since() -> int:
    """Граница окна меты — начало текущей меты-недели (сброс по средам)."""
    return ops.week_start_ts()


def _meta_week() -> dict:
    ws = ops.week_start()
    return {"start": ws.isoformat(), "reset_dow": config.OPS_WEEK_RESET_DOW,
            "reset_hour": config.OPS_WEEK_RESET_HOUR,
            "next": (ws + timedelta(days=7)).isoformat()}


@router.get("/operations/overview")
async def operations_overview():
    """Модуль на главной: мета снаряжения по классам брони (в ротации).

    Берём высокий этап (эндгейм-мета — то, что ищут); если данных мало, откатываемся
    на все этапы, чтобы модуль не пустовал. Помечаем, какой этап показан.
    """
    since = _meta_since()
    st = ops.stats()
    tier_used = ops.TIER_HIGH
    classes = ops.class_meta(ops.TIER_HIGH, since, config.OPS_MIN_SAMPLE)
    if not classes:
        tier_used = None
        classes = ops.class_meta(None, since, config.OPS_MIN_SAMPLE)
    bounds = {b["tier"]: b for b in ops.tier_bounds()}
    return {
        "sessions": st["sessions"],
        "week": _meta_week(),
        "tier": bounds.get(tier_used) if tier_used is not None else None,
        "classes": [_resolve_class(c) for c in classes],
        "last_poll": ops.get_meta("last_poll"),
    }


@router.get("/operations/meta")
async def operations_meta(tier: str = "high"):
    """Мета этапа для страницы /operations: самые быстрые комбо снаряжения и
    разбивка по классам брони. tier: low|mid|high|all."""
    t = _tier_arg(tier)
    since = _meta_since()
    combos = ops.fastest_combos(t if t is not None else ops.TIER_HIGH, since,
                                config.OPS_MIN_SAMPLE) if t is not None else \
        ops.fastest_combos(ops.TIER_HIGH, since, config.OPS_MIN_SAMPLE)
    # для 'all' быстрые комбо считаем на высоком этапе (там гонка за временем),
    # классы — по выбранному фильтру
    classes = ops.class_meta(t, since, config.OPS_MIN_SAMPLE)
    summary = ops.tier_summary(since)
    bounds = ops.tier_bounds()
    return {
        "tier": tier, "week": _meta_week(),
        "min_sample": config.OPS_MIN_SAMPLE,
        "tiers": [{**b, "sessions": (summary.get(b["tier"]) or {}).get("n", 0),
                   "avg_dur": round(v["avg_dur"]) if (v := summary.get(b["tier"]))
                   and v.get("avg_dur") is not None else None} for b in bounds],
        "fastest": [_resolve_combo(c) for c in combos],
        "classes": [_resolve_class(c) for c in classes],
    }


@router.get("/operations/sessions")
async def operations_sessions(tier: str = "all", map: str | None = None,
                              limit: int = Query(40, ge=1, le=100), offset: int = 0):
    """Лента истории забегов: кто, с каким снаряжением, на какой сложности, за сколько."""
    t = _tier_arg(tier)
    rows = ops.recent_sessions(t, map, limit, offset)
    return {
        "total": ops.session_count(t, map),
        "tiers": ops.tier_bounds(),
        "maps": ops.maps(),
        "items": [_resolve_session(s) for s in rows],
    }


@router.get("/operations/player/{username}")
async def operations_player(username: str, limit: int = Query(40, ge=1, le=100)):
    """Забеги конкретного игрока (по нику из состава сессий)."""
    rows = ops.player_sessions(username, limit)
    return {"username": username, "count": len(rows),
            "items": [_resolve_session(s) for s in rows]}


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


# Во сколько раз выкуп может превышать цену реальных сделок, чтобы считаться
# ценой, а не «резервом». Лоты вида 9 999 999 999 ₽ выставляют, чтобы предмет
# висел, а не продавался: в рейтинге дорогих они шли первыми и вытесняли
# настоящие дорогие позиции.
_ASK_SANITY_FACTOR = 5.0


def _sane_ask(r: dict) -> bool:
    return not r["avg"] or r["min_buyout"] <= r["avg"] * _ASK_SANITY_FACTOR


@router.get("/market/overview")
async def market_overview():
    """Подборки полного аукциона из тёплого кэша цен (без внешних запросов)."""
    rows = [_item_brief(iid) for iid in store.prices]
    liquid = sorted((r for r in rows if r["sales_per_hour"]),
                    key=lambda r: -r["sales_per_hour"])[:15]
    expensive = sorted((r for r in rows if r["min_buyout"] and _sane_ask(r)),
                       key=lambda r: -r["min_buyout"])[:15]
    # оборот = прод/ч × 24 × средняя цена сделки: где крутятся деньги аука
    for r in rows:
        r["turnover"] = (r["sales_per_hour"] or 0) * 24 * (r["avg"] or 0)
    turnover = sorted((r for r in rows if r["turnover"]),
                      key=lambda r: -r["turnover"])[:15]
    return {"liquid": liquid, "expensive": expensive, "turnover": turnover,
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
            # limit не влияет на стоимость запроса — берём с запасом: лоты без
            # выкупа (только под ставку) отсеиваются ниже, а у артефактов и
            # снаряжения выборку ещё режет фильтр по качеству/заточке
            lots_raw = await auction.fetch_lots_page(client, item_id, limit=200)
            hist_raw = await auction.fetch_history_page(client, item_id, limit=100,
                                                        additional=True)
    sales_log.record(item_id, hist_raw.get("prices") or [])  # копим годовой график
    store.request_history(item_id)   # воркер продолжит снимать историю предмета
    lots = []
    for lot in (lots_raw.get("lots") or []):
        bp = lot.get("buyoutPrice")
        if not bp:
            continue   # выкупа нет (лот только под ставку) — цены у него нет
        amount = lot.get("amount") or 1
        add = lot.get("additional") or {}
        lots.append({
            "amount": amount,
            "buyout": bp,
            "unit": round(bp / amount),
            "current": lot.get("currentPrice") or lot.get("startPrice"),
            "end": lot.get("endTime"),
            "qlt": int(add.get("qlt") or 0), "ptn": int(add.get("ptn") or 0),
        })
    lots.sort(key=lambda x: x["unit"])   # API сортирует по цене лота, нам нужна за штуку
    sales = []
    for e in (hist_raw.get("prices") or []):
        amount, price = e.get("amount") or 1, e.get("price")
        add = e.get("additional") or {}
        sales.append({"time": e.get("time"), "amount": amount, "price": price,
                      "unit": round(price / amount) if price else None,
                      "qlt": int(add.get("qlt") or 0), "ptn": int(add.get("ptn") or 0)})
    # качество/заточка есть у артефактов и снаряжения — фронт покажет выбор корзины
    has_buckets = any(x["qlt"] or x["ptn"] for x in lots + sales)
    res = {"item": _item_brief(item_id),
           "lots_total": lots_raw.get("total"),
           "lots_buyout": len(lots),      # сколько из них с выкупом (остальные — ставки)
           "has_buckets": has_buckets,
           "lots": lots[:60], "sales": sales,
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
    # слои импорта stalzone.wiki (scripts/wiki_map) — динамика мира
    {"id": "mob",        "name": "Мутанты / логово", "emoji": "🐗", "color": "#d98a5a"},
    {"id": "event",      "name": "Событие",         "emoji": "⚡", "color": "#ffd34d"},
    {"id": "camp",       "name": "Лагерь / застава", "emoji": "⛺", "color": "#8fd0a0"},
    {"id": "shelter",    "name": "Укрытие от выброса", "emoji": "🛡", "color": "#7fd4ff"},
    {"id": "bubble",     "name": "Простр. пузырь",  "emoji": "🌀", "color": "#b0e0ff"},
]
_MAP_CAT_IDS = {c["id"] for c in MAP_CATEGORIES}
_MAP_KINDS = {"marker", "area", "line"}
_MAP_LAYERS = {"global", "detail"}

MAP_META = {
    # view — полезная область коллажа в px (x0,y0,x1,y1): вид, зум и скролл
    # ограничены ею. Всё за рамкой — декоративные поля global_map без функции
    # (тайлы остаются на диске, просто не показываются — подбирать рамку можно
    # без перегенерации пирамиды).
    "global": {"w": 18432, "h": 8192, "tile_size": 256, "min_zoom": 0, "max_zoom": 6,
               "tile_url": "wmap/{z}/{x}/{y}.webp", "view": [4200, 500, 12000, 7250]},
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


# ---------- ДЕВ · сканер выгодных лотов (services/market_scan) ----------

@router.get("/admin/scan")
async def admin_scan_state(request: Request):
    """Снапшот сканера: настройки + текущие сделки + статистика покрытия."""
    _require_admin(request)
    return scan.snapshot()


@router.post("/admin/scan/settings")
async def admin_scan_settings(request: Request, payload: dict = Body(...)):
    """Обновить пороги сканера (min_sph/discount_pct/avg_n/min_margin/enabled/
    hist_all). Значения кламплены, сохраняются в data/scan_settings.json;
    всем WS-клиентам уходит пересчитанный снапшот."""
    _require_admin(request)
    return {"settings": scan.update_settings(payload)}


@router.websocket("/ws/dev/scan")
async def ws_dev_scan(ws: WebSocket):
    """Реалтайм сканера для админов. Auth — по сессионной куке (как HTTP).
    Серверные события: snapshot (на подключении и при смене настроек),
    deal (новая/обновлённая сделка), remove (лоты разобрали). Клиент шлёт
    "ping" каждые ~25 c — держит соединение живым сквозь прокси."""
    user = users.user_by_session(ws.cookies.get(SESSION_COOKIE, ""))
    if not is_admin(user):
        await ws.close(code=4403)
        return
    await ws.accept()
    scan.clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "snapshot", **scan.snapshot()},
                                      ensure_ascii=False))
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        scan.clients.discard(ws)


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


@router.post("/map/objects/bulk")
async def map_objects_bulk(request: Request, payload: dict = Body(...)):
    """Массовое действие над ЧЕРНОВИКАМИ слоя (только админ) — разбор импорта:
    {action: publish|delete, layer, category?|name?}. Опубликованные не трогает.
    Возвращает {changed: n}."""
    _require_admin(request)
    action = payload.get("action")
    layer = payload.get("layer")
    if action not in ("publish", "delete"):
        raise HTTPException(422, "action: publish|delete")
    if layer not in _MAP_LAYERS:
        raise HTTPException(422, "layer: global|detail")
    category = payload.get("category") or None
    if category and category not in _MAP_CAT_IDS:
        raise HTTPException(422, "неизвестная категория")
    n = mapobjects.bulk(layer, action, category=category,
                        name=payload.get("name") or None)
    return {"changed": n}


# ---------- калькулятор сборок ----------

@router.get("/build/dict")
async def build_dictionary():
    """Справочник: контейнеры, каталог статов, артефакты с окнами статов, модель."""
    return builds.build_dict()


@router.post("/build/auto")
async def build_auto(payload: dict = Body(...)):
    """Автоподбор сборки: {budget, container, stats: [{key, weight 0-100}],
    exclude: [stat_key], no_negatives: bool}. exclude — «минус не нужен»:
    ИТОГ сборки по стату не уйдёт во вредную сторону (арты с минусом остаются,
    их перекрывают плюсы других артов); заражения не исключаются — лимиты и
    контрарты. no_negatives — то же по всем обычным статам разом."""
    try:
        budget = float(payload.get("budget", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "budget must be a number")
    res = builds.auto_build(budget, str(payload.get("container", "")),
                            payload.get("stats") or [],
                            payload.get("exclude") or [],
                            bool(payload.get("no_negatives")))
    if res.get("error") in ("container_not_found", "bad_request"):
        raise HTTPException(422, res["error"])
    return res  # включая error=no_priced_variants с подсказкой — фронт покажет


@router.get("/build/ready")
async def build_ready():
    """Готовые сборки под типовые задачи для верха /builds (кэш 15 мин)."""
    return builds.ready_builds()


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
