"""Гайды (авторские статьи) — SQLite data/guides.db.

Наполняется админами через DEV-редактор (routers/api.py, /api/admin/guides).
Хранилище в volume → переживает редеплой. Бандл content/guides/*.json+html
сидится в БД при старте (insert-if-absent: правки админа не перетираются).

Тело `html` — доверенный HTML (пишут админы), рендерится тем же стилем, что и
патчи (класс `.patch-body` на фронте). Картинки гайдов — статикой:
  бандловые    → frontend/guide-img/  → /guide-img/...
  загруженные  → DATA_DIR/guide_uploads → /guide-uploads/...
published=0 — черновик (виден только в админке), 1 — на /guides и в sitemap.
"""
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guides (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',   -- JSON-массив строк
    cover       TEXT NOT NULL DEFAULT '',
    html        TEXT NOT NULL DEFAULT '',
    published   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,                 -- YYYY-MM-DD (дата гайда)
    updated_at  REAL NOT NULL                  -- epoch последней правки
);
CREATE INDEX IF NOT EXISTS idx_guides_pub ON guides(published, created_at DESC);
"""

_META_FIELDS = ("slug", "title", "description", "tags", "cover", "created_at",
                "updated_at", "published")


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "guides.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    n = _seed_bundled()
    with _lock:
        total = _conn.execute("SELECT COUNT(*) FROM guides").fetchone()[0]
    logger.info("guides: db ready (%d guides, %d seeded)", total, n)


def _seed_bundled() -> int:
    """Залить бандловые гайды из content/guides/, не трогая уже существующие slug."""
    d = config.GUIDE_SEED_DIR
    if not d.is_dir():
        return 0
    seeded = 0
    for meta_path in sorted(d.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            slug = meta.get("slug") or meta_path.stem
            with _lock:
                exists = _conn.execute(
                    "SELECT 1 FROM guides WHERE slug=?", (slug,)).fetchone()
            if exists:
                continue
            body = meta_path.with_suffix(".html")
            html = body.read_text(encoding="utf-8") if body.exists() else ""
            upsert({
                "slug": slug,
                "title": meta.get("title", slug),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
                "cover": meta.get("cover", ""),
                "html": html,
                "created_at": meta.get("created_at", _today()),
                "published": meta.get("published", True),
            })
            seeded += 1
        except Exception:
            logger.exception("guides: bad seed %s", meta_path.name)
    return seeded


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _iso_date(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")


def _meta(r: sqlite3.Row) -> dict:
    try:
        tags = json.loads(r["tags"])
    except Exception:
        tags = []
    return {
        "slug": r["slug"], "title": r["title"], "description": r["description"],
        "tags": tags, "cover": r["cover"], "created_at": r["created_at"],
        "updated_at": _iso_date(r["updated_at"]), "published": bool(r["published"]),
    }


def _full(r: sqlite3.Row) -> dict:
    return {**_meta(r), "html": r["html"]}


def list_guides(include_drafts: bool = False) -> list[dict]:
    """Список гайдов без тела, свежие сверху. Публично — только опубликованные."""
    q = "SELECT * FROM guides"
    if not include_drafts:
        q += " WHERE published=1"
    q += " ORDER BY created_at DESC, slug DESC"
    with _lock:
        rows = _conn.execute(q).fetchall()
    return [_meta(r) for r in rows]


def get_guide(slug: str, include_drafts: bool = False) -> dict | None:
    """Полный гайд (с html). Публично черновик не отдаём (None)."""
    with _lock:
        r = _conn.execute("SELECT * FROM guides WHERE slug=?", (slug,)).fetchone()
    if not r or (not include_drafts and not r["published"]):
        return None
    return _full(r)


def exists(slug: str) -> bool:
    """Опубликованный гайд с таким slug есть (для валидации комментариев)."""
    with _lock:
        return _conn.execute("SELECT 1 FROM guides WHERE slug=? AND published=1",
                             (slug,)).fetchone() is not None


def has(slug: str) -> bool:
    """Гайд с таким slug есть вообще (включая черновики) — для админки."""
    with _lock:
        return _conn.execute("SELECT 1 FROM guides WHERE slug=?",
                             (slug,)).fetchone() is not None


def all_slugs() -> list[tuple[str, str]]:
    """(slug, дата) опубликованных гайдов — для sitemap."""
    with _lock:
        rows = _conn.execute(
            "SELECT slug, created_at FROM guides WHERE published=1 "
            "ORDER BY created_at DESC").fetchall()
    return [(r["slug"], r["created_at"]) for r in rows]


def upsert(data: dict) -> dict:
    """Создать или заменить гайд по slug. Возвращает сохранённый (полный)."""
    slug = data["slug"]
    tags = json.dumps(data.get("tags") or [], ensure_ascii=False)
    with _lock:
        _conn.execute(
            """INSERT INTO guides
                 (slug, title, description, tags, cover, html, published,
                  created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 tags=excluded.tags, cover=excluded.cover, html=excluded.html,
                 published=excluded.published, created_at=excluded.created_at,
                 updated_at=excluded.updated_at""",
            (slug, data.get("title", slug), data.get("description", ""), tags,
             data.get("cover", ""), data.get("html", ""),
             1 if data.get("published", True) else 0,
             data.get("created_at") or _today(), time.time()))
        _conn.commit()
    return get_guide(slug, include_drafts=True)


def delete(slug: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM guides WHERE slug=?", (slug,))
        _conn.commit()
        return cur.rowcount > 0
