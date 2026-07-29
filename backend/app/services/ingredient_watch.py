"""Биржа ингредиентов на главной: цены ключевых материалов дважды в сутки.

Пользовательские запросы читают готовые серии из памяти; API аукциона дёргается
ТОЛЬКО в назначенные часы (config.WATCH_HOURS, МСК): средняя цена продажи из
недавней истории + мин. выкуп из лотов. Серии персистятся в
data/ingredient_watch.json и переживают рестарт; слот, пропущенный за время
простоя, доснимается сразу при старте.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from app import config
from app.services import auction, oauth

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))  # у Москвы нет переходов на летнее время


class IngredientWatch:
    def __init__(self) -> None:
        # id -> [{"slot", "ts", "avg", "min_buyout", "sales_per_hour"}, ...]
        self.series: dict[str, list[dict]] = {}
        self.last_slot: str | None = None

    @property
    def _path(self):
        return config.DATA_DIR / "ingredient_watch.json"

    # ---------- персистентность ----------
    def load(self) -> None:
        try:
            if self._path.exists():
                doc = json.loads(self._path.read_text(encoding="utf-8"))
                self.series = doc.get("series", {})
                self.last_slot = doc.get("last_slot")
                logger.info("IngredientWatch: loaded %d series, last slot %s",
                            len(self.series), self.last_slot)
        except Exception:
            logger.exception("IngredientWatch: failed to load cache")

    def save(self) -> None:
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"last_slot": self.last_slot, "series": self.series}),
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("IngredientWatch: failed to save cache")

    # ---------- расписание ----------
    @staticmethod
    def _slot_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:00")

    def latest_slot(self, now: datetime | None = None) -> str:
        """Последняя УЖЕ прошедшая точка расписания (сегодня или вчера)."""
        now = now or datetime.now(MSK)
        best = None
        for days_back in (0, 1):
            day = now - timedelta(days=days_back)
            for h in config.WATCH_HOURS:
                dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
                if dt <= now and (best is None or dt > best):
                    best = dt
        return self._slot_key(best)

    def _seconds_to_next_slot(self, now: datetime | None = None) -> float:
        now = now or datetime.now(MSK)
        candidates = []
        for days_fwd in (0, 1):
            day = now + timedelta(days=days_fwd)
            for h in config.WATCH_HOURS:
                dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
                if dt > now:
                    candidates.append(dt)
        return (min(candidates) - now).total_seconds()

    # ---------- снапшот ----------
    async def _snapshot(self, client: httpx.AsyncClient, slot: str) -> bool:
        """Снимает цены всех наблюдаемых. False — данных нет вообще (ретрай позже)."""
        await oauth.ensure(client)
        entries: dict[str, dict] = {}
        for iid in config.WATCH_IDS:
            lots = await auction.fetch_lots(client, iid)
            hist = await auction.fetch_history(client, iid)
            entries[iid] = {
                "slot": slot,
                "ts": time.time(),
                "avg": hist.get("avg_unit_price"),
                "min_buyout": lots.get("min_buyout"),
                "sales_per_hour": hist.get("sales_per_hour"),
            }
        if not any(e["avg"] is not None or e["min_buyout"] is not None
                   for e in entries.values()):
            logger.warning("IngredientWatch: snapshot %s got no data, will retry", slot)
            return False

        for iid, entry in entries.items():
            s = self.series.setdefault(iid, [])
            if s and s[-1].get("slot") == slot:
                s[-1] = entry  # рестарт внутри того же слота — перезаписываем
            else:
                s.append(entry)
            del s[:-config.WATCH_KEEP]
        self.last_slot = slot
        self.save()
        logger.info("IngredientWatch: snapshot %s done (%d items)", slot, len(entries))
        return True

    async def loop(self) -> None:
        logger.info("IngredientWatch: loop started, hours=%s MSK, items=%s",
                    config.WATCH_HOURS, config.WATCH_IDS)
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                delay = None
                try:
                    slot = self.latest_slot()
                    # новый/пропущенный слот ИЛИ в конфиг добавили предмет без
                    # серии — доснимаем текущий слот сразу, не ждём следующего
                    if slot != self.last_slot or any(
                            iid not in self.series for iid in config.WATCH_IDS):
                        if not await self._snapshot(client, slot):
                            delay = 600  # данных не было — ретрай через 10 мин
                except Exception:
                    logger.exception("IngredientWatch: snapshot failed")
                    delay = 600
                if delay is None:
                    delay = self._seconds_to_next_slot() + 30
                await asyncio.sleep(delay)


watch = IngredientWatch()
