"""Заготовки постов для Telegram-канала (SQLite data/tg_posts.db, DEV /dev/tgposts).

Тексты пишутся в репозитории — backend/content/tg_posts.json — и при старте
досеиваются в базу: новые посты добавляются, у известных обновляются тексты.
Админ на сайте только копирует текст и скрывает использованные: флаг hidden
живёт в базе (volume) и пересев его не трогает.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

BUNDLE = Path(__file__).resolve().parents[2] / "content" / "tg_posts.json"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    slug      TEXT PRIMARY KEY,
    sort      INTEGER NOT NULL DEFAULT 0,
    rubric    TEXT NOT NULL DEFAULT '',
    title     TEXT NOT NULL,
    planned   TEXT NOT NULL DEFAULT '',   -- когда публиковать: дата или «по поводу»
    link      TEXT NOT NULL DEFAULT '',   -- какая ссылка на сайт в посте (для контроля частоты)
    note      TEXT NOT NULL DEFAULT '',   -- подсказка админу: что проверить перед публикацией
    text      TEXT NOT NULL,
    hidden    INTEGER NOT NULL DEFAULT 0,
    hidden_at REAL
);
"""


def init() -> None:
    global _conn
    _conn = sqlite3.connect(str(config.DATA_DIR / "tg_posts.db"), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(_SCHEMA)
        _conn.commit()
    seed()


def seed() -> int:
    """Досев из бандла: новые — добавить, известные — обновить тексты, hidden не трогать."""
    try:
        items = json.loads(BUNDLE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("tg_posts: bundle not loaded: %s", e)
        return 0
    with _lock:
        for i, p in enumerate(items):
            _conn.execute(
                """INSERT INTO posts(slug, sort, rubric, title, planned, link, note, text)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(slug) DO UPDATE SET sort=excluded.sort, rubric=excluded.rubric,
                     title=excluded.title, planned=excluded.planned, link=excluded.link,
                     note=excluded.note, text=excluded.text""",
                (p["slug"], i, p.get("rubric", ""), p["title"], p.get("planned", ""),
                 p.get("link", ""), p.get("note", ""), p["text"]))
        _conn.commit()
    logger.info("tg_posts: %d posts in bundle", len(items))
    return len(items)


def list_all() -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM posts ORDER BY hidden, sort").fetchall()
    return [dict(r) for r in rows]


def set_hidden(slug: str, hidden: bool) -> bool:
    with _lock:
        cur = _conn.execute("UPDATE posts SET hidden=?, hidden_at=? WHERE slug=?",
                            (int(hidden), time.time() if hidden else None, slug))
        _conn.commit()
        return cur.rowcount > 0
