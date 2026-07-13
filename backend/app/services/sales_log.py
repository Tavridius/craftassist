"""Годовая история продаж предметов аукциона — данные графика в карточке.

Пассивный сборщик: НИ ОДНОГО своего запроса к API. Каждый ответ
/auction/{id}/history, который сервис и так получает (фоновый воркер цен,
вотчер артефактов, открытие карточки в полном ауке), прогоняется через
record(): продажи СТРОГО НОВЕЕ границы sale_ts:{item} агрегируются по часовым
слотам МСК в market.db/item_sales; граница двигается только вперёд — продажи
не считаются дважды, из какого бы источника ни пришла страница.

Ретенция: часы — ITEM_SALES_HOURLY_DAYS (35), старше — роллап в дневные
агрегаты; дни живут ITEM_SALES_KEEP_DAYS (год). Обслуживание (роллап+чистка)
цепляется к record() не чаще раза в 6 часов.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from app import config
from app.db import market

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))  # у Москвы нет переходов на летнее время

_last_maint = 0.0


def _parse_time(t) -> datetime | None:
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def record(item_id: str, prices: list[dict]) -> None:
    """Скормить сырую страницу(ы) истории продаж. prices — как отдаёт API:
    [{time, price, amount, ...}]. Страницы одного ответа передавать ОДНИМ
    вызовом (история отсортирована новые→старые, граница двигается сразу).
    Никогда не бросает — встроен в критичный цикл воркера цен."""
    try:
        if not prices:
            return
        floor = _parse_time(market.get_meta(f"sale_ts:{item_id}"))
        buckets: dict[str, dict] = {}
        newest: datetime | None = None
        for e in prices:
            if not isinstance(e, dict):
                continue
            t = _parse_time(e.get("time"))
            price, amount = e.get("price"), e.get("amount") or 1
            if t is None or not price or amount <= 0:
                continue
            if newest is None or t > newest:
                newest = t
            if floor is not None and t <= floor:
                continue
            unit = price / amount
            slot = t.astimezone(MSK).strftime("%Y-%m-%dT%H:00")
            b = buckets.setdefault(slot, {"n": 0, "sum": 0.0, "min": unit, "max": unit})
            b["n"] += amount                # объём — в штуках
            b["sum"] += unit * amount       # средневзвешенная цена за 1 шт
            b["min"] = min(b["min"], unit)
            b["max"] = max(b["max"], unit)
        if buckets:
            market.add_item_sales(item_id, buckets)
        if newest and (floor is None or newest > floor):
            market.set_meta(f"sale_ts:{item_id}", newest.isoformat())
    except Exception:
        logger.exception("sales_log: record failed for %s", item_id)
    _maintenance()


def _maintenance() -> None:
    """Роллап часов в дни + годовая чистка, не чаще раза в 6 часов."""
    global _last_maint
    now = time.time()
    if now - _last_maint < 6 * 3600:
        return
    _last_maint = now
    try:
        msk_now = datetime.now(MSK)
        hourly_edge = (msk_now - timedelta(days=config.ITEM_SALES_HOURLY_DAYS))
        market.rollup_item_sales(hourly_edge.strftime("%Y-%m-%dT%H:00"))
        keep_edge = (msk_now - timedelta(days=config.ITEM_SALES_KEEP_DAYS))
        market.cleanup_item_sales(keep_edge.strftime("%Y-%m-%dT00:00"))
    except Exception:
        logger.exception("sales_log: maintenance failed")
