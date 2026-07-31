"""Сравнение снаряжения: одна таблица характеристик на несколько предметов.

Строки таблицы — объединение характеристик выбранных предметов (порядок как в
игровом тултипе первого, «чужие» статы вставляются рядом со своим соседом).
Для каждой строки известно НАПРАВЛЕНИЕ пользы (_DIR): больше — лучше (урон,
защиты) или меньше — лучше (разброс, отдача, время перезарядки, вес). Только
поэтому таблица может подсвечивать лучшее и худшее значение — без направления
подсветка врала бы ровно на тех статах, где разница и важна.

Цены берём из тёплого кэша PriceStore (мин. выкуп + медиана недавних продаж);
внешний API здесь не дёргаем — сравнение открывается пачкой предметов сразу.
"""
from app.db.index import db
from app.services.price_store import store

MAX_ITEMS = 4          # больше колонок не влезает даже на десктопе
MAX_PTN = 15

# Меньше — лучше: время, разброс, отдача, вес, набегающее кровотечение.
_LOWER_BETTER = {
    "core.tooltip.info.weight",
    "weapon.tooltip.weapon.info.spread",
    "weapon.tooltip.weapon.info.hip_spread",
    "weapon.tooltip.weapon.info.recoil",
    "weapon.tooltip.weapon.info.horizontal_recoil",
    "weapon.tooltip.magazine.info.reload_time",
    "weapon.tooltip.magazine.info.reload_time_tactical",
    "weapon.tooltip.weapon.info.draw_time",
    "weapon.tooltip.weapon.info.aim_switch",
    "weapon.stat_factor.spread",
    "weapon.stat_factor.hip_spread",
    "weapon.stat_factor.recoil",
    "weapon.stat_factor.horizontal_recoil",
    "weapon.stat_factor.recoil_gain",
    "weapon.stat_factor.wiggle",
    "stalker.artefact_properties.factor.bleeding_accumulation",
}
# Больше — лучше: урон, дальность, магазин, эргономика, все защиты и бонусы.
# speed_modifier здесь же: это штраф к скорости (−1 лучше, чем −2).
_HIGHER_BETTER = {
    "core.tooltip.info.durability",
    "core.tooltip.info.max_durability",
    "core.tooltip.stat_name.damage_type.direct",
    "core.tooltip.stat_name.damage_type.default",
    "core.tooltip.stat_name.damage_type.burn",
    "core.tooltip.stat_name.damage_type.freeze",
    "core.tooltip.stat_name.damage_type.tear",
    "core.tooltip.stat_name.damage_type.chemical_burn",
    "core.tooltip.stat_name.damage_type.electroshock",
    "weapon.tooltip.weapon.info.clip_size",
    "weapon.tooltip.weapon.info.rate_of_fire",
    "weapon.tooltip.weapon.info.distance",
    "weapon.tooltip.weapon.info.bleeding",
    "weapon.tooltip.weapon.info.stopping_power",
    "weapon.tooltip.weapon.info.plate_penetrating",
    "weapon.stat_factor.reload_modifier",
    "weapon.stat_factor.damage",
    "weapon.stat_factor.damage_distant",
    "weapon.tooltip.melee_weapon.info.damage.min.common",
    "weapon.tooltip.melee_weapon.info.damage.max.common",
    "weapon.tooltip.melee_weapon.info.damage.min.strong",
    "weapon.tooltip.melee_weapon.info.damage.max.strong",
    "weapon.tooltip.melee_weapon.info.reach.common",
    "weapon.tooltip.melee_weapon.info.reach.strong",
    "weapon.tooltip.melee_weapon.stat_name.piercing",
    "weapon.tooltip.melee_weapon.stat_name.bloodlust_chance",
    "anomaly.tooltip.signal_detector.info.charge",
    "anomaly.tooltip.signal_detector.info.range",
    "stalker.gauge_meter_stat.metal_detector.info.charge",
    "stalker.gauge_meter_stat.metal_detector.info.passive_scan_radius",
    "stalker.gauge_meter_stat.metal_detector.info.active_scan_radius",
    "stalker.gauge_meter_stat.metal_detector.info.active_scan_angle",
    "stalker.tooltip.backpack.info.size",
    "stalker.tooltip.backpack.stat_name.effectiveness",
    "stalker.tooltip.backpack.stat_name.inner_protection",
    "stalker.artefact_properties.factor.speed_modifier",
    "stalker.artefact_properties.factor.max_weight_bonus",
    "stalker.artefact_properties.factor.bullet_dmg_factor",
    "stalker.artefact_properties.factor.tear_dmg_factor",
    "stalker.artefact_properties.factor.explosion_dmg_factor",
    "stalker.artefact_properties.factor.electra_dmg_factor",
    "stalker.artefact_properties.factor.burn_dmg_factor",
    "stalker.artefact_properties.factor.chemical_burn_dmg_factor",
    "stalker.artefact_properties.factor.radiation_protection",
    "stalker.artefact_properties.factor.thermal_protection",
    "stalker.artefact_properties.factor.frost_protection",
    "stalker.artefact_properties.factor.biological_protection",
    "stalker.artefact_properties.factor.psycho_protection",
    "stalker.artefact_properties.factor.bleeding_protection",
    "stalker.artefact_properties.factor.stopping_protection",
    "stalker.artefact_properties.factor.stamina_bonus",
    "stalker.artefact_properties.factor.stamina_regeneration_bonus",
    "stalker.artefact_properties.factor.regeneration_bonus",
    "stalker.artefact_properties.factor.artefakt_heal",
}

_DAMAGE_KEY = "core.tooltip.stat_name.damage_type.direct"
_ROF_KEY = "weapon.tooltip.weapon.info.rate_of_fire"
_DPS_KEY = "calc.dps"

# Категории, которые есть смысл сравнивать (у остального нет тултип-статов)
COMPARABLE_CATS = ("weapon", "armor", "attachment", "weapon_modules",
                   "containers", "backpacks", "artefact")


def _direction(key: str) -> int:
    """+1 — больше лучше, −1 — меньше лучше, 0 — направления нет (не подсвечиваем)."""
    if key in _LOWER_BETTER:
        return -1
    if key in _HIGHER_BETTER or key == _DPS_KEY:
        return 1
    if key in db.artefact_stat_names:   # статы артефактов: вредный → меньше лучше
        return -1 if db.artefact_stat_names[key]["harmful"] else 1
    return 0


def _dps_row(rows: list[dict]) -> dict | None:
    """Расчётный урон в секунду: игра его не показывает, а сравнивать стволы
    по одному урону без скорострельности бессмысленно."""
    by = {r["key"]: r for r in rows}
    dmg, rof = by.get(_DAMAGE_KEY), by.get(_ROF_KEY)
    if not dmg or not rof or dmg["num"] is None or not rof["num"]:
        return None
    dps = round(dmg["num"] * rof["num"] / 60.0, 1)
    return {"key": _DPS_KEY, "name": "Урон в секунду", "unit": "ед/с",
            "value": f"{dps:g}".replace(".", ","), "num": dps,
            "harmful": False, "group": "stat", "rank": False, "calc": True}


def _item_head(iid: str, ptn: int) -> dict:
    """Шапка колонки: предмет + цена аукциона из тёплого кэша."""
    it = db.item(iid) or {}
    p = store.get(iid)
    h = store.history.get(iid) or {}
    return {
        "id": iid, "name": it.get("name", iid), "name_en": it.get("name_en", ""),
        "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
        "status": it.get("status", ""),
        "category": db.category(iid),
        "craftable": bool(db.recipe_by_result.get(iid)),
        "max_ptn": db.max_ptn(iid),
        "ptn_exact": ptn == 0 or db.max_ptn(iid) >= ptn,   # False — показаны базовые статы
        "price": {
            "known": p["known"], "available": p["available"],
            "min_buyout": p["min_buyout"],
            "recent": h.get("recent_unit_price"),
            "sales_per_hour": h.get("sales_per_hour"),
        },
    }


def _merge_order(per_item: list[list[dict]]) -> list[str]:
    """Порядок строк: как в тултипе первого предмета, статы остальных вставляются
    сразу за своим предыдущим соседом (а не сваливаются в хвост)."""
    order: list[str] = []
    for rows in per_item:
        pos = len(order)
        for r in rows:
            key = r["key"]
            if key in order:
                pos = order.index(key) + 1
            else:
                order.insert(pos, key)
                pos += 1
    return order


def build(ids: list[str], ptn: int = 0) -> dict:
    """Таблица сравнения: колонки — предметы, строки — характеристики."""
    ptn = max(0, min(MAX_PTN, int(ptn or 0)))
    seen: list[str] = []
    missing: list[str] = []
    for iid in ids:
        if iid in seen:
            continue
        if db.item(iid) and db.characteristics(iid):
            seen.append(iid)
        else:
            missing.append(iid)
        if len(seen) >= MAX_ITEMS:
            break

    store.request(seen)      # цены незнакомых предметов воркер посчитает вне очереди
    per_item = []
    for iid in seen:
        rows = list(db.characteristics(iid, ptn))
        dps = _dps_row(rows)
        if dps:
            rows.append(dps)
        per_item.append(rows)

    meta: dict[str, dict] = {}
    for rows in per_item:
        for r in rows:
            meta.setdefault(r["key"], r)

    out_rows = []
    for key in _merge_order(per_item):
        m = meta[key]
        cells = []
        for rows in per_item:
            r = next((x for x in rows if x["key"] == key), None)
            cells.append(None if r is None else
                         {"value": r["value"], "num": r["num"], "harmful": r["harmful"],
                          "rank": r["rank"]})
        direction = _direction(key)
        nums = [c["num"] for c in cells if c and c["num"] is not None]
        if direction and len(nums) > 1 and max(nums) != min(nums):
            best = max(nums) if direction > 0 else min(nums)
            worst = min(nums) if direction > 0 else max(nums)
            for c in cells:
                if c and c["num"] is not None:
                    c["best"] = c["num"] == best
                    c["worst"] = c["num"] == worst
        out_rows.append({"key": key, "name": m["name"], "unit": m["unit"],
                         "group": m["group"], "dir": direction,
                         "calc": bool(m.get("calc")), "cells": cells})

    return {"ptn": ptn, "max_items": MAX_ITEMS,
            "items": [_item_head(i, ptn) for i in seen],
            "rows": out_rows, "missing": missing,
            "mixed": len({db.category(i) for i in seen}) > 1}
