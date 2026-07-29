"""Ручная сверка рецептов верстака с игрой — SQLite data/craft_tuning.db.

В базе EXBO нет признака «бонусный крафт» (шкала в игре есть не у всех
рецептов), а количества/энергия могут расходиться с игрой. Админ сверяет
рецепты в /dev/craft (API /api/admin/craft/recipes):

- bonus: 1 = у рецепта в игре ЕСТЬ шкала бонусного крафта, 0 = нет,
  NULL = не проверено. Калькулятор учитывает бонус ТОЛЬКО при bonus=1.
- data: JSON-переопределения полей рецепта поверх данных EXBO:
  {"energy": 1200, "result_amount": 20, "perk_level": 2,
   "ingredients": {"<item_id>": 15, ...}}  — только указанные поля;
  ingredients меняет количества существующих входов (0 = убрать вход).

Ключ рецепта (rkey) = "<item_id результата>:<номер варианта>" — позиция в
recipe_by_result GameDB. При обновлении базы EXBO порядок может сдвинуться,
поэтому в DEV-списке рядом с правками всегда показан исходный рецепт.

apply() вызывается из db.index.recipes_for на каждый запрос — кэш тюнинга
держим в памяти и перечитываем только после save().
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
_cache: dict[str, dict] | None = None   # rkey -> {"bonus": 0|1|None, "data": dict}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe_tuning (
    rkey       TEXT PRIMARY KEY,   -- '<result_item_id>:<variant_idx>'
    bonus      INTEGER,            -- 1/0/NULL — есть ли в игре бонусный крафт
    data       TEXT,               -- JSON-переопределения полей рецепта (NULL = нет)
    updated_at REAL NOT NULL
);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DATA_DIR / "craft_tuning.db"),
                                check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()
        total = _conn.execute("SELECT COUNT(*) FROM recipe_tuning").fetchone()[0]
    logger.info("craft_tuning: db ready (%d recipes tuned)", total)


def _load_cache_locked() -> dict[str, dict]:
    global _cache
    if _cache is None:
        _cache = {}
        if _conn is not None:
            for r in _conn.execute("SELECT rkey, bonus, data FROM recipe_tuning"):
                try:
                    data = json.loads(r["data"]) if r["data"] else None
                except ValueError:
                    data = None
                _cache[r["rkey"]] = {"bonus": r["bonus"], "data": data}
    return _cache


def get_all() -> dict[str, dict]:
    """Снимок всего тюнинга: rkey -> {bonus, data}."""
    with _lock:
        return dict(_load_cache_locked())


def save(rkey: str, bonus, data: dict | None) -> None:
    """Записать сверку рецепта. bonus: 1/0/None; data: dict-переопределения/None.

    Полностью пустая запись (bonus=None, data=None) удаляется из БД.
    """
    global _cache
    with _lock:
        if _conn is None:
            raise RuntimeError("craft_tuning: init() не вызван")
        if bonus is None and not data:
            _conn.execute("DELETE FROM recipe_tuning WHERE rkey=?", (rkey,))
        else:
            _conn.execute(
                "INSERT INTO recipe_tuning(rkey, bonus, data, updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(rkey) DO UPDATE SET "
                "bonus=excluded.bonus, data=excluded.data, updated_at=excluded.updated_at",
                (rkey, bonus, json.dumps(data, ensure_ascii=False) if data else None,
                 time.time()))
        _conn.commit()
        _cache = None   # перечитается лениво


def apply(recipe: dict) -> dict:
    """Рецепт с наложенными правками админа (или исходный, если правок нет).

    Добавляет 'bonus_ok' (1/0/None) — только он и означает подтверждённый
    бонусный крафт. Исходный dict НЕ мутируется: правки возвращают копию.
    """
    with _lock:
        t = _load_cache_locked().get(recipe.get("key") or "")
    if not t:
        return recipe
    data = t.get("data") or {}
    if not data:
        if t.get("bonus") is None:
            return recipe
        out = dict(recipe)
        out["bonus_ok"] = t.get("bonus")
        return out
    out = dict(recipe)
    out["bonus_ok"] = t.get("bonus")
    out["tuned"] = True
    if data.get("energy") is not None:
        out["energy"] = data["energy"]
    if data.get("result_amount") is not None:
        rid = (recipe.get("key") or ":").rsplit(":", 1)[0]
        out["result"] = [
            {**res, "amount": data["result_amount"]} if res.get("item") == rid else res
            for res in recipe.get("result", [])]
    if data.get("perk_level") is not None:
        req = dict(recipe.get("requirements") or {})
        req["perks"] = {k: data["perk_level"] for k in (req.get("perks") or {})}
        out["requirements"] = req
    amounts = data.get("ingredients")
    if isinstance(amounts, dict):
        ings = []
        for ing in recipe.get("ingredients", []):
            amt = amounts.get(ing.get("item"))
            if amt == 0:
                continue          # 0 = вход убран из рецепта
            ings.append({**ing, "amount": amt} if amt is not None else ing)
        out["ingredients"] = ings
    return out
