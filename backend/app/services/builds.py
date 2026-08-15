"""Калькулятор сборок артефактов: модель качества/заточки, заражения, автоподбор.

Формулы статов (верифицированы по игре, ROADMAP «Формулы статов»):
  стат = q0max × M × (1 + 0.02 × ptn),
M — множитель качества: тиры непрерывны по +0.15 (Q0 [0.85;1.0] … Q5 [1.6;1.75]).
Вредные статы (красные эмиссии заражения) НЕ масштабируются — константа; полезные
защиты (зелёные, отрицательные accumulation) масштабируются как обычные статы.

Заражения (минусы артефактов) — ЖЁСТКОЕ ограничение:
  net_type = Σ по артам (эмиссия + защита);  контейнер гасит положительное:
  net_eff = net × (1 − Внутр.защита%/100).  Игрок терпит СТРОГО НИЖЕ лимита
  (радиация/температура/био/холод — 1.0, пси — 3.0): на самом значении лимита
  урон уже идёт — 2.99 по пси безопасно, 3.0 бьёт (владелец, 15.08.2026), см.
  CONTAM_CEIL и _ceil. Отрицательный net — запас защиты,
  не вреден (подтверждено юзером). Превышение оптимизатор чинит в три эшелона:
  замена слабейших слотов контрартами (арты с защитой заражений — «4 арта +
  2 контрарта»), удорожание эмиссии (двойственный подъём λ с демпфером),
  бан худшего эмиттера. Сборка сверх лимитов НЕ выдаётся.

Эффективность контейнера НЕ масштабирует величину статов (в текущей игре это темп
разряда энергии) — суммы берём сырые, как в игровой формуле.

Доп-свойства порогов заточки (+5/+10/+15): фиксированный пул арта
(BONUS_PROPS из db/art_bonus_props.json), значение = base × M × заточка;
случаен только порядок разблокировки → учёт матожиданием (bonus_factor),
на +15 у обычных артов (пул 3) — детерминированно все три.

Автоподбор — bounded knapsack: пул (артефакт × качество × заточка) с ценами,
парето-фронт + DP по (слоты × бюджет). Приведённое ХП — та же основа со свипом
λ по (пулестойкость, живучесть), т.к. цель (100+пуле)×живучесть нелинейна.
"""
import json
import math
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from app import config
from app.db import market
from app.db.index import db
from app.services.artefact_lots import artlots
from app.services.artefact_watch import MSK

M_MIN, M_MAX = 0.85, 1.75
TIER_STEP = 0.15
PTN_LEVELS = (0, 5, 10, 15)  # уровни заточки в автоподборе (решение юзера)
# Заточка ЛИНЕЙНА: +2% от базы за уровень (+15 = ×1.30). Подтверждено файлами
# _variants (Батарейка zy32, Креветка gyg5: все 15 уровней ровно 1+0.02·ptn).
# Квадратичная калибровка по тултипам была ошибкой — в тултипы входили случайные
# доп-свойства порогов +5/+10/+15, которых нет в статической базе (баг VeilSol:
# Батарейка 1.84 ск.бега показывала +15→3.20 вместо 2.39). Форма a·ptn + b·ptn²
# оставлена ради совместимости с фронтом (константы уезжают в payload модели).
SHARP_A, SHARP_B = 0.02, 0.0


def sharp(ptn: int) -> float:
    return 1.0 + SHARP_A * ptn + SHARP_B * ptn * ptn

BULLET_KEY = "stalker.artefact_properties.factor.bullet_dmg_factor"
HEALTH_KEY = "stalker.artefact_properties.factor.health_bonus"
SPEED_KEY = "stalker.artefact_properties.factor.speed_modifier"
HEAL_KEY = "stalker.artefact_properties.factor.heal_efficiency"
STAMINA_KEY = "stalker.artefact_properties.factor.stamina_regeneration_bonus"
REGEN_KEY = "stalker.artefact_properties.factor.regeneration_bonus"
WEIGHT_KEY = "stalker.artefact_properties.factor.max_weight_bonus"

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

CONTAM_CEIL = 1.0 - 1e-6   # потолок нормированного заражения (net/limit), см. _ceil
BUDGET_STEPS = 400   # дискретизация бюджета в DP
ALTERNATIVES = 2     # запасных сборок

# ---------- случайная «сборка дня» ----------
# Модуль главной: раз в сутки крутим случайную сборку из топ-снаряжения.
# Броня и контейнер — только красный (Мастер) / оранжевый (Легенда).
TOP_COLORS = ("RANK_MASTER", "RANK_LEGEND")
# Лестница бюджетов на артефакты (к=тыс, кк=млн, ккк=млрд).
DAILY_BUDGETS = (100_000, 500_000, 1_000_000, 3_000_000, 5_000_000,
                 10_000_000, 50_000_000, 100_000_000, 500_000_000, 1_000_000_000)
DAILY_ARMOR_PTN = (15,)              # уровень заточки брони в сборке дня — только +15
DAILY_ATTEMPTS = 8                   # детерминированных перекруток, если под ролл нет цен
# Полезные статы для ролла. «Первичные» могут стоять первым параметром; «вторичные»
# (восст. выносливости / регенерация / переносимый вес) — только вторым/третьим.
_STAT_PRIMARY = (BULLET_KEY, SPEED_KEY, HEALTH_KEY, HEAL_KEY)
_STAT_SECONDARY = (STAMINA_KEY, REGEN_KEY, WEIGHT_KEY)
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


# ---------- доп-свойства заточки (+5/+10/+15) ----------
# Пул фиксированных доп-свойств артефакта (снят со stalzone.wiki —
# db/art_bonus_props.json). Величина НЕ случайна: base × M × заточка(ptn),
# верифицировано 9 тултипами (20.07.2026, см. ROADMAP). Случаен только порядок
# разблокировки: +5 — одно свойство пула, +10 — второе, +15 — третье. Учитываем
# матожиданием (разблокировано/размер пула): у обычных артов (пул из 3) на +15
# это ровно 1.0 — детерминировано; у Рубика (пул из 24) — всегда доля.
_BONUS_FILE = Path(__file__).resolve().parents[1] / "db" / "art_bonus_props.json"


def _load_bonus_props() -> dict:
    try:
        raw = json.loads(_BONUS_FILE.read_text(encoding="utf-8"))["props"]
    except Exception:
        return {}
    return {iid: [{"key": p["key"], "name": p.get("name_ru") or p["key"],
                   "base": p["max"] if abs(p["max"]) >= abs(p["min"]) else p["min"]}
                  for p in props]
            for iid, props in raw.items()}


BONUS_PROPS = _load_bonus_props()


def bonus_factor(iid: str, ptn: int) -> float:
    """Матожидание активности одного свойства пула на данной заточке."""
    pool = BONUS_PROPS.get(iid)
    if not pool:
        return 0.0
    return sum(1 for t in (5, 10, 15) if ptn >= t) / len(pool)


def bonus_value(bp: dict, m: float, ptn: int) -> float:
    """Полное значение доп-свойства (как в тултипе): base × M × заточка."""
    return bp["base"] * m * sharp(ptn)


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
                k = (iid, int(qlt), market.ptn_bucket(int(ptn)))
                prev = out.get(k)
                if prev:  # легаси-кэш лотов с сырой заточкой — сливаем в корзину
                    n = prev["n"] + b["n"]
                    price = round((prev["price"] * prev["n"] + b["avg"] * b["n"]) / n)
                    out[k] = {"price": price, "n": n, "src": "lots"}
                else:
                    out[k] = {"price": b["avg"], "n": b["n"], "src": "lots"}
    if src == "avg7d" or (src == "auto" and _history_mature()):
        since = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%dT%H:00")
        for r in market.window_avgs(since):
            if r["n"] >= config.ART_MIN_SALES:
                out[(r["item"], r["qlt"], r["ptn"])] = {"price": round(r["avg"]),
                                                        "n": r["n"], "src": "avg7d"}
    _prices_cache["prices"] = out
    _prices_cache["ts"] = time.time()
    return out


# ---------- собственные статы хранилища (контейнер/рюкзак) ----------
def _self_bonus(cont: dict) -> list[dict]:
    """Собственные полезные/вредные статы хранилища, КРОМЕ заражений — идут в ИТОГО
    плоско (это финальные значения предмета, эффективностью не масштабируются)."""
    return [s for s in cont.get("self_stats", []) if s["key"] not in ACCUM_KEYS]


def _self_contam(cont: dict) -> dict:
    """Собственный вклад хранилища в заражения: {key: сырое значение} (эмиссия +,
    защита −). Внутр. защита/эффективность его не трогают — это свойство предмета."""
    out: dict = {}
    for s in cont.get("self_stats", []):
        if s["key"] in CONTAM_KEYS and s["val"]:
            out[s["key"]] = out.get(s["key"], 0.0) + s["val"]
    return out


def _self_contam_norm(cont: dict) -> dict:
    """То же, нормированное на лимит: {key: val/limit} (база для оптимизатора)."""
    out: dict = {}
    for key, v in _self_contam(cont).items():
        limit = CONTAM_KEYS[key][1]
        if limit is not None:
            out[key] = v / limit
    return out


# ---------- заражения ----------
def contamination(variants: list[dict], cont: dict) -> list[dict]:
    """Заражение по типам. Эмиссия (красный, +) гасится внутренней защитой
    контейнера (кроме мороза); защита (зелёный, −) усиливается эффективностью.
    Собственный вклад хранилища (эмиссия/защита самого контейнера или рюкзака)
    добавляется как есть, без гашения защитой и без ×эффективности."""
    prot = (cont.get("protection") or 0.0) / 100.0
    eff = (cont.get("efficiency") or 100.0) / 100.0
    self_c = _self_contam(cont)
    out = []
    for key, (name, limit) in CONTAM_KEYS.items():
        emit = protect = 0.0
        present = key in self_c
        for v in variants:
            st = db.artefacts[v["item"]]["stats"].get(key)
            if st:
                present = True
                val = stat_value(st, v["m"], v["ptn"])
                if st["harmful"]:    # эмиссия заражения (константа)
                    emit += val
                else:                # защита — положительное свойство, ×эффективность
                    protect += val * eff
            f = bonus_factor(v["item"], v["ptn"])
            if f:                    # доп-свойства порогов: в пулах только защиты (−)
                for bp in BONUS_PROPS.get(v["item"], []):
                    if bp["key"] != key:
                        continue
                    present = True
                    bval = bonus_value(bp, v["m"], v["ptn"]) * f
                    if bval > 0:
                        emit += bval
                    else:
                        protect += bval * eff
        if not present:
            continue
        reduce = 1.0 if key == FROST_KEY else (1 - prot)  # мороз защита не гасит
        net = emit * reduce + protect + self_c.get(key, 0.0)
        out.append({"key": key, "name": name, "net": round(net, 3), "limit": limit,
                    # строго ниже лимита: на самом значении урон уже идёт (см. _ceil)
                    "over": limit is not None and net > limit * CONTAM_CEIL})
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
    f = bonus_factor(v["item"], v["ptn"])
    if f:   # доп-свойства порогов: отрицательные accumulation = защита
        for bp in BONUS_PROPS.get(v["item"], []):
            lim = CONTAM_KEYS.get(bp["key"])
            if not lim or lim[1] is None:
                continue
            bval = bonus_value(bp, v["m"], v["ptn"]) * f
            if bval > 0:
                reduce = 1.0 if bp["key"] == FROST_KEY else (1.0 - prot)
                em[bp["key"]] = em.get(bp["key"], 0.0) + bval * reduce / lim[1]
            elif bval < 0:
                pr[bp["key"]] = pr.get(bp["key"], 0.0) - bval * eff / lim[1]
    return em, pr


def _norms(variants: list[dict], base: dict | None = None) -> dict:
    """n_k = net/limit по кэшам _em/_pr вариантов + база хранилища (его собственная
    эмиссия/защита); сборка в норме ⇔ все n_k ≤ 1."""
    n: dict = dict(base) if base else {}
    for v in variants:
        for k, x in v["_em"].items():
            n[k] = n.get(k, 0.0) + x
        for k, x in v["_pr"].items():
            n[k] = n.get(k, 0.0) - x
    return n


def _ceil(key: str) -> float:
    """Потолок нормированного ограничения. У заражений он СТРОГИЙ: лимит — это
    значение, на котором урон уже идёт (по пси 2.99 безопасно, 3.0 бьёт —
    подтверждено владельцем 15.08.2026), поэтому держим микрозазор. Оптимизатор
    здесь knapsack: без зазора он охотно садится ровно на лимит, и сборка на
    ровных 3.0 уезжала игроку помеченной как безопасная. Ограничения «минус не в
    итоге» (псевдоключи «!стат») к заражениям отношения не имеют — там ровно 1.0.
    """
    return 1.0 if key.startswith("!") else CONTAM_CEIL


def _overage(n: dict) -> float:
    return sum(max(0.0, x - _ceil(k)) for k, x in n.items())


def _worst_emitter(variants: list[dict], n: dict) -> str | None:
    """id арта, сильнее всех вносящего в самый превышенный тип (для «починки»)."""
    key = max((k for k in n if n[k] > _ceil(k) + 1e-10), key=lambda k: n[k], default=None)
    if key is None:
        return None
    v = max(variants, key=lambda v: v["_em"].get(key, 0.0))
    return v["item"] if v["_em"].get(key) else None


def _swap_repair(picked: list[dict], pool: list[dict], banned: set,
                 budget: float, score, base: dict | None = None) -> list[dict] | None:
    """Гасим превышение заменой слотов: как игроки — «4 арта + 2 контрарта».
    Жадно меняем слот на вариант из пула (обычно контрарт), выбирая замену с
    минимальной потерей ценности на единицу снятого превышения. None — не вышло."""
    cur = list(picked)
    cost = sum(v["price"] for v in cur)
    for _ in range(len(cur) * 3):
        n = _norms(cur, base)
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
    stor_key = lambda c: (c["slots"], c.get("weight") or 0, c["name"])  # noqa: E731
    containers = sorted(db.containers.values(), key=stor_key)
    backpacks = sorted(db.backpacks.values(), key=stor_key)
    artefacts = []
    for iid, art in sorted(db.artefacts.items(), key=lambda kv: db.items[kv[0]]["name"]):
        it = db.items.get(iid, {})
        artefacts.append({"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
                          "color": it.get("color", "DEFAULT"),
                          "class": art["class"], "weight": art["weight"], "stats": art["stats"],
                          "bonus": BONUS_PROPS.get(iid, [])})
    armor = sorted(db.armor.values(), key=lambda a: (-a["bullet0"], a["name"]))
    contam = [{"key": k, "name": n, "limit": lim} for k, (n, lim) in CONTAM_KEYS.items()]
    return {"containers": containers, "backpacks": backpacks, "stats": stats,
            "artefacts": artefacts, "armor": armor, "contamination": contam,
            "model": {"m_min": M_MIN, "m_max": M_MAX, "tier_step": TIER_STEP,
                      "sharp_a": SHARP_A, "sharp_b": SHARP_B, "ptn_levels": list(PTN_LEVELS),
                      "min_sales": config.ART_MIN_SALES,
                      "bullet_key": BULLET_KEY, "health_key": HEALTH_KEY}}


# ---------- запрет минуса в итоге (исключение отрицательных эффектов) ----------
def _harm_sign(key: str) -> int:
    """Вредное направление обычного стата — знак значений его красной версии:
    у живучести вреден минус (−1), у отдачи/кровотечения — плюс (+1)."""
    for art in db.artefacts.values():
        st = art["stats"].get(key)
        if st and st["harmful"]:
            v = stat_base(st)
            if v:
                return 1 if v > 0 else -1
    return 0


def _neg_constraints(pool: list[dict], cont: dict, keys: set) -> dict:
    """{stat_key: (sign, scale)} — «минус не нужен» как жёсткое ограничение на
    ИТОГ сборки (не на отдельный арт): суммарный стат не должен уйти во вредную
    сторону, минус одного арта можно перекрыть плюсом других (просьба юзера,
    пример Креветка −живка + Ягодка +живка). scale — максимум |вклада| по пулу:
    нормирует ограничение для двойственного подъёма λ."""
    eff = (cont.get("efficiency") or 100.0) / 100.0
    out = {}
    for k in keys:
        s = _harm_sign(k)
        if not s:
            continue
        scale = 1.0
        for v in pool:
            st = db.artefacts[v["item"]]["stats"].get(k)
            if st:
                val = stat_value(st, v["m"], v["ptn"])
                scale = max(scale, abs(val if st["harmful"] else val * eff))
            f = bonus_factor(v["item"], v["ptn"])
            if f:
                for bp in BONUS_PROPS.get(v["item"], []):
                    if bp["key"] == k:
                        scale = max(scale, abs(bonus_value(bp, v["m"], v["ptn"])) * f * eff)
        out[k] = (s, scale)
    return out


# ---------- пул вариантов ----------
def _make_pool(budget: float, keep) -> list[dict]:
    """Варианты (артефакт × qlt × ptn) с ценой ≤ бюджета. keep(iid, art)->bool —
    фильтр (даёт ли арт нужный вклад). Каждый вариант несёт vals всех статов."""
    prices = bucket_prices()
    pool = []
    for iid, art in db.artefacts.items():
        if not keep(iid, art):
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
              duals: dict | None = None, neg: dict | None = None) -> list[dict]:
    """Парето+DP + жёсткие лимиты заражения. Если DP-ядро превышает лимит:
    1) чиним заменой слабейших слотов на контрарты (_swap_repair);
    2) поднимаем цену эмиссии λ (двойственный подъём с демпфером) — DP берёт
       ядро чище; 3) баним худшего эмиттера. Возвращаем ТОЛЬКО сборку в норме
    (лучшую по score из найденных); [] — не собрать. duals — состояние λ
    (тёплый старт между вызовами). neg (_neg_constraints) — запрет минуса в
    ИТОГЕ по обычным статам: та же машинерия, псевдоключи «!стат»."""
    prot = (cont.get("protection") or 0.0) / 100.0
    eff = (cont.get("efficiency") or 100.0) / 100.0
    slots = cont["slots"]
    neg = neg or {}
    cont_base = _self_contam_norm(cont)   # собственная эмиссия/защита хранилища
    for k, (s, scale) in neg.items():
        # порог: итог×знак ≤ 0 ⇔ норма ≤ 1 при базе 1 + знак×собств.вклад/scale
        selfv = sum(x["val"] for x in cont.get("self_stats", []) if x["key"] == k)
        cont_base["!" + k] = 1.0 + s * selfv / scale
    state = duals if duals is not None else {}
    lam = state.setdefault("lam", {})    # цена единицы отн. эмиссии
    stp = state.setdefault("step", {})   # адаптивный шаг (демпфер осцилляций)
    sgn = state.setdefault("sign", {})   # знак прошлого превышения
    dual_keys = [key for key, (_n, limit) in CONTAM_KEYS.items()
                 if limit is not None] + ["!" + k for k in neg]
    for key in dual_keys:
        lam.setdefault(key, 0.0)
        stp.setdefault(key, DUAL_STEP)
        sgn.setdefault(key, 0)
    for v in pool:
        if "_em" not in v:
            v["_em"], v["_pr"] = _contam_contrib(v, prot, eff)
            for k, (s, scale) in neg.items():
                t = 0.0                                    # вклад во вредную сторону
                st = db.artefacts[v["item"]]["stats"].get(k)
                if st:
                    val = stat_value(st, v["m"], v["ptn"])
                    t += s * (val if st["harmful"] else val * eff)
                f = bonus_factor(v["item"], v["ptn"])
                if f:                                      # допы всегда в полезную сторону
                    for bp in BONUS_PROPS.get(v["item"], []):
                        if bp["key"] == k:
                            t += s * bonus_value(bp, v["m"], v["ptn"]) * eff * f
                if t > 0:
                    v["_em"]["!" + k] = t / scale
                elif t < 0:
                    v["_pr"]["!" + k] = -t / scale
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
            n = _norms(picked, cont_base)
            if _overage(n) <= 1e-10:
                consider(picked)
            elif not tried_swap:
                tried_swap = True
                fixed = _swap_repair(picked, pool, local_ban, budget, score, cont_base)
                if fixed:
                    consider(fixed)
            # двойственный шаг: λ растёт на превышении, плавно спадает при запасе;
            # при смене знака превышения шаг делится пополам (гасим осцилляцию)
            moved = False
            for k in lam:
                rel = max(-1.0, min(4.0, n.get(k, 0.0) - _ceil(k)))
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

    # страховка: наружу — только сборка в пределах лимитов и без запрещённых минусов
    if best:
        if any(c["over"] for c in contamination(best, cont)):
            return []
        n = _norms(best, cont_base)
        if any(n.get("!" + k, 0.0) > 1.0 + 1e-9 for k in neg):
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
        # доп-свойства порогов: в итоги — матожиданием (×factor); на карточке — полное значение
        f = bonus_factor(v["item"], v["ptn"])
        bonus_out = []
        for bp in BONUS_PROPS.get(v["item"], []):
            bval = round(bonus_value(bp, v["m"], v["ptn"]), 4)
            bonus_out.append({"key": bp["key"], "name": bp["name"], "val": bval,
                              "factor": round(f, 4)})
            if not f or bp["key"] in ACCUM_KEYS:   # заражения — в блоке contamination
                continue
            t = totals_stats.setdefault(bp["key"], {"name": bp["name"], "harmful": False, "total": 0.0})
            t["total"] += bval * f * eff
        cost += v["price"]
        weight += art["weight"] or 0.0
        thin = v["sales"] < (3 if v["src"] == "lots" else config.ART_MIN_SALES * 3)
        if thin:
            low_liq.append(f"{it.get('name', v['item'])} Q{v['qlt']} +{v['ptn']}")
        slots_out.append({"item": v["item"], "name": it.get("name", v["item"]),
                          "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
                          "qlt": v["qlt"], "ptn": v["ptn"], "price": round(v["price"]),
                          "sales": v["sales"], "src": v["src"], "stats": vals,
                          "bonus": bonus_out, "milestones": milestones(v["ptn"])})
    for s in _self_bonus(cont):        # собственные статы хранилища — плоско (без ×eff)
        t = totals_stats.setdefault(s["key"], {"name": s["name"], "harmful": s["harmful"], "total": 0.0})
        t["total"] += s["val"]
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
    out = ["Заточка +2%/уровень; доп-свойства порогов +5/+10/+15 учтены: на +15 "
           "активен весь пул (детерминировано), на +5/+10 — матожиданием "
           "(какие именно выпали — случайный порядок).",
           "Заражения гасятся внутренней защитой контейнера (кроме холода); итог "
           "держится строго НИЖЕ лимита (рад/темп/био/холод — 1.0, пси — 3.0): на "
           "самом значении урон уже идёт, 2.99 по пси безопасно, 3.0 бьёт.",
           _price_note()]
    if builds:
        for name in builds[0].get("low_liquidity", []):
            out.append(f"Корзина {name} малоликвидна — цена ориентировочная.")
    return out


# ---------- автоподбор по статам ----------
def auto_build(budget: float, container_id: str, stats_req: list[dict],
               exclude: list | None = None, no_negatives: bool = False) -> dict:
    cont = db.storage(container_id)
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
    # Исключённые минусы (просьба юзеров): НЕ вычеркиваем носителей из пула, а
    # требуем, чтобы ИТОГ сборки по стату не ушёл во вредную сторону — минус
    # Креветки перекрывается плюсом Ягодки. Только обычные статы: заражения
    # держат жёсткие лимиты и контрарты. no_negatives — так по всем статам.
    if not isinstance(exclude, (list, tuple)):
        exclude = []
    excl = {k for k in exclude[:30] if isinstance(k, str)
            and k in db.artefact_stat_names and k not in ACCUM_KEYS}
    if no_negatives:
        excl = {k for a in db.artefacts.values() for k, st in a["stats"].items()
                if st["harmful"] and k not in ACCUM_KEYS}

    # в пул, кроме носителей запрошенных статов и контрартов, пускаем
    # компенсаторы (арты с зелёной версией исключённого стата) и носителей
    # запрошенного стата в доп-свойствах порогов заточки
    pool = _make_pool(budget, lambda iid, art: any(
        k in art["stats"] and not art["stats"][k]["harmful"] for k in keys)
        or _is_counter(art)
        or any(k in art["stats"] and not art["stats"][k]["harmful"] for k in excl)
        or any(bp["key"] in weights for bp in BONUS_PROPS.get(iid, ())))
    if not pool:
        return {"error": "no_priced_variants",
                "hint": "Биржа артефактов ещё копит цены (нужна неделя замеров) "
                        "или под бюджет/статы нет корзин с достаточными продажами."}
    neg = _neg_constraints(pool, cont, excl)
    # нормировка статов на максимум по пулу — веса сопоставимы
    ref = {}
    for k in keys:
        m = 0.0
        for v in pool:
            st = db.artefacts[v["item"]]["stats"].get(k)
            if st and not st["harmful"]:
                m = max(m, abs(stat_value(st, v["m"], v["ptn"])))
            f = bonus_factor(v["item"], v["ptn"])
            if f:
                for bp in BONUS_PROPS.get(v["item"], []):
                    if bp["key"] == k:
                        m = max(m, abs(bonus_value(bp, v["m"], v["ptn"])) * f)
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
        f = bonus_factor(v["item"], v["ptn"])
        if f:   # доп-свойства порогов — всегда полезные, в плюс (матожиданием)
            for bp in BONUS_PROPS.get(v["item"], []):
                w = weights.get(bp["key"])
                if w:
                    s += w * abs(bonus_value(bp, v["m"], v["ptn"])) * f / ref[bp["key"]]
        return s

    builds, banned, seen = [], set(), set()
    for _ in range(1 + ALTERNATIVES):
        picked = _optimize(pool, cont, budget, score, banned, neg=neg)
        key = frozenset((v["item"], v["qlt"], v["ptn"]) for v in picked)
        if not picked or key in seen:
            break
        seen.add(key)
        builds.append(_present_build(picked, cont))
        # баним только носителей запрошенных статов; чистые контрарты (score≈0)
        # оставляем — они нужны и альтернативным сборкам
        banned.update(v["item"] for v in picked if score(v) > 1e-9)

    if not builds:
        hint = ("Под этот бюджет не собрать сборку в пределах лимитов "
                "заражения — поднимите бюджет, смените контейнер или статы.")
        if neg:
            hint += (" Требование «без минуса в итоге» могло не выполниться "
                     "под этот бюджет — ослабьте исключения.")
        return {"error": "no_clean_build", "hint": hint}
    return {"container": cont, "stat_keys": keys, "builds": builds,
            "pool_size": len(pool), "warnings": _warnings(builds)}


# ---------- приведённое ХП от пулестойкости ----------
def _eff_hp(bullet: float, vit_pct: float) -> float:
    """(100 базового ХП + пулестойкость) × живучесть. Формула из игры."""
    return (100.0 + bullet) * (1.0 + vit_pct / 100.0)


def auto_hp(budget: float, container_id: str, armor_id: str, armor_ptn: int) -> dict:
    cont = db.storage(container_id)
    if not cont:
        return {"error": "container_not_found"}
    armor = db.armor.get(armor_id)
    if not armor:
        return {"error": "armor_not_found"}
    if budget <= 0:
        return {"error": "bad_request"}
    ast = db.armor_stats(armor_id, armor_ptn)
    # собственные пулестойкость/живучесть хранилища (напр. контейнер l362 даёт +23
    # пулестой) — константы, в оптимизации на выбор артов не влияют, но входят в ХП
    self_b = sum(s["val"] for s in cont.get("self_stats", []) if s["key"] == BULLET_KEY)
    self_h = sum(s["val"] for s in cont.get("self_stats", []) if s["key"] == HEALTH_KEY)
    base_bullet, base_vit = ast["bullet"] + self_b, ast["vitality"] + self_h
    eff = (cont.get("efficiency") or 100.0) / 100.0   # усиливает положительные статы

    def bv(v):
        """Эффективный вклад арта в (пулестой, живучесть): полезный × эффективность,
        вредный (красный минус) — как есть. Минус НЕ игнорируем — иначе оптимизатор
        берёт арты, роняющие живучесть. Доп-свойства порогов — матожиданием."""
        st = db.artefacts[v["item"]]["stats"]
        f = bonus_factor(v["item"], v["ptn"])
        out = []
        for key in (BULLET_KEY, HEALTH_KEY):
            s = st.get(key)
            val = 0.0
            if s:
                x = stat_value(s, v["m"], v["ptn"])
                val = x if s["harmful"] else x * eff
            if f:
                for bp in BONUS_PROPS.get(v["item"], []):
                    if bp["key"] == key:
                        val += bonus_value(bp, v["m"], v["ptn"]) * eff * f
            out.append(val)
        return out

    pool = _make_pool(budget, lambda iid, art: (
        (BULLET_KEY in art["stats"] and not art["stats"][BULLET_KEY]["harmful"])
        or (HEALTH_KEY in art["stats"] and not art["stats"][HEALTH_KEY]["harmful"])
        or _is_counter(art)
        or any(bp["key"] in (BULLET_KEY, HEALTH_KEY)
               for bp in BONUS_PROPS.get(iid, ()))))
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
    total_bullet = base_bullet + art_bullet   # base уже = броня + хранилище
    total_vit = base_vit + art_vit
    res["hp"] = {
        "armor": {"id": armor_id, "name": armor["name"], "icon": armor["icon"],
                  "color": armor["color"], "ptn": int(armor_ptn),
                  "bullet": round(ast["bullet"], 2), "vitality": round(ast["vitality"], 2)},
        "container_bullet": round(self_b, 2),
        "container_vitality": round(self_h, 2),
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


# ---------- готовые сборки для верха /builds ----------
# Страница открывалась пустой сеткой слотов: человек с запросом «калькулятор
# сборок» видел форму, которую надо заполнять, и уходил (отказы с поиска 43%
# против 15% по сайту, глубина 1.1). Показываем сверху три посчитанные сборки
# под типовые задачи — тот же приём, что вытащил /market готовыми списками.
READY_BUDGET = 5_000_000     # бюджет всех трёх: сравниваются задачи, а не деньги
READY_TTL = 900.0            # с; один профиль считается ~0.5 с, страница низкотрафичная
READY_PRESETS = (
    {"id": "pvp", "title": "ПОД БОЙ",
     "note": "Держать выстрел и не падать с одной очереди",
     "stats": ((BULLET_KEY, 100), (HEALTH_KEY, 70))},
    {"id": "run", "title": "ПОД ХОДКИ",
     "note": "Бегать дальше и дольше — вылазки за лутом",
     "stats": ((SPEED_KEY, 100), (STAMINA_KEY, 70))},
    {"id": "farm", "title": "ПОД ФАРМ",
     "note": "Унести за раз больше добычи",
     "stats": ((WEIGHT_KEY, 100), (HEALTH_KEY, 50))},
)

_ready_cache: dict = {"ts": 0.0, "payload": None}


def _ready_container() -> dict | None:
    """Хранилище для готовых сборок — правилом, а не зашитым id: база предметов
    едет с патчами. Топ-редкость, максимум слотов, при равенстве — эффективность
    (id последним, чтобы выбор был детерминирован при полном равенстве)."""
    conts = [c for c in db.containers.values() if c["color"] in TOP_COLORS]
    if not conts:
        conts = list(db.containers.values())
    if not conts:
        return None
    return max(conts, key=lambda c: (c.get("slots") or 0,
                                     c.get("efficiency") or 0.0, c["id"]))


def ready_builds() -> dict:
    """Три готовые сборки под типовые задачи на живых ценах, кэш READY_TTL.
    Профиль, под который сборка считалась, отдаём вместе с ней — фронт кладёт
    его в автоподбор, чтобы посетитель пересчитал под свой бюджет."""
    if _ready_cache["payload"] and time.time() - _ready_cache["ts"] <= READY_TTL:
        return _ready_cache["payload"]
    cont = _ready_container()
    if not cont:
        return {"budget": READY_BUDGET, "presets": [], "error": "no_containers"}
    presets = []
    for p in READY_PRESETS:
        stats_req = [{"key": k, "weight": w} for k, w in p["stats"]]
        res = auto_build(float(READY_BUDGET), cont["id"], stats_req)
        build = (res.get("builds") or [None])[0]
        if not build:      # под профиль нет корзин с ценами — молча пропускаем карточку
            continue
        presets.append({"id": p["id"], "title": p["title"], "note": p["note"],
                        "stats_req": stats_req, "build": build})
    payload = {"budget": READY_BUDGET, "container": cont, "presets": presets,
               "price_note": _price_note()}
    if presets:        # пустое (биржа не прогрелась) не кэшируем — повторим позже
        _ready_cache["payload"] = payload
        _ready_cache["ts"] = time.time()
    return payload
