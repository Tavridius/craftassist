#!/usr/bin/env python3
"""Проверка привязки на ориентирах: вырезка подложки вики (перенесённой нашим
аффином) | наш dmap z6 | шахматка обеих — с маркерами выбранных типов.

usage: wiki_check.py <slug> <wiki_png> <zoom склейки> <out_dir> [тип ...]
Берёт по маркеру каждого типа (по умолчанию bunker, stasis, лагеря), режет
окно 240×240 блоков вокруг него. Совпадение дорог/зданий на шахматке и есть
проверка: смещение видно сразу.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from wiki_register import dmap_mosaic, wiki_markers  # noqa: E402

R = 120


def main(slug, wiki_png, wz, out, types):
    d, pts = wiki_markers(slug)
    A = np.array(json.load(open(os.path.join(base, "wiki_transforms.json"),
                                encoding="utf-8"))[slug]["affine"])
    kw = 2 ** (d["settings"]["maxZoom"] - wz)
    wiki = Image.open(wiki_png).convert("RGB")
    # обратный аффин: блоки → px склейки вики
    A3 = np.vstack([A, [0, 0, 1]])
    inv = np.linalg.inv(A3)
    types = types or ["bunker", "stasis", "stalkers-camp", "bandits-camp",
                      "military-base", "rise-headquarters", "murmur-base", "location_exit"]
    rows = []
    for ts in types:
        sel = [p for p in pts if p[2] == ts][:2]
        for x, y, _, _, m in sel:
            X, Y = A @ [x, y, 1]
            bx0, by0 = int(X) - R, int(Y) - R
            ours, _, _ = dmap_mosaic((bx0, by0, bx0 + 2 * R, by0 + 2 * R), z=6)
            # вики → блоки: каждый px окна (u,v) в блоках → px склейки
            M = inv[:2] @ np.array([[1, 0, bx0], [0, 1, by0], [0, 0, 1]])
            M = M / kw
            # PIL affine: на вход — отображение выходного px во входной
            wk = wiki.transform((2 * R, 2 * R), Image.AFFINE,
                                tuple(M.ravel()), resample=Image.BILINEAR)
            chk = ours.copy()
            for i in range(0, 2 * R, 40):
                for j in range(0, 2 * R, 40):
                    if (i // 40 + j // 40) % 2:
                        chk.paste(wk.crop((i, j, i + 40, j + 40)), (i, j))
            row = Image.new("RGB", (6 * R + 20, 2 * R + 16), (20, 20, 20))
            for k, im in enumerate((wk, ours, chk)):
                im = im.copy()
                dr = ImageDraw.Draw(im)
                dr.ellipse([R - 5, R - 5, R + 5, R + 5], outline="#ff3030", width=2)
                row.paste(im, (k * (2 * R + 10), 16))
            ImageDraw.Draw(row).text((4, 2), f"{ts}  блок X={X - 86 * 512:.0f} "
                                     f"Z={Y - 38 * 512:.0f}", fill="#ffffff")
            rows.append(row)
    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)))
    yy = 0
    for r in rows:
        sheet.paste(r, (0, yy)); yy += r.height
    dst = os.path.join(out, f"check_{slug}.png")
    sheet.save(dst)
    print(f"{len(rows)} ориентиров -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5:])
