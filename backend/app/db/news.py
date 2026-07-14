"""Патчноуты игры + комментарии пользователей (SQLite data/news.db).

Патчи инжестятся из форума EXBO (services/patch_watch), HTML уже санитизирован
и с локальными картинками. Комментарии — универсальные: привязка по page_key
("patch:{id}", позже "guide:{slug}", "item:{id}"), читают все, пишут — вошедшие.
"""
import logging
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

COMMENT_MAX_LEN = 2000

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patches (
    id          INTEGER PRIMARY KEY,   -- id темы на форуме EXBO
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,         -- ISO из форума (дата патча)
    html        TEXT NOT NULL,         -- санитизированный контент, картинки локальные
    anons       TEXT NOT NULL,         -- плейн-текст анонс для списка/меты
    source_url  TEXT NOT NULL,
    last_posted TEXT,                  -- lastPostedAt форума (маркер правок)
    fetched_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patches_created ON patches(created_at DESC);

CREATE TABLE IF NOT EXISTS comments (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    page_key TEXT NOT NULL,
    user_id  INTEGER NOT NULL,
    login    TEXT NOT NULL,
    text     TEXT NOT NULL,
    ts       REAL NOT NULL,
    deleted  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_comments_page ON comments(page_key, id);
"""


def init() -> None:
    global _conn
    _conn = sqlite3.connect(str(config.DATA_DIR / "news.db"), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(_SCHEMA)
        _conn.commit()
    logger.info("news: db ready (%d patches, %d comments)",
                _conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0],
                _conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0])


# ---------- патчи ----------

def upsert_patch(pid: int, title: str, created_at: str, html: str, anons: str,
                 source_url: str, last_posted: str | None) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO patches(id, title, created_at, html, anons, source_url,
                                   last_posted, fetched_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                 created_at=excluded.created_at, html=excluded.html,
                 anons=excluded.anons, source_url=excluded.source_url,
                 last_posted=excluded.last_posted, fetched_at=excluded.fetched_at""",
            (pid, title, created_at, html, anons, source_url, last_posted, time.time()))
        _conn.commit()


def patch_meta(pid: int) -> dict | None:
    """Лёгкая запись без html (для решения «надо ли переинжестить»)."""
    with _lock:
        r = _conn.execute("SELECT id, title, created_at, anons, last_posted "
                          "FROM patches WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def get_patch(pid: int) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM patches WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def list_patches(offset: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    with _lock:
        total = _conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]
        rows = _conn.execute(
            "SELECT id, title, created_at, anons FROM patches "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [dict(r) for r in rows], total


def latest_patch() -> dict | None:
    rows, _ = list_patches(0, 1)
    return rows[0] if rows else None


def patch_count() -> int:
    with _lock:
        return _conn.execute("SELECT COUNT(*) FROM patches").fetchone()[0]


def all_patch_ids() -> list[tuple[int, str]]:
    """(id, created_at) всех патчей — для sitemap."""
    with _lock:
        rows = _conn.execute(
            "SELECT id, created_at FROM patches ORDER BY created_at DESC").fetchall()
    return [(r["id"], r["created_at"]) for r in rows]


# ---------- комментарии ----------

def add_comment(page_key: str, user_id: int, login: str, text: str) -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO comments(page_key, user_id, login, text, ts) VALUES(?,?,?,?,?)",
            (page_key, user_id, login, text, time.time()))
        _conn.commit()
        return cur.lastrowid


def list_comments(page_key: str, after: int = 0, limit: int = 200) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT id, user_id, login, text, ts FROM comments "
            "WHERE page_key=? AND id>? AND deleted=0 ORDER BY id LIMIT ?",
            (page_key, after, limit)).fetchall()
    return [dict(r) for r in rows]


def delete_comment(cid: int, user_id: int, is_admin: bool) -> bool:
    """Мягкое удаление: своё — всегда, чужое — только админ."""
    with _lock:
        r = _conn.execute("SELECT user_id FROM comments WHERE id=? AND deleted=0",
                          (cid,)).fetchone()
        if not r or (r["user_id"] != user_id and not is_admin):
            return False
        _conn.execute("UPDATE comments SET deleted=1 WHERE id=?", (cid,))
        _conn.commit()
        return True
