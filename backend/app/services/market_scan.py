"""ДЕВ-сканер выгодных лотов аука (вкладка /dev/scan, только админы).

Своих запросов к API НЕ делает — питается данными фонового обходчика PriceStore:
после каждого замера лотов (_fetch) и истории (_fetch_history) хуки on_lots /
on_history пересчитывают «сделку» предмета. Сигнал: у ликвидного предмета
(продаж/час ≥ порога) на ауке стоят лоты дешевле средней из последних N продаж
на заданный процент и с достаточной маржой. Карточки сделок уходят подключённым
админам по вебсокету /api/ws/dev/scan; когда дешёвые лоты разобрали или предмет
ушёл с аука — прилетает remove (следующий проход обходчика это заметит).

Цены сравниваются ТОЛЬКО внутри корзины качество(qlt)×заточка(ptn): у одного
артефакта средняя качества 2 — 21 тыс, качества 4 — 380 тыс, и «дешёвый» лот
низкого качества не имеет отношения к средней по всем продажам. База средней:
последние N продаж этой же корзины, а у артефактов (живых продаж в корзине мало)
— недельная средняя корзины из биржи артефактов (market.db).

Пороги настраиваются с /dev/scan на лету и живут в data/scan_settings.json.
У брони/оружия/обвесов свой порог продаж/час (min_sph_gear): они продаются
редко, но дорогие — пропускать их из-за общего порога ликвидности нельзя.
Флаг hist_all добавляет ВСЕ предметы крафт-графа в ротацию истории продаж
(без него история снимается только у крафт-результатов и открывавшихся карточек).
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app import config
from app.db import market
from app.db.index import db

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

# Категории снаряжения: свой порог продаж/час + цена зависит от заточки.
GEAR_CATS = ("weapon", "armor", "attachment", "weapon_modules",
             "containers", "backpacks")


class MarketScan:
    def __init__(self) -> None:
        self.settings: dict = self._defaults()
        self.deals: dict[str, dict] = {}   # iid -> карточка сделки
        self.clients: set = set()          # подключённые вебсокеты админов

    @staticmethod
    def _defaults() -> dict:
        return {
            "enabled": config.SCAN_ENABLED,
            "min_sph": config.SCAN_MIN_SPH,          # мин. продаж/час
            "min_sph_gear": config.SCAN_MIN_SPH_GEAR,  # то же для брони/оружия/обвесов
            "discount_pct": config.SCAN_DISCOUNT_PCT,  # лот дешевле средней на ≥ %
            "avg_n": config.SCAN_AVG_N,              # средняя из последних N продаж
            "min_margin": config.SCAN_MIN_MARGIN,    # мин. маржа ₽/шт (после комиссии)
            "max_age_min": config.SCAN_MAX_AGE_MIN,  # лоты не старше N минут
            "show_artefacts": config.SCAN_SHOW_ARTEFACTS,  # показывать артефакты
            "hist_all": config.SCAN_HIST_ALL,        # история по всем предметам графа
        }

    @property
    def _path(self):
        return config.DATA_DIR / "scan_settings.json"

    # ---------- настройки ----------
    def load(self) -> None:
        try:
            if self._path.exists():
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                self.settings = self._clamp({**self.settings, **saved})
        except Exception:
            logger.exception("market_scan: failed to load settings")

    def save(self) -> None:
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("market_scan: failed to save settings")

    @staticmethod
    def _clamp(s: dict) -> dict:
        def num(key, lo, hi, cast=float):
            try:
                return min(hi, max(lo, cast(s.get(key))))
            except (TypeError, ValueError):
                return MarketScan._defaults()[key]
        return {
            "enabled": bool(s.get("enabled")),
            "min_sph": num("min_sph", 0, 10000),
            "min_sph_gear": num("min_sph_gear", 0, 10000),
            "discount_pct": num("discount_pct", 0, 90),
            "avg_n": num("avg_n", 1, 20, int),   # recent_sales храним до 20 продаж
            "min_margin": num("min_margin", 0, 10**9),
            "max_age_min": num("max_age_min", 1, 1440),
            "show_artefacts": bool(s.get("show_artefacts")),
            "hist_all": bool(s.get("hist_all")),
        }

    def update_settings(self, patch: dict) -> dict:
        merged = {**self.settings, **{k: patch[k] for k in self._defaults() if k in patch}}
        self.settings = self._clamp(merged)
        self.save()
        self.reeval_all()
        # полный снапшот всем клиентам: после смены порогов список сделок другой
        self.broadcast({"type": "snapshot", **self.snapshot()})
        return self.settings

    def wants_history_all(self) -> bool:
        """Обходчику: снимать ли историю продаж по ВСЕМ предметам графа."""
        return self.settings["enabled"] and self.settings["hist_all"]

    def min_sph_for(self, iid: str) -> float:
        """Порог ликвидности предмета: у снаряжения свой (продаётся редко)."""
        return (self.settings["min_sph_gear"]
                if db.category(iid) in GEAR_CATS else self.settings["min_sph"])

    def skipped(self, iid: str) -> bool:
        """Предмет исключён настройками (сейчас — выключенные артефакты)."""
        return db.category(iid) == "artefact" and not self.settings["show_artefacts"]

    def hot_ids(self) -> list[str]:
        """«Горячие» предметы — ликвидные настолько, что могут стать сделкой
        (продаж/час ≥ своего порога). Их лоты обходчик снимает вне общей очереди:
        у остальных сколько ни смотри лоты, условие сделки не выполнится.
        Самые ликвидные первыми, длина ограничена — круг должен быть коротким;
        отсечённые редколиквидные всё равно обходятся общим кругом."""
        if not self.settings["enabled"]:
            return []
        from app.services.price_store import store
        hot = [(h.get("sales_per_hour") or 0.0, iid)
               for iid, h in store.history.items()
               if (h.get("sales_per_hour") or 0.0) >= self.min_sph_for(iid)
               and not self.skipped(iid)]
        hot.sort(reverse=True)
        return [iid for _, iid in hot[:config.SCAN_HOT_MAX]]

    def rotation_ids(self) -> list[str]:
        """Что добавить в обход цен ради сканера: артефакты (их нет в крафт-графе,
        а флипать их выгоднее всего) и снаряжение, дотягивающее до своего порога.
        Мёртвое снаряжение в обход не берём — история его отсеет и так."""
        if not self.settings["enabled"]:
            return []
        from app.services.price_store import store
        ids = [] if not self.settings["show_artefacts"] else list(db.category_ids("artefact"))
        lo = self.settings["min_sph_gear"]
        ids += [i for i in db.category_ids(*GEAR_CATS)
                if (store.history.get(i, {}).get("sales_per_hour") or 0.0) >= lo]
        return ids

    def probe_ids(self) -> list[str]:
        """Кому нужна история продаж ради сканера (даже если предмета нет в
        крафт-графе): арты и всё снаряжение. Мёртвые переспрашиваются редко —
        интервал регулирует PriceStore._hist_due по темпу продаж."""
        if not self.settings["enabled"]:
            return []
        cats = GEAR_CATS + (("artefact",) if self.settings["show_artefacts"] else ())
        return db.category_ids(*cats)

    # ---------- детект сделки ----------
    @staticmethod
    def _split(entry) -> tuple:
        """Запись лота/продажи [цена/шт, кол-во, качество?, заточка?] →
        (цена/шт, кол-во, корзина). Хвоста нет в записях старого кэша (снятых
        до additional=true) — такие считаем базовой корзиной 0/0."""
        e = list(entry) + [0, 0]
        return e[0], e[1], (int(e[2] or 0), market.ptn_bucket(int(e[3] or 0)))

    def _bucket_avgs(self, iid: str, h: dict, n: int) -> dict:
        """Средние по корзинам (качество, заточка): {(qlt, ptn): (средняя, источник)}.

        Основа — последние N продаж ЭТОЙ корзины. У артефактов живых продаж в
        корзине обычно меньше N, поэтому добираем недельной средней корзины из
        биржи артефактов (market.db) — она же кормит калькулятор сборок.
        """
        by_bucket: dict = {}
        for sale in (h.get("recent_sales") or []):
            unit, _, key = self._split(sale)
            by_bucket.setdefault(key, []).append(unit)

        out = {}
        for key, units in by_bucket.items():
            win = units[:n]
            if len(win) < n:
                continue
            # защита средней от «продаж за 50 цен» (перевод валюты через аук):
            # сделки дороже ART_OUTLIER_FACTOR × минимума окна не учитываем
            cap = min(win) * config.ART_OUTLIER_FACTOR
            win = [u for u in win if u <= cap]
            out[key] = (sum(win) / len(win), "сделки")

        if db.category(iid) == "artefact":
            since = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
            try:
                week = market.item_bucket_avgs(iid, since)
            except Exception:
                week = {}
            for key, agg in week.items():
                if key not in out and agg["n"] >= config.ART_MIN_SALES:
                    out[key] = (agg["avg"], "7д")
        return out

    def evaluate(self, iid: str) -> dict | None:
        """Карточка сделки по кэшам обходчика или None (условия не выполнены).

        Лоты и средние сравниваются строго внутри корзины качество×заточка;
        из подошедших корзин берём ту, где лучший лот даёт наибольшую маржу.
        """
        if not self.settings["enabled"] or self.skipped(iid):
            return None
        from app.services.price_store import store  # lazy: price_store импортирует нас
        h, p = store.history.get(iid), store.prices.get(iid)
        if not h or not p or not p.get("available"):
            return None
        # актуальность: лоты, снятые давно, скорее всего уже выкуплены. Без этой
        # отсечки в выдачу попадали карточки на ценах многочасовой давности
        # (предмет мог вообще выпасть из ротации и лежать в кэше со вчера).
        age = time.time() - (p.get("ts") or 0)
        if age > self.settings["max_age_min"] * 60:
            return None
        sph = h.get("sales_per_hour") or 0.0
        if sph < self.min_sph_for(iid):
            return None
        n = self.settings["avg_n"]
        avgs = self._bucket_avgs(iid, h, n)
        if not avgs:
            return None

        # лоты по корзинам (в старом кэше записи без качества — корзина 0/0)
        lots_by_bucket: dict = {}
        for lot in (p.get("depth") or []):
            unit, amount, key = self._split(lot)
            lots_by_bucket.setdefault(key, []).append((unit, amount))

        disc = self.settings["discount_pct"] / 100
        best_deal = None
        for key, (avg, src) in avgs.items():
            lots = lots_by_bucket.get(key)
            if not lots:
                continue
            net = avg * (1 - config.AUCTION_FEE)   # выручка с 1 шт после комиссии
            qual = sorted((u, a) for u, a in lots if u <= avg * (1 - disc))
            if not qual:
                continue
            margin = net - qual[0][0]              # маржа/шт на лучшем лоте
            if margin < self.settings["min_margin"]:
                continue
            margin_lot = max(round((net - u) * a) for u, a in qual)
            if best_deal and margin_lot <= best_deal["margin_lot"]:
                continue
            qty = sum(a for _, a in qual)
            it = db.item(iid) or {}
            best_deal = {
                "id": iid,
                "name": it.get("name", iid),
                "icon": it.get("icon", ""),
                "color": it.get("color", "DEFAULT"),
                "cat": db.category(iid),
                "qlt": key[0], "ptn": key[1],   # корзина сделки
                "avg_src": src,                 # откуда средняя: сделки / 7д
                "price": round(qual[0][0]),
                "qty": qty,
                "lots": len(qual),
                # топ-3 дешёвых лота корзины [[цена/шт, кол-во], …] — прямо на
                # карточке, чтобы лот было легко опознать в ауке
                "top_lots": [[round(u), a] for u, a in qual[:3]],
                # последние продажи ЭТОЙ корзины [[цена/шт, кол-во], …]
                "recent_sales": [[round(u), a] for u, a, k
                                 in map(self._split, h.get("recent_sales") or [])
                                 if k == key][:5],
                "avg": round(avg),
                "n": n,
                "sph": sph,
                "discount": round((1 - qual[0][0] / avg) * 100, 1),
                "margin": round(margin),
                "margin_lot": margin_lot,          # маржа лучшего ОДНОГО лота
                "margin_total": round(margin * qty),
                "ts": p.get("ts"),
                "found_ts": time.time(),
            }
        return best_deal

    def refresh(self, iid: str, broadcast: bool = True) -> None:
        """Пересчитать сделку предмета; при изменениях — разослать клиентам."""
        old = self.deals.get(iid)
        deal = self.evaluate(iid)
        if deal:
            if old:
                deal["found_ts"] = old["found_ts"]
            self.deals[iid] = deal
            if broadcast:
                self.broadcast({"type": "deal", "deal": deal})
        elif old:
            del self.deals[iid]
            if broadcast:
                self.broadcast({"type": "remove", "id": iid})

    # хуки обходчика: свежие лоты / история предмета
    def on_lots(self, iid: str) -> None:
        try:
            self.refresh(iid)
        except Exception:
            logger.exception("market_scan: on_lots(%s) failed", iid)

    def on_history(self, iid: str) -> None:
        try:
            self.refresh(iid)
        except Exception:
            logger.exception("market_scan: on_history(%s) failed", iid)

    async def sweep_loop(self) -> None:
        """Снимать протухшие карточки, не дожидаясь следующего замера предмета.

        Обычно сделка исчезает, когда обходчик заново снял лоты. Но если предмет
        выпал из ротации (или круг задержался), карточка висела бы вечно на
        старых данных — раз в полминуты проверяем возраст и убираем такие.
        """
        while True:
            await asyncio.sleep(30)
            try:
                limit = self.settings["max_age_min"] * 60
                from app.services.price_store import store
                now = time.time()
                for iid in [i for i, d in self.deals.items()
                            if now - (store.prices.get(i, {}).get("ts") or 0) > limit]:
                    self.refresh(iid)   # evaluate вернёт None → карточка снимется
            except Exception:
                logger.exception("market_scan: sweep failed")

    def reeval_all(self) -> None:
        """Полный пересчёт по кэшам (смена настроек / посев на старте)."""
        from app.services.price_store import store
        for iid in set(store.history) & set(store.prices) | set(self.deals):
            self.refresh(iid, broadcast=False)

    def seed(self) -> None:
        """Старт приложения: сделки из персистентных кэшей обходчика, без рассылки
        (клиентов ещё нет). recent_units появятся после первого цикла на новом коде."""
        self.load()
        self.reeval_all()
        logger.info("market_scan: seeded %d deals (enabled=%s, hist_all=%s)",
                    len(self.deals), self.settings["enabled"], self.settings["hist_all"])

    # ---------- выдача ----------
    def snapshot(self) -> dict:
        deals = sorted(self.deals.values(),
                       key=lambda d: d["margin_total"], reverse=True)
        return {"settings": self.settings, "deals": deals, "stats": self.stats()}

    def stats(self) -> dict:
        from app.services.price_store import store
        return {
            "deals": len(self.deals),
            "hist_items": len(store.history),
            "priced": len(store.prices),
            "hot": store.hot_count,              # предметов в горячем круге
            "hot_round_sec": store.hot_round_sec,  # длительность последнего круга
            "cycle_age_sec": (round(time.time() - store.last_cycle_ts)
                              if store.last_cycle_ts else None),
        }

    # ---------- вебсокет ----------
    def broadcast(self, msg: dict) -> None:
        """Разослать событие всем клиентам (сбойные — отключаем). Вне event loop
        (не должно случаться: хуки зовут воркер и эндпоинты) молча пропускаем."""
        if not self.clients:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        data = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.clients):
            loop.create_task(self._send(ws, data))

    async def _send(self, ws, data: str) -> None:
        try:
            await ws.send_text(data)
        except Exception:
            self.clients.discard(ws)


scan = MarketScan()
