#!/usr/bin/env python3
"""A/B-тест дизайна: сводка из Я.Метрики по параметру визита ab_design.

Что делает: тянет цели счётчика (management API), затем один запрос статистики
(stat API) с разбивкой по параметру визита ab_design и печатает таблицу
A против B — визиты, отказы, глубина, время, конверсия в каждую цель. Для
отказов и конверсий считает z-тест двух долей, чтобы не принимать шум за эффект.

Токен: https://oauth.yandex.ru → создать приложение со правом «Яндекс.Метрика:
получение статистики» (metrika:read) → получить OAuth-токен аккаунта, которому
принадлежит счётчик.

    YM_TOKEN=<token> python scripts/ab_stats.py [дней, по умолчанию 30]

Пусто в выводе = параметр ab_design в счётчик не приходил: тест выключен
(AB_TEST_DESIGN=0) либо ещё не было трафика после включения.
"""
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

# Консоль Windows по умолчанию не UTF-8 — без этого русский вывод сыпется кракозябрами
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COUNTER = 110585101
STAT = "https://api-metrika.yandex.net/stat/v1/data"
MGMT = f"https://api-metrika.yandex.net/management/v1/counter/{COUNTER}/goals"

# Системный SOCKS-прокси на машине ломает http-клиенты — ходим напрямую.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str, token: str, **params) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    try:
        with _opener.open(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"API {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def ztest(s1: float, n1: float, s2: float, n2: float) -> float | None:
    """p-value двустороннего z-теста двух долей (s из n). None — мало данных."""
    if min(n1, n2) < 1 or s1 + s2 <= 0:
        return None
    p1, p2 = s1 / n1, s2 / n2
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    return math.erfc(abs(z) / math.sqrt(2))       # двусторонний


def token_from_env_file() -> str:
    """YM_TOKEN из .env в корне репозитория (.env в .gitignore, туда его и кладём)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("YM_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def main() -> None:
    token = os.getenv("YM_TOKEN", "").strip() or token_from_env_file()
    if not token:
        sys.exit("нужен YM_TOKEN: переменная окружения или строка YM_TOKEN=... в .env")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    date2 = date.today()
    date1 = date2 - timedelta(days=days)

    goals = [(g["id"], g["name"]) for g in get(MGMT, token).get("goals", [])]
    base = ["ym:s:visits", "ym:s:users", "ym:s:bounceRate",
            "ym:s:pageDepth", "ym:s:avgVisitDurationSeconds"]
    metrics = base + [f"ym:s:goal{gid}visits" for gid, _ in goals]

    d = get(STAT, token,
            ids=COUNTER,
            date1=date1.isoformat(), date2=date2.isoformat(),
            dimensions="ym:s:paramsLevel1,ym:s:paramsLevel2",
            filters="ym:s:paramsLevel1=='ab_design'",
            metrics=",".join(metrics),
            limit=100)

    arms = {}
    for row in d.get("data", []):
        variant = (row["dimensions"][1].get("name") or "?").strip()
        arms[variant] = row["metrics"]
    if not arms:
        print(f"Параметра ab_design в счётчике нет за {date1}..{date2}.\n"
              "Тест выключен (AB_TEST_DESIGN=0) или не было трафика после включения.")
        return

    a, b = arms.get("A"), arms.get("B")
    names = ["визиты", "посетители", "отказы, %", "глубина", "время, с"] + \
            [f"цель «{n}», визитов" for _, n in goals]
    print(f"Период {date1}..{date2}   счётчик {COUNTER}\n")
    print(f"{'метрика':<32}{'A':>12}{'B':>12}{'B/A':>10}")
    print("-" * 66)
    for i, label in enumerate(names):
        va = a[i] if a else 0.0
        vb = b[i] if b else 0.0
        rel = f"{(vb / va - 1) * 100:+.1f}%" if va else "—"
        print(f"{label:<32}{va:>12.1f}{vb:>12.1f}{rel:>10}")

    if not (a and b):
        print("\nЕсть данные только по одному варианту — сравнивать нечего.")
        return

    print("\nСтатистика (p < 0.05 — различие похоже на настоящее):")
    va, vb = a[0], b[0]
    p = ztest(a[2] / 100 * va, va, b[2] / 100 * vb, vb)
    print(f"  отказы:            p = {p:.3f}" if p is not None else "  отказы: мало данных")
    for k, (_gid, gname) in enumerate(goals):
        sa, sb = a[len(base) + k], b[len(base) + k]
        p = ztest(sa, va, sb, vb)
        line = f"  цель «{gname}»:"
        print(f"{line:<22} p = {p:.3f}" if p is not None else f"{line:<22} мало данных")
    print("\nПри малом трафике честный ответ обычно «различий не видно»: чтобы"
          "\nловить эффекты порядка 10% по отказам, нужны сотни визитов на вариант.")


if __name__ == "__main__":
    main()
