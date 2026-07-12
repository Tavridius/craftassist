"""Калькулятор сборок артефактов: модель качества/заточки, заражения, автоподбор.

Формулы статов (верифицированы по игре, ROADMAP «Формулы статов»):
  стат = q0max × M × (1 + 0.02 × ptn),
M — множитель качества: тиры непрерывны по +0.15 (Q0 [0.85;1.0] … Q5 [1.6;1.75]).
Вредные статы (красные эмиссии заражения) НЕ масштабируются — константа; полезные
защиты (зелёные, отрицательные accumulation) масштабируются как обычные статы.

Заражения (минусы артефактов) — учитываются как ОГРАНИЧЕНИЕ:
  net_type = Σ по артам (эмиссия + защита);  контейнер гасит положительное:
  net_eff = net × (1 − Внутр.защита%/100).  Игрок терпит до лимита (радиация/
  температура/био — 1.0, пси — 3.0). Оптимизатор штрафует эмиттеров и чинит сборку
  (банит худшего) при превышении.

Эффективность контейнера НЕ масштабирует величину статов (в текущей игре это темп
разряда энергии) — суммы берём сырые, как в игровой формуле.

Автоподбор — bounded knapsack: пул (артефакт × качество × заточка) с ценами,
парето-фронт + DP по (слоты × бюджет). Приведённое ХП — та же основа со свипом
λ по (пулестойкость, живучесть), т.к. цель (100+пуле)×живучесть нелинейна.
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
PTN_LEVELS = (0, 5, 10, 15)  # уровни заточки в автоподборе (решение юзера)
# Заточка НЕлинейна (выведено из игровых тултипов Креветки/Браслета):
# множитель к положительным статам = 1 + a·ptn + b·ptn²  →  +0×1.0, +5×1.10,
# +10×1.35, +15×1.74. Проверено: Креветка +15 M1.15 пуле 7.1×1.15×1.739=14.2 (в игре 14.2).
SHARP_A, SHARP_B = 0.0053667, 0.0029267


def sharp(ptn: int) -> float:
    return 1.0 + SHARP_A * ptn + SHARP_B * ptn * ptn

BULLET_KEY = "stalker.artefact_properties.factor.bullet_dmg_factor"
HEALTH_KEY = "stalker.artefact_properties.factor.health_bonus"

# accumulation-стат -> (тип заражения, лимит игрока). None — лимит не задокументирован.
_CONTAM = {
    "radiation_accumulation": ("Радиация", 1.0),
    "thermal_accumulation": ("Температура", 1.0),
    "biological_accumulation": ("Биозаражение", 1.0),
    "psycho_accumulation": ("Пси-излучение", 3.0),
    "frost_accumulation": ("Холод", None),
    "combustion_accumulation": ("Горение", None),
}
CONTAM_KEYS = {f"stalker.artefact_properties.factor.{k}": v for k, v in _CONTAM.items()}
FROST_KEY = "stalker.artefact_properties.factor.frost_accumulation"  # «Холод» — защита НЕ гасит (подтверждено скрином)
ACCUM_KEYS = set(CONTAM_KEYS)  # accumulation-статы идут в блок заражения, не в статы

BUDGET_STEPS = 400   # дискретизация бюджета в DP
ALTERNATIVES = 2     # запасных сборок
CONTAM_PENALTY = 2.5  # штраф оптимизатора за заражение (в единицах ценности)
REPAIR_ITERS = 6     # попыток «починить» сборку баном худшего эмиттера


def tier_bounds(qlt: int) -> tuple[float, float]:
    top = 1.0 + TIER_STEP * qlt
    return (M_MIN if qlt == 0 else top - TIER_STEP), top


def qlt_from_m(m: float) -> int:
    if m <= 1.0:
        return 0
    return min(5, math.ceil(round((m - 1.0) / TIER_STEP, 9)))


def stat_base(st: dict) -> float:
    return st["max"] if abs(st["max"]) >= abs(st["min"]) else st["min"]


def tier_frac(m: float) -> float:
    """Позиция M внутри своего тира [0..1] (для вредных статов)."""
    lo, hi = tier_bounds(qlt_from_m(m))
    return max(0.0, min(1.0, (m - lo) / (hi - lo))) if hi > lo else 1.0


def stat_value(st: dict, m: float, ptn: int) -> float:
    """Полезные: q0max × M × заточка(ptn). Вредные (эмиссия): заточкой НЕ растут,
    внутри тира интерполируются от меньшего к большему модулю (проверено тултипами:
    Пси Креветки 1.17 при M1.08 → 1.25 при M1.15; заточка Пси не меняет)."""
    if st["harmful"]:
        lo = st["min"] if abs(st["min"]) <= abs(st["max"]) else st["max"]  # меньший модуль
        hi = st["max"] if abs(st["max"]) >= abs(st["min"]) else st["min"]
        return lo + (hi - lo) * tier_frac(m)
    return stat_base(st) * m * sharp(ptn)


def milestones(ptn: int) -> list[int]:
    """Уровни заточки +5/+10/+15 выше текущего — каждый даёт случайный доп-бонус."""
    return [m for m in (5, 10, 15) if m > ptn]


# ---------- цены корзин (кэш 60 с) ----------
_prices_cache: dict = {"ts": 0.0, "prices": {}}


def _history_mature() -> bool:
    first = market.stats().get("first_slot")
    week_ago = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
    return bool(first) and first <= week_ago


def bucket_prices() -> dict:
    """{(item, qlt, ptn): {price, n, src}}. Источник — config.BUILD_PRICE_SOURCE."""
    if time.time() - _prices_cache["ts"] <= 60:
        return _prices_cache["prices"]
    src = config.BUILD_PRICE_SOURCE
    out: dict = {}
    if src != "avg7d":
        for iid, bks in artlots.buckets.items():
            for key, b in bks.items():
                qlt, ptn = key.split(":")
                out[(iid, int(qlt), int(ptn))] = {"price": b["avg"], "n": b["n"], "src": "lots"}
    if src == "avg7d" or (src == "auto" and _history_mature()):
        since = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
        for r in market.window_avgs(since):
            if r["n"] >= config.ART_MIN_SALES:
                out[(r["item"], r["qlt"], r["ptn"])] = {"price": round(r["avg"]),
                                                        "n": r["n"], "src": "avg7d"}
    _prices_cache["prices"] = out
    _prices_cache["ts"] = time.time()
    return out


# ---------- заражения ----------
def contamination(variants: list[dict], cont: dict) -> list[dict]:
    """Заражение по типам. Эмиссия (красный, +) гасится внутренней защитой
    контейнера (кроме мороза); защита (зелёный, −) усиливается эффективностью."""
    prot = (cont.get("protection") or 0.0) / 100.0
    eff = (cont.get("efficiency") or 100.0) / 100.0
    out = []
    for key, (name, limit) in CONTAM_KEYS.items():
        emit = protect = 0.0
        present = False
        for v in variants:
            st = db.artefacts[v["item"]]["stats"].get(key)
            if not st:
                continue
            present = True
            val = stat_value(st, v["m"], v["ptn"])
            if st["harmful"]:        # эмиссия заражения (константа)
                emit += val
            else:                    # защита — положительное свойство, ×эффективность
                protect += val * eff
        if not present:
            continue
        reduce = 1.0 if key == FROST_KEY else (1 - prot)  # мороз защита не гасит
        net = emit * reduce + protect
        out.append({"key": key, "name": name, "net": round(net, 3), "limit": limit,
                    "over": limit is not None and net > limit + 1e-9})
    return out


def _contam_penalty(v: dict, prot: float) -> float:
    """Штраф варианта за эмиссию заражения к лимитированным типам (норм. на лимит)."""
    p = 0.0
    for key, (_n, limit) in CONTAM_KEYS.items():
        if limit is None:
            continue
        st = db.artefacts[v["item"]]["stats"].get(key)
        if st:
            val = stat_value(st, v["m"], v["ptn"])
            if val > 0:
                p += val * (1 - prot) / limit
    return p


def _worst_emitter(variants: list[dict], contam: list[dict]) -> str | None:
    """id арта, сильнее всех вносящего в самый превышенный тип (для «починки»)."""
    over = [c for c in contam if c["over"]]
    if not over:
        return None
    worst = max(over, key=lambda c: c["net"] - (c["limit"] or 0))
    key = worst["key"]
    best_id, best_val = None, 0.0
    for v in variants:
        st = db.artefacts[v["item"]]["stats"].get(key)
        if st:
            val = stat_value(st, v["m"], v["ptn"])
            if val > best_val:
                best_val, best_id = val, v["item"]
    return best_id


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
                          "color": it.get("color", "DEFAULT"),
                          "class": art["class"], "weight": art["weight"], "stats": art["stats"]})
    armor = sorted(db.armor.values(), key=lambda a: (-a["bullet0"], a["name"]))
    contam = [{"key": k, "name": n, "limit": lim} for k, (n, lim) in CONTAM_KEYS.items()]
    return {"containers": containers, "stats": stats, "artefacts": artefacts,
            "armor": armor, "contamination": contam,
            "model": {"m_min": M_MIN, "m_max": M_MAX, "tier_step": TIER_STEP,
                      "sharp_a": SHARP_A, "sharp_b": SHARP_B, "ptn_levels": list(PTN_LEVELS),
                      "min_sales": config.ART_MIN_SALES,
                      "bullet_key": BULLET_KEY, "health_key": HEALTH_KEY}}


# ---------- пул вариантов ----------
def _make_pool(budget: float, keep) -> list[dict]:
    """Варианты (артефакт × qlt × ptn) с ценой ≤ бюджета. keep(art)->bool — фильтр
    (даёт ли арт нужный вклад). Каждый вариант несёт vals всех своих статов."""
    prices = bucket_prices()
    pool = []
    for iid, art in db.artefacts.items():
        if not keep(art):
            continue
        for qlt in range(6):
            m = tier_bounds(qlt)[1]  # дефолт: верх тира
            for ptn in PTN_LEVELS:
                p = prices.get((iid, qlt, ptn))
                if not p or p["price"] > budget:
                    continue
                pool.append({"item": iid, "qlt": qlt, "ptn": ptn, "m": m,
                             "price": p["price"], "sales": p["n"], "src": p["src"]})
    return pool


def _pareto(pool: list[dict]) -> list[dict]:
    pool = sorted(pool, key=lambda v: (v["price"], -v["value"]))
    frontier, best = [], -1e18
    for v in pool:
        if v["value"] > best + 1e-12:
            frontier.append(v)
            best = v["value"]
    return frontier


def _dp_build(frontier: list[dict], slots: int, budget: float) -> list[dict]:
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
    picked, b = [], max(range(B + 1), key=lambda x: dp[x])
    for s in range(slots - 1, -1, -1):
        i = choice[s][b]
        if i >= 0:
            picked.append(frontier[i])
            b -= costs[i]
    return picked


def _optimize(pool: list[dict], cont: dict, budget: float, score, banned: set) -> list[dict]:
    """Парето+DP+штраф заражения+починка. score(v)->ценность (до штрафа)."""
    prot = (cont.get("protection") or 0.0) / 100.0
    slots = cont["slots"]
    local_ban = set(banned)
    best = []
    for _ in range(REPAIR_ITERS):
        sub = []
        for v in pool:
            if v["item"] in local_ban:
                continue
            v = dict(v)
            v["value"] = score(v) - CONTAM_PENALTY * _contam_penalty(v, prot)
            sub.append(v)
        picked = _dp_build(_pareto(sub), slots, budget)
        if not picked:
            break
        best = picked
        contam = contamination(picked, cont)
        offender = _worst_emitter(picked, contam)
        if offender is None:
            return picked          # заражение в норме
        local_ban.add(offender)    # чиним: баним худшего эмиттера, пробуем снова
    return best


# ---------- презентация сборки ----------
def _present_build(picked: list[dict], cont: dict) -> dict:
    eff = (cont.get("efficiency") or 100.0) / 100.0
    slots_out, totals_stats = [], {}
    cost = weight = 0.0
    low_liq = []
    for v in picked:
        it = db.items.get(v["item"], {})
        art = db.artefacts[v["item"]]
        vals = {}
        for k, st in art["stats"].items():
            val = round(stat_value(st, v["m"], v["ptn"]), 4)   # интринсик арта (как в тултипе)
            vals[k] = {"name": st["name"], "val": val, "harmful": st["harmful"]}
            if k in ACCUM_KEYS:        # заражения — в блоке contamination, не в статах
                continue
            t = totals_stats.setdefault(k, {"name": st["name"], "harmful": st["harmful"], "total": 0.0})
            t["total"] += val * eff if not st["harmful"] else val   # эффективность на положительные
        cost += v["price"]
        weight += art["weight"] or 0.0
        thin = v["sales"] < (3 if v["src"] == "lots" else config.ART_MIN_SALES * 3)
        if thin:
            low_liq.append(f"{it.get('name', v['item'])} Q{v['qlt']} +{v['ptn']}")
        slots_out.append({"item": v["item"], "name": it.get("name", v["item"]),
                          "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
                          "qlt": v["qlt"], "ptn": v["ptn"], "price": round(v["price"]),
                          "sales": v["sales"], "src": v["src"], "stats": vals,
                          "milestones": milestones(v["ptn"])})
    for t in totals_stats.values():
        t["total"] = round(t["total"], 3)
    return {"slots": slots_out,
            "totals": {"cost": round(cost),
                       "weight": round(weight + (cont.get("weight") or 0), 2),
                       "protection": cont.get("protection"),
                       "stats": totals_stats,
                       "contamination": contamination(picked, cont)},
            "low_liquidity": low_liq}


def _price_note() -> str:
    return ("Цены — средние недельные с биржи." if _history_mature()
            and config.BUILD_PRICE_SOURCE != "lots"
            else f"Цены — средняя из {config.ART_LOTS_TOP} самых дешёвых живых лотов "
                 "(биржа копит первую неделю истории).")


def _warnings(builds: list[dict]) -> list[str]:
    out = ["Случайные доп-свойства заточки (+5/+10/+15) и свежесть не моделируются.",
           "Заражения гасятся внутренней защитой контейнера; лимиты игрока: радиация/"
           "температура/био — 1.0, пси — 3.0.",
           _price_note()]
    if builds:
        for c in builds[0]["totals"]["contamination"]:
            if c["over"]:
                out.append(f"⚠ {c['name']} {c['net']} превышает лимит {c['limit']} — "
                           "под этот бюджет чище не собрать.")
        for name in builds[0].get("low_liquidity", []):
            out.append(f"Корзина {name} малоликвидна — цена ориентировочная.")
    return out


# ---------- автоподбор по статам ----------
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

    pool = _make_pool(budget, lambda art: any(
        k in art["stats"] and not art["stats"][k]["harmful"] for k in keys))
    if not pool:
        return {"error": "no_priced_variants",
                "hint": "Биржа артефактов ещё копит цены (нужна неделя замеров) "
                        "или под бюджет/статы нет корзин с достаточными продажами."}
    # нормировка статов на максимум по пулу — веса сопоставимы
    ref = {}
    for k in keys:
        m = 0.0
        for v in pool:
            st = db.artefacts[v["item"]]["stats"].get(k)
            if st and not st["harmful"]:
                m = max(m, abs(stat_value(st, v["m"], v["ptn"])))
        ref[k] = m or 1.0

    def score(v):
        art = db.artefacts[v["item"]]["stats"]
        s = 0.0
        for k, w in weights.items():
            st = art.get(k)
            if st and not st["harmful"]:
                s += w * abs(stat_value(st, v["m"], v["ptn"])) / ref[k]
        return s

    builds, banned = [], set()
    for _ in range(1 + ALTERNATIVES):
        picked = _optimize(pool, cont, budget, score, banned)
        if not picked:
            break
        builds.append(_present_build(picked, cont))
        banned.update(v["item"] for v in picked)

    return {"container": cont, "stat_keys": keys, "builds": builds,
            "pool_size": len(pool), "warnings": _warnings(builds)}


# ---------- приведённое ХП от пулестойкости ----------
def _eff_hp(bullet: float, vit_pct: float) -> float:
    """(100 базового ХП + пулестойкость) × живучесть. Формула из игры."""
    return (100.0 + bullet) * (1.0 + vit_pct / 100.0)


def auto_hp(budget: float, container_id: str, armor_id: str, armor_ptn: int) -> dict:
    cont = db.containers.get(container_id)
    if not cont:
        return {"error": "container_not_found"}
    armor = db.armor.get(armor_id)
    if not armor:
        return {"error": "armor_not_found"}
    if budget <= 0:
        return {"error": "bad_request"}
    ast = db.armor_stats(armor_id, armor_ptn)
    base_bullet, base_vit = ast["bullet"], ast["vitality"]

    def bv(v):
        st = db.artefacts[v["item"]]["stats"]
        b = stat_value(st[BULLET_KEY], v["m"], v["ptn"]) if BULLET_KEY in st and not st[BULLET_KEY]["harmful"] else 0.0
        h = stat_value(st[HEALTH_KEY], v["m"], v["ptn"]) if HEALTH_KEY in st and not st[HEALTH_KEY]["harmful"] else 0.0
        return b, h

    pool = _make_pool(budget, lambda art: (
        (BULLET_KEY in art["stats"] and not art["stats"][BULLET_KEY]["harmful"])
        or (HEALTH_KEY in art["stats"] and not art["stats"][HEALTH_KEY]["harmful"])))
    if not pool:
        return {"error": "no_priced_variants",
                "hint": "Нет корзин артефактов с пулестойкостью/живучестью под бюджет "
                        "(или биржа ещё копит цены)."}
    for v in pool:
        v["_b"], v["_h"] = bv(v)
    bmax = max((v["_b"] for v in pool), default=0.0) or 1.0
    hmax = max((v["_h"] for v in pool), default=0.0) or 1.0

    # свип λ: value = b_norm + λ·h_norm; каждый λ даёт сборку, оцениваем истинное ХП
    eff = (cont.get("efficiency") or 100.0) / 100.0   # эффективность усиливает вклад артов
    best, best_hp = None, -1.0
    banned: set = set()
    lambdas = [0.0] + [round(0.25 * i, 2) for i in range(1, 33)]  # 0 … 8
    for lam in lambdas:
        def score(v, lam=lam):
            return v["_b"] / bmax + lam * (v["_h"] / hmax)
        picked = _optimize(pool, cont, budget, score, banned)
        if not picked:
            continue
        b = base_bullet + eff * sum(v["_b"] for v in picked)
        h = base_vit + eff * sum(v["_h"] for v in picked)
        hp = _eff_hp(b, h)
        if hp > best_hp:
            best_hp, best = hp, picked

    if not best:
        return {"error": "no_priced_variants",
                "hint": "Не удалось собрать под бюджет."}

    res = _present_build(best, cont)
    eff = (cont.get("efficiency") or 100.0) / 100.0   # усиливает вклад артефактов
    art_bullet = sum(v["_b"] for v in best) * eff
    art_vit = sum(v["_h"] for v in best) * eff
    total_bullet = base_bullet + art_bullet
    total_vit = base_vit + art_vit
    res["hp"] = {
        "armor": {"id": armor_id, "name": armor["name"], "icon": armor["icon"],
                  "color": armor["color"], "ptn": int(armor_ptn),
                  "bullet": round(base_bullet, 2), "vitality": round(base_vit, 2)},
        "artefact_bullet": round(art_bullet, 2),
        "artefact_vitality": round(art_vit, 2),
        "total_bullet": round(total_bullet, 2),
        "total_vitality": round(total_vit, 2),
        "base_hp": 100,
        "effective_hp": round(_eff_hp(total_bullet, total_vit)),
    }
    return {"container": cont, "builds": [res], "pool_size": len(pool),
            "warnings": _warnings([res])}
