#!/usr/bin/env python3
"""Разовая чистка накопленных пиков в истории биржи артефактов.

Зачем отдельно от фикса: отсечка в artefact_watch работает только для НОВЫХ
снапшотов, а у уже записанных слотов медианы не было (столбец med появился
миграцией и заполнен средней слота). Поэтому старые выбросы в графиках и в
недельных средних висят до конца ретенции (ART_KEEP_DAYS).

Критерий тот же, что у живой отсечки: слот выбивается из устоявшейся цены
корзины больше чем в ART_SPIKE_FACTOR раз И не подтверждён объёмом
(n < ART_SHIFT_MIN_SALES). Опора — медиана слотовых цен корзины.

    python scripts/clean_art_spikes.py                 # только показать (dry-run)
    python scripts/clean_art_spikes.py --apply         # убрать найденные слоты
    python scripts/clean_art_spikes.py --restore       # вернуть всё обратно

Слоты не удаляются, а переносятся в art_sales_spikes — историю цен затирать
безвозвратно нельзя, а критерий могли и не угадать. --restore возвращает.
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config                      # noqa: E402
from app.db import market                   # noqa: E402
from app.db.index import db as idx          # noqa: E402


def find_spikes(conn):
    """[(item, qlt, ptn, slot, price, ref, n)] — слоты-выбросы, не подтверждённые объёмом."""
    rows = conn.execute(
        f"SELECT item, qlt, {market.PTN_SQL} AS ptn, slot, "
        "COALESCE(med, sum / n) AS price, n "
        "FROM art_sales_agg WHERE n > 0").fetchall()
    per: dict = {}
    for r in rows:
        per.setdefault((r["item"], r["qlt"], r["ptn"]), []).append(r)
    out = []
    for key, group in per.items():
        if len(group) < config.ART_REF_MIN_SLOTS:
            continue                        # опоры нет — не нам судить
        ref = statistics.median([g["price"] for g in group])
        if ref <= 0:
            continue
        lo, hi = ref / config.ART_SPIKE_FACTOR, ref * config.ART_SPIKE_FACTOR
        for g in group:
            if lo <= g["price"] <= hi:
                continue
            # тот же критерий, что у живой отсечки (artefact_watch.finalize_buckets):
            # сдвиг цены — это объём И умеренный масштаб; иначе выброс
            dev = max(g["price"] / ref, ref / g["price"])
            if (g["n"] < config.ART_SHIFT_MIN_SALES
                    or dev > config.ART_SHIFT_MAX_FACTOR):
                out.append((*key, g["slot"], g["price"], ref, g["n"]))
    out.sort(key=lambda r: -(r[4] / r[5]))
    return out


QUARANTINE = """
CREATE TABLE IF NOT EXISTS art_sales_spikes (
    item TEXT NOT NULL, qlt INTEGER NOT NULL, ptn INTEGER NOT NULL,
    slot TEXT NOT NULL, n INTEGER NOT NULL, sum REAL NOT NULL,
    min REAL NOT NULL, max REAL NOT NULL, med REAL,
    ref  REAL,                       -- опора, относительно которой признан выбросом
    PRIMARY KEY (item, qlt, ptn, slot)
);
"""


def restore(conn):
    """Вернуть карантин в агрегаты (если критерий оказался неверным)."""
    conn.executescript(QUARANTINE)
    n = conn.execute("SELECT COUNT(*) FROM art_sales_spikes").fetchone()[0]
    if not n:
        print("карантин пуст — возвращать нечего")
        return
    with market._lock:
        conn.execute(
            "INSERT OR REPLACE INTO art_sales_agg (item, qlt, ptn, slot, n, sum, min, max, med) "
            "SELECT item, qlt, ptn, slot, n, sum, min, max, med FROM art_sales_spikes")
        conn.execute("DELETE FROM art_sales_spikes")
        conn.commit()
    print(f"возвращено {n} слотов, карантин очищен")


def main():
    apply = "--apply" in sys.argv
    market.init()
    conn = market._conn
    if "--restore" in sys.argv:
        restore(conn)
        return
    total = conn.execute("SELECT COUNT(*) FROM art_sales_agg").fetchone()[0]
    spikes = find_spikes(conn)
    print(f"строк в art_sales_agg: {total}")
    print(f"слотов-выбросов (вне коридора ±{config.ART_SPIKE_FACTOR:g}x и не признаны сдвигом: "
          f"n<{config.ART_SHIFT_MIN_SALES} либо отклонение >{config.ART_SHIFT_MAX_FACTOR:g}x): "
          f"{len(spikes)} ({len(spikes) / max(total, 1) * 100:.2f}%)\n")
    for item, qlt, ptn, slot, price, ref, n in spikes[:20]:
        name = (idx.item(item) or {}).get("name", item)
        print(f"  {name[:22]:<22} q{qlt} +{ptn:<2} {slot[5:]}  "
              f"{price:>13,.0f} против опоры {ref:>11,.0f}  x{price / ref:>7.1f}  n={n}")
    if len(spikes) > 20:
        print(f"  ... и ещё {len(spikes) - 20}")
    if not spikes:
        print("чистить нечего")
        return
    if not apply:
        print("\nDRY-RUN. Чтобы убрать эти слоты в карантин, запустите с --apply")
        return
    conn.executescript(QUARANTINE)
    with market._lock:
        for item, qlt, ptn, slot, price, ref, n in spikes:
            conn.execute(
                "INSERT OR REPLACE INTO art_sales_spikes "
                "(item, qlt, ptn, slot, n, sum, min, max, med, ref) "
                "SELECT item, qlt, ptn, slot, n, sum, min, max, med, ? "
                f"FROM art_sales_agg WHERE item=? AND qlt=? AND {market.PTN_SQL}=? AND slot=?",
                (ref, item, qlt, ptn, slot))
            conn.execute(
                f"DELETE FROM art_sales_agg WHERE item=? AND qlt=? AND {market.PTN_SQL}=? "
                "AND slot=?", (item, qlt, ptn, slot))
        conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM art_sales_agg").fetchone()[0]
    kept = conn.execute("SELECT COUNT(*) FROM art_sales_spikes").fetchone()[0]
    print(f"\nв карантин перенесено {total - left} слотов (в таблице {kept}), "
          f"в агрегатах осталось {left}")
    print("откат: python scripts/clean_art_spikes.py --restore")


if __name__ == "__main__":
    main()
