#!/usr/bin/env python3
"""Массовый импорт объектов интерактивной карты в map.db (черновиками).

Зачем: наполнять карту таблицей быстрее, чем кликами. Точки готовятся в
CSV/JSON (хоть в Excel), скрипт заливает их в map_objects. По умолчанию всё
ложится ЧЕРНОВИКАМИ (published=0): проверяешь в /dev/map и публикуешь руками.

CSV (разделитель ; заголовок обязателен, порядок колонок любой):
    layer;kind;category;name;x;y;description
    detail;marker;npc;Торговец в Баре;45000;21100;Основной торговец юга
kind можно не указывать (по умолчанию marker). Для area/line вместо x;y —
колонка geometry с JSON-массивом [[x,y],...]. Колонка published (1/0) —
опубликовать сразу конкретную строку.

JSON: массив объектов с теми же полями:
    [{"layer":"detail","category":"npc","name":"...","x":45000,"y":21100}]

Координаты — нативные px слоя пирамиды (как в /dev/map: клик по карте в
редакторе показывает их в панели объекта после сохранения — или снять с
существующей метки-ориентира).

Запуск ВНУТРИ контейнера (там volume с map.db):
    docker cp points.csv stalzone_craft:/tmp/points.csv
    docker cp scripts/map_import.py stalzone_craft:/tmp/map_import.py
    docker exec stalzone_craft python /tmp/map_import.py /tmp/points.csv
Локально (map.db в backend/data): python scripts/map_import.py points.csv

Флаги: --dry — показать без записи; --publish — публиковать все строки сразу.
"""
import csv
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ("/app/backend", os.path.join(_here, "backend")):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
        break

from app.db import mapobjects  # noqa: E402

# синхронно MAP_CATEGORIES в routers/api.py (не импортируем его, чтобы не
# тянуть fastapi): неизвестная категория — не ошибка, фронт нарисует «poi»
KNOWN_CATS = {"stash", "loot", "anomaly", "danger", "npc", "quest", "spawn",
              "transition", "poi"}
KINDS = {"marker", "area", "line"}
LAYERS = {"global", "detail"}


def load_rows(path: str) -> list[dict]:
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            sys.exit("JSON должен быть массивом объектов")
        return data
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def to_obj(row: dict, n: int, publish_all: bool) -> dict:
    kind = (row.get("kind") or "marker").strip()
    layer = (row.get("layer") or "detail").strip()
    if kind not in KINDS:
        sys.exit(f"строка {n}: неизвестный kind «{kind}» (есть: {', '.join(KINDS)})")
    if layer not in LAYERS:
        sys.exit(f"строка {n}: неизвестный layer «{layer}» (есть: global, detail)")
    if kind == "marker":
        try:
            geometry = [float(row["x"]), float(row["y"])]
        except (KeyError, TypeError, ValueError):
            sys.exit(f"строка {n}: метке нужны числовые x и y")
    else:
        g = row.get("geometry")
        geometry = g if isinstance(g, list) else json.loads(g or "null")
        if not isinstance(geometry, list) or len(geometry) < (3 if kind == "area" else 2):
            sys.exit(f"строка {n}: {kind} требует geometry [[x,y],...] "
                     f"минимум из {'3' if kind == 'area' else '2'} точек")
    cat = (row.get("category") or "poi").strip() if kind == "marker" else None
    pub = publish_all or str(row.get("published") or "").strip() in ("1", "true", "yes")
    return {"kind": kind, "layer": layer, "category": cat,
            "name": (row.get("name") or "").strip(),
            "description": (row.get("description") or "").strip(),
            "color": (row.get("color") or "").strip() or None,
            "geometry": geometry, "published": pub}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    publish_all = "--publish" in sys.argv
    if not args:
        sys.exit(__doc__)
    objs = [to_obj(r, i + 1, publish_all) for i, r in enumerate(load_rows(args[0]))]
    warn = sorted({o["category"] for o in objs
                   if o["category"] and o["category"] not in KNOWN_CATS})
    if warn:
        print(f"⚠ неизвестные категории (фронт покажет как «poi»): {', '.join(warn)}")
    for o in objs:
        mark = "PUB " if o["published"] else "черн"
        print(f"  [{mark}] {o['layer']}/{o['kind']}"
              f"{'/' + o['category'] if o['category'] else ''}  {o['name'] or '(без имени)'}")
    if dry:
        print(f"\n--dry: {len(objs)} объектов НЕ записано")
        return
    mapobjects.init()
    ids = [mapobjects.create(o, None) for o in objs]
    print(f"\nзаписано {len(ids)} объектов (id {ids[0]}–{ids[-1]})" if ids
          else "\nнечего записывать")
    print("проверить и опубликовать: /dev/map (черновики — пунктиром)")


if __name__ == "__main__":
    main()
