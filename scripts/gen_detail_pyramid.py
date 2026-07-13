"""Пирамида детальной карты (pda/map) для Leaflet — второй уровень карты сайта.

Источник: клиент игры `modassets/assets/pda/map/r.X.Y.ol` — разреженная сетка
512px-регионов (1 px = 1 блок мира), один общий план для всех территорий.

Прогон (после обновления карты в игре):
  1) NO_PROXY=* python -m scfile convert <папка pda/map> -O <tmp>
  2) python scripts/gen_detail_pyramid.py <tmp с r.X.Y.dds> [frontend/dmap]

Выход: frontend/dmap/{z}/{x}/{y}.webp, 256px, zoom 0..6 (z6 = нативные пиксели).
Начало координат пирамиды — регион (XMIN, YMIN); синхронно MAP_META в api.py.
"""
import glob
import os
import re
import sys

from PIL import Image

TS = 256
MAXZ = 6
QUALITY = 70

XMIN, XMAX = -86, 132       # сетка регионов в клиенте (разреженная)
YMIN, YMAX = -38, 62
REG = 512


def main(src: str, out: str) -> None:
    tiles: dict[tuple[int, int], str] = {}
    for f in glob.glob(os.path.join(src, "r.*.dds")):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.dds$", os.path.basename(f))
        if m:
            tiles[(int(m.group(1)), int(m.group(2)))] = f
    print(f"регионов: {len(tiles)}")

    saved = 0

    def save_tile(z: int, x: int, y: int, im: Image.Image) -> None:
        nonlocal saved
        if im.getchannel("A").getextrema()[1] == 0:
            return
        d = os.path.join(out, str(z), str(x))
        os.makedirs(d, exist_ok=True)
        im.save(os.path.join(d, f"{y}.webp"), "WEBP", quality=QUALITY, method=6)
        saved += 1

    # z6 (native, регион = 2×2 тайла) и z5 (регион = 1 тайл) — порегионно
    for (X, Y), f in tiles.items():
        im = Image.open(f).convert("RGBA")
        cx, cy = X - XMIN, Y - YMIN
        for i in range(2):
            for j in range(2):
                save_tile(6, cx * 2 + i, cy * 2 + j,
                          im.crop((i * TS, j * TS, i * TS + TS, j * TS + TS)))
        save_tile(5, cx, cy, im.resize((TS, TS), Image.LANCZOS))

    # z4..z0: тайл z объединяет 2×2 тайла z+1 (читаем уже записанные webp)
    for z in range(4, -1, -1):
        seen: set[tuple[int, int]] = set()
        for path in glob.glob(os.path.join(out, str(z + 1), "*", "*.webp")):
            px = int(os.path.basename(os.path.dirname(path)))
            py = int(os.path.basename(path)[:-5])
            seen.add((px // 2, py // 2))
        for (x, y) in seen:
            cv = Image.new("RGBA", (TS * 2, TS * 2), (0, 0, 0, 0))
            for i in range(2):
                for j in range(2):
                    p = os.path.join(out, str(z + 1), str(x * 2 + i), f"{y * 2 + j}.webp")
                    if os.path.exists(p):
                        cv.paste(Image.open(p).convert("RGBA"), (i * TS, j * TS))
            save_tile(z, x, y, cv.resize((TS, TS), Image.LANCZOS))

    w, h = (XMAX - XMIN + 1) * REG, (YMAX - YMIN + 1) * REG
    print(f"план {w}×{h} (1px=1 блок), тайлов записано: {saved} → {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: gen_detail_pyramid.py <dir с r.X.Y.dds> [out=frontend/dmap]")
    main(sys.argv[1],
         sys.argv[2] if len(sys.argv) > 2 else
         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "frontend", "dmap"))
