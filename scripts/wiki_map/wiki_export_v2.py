#!/usr/bin/env python3
"""Экспорт меток и областей stalzone.wiki по привязке регистрацией (wiki_register.py).

Заменяет wiki_export.py + wiki_export_all.py: те ставили точки по фиту облака
маркеров (wiki_solve*) со смещением. Здесь — ключ <slug>.affine из
wiki_transforms.json: px вики на maxZoom (веб-меркатор) → нативные px dmap.
Карты без надёжной привязки пропускаем:
  wild-north — на нашем dmap район под облаками КПК, сопоставлять не с чем;
  graveyard  — «Могильник» на вики нарисован от руки, не план в блоках.

Выход: wiki_points_import_v2.json для map_import.py (детальный слой,
черновики; в описании — тег [wiki-import <slug>], по нему map_import
--replace-wiki снимает прошлый импорт).
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))

MAPS = ("south-zone", "north-zone", "lyubech", "labyrinth")

CAT = {
    "stash-valuable": "stash", "factory-safe": "stash", "medical-safe": "stash",
    "military-safe": "stash", "scientific-safe": "stash", "zivcas-safe": "stash",
    "murmur-safe": "stash",
    "stasis": "anomaly", "proto-discharge-cluster": "anomaly",
    "bunker": "shelter", "space-bubble": "bubble",
    "location_exit": "transition", "black-raid-player-spawn": "spawn",
}
for s in ("mutt-den", "boar-rookery", "pigs-rookery", "piggy-den", "rat-hole",
          "skitters-den", "ghouls-nest", "giant-rat-den", "psy-ghoul-den",
          "phantom-fiend-den", "boss-den", "boss_chimera", "boss_pseudogigant",
          "boss_krovosos", "zombie-group", "zombie-group-2", "zombie-horde",
          "dead_horde", "infected_dog", "boar-den", "murmur-squad",
          "abstract_rescue_zombie"):
    CAT[s] = "mob"
for s in ("call-of-help", "help-scientists", "allies-rescue", "anomalous-rift",
          "art_device", "anomaly-research-installation", "clash", "gold-cargo",
          "waypoint_event_gold_installation_protection", "dropped-cargo-common",
          "dropped-cargo-sugar", "chronorift", "shopot_lost_device",
          "lost_device_target", "science_rescue", "art_hunters", "science_camp",
          "sapper_fraction", "sniper_fraction", "force_group", "officer_fraction",
          "art_hunters_ssop"):
    CAT[s] = "event"
for s in ("bandits-camp", "stalkers-camp", "bandit-encampment", "stalker-encampment",
          "military-camp", "military-checkpoint", "military-base", "sanitars-camp",
          "covenant-encampment", "frontier-encampment", "mercenary-encampment",
          "rise-encampment", "zivcas-encampment", "fraction-outpost",
          "fraction-stronghold", "fraction-camp", "zivcas-outpost", "covenant-outpost",
          "mercenary-outpost", "rise-outpost", "frontier-outpost", "frontier-outpost-2",
          "rise-outpost-2", "mercenary-outpost-2", "covenant-outpost-2",
          "rise-headquarters", "frontier-headquarters", "covenant-headquarters",
          "mercenary-headquarters", "zivcas-outpost-2", "stronghold", "lost_house",
          "supply_base", "murmur-base", "murmur-outpost", "murmur-antenna",
          "shopot_camp", "shopot_control_center", "military-occupied-building",
          "murmur-occupied-building"):
    CAT[s] = "camp"


def to_px(c, n):
    if isinstance(c, (list, tuple)):            # области: [lat, lng]
        c = {"lat": c[0], "lng": c[1]}
    lat = math.radians(c["lat"])
    return ((c["lng"] + 180) / 360 * n,
            (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n)


def main():
    tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
    rows, per, unknown = [], {}, {}
    for slug in MAPS:
        A = tr[slug]["affine"]
        d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
        n = 2 ** d["settings"]["maxZoom"] * 256

        def xy(c):
            u, v = to_px(c, n)
            return (round(A[0][0] * u + A[0][1] * v + A[0][2], 1),
                    round(A[1][0] * u + A[1][1] * v + A[1][2], 1))

        tag = f"[wiki-import {slug}]"
        for g in d.get("marker_groups", []):
            for mt in g["marker_types"]:
                cat = CAT.get(mt["slug"])
                if cat is None:
                    unknown[mt["slug"]] = unknown.get(mt["slug"], 0) + len(mt.get("markers") or [])
                    cat = "poi"
                nm = (mt.get("name") or {}).get("ru") or mt["slug"]
                for m in mt.get("markers") or []:
                    c = m.get("coordinates") or {}
                    if "lat" not in c:
                        continue
                    x, y = xy(c)
                    desc = ((m.get("description") or {}).get("ru") or "").strip()
                    rows.append({"layer": "detail", "kind": "marker", "category": cat,
                                 "name": nm, "x": x, "y": y,
                                 "description": (desc + "\n" if desc else "") + tag})
                    per[(slug, cat)] = per.get((slug, cat), 0) + 1
        for g in d.get("area_groups", []):
            for at in g.get("area_types", []):
                nm = (at.get("name") or {}).get("ru") or at["slug"]
                color = (at.get("settings") or {}).get("fill") or "#7ce68e"
                for a in at.get("areas") or []:
                    pts = [xy(c) for c in a.get("coordinates") or []
                           if isinstance(c, list) or "lat" in c]
                    if len(pts) < 3:
                        continue
                    desc = ((a.get("description") or {}).get("ru") or "").strip()
                    rows.append({"layer": "detail", "kind": "area", "name": nm,
                                 "color": color, "geometry": [list(p) for p in pts],
                                 "description": (desc + "\n" if desc else "") + tag})
                    per[(slug, "area")] = per.get((slug, "area"), 0) + 1
    out = os.path.join(base, "wiki_points_import_v2.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"итого {len(rows)} -> {out}")
    if unknown:
        print("⚠ типы без категории (ушли в poi):", unknown)
    for (slug, cat), k in sorted(per.items()):
        print(f"  {slug:12} {cat:10} x{k}")


if __name__ == "__main__":
    main()
