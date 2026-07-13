"""Биржа артефактов: снапшоты истории продаж по корзинам качество×заточка.

По расписанию (config.ART_WATCH_HOURS, МСК) для каждого артефакта тянем
страницы /auction/{id}/history?additional=true, берём продажи СТРОГО НОВЕЕ
прошлого замера (граница last_ts в meta — продажи не считаются дважды) и
складываем агрегаты корзин (qlt, ptn) в data/market.db.

У сверхликвидных артефактов ART_WATCH_MAX_PAGES страниц покрывают не всё окно
между замерами — это осознанная ВЫБОРКА: для средней недельной цены корзины
её достаточно. Демо-API отдаёт additional пустым — на демо биржа не копится.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app import config
from app.db import market
from app.db.index import db
from app.services import auction, oauth, sales_log

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))  # у Москвы нет переходов на летнее время


def _parse_time(t) -> datetime | None:
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def bucket_page(prices: list, floor: datetime, buckets: dict) -> tuple[datetime | None, bool]:
    """Раскладывает страницу истории (новые → старые) по корзинам (qlt, ptn).

    Учитываются только продажи новее floor и в новом формате (есть qlt);
    legacy-записи (до ~2020: art_type/stats_random) пропускаются.
    Возвращает (самое новое время на странице, дошли ли до floor).
    """
    newest = None
    for e in prices:
        t = _parse_time(e.get("time"))
        if t is None:
            continue
        if newest is None or t > newest:
            newest = t
        if t <= floor:
            return newest, True  # страница отсортирована по времени — дальше старьё
        a = e.get("additional") or {}
        qlt = a.get("qlt")
        price, amount = e.get("price"), e.get("amount") or 1
        if qlt is None or not price or amount <= 0:
            continue
        unit = price / amount
        key = (int(qlt), int(a.get("ptn") or 0))
        b = buckets.setdefault(key, {"n": 0, "sum": 0.0, "min": unit, "max": unit})
        b["n"] += 1
        b["sum"] += unit
        b["min"] = min(b["min"], unit)
        b["max"] = max(b["max"], unit)
    return newest, False


class ArtefactWatch:
    def __init__(self) -> None:
        self.last_slot: str | None = None

    # ---------- расписание (как у IngredientWatch) ----------
    @staticmethod
    def _slot_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:00")

    def latest_slot(self, now: datetime | None = None) -> str:
        now = now or datetime.now(MSK)
        best = None
        for days_back in (0, 1):
            day = now - timedelta(days=days_back)
            for h in config.ART_WATCH_HOURS:
                dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
                if dt <= now and (best is None or dt > best):
                    best = dt
        return self._slot_key(best)

    def _seconds_to_next_slot(self, now: datetime | None = None) -> float:
        now = now or datetime.now(MSK)
        candidates = []
        for days_fwd in (0, 1):
            day = now + timedelta(days=days_fwd)
            for h in config.ART_WATCH_HOURS:
                dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
                if dt > now:
                    candidates.append(dt)
        return (min(candidates) - now).total_seconds()

    # ---------- снапшот ----------
    async def _snapshot_item(self, client: httpx.AsyncClient, iid: str, slot: str) -> bool:
        """Свежие продажи одного артефакта → корзины в market.db. False = сбой API."""
        last_ts = market.get_meta(f"last_ts:{iid}")
        floor = _parse_time(last_ts)
        if floor is None:  # первый замер: окно в один интервал расписания назад
            step_h = 24 / max(len(config.ART_WATCH_HOURS), 1)
            floor = datetime.now(timezone.utc) - timedelta(hours=step_h)

        buckets: dict = {}
        all_prices: list = []       # все страницы — в sales_log (годовой график)
        newest_all: datetime | None = None
        offset = 0
        for _ in range(config.ART_WATCH_MAX_PAGES):
            page = await auction.fetch_history_page(client, iid, offset=offset)
            if page.get("error"):
                logger.warning("artefact_watch: %s history failed: %s", iid, page["error"])
                return False
            prices = page.get("prices") or []
            if not prices:
                break
            all_prices.extend(prices)
            newest, reached_floor = bucket_page(prices, floor, buckets)
            if newest and (newest_all is None or newest > newest_all):
                newest_all = newest
            if reached_floor or len(prices) < 200:
                break
            offset += len(prices)
        # у sales_log своя граница sale_ts — страницы передаём одним вызовом
        sales_log.record(iid, all_prices)

        # границу двигаем только ВПЕРЁД: без новых продаж newest со страницы старее floor
        new_ts = newest_all.isoformat() if newest_all and newest_all > floor else None
        if buckets or new_ts:
            market.add_snapshot(iid, slot, buckets, new_ts)
        return True

    async def _snapshot(self, client: httpx.AsyncClient, slot: str) -> bool:
        """Замер всех артефактов. False — не получилось ничего (ретрай позже)."""
        await oauth.ensure(client)
        ids = db.artefact_ids()
        ok = 0
        for iid in ids:
            try:
                if await self._snapshot_item(client, iid, slot):
                    ok += 1
            except Exception:
                logger.exception("artefact_watch: %s snapshot failed", iid)
        if not ok:
            logger.warning("artefact_watch: slot %s got nothing, will retry", slot)
            return False

        cutoff = datetime.now(MSK) - timedelta(days=config.ART_KEEP_DAYS)
        market.cleanup(self._slot_key(cutoff))
        market.set_meta("last_slot", slot)
        self.last_slot = slot
        logger.info("artefact_watch: snapshot %s done (%d/%d artefacts)", slot, ok, len(ids))
        return True

    async def loop(self) -> None:
        self.last_slot = market.get_meta("last_slot")
        logger.info("artefact_watch: loop started, hours=%s MSK, artefacts=%d, last_slot=%s",
                    config.ART_WATCH_HOURS, len(db.artefact_ids()), self.last_slot)
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                delay = None
                try:
                    slot = self.latest_slot()
                    if slot != self.last_slot:  # новый или пропущенный слот
                        if not await self._snapshot(client, slot):
                            delay = 600  # совсем без данных — ретрай через 10 мин
                except Exception:
                    logger.exception("artefact_watch: snapshot failed")
                    delay = 600
                if delay is None:
                    delay = self._seconds_to_next_slot() + 30
                await asyncio.sleep(delay)


artwatch = ArtefactWatch()
