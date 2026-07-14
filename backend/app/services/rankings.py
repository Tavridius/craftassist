"""Рейтинги для главной страницы: популярные, выгодные, профитные крафты.

Считаются целиком из тёплого кэша (PriceStore + GameDB) — без обращений к API,
поэтому пересчёт дешёвый; результат кэшируется на RANKINGS_TTL секунд.

- популярные: по счётчику открытий карточек (data/popularity.json);
- выгодные:   максимальная ДЕЛЬТА в рублях (продажа-нетто − стоимость крафта),
              % оставляем справочно (решение юзера 14 июля 2026: важна
              абсолютная прибыль за цикл крафта, а не относительная);
- профитные:  то же, но только предметы с частотой продаж ≥ LIQUID_MIN_SALES_PER_HOUR.
"""
import json
import logging
import os
import time

from app import config
from app.db.index import db
from app.services import craft
from app.services.price_store import store

logger = logging.getLogger(__name__)

RANKINGS_TTL = int(os.getenv("RANKINGS_TTL", "60"))
LIQUID_MIN_SALES_PER_HOUR = float(os.getenv("LIQUID_MIN_SALES_PER_HOUR", "10"))
TOP_N = int(os.getenv("TOP_N", "15"))


class Rankings:
    def __init__(self) -> None:
        self.opens: dict[str, int] = {}
        self._bump_ctr = 0
        self._cache: dict | None = None
        self._cache_ts = 0.0

    @property
    def _path(self):
        return config.DATA_DIR / "popularity.json"

    # ---------- популярность ----------
    def load(self) -> None:
        try:
            if self._path.exists():
                self.opens = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Rankings: loaded popularity for %d items", len(self.opens))
        except Exception:
            logger.exception("Rankings: failed to load popularity.json")

    def save(self) -> None:
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.opens), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("Rankings: failed to save popularity.json")

    def bump(self, item_id: str) -> None:
        self.opens[item_id] = self.opens.get(item_id, 0) + 1
        self._bump_ctr += 1
        if self._bump_ctr % 10 == 0:
            self.save()

    # ---------- рейтинги ----------
    def compute(self) -> dict:
        now = time.time()
        if self._cache and now - self._cache_ts < RANKINGS_TTL:
            return self._cache

        result_ids = sorted(db.recipe_by_result)
        ctx = {"memo": {}, "seen": set()}
        rows: dict[str, dict] = {}
        for rid in result_ids:
            node = craft._price(rid, tuple(), ctx, 0, expand=False)
            cc, buy = node.get("craft_cost"), node.get("market_price")
            it = db.item(rid) or {}
            hist = store.history.get(rid) or {}
            # выгода — от реальной цены продажи (медиана свежих сделок) минус
            # комиссия аука; мин. выкуп — только fallback, пока истории нет
            sell = craft.sell_price(rid)
            base = sell if sell is not None else buy
            net = base * (1 - config.AUCTION_FEE) if base else None
            ok = cc and net and cc > 0
            pct = round((net - cc) / cc * 100) if ok else None
            diff = round(net - cc) if ok else None
            rows[rid] = {
                "id": rid,
                "name": it.get("name", rid),
                "icon": it.get("icon", ""),
                "color": it.get("color", "DEFAULT"),
                "craft_cost": cc,
                "buy_price": buy,
                "sell_price": sell,
                "pct": pct,
                "diff": diff,
                "sales_per_hour": hist.get("sales_per_hour"),
                "opens": self.opens.get(rid, 0),
            }

        priced = [r for r in rows.values() if r["diff"] is not None]
        profitable = sorted(priced, key=lambda r: -r["diff"])[:TOP_N]
        liquid = sorted(
            [r for r in priced if (r["sales_per_hour"] or 0) >= LIQUID_MIN_SALES_PER_HOUR],
            key=lambda r: -r["diff"])[:TOP_N]
        popular = sorted(
            [r for r in rows.values() if r["opens"] > 0],
            key=lambda r: -r["opens"])[:TOP_N]

        self._cache = {
            "popular": popular,
            "profitable": profitable,
            "liquid": liquid,
            "liquid_threshold": LIQUID_MIN_SALES_PER_HOUR,
            "prices_ready": store.stats()["priced"],
        }
        self._cache_ts = now
        return self._cache


rankings = Rankings()
