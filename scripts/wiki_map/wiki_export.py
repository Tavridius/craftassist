"""Экспорт нужных типов маркеров stalzone.wiki в JSON для map_import.py.

Типы: тайники (stash-valuable + сейфы) -> stash; аномалии Застой и
Скопление «Проторазрядов» -> anomaly. Всё черновиками, слой detail.

Трансформации:
  south-zone / north-zone — решённые (wiki_transforms.json);
  graveyard  — фикс. масштаб (средний юг/север), центр на бокс mg из кэша;
  lyubech    — фикс. масштаб, центр на бокс территории Любеч-3;
  wild-north — free-scale перцентильный bbox -> бокс территории Дикий Север.
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from wiki_solve import wiki_points, cache_locations  # noqa: E402
from wiki_solve2 import pct  # noqa: E402

X0, Y0 = -86, -38

WANT = {  # slug типа -> (категория, имя по умолчанию)
    "stash-valuable": ("stash", "Тайник"),
    "factory-safe": ("stash", "Заводской сейф"),
    "medical-safe": ("stash", "Медицинский сейф"),
    "military-safe": ("stash", "Военный сейф"),
    "scientific-safe": ("stash", "Научный сейф"),
    "zivcas-safe": ("stash", "Сейф «Зивкаса»"),
    "murmur-safe": ("stash", "Сейф «Шёпота»"),
    "stasis": ("anomaly", "Аномалия «Застой»"),
    "proto-discharge-cluster": ("anomaly", "Скопление «Проторазрядов»"),
}

TERR_BOX = {  # px детальной пирамиды из api.py MAP_TERRITORIES
    "limansk": ((-4 - X0) * 512, (-2 - Y0) * 512, (0 - X0 + 1) * 512, (2 - Y0 + 1) * 512),
    "wnorth": ((12 - X0) * 512, (-3 - Y0) * 512, (18 - X0 + 1) * 512, (3 - Y0 + 1) * 512),
}

tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
S_AVG = (tr["south-zone"]["su"] + tr["north-zone"]["su"]) / 2
V_AVG = (tr["south-zone"]["sv"] + tr["north-zone"]["sv"]) / 2


def centroid_fit(slug, box, su=S_AVG, sv=V_AVG):
    pts = wiki_points(slug)
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    cu = (pct(us, 0.02) + pct(us, 0.98)) / 2
    cv = (pct(vs, 0.02) + pct(vs, 0.98)) / 2
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return {"su": su, "ou": cx - su * cu, "sv": sv, "ov": cy - sv * cv}


def bbox_fit(slug, box):
    pts = wiki_points(slug)
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    u0, u1 = pct(us, 0.02), pct(us, 0.98)
    v0, v1 = pct(vs, 0.02), pct(vs, 0.98)
    su = (box[2] - box[0]) / (u1 - u0)
    sv = -(box[3] - box[1]) / (v1 - v0)
    return {"su": su, "ou": box[0] - su * u0, "sv": sv, "ov": box[1] - sv * v1}


mg_box = cache_locations()["mg"]
tr.setdefault("graveyard", centroid_fit("graveyard", mg_box))
tr.setdefault("lyubech", centroid_fit("lyubech", TERR_BOX["limansk"]))
tr.setdefault("wild-north", bbox_fit("wild-north", TERR_BOX["wnorth"]))
with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
    json.dump(tr, f, indent=1)

rows = []
per = {}
for slug in ("south-zone", "north-zone", "wild-north", "lyubech", "graveyard"):
    t = tr[slug]
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    for g in d["marker_groups"]:
        for mt in g["marker_types"]:
            w = WANT.get(mt["slug"])
            if not w:
                continue
            cat, nm = w
            for m in mt.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" not in c:
                    continue
                v = math.degrees(math.log(math.tan(
                    math.pi / 4 + math.radians(c["lat"]) / 2)))
                X = round(t["su"] * c["lng"] + t["ou"], 1)
                Y = round(t["sv"] * v + t["ov"], 1)
                desc = ((m.get("description") or {}).get("ru") or "").strip()
                rows.append({"layer": "detail", "kind": "marker", "category": cat,
                             "name": nm, "x": X, "y": Y,
                             "description": (desc + "\n" if desc else "")
                             + f"[wiki-import {slug}]"})
                per[(slug, nm)] = per.get((slug, nm), 0) + 1

out = os.path.join(base, "wiki_points_import.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)
print(f"итого точек: {len(rows)} -> {out}")
for (slug, nm), n in sorted(per.items()):
    print(f"  {slug:12} {nm:30} x{n}")
