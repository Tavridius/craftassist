"""Биржа артефактов (SQLite): агрегаты продаж по корзинам качество×заточка.

Снапшоты artefact_watch раскладывают продажи из истории аукциона по корзинам
(item, qlt, ptn) и часовым слотам (МСК). Пользовательские запросы читают
готовые агрегаты — внешний API на чтении не дёргается. Файл data/market.db
живёт в docker-volume и переживает рестарт.
"""
import logging
import sqlite3
import threading

from app import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS art_sales_agg (
    item TEXT NOT NULL,
    qlt  INTEGER NOT NULL,           -- качество 0-5
    ptn  INTEGER NOT NULL,           -- заточка 0-15 (0 = без заточки)
    slot TEXT NOT NULL,              -- ISO-час снапшота МСК 'YYYY-MM-DDTHH:00'
    n    INTEGER NOT NULL,           -- продаж в корзине за слот
    sum  REAL NOT NULL,              -- сумма цен за 1 шт (для средней)
    min  REAL NOT NULL,
    max  REAL NOT NULL,
    PRIMARY KEY (item, qlt, ptn, slot)
);
CREATE INDEX IF NOT EXISTS idx_art_slot ON art_sales_agg(slot);
CREATE TABLE IF NOT EXISTS item_sales (
    item TEXT NOT NULL,
    res  TEXT NOT NULL,              -- разрешение: 'h' — час, 'd' — день (роллап)
    slot TEXT NOT NULL,              -- ISO МСК 'YYYY-MM-DDTHH:00' ('d' — 'YYYY-MM-DDT00:00')
    n    INTEGER NOT NULL,           -- продано ШТУК за слот
    sum  REAL NOT NULL,              -- Σ (цена/шт × шт) — для средневзвешенной
    min  REAL NOT NULL,              -- мин/макс цена за 1 шт в слоте
    max  REAL NOT NULL,
    PRIMARY KEY (item, res, slot)
);
CREATE INDEX IF NOT EXISTS idx_item_sales_slot ON item_sales(res, slot);
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
        _conn = sqlite3.connect(str(config.DATA_DIR / "market.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
    logger.info("market: db ready (%s)", stats())


def get_meta(key: str) -> str | None:
    with _lock:
        row = _conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with _lock:
        _conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        _conn.commit()


def add_snapshot(item: str, slot: str, buckets: dict, last_ts: str | None) -> None:
    """Записать агрегаты корзин одного артефакта за слот одной транзакцией.

    buckets: {(qlt, ptn): {n, sum, min, max}}. Повторный замер в том же слоте
    (рестарт/ретрай) СКЛАДЫВАЕТСЯ с уже записанным — artefact_watch следит,
    чтобы продажи не считались дважды (граница last_ts).
    """
    with _lock:
        for (qlt, ptn), b in buckets.items():
            _conn.execute(
                """INSERT INTO art_sales_agg (item, qlt, ptn, slot, n, sum, min, max)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(item, qlt, ptn, slot) DO UPDATE SET
                     n = n + excluded.n, sum = sum + excluded.sum,
                     min = MIN(min, excluded.min), max = MAX(max, excluded.max)""",
                (item, qlt, ptn, slot, b["n"], b["sum"], b["min"], b["max"]))
        if last_ts:
            _conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                          (f"last_ts:{item}", last_ts))
        _conn.commit()


def cleanup(before_slot: str) -> int:
    """Удалить слоты старше ретенции. Возвращает число удалённых строк."""
    with _lock:
        n = _conn.execute("DELETE FROM art_sales_agg WHERE slot < ?", (before_slot,)).rowcount
        _conn.commit()
    if n:
        logger.info("market: cleaned %d rows older than %s", n, before_slot)
    return n


def window_avgs(since_slot: str, until_slot: str | None = None) -> list[dict]:
    """Средние по корзинам за окно слотов: since включительно, until исключительно."""
    q = ("SELECT item, qlt, ptn, SUM(sum)/SUM(n) AS avg, SUM(n) AS n "
         "FROM art_sales_agg WHERE slot >= ?")
    args: list = [since_slot]
    if until_slot:
        q += " AND slot < ?"
        args.append(until_slot)
    q += " GROUP BY item, qlt, ptn"
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def item_series(item: str) -> list[dict]:
    """Все слоты всех корзин артефакта (для графиков карточки), от старых к новым."""
    with _lock:
        rows = _conn.execute(
            "SELECT qlt, ptn, slot, sum/n AS avg, n FROM art_sales_agg "
            "WHERE item = ? ORDER BY slot", (item,)).fetchall()
    return [dict(r) for r in rows]


# ---------- годовая история продаж предметов (график карточки полного аука) ----------
def add_item_sales(item: str, buckets: dict) -> None:
    """buckets: {hour_slot: {n, sum, min, max}} — складывается с уже записанным
    (дедуп продаж — граница sale_ts в sales_log, сюда попадают только новые)."""
    with _lock:
        for slot, b in buckets.items():
            _conn.execute(
                """INSERT INTO item_sales (item, res, slot, n, sum, min, max)
                   VALUES (?,'h',?,?,?,?,?)
                   ON CONFLICT(item, res, slot) DO UPDATE SET
                     n = n + excluded.n, sum = sum + excluded.sum,
                     min = MIN(min, excluded.min), max = MAX(max, excluded.max)""",
                (item, slot, b["n"], b["sum"], b["min"], b["max"]))
        _conn.commit()


def item_sales_hourly(item: str, since_slot: str, until_slot: str) -> list[dict]:
    """Часовые агрегаты в окне [since; until] включительно (доступны в окне роллапа)."""
    with _lock:
        rows = _conn.execute(
            "SELECT slot AS t, n, sum/n AS avg, min, max FROM item_sales "
            "WHERE item = ? AND res = 'h' AND slot >= ? AND slot <= ? ORDER BY slot",
            (item, since_slot, until_slot)).fetchall()
    return [dict(r) for r in rows]


def item_sales_daily(item: str, since_slot: str, until_slot: str) -> list[dict]:
    """Дневные агрегаты: роллап-строки + свежие часы, сгруппированные по дню."""
    with _lock:
        rows = _conn.execute(
            "SELECT substr(slot, 1, 10) AS t, SUM(n) AS n, SUM(sum)/SUM(n) AS avg, "
            "MIN(min) AS min, MAX(max) AS max FROM item_sales "
            "WHERE item = ? AND slot >= ? AND slot <= ? "
            "GROUP BY substr(slot, 1, 10) ORDER BY t",
            (item, since_slot, until_slot)).fetchall()
    return [dict(r) for r in rows]


def item_sales_first(item: str) -> str | None:
    with _lock:
        row = _conn.execute("SELECT MIN(slot) AS s FROM item_sales WHERE item = ?",
                            (item,)).fetchone()
    return row["s"] if row else None


def rollup_item_sales(before_slot: str) -> int:
    """Часовые строки старше границы схлопнуть в дневные (res='d'). Возвращает
    число убранных часовых строк. Аддитивный upsert — безопасно при повторе."""
    with _lock:
        rows = _conn.execute(
            "SELECT item, substr(slot, 1, 10) AS day, SUM(n) AS n, SUM(sum) AS sum, "
            "MIN(min) AS min, MAX(max) AS max FROM item_sales "
            "WHERE res = 'h' AND slot < ? GROUP BY item, day", (before_slot,)).fetchall()
        for r in rows:
            _conn.execute(
                """INSERT INTO item_sales (item, res, slot, n, sum, min, max)
                   VALUES (?,'d',?,?,?,?,?)
                   ON CONFLICT(item, res, slot) DO UPDATE SET
                     n = n + excluded.n, sum = sum + excluded.sum,
                     min = MIN(min, excluded.min), max = MAX(max, excluded.max)""",
                (r["item"], r["day"] + "T00:00", r["n"], r["sum"], r["min"], r["max"]))
        n = _conn.execute("DELETE FROM item_sales WHERE res = 'h' AND slot < ?",
                          (before_slot,)).rowcount
        _conn.commit()
    if n:
        logger.info("market: rolled up %d hourly item_sales rows older than %s",
                    n, before_slot)
    return n


def cleanup_item_sales(before_slot: str) -> int:
    """Удалить агрегаты старше годовой ретенции."""
    with _lock:
        n = _conn.execute("DELETE FROM item_sales WHERE slot < ?", (before_slot,)).rowcount
        _conn.commit()
    if n:
        logger.info("market: cleaned %d item_sales rows older than %s", n, before_slot)
    return n


def item_sales_stats() -> dict:
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT item) AS items, "
            "MIN(slot) AS first_slot FROM item_sales").fetchone()
    return dict(row)


def stats() -> dict:
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT item) AS items, "
            "MIN(slot) AS first_slot, MAX(slot) AS last_slot FROM art_sales_agg").fetchone()
    return dict(row)
