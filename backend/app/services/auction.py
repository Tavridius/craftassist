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
    buyouts = []
    for lot in lots:
        bp, amount = lot.get("buyoutPrice"), lot.get("amount") or 1
        if bp:
            buyouts.append(bp / amount)  # цена за 1 штуку
    if not buyouts:
        return {"available": False, "error": "no_lots"}
    return {"available": True, "min_buyout": round(min(buyouts)), "lots_count": len(lots)}


async def fetch_history(client: httpx.AsyncClient, item_id: str) -> dict:
    """Частота продаж по недавней истории аука: {available, sales_per_hour, sold_count}."""
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
    times = []
    for e in entries:
        t = e.get("time")
        if t:
            try:
                times.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
            except ValueError:
                pass
    if not times:
        return {"available": True, "sales_per_hour": 0.0, "sold_count": 0}

    now = datetime.now(timezone.utc)
    span_h = max((now - min(times)).total_seconds() / 3600, 1 / 60)
    return {"available": True,
            "sales_per_hour": round(len(times) / span_h, 1),
            "sold_count": len(times)}
