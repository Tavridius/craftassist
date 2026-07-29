#!/usr/bin/env python3
"""Обновить УЖЕ опубликованный гайд телом из бандла content/guides/.

Зачем: guides.init() сидит бандл insert-if-absent, чтобы редеплой не перетирал
правки админа из /dev/guides. Обратная сторона — правку в бандле существующий
гайд не подхватывает никогда. Этот скрипт закрывает пробел: перечитывает
<slug>.json + <slug>.html и вызывает тот же upsert, что и админка.

Запускать ВНУТРИ контейнера (там смонтирован volume с guides.db):

    docker exec stalzone_craft python /app/scripts/reseed_guide.py konvert-s-baksami

Без аргументов — только показывает, что в БД и что в бандле, ничего не меняя.
"""
import json
import sys

sys.path.insert(0, "/app/backend")

from app.db import guides            # noqa: E402
from app import config               # noqa: E402


def bundle(slug):
    d = config.GUIDE_SEED_DIR
    meta = json.loads((d / f"{slug}.json").read_text(encoding="utf-8"))
    html = (d / f"{slug}.html").read_text(encoding="utf-8")
    return meta, html


def main():
    guides.init()
    if len(sys.argv) < 2:
        for g in guides.list_guides(include_drafts=True):
            print(f"  {g['slug']:<30} в БД: {len(g.get('html') or '')} симв.")
        print("\nукажите slug, чтобы обновить его телом из бандла")
        return
    slug = sys.argv[1]
    cur = guides.get_guide(slug, include_drafts=True)
    meta, html = bundle(slug)
    print(f"{slug}: в БД {len(cur['html']) if cur else 0} симв. "
          f"-> из бандла {len(html)} симв.")
    if cur and cur["html"].strip() == html.strip():
        print("тела совпадают — обновлять нечего")
        return
    guides.upsert({
        "slug": slug,
        "title": meta.get("title", slug),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "cover": meta.get("cover", ""),
        "html": html,
        "created_at": meta.get("created_at"),
        "published": meta.get("published", True),
    })
    after = guides.get_guide(slug, include_drafts=True)
    print(f"обновлено, теперь в БД {len(after['html'])} симв.")


if __name__ == "__main__":
    main()
