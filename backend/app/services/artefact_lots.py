"""Живые лоты артефактов: средняя из N самых дешёвых по корзинам качество×заточка.

Пока биржа истории (artefact_watch) копит первую неделю, калькулятор сборок
ценит корзины по живым лотам: средняя из ART_LOTS_TOP самых дешёвых выкупов
корзины — устойчивее одного минимального лота к манипуляциям. Цикл лёгкий:
~103 запроса раз в ART_LOTS_MINUTES через общий троттл аукциона.
Кэш в data/artefact_lots.json переживает рестарт.
"""
import asyncio
import json
import logging
import os
import time

import httpx

from app import config
from app.db.index import db
from app.services import auction, oauth

logger = logging.getLogger(__name__)


def bucket_lots(lots: list) -> dict:
    """Раскладка лотов по корзинам: {"qlt:ptn": {avg, n, min}}, avg — средняя
    из ART_LOTS_TOP самых дешёвых выкупов за 1 шт. Лоты без qlt (демо/легаси)
    и без выкупа пропускаются."""
    per: dict[str, list[float]] = {}
    for lot in lots:
        a = lot.get("additional") or {}
        qlt = a.get("qlt")
        bp, amount = lot.get("buyoutPrice"), lot.get("amount") or 1
        if qlt is None or not bp or amount <= 0:
            continue
        per.setdefault(f"{int(qlt)}:{int(a.get('ptn') or 0)}", []).append(bp / amount)
    out = {}
    for key, arr in per.items():
        arr.sort()
        top = arr[:config.ART_LOTS_TOP]
        out[key] = {"avg": round(sum(top) / len(top)), "n": len(arr), "min": round(arr[0])}
    return out


class ArtefactLots:
    def __init__(self) -> None:
        self.buckets: dict[str, dict] = {}   # item -> {"qlt:ptn": {avg, n, min}}
        self.updated: float | None = None

    @property
    def _path(self):
        return config.DATA_DIR / "artefact_lots.json"

    def load(self) -> None:
        try:
            if self._path.exists():
                doc = json.loads(self._path.read_text(encoding="utf-8"))
                self.buckets = doc.get("buckets", {})
                self.updated = doc.get("updated")
                logger.info("ArtefactLots: loaded %d items", len(self.buckets))
        except Exception:
            logger.exception("ArtefactLots: failed to load cache")

    def save(self) -> None:
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"updated": self.updated, "buckets": self.buckets}),
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("ArtefactLots: failed to save cache")

    async def _refresh_item(self, client: httpx.AsyncClient, iid: str) -> bool:
        lots: list = []
        offset = 0
        for _ in range(config.ART_LOTS_MAX_PAGES):
            page = await auction.fetch_lots_page(client, iid, offset=offset)
            if page.get("error"):
                logger.warning("ArtefactLots: %s lots failed: %s", iid, page["error"])
                return False
            batch = page.get("lots") or []
            lots.extend(batch)
            if len(batch) < 200:
                break
            offset += len(batch)
        self.buckets[iid] = bucket_lots(lots)  # пустой dict = лотов нет, тоже знание
        return True

    async def loop(self) -> None:
        self.load()
        ids = db.artefact_ids()
        logger.info("ArtefactLots: loop started, every %d min, top-%d cheapest, %d artefacts",
                    config.ART_LOTS_MINUTES, config.ART_LOTS_TOP, len(ids))
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                try:
                    await oauth.ensure(client)
                    ok = 0
                    for iid in ids:
                        try:
                            ok += bool(await self._refresh_item(client, iid))
                        except Exception:
                            logger.exception("ArtefactLots: %s refresh failed", iid)
                    if ok:
                        self.updated = time.time()
                        self.save()
                    logger.info("ArtefactLots: cycle done (%d/%d items)", ok, len(ids))
                except Exception:
                    logger.exception("ArtefactLots: cycle failed")
                await asyncio.sleep(config.ART_LOTS_MINUTES * 60)

    def stats(self) -> dict:
        return {"items": sum(1 for b in self.buckets.values() if b),
                "updated": self.updated}


artlots = ArtefactLots()
