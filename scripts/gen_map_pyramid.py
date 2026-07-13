"""Сборка Leaflet-пирамиды тайлов карты мира из global_map КПК STALZONE.

Источник: клиент игры, `modassets/assets/pda/global_map/r.X.Y.ol` —
36 регион-тайлов 2048² (сетка X:-4..4, Y:-2..1), полный мир 18432×8192.

Прогон (один раз при обновлении карты в игре):
  1) .ol → .dds:  NO_PROXY=* python -m scfile convert <папка global_map> -O <tmp>
     (pip install sc-file; системный SOCKS-прокси ломает pip/httpx — обходить NO_PROXY=*)
  2) python scripts/gen_map_pyramid.py <tmp с r.X.Y.dds> [frontend/wmap]

Выход: frontend/wmap/{z}/{x}/{y}.webp — 256px, zoom 0..6 (z6 = нативные пиксели).
Параметры ниже синхронны MAP_META в backend/app/routers/api.py.
"""
import glob
import os
import re
import sys

from PIL import Image

TS = 256          # размер тайла Leaflet
MAXZ = 6          # z6 — нативное разрешение источника
QUALITY = 72      # webp: спутниковая картинка, ниже — заметно мылит

XMIN, XMAX, YMIN, YMAX = -4, 4, -2, 1              # сетка регионов в клиенте
COLS, ROWS = XMAX - XMIN + 1, YMAX - YMIN + 1      # 9 × 4
REG = 2048                                          # пиксели региона
FULL_W, FULL_H = COLS * REG, ROWS * REG             # 18432 × 8192


def main(src: str, out: str) -> None:
    regions: dict[tuple[int, int], Image.Image] = {}   # (col,row) → RGBA 2048²
    for f in glob.glob(os.path.join(src, "r.*.dds")):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.dds$", os.path.basename(f))
        if not m:
            continue
        x, y = int(m.group(1)), int(m.group(2))
        regions[(x - XMIN, y - YMIN)] = Image.open(f).convert("RGBA")
    if len(regions) != COLS * ROWS:
        print(f"WARN: регионов {len(regions)}, ожидалось {COLS * ROWS} — сетка в игре сменилась?")

    saved = 0

    def save_tile(z: int, x: int, y: int, im: Image.Image) -> None:
        nonlocal saved
        if im.getchannel("A").getextrema()[1] == 0:    # полностью прозрачный — не пишем
            return
        d = os.path.join(out, str(z), str(x))
        os.makedirs(d, exist_ok=True)
        im.save(os.path.join(d, f"{y}.webp"), "WEBP", quality=QUALITY, method=6)
        saved += 1

    # z ≥ 3: тайлы не пересекают границы регионов — режем каждый регион отдельно,
    # без сборки гигантского холста в памяти
    for z in range(MAXZ, 2, -1):
        reg_px = REG // (2 ** (MAXZ - z))              # 2048, 1024, 512, 256
        n = reg_px // TS
        for (col, row), im0 in regions.items():
            im = im0 if reg_px == REG else im0.resize((reg_px, reg_px), Image.LANCZOS)
            for i in range(n):
                for j in range(n):
                    save_tile(z, col * n + i, row * n + j,
                              im.crop((i * TS, j * TS, i * TS + TS, j * TS + TS)))

    # z ≤ 2: мир уже мал (z3 = 2304×1024) — собираем холст и уменьшаем
    canvas3 = Image.new("RGBA", (COLS * TS, ROWS * TS), (0, 0, 0, 0))
    for (col, row), im0 in regions.items():
        canvas3.paste(im0.resize((TS, TS), Image.LANCZOS), (col * TS, row * TS))
    for z in (2, 1, 0):
        div = 2 ** (MAXZ - z)
        cv = canvas3.resize((FULL_W // div, FULL_H // div), Image.LANCZOS)
        nx, ny = -(-cv.width // TS), -(-cv.height // TS)
        for x in range(nx):
            for y in range(ny):
                sub = Image.new("RGBA", (TS, TS), (0, 0, 0, 0))
                sub.paste(cv.crop((x * TS, y * TS, min(x * TS + TS, cv.width),
                                   min(y * TS + TS, cv.height))), (0, 0))
                save_tile(z, x, y, sub)

    print(f"мир {FULL_W}×{FULL_H}, тайлов записано: {saved} → {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: gen_map_pyramid.py <dir с r.X.Y.dds> [out=frontend/wmap]")
    main(sys.argv[1],
         sys.argv[2] if len(sys.argv) > 2 else
         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "frontend", "wmap"))
