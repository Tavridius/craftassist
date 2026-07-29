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
import statistics
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


def bucket_page(prices: list, floor: datetime, raw: dict) -> tuple[datetime | None, bool]:
    """Раскладывает страницу истории (новые → старые) по корзинам (qlt, ptn),
    собирая сырые цены за 1 шт в raw[(qlt, ptn)]. Отсечку выбросов и агрегаты
    считает finalize_buckets по всей выборке снапшота (нужен минимум корзины).

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
        ptn = market.ptn_bucket(int(a.get("ptn") or 0))  # котируем +0/+5/+10/+15
        raw.setdefault((int(qlt), ptn), []).append(price / amount)
    return newest, False


def finalize_buckets(raw: dict, refs: dict | None = None) -> dict:
    """Сырые цены корзин {(qlt, ptn): [цена/шт]} → агрегаты {n, sum, min, max, med}.

    Отсечка выбросов, по приоритету (подробности и замеры — в config.py):
    1. Есть опора refs[(qlt, ptn)] (устоявшаяся цена корзины по истории) —
       держим коридор [ref/F, ref×F], F = ART_SPIKE_FACTOR. Это и ловит разовые
       сделки: привязка к минимуму ТОГО ЖЕ снапшота при n=1 бесполезна, потому
       что минимум и есть сама выбросовая сделка.
    2. Опоры нет (первые замеры корзины) — прежний резерв: ART_OUTLIER_FACTOR ×
       минимум корзины в снапшоте.

    Если вся выборка вне коридора — принимаем как новый уровень цены только при
    ДВУХ условиях: сделок >= ART_SHIFT_MIN_SALES и отклонение медианы меньше
    ART_SHIFT_MAX_FACTOR. Иначе корзину за слот НЕ пишем вовсе — честнее «не
    знаем», чем записать выброс. Одного объёма мало: перевод валюты делают и в
    4-20 сделок; одного веса слота при чтении тоже мало: у дешёвого артефакта
    сделка ×1500 сопоставима со всем недельным оборотом.
    """
    out = {}
    for key, units in raw.items():
        ref = (refs or {}).get(key)
        if ref and ref > 0:
            lo, hi = ref / config.ART_SPIKE_FACTOR, ref * config.ART_SPIKE_FACTOR
            kept = [u for u in units if lo <= u <= hi]
            if not kept:
                dev = max(statistics.median(units) / ref, ref / statistics.median(units))
                if (len(units) < config.ART_SHIFT_MIN_SALES
                        or dev > config.ART_SHIFT_MAX_FACTOR):
                    continue                      # выброс, а не сдвиг — слот пропускаем
                kept = units                      # сдвиг подтверждён объёмом и масштабом
        else:
            cap = min(units) * config.ART_OUTLIER_FACTOR
            kept = [u for u in units if u <= cap]  # минимум всегда проходит — kept непуст
        out[key] = {"n": len(kept), "sum": sum(kept), "min": min(kept),
                    "max": max(kept), "med": statistics.median(kept)}
    return out


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

        raw: dict = {}              # (qlt, ptn) -> [цена/шт]; фильтр — в finalize_buckets
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
            newest, reached_floor = bucket_page(prices, floor, raw)
            if newest and (newest_all is None or newest > newest_all):
                newest_all = newest
            if reached_floor or len(prices) < 200:
                break
            offset += len(prices)
        # у sales_log своя граница sale_ts — страницы передаём одним вызовом
        sales_log.record(iid, all_prices)
        # опора для отсечки — устоявшаяся цена корзин по истории (не по этому снапшоту)
        ref_since = self._slot_key(datetime.now(MSK) - timedelta(days=config.ART_REF_DAYS))
        buckets = finalize_buckets(raw, market.bucket_refs(iid, ref_since))

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
