#!/usr/bin/env python3
"""Выгрузка из API Яндекс.Вебмастера (сайт stalzone-helper.ru).

Метрика показывает только фразы, которые УЖЕ привели трафик. Вебмастер отдаёт
весь объём показов, средние позиции и CTR — то есть отвечает на вопрос «где мы
уже в выдаче, но нас не кликают». Это дополнение к scripts/ym_dump.py.

    python scripts/wm_dump.py queries --from 2026-08-04 --to 2026-09-02
    python scripts/wm_dump.py queries --limit 300 --order CLICKS
    python scripts/wm_dump.py pages
    python scripts/wm_dump.py indexing

Токен: YANDEX_TOKEN в окружении или в .env в корне. Выпуск/перевыпуск —
oauth.yandex.ru, приложение должно иметь право «Яндекс.Вебмастер».
Заголовок именно `OAuth`, не `Bearer` — Bearer Вебмастер не принимает.
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
API = "https://api.webmaster.yandex.net/v4"
HOST_ID = "https:stalzone-helper.ru:443"

# системный SOCKS-прокси на машине владельца ломает исходящие запросы — идём мимо
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

INDICATORS = ["TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION", "AVG_CLICK_POSITION"]


def token() -> str:
    t = os.getenv("YANDEX_TOKEN")
    if t:
        return t.strip()
    try:
        env = open(os.path.join(ROOT, ".env"), encoding="utf-8").read()
    except OSError:
        sys.exit("нет YANDEX_TOKEN в окружении и нет .env в корне")
    m = re.search(r"^YANDEX_TOKEN=(\S+)", env, re.M)
    if not m:
        sys.exit("в .env нет строки YANDEX_TOKEN=...")
    return m.group(1).strip("\"'")


def api(path: str, tok: str, **params) -> dict:
    qs = urllib.parse.urlencode(params, doseq=True)
    url = f"{API}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {tok}"})
    try:
        return json.load(_opener.open(req, timeout=60))
    except urllib.error.HTTPError as e:
        body = e.read(600).decode("utf-8", "replace")
        sys.exit(f"[{e.code}] {url}\n{body}")


def user_id(tok: str) -> int:
    return api("/user/", tok)["user_id"]


def _host(tok: str) -> str:
    return f"/user/{user_id(tok)}/hosts/{urllib.parse.quote(HOST_ID, safe='')}"


def _num(x):
    return 0 if x is None else x


def queries(tok: str, d_from: str, d_to: str, limit: int, order: str) -> None:
    d = api(f"{_host(tok)}/search-queries/popular/", tok,
            order_by=order, query_indicator=INDICATORS,
            date_from=d_from, date_to=d_to, limit=min(limit, 500))
    rows = []
    for q in d.get("queries", []):
        i = q.get("indicators", {})
        rows.append((q.get("query_text", ""), _num(i.get("TOTAL_SHOWS")),
                     _num(i.get("TOTAL_CLICKS")), i.get("AVG_SHOW_POSITION")))
    print(f"### Поисковые запросы  [{d_from} .. {d_to}]  всего в выборке: {d.get('count')}")
    print(f"{'запрос':52} {'показы':>8} {'клики':>6} {'CTR':>6} {'ср.поз':>7}")
    for t, s, c, p in rows:
        ctr = f"{100 * c / s:.1f}%" if s else "—"
        pos = f"{p:.1f}" if p else "—"
        print(f"{t[:52]:52} {s:>8.0f} {c:>6.0f} {ctr:>6} {pos:>7}")
    ts, tc = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"\n= ИТОГО по выдаче: показов {ts:.0f}, кликов {tc:.0f}, "
          f"CTR {(100 * tc / ts if ts else 0):.2f}%")


def pages(tok: str, limit: int) -> None:
    """Страницы, реально попавшие в поиск. Отчёта с показами по URL в v4 нет —
    есть только выборка проиндексированных (`search-urls/popular/` = 404)."""
    h = _host(tok)
    d = api(f"{h}/search-urls/in-search/samples/", tok, limit=min(limit, 100))
    print(f"### Страницы в поиске (всего {d.get('count')})")
    for u in d.get("samples", []):
        print(f"  {u.get('url','')[:78]:78} {u.get('last_access','')[:10]}")


def indexing(tok: str) -> None:
    h = _host(tok)
    s = api(f"{h}/summary/", tok)
    print("### Сводка по сайту")
    print(f"  ИКС                                {s.get('sqi')}")
    print(f"  страниц в поиске                   {s.get('searchable_pages_count')}")
    print(f"  исключено                          {s.get('excluded_pages_count')}")
    print(f"  проблемы                           {s.get('site_problems')}")
    for sm in api(f"{h}/sitemaps/", tok).get("sitemaps", []):
        print(f"  sitemap {sm.get('sitemap_url')}")
        print(f"    адресов {sm.get('urls_count')}, ошибок {sm.get('errors_count')}, "
              f"обход {sm.get('last_access_date','')[:10]}")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit("срезы: queries | pages | indexing\n"
                 "флаги: --from ГГГГ-ММ-ДД --to ГГГГ-ММ-ДД --limit N "
                 "--order TOTAL_SHOWS|TOTAL_CLICKS")
    slice_ = args[0]

    def flag(name, default):
        return args[args.index(name) + 1] if name in args else default

    d_to = flag("--to", str(date.today() - timedelta(days=1)))
    d_from = flag("--from", str(date.fromisoformat(d_to) - timedelta(days=29)))
    limit = int(flag("--limit", "100"))
    order = flag("--order", "TOTAL_SHOWS")

    tok = token()
    if slice_ == "queries":
        queries(tok, d_from, d_to, limit, order)
    elif slice_ == "pages":
        pages(tok, limit)
    elif slice_ == "indexing":
        indexing(tok)
    else:
        sys.exit(f"неизвестный срез: {slice_}")


if __name__ == "__main__":
    main()
