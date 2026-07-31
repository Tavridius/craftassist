"""Пара картинок для визуальной привязки: наша территория (dmap z3) и скаттер
маркеров wiki-карты (lng, mercator-lat), нормированный в тот же размер.

usage: render_pair.py <terr_id> <wiki_slug>
терр. bbox — как в api.py: _bbox_px(регионы), DETAIL X0,Y0 = -86,-38.
"""
import glob
import json
import math
import os
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
DMAP = r"d:\stalzone craft\frontend\dmap"
X0, Y0 = -86, -38

TERR = {  # регионы (x0,y0,x1,y1) вкл. — из api.py MAP_TERRITORIES
    "south":   (-14, -3, -4, 13),
    "sever":   (-27, 0, -13, 10),
    "wnorth":  (12, -3, 18, 3),
    "limansk": (-4, -2, 0, 2),
}

# приметные типы: якорные кандидаты рисуем цветом и подписью номера
HIGHLIGHT = {
    "rise-headquarters": ("#ff4040", "ШЗ"), "frontier-headquarters": ("#ff8c00", "ШР"),
    "covenant-headquarters": ("#00c8ff", "ШЗв"), "mercenary-headquarters": ("#ffe040", "ШН"),
    "military-base": ("#ff4040", "ВБ"), "bandits-camp": ("#ffe040", "ЛБ"),
    "stalkers-camp": ("#00ff70", "ЛС"), "military-camp": ("#ff8c00", "ЛВ"),
    "murmur-base": ("#ff4040", "БШ"), "location_exit": ("#00ff70", "ВЫХ"),
    "shopot_control_center": ("#00c8ff", "ПУ"),
    "sanitars-camp": ("#c080ff", "САН"),
}


def terr_mosaic(tid, z=3):
    rx0, ry0, rx1, ry1 = TERR[tid]
    px0, py0 = (rx0 - X0) * 512, (ry0 - Y0) * 512
    px1, py1 = (rx1 - X0 + 1) * 512, (ry1 - Y0 + 1) * 512
    div = 2 ** (6 - z)
    zx0, zy0, zx1, zy1 = px0 // div, py0 // div, px1 // div, py1 // div
    im = Image.new("RGB", (zx1 - zx0, zy1 - zy0), (8, 10, 8))
    t0x, t0y = zx0 // 256, zy0 // 256
    for f in glob.glob(os.path.join(DMAP, str(z), "*", "*.webp")):
        tx = int(os.path.basename(os.path.dirname(f)))
        ty = int(os.path.splitext(os.path.basename(f))[0])
        ox, oy = tx * 256 - zx0, ty * 256 - zy0
        if -256 < ox < im.width and -256 < oy < im.height:
            im.paste(Image.open(f).convert("RGB"), (ox, oy))
    return im, (px0, py0, px1, py1)


def merc(lat):
    """Меркаторная y в градусо-эквивалентах — соизмерима с lng в градусах."""
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def scatter(slug, w, h):
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    pts = []
    for g in d["marker_groups"]:
        for t in g["marker_types"]:
            for m in t.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" in c:
                    pts.append((c["lng"], merc(c["lat"]), t["slug"]))
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 30
    sc = min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0))
    im = Image.new("RGB", (w, h), (12, 12, 16))
    dr = ImageDraw.Draw(im)
    for lng, my, ts in pts:
        x = pad + (lng - x0) * sc
        y = pad + (y1 - my) * sc          # mercator y растёт на север — переворот
        col, lbl = HIGHLIGHT.get(ts, ("#3c5a3c", None))
        r = 4 if lbl else 2
        dr.ellipse([x - r, y - r, x + r, y + r], fill=col)
        if lbl:
            dr.text((x + 5, y - 5), lbl, fill=col)
    return im


def main(tid, slug):
    mos, pxbox = terr_mosaic(tid)
    mos.save(os.path.join(base, f"our_{tid}.png"))
    sc = scatter(slug, mos.width, mos.height)
    sc.save(os.path.join(base, f"wiki_{slug}_scatter.png"))
    print(f"our_{tid}.png {mos.size} px-бокс {pxbox}")
    print(f"wiki_{slug}_scatter.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
