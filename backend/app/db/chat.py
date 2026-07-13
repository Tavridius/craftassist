"""Чаты сайта (SQLite): «общий» и «баги/предложения».

Читать может любой, писать — только вошедшие через EXBO (роутер проверяет).
Храним последние 500 сообщений на комнату (старые ротируются), файл
data/chat.db живёт в том же docker-volume, что и users.db.
"""
import logging
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

ROOMS = ("general", "bugs")
MAX_LEN = 500          # максимум символов в сообщении
KEEP = 500             # сколько сообщений храним на комнату

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    room    TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    login   TEXT NOT NULL,
    text    TEXT NOT NULL,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room, id);
"""


def init() -> None:
    global _conn
    _conn = sqlite3.connect(str(config.DATA_DIR / "chat.db"), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(_SCHEMA)
        _conn.commit()
    logger.info("chat: db ready (%d messages)",
                _conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])


def post(room: str, user_id: int, login: str, text: str) -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO messages(room, user_id, login, text, ts) VALUES(?,?,?,?,?)",
            (room, user_id, login, text, time.time()))
        # ротация: держим только последние KEEP сообщений комнаты
        _conn.execute(
            """DELETE FROM messages WHERE room=? AND id NOT IN
               (SELECT id FROM messages WHERE room=? ORDER BY id DESC LIMIT ?)""",
            (room, room, KEEP))
        _conn.commit()
        return cur.lastrowid


def fetch(room: str, after: int = 0, limit: int = 100) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT id, login, text, ts FROM messages WHERE room=? AND id>? "
            "ORDER BY id DESC LIMIT ?", (room, after, limit)).fetchall()
    return [{"id": r["id"], "login": r["login"], "text": r["text"], "ts": r["ts"]}
            for r in reversed(rows)]
