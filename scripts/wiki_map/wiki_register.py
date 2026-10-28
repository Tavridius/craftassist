#!/usr/bin/env python3
"""Привязка карты stalzone.wiki к нашему dmap регистрацией изображений.

Прошлый подход (wiki_solve*.py) подбирал масштаб/сдвиг по облаку маркеров и
давал смещение. Здесь привязываем КАРТИНКИ: подложка вики (wiki_tiles.py) ↔
мозаика нашего детального слоя, SIFT + ratio-test + RANSAC (аффинное
преобразование). Маркеры потом идут по цепочке:
    lat/lng → px вики на maxZoom (веб-меркатор) → px склейки → аффин → px dmap

usage: wiki_register.py <slug> <wiki_png> <zoom склейки> [out_dir]
  — пишет в wiki_transforms.json ключ <slug>.affine (2×3, из px вики на maxZoom
    в нативные px dmap) и оверлей overlay_<slug>.png (маркеры на нашей мозаике).
"""
import glob
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
DMAP = os.path.join(os.path.dirname(os.path.dirname(base)), "frontend", "dmap")
DW, DH = 112128, 51712                      # детальный слой, нативные px (= блоки)
MZ = int(os.environ.get("WIKI_MZ", 4))          # зум нашей мозаики (z4: 1 px = 4 блока)
# регионы территорий (x0,y0,x1,y1) вкл. — как MAP_TERRITORIES в api.py
TERR = {"south-zone": (-14, -3, -4, 13), "north-zone": (-27, 0, -13, 10),
        "wild-north": (12, -5, 18, 3), "lyubech": (-1, -10, 3, -6),
        "labyrinth": (-4, -2, 0, 2)}


def wiki_markers(slug):
    """[(x, y, type_slug, group_slug, marker)] в px вики на maxZoom."""
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    n = 2 ** d["settings"]["maxZoom"] * 256
    out = []
    for g in d["marker_groups"]:
        for t in g["marker_types"]:
            for m in t.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" not in c:
                    continue
                lat = math.radians(c["lat"])
                x = (c["lng"] + 180) / 360 * n
                y = (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n
                out.append((x, y, t["slug"], g.get("slug"), m))
    return d, out


def dmap_mosaic(box, z=MZ):
    """Мозаика dmap на зуме z для нативного бокса (x0,y0,x1,y1)."""
    div = 2 ** (6 - z)
    zx0, zy0 = box[0] // div, box[1] // div
    zx1, zy1 = -(-box[2] // div), -(-box[3] // div)
    im = Image.new("RGB", (zx1 - zx0, zy1 - zy0), (0, 0, 0))
    for tx in range(zx0 // 256, zx1 // 256 + 1):
        for ty in range(zy0 // 256, zy1 // 256 + 1):
            f = os.path.join(DMAP, str(z), str(tx), f"{ty}.webp")
            if os.path.exists(f):
                t = Image.open(f).convert("RGBA")
                bg = Image.new("RGB", t.size, (0, 0, 0))
                bg.paste(t, mask=t.getchannel("A"))
                im.paste(bg, (tx * 256 - zx0, ty * 256 - zy0))
    return im, (zx0 * div, zy0 * div), div


def gray(im):
    g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


def register(wiki_img, our_img):
    """Аффин wiki-склейка → наша мозаика. Возвращает (M 2×3, inliers, matches)."""
    sift = cv2.SIFT_create(nfeatures=40000)
    k1, d1 = sift.detectAndCompute(gray(wiki_img), None)
    k2, d2 = sift.detectAndCompute(gray(our_img), None)
    fl = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    good = [m for m, n in fl.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffine2D(p1, p2, method=cv2.RANSAC,
                                  ransacReprojThreshold=2.0, maxIters=20000,
                                  confidence=0.999)
    return M, inl.ravel().astype(bool), (p1, p2)


def main(slug, wiki_png, wz, out):
    d, pts = wiki_markers(slug)
    mzw = d["settings"]["maxZoom"]
    kw = 2 ** (mzw - wz)                     # px вики на maxZoom → px склейки
    wiki = Image.open(wiki_png).convert("RGB")
    tr = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8"))
    # бокс поиска: регионы территории + поле; иначе — район по старому фиту
    # облака (смещён, но место верное); иначе — весь слой
    old = tr.get(slug)
    if slug in TERR:
        rx0, ry0, rx1, ry1 = TERR[slug]
        m = 3000
        box = [max(0, (rx0 + 86) * 512 - m), max(0, (ry0 + 38) * 512 - m),
               min(DW, (rx1 + 87) * 512 + m), min(DH, (ry1 + 39) * 512 + m)]
    elif old and "su" in old:
        us = [p[0] for p in pts]; vs = [p[1] for p in pts]
        # старый фит жил в координатах (lng, merc-lat); пересчёт не нужен — берём
        # центр облака и размер картинки вики в блоках по его масштабу
        lng = [(u / (2 ** mzw * 256)) * 360 - 180 for u in us]
        cx = old["su"] * (sum(lng) / len(lng)) + old["ou"]
        span = wiki.width * kw / (2 ** mzw * 256) * 360 * abs(old["su"])
        merc = [math.degrees(math.pi - 2 * math.pi * v / (2 ** mzw * 256)) for v in vs]
        cy = old["sv"] * (sum(merc) / len(merc)) + old["ov"]
        spy = span * wiki.height / wiki.width
        m = 4000
        box = [int(max(0, cx - span / 2 - m)), int(max(0, cy - spy / 2 - m)),
               int(min(DW, cx + span / 2 + m)), int(min(DH, cy + spy / 2 + m))]
    else:
        box = [0, 0, DW, DH]
    ours, (ox, oy), div = dmap_mosaic(box)
    print(f"{slug}: вики {wiki.size} (z{wz}), наша мозаика {ours.size} z{MZ} бокс {box}")
    M, inl, (p1, p2) = register(wiki, ours)
    if M is None:
        sys.exit("регистрация не сошлась")
    res = np.linalg.norm((p1[inl] @ M[:, :2].T + M[:, 2]) - p2[inl], axis=1)
    sx, sy = np.linalg.norm(M[:, 0]), np.linalg.norm(M[:, 1])
    rot = math.degrees(math.atan2(M[1, 0], M[0, 0]))
    print(f"  совпадений {len(p1)}, инлайеров {inl.sum()}, невязка "
          f"медиана {np.median(res):.2f} / p90 {np.percentile(res, 90):.2f} px мозаики")
    print(f"  масштаб x {sx:.4f} y {sy:.4f}, поворот {rot:.3f}°")
    # итог: px вики на maxZoom → нативные px dmap
    A = np.zeros((2, 3))
    A[:, :2] = M[:, :2] / kw * div
    A[:, 2] = M[:, 2] * div + [ox, oy]
    tr.setdefault(slug, {})["affine"] = [[round(v, 6) for v in r] for r in A.tolist()]
    tr[slug]["affine_info"] = {"wiki_zoom": wz, "our_zoom": MZ, "inliers": int(inl.sum()),
                               "median_err_blocks": round(float(np.median(res)) * div, 2),
                               "scale_blocks_per_wiki_px": round(float(sx / kw * div), 5)}
    with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
        json.dump(tr, f, ensure_ascii=False, indent=1)
    # оверлей
    dr = ImageDraw.Draw(ours)
    inside = 0
    for x, y, ts, gs, _ in pts:
        X, Y = A @ [x, y, 1]
        u, v = (X - ox) / div, (Y - oy) / div
        if 0 <= u < ours.width and 0 <= v < ours.height:
            inside += 1
        col = {"anomalies": "#ff4040", "other": "#40c8ff"}.get(gs, "#ffd040")
        dr.ellipse([u - 3, v - 3, u + 3, v + 3], outline=col, width=2)
    dst = os.path.join(out, f"overlay_{slug}.png")
    ours.save(dst)
    print(f"  маркеров {len(pts)}, в кадре {inside} -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else base)
