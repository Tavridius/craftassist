"""Telegram-бот канала t.me/stalzone_helper: новые патчи и выбросы.

Патч — обычный пост: заголовок, анонс и ссылка на страницу патча на сайте.
Выброс — тихое сообщение (без звука), которое бот удаляет через
TG_EMISSION_TTL_MIN: выбросы идут каждые 40-120 минут, и без удаления канал
превратился бы в ленту тревог поверх постов. Удаление переживает рестарт:
ожидающие удаления сообщения лежат в data/tg_bot.json вместе с дедупом.

Без TG_BOT_TOKEN всё молчит. Бот должен быть админом канала с правами
«публикация сообщений» и «удаление сообщений».
"""
import asyncio
import html
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app import config

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
PATCH_MAX_AGE = 3 * 86400    # с; патч старше — не новость (правка старой темы, бэкфилл)
EMISSION_MAX_AGE = 15 * 60   # с; выброс, замеченный позже, уже почти кончился
EMISSION_GAP = 15 * 60       # с; API отдаёт старт с дрожью в секундах — ближе считаем тем же выбросом
KEEP = 200                   # сколько id патчей/стартов помнить для дедупа


class TgBot:
    def __init__(self) -> None:
        self.patches: list[int] = []        # уже отправленные патчи
        self.emissions: list[float] = []    # ts стартов, о которых сообщили
        self.pending: list[dict] = []       # {"id": message_id, "at": ts удаления}
        self.sent = 0
        self.errors = 0

    @property
    def enabled(self) -> bool:
        return bool(config.TG_BOT_TOKEN)

    @property
    def _path(self):
        return config.DATA_DIR / "tg_bot.json"

    def load(self) -> None:
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.patches = list(d.get("patches") or [])[-KEEP:]
        self.emissions = list(d.get("emissions") or [])[-KEEP:]
        self.pending = list(d.get("pending") or [])

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(
                {"patches": self.patches[-KEEP:], "emissions": self.emissions[-KEEP:],
                 "pending": self.pending}, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("tg_bot: save failed: %s", e)

    async def _call(self, method: str, payload: dict) -> dict | None:
        url = f"{config.TG_API_BASE}/bot{config.TG_BOT_TOKEN}/{method}"
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=20.0) as client:
                r = await client.post(url, json=payload)
            d = r.json()
            if not d.get("ok"):
                self.errors += 1
                logger.warning("tg_bot: %s failed: %s", method, d.get("description"))
                return None
            return d.get("result")
        except Exception as e:                     # noqa: BLE001 — бот не должен ронять вотчеры
            self.errors += 1
            logger.warning("tg_bot: %s failed: %s", method, e)
            return None

    async def send(self, text: str, silent: bool = False, preview: bool = True) -> int | None:
        res = await self._call("sendMessage", {
            "chat_id": config.TG_CHANNEL, "text": text, "parse_mode": "HTML",
            "disable_notification": silent,
            "link_preview_options": {"is_disabled": not preview},
        })
        if res:
            self.sent += 1
            return res.get("message_id")
        return None

    # ---------- патчи ----------
    async def patch(self, pid: int, title: str, anons: str, created_at: str) -> None:
        """Новый патч с форума EXBO. Зовёт patch_watch при инжесте ранее
        неизвестной темы; старые (бэкфилл, правка давней темы) отсекаем по дате."""
        if not (self.enabled and config.TG_NOTIFY_PATCHES) or pid in self.patches:
            return
        try:
            age = time.time() - datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            age = 0.0
        if age > PATCH_MAX_AGE:
            return
        self.patches.append(pid)            # до отправки: сбой сети не должен дать дубль на рестарте
        self._save()
        url = (f"{config.SITE_URL}/patches/{pid}"
               "?utm_source=telegram&utm_medium=bot&utm_campaign=patch")
        text = (f"🛠 <b>{html.escape(title)}</b>\n\n"
                f"{html.escape(anons)}\n\n"
                f'<a href="{html.escape(url)}">Патч целиком — на сайте</a>')
        await self.send(text)

    # ---------- выбросы ----------
    async def emission(self, start_iso: str) -> None:
        """Старт выброса. Зовёт emission_watch, когда в истории появился новый старт."""
        if not (self.enabled and config.TG_NOTIFY_EMISSIONS):
            return
        try:
            start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        except ValueError:
            return
        ts = start.timestamp()
        if time.time() - ts > EMISSION_MAX_AGE:
            return
        if any(abs(ts - t) < EMISSION_GAP for t in self.emissions):
            return
        self.emissions.append(ts)
        self._save()
        hhmm = start.astimezone(MSK).strftime("%H:%M")
        mid = await self.send(f"☢️ <b>Выброс начался в {hhmm} МСК.</b> Ищите укрытие.\n"
                              f"<i>Сообщение исчезнет через {config.TG_EMISSION_TTL_MIN} мин.</i>",
                              silent=True, preview=False)
        if mid:
            self.pending.append({"id": mid, "at": time.time() + config.TG_EMISSION_TTL_MIN * 60})
            self._save()

    async def cleanup_loop(self) -> None:
        """Удаляет истёкшие сообщения о выбросах (раз в минуту)."""
        self.load()
        while True:
            now = time.time()
            due = [p for p in self.pending if p["at"] <= now]
            if due and self.enabled:
                for p in due:
                    # удалённое руками или старше 48 ч Telegram не удалит — всё равно снимаем
                    await self._call("deleteMessage", {"chat_id": config.TG_CHANNEL,
                                                       "message_id": p["id"]})
                self.pending = [p for p in self.pending if p["at"] > now]
                self._save()
            await asyncio.sleep(60)

    def stats(self) -> dict:
        return {"enabled": self.enabled, "channel": config.TG_CHANNEL, "sent": self.sent,
                "errors": self.errors, "pending_deletes": len(self.pending)}


tgbot = TgBot()
