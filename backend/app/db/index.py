"""Индексы игровой БД в памяти: предметы, поиск по имени, рецепты по результату."""
import json
import logging
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)


def _tr(node: dict | None, lang: str = "ru") -> str:
    """Достаёт локализованную строку из translation-объекта БД."""
    if not isinstance(node, dict):
        return ""
    lines = node.get("lines") or {}
    return lines.get(lang) or lines.get("en") or node.get("key") or ""


def _id_from_path(p: str) -> str:
    """/items/other/qyvk.json -> qyvk"""
    return Path(p).stem


class GameDB:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}          # id -> инфо о предмете
        self.recipe_by_result: dict[str, list] = {}   # id результата -> [рецепты верстака]
        self._search: list[tuple[str, str]] = []  # (id, "имя_ru имя_en" в нижнем регистре)

    # ---------- загрузка ----------
    def load(self) -> None:
        self._load_items()
        self._load_hideout_recipes()
        logger.info(
            "GameDB loaded: %d items, %d craft results",
            len(self.items), len(self.recipe_by_result),
        )

    def _read(self, name: str):
        with open(config.DATA_DIR / name, encoding="utf-8") as f:
            return json.load(f)

    def _load_items(self) -> None:
        listing = self._read("listing.json")
        for e in listing:
            data_path = e.get("data") or ""
            item_id = _id_from_path(data_path)
            if not item_id:
                continue
            name_ru = _tr(e.get("name"), "ru")
            name_en = _tr(e.get("name"), "en")
            icon = (e.get("icon") or "").lstrip("/")  # 'icons/other/qyvk.png' (relative)
            self.items[item_id] = {
                "id": item_id,
                "name": name_ru or name_en or item_id,
                "name_en": name_en,
                "icon": icon,
                "color": e.get("color", "DEFAULT"),
                "status": (e.get("status") or {}).get("state", "NONE"),
            }
            self._search.append((item_id, f"{name_ru} {name_en}".lower()))

    def _load_hideout_recipes(self) -> None:
        doc = self._read("hideout_recipes.json")
        for rc in doc.get("recipes", []):
            recipe = {
                "bench": rc.get("bench"),
                "category": _tr(rc.get("category")),
                "subcategory": _tr(rc.get("subcategory")),
                "result": rc.get("result", []),
                "ingredients": rc.get("ingredients", []),
                "energy": rc.get("energy"),
            }
            for res in recipe["result"]:
                self.recipe_by_result.setdefault(res["item"], []).append(recipe)

    # ---------- запросы ----------
    def item(self, item_id: str) -> dict | None:
        return self.items.get(item_id)

    def search(self, query: str, limit: int = 30) -> list[dict]:
        q = query.strip().lower()
        if not q:
            return []
        out = []
        for item_id, hay in self._search:
            pos = hay.find(q)
            if pos != -1:
                out.append((pos, item_id))
        out.sort(key=lambda t: (t[0], len(self.items[t[1]]["name"])))  # точнее совпадение выше
        return [self.items[i] for _, i in out[:limit]]

    def recipes_for(self, item_id: str) -> list[dict]:
        """Все рецепты верстака, дающие предмет."""
        return self.recipe_by_result.get(item_id, [])

    def priceable_ids(self) -> list[str]:
        """Все предметы крафт-графа (результаты + ингредиенты) — для фонового обновления цен."""
        ids: set[str] = set(self.recipe_by_result)
        for recipes in self.recipe_by_result.values():
            for r in recipes:
                for ing in r.get("ingredients", []):
                    ids.add(ing["item"])
                for res in r.get("result", []):
                    ids.add(res["item"])
        return sorted(ids)


db = GameDB()
