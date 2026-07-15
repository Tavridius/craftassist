"""Объекты интерактивной карты (метки, области, линии) — SQLite data/map.db.

Наполняется админами через DEV-редактор (routers/api.py, /api/map/objects).
Координаты — нативные пиксели соответствующего слоя пирамиды (global/detail),
как их проецирует Leaflet (map.project(latlng, max_zoom)); фронт разворачивает
обратно через unproject. Геометрия хранится JSON-строкой:
  marker    → [x, y]
  area/line → [[x, y], ...]
published=0 — черновик (виден только админам), 1 — виден всем на /map.
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
CREATE TABLE IF NOT EXISTS map_objects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,               -- marker | area | line
    layer       TEXT NOT NULL,               -- global | detail
    category    TEXT,                         -- id категории (для меток)
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    color       TEXT,                          -- hex-обводка/заливка (области/линии)
    geometry    TEXT NOT NULL,                 -- JSON, см. модуль-докстринг
    published   INTEGER NOT NULL DEFAULT 0,
    created_by  INTEGER,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_map_layer ON map_objects(layer, published);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "map.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM map_objects").fetchone()[0]
    logger.info("map: db ready (%d objects)", total)


def _row(r: sqlite3.Row) -> dict:
    try:
        geom = json.loads(r["geometry"])
    except Exception:
        geom = None
    return {
        "id": r["id"], "kind": r["kind"], "layer": r["layer"],
        "category": r["category"], "name": r["name"], "description": r["description"],
        "color": r["color"], "geometry": geom, "published": bool(r["published"]),
        "updated_at": r["updated_at"],
    }


def list_objects(layer: str | None = None, include_drafts: bool = False) -> list[dict]:
    """Объекты слоя (или всех). include_drafts=True — с черновиками (для админа)."""
    q = "SELECT * FROM map_objects"
    cond: list[str] = []
    args: list = []
    if layer:
        cond.append("layer=?")
        args.append(layer)
    if not include_drafts:
        cond.append("published=1")
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY id"
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    return [_row(r) for r in rows]


def get(oid: int) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM map_objects WHERE id=?", (oid,)).fetchone()
    return _row(r) if r else None


def create(obj: dict, user_id: int | None) -> int:
    now = time.time()
    with _lock:
        cur = _conn.execute(
            """INSERT INTO map_objects
               (kind, layer, category, name, description, color, geometry,
                published, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (obj["kind"], obj["layer"], obj.get("category"), obj.get("name", ""),
             obj.get("description", ""), obj.get("color"),
             json.dumps(obj["geometry"], ensure_ascii=False),
             1 if obj.get("published") else 0, user_id, now, now))
        _conn.commit()
        return cur.lastrowid


_FIELDS = {"category", "name", "description", "color", "published", "geometry"}


def update(oid: int, fields: dict) -> bool:
    """Частичное обновление: применяются только известные поля из fields."""
    sets: list[str] = []
    args: list = []
    for k, v in fields.items():
        if k not in _FIELDS:
            continue
        if k == "geometry":
            v = json.dumps(v, ensure_ascii=False)
        elif k == "published":
            v = 1 if v else 0
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        return False
    sets.append("updated_at=?")
    args.append(time.time())
    args.append(oid)
    with _lock:
        cur = _conn.execute(
            f"UPDATE map_objects SET {', '.join(sets)} WHERE id=?", args)
        _conn.commit()
        return cur.rowcount > 0


def delete(oid: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM map_objects WHERE id=?", (oid,))
        _conn.commit()
        return cur.rowcount > 0


def stats() -> dict:
    with _lock:
        total = _conn.execute("SELECT COUNT(*) FROM map_objects").fetchone()[0]
        pub = _conn.execute(
            "SELECT COUNT(*) FROM map_objects WHERE published=1").fetchone()[0]
    return {"objects": total, "published": pub}
