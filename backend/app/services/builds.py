"""Калькулятор сборок артефактов: модель качества/заточки, заражения, автоподбор.

Формулы статов (верифицированы по игре, ROADMAP «Формулы статов»):
  стат = q0max × M × (1 + 0.02 × ptn),
M — множитель качества: тиры непрерывны по +0.15 (Q0 [0.85;1.0] … Q5 [1.6;1.75]).
Вредные статы (красные эмиссии заражения) НЕ масштабируются — константа; полезные
защиты (зелёные, отрицательные accumulation) масштабируются как обычные статы.

Заражения (минусы артефактов) — ЖЁСТКОЕ ограничение:
  net_type = Σ по артам (эмиссия + защита);  контейнер гасит положительное:
  net_eff = net × (1 − Внутр.защита%/100).  Игрок терпит до лимита (радиация/
  температура/био/холод — 1.0, пси — 3.0); отрицательный net — запас защиты,
  не вреден (подтверждено юзером). Превышение оптимизатор чинит в три эшелона:
  замена слабейших слотов контрартами (арты с защитой заражений — «4 арта +
  2 контрарта»), удорожание эмиссии (двойственный подъём λ с демпфером),
  бан худшего эмиттера. Сборка сверх лимитов НЕ выдаётся.

Эффективность контейнера НЕ масштабирует величину статов (в текущей игре это темп
разряда энергии) — суммы берём сырые, как в игровой формуле.

Автоподбор — bounded knapsack: пул (артефакт × качество × заточка) с ценами,
парето-фронт + DP по (слоты × бюджет). Приведённое ХП — та же основа со свипом
λ по (пулестойкость, живучесть), т.к. цель (100+пуле)×живучесть нелинейна.
"""
import math
import random
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
    "frost_accumulation": ("Холод", 1.0),   # лимит 1.0 подтверждён юзером
    "combustion_accumulation": ("Горение", None),
}
CONTAM_KEYS = {f"stalker.artefact_properties.factor.{k}": v for k, v in _CONTAM.items()}
FROST_KEY = "stalker.artefact_properties.factor.frost_accumulation"  # «Холод» — защита НЕ гасит (подтверждено скрином)
ACCUM_KEYS = set(CONTAM_KEYS)  # accumulation-статы идут в блок заражения, не в статы

BUDGET_STEPS = 400   # дискретизация бюджета в DP
ALTERNATIVES = 2     # запасных сборок

# ---------- случайная «сборка дня» ----------
# Модуль главной: раз в сутки крутим случайную сборку из топ-снаряжения.
# Броня и контейнер — только красный (Мастер) / оранжевый (Легенда).
TOP_COLORS = ("RANK_MASTER", "RANK_LEGEND")
# Лестница бюджетов на артефакты (к=тыс, кк=млн, ккк=млрд).
DAILY_BUDGETS = (100_000, 500_000, 1_000_000, 3_000_000, 5_000_000,
                 10_000_000, 50_000_000, 100_000_000, 500_000_000, 1_000_000_000)
DAILY_ARMOR_PTN = (0, 5, 10, 15)     # уровень заточки брони в сборке дня
DAILY_ATTEMPTS = 8                   # детерминированных перекруток, если под ролл нет цен
# Полезные статы для ролла. «Первичные» могут стоять первым параметром; «вторичные»
# (восст. выносливости / регенерация / переносимый вес) — только вторым/третьим.
_STAT_PRIMARY = (
    "stalker.artefact_properties.factor.bullet_dmg_factor",   # Пулестойкость
    "stalker.artefact_properties.factor.speed_modifier",      # Скорость передвижения
    "stalker.artefact_properties.factor.health_bonus",        # Живучесть
    "stalker.artefact_properties.factor.heal_efficiency",     # Эффективность лечения
)
_STAT_SECONDARY = (
    "stalker.artefact_properties.factor.stamina_regeneration_bonus",  # Восст. выносливости
    "stalker.artefact_properties.factor.regeneration_bonus",          # Регенерация здоровья
    "stalker.artefact_properties.factor.max_weight_bonus",            # Переносимый вес
)
_DAILY_STAT_WEIGHTS = (100, 70, 50)  # вес стата по позиции (приоритет первого)

DUAL_ITERS = 8       # шагов двойственного подъёма λ (цены эмиссии) на раунд
BAN_ROUNDS = 3       # раундов «починки» баном худшего эмиттера (1-й — без бана)
DUAL_STEP = 1.5      # стартовый шаг λ; при смене знака превышения — деление пополам


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


def _is_counter(art: dict) -> bool:
    """Контрарт: несёт защиту (зелёный минус) хотя бы по одному лимитированному
    заражению — в игре такими гасят минусы сильных артов («народное» название)."""
    for key, (_n, limit) in CONTAM_KEYS.items():
        if limit is None:
            continue
        st = art["stats"].get(key)
        if st and not st["harmful"]:
            return True
    return False


def _contam_contrib(v: dict, prot: float, eff: float) -> tuple[dict, dict]:
    """Вклады варианта в лимитированные заражения, нормированные на лимит:
    (эмиссия ≥0 с учётом защиты контейнера, защита ≥0 с учётом эффективности)."""
    em: dict = {}
    pr: dict = {}
    stats = db.artefacts[v["item"]]["stats"]
    for key, (_n, limit) in CONTAM_KEYS.items():
        if limit is None:
            continue
        st = stats.get(key)
        if not st:
            continue
        val = stat_value(st, v["m"], v["ptn"])
        if st["harmful"]:
            reduce = 1.0 if key == FROST_KEY else (1.0 - prot)
            if val > 0:
                em[key] = em.get(key, 0.0) + val * reduce / limit
        elif val < 0:
            pr[key] = pr.get(key, 0.0) - val * eff / limit
    return em, pr


def _norms(variants: list[dict]) -> dict:
    """n_k = net/limit по кэшам _em/_pr вариантов; сборка в норме ⇔ все n_k ≤ 1."""
    n: dict = {}
    for v in variants:
        for k, x in v["_em"].items():
            n[k] = n.get(k, 0.0) + x
        for k, x in v["_pr"].items():
            n[k] = n.get(k, 0.0) - x
    return n


def _overage(n: dict) -> float:
    return sum(max(0.0, x - 1.0) for x in n.values())


def _worst_emitter(variants: list[dict], n: dict) -> str | None:
    """id арта, сильнее всех вносящего в самый превышенный тип (для «починки»)."""
    key = max((k for k in n if n[k] > 1.0 + 1e-10), key=lambda k: n[k], default=None)
    if key is None:
        return None
    v = max(variants, key=lambda v: v["_em"].get(key, 0.0))
    return v["item"] if v["_em"].get(key) else None


def _swap_repair(picked: list[dict], pool: list[dict], banned: set,
                 budget: float, score) -> list[dict] | None:
    """Гасим превышение заменой слотов: как игроки — «4 арта + 2 контрарта».
    Жадно меняем слот на вариант из пула (обычно контрарт), выбирая замену с
    минимальной потерей ценности на единицу снятого превышения. None — не вышло."""
    cur = list(picked)
    cost = sum(v["price"] for v in cur)
    for _ in range(len(cur) * 3):
        n = _norms(cur)
        ov = _overage(n)
        if ov <= 1e-10:
            return cur
        best = None    # (ratio, i, cand)
        for i, out_v in enumerate(cur):
            for cand in pool:
                if cand["item"] in banned:
                    continue
                if cost - out_v["price"] + cand["price"] > budget + 1e-9:
                    continue
                n2 = dict(n)
                for k, x in out_v["_em"].items():
                    n2[k] = n2.get(k, 0.0) - x
                for k, x in out_v["_pr"].items():
                    n2[k] = n2.get(k, 0.0) + x
                for k, x in cand["_em"].items():
                    n2[k] = n2.get(k, 0.0) + x
                for k, x in cand["_pr"].items():
                    n2[k] = n2.get(k, 0.0) - x
                red = ov - _overage(n2)
                if red <= 1e-12:
                    continue
                ratio = (score(out_v) - score(cand)) / red
                if best is None or ratio < best[0]:
                    best = (ratio, i, cand)
        if best is None:
            return None
        _, i, cand = best
        cost += cand["price"] - cur[i]["price"]
        cur[i] = cand
    return None


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


def _optimize(pool: list[dict], cont: dict, budget: float, score, banned: set,
              duals: dict | None = None) -> list[dict]:
    """Парето+DP + жёсткие лимиты заражения. Если DP-ядро превышает лимит:
    1) чиним заменой слабейших слотов на контрарты (_swap_repair);
    2) поднимаем цену эмиссии λ (двойственный подъём с демпфером) — DP берёт
       ядро чище; 3) баним худшего эмиттера. Возвращаем ТОЛЬКО сборку в норме
    (лучшую по score из найденных); [] — не собрать. duals — состояние λ
    (тёплый старт между вызовами)."""
    prot = (cont.get("protection") or 0.0) / 100.0
    eff = (cont.get("efficiency") or 100.0) / 100.0
    slots = cont["slots"]
    state = duals if duals is not None else {}
    lam = state.setdefault("lam", {})    # цена единицы отн. эмиссии
    stp = state.setdefault("step", {})   # адаптивный шаг (демпфер осцилляций)
    sgn = state.setdefault("sign", {})   # знак прошлого превышения
    for key, (_n, limit) in CONTAM_KEYS.items():
        if limit is not None:
            lam.setdefault(key, 0.0)
            stp.setdefault(key, DUAL_STEP)
            sgn.setdefault(key, 0)
    for v in pool:
        if "_em" not in v:
            v["_em"], v["_pr"] = _contam_contrib(v, prot, eff)
    local_ban = set(banned)
    best, best_sc = [], -1e18

    def consider(cand: list[dict]) -> None:
        nonlocal best, best_sc
        sc = sum(score(v) for v in cand)
        if sc > best_sc:
            best, best_sc = cand, sc

    for _round in range(BAN_ROUNDS):
        picked = []
        n = {}
        tried_swap = False
        for _ in range(DUAL_ITERS):
            sub = []
            for v in pool:
                if v["item"] in local_ban:
                    continue
                em = v["_em"]
                v = dict(v)
                v["value"] = score(v) - sum(lam[k] * x for k, x in em.items())
                sub.append(v)
            picked = _dp_build(_pareto(sub), slots, budget)
            if not picked:
                return best
            n = _norms(picked)
            if _overage(n) <= 1e-10:
                consider(picked)
            elif not tried_swap:
                tried_swap = True
                fixed = _swap_repair(picked, pool, local_ban, budget, score)
                if fixed:
                    consider(fixed)
            # двойственный шаг: λ растёт на превышении, плавно спадает при запасе;
            # при смене знака превышения шаг делится пополам (гасим осцилляцию)
            moved = False
            for k in lam:
                rel = max(-1.0, min(4.0, n.get(k, 0.0) - 1.0))
                s = 1 if rel > 1e-9 else (-1 if rel < -1e-9 else 0)
                if s and sgn[k] and s != sgn[k]:
                    stp[k] = max(stp[k] * 0.5, 0.05)
                if s:
                    sgn[k] = s
                nl = max(0.0, lam[k] + stp[k] * rel)
                if abs(nl - lam[k]) > 1e-6:
                    moved = True
                lam[k] = nl
            if not moved:
                break    # λ стабилен — лучше не станет
        if best:
            break
        offender = _worst_emitter(picked, n)
        if offender is None:
            break
        local_ban.add(offender)    # чиним баном худшего эмиттера

    # страховка: наружу — только сборка в пределах лимитов
    if best and any(c["over"] for c in contamination(best, cont)):
        return []
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
           "Заражения гасятся внутренней защитой контейнера (кроме холода); сборки "
           "сверх лимитов (рад/темп/био/холод — 1.0, пси — 3.0) не выдаются.",
           _price_note()]
    if builds:
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
        k in art["stats"] and not art["stats"][k]["harmful"] for k in keys)
        or _is_counter(art))
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
            if not st:
                continue
            val = abs(stat_value(st, v["m"], v["ptn"])) / ref[k]
            s += -w * val if st["harmful"] else w * val   # вредная версия стата — в минус
        return s

    builds, banned, seen = [], set(), set()
    for _ in range(1 + ALTERNATIVES):
        picked = _optimize(pool, cont, budget, score, banned)
        key = frozenset((v["item"], v["qlt"], v["ptn"]) for v in picked)
        if not picked or key in seen:
            break
        seen.add(key)
        builds.append(_present_build(picked, cont))
        # баним только носителей запрошенных статов; чистые контрарты (score≈0)
        # оставляем — они нужны и альтернативным сборкам
        banned.update(v["item"] for v in picked if score(v) > 1e-9)

    if not builds:
        return {"error": "no_clean_build",
                "hint": "Под этот бюджет не собрать сборку в пределах лимитов "
                        "заражения — поднимите бюджет, смените контейнер или статы."}
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
    eff = (cont.get("efficiency") or 100.0) / 100.0   # усиливает положительные статы

    def bv(v):
        """Эффективный вклад арта в (пулестой, живучесть): полезный × эффективность,
        вредный (красный минус) — как есть. Минус НЕ игнорируем — иначе оптимизатор
        берёт арты, роняющие живучесть."""
        st = db.artefacts[v["item"]]["stats"]
        out = []
        for key in (BULLET_KEY, HEALTH_KEY):
            s = st.get(key)
            if not s:
                out.append(0.0)
                continue
            val = stat_value(s, v["m"], v["ptn"])
            out.append(val if s["harmful"] else val * eff)
        return out

    pool = _make_pool(budget, lambda art: (
        (BULLET_KEY in art["stats"] and not art["stats"][BULLET_KEY]["harmful"])
        or (HEALTH_KEY in art["stats"] and not art["stats"][HEALTH_KEY]["harmful"])
        or _is_counter(art)))
    if not pool:
        return {"error": "no_priced_variants",
                "hint": "Нет корзин артефактов с пулестойкостью/живучестью под бюджет "
                        "(или биржа ещё копит цены)."}
    for v in pool:
        v["_b"], v["_h"] = bv(v)
    bmax = max((v["_b"] for v in pool), default=0.0) or 1.0
    hmax = max((v["_h"] for v in pool), default=0.0) or 1.0

    # свип λ: value = b_norm + λ·h_norm; каждый λ даёт сборку, оцениваем истинное ХП
    best, best_hp = None, -1.0
    banned: set = set()
    duals: dict = {}   # тёплый старт двойственных штрафов заражения между λ
    lambdas = [0.0] + [round(0.25 * i, 2) for i in range(1, 33)]  # 0 … 8
    for lam in lambdas:
        def score(v, lam=lam):
            return v["_b"] / bmax + lam * (v["_h"] / hmax)
        picked = _optimize(pool, cont, budget, score, banned, duals)
        if not picked:
            continue
        b = base_bullet + sum(v["_b"] for v in picked)
        h = base_vit + sum(v["_h"] for v in picked)
        hp = _eff_hp(b, h)
        if hp > best_hp:
            best_hp, best = hp, picked

    if not best:
        return {"error": "no_clean_build",
                "hint": "Под этот бюджет не собрать сборку в пределах лимитов "
                        "заражения — поднимите бюджет или смените контейнер."}

    res = _present_build(best, cont)
    art_bullet = sum(v["_b"] for v in best)   # eff уже внутри bv
    art_vit = sum(v["_h"] for v in best)
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


# ---------- случайная «сборка дня» для главной ----------
_daily_cache: dict = {"date": None, "payload": None}


def _roll_daily_params(rnd: random.Random) -> dict | None:
    """Детерминированный ролл параметров сборки дня из топ-снаряжения.
    Броня/контейнер — Мастер/Легенда; бюджет — из лестницы; 1–3 полезных стата
    (первый — из первичных, вторичные статы только со 2-й позиции)."""
    armors = [a for a in db.armor.values() if a["color"] in TOP_COLORS]
    conts = [c for c in db.containers.values() if c["color"] in TOP_COLORS]
    if not armors or not conts:
        return None
    armor = rnd.choice(armors)
    cont = rnd.choice(conts)
    budget = rnd.choice(DAILY_BUDGETS)
    armor_ptn = rnd.choice(DAILY_ARMOR_PTN)
    n = rnd.randint(1, 3)
    first = rnd.choice(list(_STAT_PRIMARY))
    keys = [first]
    rest = [k for k in (_STAT_PRIMARY + _STAT_SECONDARY) if k != first]
    rnd.shuffle(rest)
    keys += rest[:n - 1]
    stats_req = [{"key": k, "weight": _DAILY_STAT_WEIGHTS[i]} for i, k in enumerate(keys)]
    return {"armor": armor, "cont": cont, "budget": budget,
            "armor_ptn": armor_ptn, "keys": keys, "stats_req": stats_req}


def _armor_payload(armor: dict, ptn: int) -> dict:
    ast = db.armor_stats(armor["id"], ptn)
    return {"id": armor["id"], "name": armor["name"], "icon": armor["icon"],
            "color": armor["color"], "class": armor.get("class", ""), "ptn": int(ptn),
            "bullet": round(ast["bullet"], 1), "vitality": round(ast["vitality"], 1)}


def _present_daily(today: str, p: dict, res: dict) -> dict:
    """Готовый payload сборки дня: броня + контейнер + подобранные арты + сводное
    приведённое ХП (броня + арты)."""
    build = res["builds"][0]
    armor = _armor_payload(p["armor"], p["armor_ptn"])
    stats = build["totals"]["stats"]
    art_bullet = stats.get(BULLET_KEY, {}).get("total", 0.0)
    art_vit = stats.get(HEALTH_KEY, {}).get("total", 0.0)
    total_bullet = armor["bullet"] + art_bullet
    total_vit = armor["vitality"] + art_vit
    return {
        "date": today,
        "budget": p["budget"],
        "armor": armor,
        "container": res["container"],
        "stat_keys": p["keys"],
        "stat_names": [db.artefact_stat_names[k]["name"] for k in p["keys"]],
        "build": build,
        "hp": {"armor_bullet": armor["bullet"], "armor_vitality": armor["vitality"],
               "artefact_bullet": round(art_bullet, 1), "artefact_vitality": round(art_vit, 1),
               "total_bullet": round(total_bullet, 1), "total_vitality": round(total_vit, 1),
               "effective_hp": round(_eff_hp(total_bullet, total_vit))},
        "warnings": res.get("warnings", []),
    }


def daily_build() -> dict:
    """Случайная сборка дня для главной: параметры фиксированы сидом-датой (МСК),
    сборка считается один раз в сутки и кэшируется. Если под ролл нет ценовых
    корзин — берём следующую детерминированную перекрутку того же дня; если цен
    нет вовсе (биржа не прогрелась) — вернём параметры без сборки и НЕ кэшируем."""
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    if _daily_cache["date"] == today and _daily_cache["payload"]:
        return _daily_cache["payload"]
    first_params = None
    for attempt in range(DAILY_ATTEMPTS):
        rnd = random.Random(f"{today}#{attempt}")
        p = _roll_daily_params(rnd)
        if not p:
            return {"date": today, "error": "no_equipment",
                    "hint": "Нет данных брони/контейнеров топ-редкости."}
        if first_params is None:
            first_params = p
        res = auto_build(float(p["budget"]), p["cont"]["id"], p["stats_req"])
        if res.get("builds"):
            payload = _present_daily(today, p, res)
            _daily_cache["date"] = today
            _daily_cache["payload"] = payload
            return payload
    # цен ещё нет — показываем параметры дня без сборки, без кэша (повторим позже)
    p = first_params
    return {"date": today, "budget": p["budget"], "armor": _armor_payload(p["armor"], p["armor_ptn"]),
            "container": p["cont"], "stat_keys": p["keys"],
            "stat_names": [db.artefact_stat_names[k]["name"] for k in p["keys"]],
            "build": None,
            "hint": "Биржа артефактов ещё копит цены — сборка дня появится после первых замеров."}
