"""Персистентный кэш цен + фоновый воркер обновления.

Идея масштабируемости: цены аукциона тянет ТОЛЬКО фоновый воркер, с фиксированной
скоростью (в рамках лимита API), циклически по всему крафт-графу. Запросы пользователей
читают готовые цены из памяти и НЕ ходят в API. Значит нагрузка на API постоянна
(~2 запроса/с) и не зависит от числа пользователей.

Кэш сохраняется в data/prices.json (переживает рестарт). Предметы, запрошенные, но
ещё не посчитанные, попадают в приоритетную очередь и обновляются вне очереди.
"""
import asyncio
import json
import logging
import os
import time

import httpx

from app import config
from app.services import auction, oauth

logger = logging.getLogger(__name__)


class PriceStore:
    def __init__(self) -> None:
        self.prices: dict[str, dict] = {}   # id -> {"available": bool, "min_buyout": int|None, "ts": float}
        self.history: dict[str, dict] = {}  # id -> {"sales_per_hour": float, "ts": float}
        self.base: list[str] = []           # крафт-граф: постоянно обновляем цены
        self.results: list[str] = []        # крафт-результаты: для них ещё и история продаж
        self.extra: set[str] = set()        # запрошенные вне графа предметы
        self.pending: set[str] = set()      # не посчитанные — обновить вне очереди
        self.cycles = 0
        self.last_cycle_ts: float | None = None
        self.started = False
        self._save_ctr = 0

    @property
    def _path(self):
        return config.DATA_DIR / "prices.json"

    @property
    def _hist_path(self):
        return config.DATA_DIR / "history.json"

    # ---------- персистентность ----------
    def load(self) -> None:
        try:
            if self._path.exists():
                self.prices = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("PriceStore: loaded %d cached prices", len(self.prices))
            if self._hist_path.exists():
                self.history = json.loads(self._hist_path.read_text(encoding="utf-8"))
                logger.info("PriceStore: loaded %d cached histories", len(self.history))
        except Exception:
            logger.exception("PriceStore: failed to load cache files")

    def save(self) -> None:
        for path, data in ((self._path, self.prices), (self._hist_path, self.history)):
            try:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, path)
            except Exception:
                logger.exception("PriceStore: failed to save %s", path.name)

    # ---------- чтение (для запросов пользователей) ----------
    def set_base(self, ids) -> None:
        self.base = list(ids)

    def set_results(self, ids) -> None:
        self.results = list(ids)

    def get(self, item_id: str) -> dict:
        p = self.prices.get(item_id)
        if p is None:
            return {"known": False, "available": False, "min_buyout": None, "ts": None}
        return {"known": True, "available": p.get("available", False),
                "min_buyout": p.get("min_buyout"), "ts": p.get("ts")}

    def request(self, ids) -> None:
        """Записать интерес к предметам: не из графа → в extra; не посчитанные → в приоритет."""
        base_extra = set(self.base) | self.extra
        for iid in ids:
            if iid not in base_extra:
                self.extra.add(iid)
            if iid not in self.prices:
                self.pending.add(iid)

    def stats(self) -> dict:
        now = time.time()
        fresh = sum(1 for p in self.prices.values()
                    if p.get("ts") and now - p["ts"] < config.PRICE_STALE_AFTER)
        return {
            "priced": len(self.prices),
            "fresh": fresh,
            "histories": len(self.history),
            "base": len(self.base),
            "results": len(self.results),
            "extra": len(self.extra),
            "pending": len(self.pending),
            "cycles": self.cycles,
            "last_cycle_age_sec": round(now - self.last_cycle_ts) if self.last_cycle_ts else None,
        }

    # ---------- фоновый воркер ----------
    async def refresh_loop(self) -> None:
        self.started = True
        logger.info("PriceStore: refresh loop started (base=%d)", len(self.base))
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                try:
                    await self._run_cycle(client)
                    self.cycles += 1
                    self.last_cycle_ts = time.time()
                    self.save()
                except Exception:
                    logger.exception("PriceStore: cycle failed")
                await asyncio.sleep(config.PRICE_REFRESH_PAUSE)

    async def _run_cycle(self, client) -> None:
        await oauth.ensure(client)  # свежий app-токен (no-op без клиентских кредов)
        # 1) цены всего крафт-графа
        work = list(dict.fromkeys(self.base + sorted(self.extra)))
        for iid in work:
            # приоритет: посчитать запрошенные-но-неизвестные вне очереди
            while self.pending:
                pid = self.pending.pop()
                await self._fetch(client, pid)
            await self._fetch(client, iid)
        # 2) частота продаж — только для крафт-результатов (для рейтинга профитных)
        for iid in self.results:
            while self.pending:
                pid = self.pending.pop()
                await self._fetch(client, pid)
            await self._fetch_history(client, iid)

    async def _fetch(self, client, iid: str) -> None:
        r = await auction.fetch_lots(client, iid)  # троттлинг + ретраи внутри
        if r.get("error") == "unauthorized" and oauth.enabled():
            oauth.invalidate()
            await oauth.ensure(client)  # кулдаун внутри — не спамит token-endpoint
        self.prices[iid] = {
            "available": r.get("available", False),
            "min_buyout": r.get("min_buyout"),
            "depth": r.get("depth"),   # дешёвые лоты [[цена/шт, кол-во], …]
            "ts": time.time(),
        }
        self._save_ctr += 1
        if self._save_ctr % 25 == 0:
            self.save()

    async def _fetch_history(self, client, iid: str) -> None:
        r = await auction.fetch_history(client, iid)
        if r.get("available"):
            self.history[iid] = {"sales_per_hour": r.get("sales_per_hour", 0.0),
                                 "avg_unit_price": r.get("avg_unit_price"),
                                 "last_unit_price": r.get("last_unit_price"),
                                 "recent_unit_price": r.get("recent_unit_price"),
                                 "ts": time.time()}
        self._save_ctr += 1
        if self._save_ctr % 25 == 0:
            self.save()


store = PriceStore()
