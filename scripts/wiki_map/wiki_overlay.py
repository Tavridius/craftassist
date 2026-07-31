"""Оверлей: маркеры вики по найденной трансформации поверх нашей dmap-мозаики."""
import json
import math
import os
import sys

from PIL import ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from render_pair import terr_mosaic, merc, TERR  # noqa: E402
from wiki_solve import wiki_points, cache_locations  # noqa: E402

COLORS = {"stash-valuable": "#ffd040", "stasis": "#ff5050",
          "proto-discharge-cluster": "#c080ff", "bunker": "#40c8ff"}

tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))

for slug, tid in (("south-zone", "south"), ("north-zone", "sever")):
    if slug not in tr:
        continue
    t = tr[slug]
    mos, (px0, py0, px1, py1) = terr_mosaic(tid, z=3)
    dr = ImageDraw.Draw(mos)
    # рамки кэш-локаций — зелёным
    for nm, b in cache_locations(TERR[tid]).items():
        dr.rectangle([(b[0] - px0) / 8, (b[1] - py0) / 8,
                      (b[2] - px0) / 8, (b[3] - py0) / 8], outline="#00b000")
        dr.text(((b[0] - px0) / 8 + 3, (b[1] - py0) / 8 + 2), nm, fill="#00e000")
    n_in = n_out = 0
    for u, v, ts in wiki_points(slug):
        X = t["su"] * u + t["ou"]
        Y = t["sv"] * v + t["ov"]
        x, y = (X - px0) / 8, (Y - py0) / 8
        if 0 <= x < mos.width and 0 <= y < mos.height:
            n_in += 1
        else:
            n_out += 1
            continue
        col = COLORS.get(ts, "#ff9500")
        dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)
    mos.save(os.path.join(base, f"overlay_{slug}.png"))
    print(f"{slug}: в кадре {n_in}, за кадром {n_out} -> overlay_{slug}.png")
