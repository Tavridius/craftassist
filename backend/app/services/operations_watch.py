"""Воркер раздела «Операции»: опрос сессий PvE-режима → operations.db.

Раз в OPS_POLL_MIN минут тянем свежие сессии из GET /{region}/operations/sessions
(сорт по date_finish desc — новые первыми), дедуп по id в БД. На каждом опросе
идём вглубь до OPS_MAX_PAGES страниц ИЛИ пока страница не перестанет приносить
новые сессии (догнали прошлый опрос). Первый запуск на пустой БД — бэкфилл на те
же OPS_MAX_PAGES страниц.

Нюанс доступа: eapi отдаёт эндпоинт только с app-токеном, demo-API его не
реализует (404). Значит данные копятся ТОЛЬКО на проде — на демо воркер тихо
простаивает (лог раз при смене состояния), UI показывает «накапливаем данные».
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.db import operations as ops
from app.services import auction, oauth

logger = logging.getLogger(__name__)


def _parse_ts(t) -> int | None:
    try:
        return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError, TypeError):
        return None


def _norm_participant(p: dict) -> dict:
    def _id(v):
        v = (v or "").strip() if isinstance(v, str) else v
        return v or None
    return {
        "username": p.get("username"),
        "armor_item": _id(p.get("armorItemId")),
        "armor_level": p.get("armorLevel"),
        "armor_class": (p.get("armorClass") or "").strip() or None,
        "prim_item": _id(p.get("primaryWeaponItemId")),
        "prim_level": p.get("primaryWeaponLevel"),
        "sec_item": _id(p.get("secondaryWeaponItemId")),
        "sec_level": p.get("secondaryWeaponLevel"),
        "deaths": p.get("death"),
        "mob_kills": p.get("mobKills"),
        "dmg_dealt": p.get("damageDealt"),
        "dmg_recv": p.get("damageReceived"),
    }


def _has_gear(sess: dict) -> bool:
    """Есть ли в сессии снаряжение хоть у одного участника. API отдаёт свежий
    забег с пустым составом и проставляет снаряжение через пару минут — такие
    сессии не сохраняем, дождёмся полной версии в следующем опросе."""
    return any(p.get("armor_item") or p.get("prim_item") for p in sess["parts"])


def _norm_session(s: dict) -> dict | None:
    sid = s.get("id")
    if sid is None:
        return None
    ts = _parse_ts(s.get("endTime")) or _parse_ts(s.get("startTime"))
    if ts is None:
        return None
    parts = [_norm_participant(p) for p in (s.get("participants") or [])]
    diff = int(s.get("difficulty") or 0)
    return {
        "id": int(sid), "ts": ts, "end_time": s.get("endTime"),
        "map": s.get("map"), "difficulty": diff, "tier": ops.tier_of(diff),
        "duration": s.get("sessionDurationSeconds"),
        "reward": s.get("difficultyReward"), "n": len(parts), "parts": parts,
    }


class OperationsWatch:
    def __init__(self) -> None:
        self._last_error: str | None = None

    async def _poll(self, client: httpx.AsyncClient) -> bool:
        """Один проход опроса. False — API не ответил (ретрай по расписанию)."""
        await oauth.ensure(client)
        have_data = ops.stats()["sessions"] > 0
        total_added = 0
        got_any = False
        for page in range(config.OPS_MAX_PAGES):
            res = await auction.fetch_operation_sessions(
                client, offset=page * config.OPS_PAGE_LIMIT, limit=config.OPS_PAGE_LIMIT)
            if res.get("error"):
                if self._last_error != res["error"]:
                    logger.warning("operations_watch: API error %s (page %d) — раздел "
                                   "копится только на проде с app-токеном", res["error"], page)
                    self._last_error = res["error"]
                return got_any
            got_any = True
            self._last_error = None
            raw = res.get("sessions") or []
            sessions = [n for n in (_norm_session(s) for s in raw) if n]
            if not sessions:
                break
            # сохраняем только сессии со снаряжением; свежие «пустые» пропускаем —
            # подхватим полными в следующем опросе (см. _has_gear)
            added = ops.add_sessions([s for s in sessions if _has_gear(s)])
            total_added += added
            # догнали прошлый опрос: страница не принесла новых ПОЛНЫХ сессий —
            # глубже старьё (на первом заполнении БД пусто — идём до OPS_MAX_PAGES)
            if added == 0 and have_data:
                break
            if len(raw) < config.OPS_PAGE_LIMIT:
                break

        if total_added:
            before = int(datetime.now(timezone.utc).timestamp()) - config.OPS_KEEP_DAYS * 86400
            ops.cleanup(before)
            logger.info("operations_watch: +%d new sessions (%s)", total_added, ops.stats())
        ops.set_meta("last_poll", datetime.now(timezone.utc).isoformat())
        return got_any

    async def loop(self) -> None:
        logger.info("operations_watch: loop started, poll=%dm, tiers 0-%d / %d-%d / %d+",
                    config.OPS_POLL_MIN, config.OPS_TIER_LOW_MAX,
                    config.OPS_TIER_LOW_MAX + 1, config.OPS_TIER_MID_MAX,
                    config.OPS_TIER_MID_MAX + 1)
        ops.purge_incomplete()   # чистим накопленные «пустые» — переберутся полными
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                try:
                    await self._poll(client)
                except Exception:
                    logger.exception("operations_watch: poll failed")
                await asyncio.sleep(config.OPS_POLL_MIN * 60)


opswatch = OperationsWatch()
