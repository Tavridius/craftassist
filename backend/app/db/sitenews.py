"""Новости САЙТА — SQLite data/sitenews.db.

Не путать с db/news.py: там патчноуты игры с форума EXBO. Здесь — то, что мы
сами пишем игроку: «починили расчёт бартера», «появился раздел сравнения».

Лента на главной гибридная: ручные посты отсюда + автособытия из уже готовых
источников (свежие гайды, промокоды, патчи игры) — колонка не пустует, даже
если руками ничего не написано. Склейка — в api.news_feed(), тут только CRUD.

kind у ручного поста всегда "post"; автособытия kind = guide/promo/patch и в
эту таблицу не пишутся (иначе пришлось бы синхронизировать удаления).
"""
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from app import config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

BODY_MAX = 600          # короткая заметка: колонка на главной, не статья
TITLE_MAX = 160

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',   -- плейн-текст, переносы строк сохраняются
    url         TEXT NOT NULL DEFAULT '',   -- внутренняя ссылка «подробнее» ('' = без ссылки)
    tag         TEXT NOT NULL DEFAULT '',   -- метка для ленты: ОБНОВЛЕНИЕ / ФИКС / РАЗДЕЛ
    pinned      INTEGER NOT NULL DEFAULT 0, -- закреплён сверху ленты
    published   INTEGER NOT NULL DEFAULT 1, -- 0 = черновик (виден только админу)
    created_at  TEXT NOT NULL,              -- YYYY-MM-DD (дата новости, МСК)
    updated_at  REAL NOT NULL               -- epoch последней правки
);
CREATE INDEX IF NOT EXISTS idx_posts_pub ON posts(published, created_at DESC);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "sitenews.db"),
                                check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    logger.info("sitenews: db ready (%d posts)", total)


def _today() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "kind": "post", "title": r["title"], "body": r["body"],
        "url": r["url"], "tag": r["tag"], "pinned": bool(r["pinned"]),
        "published": bool(r["published"]), "created_at": r["created_at"],
    }


def list_posts(include_drafts: bool = False) -> list[dict]:
    """Закреплённые сверху, дальше свежие. Публично — без черновиков."""
    q = "SELECT * FROM posts"
    if not include_drafts:
        q += " WHERE published=1"
    q += " ORDER BY pinned DESC, created_at DESC, id DESC"
    with _lock:
        rows = _conn.execute(q).fetchall()
    return [_row(r) for r in rows]


def get(pid: int) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    return _row(r) if r else None


def save(pid: int | None, data: dict) -> dict | None:
    """Создать (pid=None) или обновить пост. None — если pid не найден."""
    vals = (data["title"], data.get("body", ""), data.get("url", ""),
            data.get("tag", ""), 1 if data.get("pinned") else 0,
            1 if data.get("published", True) else 0)
    with _lock:
        if pid is None:
            cur = _conn.execute(
                """INSERT INTO posts
                     (title, body, url, tag, pinned, published, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (*vals, data.get("created_at") or _today(), time.time()))
            pid = cur.lastrowid
        else:
            cur = _conn.execute(
                """UPDATE posts SET title=?, body=?, url=?, tag=?, pinned=?,
                     published=?, created_at=?, updated_at=? WHERE id=?""",
                (*vals, data.get("created_at") or _today(), time.time(), pid))
            if not cur.rowcount:
                return None
        _conn.commit()
    return get(pid)


def delete(pid: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM posts WHERE id=?", (pid,))
        _conn.commit()
        return cur.rowcount > 0
