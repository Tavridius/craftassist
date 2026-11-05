#!/usr/bin/env python3
"""Вклеить подложку карты stalzone.wiki в нашу пирамиду dmap — временно, пока
в клиенте территория под облаками КПК (Дикий Север, 11.2026).

Картинка вики (wiki_tiles.py) ставится по ключу <slug>.affine из
wiki_transforms.json (px вики на maxZoom → нативные px dmap) — той же
привязкой, что и метки (wiki_export_v2.py), поэтому метки ложатся на подложку
точно. Перекрываются только пиксели, где у вики есть изображение; облака
вокруг остаются.

Пересобираются тайлы z6 в рамке картинки и их предки z5..z0. Откат — прогон
gen_detail_pyramid.py по клиенту (или git checkout frontend/dmap).

usage: wiki_underlay.py <slug> <wiki_png> <wiki_zoom> [dmap_dir]
"""
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
TS = 256
QUALITY = 70                                   # как gen_detail_pyramid.py


def tile_path(out, z, x, y):
    return os.path.join(out, str(z), str(x), f"{y}.webp")


def save(out, z, x, y, im):
    if im.getchannel("A").getextrema()[1] == 0:
        return
    os.makedirs(os.path.join(out, str(z), str(x)), exist_ok=True)
    im.save(tile_path(out, z, x, y), "WEBP", quality=QUALITY, method=6)


def main(slug, wiki_png, wz, out):
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    A = np.array(json.load(open(os.path.join(base, "wiki_transforms.json"),
                                encoding="utf-8"))[slug]["affine"], dtype=np.float64)
    kw = 2 ** (d["settings"]["maxZoom"] - wz)  # px склейки → px вики на maxZoom
    # px склейки → нативные px dmap
    P = A.copy()
    P[:, :2] *= kw
    src = np.asarray(Image.open(wiki_png).convert("RGB"))
    # где у вики есть картинка: не чёрный фон незагруженных тайлов
    mask = (src.max(axis=2) > 10).astype(np.uint8) * 255
    # за краем карты тайлы вики сплошь белые (Дикий Север: картинка 6356×3056
    # в склейке 6400×3328) — такие столбцы и строки не берём
    white = src.min(axis=2) > 245
    mask[:, white.mean(axis=0) > 0.9] = 0
    mask[white.mean(axis=1) > 0.9, :] = 0
    mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
    # по краю карты у вики светлая кайма — срезаем
    ys, xs = np.nonzero(mask)
    edge = 12
    mask[:, :xs.min() + edge] = 0
    mask[:, xs.max() - edge:] = 0
    mask[:ys.min() + edge, :] = 0
    mask[ys.max() - edge:, :] = 0
    h, w = mask.shape
    corners = P @ np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]]).T
    x0, y0 = corners.min(axis=1)
    x1, y1 = corners.max(axis=1)
    print(f"{slug}: склейка {w}x{h} z{wz} -> dmap [{x0:.0f},{y0:.0f} .. {x1:.0f},{y1:.0f}]")

    touched = set()
    for tx in range(int(x0 // TS), int(math.ceil(x1 / TS))):
        for ty in range(int(y0 // TS), int(math.ceil(y1 / TS))):
            M = P.copy()
            M[:, 2] -= (tx * TS, ty * TS)
            m = cv2.warpAffine(mask, M, (TS, TS), flags=cv2.INTER_LINEAR,
                               borderValue=0)
            if not m.any():
                continue
            rgb = cv2.warpAffine(src, M, (TS, TS), flags=cv2.INTER_LINEAR,
                                 borderValue=(0, 0, 0))
            p = tile_path(out, 6, tx, ty)
            under = (Image.open(p).convert("RGBA") if os.path.exists(p)
                     else Image.new("RGBA", (TS, TS), (0, 0, 0, 0)))
            top = Image.fromarray(np.dstack([rgb, np.full((TS, TS), 255, np.uint8)]))
            save(out, 6, tx, ty, Image.composite(top, under, Image.fromarray(m)))
            touched.add((tx, ty))
    print(f"  z6: тайлов {len(touched)}")

    for z in range(5, -1, -1):
        touched = {(x // 2, y // 2) for x, y in touched}
        for x, y in touched:
            cv = Image.new("RGBA", (TS * 2, TS * 2), (0, 0, 0, 0))
            for i in range(2):
                for j in range(2):
                    p = tile_path(out, z + 1, x * 2 + i, y * 2 + j)
                    if os.path.exists(p):
                        cv.paste(Image.open(p).convert("RGBA"), (i * TS, j * TS))
            save(out, z, x, y, cv.resize((TS, TS), Image.LANCZOS))
        print(f"  z{z}: тайлов {len(touched)}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else
         os.path.join(os.path.dirname(os.path.dirname(base)), "frontend", "dmap"))
