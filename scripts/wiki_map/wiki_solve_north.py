"""Север: грид-серч вокруг сидов от визуальной прикидки, два варианта v
(merc_deg(lat) и линейная lat). Объектив — попадания маркеров в 6 локаций кэша.
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from wiki_solve import cache_locations  # noqa: E402


def merc(lat):
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


d = json.load(open(os.path.join(base, "wiki_north-zone.json"), encoding="utf-8"))
raw = [(m["coordinates"]["lng"], m["coordinates"]["lat"])
       for g in d["marker_groups"] for t in g["marker_types"]
       for m in t.get("markers") or [] if m.get("coordinates")]
locs = cache_locations((-27, 0, -13, 10))
boxes = list(locs.values())


def hits(pts, su, ou, sv, ov):
    n = 0
    for u, v in pts:
        X = su * u + ou
        Y = sv * v + ov
        for b in boxes:
            if b[0] <= X <= b[2] and b[1] <= Y <= b[3]:
                n += 1
                break
    return n


def refine(pts, seed, name):
    best = (hits(pts, *seed),) + seed
    for it in range(4):
        _, su, ou, sv, ov = best
        fs = 0.10 / (it + 1)
        fo = 700 / (it + 1)
        for dsu in (-fs, -fs / 2, 0, fs / 2, fs):
            for dsv in (-fs, -fs / 2, 0, fs / 2, fs):
                for dou in (-fo, 0, fo):
                    for dov in (-fo, 0, fo):
                        cand = (su * (1 + dsu), ou + dou, sv * (1 + dsv), ov + dov)
                        h = hits(pts, *cand)
                        if h > best[0]:
                            best = (h,) + cand
    h, su, ou, sv, ov = best
    print(f"{name}: hits {h}/{len(pts)} ({100*h/len(pts):.0f}%)  "
          f"su={su:.2f} ou={ou:.0f} sv={sv:.2f} ov={ov:.0f}")
    return best


pts_m = [(u, merc(la)) for u, la in raw]
pts_l = list(raw)
bm = refine(pts_m, (27.1, 36832.0, -28.4, 23448.0), "меркатор")
bl = refine(pts_l, (27.1, 36832.0, -51.6, 23900.0), "линейная")

win, pts, tag = (bm, pts_m, "merc") if bm[0] >= bl[0] else (bl, pts_l, "lat")
out = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
out["north-zone"] = {"su": win[1], "ou": win[2], "sv": win[3], "ov": win[4],
                     "hits": win[0], "total": len(pts), "v": tag}
with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("выбран вариант:", tag)
