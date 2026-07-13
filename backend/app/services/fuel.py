"""Топливо генератора убежища: цена энергии и выгодные источники заправки.

Крафт жжёт энергию верстака; энергию даёт генератор, сжигая топливо. Каждому
топливу в БД предмета прописан номинал (core.tooltip.energy). Метрика выгоды —
рублей за 1000 ед. энергии; цена топлива — медиана 50 последних продаж аука
(fallback: медиана 10 → средняя → закупка по стакану → мин. выкуп).

Группы соответствуют апгрейдам генератора (ключи фич — из requirements рецептов):
базовый ДВС жжёт жидкое топливо и газ, станции батарей/аномального
преобразования открываются улучшениями и отмечаются в профиле убежища.
"""
from app.db.index import db
from app.services.price_store import store

# фичи-улучшения генератора (есть в db.hideout_features и в профиле пользователя)
FEATURE_BATTERY = "generator_energy_source_battery"
FEATURE_ANOMAL = "generator_energy_source_anomal"
GENERATOR_FEATURES = [FEATURE_BATTERY, FEATURE_ANOMAL]

# id топлива -> (группа, номинал-fallback, если в json предмета нет energy)
FUEL_ITEMS: dict[str, tuple[str, float]] = {
    "g0vn":  ("base", 2000),      # Канистра с бензином
    "z7lk":  ("base", 2500),      # Канистра с дизелем
    "5dgo":  ("base", 2500),      # Баллон с пропаном
    "y7j0":  ("base", 3000),      # Баллон с метаном
    "w3923": ("battery", 1000),   # Сменный аккумулятор
    "55621": ("battery", 5000),   # Армейский аккумулятор
    "401j":  ("battery", 5000),   # Батарея холодного синтеза
    "7l127": ("anomal", 50),      # Аномальная пыль
    "1rl71": ("anomal", 250),     # Пыль изменения
    "96z2z": ("anomal", 1250),    # Хронопыль
    "3gqkg": ("anomal", 5000),    # Нестабильная аномальная батарея
    "1rl61": ("anomal", 40000),   # Хроносфера
}

GROUP_FEATURE = {"base": None, "battery": FEATURE_BATTERY, "anomal": FEATURE_ANOMAL}


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
