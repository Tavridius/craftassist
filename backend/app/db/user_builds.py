"""Сборки игроков (SQLite): общий пул /sborki.

Публикуют только вошедшие (роутер проверяет), читают все. Храним состав
сборки — хранилище и слоты {item, m, ptn, bx}; статы и цена считаются при
выдаче по живым ценам (services/builds.evaluate), иначе цена в карточке
протухала бы через неделю. «Анонимно» прячет автора только в выдаче:
user_id остаётся, чтобы автор мог удалить сборку, а админ — найти спамера.
Файл data/user_builds.db живёт в том же docker-volume, что и users.db.
"""
import json
import logging
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

TITLE_MAX = 60         # символов в названии сборки
DAY_LIMIT = 10         # публикаций на пользователя за сутки

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    author    TEXT NOT NULL,
    anonymous INTEGER NOT NULL DEFAULT 0,
    title     TEXT NOT NULL,
    container TEXT NOT NULL,
    slots     TEXT NOT NULL,           -- json [{item, m, ptn, bx}]
    signature TEXT NOT NULL,           -- состав без порядка слотов: дубли одного автора
    ts        REAL NOT NULL,
    deleted   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_builds_user ON builds(user_id, ts);
CREATE TABLE IF NOT EXISTS likes (
    build_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    PRIMARY KEY (build_id, user_id)
);
"""


def init() -> None:
    global _conn
    _conn = sqlite3.connect(str(config.DATA_DIR / "user_builds.db"), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(_SCHEMA)
        _conn.commit()
    logger.info("user_builds: db ready (%d builds)",
                _conn.execute("SELECT COUNT(*) FROM builds WHERE deleted=0").fetchone()[0])


def signature(container: str, slots: list[dict]) -> str:
    parts = sorted(f"{s['item']}:{s['m']:.3f}:{s['ptn']}:{','.join(sorted(s.get('bx') or []))}"
                   for s in slots)
    return container + "|" + ";".join(parts)


def add(user_id: int, author: str, anonymous: bool, title: str,
        container: str, slots: list[dict]) -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO builds(user_id, author, anonymous, title, container, slots, signature, ts)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (user_id, author, int(anonymous), title, container,
             json.dumps(slots, ensure_ascii=False), signature(container, slots), time.time()))
        _conn.commit()
        return cur.lastrowid


def published_today(user_id: int) -> int:
    with _lock:
        return _conn.execute(
            "SELECT COUNT(*) FROM builds WHERE user_id=? AND ts>?",
            (user_id, time.time() - 86400)).fetchone()[0]


def duplicate_of(user_id: int, sig: str) -> int | None:
    with _lock:
        r = _conn.execute(
            "SELECT id FROM builds WHERE user_id=? AND signature=? AND deleted=0",
            (user_id, sig)).fetchone()
    return r["id"] if r else None


def _row(r: sqlite3.Row, likes: int) -> dict:
    return {"id": r["id"], "user_id": r["user_id"],
            "author": None if r["anonymous"] else r["author"],
            "title": r["title"], "container": r["container"],
            "slots": json.loads(r["slots"]), "ts": r["ts"], "likes": likes}


def all_builds() -> list[dict]:
    """Весь живой пул с числом лайков. Пул — сотни строк, фильтры считает
    сервис по живым ценам, поэтому выборка целиком, без SQL-фильтров."""
    with _lock:
        rows = _conn.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM likes l WHERE l.build_id=b.id) AS n"
            " FROM builds b WHERE b.deleted=0 ORDER BY b.id DESC").fetchall()
    return [_row(r, r["n"]) for r in rows]


def get(bid: int) -> dict | None:
    with _lock:
        r = _conn.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM likes l WHERE l.build_id=b.id) AS n"
            " FROM builds b WHERE b.id=? AND b.deleted=0", (bid,)).fetchone()
    return _row(r, r["n"]) if r else None


def delete(bid: int) -> bool:
    with _lock:
        cur = _conn.execute("UPDATE builds SET deleted=1 WHERE id=? AND deleted=0", (bid,))
        _conn.commit()
        return cur.rowcount > 0


def liked_by(user_id: int) -> set[int]:
    with _lock:
        return {r[0] for r in _conn.execute(
            "SELECT build_id FROM likes WHERE user_id=?", (user_id,))}


def toggle_like(bid: int, user_id: int) -> tuple[bool, int]:
    """(лайк стоит после переключения, всего лайков)."""
    with _lock:
        had = _conn.execute("SELECT 1 FROM likes WHERE build_id=? AND user_id=?",
                            (bid, user_id)).fetchone()
        if had:
            _conn.execute("DELETE FROM likes WHERE build_id=? AND user_id=?", (bid, user_id))
        else:
            _conn.execute("INSERT INTO likes(build_id, user_id) VALUES(?,?)", (bid, user_id))
        _conn.commit()
        n = _conn.execute("SELECT COUNT(*) FROM likes WHERE build_id=?", (bid,)).fetchone()[0]
    return (not had, n)
