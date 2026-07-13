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
    """Мин. цена выкупа за 1 штуку на ауке. {available, min_buyout?, lots_count?, error?}."""
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/lots"
    params = {"limit": config.AUCTION_LOTS_LIMIT, "sort": "buyout_price", "order": "asc"}

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
    units = []  # (цена за 1 штуку, количество в лоте)
    for lot in lots:
        bp, amount = lot.get("buyoutPrice"), lot.get("amount") or 1
        if bp:
            units.append((bp / amount, amount))
    if not units:
        return {"available": False, "error": "no_lots"}
    units.sort(key=lambda u: u[0])
    # глубина стакана: дешёвые лоты (для средней цены закупки партии);
    # ограничиваем объём, чтобы кэш цен не разбухал
    depth, got = [], 0
    for unit, amount in units:
        depth.append([round(unit), amount])
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


async def fetch_history(client: httpx.AsyncClient, item_id: str) -> dict:
    """Недавняя история продаж: {available, sales_per_hour, sold_count, avg_unit_price}."""
    url = f"{config.API_BASE}/{config.REGION}/auction/{item_id}/history"
    params = {"limit": 100}

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
    for e in entries:
        t = None
        if e.get("time"):
            try:
                t = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
                times.append(t)
            except ValueError:
                pass
        price, amount = e.get("price"), e.get("amount") or 1
        if price:
            unit = price / amount  # цена продажи за 1 штуку
            units.append(unit)
            if t:
                dated.append((t, unit))
    avg = round(sum(units) / len(units)) if units else None

    # реальная цена продажи: последняя сделка + медиана 10 свежих сделок
    # (мин. выкуп — цена ХОТЕЛОК продавцов; фактические сделки обычно ниже)
    dated.sort(key=lambda p: p[0], reverse=True)
    last_unit = round(dated[0][1]) if dated else None
    recent = sorted(u for _, u in dated[:10])
    recent_unit = round(recent[len(recent) // 2]) if recent else None

    if not times:
        return {"available": True, "sales_per_hour": 0.0, "sold_count": 0,
                "avg_unit_price": avg, "last_unit_price": last_unit,
                "recent_unit_price": recent_unit, "prices_raw": raw}

    now = datetime.now(timezone.utc)
    span_h = max((now - min(times)).total_seconds() / 3600, 1 / 60)
    return {"available": True,
            "sales_per_hour": round(len(times) / span_h, 1),
            "sold_count": len(times),
            "avg_unit_price": avg,
            "last_unit_price": last_unit,
            "recent_unit_price": recent_unit,
            "prices_raw": raw}
