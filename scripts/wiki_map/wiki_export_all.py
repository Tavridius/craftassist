#!/usr/bin/env python3
"""Экспорт ОСТАЛЬНЫХ слоёв stalzone.wiki (всё, кроме уже залитых тайников и
аномалий из wiki_export.py): события, логова мутантов, лагеря и заставы,
укрытия, пузыри, переходы — метками; прикопы и зоны заражений — полигонами.

Категории меток — расширенный MAP_CATEGORIES (api.py): mob/event/camp/
shelter/bubble + существующие transition/spawn. Имена и цвета полигонов —
из данных вики (name.ru, settings.fill).

Использует привязки wiki_transforms.json (решены в wiki_solve*/wiki_refit,
НЕ пересчитывает их). Данные wiki_<slug>.json должны лежать рядом.
Выход: wiki_points_import_all.json для map_import.py. Лабиринт пропускаем —
его нет на нашей детальной карте.
"""
import json
import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))

DONE = {  # уже залито первым импортом (wiki_export.py) — не дублируем
    "stash-valuable", "factory-safe", "medical-safe", "military-safe",
    "scientific-safe", "zivcas-safe", "murmur-safe", "stasis",
    "proto-discharge-cluster",
}

CAT = {}
for slug in ("mutt-den", "boar-rookery", "pigs-rookery", "piggy-den", "rat-hole",
             "skitters-den", "ghouls-nest", "giant-rat-den", "psy-ghoul-den",
             "phantom-fiend-den", "boss-den", "boss_chimera", "boss_pseudogigant",
             "boss_krovosos", "zombie-group", "zombie-group-2", "zombie-horde",
             "dead_horde", "infected_dog", "boar-den", "murmur-squad"):
    CAT[slug] = "mob"
for slug in ("call-of-help", "help-scientists", "allies-rescue", "anomalous-rift",
             "art_device", "anomaly-research-installation", "clash", "gold-cargo",
             "waypoint_event_gold_installation_protection", "dropped-cargo-common",
             "dropped-cargo-sugar", "chronorift", "shopot_lost_device",
             "lost_device_target", "science_rescue", "art_hunters", "science_camp",
             "sapper_fraction", "sniper_fraction", "force_group",
             "officer_fraction"):
    CAT[slug] = "event"
for slug in ("bandits-camp", "stalkers-camp", "bandit-encampment",
             "stalker-encampment", "military-camp", "military-checkpoint",
             "military-base", "sanitars-camp", "covenant-encampment",
             "frontier-encampment", "mercenary-encampment", "rise-encampment",
             "zivcas-encampment", "fraction-outpost", "fraction-stronghold",
             "fraction-camp", "covenant-outpost", "mercenary-outpost",
             "rise-outpost", "frontier-outpost", "frontier-outpost-2",
             "rise-outpost-2", "mercenary-outpost-2", "covenant-outpost-2",
             "rise-headquarters", "frontier-headquarters", "covenant-headquarters",
             "mercenary-headquarters", "zivcas-outpost-2", "stronghold",
             "lost_house", "supply_base", "murmur-base", "murmur-outpost",
             "murmur-antenna", "shopot_camp", "shopot_control_center",
             "military-occupied-building", "murmur-occupied-building"):
    CAT[slug] = "camp"
CAT["bunker"] = "shelter"
CAT["space-bubble"] = "bubble"
CAT["location_exit"] = "transition"
CAT["black-raid-player-spawn"] = "spawn"

MAPS = ("south-zone", "north-zone", "wild-north", "lyubech", "graveyard")


def merc(lat):
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
rows = []
unknown = {}
per = {}

for slug in MAPS:
    t = tr[slug]

    def to_xy(c):
        return (round(t["su"] * c["lng"] + t["ou"], 1),
                round(t["sv"] * merc(c["lat"]) + t["ov"], 1))

    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    for g in d.get("marker_groups", []):
        for mt in g["marker_types"]:
            ts = mt["slug"]
            if ts in DONE:
                continue
            cat = CAT.get(ts)
            if cat is None:
                unknown[ts] = unknown.get(ts, 0) + len(mt.get("markers") or [])
                cat = "poi"
            nm = (mt.get("name") or {}).get("ru") or ts
            for m in mt.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" not in c:
                    continue
                x, y = to_xy(c)
                desc = ((m.get("description") or {}).get("ru") or "").strip()
                rows.append({"layer": "detail", "kind": "marker", "category": cat,
                             "name": nm, "x": x, "y": y,
                             "description": (desc + "\n" if desc else "")
                             + f"[wiki-import {slug}]"})
                per[(slug, nm)] = per.get((slug, nm), 0) + 1
    for g in d.get("area_groups", []):
        for at in g.get("area_types", []):
            nm = (at.get("name") or {}).get("ru") or at["slug"]
            color = ((at.get("settings") or {}).get("fill") or "#7ce68e")
            for a in at.get("areas") or []:
                pts = [to_xy(c) for c in a.get("coordinates") or [] if "lat" in c]
                if len(pts) < 3:
                    continue
                desc = ((a.get("description") or {}).get("ru") or "").strip()
                rows.append({"layer": "detail", "kind": "area", "name": nm,
                             "color": color, "geometry": [[x, y] for x, y in pts],
                             "description": (desc + "\n" if desc else "")
                             + f"[wiki-import {slug}]"})
                per[(slug, nm + " (обл.)")] = per.get((slug, nm + " (обл.)"), 0) + 1

out = os.path.join(base, "wiki_points_import_all.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)
print(f"итого объектов: {len(rows)} -> {out}")
if unknown:
    print("⚠ типы без категории (ушли в poi):", unknown)
n_m = sum(1 for r in rows if r["kind"] == "marker")
n_a = sum(1 for r in rows if r["kind"] == "area")
print(f"меток {n_m}, полигонов {n_a}")
for (slug, nm), n in sorted(per.items()):
    print(f"  {slug:12} {nm:36} x{n}")
