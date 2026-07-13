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
        self.used_in: dict[str, list[str]] = {}   # id ингредиента -> [id результатов]
        self.hideout_perks: list[dict] = []       # [{id, name}] — навыки крафта из БД
        self.hideout_features: list[str] = []     # все станки/фичи из requirements рецептов
        self.hideout_feature_icons: dict[str, str] = {}  # фича -> игровая иконка станка
        self.hideout_feature_bench: dict[str, str] = {}  # фича -> стол (workbench/laboratory_table/kitchen_table)
        self.artefacts: dict[str, dict] = {}      # id -> {class, weight, stats{key: {name,min,max,harmful}}}
        self.artefact_stat_names: dict[str, dict] = {}  # stat_key -> {name, harmful} (справочник)
        self.containers: dict[str, dict] = {}     # id -> {name, icon, color, rank, slots, efficiency, protection, weight}
        self.armor: dict[str, dict] = {}          # id -> {name, icon, color, class, weight, bullet0, vit0, rel}
        self._armor_lvl: dict[tuple, dict] = {}   # (id, ptn) -> {bullet, vitality} (ленивый кэш заточки)
        self._search: list[tuple[str, str]] = []  # (id, "имя_ru имя_en" в нижнем регистре)
        self._data_path: dict[str, str] = {}      # id -> относительный путь к json предмета
        self._desc_cache: dict[str, str | None] = {}

    # ---------- загрузка ----------
    def load(self) -> None:
        self._load_items()
        self._load_hideout_recipes()
        self._build_used_in()
        self._load_equipment()
        logger.info(
            "GameDB loaded: %d items, %d craft results, %d used-in entries, "
            "%d artefacts with stats, %d containers, %d armor",
            len(self.items), len(self.recipe_by_result), len(self.used_in),
            len(self.artefacts), len(self.containers), len(self.armor),
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
            self._data_path[item_id] = data_path.lstrip("/")  # 'items/misc/404p.json'
            self._search.append((item_id, f"{name_ru} {name_en}".lower()))

    def _load_hideout_recipes(self) -> None:
        doc = self._read("hideout_recipes.json")
        self.hideout_perks = [{"id": p["id"], "name": _tr(p.get("name")) or p["id"]}
                              for p in doc.get("perks", []) if p.get("id")]
        feats: set[str] = set()
        bench_cnt: dict[str, dict[str, int]] = {}  # фича -> {стол: сколько рецептов требуют}
        for rc in doc.get("recipes", []):
            for f in (rc.get("requirements") or {}).get("features") or []:
                feats.add(f)
                if rc.get("bench"):
                    c = bench_cnt.setdefault(f, {})
                    c[rc["bench"]] = c.get(rc["bench"], 0) + 1
            recipe = {
                "bench": rc.get("bench"),
                "category": _tr(rc.get("category")),
                "subcategory": _tr(rc.get("subcategory")),
                "result": rc.get("result", []),
                "ingredients": rc.get("ingredients", []),
                "energy": rc.get("energy"),
                "requirements": rc.get("requirements") or {},
            }
            for res in recipe["result"]:
                self.recipe_by_result.setdefault(res["item"], []).append(recipe)
        self.hideout_features = sorted(feats)
        # станок относим к столу, на чьих рецептах он чаще всего требуется; нужно для
        # группировки в профиле (при равенстве — кухня > лаборатория > верстак:
        # единственный спорный случай — вытяжка, в игре это апгрейд кухни)
        prio = {"kitchen_table": 2, "laboratory_table": 1, "workbench": 0}
        self.hideout_feature_bench = {
            f: max(c, key=lambda b: (c[b], prio.get(b, -1)))
            for f, c in bench_cnt.items()}
        # иконки станков/инструментов — игровые рендеры (frontend/hideout/<фича>.png),
        # извлечённые из клиента (в базе EXBO этих предметов часто нет)
        hdir = config.FRONTEND_DIR / "hideout"
        self.hideout_feature_icons = {
            f: f"hideout/{f}.png" for f in self.hideout_features
            if (hdir / f"{f}.png").exists()}

    # ---------- статы артефактов и контейнеры (для калькулятора сборок) ----------
    def _item_json(self, item_id: str) -> dict | None:
        rel = self._data_path.get(item_id)
        if not rel:
            return None
        path = config.DATA_DIR / rel
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed to read item json for %s", item_id)
            return None

    @staticmethod
    def _elements(doc: dict):
        for block in doc.get("infoBlocks", []):
            for el in (block.get("elements") or []):
                yield el

    def _load_equipment(self) -> None:
        """Артефакты: окно статов ОБЫЧНОГО качества из базового json (диапазон =
        M∈[0.85; 1.0] от Q0-max; тиры выше — сдвиг M, формулы в services/builds).
        Вредные статы определяются по красному nameColor и не масштабируются.
        Контейнеры: слоты/эффективность/защита/вес по translation-ключам."""
        for iid, rel in self._data_path.items():
            if rel.startswith("items/artefact/"):
                doc = self._item_json(iid)
                if not doc:
                    continue
                art = {"class": "", "weight": None, "stats": {}}
                for el in self._elements(doc):
                    key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
                    if el.get("type") == "key-value" and key == "core.tooltip.info.category":
                        art["class"] = _tr(el.get("value"))
                    elif el.get("type") == "numeric" and key == "core.tooltip.info.weight":
                        art["weight"] = el.get("value")
                    elif el.get("type") == "range" and el.get("min") is not None:
                        color = ((el.get("formatted") or {}).get("nameColor") or "").upper()
                        harmful = color.startswith("C1")  # C15252 — красный (вредный)
                        name = _tr(el.get("name")) or key
                        art["stats"][key] = {"name": name, "min": el["min"],
                                             "max": el["max"], "harmful": harmful}
                        # в каталоге стат «вредный», только если вреден на ВСЕХ
                        # артефактах (один и тот же стат бывает и зелёным, и красным)
                        cat = self.artefact_stat_names.setdefault(
                            key, {"name": name, "harmful": harmful})
                        cat["harmful"] = cat["harmful"] and harmful
                if art["stats"]:
                    self.artefacts[iid] = art
            elif rel.startswith("items/containers/"):
                doc = self._item_json(iid)
                if not doc:
                    continue
                cont = {"rank": "", "slots": None, "efficiency": None,
                        "protection": None, "weight": None}
                keymap = {
                    "core.tooltip.info.weight": "weight",
                    "stalker.tooltip.backpack.stat_name.inner_protection": "protection",
                    "stalker.tooltip.backpack.stat_name.effectiveness": "efficiency",
                    "stalker.tooltip.backpack.info.size": "slots",
                }
                for el in self._elements(doc):
                    key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
                    if el.get("type") == "numeric" and key in keymap:
                        cont[keymap[key]] = el.get("value")
                    elif el.get("type") == "key-value" and key == "core.tooltip.info.rank":
                        cont["rank"] = _tr(el.get("value"))
                if cont["slots"]:
                    it = self.items.get(iid, {})
                    self.containers[iid] = {"id": iid, "name": it.get("name", iid),
                                            "icon": it.get("icon", ""),
                                            "color": it.get("color", "DEFAULT"), **cont,
                                            "slots": int(cont["slots"])}
            elif rel.startswith("items/armor/"):
                doc = self._item_json(iid)
                if not doc:
                    continue
                bullet, vit, cls, weight = self._armor_bv(doc, want_meta=True)
                if bullet <= 0:      # для приведённого ХП нужна пулестойкость
                    continue
                it = self.items.get(iid, {})
                self.armor[iid] = {"id": iid, "name": it.get("name", iid),
                                   "icon": it.get("icon", ""), "color": it.get("color", "DEFAULT"),
                                   "class": cls, "weight": weight,
                                   "bullet0": bullet, "vit0": vit, "rel": rel}

    _BULLET_KEY = "stalker.artefact_properties.factor.bullet_dmg_factor"
    _HEALTH_KEY = "stalker.artefact_properties.factor.health_bonus"

    def _armor_bv(self, doc: dict, want_meta: bool = False):
        """Пулестойкость (макс. из записей = итог, не дельта) и Живучесть брони.
        В заточённых вариантах два bullet-значения: итог и бонус — берём больший."""
        bullet = vit = 0.0
        cls = ""
        weight = None
        for el in self._elements(doc):
            key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
            if el.get("type") == "numeric":
                v = el.get("value") or 0.0
                if key == self._BULLET_KEY:
                    bullet = max(bullet, v)
                elif key == self._HEALTH_KEY:
                    vit = max(vit, v)
                elif key == "core.tooltip.info.weight":
                    weight = v
            elif want_meta and el.get("type") == "key-value" and key == "core.tooltip.info.category":
                cls = _tr(el.get("value"))
        return (bullet, vit, cls, weight) if want_meta else (bullet, vit)

    def armor_stats(self, armor_id: str, ptn: int) -> dict:
        """Пулестойкость и Живучесть брони на уровне заточки ptn (ленивое чтение
        _variants — заточка брони НЕлинейна, формулой не считается)."""
        a = self.armor.get(armor_id)
        if not a:
            return {"bullet": 0.0, "vitality": 0.0}
        ptn = max(0, min(15, int(ptn)))
        if ptn == 0:
            return {"bullet": a["bullet0"], "vitality": a["vit0"]}
        ck = (armor_id, ptn)
        if ck not in self._armor_lvl:
            # rel = items/armor/<sub>/<id>.json → items/armor/<sub>/_variants/<id>/<ptn>.json
            from pathlib import Path
            rp = Path(a["rel"])
            vp = rp.parent / "_variants" / rp.stem / f"{ptn}.json"
            doc = None
            fp = config.DATA_DIR / vp
            if fp.exists():
                try:
                    doc = json.loads(fp.read_text(encoding="utf-8"))
                except Exception:
                    doc = None
            if doc:
                b, v = self._armor_bv(doc)
                self._armor_lvl[ck] = {"bullet": b, "vitality": v}
            else:  # варианта нет — линейная аппроксимация от базы
                self._armor_lvl[ck] = {"bullet": a["bullet0"] * (1 + 0.02 * ptn),
                                       "vitality": a["vit0"] * (1 + 0.02 * ptn)}
        return self._armor_lvl[ck]

    def _build_used_in(self) -> None:
        """Обратный индекс: ингредиент -> крафт-результаты, где он нужен."""
        rev: dict[str, set[str]] = {}
        for result_id, recipes in self.recipe_by_result.items():
            for r in recipes:
                for ing in r.get("ingredients", []):
                    rev.setdefault(ing["item"], set()).add(result_id)
        name = lambda iid: (self.items.get(iid) or {}).get("name", iid)  # noqa: E731
        self.used_in = {iid: sorted(rids, key=name) for iid, rids in rev.items()}

    # ---------- запросы ----------
    def item(self, item_id: str) -> dict | None:
        return self.items.get(item_id)

    def description(self, item_id: str) -> str | None:
        """Игровое описание предмета из его json-файла (лениво, с кэшем)."""
        if item_id in self._desc_cache:
            return self._desc_cache[item_id]
        desc = None
        rel = self._data_path.get(item_id)
        if rel:
            try:
                path = config.DATA_DIR / rel
                if path.exists():
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    parts = [_tr(b.get("text")) for b in doc.get("infoBlocks", [])
                             if isinstance(b, dict) and b.get("type") == "text"]
                    desc = "\n".join(p for p in parts if p) or None
            except Exception:
                logger.exception("failed to read item description for %s", item_id)
        self._desc_cache[item_id] = desc
        return desc

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

    def artefact_ids(self) -> list[str]:
        """Все артефакты (по пути данных items/artefact/**) — для биржи артефактов."""
        return sorted(i for i, p in self._data_path.items()
                      if p.startswith("items/artefact/"))

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
