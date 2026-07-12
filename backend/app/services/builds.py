"""Калькулятор сборок артефактов: модель качества/заточки + автоподбор.

Формулы верифицированы по игре (см. ROADMAP «Формулы статов»):
  стат = q0max × M × (1 + 0.02 × ptn),
где q0max — верх диапазона базового json (окно ОБЫЧНОГО), M — множитель
качества: тиры непрерывны по +0.15 (Q0 [0.85;1.0] … Q5 [1.6;1.75]).
Вредные статы (красные) не масштабируются вовсе — берём верх диапазона.

Автоподбор: bounded knapsack с ограничением слотов. Пул вариантов
(артефакт × качество × заточка 0/5/10/15) с ценами avg7d из market.db
режется парето-фронтом (для линейной целевой функции достаточно
недоминируемых вариантов), дальше точный DP по (слоты × бюджет).
"""
import math
import time
from datetime import datetime, timedelta

from app import config
from app.db import market
from app.db.index import db
from app.services.artefact_lots import artlots
from app.services.artefact_watch import MSK

M_MIN, M_MAX = 0.85, 1.75
TIER_STEP = 0.15
PTN_BONUS = 0.02            # +2% от базы за уровень заточки
PTN_LEVELS = (0, 5, 10, 15)  # уровни заточки в автоподборе (решение юзера)
RADIATION_KEY = "stalker.artefact_properties.factor.radiation_accumulation"

BUDGET_STEPS = 400   # дискретизация бюджета в DP (шаг 0.25%)
ALTERNATIVES = 2     # сколько запасных сборок отдавать


def tier_bounds(qlt: int) -> tuple[float, float]:
    """Границы множителя M для тира качества: Q0 [0.85;1.0], далее по +0.15."""
    top = 1.0 + TIER_STEP * qlt
    return (M_MIN if qlt == 0 else top - TIER_STEP), top


def qlt_from_m(m: float) -> int:
    """Тир качества по множителю M (верх тира принадлежит тиру)."""
    if m <= 1.0:
        return 0
    return min(5, math.ceil(round((m - 1.0) / TIER_STEP, 9)))


def stat_base(st: dict) -> float:
    """Опорное значение (Q0-max по модулю): конец диапазона с большим модулем.
    У статов «меньше — лучше» (Кровотечение) он отрицательный — знак сохраняем,
    масштаб по скринам Ягодки: Q5 = −0.6×1.75 = −1.05."""
    return st["max"] if abs(st["max"]) >= abs(st["min"]) else st["min"]


def stat_value(st: dict, m: float, ptn: int) -> float:
    """Значение стата для множителя качества M и заточки. Вредные — константа."""
    if st["harmful"]:
        return stat_base(st)
    return stat_base(st) * m * (1 + PTN_BONUS * ptn)


# ---------- цены корзин (кэш 60 с) ----------
_prices_cache: dict = {"ts": 0.0, "prices": {}}


def _history_mature() -> bool:
    """Истории ≥ 7 дней — можно переходить на среднюю недельную."""
    first = market.stats().get("first_slot")
    week_ago = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
    return bool(first) and first <= week_ago


def bucket_prices() -> dict:
    """{(item, qlt, ptn): {price, n, src}}.

    Источник по config.BUILD_PRICE_SOURCE:
      lots  — средняя из ART_LOTS_TOP самых дешёвых живых лотов корзины;
      avg7d — средняя недельная цена продаж (биржа истории);
      auto  — лоты, пока история не накопила 7 дней; после — история поверх
              лотов (корзины без недельных данных остаются на лотах).
    """
    if time.time() - _prices_cache["ts"] <= 60:
        return _prices_cache["prices"]
    src = config.BUILD_PRICE_SOURCE
    out: dict = {}
    if src != "avg7d":
        for iid, bks in artlots.buckets.items():
            for key, b in bks.items():
                qlt, ptn = key.split(":")
                out[(iid, int(qlt), int(ptn))] = {"price": b["avg"], "n": b["n"],
                                                  "src": "lots"}
    if src == "avg7d" or (src == "auto" and _history_mature()):
        since = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
        for r in market.window_avgs(since):
            if r["n"] >= config.ART_MIN_SALES:
                out[(r["item"], r["qlt"], r["ptn"])] = {"price": round(r["avg"]),
                                                        "n": r["n"], "src": "avg7d"}
    _prices_cache["prices"] = out
    _prices_cache["ts"] = time.time()
    return out


# ---------- справочник для фронта ----------
def build_dict() -> dict:
    stats = [{"key": k, **v} for k, v in db.artefact_stat_names.items()]
    stats.sort(key=lambda s: (s["harmful"], s["name"]))
    containers = sorted(db.containers.values(),
                        key=lambda c: (c["slots"], c.get("weight") or 0, c["name"]))
    artefacts = []
    for iid, art in sorted(db.artefacts.items(), key=lambda kv: db.items[kv[0]]["name"]):
        it = db.items.get(iid, {})
        artefacts.append({"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
                          "class": art["class"], "weight": art["weight"], "stats": art["stats"]})
    return {"containers": containers, "stats": stats, "artefacts": artefacts,
            "model": {"m_min": M_MIN, "m_max": M_MAX, "tier_step": TIER_STEP,
                      "ptn_bonus": PTN_BONUS, "ptn_levels": list(PTN_LEVELS),
                      "min_sales": config.ART_MIN_SALES}}


# ---------- автоподбор ----------
def _make_pool(keys: list[str], budget: float, banned: set[str]) -> list[dict]:
    """Варианты (артефакт × qlt × ptn) с ценой avg7d, дающие хоть один нужный стат."""
    prices = bucket_prices()
    pool = []
    for iid, art in db.artefacts.items():
        if iid in banned:
            continue
        contrib = {k: art["stats"][k] for k in keys
                   if k in art["stats"] and not art["stats"][k]["harmful"]}
        if not contrib:
            continue
        for qlt in range(6):
            m = tier_bounds(qlt)[1]  # дефолт модели: верх тира
            for ptn in PTN_LEVELS:
                p = prices.get((iid, qlt, ptn))
                if not p or p["price"] > budget:  # avg7d уже отфильтрован по n
                    continue
                pool.append({
                    "item": iid, "qlt": qlt, "ptn": ptn, "m": m,
                    "price": p["price"], "sales": p["n"], "src": p["src"],
                    "vals": {k: stat_value(st, m, ptn) for k, st in contrib.items()},
                })
    return pool


def _score_pool(pool: list[dict], weights: dict[str, float]) -> None:
    """Линейная ценность варианта: Σ вес × |стат| / максимум по пулу."""
    ref = {k: max((abs(v["vals"].get(k, 0.0)) for v in pool), default=0.0) or 1.0
           for k in weights}
    for v in pool:
        v["value"] = sum(w * abs(v["vals"].get(k, 0.0)) / ref[k]
                         for k, w in weights.items())


def _pareto(pool: list[dict]) -> list[dict]:
    """Недоминируемые варианты (цена ↑, ценность строго ↑) — для линейной цели
    оптимум всегда собирается из них."""
    pool = sorted(pool, key=lambda v: (v["price"], -v["value"]))
    frontier, best = [], -1.0
    for v in pool:
        if v["value"] > best + 1e-12:
            frontier.append(v)
            best = v["value"]
    return frontier


def _dp_build(frontier: list[dict], slots: int, budget: float) -> list[dict]:
    """Точный рюкзак: ≤ slots предметов (повторы разрешены), Σцен ≤ бюджет."""
    if not frontier:
        return []
    step = max(budget / BUDGET_STEPS, 1.0)
    B = int(budget / step)
    costs = [math.ceil(v["price"] / step) for v in frontier]

    dp = [0.0] * (B + 1)
    choice: list[list[int]] = []
    for _ in range(slots):
        nxt = dp[:]
        ch = [-1] * (B + 1)
        for i, v in enumerate(frontier):
            c = costs[i]
            if c > B:
                continue
            val = v["value"]
            for b in range(c, B + 1):
                cand = dp[b - c] + val
                if cand > nxt[b] + 1e-12:
                    nxt[b] = cand
                    ch[b] = i
        dp = nxt
        choice.append(ch)

    picked = []
    b = max(range(B + 1), key=lambda x: dp[x])
    for s in range(slots - 1, -1, -1):
        i = choice[s][b]
        if i >= 0:
            picked.append(frontier[i])
            b -= costs[i]
    return picked


def auto_build(budget: float, container_id: str, stats_req: list[dict]) -> dict:
    cont = db.containers.get(container_id)
    if not cont:
        return {"error": "container_not_found"}
    weights = {}
    for s in stats_req[:3]:
        k = s.get("key")
        if k in db.artefact_stat_names and not db.artefact_stat_names[k]["harmful"]:
            weights[k] = max(0.0, min(100.0, float(s.get("weight", 50)))) / 100.0
    if not weights or budget <= 0:
        return {"error": "bad_request"}
    keys = list(weights)

    pool = _make_pool(keys, budget, set())
    if not pool:
        return {"error": "no_priced_variants",
                "hint": "Биржа артефактов ещё копит цены (нужна неделя замеров) "
                        "или под бюджет/статы нет корзин с достаточными продажами."}
    _score_pool(pool, weights)

    builds, banned = [], set()
    for _ in range(1 + ALTERNATIVES):
        sub = [v for v in pool if v["item"] not in banned]
        picked = _dp_build(_pareto(sub), cont["slots"], budget)
        if not picked:
            break
        builds.append(_present_build(picked, cont, keys))
        banned.update(v["item"] for v in picked)

    return {"container": cont, "stat_keys": keys, "builds": builds,
            "pool_size": len(pool),
            "warnings": _warnings(builds)}


def _present_build(picked: list[dict], cont: dict, keys: list[str]) -> dict:
    eff = (cont.get("efficiency") or 100.0) / 100.0
    slots_out, totals_stats = [], {}
    cost = weight = radiation = 0.0
    low_liq = []
    for v in picked:
        it = db.items.get(v["item"], {})
        art = db.artefacts[v["item"]]
        vals = {}
        for k, st in art["stats"].items():
            val = stat_value(st, v["m"], v["ptn"])
            vals[k] = round(val, 4)
            t = totals_stats.setdefault(k, {"name": st["name"], "harmful": st["harmful"],
                                            "total": 0.0})
            t["total"] += val if st["harmful"] else val * eff
        cost += v["price"]
        weight += art["weight"] or 0.0
        rad = art["stats"].get(RADIATION_KEY)
        radiation += stat_base(rad) if rad else 0.0
        thin = v["sales"] < (3 if v["src"] == "lots" else config.ART_MIN_SALES * 3)
        if thin:
            low_liq.append(f"{it.get('name', v['item'])} Q{v['qlt']} +{v['ptn']}")
        slots_out.append({"item": v["item"], "name": it.get("name", v["item"]),
                          "icon": it.get("icon", ""), "qlt": v["qlt"], "ptn": v["ptn"],
                          "price": round(v["price"]), "sales": v["sales"],
                          "src": v["src"], "stats": vals})
    for t in totals_stats.values():
        t["total"] = round(t["total"], 3)
    return {"slots": slots_out,
            "totals": {"cost": round(cost), "weight": round(weight + (cont.get("weight") or 0), 2),
                       "radiation": round(radiation, 3),
                       "protection": cont.get("protection"),
                       "stats": totals_stats},
            "low_liquidity": low_liq}


def _warnings(builds: list[dict]) -> list[str]:
    price_note = ("Цены — средние недельные с биржи." if _history_mature()
                  and config.BUILD_PRICE_SOURCE != "lots"
                  else f"Цены — средняя из {config.ART_LOTS_TOP} самых дешёвых живых лотов "
                       "(биржа копит первую неделю истории).")
    out = ["Случайные доп-свойства заточки (+5/+10/+15) и свежесть не моделируются.",
           price_note]
    for b in builds[:1]:
        for name in b.get("low_liquidity", []):
            out.append(f"Корзина {name} малоликвидна — цена ориентировочная.")
    return out
