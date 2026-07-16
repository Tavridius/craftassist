"""Квесты (блок-схемы линеек с прохождением) — SQLite data/quests.db.

Наполняется админами через DEV-редактор (routers/api.py, /api/admin/quests).
Хранилище в volume → переживает редеплой.

Линейки (faction): сталкеры/бандиты + группировки (завет/заря/долг/наёмники) —
справочник QUEST_FACTIONS в routers/api.py. Связи «открывается после» — parents
(JSON-массив id): фронт строит по ним блок-схему (уровни + стрелки), поэтому
циклы запрещены (валидация в API).

Тело `html` — доверенный HTML (пишут админы), рендерится стилем статей
(.patch-body). Точки на карте: map_layer (global|detail из /map/meta) +
map_points — JSON [[x, y, "подпись"], ...] в нативных px слоя (как db/mapobjects).
published=0 — черновик (виден только админам), 1 — виден всем на /quests.
"""
import json
import logging
import sqlite3
import threading
import time

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    faction     TEXT NOT NULL,                 -- id линейки (QUEST_FACTIONS)
    kind        TEXT NOT NULL DEFAULT 'main',  -- main | side
    summary     TEXT NOT NULL DEFAULT '',      -- кратко (тултип на блоке)
    reward      TEXT NOT NULL DEFAULT '',      -- награда, простой текст
    html        TEXT NOT NULL DEFAULT '',      -- прохождение (доверенный HTML)
    parents     TEXT NOT NULL DEFAULT '[]',    -- JSON [id, ...] — «после каких»
    map_layer   TEXT NOT NULL DEFAULT '',      -- '' | global | detail
    map_points  TEXT NOT NULL DEFAULT '[]',    -- JSON [[x, y, подпись], ...]
    sort        INTEGER NOT NULL DEFAULT 0,    -- порядок веток на одном уровне
    published   INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quests_pub ON quests(published, faction);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "quests.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM quests").fetchone()[0]
    logger.info("quests: db ready (%d quests)", total)


def _loads(s: str, default):
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else default
    except Exception:
        return default


def _meta(r: sqlite3.Row) -> dict:
    """Мета для блок-схемы/списков — без тела и точек карты."""
    return {
        "id": r["id"], "title": r["title"], "faction": r["faction"],
        "kind": r["kind"], "summary": r["summary"],
        "parents": _loads(r["parents"], []), "sort": r["sort"],
        "published": bool(r["published"]),
        "has_map": bool(r["map_layer"]) and bool(_loads(r["map_points"], [])),
    }


def _full(r: sqlite3.Row) -> dict:
    return {**_meta(r), "reward": r["reward"], "html": r["html"],
            "map_layer": r["map_layer"],
            "map_points": _loads(r["map_points"], [])}


def list_quests(include_drafts: bool = False) -> list[dict]:
    """Мета всех квестов (для схемы). Публично — только опубликованные."""
    q = "SELECT * FROM quests"
    if not include_drafts:
        q += " WHERE published=1"
    q += " ORDER BY faction, sort, id"
    with _lock:
        rows = _conn.execute(q).fetchall()
    return [_meta(r) for r in rows]


def get(qid: int, include_drafts: bool = False) -> dict | None:
    """Полный квест (прохождение + карта). Публично черновик не отдаём."""
    with _lock:
        r = _conn.execute("SELECT * FROM quests WHERE id=?", (qid,)).fetchone()
    if not r or (not include_drafts and not r["published"]):
        return None
    return _full(r)


def exists(qid: int) -> bool:
    with _lock:
        return _conn.execute("SELECT 1 FROM quests WHERE id=?", (qid,)).fetchone() is not None


def parent_map() -> dict[int, list[int]]:
    """{id: [parents]} по всей базе — для проверки циклов при сохранении."""
    with _lock:
        rows = _conn.execute("SELECT id, parents FROM quests").fetchall()
    return {r["id"]: _loads(r["parents"], []) for r in rows}


def create(data: dict) -> dict:
    now = time.time()
    with _lock:
        cur = _conn.execute(
            """INSERT INTO quests
               (title, faction, kind, summary, reward, html, parents,
                map_layer, map_points, sort, published, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data["title"], data["faction"], data["kind"], data["summary"],
             data["reward"], data["html"],
             json.dumps(data["parents"]),
             data["map_layer"], json.dumps(data["map_points"], ensure_ascii=False),
             data["sort"], 1 if data["published"] else 0, now, now))
        _conn.commit()
        qid = cur.lastrowid
    return get(qid, include_drafts=True)


def update(qid: int, data: dict) -> dict | None:
    """Полная замена редактируемых полей (форма шлёт объект целиком)."""
    with _lock:
        cur = _conn.execute(
            """UPDATE quests SET title=?, faction=?, kind=?, summary=?, reward=?,
               html=?, parents=?, map_layer=?, map_points=?, sort=?, published=?,
               updated_at=? WHERE id=?""",
            (data["title"], data["faction"], data["kind"], data["summary"],
             data["reward"], data["html"],
             json.dumps(data["parents"]),
             data["map_layer"], json.dumps(data["map_points"], ensure_ascii=False),
             data["sort"], 1 if data["published"] else 0, time.time(), qid))
        _conn.commit()
        if not cur.rowcount:
            return None
    return get(qid, include_drafts=True)


def delete(qid: int) -> bool:
    """Удалить квест и вычистить его id из parents остальных (схема не рвётся)."""
    with _lock:
        cur = _conn.execute("DELETE FROM quests WHERE id=?", (qid,))
        if cur.rowcount:
            for r in _conn.execute("SELECT id, parents FROM quests").fetchall():
                ps = _loads(r["parents"], [])
                if qid in ps:
                    _conn.execute("UPDATE quests SET parents=? WHERE id=?",
                                  (json.dumps([p for p in ps if p != qid]), r["id"]))
        _conn.commit()
        return cur.rowcount > 0
