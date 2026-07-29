"""Биржа артефактов (SQLite): агрегаты продаж по корзинам качество×заточка.

Снапшоты artefact_watch раскладывают продажи из истории аукциона по корзинам
(item, qlt, ptn) и часовым слотам (МСК). Пользовательские запросы читают
готовые агрегаты — внешний API на чтении не дёргается. Файл data/market.db
живёт в docker-volume и переживает рестарт.
"""
import logging
import sqlite3
import statistics
import threading

from app import config

logger = logging.getLogger(__name__)

# Заточки котируем ТОЛЬКО корзинами +0/+5/+10/+15 (решение юзера): 0-4 → +0,
# 5-9 → +5, 10-14 → +10, 15 → +15. Новые снапшоты пишутся уже корзинами;
# старые строки могут лежать с сырой заточкой — чтение агрегирует по корзине.
PTN_SQL = "min(ptn / 5 * 5, 15)"

# Цена окна — средневзвешенная ПО МЕДИАНАМ СЛОТОВ, а не по суммам цен.
# Почему не SUM(sum)/SUM(n): одна завышенная сделка внутри слота тянула среднюю
# слота, а слот из единственной сделки тянул всё окно. Медиана слота к разовой
# сделке не двигается, а слот с n=1 весит 1 против сотен. Отсечка выбросов при
# записи (artefact_watch.finalize_buckets) — вторая линия, независимая.
AVG_SQL = "SUM(COALESCE(med, sum / n) * n) / SUM(n)"


def ptn_bucket(ptn: int) -> int:
    """Сырая заточка 0-15 → корзина котировки (0/5/10/15)."""
    return min(ptn // 5 * 5, 15)


_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS art_sales_agg (
    item TEXT NOT NULL,
    qlt  INTEGER NOT NULL,           -- качество 0-5
    ptn  INTEGER NOT NULL,           -- корзина заточки 0/5/10/15 (см. ptn_bucket)
    slot TEXT NOT NULL,              -- ISO-час снапшота МСК 'YYYY-MM-DDTHH:00'
    n    INTEGER NOT NULL,           -- продаж в корзине за слот
    sum  REAL NOT NULL,              -- сумма цен за 1 шт (для средней)
    min  REAL NOT NULL,
    max  REAL NOT NULL,
    med  REAL,                       -- медиана цен слота: устойчива к разовой сделке
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
        _migrate()
        _conn.commit()
    logger.info("market: db ready (%s)", stats())


def _migrate() -> None:
    """Донакатить столбцы на уже существующую БД (CREATE TABLE IF NOT EXISTS их не добавит)."""
    cols = {r["name"] for r in _conn.execute("PRAGMA table_info(art_sales_agg)")}
    if "med" not in cols:
        _conn.execute("ALTER TABLE art_sales_agg ADD COLUMN med REAL")
        # У старых слотов медианы нет и восстановить её нечем — берём среднюю
        # слота. Это не хуже прежнего поведения: агрегаты и раньше жили на ней.
        _conn.execute("UPDATE art_sales_agg SET med = sum / n WHERE med IS NULL AND n > 0")
        logger.info("market: added art_sales_agg.med, backfilled from slot averages")


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

    buckets: {(qlt, ptn): {n, sum, min, max, med}}. Повторный замер в том же
    слоте (рестарт/ретрай) СКЛАДЫВАЕТСЯ с уже записанным — artefact_watch следит,
    чтобы продажи не считались дважды (граница last_ts). Медианы двух замеров
    точно не сложить, поэтому смешиваем по весу n — путь редкий (только ретрай).
    """
    with _lock:
        for (qlt, ptn), b in buckets.items():
            _conn.execute(
                """INSERT INTO art_sales_agg (item, qlt, ptn, slot, n, sum, min, max, med)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(item, qlt, ptn, slot) DO UPDATE SET
                     n = n + excluded.n, sum = sum + excluded.sum,
                     min = MIN(min, excluded.min), max = MAX(max, excluded.max),
                     med = (COALESCE(med, sum / n) * n + excluded.med * excluded.n)
                           / (n + excluded.n)""",
                (item, qlt, ptn, slot, b["n"], b["sum"], b["min"], b["max"], b["med"]))
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
    q = (f"SELECT item, qlt, {PTN_SQL} AS ptn, {AVG_SQL} AS avg, SUM(n) AS n "
         "FROM art_sales_agg WHERE slot >= ?")
    args: list = [since_slot]
    if until_slot:
        q += " AND slot < ?"
        args.append(until_slot)
    q += f" GROUP BY item, qlt, {PTN_SQL}"
    with _lock:
        rows = _conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def item_bucket_avgs(item: str, since_slot: str) -> dict:
    """Средние по корзинам (qlt, ptn) ОДНОГО артефакта за окно: {(qlt, ptn): {avg, n}}.

    База котировки для ДЕВ-сканера: у артефакта живых продаж в конкретной
    корзине за последние часы обычно мало, а накопленных за неделю — достаточно.
    """
    with _lock:
        rows = _conn.execute(
            f"SELECT qlt, {PTN_SQL} AS ptn, {AVG_SQL} AS avg, SUM(n) AS n "
            f"FROM art_sales_agg WHERE item = ? AND slot >= ? GROUP BY qlt, {PTN_SQL}",
            (item, since_slot)).fetchall()
    return {(r["qlt"], r["ptn"]): {"avg": r["avg"], "n": r["n"]} for r in rows}


def bucket_refs(item: str, since_slot: str) -> dict:
    """Опорная цена корзин артефакта по истории: {(qlt, ptn): цена}.

    Медиана медиан слотов — от неё artefact_watch отсекает выбросы. Считается в
    Python, а не в SQL: медианы в SQLite нет, а выборка тут крошечная (корзины
    одного артефакта за ART_REF_DAYS). Корзины, где слотов меньше
    ART_REF_MIN_SLOTS, не возвращаем — на одном-двух слотах опора сама может
    оказаться выбросом, тогда лучше резервный механизм по минимуму снапшота.
    """
    with _lock:
        rows = _conn.execute(
            f"SELECT qlt, {PTN_SQL} AS ptn, COALESCE(med, sum / n) AS med "
            "FROM art_sales_agg WHERE item = ? AND slot >= ? AND n > 0",
            (item, since_slot)).fetchall()
    per: dict = {}
    for r in rows:
        per.setdefault((r["qlt"], r["ptn"]), []).append(r["med"])
    return {k: statistics.median(v) for k, v in per.items()
            if len(v) >= config.ART_REF_MIN_SLOTS}


def item_series(item: str) -> list[dict]:
    """Все слоты всех корзин артефакта (для графиков карточки), от старых к новым."""
    with _lock:
        rows = _conn.execute(
            f"SELECT qlt, {PTN_SQL} AS ptn, slot, {AVG_SQL} AS avg, SUM(n) AS n "
            f"FROM art_sales_agg WHERE item = ? GROUP BY qlt, {PTN_SQL}, slot "
            "ORDER BY slot", (item,)).fetchall()
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
            # item_sales — другая таблица (обороты полного аука), медианы слотов
            # там нет: n считает ШТУКИ, средневзвешенная по ним и нужна.
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
