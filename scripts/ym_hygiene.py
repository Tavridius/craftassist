"""Гигиена счётчика Я.Метрики (110585101) — разовая правка настроек через
management API. Токен берётся из YM_TOKEN в .env.

⚠️ ТЕКУЩИЙ YM_TOKEN ТОЛЬКО ЧИТАЕТ (проверено 31.07.2026): чтение счётчика,
фильтров и целей работает, а PUT/POST возвращают 403 access_denied — право
«получение статистики» записи настроек не даёт. Чтобы скрипт заработал, нужен
токен со скоупом полного доступа к Метрике. Пока его нет, обе правки ниже
делаются руками: Настройка счётчика → Фильтры.

Что делает:
  1. filter_robots 1 -> 2 — фильтрация роботов не только по строгим правилам,
     но и по поведению (в аудите: HeadlessChrome, 20 визитов, отказы 75%).
  2. Добавляет фильтр «реферер содержит metrika.yandex.ru -> исключить»:
     заходы на сайт из интерфейса Метрики — это мы сами (60 визитов от 3
     человек), встроенный фильтр «мои визиты» (uniq_id/me, уже стоит) их не
     ловит, потому что это другой браузер/сессия.

Фильтры Метрики действуют только на будущие данные, историю не переписывают.
Запуск:  python scripts/ym_hygiene.py           # показать текущее состояние
         python scripts/ym_hygiene.py --apply   # применить
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTER_ID = 110585101
API = "https://api-metrika.yandex.net/management/v1"

# системный SOCKS-прокси на машине владельца ломает исходящие запросы — идём мимо
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _token() -> str:
    env = open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace").read()
    m = re.search(r"^YM_TOKEN=(\S+)", env, re.M)
    if not m:
        sys.exit("YM_TOKEN не найден в .env")
    return m.group(1)


def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"OAuth {_token()}", "Content-Type": "application/json"})
    try:
        return json.load(_opener.open(req, timeout=30))
    except urllib.error.HTTPError as e:
        return {"__error": e.code, "__body": e.read().decode("utf-8", "replace")[:600]}


def show() -> dict:
    counter = call(f"/counter/{COUNTER_ID}").get("counter", {})
    print("счётчик:", counter.get("name"), "| filter_robots:", counter.get("filter_robots"))
    print("фильтры:")
    for f in call(f"/counter/{COUNTER_ID}/filters").get("filters", []):
        print(f"  id={f['id']} {f['attr']}/{f['type']} '{f['value']}' -> {f['action']} ({f['status']})")
    return counter


def main() -> None:
    before = show()
    if "--apply" not in sys.argv:
        print("\n(ничего не менялось — запусти с --apply)")
        return

    r = call(f"/counter/{COUNTER_ID}", "PUT", {"counter": {"filter_robots": 2}})
    print("\nfilter_robots -> 2:", "ОШИБКА " + str(r)[:300] if "__error" in r else "ок")

    r = call(f"/counter/{COUNTER_ID}/filters", "POST",
             {"filter": {"attr": "referer", "type": "contain", "value": "metrika.yandex.ru",
                         "action": "exclude", "status": "active"}})
    print("фильтр реферера:", "ОШИБКА " + str(r)[:300] if "__error" in r else "ок")

    print()
    after = show()
    # частичный PUT не должен был задеть ничего, кроме filter_robots — сверяем
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    print("\nизменившиеся поля счётчика:", ", ".join(sorted(changed)) or "нет")


if __name__ == "__main__":
    main()
