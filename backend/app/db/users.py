"""БД пользователей (SQLite): аккаунты EXBO + серверные сессии.

Вход — OAuth 2.0 authorization code через аккаунт EXBO (routers/auth.py).
Храним только идентичность (exbo id / login), токены EXBO не сохраняем.
Сессии серверные: в куке случайный токен, в БД — его sha256, поэтому утечка
файла БД не раскрывает живые сессии. Файл data/users.db живёт в docker-volume.
"""
import hashlib
import json
import logging
import secrets
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exbo_id       INTEGER UNIQUE NOT NULL,
    uuid          TEXT,
    login         TEXT NOT NULL,
    display_login TEXT,
    distributor   TEXT,
    created_at    REAL NOT NULL,
    last_login_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS profiles (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""

_EMPTY_PROFILE = {"perks": {}, "features": []}


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "users.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(_SCHEMA)
        purged = _conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (time.time(),)).rowcount
        total = _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        _conn.commit()
    logger.info("users: db ready (%d users, purged %d expired sessions)", total, purged)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def upsert_user(profile: dict) -> int:
    """Создать/обновить пользователя по ответу exbo /oauth/user, вернуть наш id."""
    now = time.time()
    with _lock:
        _conn.execute(
            """INSERT INTO users (exbo_id, uuid, login, display_login, distributor,
                                  created_at, last_login_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(exbo_id) DO UPDATE SET
                 uuid=excluded.uuid, login=excluded.login,
                 display_login=excluded.display_login, distributor=excluded.distributor,
                 last_login_at=excluded.last_login_at""",
            (profile["id"], profile.get("uuid"),
             profile.get("login") or f"user{profile['id']}",
             profile.get("display_login"), profile.get("distributor"), now, now))
        uid = _conn.execute(
            "SELECT id FROM users WHERE exbo_id=?", (profile["id"],)).fetchone()[0]
        _conn.commit()
    return uid


def create_session(user_id: int) -> str:
    """Новая сессия; наружу уходит сырой токен (в куку), в БД — только хэш."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (_hash(token), user_id, now, now + config.SESSION_TTL_DAYS * 86400))
        _conn.commit()
    return token


def user_by_session(token: str) -> dict | None:
    if not token:
        return None
    with _lock:
        row = _conn.execute(
            """SELECT u.id, u.exbo_id, u.login, u.display_login, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash=?""", (_hash(token),)).fetchone()
    if not row or row["expires_at"] < time.time():
        return None
    return {"id": row["id"], "exbo_id": row["exbo_id"], "login": row["login"],
            "display_login": row["display_login"]}


def delete_session(token: str) -> None:
    if not token:
        return
    with _lock:
        _conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
        _conn.commit()


def get_profile(user_id: int) -> dict:
    """Профиль убежища (перки/станки); пустой, если ещё не заполнялся."""
    with _lock:
        row = _conn.execute("SELECT data FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return dict(_EMPTY_PROFILE)
    try:
        return json.loads(row["data"])
    except Exception:
        logger.exception("users: broken profile json for user %s", user_id)
        return dict(_EMPTY_PROFILE)


def save_profile(user_id: int, data: dict) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO profiles (user_id, data, updated_at) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 data=excluded.data, updated_at=excluded.updated_at""",
            (user_id, json.dumps(data, ensure_ascii=False), time.time()))
        _conn.commit()


def stats() -> dict:
    with _lock:
        users_n = _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        sessions_n = _conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (time.time(),)).fetchone()[0]
    return {"users": users_n, "active_sessions": sessions_n}
