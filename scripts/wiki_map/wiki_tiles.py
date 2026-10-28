#!/usr/bin/env python3
"""Склейка подложки карты stalzone.wiki в одну картинку — для регистрации с dmap.

Тайлы: cdn3.stalzone.wiki/map/tiles/<path>/{z}-{x}-{y}.jpg, 256px, обычная XYZ-
сетка веб-меркатора. settings.width/height в выгрузке (wiki_extract.py) — размер
картинки на zoom maxZoom-1. Качаем последовательно, с паузой, кэшируем на диск.

usage: wiki_tiles.py <slug> [zoom] [out_dir]
выход: <out_dir>/wiki_<slug>_z<zoom>.png (по умолчанию — рядом со скриптом)
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
CDN = "https://cdn3.stalzone.wiki/map/tiles/"
_o = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def stitch(slug: str, z: int | None, out: str) -> str:
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    st = d["settings"]
    path = st["tiles"].split("/map/tiles/", 1)[1]
    z = st["maxZoom"] if z is None else z
    k = 2 ** (z - (st["maxZoom"] - 1))
    nx, ny = math.ceil(st["width"] * k / 256), math.ceil(st["height"] * k / 256)
    # width/height у части карт (wild-north) занижены — расширяем по маркерам
    n = 2 ** z * 256
    for g in d["marker_groups"]:
        for t in g["marker_types"]:
            for m in t.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" in c:
                    lat = math.radians(c["lat"])
                    x = (c["lng"] + 180) / 360 * n
                    y = (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * n
                    nx, ny = max(nx, int(x // 256) + 2), max(ny, int(y // 256) + 2)
    cache = os.path.join(out, "tiles", slug, str(z))
    os.makedirs(cache, exist_ok=True)
    im = Image.new("RGB", (nx * 256, ny * 256))
    got = 0
    for x in range(nx):
        for y in range(ny):
            f = os.path.join(cache, f"{x}-{y}.jpg")
            if not os.path.exists(f):
                try:
                    with _o.open(f"{CDN}{path}/{z}-{x}-{y}.jpg", timeout=30) as r:
                        data = r.read()
                except urllib.error.HTTPError:
                    data = b""
                with open(f, "wb") as fh:
                    fh.write(data)
                time.sleep(0.15)
            if os.path.getsize(f):
                im.paste(Image.open(f).convert("RGB"), (x * 256, y * 256))
                got += 1
    dst = os.path.join(out, f"wiki_{slug}_z{z}.png")
    im.save(dst)
    print(f"{slug} z{z}: {nx}x{ny} тайлов, есть {got} -> {dst} {im.size}")
    return dst


if __name__ == "__main__":
    stitch(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None,
           sys.argv[3] if len(sys.argv) > 3 else base)
