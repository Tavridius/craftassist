"""Привязка v2: перцентильный bbox маркерного облака → union-bbox локаций
из map_cache, затем локальный grid-search (максимизация доли маркеров внутри
объединения локаций). Работает, когда кэш покрывает все локации карты (юг, мг).
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
from wiki_solve import wiki_points, cache_locations  # noqa: E402


def pct(vals, p):
    s = sorted(vals)
    i = (len(s) - 1) * p
    lo = int(i)
    return s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (i - lo)


def solve_bbox(slug, loc_names, reg_box=None, plo=0.02, phi=0.98):
    pts = wiki_points(slug)
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    locs = cache_locations(reg_box)
    boxes = [locs[n] for n in loc_names if n in locs]
    missing = [n for n in loc_names if n not in locs]
    if missing:
        print(f"  ! нет в кэше: {missing}")
    Ux0 = min(b[0] for b in boxes); Uy0 = min(b[1] for b in boxes)
    Ux1 = max(b[2] for b in boxes); Uy1 = max(b[3] for b in boxes)
    u0, u1 = pct(us, plo), pct(us, phi)
    v0, v1 = pct(vs, plo), pct(vs, phi)
    su = (Ux1 - Ux0) / (u1 - u0)
    sv = -(Uy1 - Uy0) / (v1 - v0)
    ou = Ux0 - su * u0
    ov = Uy0 - sv * v1
    mid = sum(vs) / len(vs)

    def hits(su, ou, sv, ov):
        n = 0
        for u, v, _ in pts:
            X = su * u + ou
            Y = sv * v + ov
            for b in boxes:
                if b[0] <= X <= b[2] and b[1] <= Y <= b[3]:
                    n += 1
                    break
        return n

    # локальный grid-search вокруг инициализации
    best = (hits(su, ou, sv, ov), su, ou, sv, ov)
    for it in range(3):
        _, su, ou, sv, ov = best
        step_s = 0.06 / (it + 1)
        step_o = 400 / (it + 1)
        for dsu in (-step_s, 0, step_s):
            for dsv in (-step_s, 0, step_s):
                for dou in (-step_o, 0, step_o):
                    for dov in (-step_o, 0, step_o):
                        s2 = su * (1 + dsu); v2 = sv * (1 + dsv)
                        o2 = ou + dou - (s2 - su) * (u0 + u1) / 2
                        p2 = ov + dov - (v2 - sv) * (v0 + v1) / 2
                        h = hits(s2, o2, v2, p2)
                        if h > best[0]:
                            best = (h, s2, o2, v2, p2)
    h, su, ou, sv, ov = best
    cosmid = math.cos(math.radians(sum(
        [m for m in []] or [0])))  # placeholder не используется
    print(f"{slug}: hits {h}/{len(pts)} ({100*h/len(pts):.0f}%)  "
          f"su={su:.2f} ou={ou:.0f} sv={sv:.2f} ov={ov:.0f}  "
          f"ratio={-sv/su:.2f}")
    return {"su": su, "ou": ou, "sv": sv, "ov": ov,
            "hits": h, "total": len(pts)}


SOUTH_LOCS = ["bolota", "kordon", "svalka", "agroprom", "bar", "armsklad",
              "yantar", "mg", "pd", "rls", "yanov", "zaton"]

if __name__ == "__main__":
    out = json.load(open(os.path.join(base, "wiki_transforms.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(base, "wiki_transforms.json")) else {}
    out["south-zone"] = solve_bbox("south-zone", SOUTH_LOCS, (-14, -3, -4, 13))
    with open(os.path.join(base, "wiki_transforms.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
