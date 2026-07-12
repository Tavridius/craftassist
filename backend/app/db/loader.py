"""Загрузчик игровой БД из репозитория EXBO-Studio/stalzone-database.

Скачивает репо одним zip-архивом и раскладывает локально:
  data/listing.json          — индекс предметов
  data/hideout_recipes.json  — рецепты верстака
  data/items/**              — json-файлы предметов (описания, как в игре)
  data/icons/**              — PNG-иконки (зеркалим к себе)

Скачиваем только если файлов ещё нет (или force=True). В продакшене обновлять
раз в сутки (cron / фоновая задача).
"""
import io
import logging
import shutil
import zipfile

import httpx

from app import config

logger = logging.getLogger(__name__)

_JSON_FILES = ("listing.json", "hideout_recipes.json")


def is_present() -> bool:
    return (all((config.DATA_DIR / f).exists() for f in _JSON_FILES)
            and config.ICONS_DIR.exists() and config.ITEMS_DIR.exists())


def ensure_data(force: bool = False) -> None:
    """Гарантирует наличие локальной БД. Скачивает zip и раскладывает при необходимости."""
    if is_present() and not force:
        logger.info("Game DB already present at %s", config.DATA_DIR)
        return

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading game DB zip: %s", config.DB_REPO_ZIP)

    with httpx.stream("GET", config.DB_REPO_ZIP, follow_redirects=True,
                      timeout=120.0, trust_env=False) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_bytes(chunk_size=1 << 16):
            buf.write(chunk)
    buf.seek(0)
    logger.info("Downloaded %.1f MB, extracting...", buf.getbuffer().nbytes / 1e6)

    lang = config.DB_LANG
    counts = {"icons": 0, "items": 0}
    trees = {  # zip-префикс -> (куда извлекать, счётчик)
        f"{lang}/icons/": (config.ICONS_DIR, "icons"),
        f"{lang}/items/": (config.ITEMS_DIR, "items"),
    }

    for target_dir, _ in trees.values():
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(buf) as zf:
        # верхняя папка вида "stalzone-database-main/"
        root = zf.namelist()[0].split("/")[0]

        for name in _JSON_FILES:
            member = f"{root}/{lang}/{name}"
            with zf.open(member) as src, open(config.DATA_DIR / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            logger.info("Extracted %s", name)

        for member in zf.namelist():
            if member.endswith("/"):
                continue
            for prefix, (target_dir, key) in trees.items():
                marker = f"{root}/{prefix}"
                if member.startswith(marker):
                    rel = member[len(marker):]  # напр. other/qyvk.png | misc/404p.json
                    target = target_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    counts[key] += 1
                    break

    logger.info("Extracted %d icons, %d item files", counts["icons"], counts["items"])
