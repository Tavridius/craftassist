#!/usr/bin/env python3
"""Выгрузка срезов из Я.Метрики под аудит (счётчик 110585101).

Раньше срезы снимались одноразовыми скриптами, которые не переживали аудит.
Здесь то же самое, но набором именованных запросов: `python scripts/ym_dump.py
<срез> [--from ГГГГ-ММ-ДД] [--to ГГГГ-ММ-ДД]`. Без аргументов — список срезов.

    python scripts/ym_dump.py base --from 2026-08-01 --to 2026-08-06
    python scripts/ym_dump.py entry-device
    python scripts/ym_dump.py all --from 2026-07-11 --to 2026-07-31

Токен: YM_TOKEN в окружении или в .env в корне (см. scripts/ab_stats.py).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTER = 110585101
STAT = "https://api-metrika.yandex.net/stat/v1/data"
MGMT = f"https://api-metrika.yandex.net/management/v1/counter/{COUNTER}/goals"

# системный SOCKS-прокси на машине владельца ломает исходящие запросы — идём мимо
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

BASE = ["ym:s:visits", "ym:s:users", "ym:s:bounceRate",
        "ym:s:pageDepth", "ym:s:avgVisitDurationSeconds"]

# срез -> (заголовок, dimensions, metrics, filters, limit)
SLICES = {
    "base":         ("Всего за период", "", BASE, "", 1),
    "sources":      ("Источники трафика", "ym:s:lastsignTrafficSource", BASE, "", 20),
    "engines":      ("Поисковые системы", "ym:s:lastsignSearchEngine", BASE, "", 20),
    "entry":        ("Страницы входа", "ym:s:startURLPath", BASE, "", 60),
    "entry-device": ("Страница входа x устройство", "ym:s:startURLPath,ym:s:deviceCategory", BASE, "", 200),
    "device":       ("Тип устройства", "ym:s:deviceCategory", BASE, "", 10),
    "phrases":      ("Поисковые фразы", "ym:s:searchPhrase", BASE, "", 100),
    "pages":        ("Просмотры страниц", "ym:pv:URLPath", ["ym:pv:pageviews", "ym:pv:users"], "", 60),
    "browsers":     ("Браузеры", "ym:s:browser", BASE, "", 20),
    "geo":          ("География", "ym:s:regionCity", BASE, "", 20),
    "newness":      ("Новые и вернувшиеся", "ym:s:isNewUser", BASE, "", 5),
    "referers":     ("Переходы по ссылкам", "ym:s:referalSource", BASE,
                     "ym:s:lastsignTrafficSource=='referral'", 30),
    "depth":        ("Распределение глубины", "ym:s:pageViews", ["ym:s:visits"], "", 30),
    "resolution":   ("Разрешение экрана", "ym:s:screenFormat", BASE, "", 20),
    "daily":        ("По дням", "ym:s:date", BASE, "", 400),
    "daily-device": ("По дням x устройство", "ym:s:date,ym:s:deviceCategory", BASE, "", 400),
}


def token() -> str:
    t = os.getenv("YM_TOKEN", "").strip()
    if t:
        return t
    try:
        env = open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace").read()
    except OSError:
        sys.exit("нет .env и нет YM_TOKEN в окружении")
    m = re.search(r"^YM_TOKEN=(\S+)", env, re.M)
    if not m:
        sys.exit("в .env нет строки YM_TOKEN=...")
    return m.group(1).strip().strip("'\"")


def get(url: str, tok: str, **params) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {tok}"})
    try:
        with _opener.open(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print(f"  !! API {e.code}: {body}", file=sys.stderr)
        return {"data": []}


def goals(tok: str) -> list[tuple[int, str]]:
    return [(g["id"], g["name"]) for g in get(MGMT, tok).get("goals", [])]


def run(name: str, tok: str, d1: str, d2: str, with_goals: bool = False) -> None:
    title, dims, metrics, filters, limit = SLICES[name]
    metrics = list(metrics)
    labels = ["визиты", "польз.", "отказы%", "глуб.", "время"] if metrics[:5] == BASE \
        else [m.split(":")[-1] for m in metrics]
    if with_goals and metrics[:5] == BASE:
        gs = goals(tok)
        metrics += [f"ym:s:goal{g}visits" for g, _ in gs]
        # имена целей длиннее колонки — режем, иначе шапка съезжает относительно цифр
        labels += [n.replace("Автоцель: ", "")[:9] for _, n in gs]

    params = dict(ids=COUNTER, date1=d1, date2=d2, metrics=",".join(metrics),
                  limit=limit, accuracy="full")
    if dims:
        params["dimensions"] = dims
    if filters:
        params["filters"] = filters
    d = get(STAT, tok, **params)

    print(f"\n### {title}  [{d1} .. {d2}]")
    rows = d.get("data", [])
    if not rows:
        print("  (нет данных)")
        return
    print(f"  {'':<44}" + "".join(f"{l:>10}" for l in labels))
    for row in rows:
        key = " / ".join((x.get("name") or x.get("id") or "—") or "—"
                         for x in row["dimensions"]) if row["dimensions"] else "ИТОГО"
        key = key[:43]
        vals = "".join(f"{v:>10.1f}" for v in row["metrics"])
        print(f"  {key:<44}{vals}")
    tot = d.get("totals")
    if tot and rows and row["dimensions"]:
        print(f"  {'= ИТОГО':<44}" + "".join(f"{v:>10.1f}" for v in tot))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {}
    for i, a in enumerate(sys.argv[1:]):
        if a.startswith("--") and i + 1 < len(sys.argv) - 1:
            flags[a[2:]] = sys.argv[i + 2]
    if not args:
        print("срезы:", ", ".join(SLICES), "\n  ym_dump.py <срез|all> [--from Д] [--to Д] [--goals]")
        return
    d2 = flags.get("to") or date.today().isoformat()
    d1 = flags.get("from") or (date.fromisoformat(d2) - timedelta(days=30)).isoformat()
    tok = token()
    wg = "--goals" in sys.argv
    names = list(SLICES) if args[0] == "all" else args
    for n in names:
        if n not in SLICES:
            print(f"неизвестный срез: {n}", file=sys.stderr)
            continue
        run(n, tok, d1, d2, with_goals=wg)


if __name__ == "__main__":
    main()
