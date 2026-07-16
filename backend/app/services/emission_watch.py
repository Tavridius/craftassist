"""Вотчер выбросов: копит историю стартов (API отдаёт только текущий/предыдущий).

GET /{region}/emission → {currentStart?, previousStart?, previousEnd?}.
Опрос раз в EMISSION_POLL_SEC через общий троттл аукциона (бюджет лимита один).
История стартов персистится в data/emissions.json — фронту отдаём последние.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.services import auction, oauth

logger = logging.getLogger(__name__)


class EmissionWatch:
    def __init__(self) -> None:
        self.current_start: str | None = None
        self.previous_start: str | None = None
        self.previous_end: str | None = None
        self.history: list[str] = []          # ISO-старты, новые первыми
        self.checked_at: str | None = None

    @property
    def _path(self):
        return config.DATA_DIR / "emissions.json"

    def load(self) -> None:
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            self.history = list(d.get("history") or [])[:50]
        except (OSError, ValueError):
            self.history = []

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps({"history": self.history[:50]}, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            logger.warning("emission save failed: %s", e)

    def _note(self, iso: str | None) -> bool:
        """Добавить старт в историю (сек-точность, дедуп). True — что-то новое."""
        if not iso:
            return False
        try:  # нормализуем до секунд, чтобы не плодить дубли из-за микросекунд
            t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            key = t.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except ValueError:
            return False
        if key in self.history:
            return False
        self.history.append(key)
        self.history.sort(reverse=True)
        del self.history[50:]
        return True

    def snapshot(self) -> dict:
        return {"current_start": self.current_start,
                "previous_start": self.previous_start,
                "previous_end": self.previous_end,
                "history": self.history[:15],
                "checked_at": self.checked_at}

    async def loop(self) -> None:
        self.load()
        url = f"{config.API_BASE}/{config.REGION}/emission"
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                try:
                    await auction._throttle()          # общий бюджет лимита с ауком
                    tok = oauth.token() or config.API_TOKEN
                    r = await client.get(
                        url, headers={"Authorization": f"Bearer {tok}"} if tok else {},
                        timeout=15.0)
                    if r.status_code == 200:
                        d = r.json()
                        self.current_start = d.get("currentStart")
                        self.previous_start = d.get("previousStart")
                        self.previous_end = d.get("previousEnd")
                        self.checked_at = datetime.now(timezone.utc).isoformat()
                        changed = self._note(self.current_start)
                        changed = self._note(self.previous_start) or changed
                        if changed:
                            self.save()
                    else:
                        logger.warning("emission HTTP %s", r.status_code)
                except Exception as e:                # noqa: BLE001 — вотчер не должен падать
                    logger.warning("emission poll failed: %s", e)
                await asyncio.sleep(config.EMISSION_POLL_SEC)


ewatch = EmissionWatch()
