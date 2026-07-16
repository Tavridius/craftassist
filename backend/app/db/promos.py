"""Промокоды игры — SQLite data/promos.db.

Наполняются админом через DEV-редактор (/dev/promo, API /api/admin/promos).
Показываются модулем на главной и на индексируемой странице /promo.

expires_at — 'YYYY-MM-DDTHH:MM' по МСК, минута истечения ('' = бессрочный).
API нормализует дату без времени в T23:59 — «весь день включительно».
Истёкшие коды удаляются лениво при каждом чтении списка (purge по времени МСК,
формат единый → сравнение строк корректно) — отдельный планировщик не нужен,
наружу протухший код не уходит.

is_ref — реферальный промокод владельца сайта: всегда один (сохранение нового
реферального снимает флаг с прежнего), в выдаче списка идёт первым — под него
заложено место сверху и на главной, и на /promo.
"""
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from app import config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS promos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    code        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image       TEXT NOT NULL DEFAULT '',
    expires_at  TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DDTHH:MM МСК; '' = бессрочный
    is_ref      INTEGER NOT NULL DEFAULT 0, -- реферальный (единственный, первым в списке)
    created_at  TEXT NOT NULL,              -- YYYY-MM-DD (дата добавления)
    updated_at  REAL NOT NULL               -- epoch последней правки
);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "promos.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM promos").fetchone()[0]
    logger.info("promos: db ready (%d promos)", total)


def _today() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "title": r["title"], "code": r["code"],
        "description": r["description"], "image": r["image"],
        "expires_at": r["expires_at"], "is_ref": bool(r["is_ref"]),
        "created_at": r["created_at"],
    }


def _purge_expired_locked() -> None:
    """Удалить истёкшие коды (минута истечения уже прошла по МСК)."""
    now = datetime.now(MSK).strftime("%Y-%m-%dT%H:%M")
    cur = _conn.execute(
        "DELETE FROM promos WHERE expires_at != '' AND expires_at < ?", (now,))
    if cur.rowcount:
        _conn.commit()
        logger.info("promos: purged %d expired", cur.rowcount)


def list_promos() -> list[dict]:
    """Активные промокоды: реферальный первым, дальше свежие сверху."""
    with _lock:
        _purge_expired_locked()
        rows = _conn.execute(
            "SELECT * FROM promos ORDER BY is_ref DESC, id DESC").fetchall()
    return [_row(r) for r in rows]


def get(pid: int) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM promos WHERE id=?", (pid,)).fetchone()
    return _row(r) if r else None


def save(pid: int | None, data: dict) -> dict | None:
    """Создать (pid=None) или обновить промокод. Реферальный — единственный:
    флаг с остальных снимается. None — если pid не найден."""
    is_ref = 1 if data.get("is_ref") else 0
    with _lock:
        if pid is None:
            cur = _conn.execute(
                """INSERT INTO promos
                     (title, code, description, image, expires_at, is_ref,
                      created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (data["title"], data["code"], data.get("description", ""),
                 data.get("image", ""), data.get("expires_at", ""), is_ref,
                 _today(), time.time()))
            pid = cur.lastrowid
        else:
            cur = _conn.execute(
                """UPDATE promos SET title=?, code=?, description=?, image=?,
                     expires_at=?, is_ref=?, updated_at=? WHERE id=?""",
                (data["title"], data["code"], data.get("description", ""),
                 data.get("image", ""), data.get("expires_at", ""), is_ref,
                 time.time(), pid))
            if not cur.rowcount:
                return None
        if is_ref:
            _conn.execute("UPDATE promos SET is_ref=0 WHERE id != ?", (pid,))
        _conn.commit()
    return get(pid)


def delete(pid: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM promos WHERE id=?", (pid,))
        _conn.commit()
        return cur.rowcount > 0
