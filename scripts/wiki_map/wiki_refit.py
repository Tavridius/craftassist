"""Рефит трёх слабых карт на фактические рамки суши (сняты с мозаик) +
контрольные оверлеи, включая Могильник (кроп dmap вокруг бокса mg).
"""
import glob
import json
import os
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from wiki_solve import cache_locations  # noqa: E402
from wiki_export import bbox_fit, WANT  # noqa: E402
import wiki_export  # noqa: E402  (переиспользуем экспортную логику ниже)

DMAP = r"d:\stalzone craft\frontend\dmap"

# рамки фактической суши, сняты с оверлеев z3 (world px детальной пирамиды)
LAND = {
    "wild-north": (50456, 17960, 52856, 20840),
    "lyubech": (42600, 18700, 43650, 19900),
}

tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
tr["wild-north"] = bbox_fit("wild-north", LAND["wild-north"])
tr["lyubech"] = bbox_fit("lyubech", LAND["lyubech"])
with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
    json.dump(tr, f, indent=1)
print("рефит записан:", {k: {kk: round(vv, 2) for kk, vv in tr[k].items()}
                        for k in ("wild-north", "lyubech")})


def crop_mosaic(px_box, z=3):
    div = 2 ** (6 - z)
    x0, y0, x1, y1 = [c // div for c in px_box]
    im = Image.new("RGB", (x1 - x0, y1 - y0), (8, 10, 8))
    for f in glob.glob(os.path.join(DMAP, str(z), "*", "*.webp")):
        tx = int(os.path.basename(os.path.dirname(f)))
        ty = int(os.path.splitext(os.path.basename(f))[0])
        ox, oy = tx * 256 - x0, ty * 256 - y0
        if -256 < ox < im.width and -256 < oy < im.height:
            im.paste(Image.open(f).convert("RGB"), (ox, oy))
    return im


# пересобрать экспорт с новыми трансформациями (модульная логика в wiki_export
# исполняется при импорте — поэтому просто перечитываем результат)
rows = json.load(open(os.path.join(base, "wiki_points_import.json"), encoding="utf-8"))
CC = {"stash": "#ffd040", "anomaly": "#ff5050"}
VIEW = {
    "wild-north": (50176, 17600, 53200, 21200),
    "lyubech": (42200, 18300, 44000, 20200),
    "graveyard": (37500, 19100, 39800, 21400),
}
for slug, box in VIEW.items():
    mos = crop_mosaic(box)
    dr = ImageDraw.Draw(mos)
    t = tr[slug]
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    import math
    n_in = n_tot = 0
    for g in d["marker_groups"]:
        for mt in g["marker_types"]:
            w = WANT.get(mt["slug"])
            if not w:
                continue
            for m in mt.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" not in c:
                    continue
                v = math.degrees(math.log(math.tan(
                    math.pi / 4 + math.radians(c["lat"]) / 2)))
                X = t["su"] * c["lng"] + t["ou"]
                Y = t["sv"] * v + t["ov"]
                n_tot += 1
                x, y = (X - box[0]) / 8, (Y - box[1]) / 8
                if 0 <= x < mos.width and 0 <= y < mos.height:
                    n_in += 1
                dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=CC[w[0]])
    if slug == "graveyard":
        b = cache_locations()["mg"]
        dr.rectangle([(b[0] - box[0]) / 8, (b[1] - box[1]) / 8,
                      (b[2] - box[0]) / 8, (b[3] - box[1]) / 8], outline="#00c000")
    mos.save(os.path.join(base, f"overlay2_{slug}.png"))
    print(f"{slug}: {n_in}/{n_tot} в кадре -> overlay2_{slug}.png {mos.size}")
