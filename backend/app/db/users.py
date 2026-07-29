"""БД пользователей (SQLite): аккаунты + серверные сессии.

Два способа входа (routers/auth.py):
  • локальный  — email + пароль (регистрация на сайте);
  • EXBO OAuth — вход через игровой аккаунт (создаётся автоматически, без формы).
У локального аккаунта exbo_id пуст, у EXBO-аккаунта пуст password_hash.

Пароли храним как pbkdf2-хэш (stdlib, без внешних зависимостей). Токены EXBO
пользователя НЕ сохраняем — после получения профиля выбрасываем.
Сессии серверные: в куке случайный токен, в БД — его sha256, поэтому утечка
файла БД не раскрывает живые сессии. Файл data/users.db живёт в docker-volume.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# Итоговая схема (после миграции). exbo_id теперь МОЖЕТ быть NULL (локальные аккаунты).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exbo_id       INTEGER UNIQUE,
    uuid          TEXT,
    login         TEXT NOT NULL,
    display_login TEXT,
    distributor   TEXT,
    email         TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0,
    password_hash TEXT,
    consent_at    REAL,
    created_at    REAL NOT NULL,
    last_login_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
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
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,          -- verify | reset
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_tokens_user ON email_tokens(user_id);
"""

_EMPTY_PROFILE = {"perks": {}, "features": []}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(ValueError):
    """Ошибка регистрации/входа с текстом для пользователя."""


# ---------- инициализация + миграция ----------

def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "users.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        # своя коллация: встроенный NOCASE сворачивает только ASCII, а ники кириллические
        _conn.create_collation("UNOCASE", _ucmp)
        _conn.execute("PRAGMA journal_mode=WAL")
        _migrate(_conn)
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(_SCHEMA)
        # consent_at добавлен позже (152-ФЗ: фиксируем момент согласия на обработку
        # ПДн). CREATE TABLE IF NOT EXISTS не добавляет колонку к существующей БД —
        # доклеиваем идемпотентно.
        if "consent_at" not in {r[1] for r in
                                _conn.execute("PRAGMA table_info(users)").fetchall()}:
            _conn.execute("ALTER TABLE users ADD COLUMN consent_at REAL")
        purged = _conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (time.time(),)).rowcount
        _conn.execute("DELETE FROM email_tokens WHERE expires_at < ?", (time.time(),))
        total = _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        _conn.commit()
    logger.info("users: db ready (%d users, purged %d expired sessions)", total, purged)


def _migrate(conn: sqlite3.Connection) -> None:
    """Старая схема имела exbo_id NOT NULL и не знала про email/пароль.
    Локальные аккаунты не могут вставиться при NOT NULL на exbo_id, поэтому таблицу
    перестраиваем (id сохраняются → сессии/профили остаются валидны)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if not cols:
        return  # таблицы ещё нет — создастся из _SCHEMA как новая
    if "password_hash" in cols:
        return  # уже мигрировано
    logger.info("users: migrating schema (add email/password, exbo_id nullable)")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("""
            CREATE TABLE users_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                exbo_id       INTEGER UNIQUE,
                uuid          TEXT,
                login         TEXT NOT NULL,
                display_login TEXT,
                distributor   TEXT,
                email         TEXT,
                email_verified INTEGER NOT NULL DEFAULT 0,
                password_hash TEXT,
                created_at    REAL NOT NULL,
                last_login_at REAL NOT NULL
            )""")
        conn.execute("""
            INSERT INTO users_new (id, exbo_id, uuid, login, display_login,
                                   distributor, created_at, last_login_at)
            SELECT id, exbo_id, uuid, login, display_login,
                   distributor, created_at, last_login_at FROM users""")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        logger.exception("users: migration failed")
        raise


# ---------- хэши ----------

def _ucmp(a: str, b: str) -> int:
    """Юникод-регистронезависимое сравнение для коллации UNOCASE (ники)."""
    a, b = a.casefold(), b.casefold()
    return (a > b) - (a < b)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, *, iterations: int = 200_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


# ---------- аккаунты EXBO ----------

def upsert_user(profile: dict) -> tuple[int, bool]:
    """Создать/обновить пользователя по ответу exbo /oauth/user.
    Возвращает (наш id, created?) — created=True если аккаунт только что заведён."""
    now = time.time()
    with _lock:
        existed = _conn.execute(
            "SELECT id FROM users WHERE exbo_id=?", (profile["id"],)).fetchone()
        _conn.execute(
            """INSERT INTO users (exbo_id, uuid, login, display_login, distributor,
                                  consent_at, created_at, last_login_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(exbo_id) DO UPDATE SET
                 uuid=excluded.uuid, login=excluded.login,
                 display_login=excluded.display_login, distributor=excluded.distributor,
                 last_login_at=excluded.last_login_at""",
            (profile["id"], profile.get("uuid"),
             profile.get("login") or f"user{profile['id']}",
             profile.get("display_login"), profile.get("distributor"), now, now, now))
        uid = _conn.execute(
            "SELECT id FROM users WHERE exbo_id=?", (profile["id"],)).fetchone()[0]
        _conn.commit()
    return uid, existed is None


# ---------- локальные аккаунты (email + пароль) ----------

def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def create_local_user(email: str, password: str, login: str) -> int:
    """Регистрация по email+паролю. Бросает AuthError с текстом для пользователя."""
    email = _norm_email(email)
    login = (login or "").strip()
    if not _EMAIL_RE.match(email):
        raise AuthError("Некорректный email")
    if len(password) < config.PASSWORD_MIN_LEN:
        raise AuthError(f"Пароль короче {config.PASSWORD_MIN_LEN} символов")
    if not (2 <= len(login) <= 24):
        raise AuthError("Ник должен быть от 2 до 24 символов")
    now = time.time()
    pwhash = hash_password(password)
    with _lock:
        if _conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AuthError("Этот email уже зарегистрирован")
        if _conn.execute("SELECT 1 FROM users WHERE login=? COLLATE UNOCASE",
                         (login,)).fetchone():
            raise AuthError("Этот ник уже занят")
        cur = _conn.execute(
            """INSERT INTO users (login, display_login, email, email_verified,
                                  password_hash, consent_at, created_at, last_login_at)
               VALUES (?,?,?,0,?,?,?,?)""",
            (login, login, email, pwhash, now, now, now))
        _conn.commit()
        return cur.lastrowid


def authenticate_local(ident: str, password: str) -> dict | None:
    """Вход по email ИЛИ нику + пароль. None — если не совпало."""
    ident = (ident or "").strip()
    if not ident or not password:
        return None
    with _lock:
        row = _conn.execute(
            """SELECT id, exbo_id, login, display_login, email, email_verified, password_hash
               FROM users WHERE email=? OR login=? COLLATE UNOCASE
               ORDER BY (email=?) DESC LIMIT 1""",
            (_norm_email(ident), ident, _norm_email(ident))).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    with _lock:
        _conn.execute("UPDATE users SET last_login_at=? WHERE id=?",
                      (time.time(), row["id"]))
        _conn.commit()
    return _pub(row)


def set_password(user_id: int, password: str) -> None:
    if len(password) < config.PASSWORD_MIN_LEN:
        raise AuthError(f"Пароль короче {config.PASSWORD_MIN_LEN} символов")
    with _lock:
        _conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                      (hash_password(password), user_id))
        _conn.commit()


def mark_email_verified(user_id: int) -> None:
    with _lock:
        _conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
        _conn.commit()


def user_by_email(email: str) -> dict | None:
    with _lock:
        row = _conn.execute(
            """SELECT id, exbo_id, login, display_login, email, email_verified
               FROM users WHERE email=?""", (_norm_email(email),)).fetchone()
    return _pub(row) if row else None


def _pub(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "exbo_id": row["exbo_id"], "login": row["login"],
            "display_login": row["display_login"], "email": row["email"],
            "email_verified": bool(row["email_verified"])}


# ---------- сессии ----------

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
            """SELECT u.id, u.exbo_id, u.login, u.display_login, u.email,
                      u.email_verified, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash=?""", (_hash(token),)).fetchone()
    if not row or row["expires_at"] < time.time():
        return None
    return _pub(row)


def delete_session(token: str) -> None:
    if not token:
        return
    with _lock:
        _conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
        _conn.commit()


# ---------- токены email (verify / reset) ----------

def create_email_token(user_id: int, kind: str) -> str:
    """Одноразовый токен для ссылки в письме (kind = verify | reset)."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        # один активный токен на пользователя+тип
        _conn.execute("DELETE FROM email_tokens WHERE user_id=? AND kind=?", (user_id, kind))
        _conn.execute(
            "INSERT INTO email_tokens (token_hash, user_id, kind, created_at, expires_at) "
            "VALUES (?,?,?,?,?)",
            (_hash(token), user_id, kind, now,
             now + config.EMAIL_TOKEN_TTL_HOURS * 3600))
        _conn.commit()
    return token


def consume_email_token(token: str, kind: str) -> int | None:
    """Проверить и погасить токен. Возвращает user_id или None."""
    if not token:
        return None
    th = _hash(token)
    with _lock:
        row = _conn.execute(
            "SELECT user_id, expires_at FROM email_tokens WHERE token_hash=? AND kind=?",
            (th, kind)).fetchone()
        if not row:
            return None
        _conn.execute("DELETE FROM email_tokens WHERE token_hash=?", (th,))
        _conn.commit()
    if row["expires_at"] < time.time():
        return None
    return row["user_id"]


# ---------- профиль убежища ----------

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
