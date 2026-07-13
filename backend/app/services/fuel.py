"""Топливо генератора убежища: цена энергии и выгодные источники заправки.

Крафт жжёт энергию верстака; энергию даёт генератор, сжигая топливо. Каждому
топливу в БД предмета прописан номинал (core.tooltip.energy). Метрика выгоды —
рублей за 1000 ед. энергии; цена топлива — медиана 50 последних продаж аука
(fallback: медиана 10 → средняя → закупка по стакану → мин. выкуп).

Группы соответствуют пристройкам генератора: базовый жжёт канистры (бензин/
дизель), баллоны с газом принимает газовая станция, батареи и аномальное —
свои станции приёма (справка EXBO: пристройки «Генератора» также поднимают
лимит энергии и скорость расщепления — на цену энергии это не влияет).
"""
from app.db.index import db
from app.services.price_store import store

# фичи-станции, открывающие энергоносители. battery/anomal есть в requirements
# рецептов (db.hideout_features), gas — только пристройка, ключ синтетический
FEATURE_GAS = "generator_energy_source_gas"
FEATURE_BATTERY = "generator_energy_source_battery"
FEATURE_ANOMAL = "generator_energy_source_anomal"

# пристройки без влияния на цену энергии (лимит/скорость расщепления) —
# в профиле отмечаются для полноты, расчёт топлива их не использует
PASSIVE_FEATURES = ["generator_fuel_filter",       # Топливный фильтр
                    "generator_inverter",          # Инвертор
                    "generator_battery_cabinet"]   # Аккумуляторный шкаф

# фичи вне db.hideout_features — добавляются в справочник /api/hideout и
# в известные ключи профиля (hideout.validate_profile)
EXTRA_PROFILE_FEATURES = [FEATURE_GAS] + PASSIVE_FEATURES

# иконки пристроек — игровые предметы-аналоги из БД (у станций батарей/аномального
# приоритет за рендерами из frontend/hideout, см. /api/hideout)
FEATURE_ITEM_ICONS = {
    FEATURE_GAS: "gvk6",                     # Станция для приема баллонов с газом
    "generator_fuel_filter": "1jog",         # Топливный фильтр
    "generator_inverter": "zlky",            # Инвертор
    "generator_battery_cabinet": None,       # предмета в базе EXBO нет
}

# id топлива -> (группа, номинал-fallback, если в json предмета нет energy)
FUEL_ITEMS: dict[str, tuple[str, float]] = {
    "g0vn":  ("base", 2000),      # Канистра с бензином
    "z7lk":  ("base", 2500),      # Канистра с дизелем
    "5dgo":  ("gas", 2500),       # Баллон с пропаном
    "y7j0":  ("gas", 3000),       # Баллон с метаном
    "w3923": ("battery", 1000),   # Сменный аккумулятор
    "55621": ("battery", 5000),   # Армейский аккумулятор
    "401j":  ("battery", 5000),   # Батарея холодного синтеза
    "7l127": ("anomal", 50),      # Аномальная пыль
    "1rl71": ("anomal", 250),     # Пыль изменения
    "96z2z": ("anomal", 1250),    # Хронопыль
    "3gqkg": ("anomal", 5000),    # Нестабильная аномальная батарея
    "1rl61": ("anomal", 40000),   # Хроносфера
}

GROUP_FEATURE = {"base": None, "gas": FEATURE_GAS,
                 "battery": FEATURE_BATTERY, "anomal": FEATURE_ANOMAL}


def feature_icons() -> dict[str, str]:
    """Иконки пристроек генератора из предметов БД (для страницы профиля)."""
    out = {}
    for feat, iid in FEATURE_ITEM_ICONS.items():
        it = db.item(iid) if iid else None
        if it and it.get("icon"):
            out[feat] = it["icon"]
    return out


def warm() -> None:
    """Записать интерес воркера цен: лоты + история продаж всех топлив."""
    store.request(FUEL_ITEMS)
    for iid in FUEL_ITEMS:
        store.request_history(iid)


def unit_price(item_id: str) -> tuple[int | None, str | None]:
    """Цена 1 шт топлива и база расчёта: sales50 → sales10 → avg → стакан/выкуп."""
    h = store.history.get(item_id) or {}
    for key, basis in (("recent50_unit_price", "sales50"),
                       ("recent_unit_price", "sales10"),
                       ("avg_unit_price", "avg")):
        if h.get(key):
            return h[key], basis
    from app.services.craft import unit_buy_price   # локально: craft импортирует fuel
    p = unit_buy_price(item_id)
    return (p, "market") if p else (None, None)


def sources(profile: dict | None = None) -> list[dict]:
    """Все источники энергии с ценой за 1000 ед., дешёвые первыми.

    profile задан — каждому источнику проставляется available по улучшениям
    генератора в профиле (базовый ДВС доступен всегда).
    """
    feats = set((profile or {}).get("features") or [])
    out = []
    for iid, (group, fallback) in FUEL_ITEMS.items():
        it = db.item(iid)
        if not it:
            continue
        energy = db.energy_value(iid) or fallback
        price, basis = unit_price(iid)
        need = GROUP_FEATURE[group]
        out.append({
            "id": iid, "name": it["name"], "icon": it["icon"], "color": it["color"],
            "group": group, "feature": need,
            "available": profile is None or need is None or need in feats,
            "energy": round(energy), "price": price, "basis": basis,
            "per_1k": round(price / energy * 1000, 1) if price else None,
        })
    out.sort(key=lambda s: (s["per_1k"] is None, s["per_1k"] or 0))
    return out


def best(profile: dict | None = None) -> dict | None:
    """Самый выгодный ДОСТУПНЫЙ источник (profile=None — самый выгодный вообще)."""
    for s in sources(profile):
        if s["available"] and s["per_1k"] is not None:
            return s
    return None
