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


# --- характеристики предмета (тултип) для игровой карточки ---
# элементы без переведённого имени в базе подписываем вручную
_CHAR_KEY_NAMES = {
    "core.tooltip.info.rank": "Ранг",
    "core.tooltip.info.category": "Класс",
    "weapon.tooltip.weapon.info.ammo_type": "Тип боеприпасов",
}
# единицы измерения по ключу стата (как в игровом интерфейсе)
_CHAR_UNITS = {
    "core.tooltip.info.weight": "кг",
    "core.tooltip.info.durability": "%",
    "core.tooltip.info.max_durability": "%",
    "stalker.artefact_properties.factor.speed_modifier": "%",
    "core.tooltip.stat_name.damage_type.direct": "ед",
    "weapon.tooltip.weapon.info.distance": "м",
    "weapon.tooltip.weapon.info.rate_of_fire": "выстр/мин",
    "weapon.tooltip.magazine.info.reload_time": "с",
    "weapon.tooltip.magazine.info.reload_time_tactical": "с",
    "weapon.stat_factor.reload_modifier": "%",
    "weapon.tooltip.weapon.info.spread": "°",
    "weapon.tooltip.weapon.info.hip_spread": "°",
    "weapon.tooltip.weapon.info.draw_time": "с",
    "weapon.tooltip.weapon.info.aim_switch": "с",
}


def _fmt_num(v) -> str | None:
    """Число тултипа → строка без хвостовых нулей, с десятичной запятой как в игре
    (33.9→«33,9», 100.0→«100», -1.9999981→«-2», 0.42000008→«0,42»)."""
    if v is None:
        return None
    r = round(float(v), 2)
    s = str(int(r)) if r == int(r) else f"{r:g}"
    return s.replace(".", ",")


def _is_weapon_part(name: str) -> bool:
    """Оружейная «часть»: «Часть … #N» или «Часть схемы: …» (решение юзера —
    такие бартеры (сборка оружия из частей) в разделе не нужны)."""
    nm = (name or "").strip()
    return nm.startswith("Часть схемы") or (nm.startswith("Часть ") and "#" in nm)


_CURRENCY_WORDS = ("жетон", "талон", "расписк")


def _is_activity_currency(name: str, rel_path: str) -> bool:
    """Валюта активности: жетоны/талоны/расписки за бои, репутацию и квесты.

    Их зарабатывают, а не покупают, поэтому рублёвая цена с аукциона для них —
    ложь. «Боевой жетон» там реально стоит 4 000 ₽/шт, и вход «1000 жетонов»
    превращал себестоимость бартера в 4 млн ₽ (Аномальная сыворотка → Берлога-6,
    85% посчитанной цены). Такие входы — фарм, цены у них нет.

    Только items/other: одноимённые аксессуары («Золотой жетон сталкера») —
    настоящие предметы аукциона, их цена честная.
    """
    if not rel_path.startswith("items/other/"):
        return False
    nm = (name or "").lower()
    return any(w in nm for w in _CURRENCY_WORDS)


class GameDB:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}          # id -> инфо о предмете
        self.recipe_by_result: dict[str, list] = {}   # id результата -> [рецепты верстака]
        self.used_in: dict[str, list[str]] = {}   # id ингредиента -> [id результатов]
        self.hideout_perks: list[dict] = []       # [{id, name}] — навыки крафта из БД
        self.hideout_features: list[str] = []     # все станки/фичи из requirements рецептов
        self.hideout_feature_icons: dict[str, str] = {}  # фича -> игровая иконка станка
        self.hideout_feature_bench: dict[str, str] = {}  # фича -> стол (workbench/laboratory_table/kitchen_table)
        self.barter_by_result: dict[str, list] = {}  # id результата -> [бартеры поселений]
        self.barter_used_in: dict[str, list[str]] = {}  # id входа -> [id результатов бартера]
        self.barter_settlements: dict[str, str] = {}    # ключ поселения -> имя (ru)
        self.farm_currency: set[str] = set()      # валюты активности (жетоны/талоны): цены с аука не берём
        self.disassembly: dict[str, dict] = {}    # id входа -> {parent, count}: разбор родителя с аука
        self.artefacts: dict[str, dict] = {}      # id -> {class, weight, stats{key: {name,min,max,harmful}}}
        self.artefact_stat_names: dict[str, dict] = {}  # stat_key -> {name, harmful} (справочник)
        self.containers: dict[str, dict] = {}     # id -> {name, icon, color, kind, rank, slots, efficiency, protection, weight, self_stats}
        self.backpacks: dict[str, dict] = {}      # то же, что контейнеры (рюкзаки со слотами под арты)
        self.armor: dict[str, dict] = {}          # id -> {name, icon, color, class, weight, bullet0, vit0, rel}
        self._armor_lvl: dict[tuple, dict] = {}   # (id, ptn) -> {bullet, vitality} (ленивый кэш заточки)
        self._search: list[tuple[str, str]] = []  # (id, "имя_ru имя_en" в нижнем регистре)
        self._data_path: dict[str, str] = {}      # id -> относительный путь к json предмета
        self._desc_cache: dict[str, str | None] = {}
        self._char_cache: dict[tuple, list] = {}  # (id, ptn) -> характеристики (тултип)
        self._ptn_cache: dict[str, int] = {}      # id -> макс. уровень заточки в БД (0 — нет)
        self._energy_cache: dict[str, float | None] = {}  # номинал топлива (core.tooltip.energy)

    # ---------- загрузка ----------
    def load(self) -> None:
        self._load_items()
        self._load_hideout_recipes()
        self._load_barter_recipes()
        self._load_disassembly()
        self._build_used_in()
        self._load_equipment()
        self.farm_currency = {
            iid for iid, it in self.items.items()
            if _is_activity_currency(it.get("name", ""), self._data_path.get(iid, ""))}
        logger.info("farm currency (цены с аука не берём): %s",
                    ", ".join(sorted(self.items[i]["name"] for i in self.farm_currency)))
        logger.info(
            "GameDB loaded: %d items, %d craft results, %d barter results, "
            "%d used-in entries, %d artefacts with stats, %d containers, %d backpacks, "
            "%d armor, %d disassembly maps",
            len(self.items), len(self.recipe_by_result), len(self.barter_by_result),
            len(self.used_in), len(self.artefacts), len(self.containers),
            len(self.backpacks), len(self.armor), len(self.disassembly),
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
                lst = self.recipe_by_result.setdefault(res["item"], [])
                # ключ для ручного тюнинга (/dev/craft): результат + № варианта;
                # у рецепта с несколькими результатами ключ по первому — first wins
                recipe.setdefault("key", f"{res['item']}:{len(lst)}")
                lst.append(recipe)
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

    def _load_barter_recipes(self) -> None:
        """Бартеры торговцев поселений (barter_recipes.json).

        В файле 14 блоков на 12 уникальных поселений: «Бар» и «Фракции Севера»
        встречаются дважды (зеркала с другим трейд-ин вариантом брони) — мержим
        по ключу поселения, офферы дедупим по содержимому. Нормализованный бартер:
        {settlement, settlement_name, level, item, offers:[{currency, cost, inputs}]}.
        """
        try:
            doc = self._read("barter_recipes.json")
        except FileNotFoundError:
            logger.warning("barter_recipes.json missing — barter disabled until re-download")
            return
        # оружейные «части» (сборка оружия из частей) — убираем целиком: и как
        # результат бартера, и офферы, которые их требуют трейд-ином
        excluded = {iid for iid, it in self.items.items()
                    if _is_weapon_part(it.get("name", ""))}
        merged: dict[tuple[str, str], dict] = {}   # (поселение, результат) -> бартер
        for block in doc:
            key = ((block.get("settlementTitle") or {}).get("key") or "")
            key = key.removeprefix("settlement.id.").removesuffix(".title") or "unknown"
            name = _tr(block.get("settlementTitle")) or key
            self.barter_settlements.setdefault(key, name)
            for rc in block.get("recipes", []):
                iid = rc.get("item")
                if not iid or iid in excluded:
                    continue
                b = merged.setdefault((key, iid), {
                    "settlement": key, "settlement_name": name,
                    "level": rc.get("settlementRequiredLevel"),
                    "item": iid, "offers": [], "_sigs": set(),
                })
                lv = rc.get("settlementRequiredLevel")
                if lv is not None and (b["level"] is None or lv < b["level"]):
                    b["level"] = lv
                for off in rc.get("offers", []):
                    inputs = [{"item": ri["item"], "amount": ri.get("amount", 1)}
                              for ri in off.get("requiredItems", [])]
                    if any(i["item"] in excluded for i in inputs):
                        continue
                    sig = (off.get("currency"), off.get("cost"),
                           tuple(sorted((i["item"], i["amount"]) for i in inputs)))
                    if sig in b["_sigs"]:
                        continue
                    b["_sigs"].add(sig)
                    b["offers"].append({"currency": off.get("currency") or "money",
                                        "cost": off.get("cost") or 0, "inputs": inputs})
        rev: dict[str, set[str]] = {}
        for (_, iid), b in merged.items():
            del b["_sigs"]
            if not b["offers"]:            # все офферы отфильтрованы (были с частями)
                continue
            self.barter_by_result.setdefault(iid, []).append(b)
            for off in b["offers"]:
                for ing in off["inputs"]:
                    rev.setdefault(ing["item"], set()).add(iid)
        name_of = lambda i: (self.items.get(i) or {}).get("name", i)  # noqa: E731
        self.barter_used_in = {iid: sorted(rids, key=name_of) for iid, rids in rev.items()}

    def _load_disassembly(self) -> None:
        """Ручная таблица: вход бартера, которого нет на ауке, добывается разбором
        родителя (который на ауке есть). {child: {parent, count}} из seed-файла;
        цена входа = цена родителя на ауке / count (см. services/barter._obtain)."""
        seed = config.BACKEND_DIR / "seed" / "barter_disassembly.json"
        if not seed.exists():
            return
        try:
            doc = json.loads(seed.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed to read barter_disassembly.json")
            return
        for child, rec in doc.items():
            if child.startswith("_") or not isinstance(rec, dict):
                continue
            parent, count = rec.get("parent"), rec.get("count")
            if parent and count and child in self.items and parent in self.items:
                self.disassembly[child] = {"parent": parent, "count": int(count)}

    def barter_item_ids(self) -> set[str]:
        """Все предметы бартер-графа (результаты + входы + родители разбора) — для цен."""
        ids: set[str] = set(self.barter_by_result)
        ids.update(self.barter_used_in)
        ids.update(d["parent"] for d in self.disassembly.values())
        return ids

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

    def _parse_storage(self, iid: str, doc: dict, kind: str) -> dict | None:
        """Хранилище под арты (контейнер/рюкзак): слоты (size), эффективность,
        внутр. защита, вес, ранг — плюс СОБСТВЕННЫЕ статы предмета (пулестойкость,
        переносимый вес, эфф. лечения, защита/эмиссия заражения…): в игре они входят
        в сборку так же, как статы артефактов. Вредный стат — по красному nameColor.
        None — у предмета нет слотов под арты (сумки без размера не берём)."""
        fields = {"rank": "", "slots": None, "efficiency": None,
                  "protection": None, "weight": None}
        keymap = {
            "core.tooltip.info.weight": "weight",
            "stalker.tooltip.backpack.stat_name.inner_protection": "protection",
            "stalker.tooltip.backpack.stat_name.effectiveness": "efficiency",
            "stalker.tooltip.backpack.info.size": "slots",
        }
        self_stats = []
        for el in self._elements(doc):
            key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
            if el.get("type") == "numeric" and key in keymap:
                fields[keymap[key]] = el.get("value")
            elif el.get("type") == "key-value" and key == "core.tooltip.info.rank":
                fields["rank"] = _tr(el.get("value"))
            elif (el.get("type") == "numeric"
                  and key.startswith("stalker.artefact_properties.factor.")):
                color = ((el.get("formatted") or {}).get("nameColor") or "").upper()
                self_stats.append({"key": key, "name": _tr(el.get("name")) or key,
                                   "val": el.get("value"), "harmful": color.startswith("C1")})
        if not fields["slots"]:
            return None
        it = self.items.get(iid, {})
        return {"id": iid, "name": it.get("name", iid), "icon": it.get("icon", ""),
                "color": it.get("color", "DEFAULT"), "kind": kind,
                **fields, "slots": int(fields["slots"]), "self_stats": self_stats}

    def storage(self, sid: str) -> dict | None:
        """Хранилище сборки по id — контейнер или рюкзак (в калькуляторе равноправны)."""
        return self.containers.get(sid) or self.backpacks.get(sid)

    def _load_equipment(self) -> None:
        """Артефакты: окно статов ОБЫЧНОГО качества из базового json (диапазон =
        M∈[0.85; 1.0] от Q0-max; тиры выше — сдвиг M, формулы в services/builds).
        Вредные статы определяются по красному nameColor и не масштабируются.
        Контейнеры/рюкзаки: слоты/эффективность/защита/вес + собственные статы."""
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
                st = self._parse_storage(iid, doc, "container") if doc else None
                if st:
                    self.containers[iid] = st
            elif rel.startswith("items/backpacks/"):
                doc = self._item_json(iid)
                st = self._parse_storage(iid, doc, "backpack") if doc else None
                if st:
                    self.backpacks[iid] = st
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

    def category(self, item_id: str) -> str:
        """Категория предмета по пути данных: 'items/armor/x.json' → 'armor'.
        Известные: artefact, weapon, armor, attachment, bullet, misc, supply,
        containers, backpacks, grenade, medicine, other. Пусто — предмет вне базы."""
        rel = self._data_path.get(item_id) or ""
        parts = rel.split("/")
        return parts[1] if len(parts) > 2 else ""

    def category_ids(self, *cats: str) -> list[str]:
        """Все предметы перечисленных категорий (см. category)."""
        want = set(cats)
        return sorted(i for i in self._data_path if self.category(i) in want)

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

    @staticmethod
    def _parse_chars(doc: dict | None) -> list[dict]:
        """Тултип предмета → строки характеристик (порядок файла сохранён)."""
        out: list[dict] = []
        for el in GameDB._elements(doc or {}):
            key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
            t = el.get("type")
            name = _tr(el.get("name")) or _CHAR_KEY_NAMES.get(key, "")
            if not name:
                continue
            num = None
            if t == "numeric":
                val = _fmt_num(el.get("value"))
                num = None if el.get("value") is None else round(float(el["value"]), 2)
            elif t == "range" and el.get("min") is not None:
                val = f"{_fmt_num(el.get('min'))}–{_fmt_num(el.get('max'))}"
                num = round(float(el.get("max") or el["min"]), 2)   # верх тира — для сравнения
            elif t == "key-value":
                val = _tr(el.get("value"))
            else:
                continue
            if val in (None, ""):
                continue
            color = ((el.get("formatted") or {}).get("nameColor") or "").upper()
            out.append({
                "key": key, "name": name, "value": val, "num": num,
                "unit": _CHAR_UNITS.get(key, ""),
                "harmful": color.startswith("C1"),
                "group": "info" if key.startswith("core.tooltip.info.") else "stat",
                "rank": key == "core.tooltip.info.rank",
            })
        return out

    def _variant_json(self, item_id: str, ptn: int) -> dict | None:
        """Тултип предмета на уровне заточки: items/<cat>/<sub>/_variants/<id>/<ptn>.json."""
        rel = self._data_path.get(item_id)
        if not rel:
            return None
        rp = Path(rel)
        path = config.DATA_DIR / rp.parent / "_variants" / rp.stem / f"{ptn}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed to read variant json for %s +%d", item_id, ptn)
            return None

    def max_ptn(self, item_id: str) -> int:
        """До какой заточки предмет расписан в базе (0 — заточка неприменима)."""
        if item_id in self._ptn_cache:
            return self._ptn_cache[item_id]
        lvl = 0
        rel = self._data_path.get(item_id)
        if rel:
            rp = Path(rel)
            d = config.DATA_DIR / rp.parent / "_variants" / rp.stem
            if d.is_dir():
                for f in d.glob("*.json"):
                    if f.stem.isdigit():
                        lvl = max(lvl, int(f.stem))
        self._ptn_cache[item_id] = lvl
        return lvl

    def characteristics(self, item_id: str, ptn: int = 0) -> list[dict]:
        """Характеристики предмета из тултипа игрового json (порядок сохранён) для
        игровой карточки: [{key, name, value, num, unit, harmful, group}]. group='info' —
        шапка (ранг/класс/вес/прочность), 'stat' — боевые статы (урон, защиты,
        скорострельность…). Минусы — harmful. С кэшем: json читаем один раз.

        ptn>0 — значения на этом уровне заточки (файл варианта). В варианте после
        базовых статов идут строки-НАДБАВКИ (тот же стат с дельтой, а у оружия ещё
        и weapon.stat_factor.*), поэтому набор строк берём из базы, а значения —
        первое вхождение ключа в варианте. Заточки нет в базе — отдаём базовые.
        """
        ptn = max(0, min(15, int(ptn or 0)))
        ck = (item_id, ptn)
        if ck in self._char_cache:
            return self._char_cache[ck]
        rows = self._parse_chars(self._item_json(item_id))
        doc = self._variant_json(item_id, ptn) if ptn and rows else None
        if doc:
            pool: dict[str, list[dict]] = {}
            for r in self._parse_chars(doc):
                pool.setdefault(r["key"], []).append(r)
            rows = [pool[r["key"]].pop(0) if pool.get(r["key"]) else r for r in rows]
        self._char_cache[ck] = rows
        return rows

    def energy_value(self, item_id: str) -> float | None:
        """Сколько энергии даёт предмет в генераторе (core.tooltip.energy), с кэшем."""
        if item_id in self._energy_cache:
            return self._energy_cache[item_id]
        val = None
        doc = self._item_json(item_id)
        if doc:
            for el in self._elements(doc):
                key = ((el.get("name") or el.get("key") or {}).get("key")) or ""
                if el.get("type") == "numeric" and key == "core.tooltip.energy":
                    val = el.get("value")
                    break
        self._energy_cache[item_id] = val
        return val

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
        """Все рецепты верстака, дающие предмет (с правками админа из /dev/craft)."""
        from app.db import craft_tuning   # локально: избежать цикла при загрузке
        return [craft_tuning.apply(r) for r in self.recipe_by_result.get(item_id, [])]

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
