"""Операции (PvE-режим): история сессий и агрегаты меты снаряжения (SQLite).

Воркер services/operations_watch.py тянет проведённые забеги из
GET /{region}/operations/sessions и складывает их сюда: сырую сессию (для ленты
истории и разбора состава) в ops_session и по строке на участника с ЕГО
снаряжением/статами в ops_participant (денормализованно — с tier/duration/map
сессии, чтобы агрегаты меты считались одним GROUP BY без джойна).

Пользовательские запросы (страница /operations, модуль на главной) читают готовые
агрегаты — внешний API на чтении не дёргается. Файл data/operations.db живёт в
docker-volume и переживает рестарт.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from app import config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))  # у Москвы нет переходов на летнее время

# Три этапа сложности (границы — config, верхняя ВКЛючительно).
TIER_LOW, TIER_MID, TIER_HIGH = 0, 1, 2
TIER_KEYS = ("low", "mid", "high")


def week_start(now: datetime | None = None) -> datetime:
    """Начало текущей меты-недели (последний сброс) в МСК.

    Сброс — в день недели OPS_WEEK_RESET_DOW (0=Пн … 2=Ср) в час
    OPS_WEEK_RESET_HOUR. До часа сброса в сам день сброса неделя ещё прошлая.
    """
    now = now or datetime.now(MSK)
    anchor = now.replace(hour=config.OPS_WEEK_RESET_HOUR, minute=0, second=0, microsecond=0)
    days_back = (now.weekday() - config.OPS_WEEK_RESET_DOW) % 7
    reset = anchor - timedelta(days=days_back)
    if reset > now:                 # день сброса, но час ещё не наступил → прошлая неделя
        reset -= timedelta(days=7)
    return reset


def week_start_ts(now: datetime | None = None) -> int:
    """Начало меты-недели как epoch-сек (граница окна агрегатов меты)."""
    return int(week_start(now).timestamp())


def tier_of(difficulty: int) -> int:
    """Сложность забега → этап (0 низкий / 1 средний / 2 высокий)."""
    d = int(difficulty or 0)
    if d <= config.OPS_TIER_LOW_MAX:
        return TIER_LOW
    if d <= config.OPS_TIER_MID_MAX:
        return TIER_MID
    return TIER_HIGH


def tier_bounds() -> list[dict]:
    """Описание этапов для фронта: ключ, подпись диапазона, границы."""
    lo, mid = config.OPS_TIER_LOW_MAX, config.OPS_TIER_MID_MAX
    return [
        {"tier": TIER_LOW, "key": "low", "label": f"0–{lo}", "min": 0, "max": lo},
        {"tier": TIER_MID, "key": "mid", "label": f"{lo + 1}–{mid}", "min": lo + 1, "max": mid},
        {"tier": TIER_HIGH, "key": "high", "label": f"{mid + 1}+", "min": mid + 1, "max": None},
    ]


_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_session (
    id       INTEGER PRIMARY KEY,       -- id сессии из API (естественный дедуп)
    ts       INTEGER NOT NULL,          -- время финиша, epoch-сек (для ленты и ретенции)
    end_time TEXT,                      -- ISO финиша (как отдал API)
    map      TEXT,
    difficulty INTEGER NOT NULL,
    tier     INTEGER NOT NULL,          -- 0/1/2 (см. tier_of)
    duration REAL,                      -- sessionDurationSeconds
    reward   INTEGER,                   -- difficultyReward
    n        INTEGER NOT NULL,          -- участников
    parts    TEXT NOT NULL              -- JSON-состав с снаряжением (для карточки сессии)
);
CREATE INDEX IF NOT EXISTS idx_ops_sess_ts   ON ops_session(ts);
CREATE INDEX IF NOT EXISTS idx_ops_sess_tier ON ops_session(tier, ts);
CREATE INDEX IF NOT EXISTS idx_ops_sess_map  ON ops_session(map, ts);

CREATE TABLE IF NOT EXISTS ops_participant (
    session_id INTEGER NOT NULL,
    ts         INTEGER NOT NULL,        -- = ts сессии (окно меты/ретенция без джойна)
    tier       INTEGER NOT NULL,
    map        TEXT,
    difficulty INTEGER NOT NULL,
    duration   REAL,
    username   TEXT,
    armor_item TEXT,
    armor_level INTEGER,
    armor_class TEXT,
    prim_item  TEXT,
    prim_level INTEGER,
    sec_item   TEXT,
    sec_level  INTEGER,
    deaths     INTEGER,
    mob_kills  INTEGER,
    dmg_dealt  REAL,
    dmg_recv   REAL
);
CREATE INDEX IF NOT EXISTS idx_ops_part_ts    ON ops_participant(ts);
CREATE INDEX IF NOT EXISTS idx_ops_part_tier  ON ops_participant(tier, ts);
CREATE INDEX IF NOT EXISTS idx_ops_part_class ON ops_participant(armor_class, tier, ts);
CREATE INDEX IF NOT EXISTS idx_ops_part_user  ON ops_participant(username);
CREATE INDEX IF NOT EXISTS idx_ops_part_sess  ON ops_participant(session_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "operations.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    logger.info("operations: db ready (%s)", stats())


def get_meta(key: str) -> str | None:
    with _lock:
        row = _conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with _lock:
        _conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        _conn.commit()


def add_sessions(sessions: list[dict]) -> int:
    """Записать новые сессии (дедуп по id). Возвращает число реально добавленных.

    sessions: элементы уже нормализованы воркером в {id, ts, end_time, map,
    difficulty, tier, duration, reward, n, parts:[...]}. Участники разворачиваются
    в ops_participant только для НОВОЙ сессии (иначе задвоятся при повторном опросе).
    """
    added = 0
    with _lock:
        for s in sessions:
            cur = _conn.execute(
                """INSERT OR IGNORE INTO ops_session
                   (id, ts, end_time, map, difficulty, tier, duration, reward, n, parts)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (s["id"], s["ts"], s.get("end_time"), s.get("map"), s["difficulty"],
                 s["tier"], s.get("duration"), s.get("reward"), s["n"],
                 json.dumps(s["parts"], ensure_ascii=False)))
            if cur.rowcount == 0:      # уже была — участников не трогаем
                continue
            added += 1
            for p in s["parts"]:
                _conn.execute(
                    """INSERT INTO ops_participant
                       (session_id, ts, tier, map, difficulty, duration, username,
                        armor_item, armor_level, armor_class, prim_item, prim_level,
                        sec_item, sec_level, deaths, mob_kills, dmg_dealt, dmg_recv)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (s["id"], s["ts"], s["tier"], s.get("map"), s["difficulty"],
                     s.get("duration"), p.get("username"),
                     p.get("armor_item"), p.get("armor_level"), p.get("armor_class"),
                     p.get("prim_item"), p.get("prim_level"),
                     p.get("sec_item"), p.get("sec_level"),
                     p.get("deaths"), p.get("mob_kills"),
                     p.get("dmg_dealt"), p.get("dmg_recv")))
        _conn.commit()
    return added


def purge_incomplete() -> int:
    """Удалить сессии без снаряжения (API отдаёт свежий забег с пустым составом,
    а снаряжение проставляет через пару минут). Такие сессии переберутся заново
    уже полными при следующем опросе. Возвращает число удалённых.

    «Без снаряжения» = ни у одного участника нет armor_item (в JSON состава нет
    подстроки '"armor_item": "…"' со значением)."""
    with _lock:
        ids = [r["id"] for r in _conn.execute(
            'SELECT id FROM ops_session WHERE parts NOT LIKE \'%"armor_item": "%\'').fetchall()]
        if ids:
            marks = ",".join("?" * len(ids))
            _conn.execute(f"DELETE FROM ops_participant WHERE session_id IN ({marks})", ids)
            _conn.execute(f"DELETE FROM ops_session WHERE id IN ({marks})", ids)
            _conn.commit()
    if ids:
        logger.info("operations: purged %d sessions without gear (will refetch)", len(ids))
    return len(ids)


def cleanup(before_ts: int) -> int:
    """Удалить сессии и участников старше ретенции. Возвращает удалённых сессий."""
    with _lock:
        n = _conn.execute("DELETE FROM ops_session WHERE ts < ?", (before_ts,)).rowcount
        _conn.execute("DELETE FROM ops_participant WHERE ts < ?", (before_ts,))
        _conn.commit()
    if n:
        logger.info("operations: cleaned %d sessions older than ts=%d", n, before_ts)
    return n


# ---------- чтение: лента истории ----------
def recent_sessions(tier: int | None = None, map_: str | None = None,
                    limit: int = 40, offset: int = 0) -> list[dict]:
    q = ("SELECT id, ts, end_time, map, difficulty, tier, duration, reward, n, parts "
         "FROM ops_session WHERE 1=1")
    args: list = []
    if tier is not None:
        q += " AND tier = ?"
        args.append(tier)
    if map_:
        q += " AND map = ?"
        args.append(map_)
    q += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["parts"] = json.loads(d.pop("parts") or "[]")
        out.append(d)
    return out


def session_count(tier: int | None = None, map_: str | None = None) -> int:
    q = "SELECT COUNT(*) AS c FROM ops_session WHERE 1=1"
    args: list = []
    if tier is not None:
        q += " AND tier = ?"
        args.append(tier)
    if map_:
        q += " AND map = ?"
        args.append(map_)
    with _lock:
        return _conn.execute(q, args).fetchone()["c"]


def maps() -> list[str]:
    with _lock:
        rows = _conn.execute(
            "SELECT map, COUNT(*) c FROM ops_session WHERE map IS NOT NULL "
            "GROUP BY map ORDER BY c DESC").fetchall()
    return [r["map"] for r in rows]


def player_sessions(username: str, limit: int = 40) -> list[dict]:
    """Сессии, где участвовал игрок (регистр не важен)."""
    with _lock:
        rows = _conn.execute(
            "SELECT s.id, s.ts, s.end_time, s.map, s.difficulty, s.tier, s.duration, "
            "s.reward, s.n, s.parts FROM ops_session s "
            "JOIN ops_participant p ON p.session_id = s.id "
            "WHERE p.username = ? COLLATE NOCASE "
            "ORDER BY s.ts DESC LIMIT ?", (username, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["parts"] = json.loads(d.pop("parts") or "[]")
        out.append(d)
    return out


# ---------- чтение: мета снаряжения ----------
def _tier_clause(tier: int | None, since_ts: int, args: list) -> str:
    args.append(since_ts)
    c = "ts >= ?"
    if tier is not None:
        c += " AND tier = ?"
        args.append(tier)
    return c


def fastest_combos(tier: int, since_ts: int, min_sample: int,
                   limit: int = 12) -> list[dict]:
    """Комбо броня+основное оружие на этапе, отсортированные по среднему времени
    прохождения (быстрые первыми). Только комбо с выборкой ≥ min_sample."""
    args: list = []
    clause = _tier_clause(tier, since_ts, args)
    args.append(min_sample)
    args.append(limit)
    with _lock:
        rows = _conn.execute(
            f"""SELECT armor_class, armor_item, prim_item,
                       COUNT(*) uses, AVG(duration) avg_dur, MIN(duration) min_dur,
                       AVG(armor_level) armor_lvl, AVG(prim_level) prim_lvl,
                       AVG(deaths) avg_deaths
                FROM ops_participant
                WHERE {clause} AND armor_item != '' AND prim_item != '' AND duration > 0
                GROUP BY armor_item, prim_item
                HAVING uses >= ?
                ORDER BY avg_dur ASC LIMIT ?""", args).fetchall()
    return [dict(r) for r in rows]


def class_meta(tier: int | None, since_ts: int, min_sample: int) -> list[dict]:
    """Мета по классам брони: для каждого armor_class — самая ходовая броня,
    топ основного оружия и число забегов. Классы — по числу забегов (популярные
    первыми). Используется модулем на главной (в ротации по классам)."""
    a1: list = []
    clause1 = _tier_clause(tier, since_ts, a1)
    with _lock:
        armor = _conn.execute(
            f"""SELECT armor_class, armor_item, COUNT(*) uses,
                       AVG(duration) avg_dur, AVG(armor_level) avg_lvl
                FROM ops_participant
                WHERE {clause1} AND armor_class != '' AND armor_item != ''
                GROUP BY armor_class, armor_item""", a1).fetchall()
        a2: list = []
        clause2 = _tier_clause(tier, since_ts, a2)
        weap = _conn.execute(
            f"""SELECT armor_class, prim_item, COUNT(*) uses,
                       AVG(duration) avg_dur, AVG(prim_level) avg_lvl
                FROM ops_participant
                WHERE {clause2} AND armor_class != '' AND prim_item != ''
                GROUP BY armor_class, prim_item""", a2).fetchall()

    classes: dict[str, dict] = {}
    for r in armor:
        c = classes.setdefault(r["armor_class"],
                               {"armor_class": r["armor_class"], "sessions": 0,
                                "armors": [], "weapons": []})
        c["sessions"] += r["uses"]
        c["armors"].append(dict(r))
    for r in weap:
        c = classes.get(r["armor_class"])
        if c:
            c["weapons"].append(dict(r))

    out = []
    for c in classes.values():
        if c["sessions"] < min_sample:
            continue
        c["armors"].sort(key=lambda x: -x["uses"])
        c["weapons"].sort(key=lambda x: -x["uses"])
        c["armors"] = c["armors"][:3]
        c["weapons"] = c["weapons"][:3]
        out.append(c)
    out.sort(key=lambda x: -x["sessions"])
    return out


def tier_summary(since_ts: int) -> dict:
    """Число забегов и медиана-ориентир (среднее) времени по этапам — для шапки."""
    with _lock:
        rows = _conn.execute(
            "SELECT tier, COUNT(*) n, AVG(duration) avg_dur, AVG(difficulty) avg_diff "
            "FROM ops_session WHERE ts >= ? GROUP BY tier", (since_ts,)).fetchall()
    return {r["tier"]: dict(r) for r in rows}


def stats() -> dict:
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS sessions, MIN(ts) AS first_ts, MAX(ts) AS last_ts "
            "FROM ops_session").fetchone()
        parts = _conn.execute("SELECT COUNT(*) AS c FROM ops_participant").fetchone()["c"]
    d = dict(row)
    d["participants"] = parts
    return d
