"""Статистика продаж: топ продаваемых за сегодня и за неделю.

«Сегодня» — живые продажи/час из PriceStore.history (окно последних сделок).
«Неделя» — среднее по снапшотам: раз в SALES_SNAP_HOURS копируем текущие
темпы в data/sales_stats.json (ретенция 7 дней). История продаж есть только
у крафт-результатов и запрошенных предметов — это и есть торговое ядро.
"""
import asyncio
import json
import logging
import time

from app import config
from app.services.price_store import store

logger = logging.getLogger(__name__)


class SalesStats:
    def __init__(self) -> None:
        self.snaps: list[dict] = []      # [{"ts": float, "rates": {iid: прод/ч}}]

    @property
    def _path(self):
        return config.DATA_DIR / "sales_stats.json"

    def load(self) -> None:
        try:
            self.snaps = json.loads(self._path.read_text(encoding="utf-8")).get("snaps", [])
        except (OSError, ValueError):
            self.snaps = []

    def save(self) -> None:
        try:
            self._path.write_text(json.dumps({"snaps": self.snaps}), encoding="utf-8")
        except OSError as e:
            logger.warning("sales_stats save failed: %s", e)

    def _snapshot(self) -> None:
        rates = {iid: h["sales_per_hour"] for iid, h in store.history.items()
                 if h.get("sales_per_hour")}
        if not rates:
            return
        self.snaps.append({"ts": time.time(), "rates": rates})
        cutoff = time.time() - 7 * 86400
        self.snaps = [s for s in self.snaps if s["ts"] >= cutoff]
        self.save()
        logger.info("sales_stats: snapshot #%d (%d items)", len(self.snaps), len(rates))

    def today_top(self, n: int = 10) -> list[tuple[str, float]]:
        rates = [(iid, h["sales_per_hour"]) for iid, h in store.history.items()
                 if h.get("sales_per_hour")]
        rates.sort(key=lambda r: -r[1])
        return rates[:n]

    def week_top(self, n: int = 10) -> list[tuple[str, float]]:
        if not self.snaps:
            return []
        acc: dict[str, float] = {}
        for s in self.snaps:
            for iid, rate in s["rates"].items():
                acc[iid] = acc.get(iid, 0.0) + rate
        avg = [(iid, total / len(self.snaps)) for iid, total in acc.items()]
        avg.sort(key=lambda r: -r[1])
        return avg[:n]

    async def loop(self) -> None:
        self.load()
        while True:
            # первый снапшот — после прогрева истории (иначе пустой)
            await asyncio.sleep(600 if not self.snaps else config.SALES_SNAP_HOURS * 3600)
            try:
                self._snapshot()
            except Exception as e:              # noqa: BLE001
                logger.warning("sales_stats snapshot failed: %s", e)


sstats = SalesStats()
