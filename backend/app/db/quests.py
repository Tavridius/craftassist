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
    faction     TEXT NOT NULL,                 -- id основной линейки (QUEST_FACTIONS)
    factions    TEXT NOT NULL DEFAULT '[]',    -- JSON [id, ...] — доп. линейки (общий/вступит.)
    kind        TEXT NOT NULL DEFAULT 'main',  -- main | side
    summary     TEXT NOT NULL DEFAULT '',      -- кратко (тултип на блоке)
    reward      TEXT NOT NULL DEFAULT '',      -- награда, простой текст
    html        TEXT NOT NULL DEFAULT '',      -- прохождение (доверенный HTML)
    parents     TEXT NOT NULL DEFAULT '[]',    -- JSON [id, ...] — «после каких»
    map_layer   TEXT NOT NULL DEFAULT '',      -- '' | global | detail
    map_points  TEXT NOT NULL DEFAULT '[]',    -- JSON [[x, y, подпись], ...]
    pos         TEXT NOT NULL DEFAULT '{}',    -- JSON {faction: [col, row]} — ручная сетка
    sort        INTEGER NOT NULL DEFAULT 0,    -- порядок веток на одном уровне (авто-раскладка)
    published   INTEGER NOT NULL DEFAULT 0,
    group_id    INTEGER,                       -- id группы (quest_groups) или NULL
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quests_pub ON quests(published, faction);

-- Группы квестов: несколько мелких квестов = один «модуль» на схеме (сворачивается)
CREATE TABLE IF NOT EXISTS quest_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    faction     TEXT NOT NULL,                 -- линейка группы
    title       TEXT NOT NULL DEFAULT '',
    pos         TEXT NOT NULL DEFAULT '{}',    -- JSON {faction: [col, row]}
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
"""


def _migrate() -> None:
    """Досоздать колонки на старых базах (factions, pos, group_id появились позже)."""
    have = {r["name"] for r in _conn.execute("PRAGMA table_info(quests)").fetchall()}
    if "factions" not in have:
        _conn.execute("ALTER TABLE quests ADD COLUMN factions TEXT NOT NULL DEFAULT '[]'")
    if "pos" not in have:
        _conn.execute("ALTER TABLE quests ADD COLUMN pos TEXT NOT NULL DEFAULT '{}'")
    if "group_id" not in have:
        _conn.execute("ALTER TABLE quests ADD COLUMN group_id INTEGER")


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
        _migrate()
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM quests").fetchone()[0]
    logger.info("quests: db ready (%d quests)", total)


def _loads(s: str, default):
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else default
    except Exception:
        return default


def _loads_map(s: str) -> dict:
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _meta(r: sqlite3.Row) -> dict:
    """Мета для блок-схемы/списков — без тела и точек карты."""
    return {
        "id": r["id"], "title": r["title"], "faction": r["faction"],
        "factions": _loads(r["factions"], []),
        "kind": r["kind"], "summary": r["summary"],
        "parents": _loads(r["parents"], []), "sort": r["sort"],
        "pos": _loads_map(r["pos"]),
        "group_id": r["group_id"],
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


def all_quest_ids() -> list[tuple[int, str]]:
    """(id, 'YYYY-MM-DD') опубликованных квестов — для sitemap.xml."""
    with _lock:
        rows = _conn.execute(
            "SELECT id, updated_at FROM quests WHERE published=1 ORDER BY id").fetchall()
    return [(r["id"],
             time.strftime("%Y-%m-%d", time.gmtime(r["updated_at"])) if r["updated_at"] else "")
            for r in rows]


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
               (title, faction, factions, kind, summary, reward, html, parents,
                map_layer, map_points, sort, published, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data["title"], data["faction"], json.dumps(data["factions"]),
             data["kind"], data["summary"],
             data["reward"], data["html"],
             json.dumps(data["parents"]),
             data["map_layer"], json.dumps(data["map_points"], ensure_ascii=False),
             data["sort"], 1 if data["published"] else 0, now, now))
        _conn.commit()
        qid = cur.lastrowid
    return get(qid, include_drafts=True)


def update(qid: int, data: dict) -> dict | None:
    """Полная замена редактируемых полей (форма шлёт объект целиком).
    Ручные позиции сетки (pos) НЕ трогаем — их правит только set_pos()."""
    with _lock:
        cur = _conn.execute(
            """UPDATE quests SET title=?, faction=?, factions=?, kind=?, summary=?,
               reward=?, html=?, parents=?, map_layer=?, map_points=?, sort=?,
               published=?, updated_at=? WHERE id=?""",
            (data["title"], data["faction"], json.dumps(data["factions"]),
             data["kind"], data["summary"],
             data["reward"], data["html"],
             json.dumps(data["parents"]),
             data["map_layer"], json.dumps(data["map_points"], ensure_ascii=False),
             data["sort"], 1 if data["published"] else 0, time.time(), qid))
        _conn.commit()
        if not cur.rowcount:
            return None
    return get(qid, include_drafts=True)


def set_parents(qid: int, parents: list[int]) -> bool:
    """Пересохранить только связи «открывается после» (рисование стрелок на карте)."""
    with _lock:
        cur = _conn.execute("UPDATE quests SET parents=?, updated_at=? WHERE id=?",
                            (json.dumps(parents), time.time(), qid))
        _conn.commit()
        return cur.rowcount > 0


def set_pos(qid: int, faction: str, col: int, row: int) -> bool:
    """Сохранить ручную позицию блока на сетке для конкретной линейки.
    Не бьёт updated_at (перетаскивание не должно менять дату для SEO)."""
    with _lock:
        r = _conn.execute("SELECT pos FROM quests WHERE id=?", (qid,)).fetchone()
        if not r:
            return False
        pos = _loads_map(r["pos"])
        pos[faction] = [col, row]
        _conn.execute("UPDATE quests SET pos=? WHERE id=?", (json.dumps(pos), qid))
        _conn.commit()
    return True


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


# ---------- группы квестов (несколько квестов = один сворачиваемый модуль) ----------

def _members(gid: int) -> list[int]:
    return [r["id"] for r in _conn.execute(
        "SELECT id FROM quests WHERE group_id=? ORDER BY sort, id", (gid,)).fetchall()]


def _group_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "faction": r["faction"], "title": r["title"],
            "pos": _loads_map(r["pos"]), "members": _members(r["id"])}


def groups_list() -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM quest_groups ORDER BY id").fetchall()
        return [_group_row(r) for r in rows]


def group_get(gid: int) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM quest_groups WHERE id=?", (gid,)).fetchone()
        return _group_row(r) if r else None


def group_exists(gid: int) -> bool:
    with _lock:
        return _conn.execute("SELECT 1 FROM quest_groups WHERE id=?", (gid,)).fetchone() is not None


def group_create(faction: str, title: str, members: list[int]) -> dict:
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO quest_groups (faction, title, pos, created_at, updated_at) VALUES (?,?,?,?,?)",
            (faction, title, "{}", now, now))
        gid = cur.lastrowid
        for mid in members:                        # квест может быть только в одной группе
            _conn.execute("UPDATE quests SET group_id=? WHERE id=?", (gid, mid))
        _conn.commit()
    return group_get(gid)


def group_update(gid: int, title: str | None = None, members: list[int] | None = None) -> dict | None:
    with _lock:
        if not _conn.execute("SELECT 1 FROM quest_groups WHERE id=?", (gid,)).fetchone():
            return None
        if title is not None:
            _conn.execute("UPDATE quest_groups SET title=?, updated_at=? WHERE id=?",
                          (title, time.time(), gid))
        if members is not None:
            _conn.execute("UPDATE quests SET group_id=NULL WHERE group_id=?", (gid,))
            for mid in members:
                _conn.execute("UPDATE quests SET group_id=? WHERE id=?", (gid, mid))
        _conn.commit()
    return group_get(gid)


def group_delete(gid: int) -> bool:
    """Разгруппировать: снять group_id с квестов и удалить саму группу."""
    with _lock:
        _conn.execute("UPDATE quests SET group_id=NULL WHERE group_id=?", (gid,))
        cur = _conn.execute("DELETE FROM quest_groups WHERE id=?", (gid,))
        _conn.commit()
        return cur.rowcount > 0


def group_set_pos(gid: int, faction: str, col: int, row: int) -> bool:
    with _lock:
        r = _conn.execute("SELECT pos FROM quest_groups WHERE id=?", (gid,)).fetchone()
        if not r:
            return False
        pos = _loads_map(r["pos"])
        pos[faction] = [col, row]
        _conn.execute("UPDATE quest_groups SET pos=? WHERE id=?", (json.dumps(pos), gid))
        _conn.commit()
    return True
