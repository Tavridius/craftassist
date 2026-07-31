"""Привязка координат stalzone.wiki к нашей детальной карте.

Модель: их хранение (lat,lng) отображается на экран через веб-меркатор →
u = lng, v = merc_deg(lat) линейны относительно игрового плана:
    world_x = su*u + ou ;  world_y = sv*v + ov   (su>0, sv<0)

Якоря без ручной разметки: клиентский map_cache даёт «локация → регионы мира»,
кластеры маркеров вики ≈ локации. RANSAC по парам (кластер, локация).

world px здесь = px детальной пирамиды (регион R → (R - (-86,-38)) * 512).
"""
import glob
import json
import math
import os
import re
import sys
from itertools import combinations

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
CACHE = r"d:\EXBO\runtime\stalcraft\map_cache\5.0"
X0, Y0 = -86, -38


def merc(lat):
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def wiki_points(slug):
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    pts = []
    for g in d["marker_groups"]:
        for t in g["marker_types"]:
            for m in t.get("markers") or []:
                c = m.get("coordinates") or {}
                if "lat" in c:
                    pts.append((c["lng"], merc(c["lat"]), t["slug"]))
    return pts


def cluster(pts, eps):
    """Union-find по близости центров (алгоритм «жадные кластеры»)."""
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in combinations(range(len(pts)), 2):
        if abs(pts[i][0] - pts[j][0]) < eps and abs(pts[i][1] - pts[j][1]) < eps:
            parent[find(i)] = find(j)
    groups = {}
    for i in range(len(pts)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        if len(idx) < 5:
            continue
        us = [pts[i][0] for i in idx]
        vs = [pts[i][1] for i in idx]
        out.append({"n": len(idx), "cu": sum(us) / len(us), "cv": sum(vs) / len(vs),
                    "u0": min(us), "u1": max(us), "v0": min(vs), "v1": max(vs)})
    return out


def cache_locations(reg_box=None, skip=("battlefield", "dungeon", "operation",
                                        "signals", "prestige", "tutorial", "save",
                                        "hideout", "encaged", "poligon")):
    """Локации из map_cache: имя → бокс доминирующего блоба регионов (world px)."""
    locs = {}
    for d in sorted(glob.glob(os.path.join(CACHE, "*"))):
        name = os.path.basename(d)
        if any(s in name for s in skip):
            continue
        regs = []
        for f in glob.glob(os.path.join(d, "reg.*.mdat")):
            m = re.match(r"reg\.(-?\d+)\.(-?\d+)\.mdat$", os.path.basename(f))
            if m:
                regs.append((int(m.group(1)), int(m.group(2))))
        if not regs:
            continue
        # доминирующий блоб: связные компоненты по 8-соседству
        regs = set(regs)
        best = []
        seen = set()
        for r in regs:
            if r in seen:
                continue
            comp, stack = [], [r]
            seen.add(r)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nb = (cur[0] + dx, cur[1] + dy)
                        if nb in regs and nb not in seen:
                            seen.add(nb)
                            stack.append(nb)
            if len(comp) > len(best):
                best = comp
        xs = [r[0] for r in best]
        ys = [r[1] for r in best]
        if reg_box:
            bx0, by0, bx1, by1 = reg_box
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            if not (bx0 - 1 <= cx <= bx1 + 1 and by0 - 1 <= cy <= by1 + 1):
                continue
        locs[name] = ((min(xs) - X0) * 512, (min(ys) - Y0) * 512,
                      (max(xs) - X0 + 1) * 512, (max(ys) - Y0 + 1) * 512)
    return locs


def solve(slug, reg_box, eps_frac=45, pad=768):
    pts = wiki_points(slug)
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    # средняя широта карты — для меркаторного ограничения масштабов
    d = json.load(open(os.path.join(base, f"wiki_{slug}.json"), encoding="utf-8"))
    lats = [m["coordinates"]["lat"] for g in d["marker_groups"]
            for t in g["marker_types"] for m in t.get("markers") or []
            if m.get("coordinates")]
    global cos_mid
    cos_mid = math.cos(math.radians(sum(lats) / len(lats)))
    eps = max(max(us) - min(us), max(vs) - min(vs)) / eps_frac
    cls = cluster(pts, eps)
    locs = cache_locations(reg_box)
    print(f"{slug}: {len(pts)} маркеров -> {len(cls)} кластеров; локаций-кандидатов {len(locs)}")
    for n, b in locs.items():
        print(f"   {n:22} px {b}")

    def loc_c(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    best = None
    loc_items = list(locs.items())
    for ci, cj in combinations(range(len(cls)), 2):
        a, b = cls[ci], cls[cj]
        if abs(a["cu"] - b["cu"]) < eps or abs(a["cv"] - b["cv"]) < eps:
            continue                        # пары почти на одной оси не дают масштаба
        for (na, ba), (nb, bb) in combinations(loc_items, 2):
            for (c1, l1), (c2, l2) in (((a, ba), (b, bb)), ((a, bb), (b, ba))):
                x1, y1 = loc_c(l1)
                x2, y2 = loc_c(l2)
                su = (x2 - x1) / (c2["cu"] - c1["cu"])
                sv = (y2 - y1) / (c2["cv"] - c1["cv"])
                if su <= 0 or sv >= 0:
                    continue
                # физика меркатора: блок в px тайла растянут по x в 1/cos(lat);
                # в градусо-меркаторной v это даёт |sv| ~ su*cos(среднего lat)
                if not (0.55 < -sv / (su * cos_mid) < 1.8):
                    continue
                ou = x1 - su * c1["cu"]
                ov = y1 - sv * c1["cv"]
                # инлаеры: кластер попал в паддед-бокс какой-то локации
                used = set()
                inl = 0
                for c in cls:
                    X = su * c["cu"] + ou
                    Y = sv * c["cv"] + ov
                    for nm, lb in loc_items:
                        if nm in used:
                            continue
                        if lb[0] - pad <= X <= lb[2] + pad and lb[1] - pad <= Y <= lb[3] + pad:
                            used.add(nm)
                            inl += 1
                            break
                if best is None or inl > best[0]:
                    best = (inl, su, ou, sv, ov)
    if not best:
        print("  не решилось")
        return None
    inl, su, ou, sv, ov = best
    print(f"  ЛУЧШЕЕ: инлаеров {inl}/{len(cls)}  su={su:.2f} ou={ou:.0f} sv={sv:.2f} ov={ov:.0f}")
    return {"su": su, "ou": ou, "sv": sv, "ov": ov, "inliers": inl, "clusters": len(cls)}


if __name__ == "__main__":
    out = {}
    for slug, box in (("south-zone", (-14, -3, -4, 13)),
                      ("north-zone", (-27, 0, -13, 10))):
        r = solve(slug, box)
        if r:
            out[slug] = r
    with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
