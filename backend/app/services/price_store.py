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
from app.services import auction, oauth, sales_log
from app.services.market_scan import scan

logger = logging.getLogger(__name__)


class PriceStore:
    def __init__(self) -> None:
        self.prices: dict[str, dict] = {}   # id -> {"available": bool, "min_buyout": int|None, "ts": float}
        self.history: dict[str, dict] = {}  # id -> {"sales_per_hour": float, "ts": float}
        self.base: list[str] = []           # крафт-граф: постоянно обновляем цены
        self.results: list[str] = []        # крафт-результаты: для них ещё и история продаж
        self.extra: set[str] = set()        # запрошенные вне графа предметы
        self.pending: set[str] = set()      # не посчитанные — обновить вне очереди
        self.hist_extra: set[str] = set()   # интерес к истории (открывали карточку в ауке)
        self.cycles = 0
        self.last_cycle_ts: float | None = None
        self.started = False
        self._save_ctr = 0
        self.hot_count = 0                      # длина горячего круга (ДЕВ-сканер)
        self.hot_round_sec: int | None = None   # сколько занял последний круг

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

    def request_history(self, item_id: str) -> None:
        """Интерес к истории продаж (открыли карточку в ауке): воркер начнёт
        снимать историю предмета каждый цикл — график будет копиться дальше.
        После первого замера предмет попадает в self.history (персистентен)."""
        self.hist_extra.add(item_id)

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

    def _hist_due(self, iid: str, now: float) -> bool:
        """Пора ли перечитывать историю предмета (см. SCAN_HIST_TTL_MIN).

        Темп продаж и средняя цена меняются медленно, поэтому каждый круг их
        снимать незачем — бюджет запросов нужнее лотам. Но окно /history — это
        100 ПОСЛЕДНИХ продаж: у сверхликвидных они вытесняются за минуты, и
        редкий замер оставил бы дыры в годовом графике (sales_log). Поэтому для
        них интервал сокращаем так, чтобы успевать до вытеснения окна.
        """
        h = self.history.get(iid)
        if not h or not h.get("ts") or h.get("recent_sales") is None:
            return True   # ещё не снимали (или старый формат кэша) — снять сейчас
        ttl = config.SCAN_HIST_TTL_MIN * 60
        sph = h.get("sales_per_hour") or 0.0
        if sph > 0:
            ttl = min(ttl, 0.7 * 100 / sph * 3600)  # 70% времени жизни окна
        if sph < 0.2:
            ttl = max(ttl, 6 * 3600)   # почти не продаётся — переспрашивать редко
        return now - h["ts"] >= ttl

    async def _run_cycle(self, client) -> None:
        await oauth.ensure(client)  # свежий app-токен (no-op без клиентских кредов)
        # 1) цены всего крафт-графа, вперемешку с горячим кругом ДЕВ-сканера:
        # ликвидные предметы (только они могут стать сделкой) обновляются в
        # SCAN_HOT_RATIO раз чаще холодных — сделки свежие, полный обход идёт своим ходом
        # scan.rotation_ids(): артефактов и части снаряжения нет в крафт-графе,
        # но именно их выгоднее всего перепродавать — добираем в обход
        work = list(dict.fromkeys(self.base + sorted(self.extra) + scan.rotation_ids()))
        hot: list[str] = []
        hot_i, hot_debt, hot_t0 = 0, 0.0, time.time()
        for iid in work:
            # приоритет: посчитать запрошенные-но-неизвестные вне очереди
            while self.pending:
                pid = self.pending.pop()
                await self._fetch(client, pid)
            await self._fetch(client, iid)
            hot_debt += config.SCAN_HOT_RATIO
            while hot_debt >= 1:
                if hot_i >= len(hot):   # круг пройден — пересобрать (пороги могли смениться)
                    if hot:
                        self.hot_round_sec = round(time.time() - hot_t0)
                    hot, hot_i, hot_t0 = scan.hot_ids(), 0, time.time()
                    self.hot_count = len(hot)
                    if not hot:
                        hot_debt = 0.0
                        break
                hot_debt -= 1
                await self._fetch(client, hot[hot_i])
                hot_i += 1
        # 2) частота продаж: крафт-результаты (рейтинг профитных) + всё, к чьей
        # истории проявляли интерес (график продаж в карточке аука)
        hist_ids = self.results + sorted(self.hist_extra | set(self.history))
        if scan.wants_history_all():
            hist_ids += work   # ДЕВ-сканер: история нужна всему графу
        # разведка сканера: темп продаж артов и снаряжения (мёртвые
        # переспрашиваются раз в 6 часов — см. _hist_due)
        hist_ids += scan.probe_ids()
        hist_work = dict.fromkeys(hist_ids)
        now = time.time()
        for iid in hist_work:
            while self.pending:
                pid = self.pending.pop()
                await self._fetch(client, pid)
            if self._hist_due(iid, now):
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
        scan.on_lots(iid)   # ДЕВ-сканер: свежие лоты → пересчёт/снятие сделки
        self._save_ctr += 1
        if self._save_ctr % 25 == 0:
            self.save()

    async def _fetch_history(self, client, iid: str) -> None:
        r = await auction.fetch_history(client, iid)
        sales_log.record(iid, r.get("prices_raw") or [])  # копим годовой график
        if r.get("available"):
            self.history[iid] = {"sales_per_hour": r.get("sales_per_hour", 0.0),
                                 "avg_unit_price": r.get("avg_unit_price"),
                                 "last_unit_price": r.get("last_unit_price"),
                                 "recent_unit_price": r.get("recent_unit_price"),
                                 "recent50_unit_price": r.get("recent50_unit_price"),
                                 "recent_units": r.get("recent_units") or [],
                                 "recent_sales": r.get("recent_sales") or [],
                                 "last_sale_ts": r.get("last_sale_ts"),
                                 "ts": time.time()}
            scan.on_history(iid)   # ДЕВ-сканер: свежая история → пересчёт сделки
        self._save_ctr += 1
        if self._save_ctr % 25 == 0:
            self.save()


store = PriceStore()
