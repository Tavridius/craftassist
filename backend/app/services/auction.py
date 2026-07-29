"""Низкоуровневый клиент STALZONE auction API.

Единственный вызывающий — фоновый воркер PriceStore. Глобальный троттл держит
интервал между запросами (демо-API ~2/с), на 429 — ретрай с бэкоффом.
Кэширование и персистентность — в PriceStore, здесь только сам запрос.
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.services import oauth

logger = logging.getLogger(__name__)

# Глобальный троттл: минимальный интервал между запросами к ауку.
_throttle_lock = asyncio.Lock()
_last_request = 0.0


def _headers() -> dict:
    tok = oauth.token() or config.API_TOKEN
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def _throttle() -> None:
    global _last_request
    async with _throttle_lock:
        loop = asyncio.get_event_loop()
        wait = _last_request + config.AUCTION_MIN_INTERVAL - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request = loop.time()


async def fetch_lots(client: httpx.AsyncClient, item_id: str) -> dict:
    """Мин. цена выкупа за 1 штуку на ауке. {available, min_buyout?, lots_count?, error?}.

    additional=true (стоимость запроса та же) — чтобы у каждого лота знать
    качество (qlt) и заточку (ptn): у артефактов и снаряжения цена зависит от них
    в разы, и ДЕВ-сканер сравнивает лот со средней ТОЙ ЖЕ корзины, а не со смешанной.
    """
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/lots"
    params = {"limit": config.AUCTION_LOTS_LIMIT, "additional": "true",
              "sort": "buyout_price", "order": "asc"}

    resp = None
    for attempt in range(config.AUCTION_MAX_RETRIES + 1):
        await _throttle()
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=15.0)
        except httpx.HTTPError as e:
            logger.warning("auction request failed for %s: %s", item_id, e)
            return {"available": False, "error": "request_failed"}

        if resp.status_code == 429:  # rate limited — подождать и повторить
            retry_after = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 5.0) * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code == 401:
        return {"available": False, "error": "unauthorized"}
    if resp.status_code != 200:
        logger.warning("auction %s -> HTTP %s", item_id, resp.status_code)
        return {"available": False, "error": f"http_{resp.status_code}"}

    lots = resp.json().get("lots", [])
    units = []  # (цена за 1 штуку, количество, качество, заточка)
    for lot in lots:
        bp, amount = lot.get("buyoutPrice"), lot.get("amount") or 1
        if bp:
            add = lot.get("additional") or {}
            units.append((bp / amount, amount, int(add.get("qlt") or 0),
                          int(add.get("ptn") or 0)))
    if not units:
        return {"available": False, "error": "no_lots"}
    units.sort(key=lambda u: u[0])
    # глубина стакана: дешёвые лоты (для средней цены закупки партии);
    # ограничиваем объём, чтобы кэш цен не разбухал
    depth, got = [], 0
    for unit, amount, qlt, ptn in units:
        depth.append([round(unit), amount, qlt, ptn])
        got += amount
        if got >= 600 or len(depth) >= 60:
            break
    return {"available": True, "min_buyout": round(units[0][0]),
            "lots_count": len(lots), "depth": depth}


async def fetch_lots_page(client: httpx.AsyncClient, item_id: str,
                          offset: int = 0, limit: int = 200) -> dict:
    """Сырая страница активных лотов, дешёвые первыми: {total, lots: [...]} или {error}.

    additional=true добавляет лотам qlt/ptn — раскладка по корзинам для цен
    калькулятора сборок (средняя из N самых дешёвых выкупов корзины).
    """
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/lots"
    params = {"limit": limit, "offset": offset, "additional": "true",
              "sort": "buyout_price", "order": "asc"}

    resp = None
    for attempt in range(config.AUCTION_MAX_RETRIES + 1):
        await _throttle()
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20.0)
        except httpx.HTTPError as e:
            logger.warning("lots page failed for %s: %s", item_id, e)
            return {"error": "request_failed"}
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 5.0) * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code != 200:
        return {"error": f"http_{resp.status_code if resp else 'none'}"}
    return resp.json()


async def fetch_history_page(client: httpx.AsyncClient, item_id: str,
                             offset: int = 0, limit: int = 200,
                             additional: bool = True) -> dict:
    """Сырая страница истории продаж: {total, prices: [...]} или {error}.

    additional=true добавляет каждой продаже qlt/ptn (качество/заточка) —
    основа биржи артефактов. Страница ≤200 записей, offset — на любую глубину
    (история хранится с 2018; у старых записей другой формат additional).
    """
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/history"
    params = {"limit": limit, "offset": offset,
              "additional": "true" if additional else "false"}

    resp = None
    for attempt in range(config.AUCTION_MAX_RETRIES + 1):
        await _throttle()
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20.0)
        except httpx.HTTPError as e:
            logger.warning("history page failed for %s: %s", item_id, e)
            return {"error": "request_failed"}
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 5.0) * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code != 200:
        return {"error": f"http_{resp.status_code if resp else 'none'}"}
    return resp.json()


async def fetch_operation_sessions(client: httpx.AsyncClient, *, offset: int = 0,
                                   limit: int = 100, sort: str = "date_finish",
                                   order: str = "desc", after: str | None = None,
                                   username: str | None = None,
                                   map_: str | None = None) -> dict:
    """Страница сессий PvE-режима «Операции»: {total, sessions: [...]} или {error}.

    GET /{region}/operations/sessions (eapi, нужен app-токен; demo-API отдаёт 404).
    Каждая сессия: {id, map, startTime, endTime, difficulty, sessionDurationSeconds,
    difficultyReward, participants:[{username, death, mobKills, damageDealt,
    damageReceived, armorClass, armorItemId, armorLevel, primaryWeaponItemId,
    primaryWeaponLevel, secondaryWeaponItemId, secondaryWeaponLevel}]}.
    """
    url = f"{config.API_BASE}/{config.REGION}/operations/sessions"
    params: dict = {"limit": limit, "offset": offset, "sort": sort, "order": order}
    if after:
        params["after"] = after
    if username:
        params["username"] = username
    if map_:
        params["map"] = map_

    resp = None
    for attempt in range(config.AUCTION_MAX_RETRIES + 1):
        await _throttle()
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20.0)
        except httpx.HTTPError as e:
            logger.warning("operations request failed: %s", e)
            return {"error": "request_failed"}
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 5.0) * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code != 200:
        return {"error": f"http_{resp.status_code if resp else 'none'}"}
    return resp.json()


async def fetch_history(client: httpx.AsyncClient, item_id: str) -> dict:
    """Недавняя история продаж: {available, sales_per_hour, sold_count, avg_unit_price}.

    additional=true (стоимость запроса та же) — чтобы ОТСЕЯТЬ заточенные (ptn)
    и качественные (qlt) экземпляры из ценовых агрегатов: продажи +10/+15 оружия
    стоят миллионы и завышали «цену продажи» базового предмета в разы (всплыло
    на бартер-оружии). Темп продаж считаем по всем записям — спрос есть спрос.
    """
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/history"
    params = {"limit": 100, "additional": "true"}

    resp = None
    for attempt in range(config.AUCTION_MAX_RETRIES + 1):
        await _throttle()
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=15.0)
        except httpx.HTTPError as e:
            logger.warning("history request failed for %s: %s", item_id, e)
            return {"available": False, "error": "request_failed"}
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 5.0) * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code != 200:
        return {"available": False,
                "error": f"http_{resp.status_code if resp else 'none'}"}

    entries = resp.json().get("prices", [])
    # сырые записи отдаём вызывающему (PriceStore скармливает их sales_log —
    # так копится годовая история продаж без лишних запросов)
    raw = entries
    times, units, dated = [], [], []
    all_dated = []  # ВСЕ продажи с корзиной (qlt, ptn) — для ДЕВ-сканера
    for e in entries:
        t = None
        if e.get("time"):
            try:
                t = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
                times.append(t)
            except ValueError:
                pass
        add = e.get("additional") or {}
        plain = not add.get("ptn") and not add.get("qlt")  # базовый экземпляр
        price, amount = e.get("price"), e.get("amount") or 1
        if price and t:
            # сканеру нужны ВСЕ продажи с корзиной: у артефакта качества 2 и 4
            # цена отличается в разы, сравнивать можно только внутри корзины
            all_dated.append((t, price / amount, amount,
                              int(add.get("qlt") or 0), int(add.get("ptn") or 0)))
        if price and plain:
            unit = price / amount  # цена продажи за 1 штуку
            units.append(unit)
            if t:
                dated.append((t, unit, amount))
    # медиана, а не среднее: одна продажа «за 50 цен» (перевод валюты через
    # аук) не должна задирать цену продажи. Медианные recent/last ниже и так
    # устойчивы — выравниваем и «среднюю».
    su = sorted(units)
    avg = round(su[len(su) // 2]) if su else None

    # реальная цена продажи: последняя сделка + медиана 10 свежих сделок
    # (мин. выкуп — цена ХОТЕЛОК продавцов; фактические сделки обычно ниже)
    dated.sort(key=lambda p: p[0], reverse=True)
    last_unit = round(dated[0][1]) if dated else None
    # «свежих» — только по названию: окно /history это 100 ПОСЛЕДНИХ продаж без
    # ограничения по времени. У неликвида эти 10 сделок могут быть за год, и
    # медиана по ним выдаётся за текущую цену. Отдаём время последней сделки —
    # потребитель решает, можно ли ей верить (см. barter._sell_side)
    last_sale_ts = dated[0][0].isoformat() if dated else None
    recent = sorted(u for _, u, _ in dated[:10])
    recent_unit = round(recent[len(recent) // 2]) if recent else None
    # медиана 50 последних сделок — база расчёта цены топлива генератора
    recent50 = sorted(u for _, u, _ in dated[:50])
    recent50_unit = round(recent50[len(recent50) // 2]) if recent50 else None

    # последние продажи (новые первыми) для ДЕВ-сканера:
    # recent_units — базовые экземпляры (совместимость), recent_sales —
    # ВСЕ продажи как [цена/шт, кол-во, качество, заточка]: из них сканер
    # считает средние по корзинам и показывает продажи на карточке
    recent_units = [round(u) for _, u, _ in dated[:20]]
    all_dated.sort(key=lambda p: p[0], reverse=True)
    recent_sales = [[round(u), a, q, pt] for _, u, a, q, pt in all_dated[:20]]

    if not times:
        return {"available": True, "sales_per_hour": 0.0, "sold_count": 0,
                "avg_unit_price": avg, "last_unit_price": last_unit,
                "recent_unit_price": recent_unit, "recent50_unit_price": recent50_unit,
                "recent_units": recent_units, "recent_sales": recent_sales,
                "last_sale_ts": last_sale_ts, "prices_raw": raw}

    now = datetime.now(timezone.utc)
    span_h = max((now - min(times)).total_seconds() / 3600, 1 / 60)
    return {"available": True,
            "sales_per_hour": round(len(times) / span_h, 1),
            "sold_count": len(times),
            "avg_unit_price": avg,
            "last_unit_price": last_unit,
            "recent_unit_price": recent_unit,
            "recent50_unit_price": recent50_unit,
            "recent_units": recent_units,
            "recent_sales": recent_sales,
            "last_sale_ts": last_sale_ts,
            "prices_raw": raw}
