#!/usr/bin/env python3
"""Выгрузка маркеров карт stalzone.wiki из RSC-payload страниц (Next.js).

Страница /ru/maps/<slug> содержит все маркеры инлайном в self.__next_f.push
чанках. Склеиваем чанки, находим объект с "marker_groups" балансным парсером,
сохраняем <slug>.json в scratchpad.
"""
import json
import os
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.dirname(os.path.abspath(__file__))
_o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_o.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")]

SLUGS = ["south-zone", "north-zone", "wild-north", "lyubech", "graveyard", "labyrinth"]


def fetch(slug):
    with _o.open(f"https://stalzone.wiki/ru/maps/{slug}", timeout=60) as r:
        return r.read().decode("utf-8")


def rsc_text(html):
    """Склеить строковые аргументы self.__next_f.push([1,"..."]) с JS-unescape."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    return "".join(json.loads(c) for c in chunks)


def find_map_object(text):
    """Найти в тексте JSON-объект, содержащий "marker_groups" и "tiles"."""
    i = text.find('"marker_groups"')
    if i < 0:
        return None
    # откатываемся к началу объекта карты: ближайшая '{' с балансом до i
    start = None
    depth = 0
    for j in range(i, -1, -1):
        ch = text[j]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                start = j
                # проверим, что это объект карты (в нём есть tiles до marker_groups)
                head = text[j:i]
                if '"tiles"' in head or '"settings"' in head or len(head) < 4000:
                    # поднимаемся выше, пока не захватим tiles
                    if '"tiles"' not in head:
                        depth = 1  # продолжаем искать внешнюю {
                        continue
                break
            depth -= 1
    if start is None:
        return None
    # вперёд с балансом до закрытия
    depth = 0
    in_str = False
    esc = False
    for k in range(start, len(text)):
        ch = text[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:k + 1])
    return None


for slug in SLUGS:
    try:
        html = fetch(slug)
    except Exception as e:
        print(f"{slug}: FETCH FAIL {e}")
        continue
    obj = find_map_object(rsc_text(html))
    if not obj:
        print(f"{slug}: маркеры не найдены")
        continue
    with open(os.path.join(OUT, f"wiki_{slug}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    st = obj.get("settings") or obj.get("tiles") or {}
    n = sum(len(t.get("markers") or [])
            for g in obj.get("marker_groups", []) for t in g.get("marker_types", []))
    print(f"{slug}: маркеров {n}; ключи: {sorted(obj.keys())[:8]}")
