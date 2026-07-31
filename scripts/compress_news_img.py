"""Разовое сжатие уже зеркалированных картинок патчноутов + правка ссылок в БД.

Зачем: форум EXBO отдаёт баннеры и скриншоты в исходном разрешении, и зеркало
сохраняло их как есть. Замер 31.07.2026 по живому проду: страница патча
22.07 весила 47.9 МБ (34 картинки, самая большая 4.8 МБ), 15.07 — 30.8 МБ,
08.07 — 23.0 МБ. Всего 2777 файлов на 1.7 ГБ. В аудите Метрики /patches —
53.8% отказов при 10 секундах на странице, худшая мобильная страница сайта.

Что делает: каждую картинку ужимает до ширины 1280 в WebP (services/imgopt.py),
затем в news.db переписывает src в HTML патчей на новые файлы. Оригиналы по
умолчанию ОСТАЮТСЯ на диске — сначала проверь выдачу, потом освободи место
запуском с --delete-originals.

Запуск (скрипт есть в образе, БД и картинки — в томе):
    docker exec -w /app/backend stalzone_craft python /app/scripts/compress_news_img.py --dry
    docker exec -w /app/backend stalzone_craft python /app/scripts/compress_news_img.py
    docker exec -w /app/backend stalzone_craft python /app/scripts/compress_news_img.py --delete-originals
"""
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend" if os.path.isdir("/app/backend") else
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app import config                      # noqa: E402
from app.services import imgopt             # noqa: E402

SRC_EXT = (".png", ".jpg", ".jpeg", ".gif")   # .webp уже сжат; гифки — в анимированный WebP


def human(n: int) -> str:
    return f"{n / 1e6:.1f} МБ" if n >= 1e6 else f"{n / 1e3:.0f} КБ"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="только показать, что будет сделано")
    ap.add_argument("--delete-originals", action="store_true",
                    help="удалить исходники после успешной конвертации и правки БД")
    args = ap.parse_args()

    root = config.NEWS_IMG_DIR
    # уже сжатые пропускаем: скрипт можно догонять повторно, не переделывая всё
    files = sorted(p for p in root.rglob("*")
                   if p.suffix.lower() in SRC_EXT and not p.with_suffix(".webp").exists())
    print(f"картинок к обработке: {len(files)} в {root}")
    if args.dry:
        total = sum(p.stat().st_size for p in files)
        print(f"их общий вес: {human(total)}")
        print("(пробный прогон — ничего не меняем)")
        return

    was = now = 0
    converted = failed = 0
    for i, path in enumerate(files, 1):
        res = imgopt.compress_file(path)
        if not res:
            failed += 1
            continue
        _, a, b = res
        was += a
        now += b
        converted += 1
        if i % 200 == 0:
            print(f"  {i}/{len(files)}  {human(was)} -> {human(now)}")

    print(f"\nсжато: {converted}, пропущено/не вышло: {failed}")
    print(f"вес обработанных: {human(was)} -> {human(now)}"
          + (f" (в {was / now:.1f} раза меньше)" if now else ""))

    # Правим ссылки в HTML патчей. Опираемся не на список этого прогона, а на
    # факт наличия .webp на диске — тогда скрипт можно догонять после обрыва.
    # news.db — единственная база проекта без WAL, а приложение в это время из
    # неё читает: ждём блокировку, а не падаем.
    db = sqlite3.connect(config.DATA_DIR / "news.db", timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row

    def to_webp(m: re.Match) -> str:
        src = m.group(0)
        orig = root / src.split("/news-img/", 1)[1]
        webp = orig.with_suffix(imgopt.SUFFIX)
        if orig.suffix.lower() == imgopt.SUFFIX or not webp.exists():
            return src
        return f"/news-img/{webp.parent.name}/{webp.name}"

    rows = db.execute("SELECT id, html FROM patches").fetchall()
    changed = 0
    referenced: set[Path] = set()
    for r in rows:
        new = re.sub(r'/news-img/\d+/[^"\'\s>]+', to_webp, r["html"])
        if new != r["html"]:
            db.execute("UPDATE patches SET html=? WHERE id=?", (new, r["id"]))
            changed += 1
        for rel in re.findall(r'/news-img/(\d+/[^"\'\s>]+)', new):
            referenced.add(root / rel)
    db.commit()
    print(f"патчей с обновлёнными ссылками: {changed} из {len(rows)}")

    if args.delete_originals:
        # удаляем только то, что уже заменено на .webp и ни в одном патче не
        # упоминается — считаем по итоговому состоянию БД, а не по этому прогону
        freed = n = 0
        for p in root.rglob("*"):
            if (p.suffix.lower() in SRC_EXT and p not in referenced
                    and p.with_suffix(imgopt.SUFFIX).exists()):
                freed += p.stat().st_size
                p.unlink()
                n += 1
        print(f"исходники удалены ({n} шт.), освобождено {human(freed)}")
    else:
        print("исходники оставлены на диске — проверь выдачу и запусти с --delete-originals")

    db.close()


if __name__ == "__main__":
    main()
