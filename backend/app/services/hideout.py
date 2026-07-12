"""Сверка требований рецептов (перки/станки убежища) с профилем пользователя.

Профиль: {"perks": {perk_id: уровень}, "features": [ключи станков/фич]}.
Хранится в db/users.py (таблица profiles), редактируется на странице профиля.
"""
from app.db.index import db

PERK_MAX = 10  # шкала уровней навыка в игре (карточка рисует 10 пипов)


def _norm(profile: dict) -> tuple[dict, set]:
    perks = {k: int(v) for k, v in (profile.get("perks") or {}).items()}
    feats = set(profile.get("features") or [])
    return perks, feats


def variant_ok(req: dict, perks: dict, feats: set) -> bool:
    if any(perks.get(k, 0) < lvl for k, lvl in (req.get("perks") or {}).items()):
        return False
    return all(f in feats for f in (req.get("features") or []))


def check(req: dict, profile: dict) -> dict:
    """Детальная сверка одного варианта рецепта: что есть, чего не хватает."""
    perks, feats = _norm(profile)
    perk_rows = [{"id": k, "need": lvl, "have": perks.get(k, 0), "ok": perks.get(k, 0) >= lvl}
                 for k, lvl in (req.get("perks") or {}).items()]
    feat_rows = [{"id": f, "ok": f in feats} for f in (req.get("features") or [])]
    missing = sum(1 for r in perk_rows + feat_rows if not r["ok"])
    return {"ok": missing == 0, "missing": missing, "perks": perk_rows, "features": feat_rows}


def item_available(item_id: str, profile: dict) -> bool:
    """Хватает ли прокачки хотя бы на ОДИН вариант рецепта предмета."""
    perks, feats = _norm(profile)
    return any(variant_ok(r.get("requirements") or {}, perks, feats)
               for r in db.recipe_by_result.get(item_id, ()))


def validate_profile(payload: dict) -> dict:
    """Санитизация PUT /api/profile: только известные ключи, уровни 0..PERK_MAX."""
    known_perks = {p["id"] for p in db.hideout_perks}
    known_feats = set(db.hideout_features)
    perks = {}
    for k, v in (payload.get("perks") or {}).items():
        if k not in known_perks:
            continue
        try:
            lvl = max(0, min(PERK_MAX, int(v)))
        except (TypeError, ValueError):
            continue
        if lvl > 0:
            perks[k] = lvl
    feats = [f for f in dict.fromkeys(payload.get("features") or []) if f in known_feats]
    return {"perks": perks, "features": feats}
