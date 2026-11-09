"""Telegram-бот канала t.me/stalzone_helper: патчи, выбросы и промокоды.

Патч — обычный пост: заголовок, анонс и ссылка на страницу патча на сайте.
Выброс — тихое сообщение (без звука), которое бот удаляет через
TG_EMISSION_TTL_MIN: выбросы идут каждые 40-120 минут, и без удаления канал
превратился бы в ленту тревог поверх постов. Удаление переживает рестарт:
ожидающие удаления сообщения лежат в data/tg_bot.json вместе с дедупом.

Промокод — пост сразу после добавления кода в /dev/promo (реферальный код
владельца в канал не идёт, он только на сайте). Пока код действует, пост
закреплён; правка кода на сайте правит пост; истёк или удалён — пост
удаляется. Telegram не даёт удалять сообщения старше 48 часов, поэтому
такой пост бот вместо удаления помечает «истёк» и открепляет. Сроки и id
постов лежат в data/tg_bot.json: строка промокода из promos.db при истечении
удаляется, и без своей копии бот не узнал бы, какой пост снимать.

Разовый анонс «промокоды теперь в канале» (сводка) перечисляет все
действующие коды одним постом; когда код из сводки истекает, бот правит
сводку, а не удаляет её.

Без TG_BOT_TOKEN всё молчит. Бот должен быть админом канала с правами
«публикация сообщений», «удаление сообщений» и «редактирование сообщений»
(последнее Telegram требует для закрепа в канале).
"""
import asyncio
import html
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import httpx

from app import config

logger = logging.getLogger(__name__)

PROMO_UTM = "?utm_source=telegram&utm_medium=bot&utm_campaign=promo"
PROMO_DESC_MAX = 900         # символов разметки описания; длиннее — режем до плоского текста


class _TgHtml(HTMLParser):
    """HTML описания промокода (пишут админы под /promo) → подмножество разметки
    Telegram: b/i/u/s/code/a остаются, абзацы и пункты списка — переносами,
    остальное (картинки, div, span) — только текст."""
    KEEP = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u",
            "s": "s", "del": "s", "code": "code"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.KEEP:
            self.out.append(f"<{self.KEEP[tag]}>")
            self.stack.append(self.KEEP[tag])
        elif tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if href.startswith("/"):
                href = config.SITE_URL + href
            if re.match(r"^https?://", href):
                self.out.append(f'<a href="{html.escape(href)}">')
                self.stack.append("a")
            else:
                self.stack.append("")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n• ")
        elif tag in ("p", "ul", "ol", "h2", "h3", "h4", "blockquote", "div"):
            self.out.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.KEEP or tag == "a":
            if self.stack:
                t = self.stack.pop()
                if t:
                    self.out.append(f"</{t}>")
        elif tag in ("p", "ul", "ol", "h2", "h3", "h4", "blockquote", "div"):
            self.out.append("\n\n")

    def handle_data(self, data):
        self.out.append(html.escape(re.sub(r"\s+", " ", data), quote=False))

    def result(self) -> str:
        while self.stack:                       # незакрытые теги — Telegram отверг бы весь пост
            t = self.stack.pop()
            if t:
                self.out.append(f"</{t}>")
        s = "".join(self.out)
        s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


def promo_desc(desc: str) -> str:
    """Описание промокода для поста: разметка Telegram, не длиннее PROMO_DESC_MAX."""
    if not desc.strip():
        return ""
    p = _TgHtml()
    p.feed(desc)
    p.close()
    s = p.result()
    if len(s) <= PROMO_DESC_MAX:
        return s
    plain = html.unescape(re.sub(r"<[^>]+>", "", s))
    return html.escape(plain[:PROMO_DESC_MAX - 1].rstrip() + "…", quote=False)


def promo_until(exp: str) -> str:
    """'2026-11-18T23:59' → 'до 18.11 включительно'; '' → 'бессрочно'."""
    if not exp:
        return "бессрочно"
    try:
        t = datetime.strptime(exp, "%Y-%m-%dT%H:%M")
    except ValueError:
        return f"до {exp}"
    if t.strftime("%H:%M") == "23:59":
        return f"до {t:%d.%m} включительно"
    return f"до {t:%d.%m %H:%M} МСК"


def _promo_expired(exp: str) -> bool:
    """Та же граница, что у promos._purge_expired_locked: минута истечения прошла."""
    return bool(exp) and exp < datetime.now(MSK).strftime("%Y-%m-%dT%H:%M")

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
        self.promo_posts: dict[str, dict] = {}  # id промокода → {"mid": message_id, "exp": expires_at}
        self.digest: dict | None = None     # сводка: {"mid", "items": [снимки кодов], "pinned"}
        self.digest_sent: float | None = None   # ts разового анонса — второй раз не шлём
        self.upd_offset = 0                 # getUpdates: ищем там служебку «закрепил»
        self.sent = 0
        self.errors = 0
        self._promo_lock = asyncio.Lock()   # правки промо-постов идут и из API, и из cleanup_loop

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
        self.promo_posts = dict(d.get("promos") or {})
        self.digest = d.get("digest") or None
        self.digest_sent = d.get("digest_sent")
        self.upd_offset = int(d.get("upd_offset") or 0)

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(
                {"patches": self.patches[-KEEP:], "emissions": self.emissions[-KEEP:],
                 "pending": self.pending, "promos": self.promo_posts,
                 "digest": self.digest, "digest_sent": self.digest_sent,
                 "upd_offset": self.upd_offset}, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("tg_bot: save failed: %s", e)

    async def _call(self, method: str, payload: dict) -> dict | None:
        url = f"{config.TG_API_BASE}/bot{config.TG_BOT_TOKEN}/{method}"
        proxy = f"socks5://{config.TG_SOCKS}" if config.TG_SOCKS else None
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=20.0, proxy=proxy) as client:
                r = await client.post(url, json=payload)
            d = r.json()
            if not d.get("ok"):
                # правка тем же текстом: для нас это успех, а не ошибка
                if "message is not modified" in str(d.get("description")):
                    return True
                self.errors += 1
                logger.warning("tg_bot: %s failed: %s", method, d.get("description"))
                return None
            return d.get("result")
        except Exception as e:                     # noqa: BLE001 — бот не должен ронять вотчеры
            self.errors += 1
            # у таймаутов httpx пустой str(e) — без имени класса в логе было «failed: »
            logger.warning("tg_bot: %s failed: %s %s", method, type(e).__name__, e)
            return None

    async def send(self, text: str, silent: bool = False, preview: bool = True,
                   markup: dict | None = None) -> int | None:
        payload = {
            "chat_id": config.TG_CHANNEL, "text": text, "parse_mode": "HTML",
            "disable_notification": silent,
            "link_preview_options": {"is_disabled": not preview},
        }
        if markup:
            payload["reply_markup"] = markup
        res = await self._call("sendMessage", payload)
        if res:
            self.sent += 1
            return res.get("message_id")
        return None

    async def _edit(self, mid: int, text: str, markup: dict | None = None) -> bool:
        payload = {"chat_id": config.TG_CHANNEL, "message_id": mid, "text": text,
                   "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
        if markup:                          # без reply_markup Telegram снимает кнопку
            payload["reply_markup"] = markup
        return bool(await self._call("editMessageText", payload))

    async def _pin(self, mid: int) -> bool:
        ok = await self._call("pinChatMessage", {"chat_id": config.TG_CHANNEL, "message_id": mid,
                                                 "disable_notification": True})
        if ok:
            await self._drop_pin_notice(mid)
        return bool(ok)

    async def _unpin(self, mid: int) -> None:
        await self._call("unpinChatMessage", {"chat_id": config.TG_CHANNEL, "message_id": mid})

    async def _drop_pin_notice(self, mid: int) -> None:
        """Закреп в канале оставляет в ленте служебку «… закрепил(а) …». Её id
        Bot API не возвращает, зато она приходит боту апдейтом channel_post с
        pinned_message — находим именно её и удаляем. Не нашли — служебка
        остаётся, это не ошибка."""
        for _ in range(3):
            await asyncio.sleep(1.5)
            ups = await self._call("getUpdates", {"offset": self.upd_offset, "timeout": 0,
                                                  "allowed_updates": ["channel_post"]})
            if not isinstance(ups, list):
                return
            found = None
            for u in ups:
                self.upd_offset = max(self.upd_offset, u.get("update_id", 0) + 1)
                post = u.get("channel_post") or {}
                if (post.get("pinned_message") or {}).get("message_id") == mid:
                    found = post.get("message_id")
            self._save()
            if found:
                await self._call("deleteMessage", {"chat_id": config.TG_CHANNEL,
                                                   "message_id": found})
                return

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

    # ---------- промокоды ----------
    @staticmethod
    def _promo_link(text: str) -> str:
        url = f"{config.SITE_URL}/promo{PROMO_UTM}"
        return f'<a href="{html.escape(url)}">{text}</a>'

    @staticmethod
    def _promo_markup(p: dict) -> dict | None:
        url = p.get("url") or ""
        return {"inline_keyboard": [[{"text": "Забрать", "url": url}]]} if url else None

    def _promo_text(self, p: dict) -> str:
        head = "🎁 <b>Новый промокод</b>" if p.get("code") else "🎁 <b>Бесплатная раздача</b>"
        parts = [f"{head}\n<b>{html.escape(p['title'])}</b>"]
        if p.get("code"):
            parts.append(f"<code>{html.escape(p['code'])}</code>\n"
                         "<i>Нажмите на код, чтобы скопировать.</i>")
        desc = promo_desc(p.get("description") or "")
        if desc:
            parts.append(desc)
        parts.append(f"⏳ Действует {promo_until(p.get('expires_at') or '')}")
        parts.append(self._promo_link("Все промокоды на сайте"))
        return "\n\n".join(parts)

    def _promo_gone_text(self, title: str) -> str:
        return (f"<s>{html.escape(title)}</s>\n\n❌ Промокод больше не действует.\n\n"
                + self._promo_link("Действующие промокоды на сайте"))

    @staticmethod
    def _digest_item(p: dict) -> dict:
        return {"id": p["id"], "title": p["title"], "code": p.get("code") or "",
                "url": p.get("url") or "", "exp": p.get("expires_at") or ""}

    def _digest_text(self, items: list[dict]) -> str:
        s = ("📢 <b>Промокоды теперь приходят в канал</b>\n\n"
             "Как только на сайте появляется новый промокод, бот сразу публикует его здесь. "
             "Пока код действует, пост висит в закрепе, а когда срок выходит, пост убирается.")
        if items:
            s += "\n\n<b>Действуют сейчас:</b>"
            for i in sorted(items, key=lambda i: (i["exp"] == "", i["exp"])):
                what = []
                if i["code"]:
                    what.append(f"<code>{html.escape(i['code'])}</code>")
                if i["url"]:
                    what.append(f'<a href="{html.escape(i["url"])}">Забрать</a>')
                what.append(promo_until(i["exp"]))
                s += f"\n\n🎁 <b>{html.escape(i['title'])}</b>\n" + " · ".join(what)
        else:
            s += ("\n\n<i>Все коды из этого поста уже истекли. "
                  "Новые придут сюда отдельными постами.</i>")
        return s + "\n\n" + self._promo_link("Все промокоды и что они дают — на сайте")

    async def _remove_promo_post(self, key: str, title: str) -> None:
        """Снять пост промокода: удалить, а если Telegram не даёт (старше 48 ч) —
        пометить «не действует» и открепить."""
        e = self.promo_posts.pop(key, None)
        self._save()
        if not e:
            return
        if not await self._call("deleteMessage", {"chat_id": config.TG_CHANNEL,
                                                  "message_id": e["mid"]}):
            await self._edit(e["mid"], self._promo_gone_text(e.get("title") or title))
            await self._unpin(e["mid"])

    async def _refresh_digest(self) -> None:
        d = self.digest
        if not d:
            return
        await self._edit(d["mid"], self._digest_text(d["items"]), None)
        if not d["items"] and d.get("pinned"):
            await self._unpin(d["mid"])
            d["pinned"] = False
        self._save()

    async def promo_saved(self, p: dict, created: bool) -> None:
        """Промокод сохранён в /dev/promo. Новый — пост и закреп; известный — правка
        поста (или снятие, если код стал реферальным); код из сводки — правка сводки."""
        if not self.enabled:
            return
        key = str(p["id"])
        async with self._promo_lock:
            if key in self.promo_posts:
                if p.get("is_ref"):
                    await self._remove_promo_post(key, p["title"])
                else:
                    e = self.promo_posts[key]
                    await self._edit(e["mid"], self._promo_text(p), self._promo_markup(p))
                    e.update(exp=p.get("expires_at") or "", title=p["title"])
                    self._save()
            elif (created and config.TG_NOTIFY_PROMOS and not p.get("is_ref")
                  and not _promo_expired(p.get("expires_at") or "")):
                mid = await self.send(self._promo_text(p), preview=False,
                                      markup=self._promo_markup(p))
                if mid:
                    self.promo_posts[key] = {"mid": mid, "exp": p.get("expires_at") or "",
                                             "title": p["title"]}
                    self._save()
                    await self._pin(mid)
            d = self.digest
            if d and any(i["id"] == p["id"] for i in d["items"]):
                d["items"] = [i for i in d["items"] if i["id"] != p["id"]]
                if not p.get("is_ref"):
                    d["items"].append(self._digest_item(p))
                await self._refresh_digest()

    async def promo_deleted(self, pid: int) -> None:
        """Промокод удалён на сайте — снять его пост и вычеркнуть из сводки."""
        if not self.enabled:
            return
        async with self._promo_lock:
            if str(pid) in self.promo_posts:
                await self._remove_promo_post(str(pid), "")
            d = self.digest
            if d and any(i["id"] == pid for i in d["items"]):
                d["items"] = [i for i in d["items"] if i["id"] != pid]
                await self._refresh_digest()

    async def promo_digest(self, items: list[dict]) -> int | None:
        """Разовый анонс со всеми действующими кодами (без реферального). Закреплён,
        пока в нём есть живые коды."""
        async with self._promo_lock:
            if self.digest_sent or not self.enabled:
                return None
            snap = [self._digest_item(p) for p in items if not p.get("is_ref")]
            mid = await self.send(self._digest_text(snap), preview=False)
            if not mid:
                return None
            self.digest = {"mid": mid, "items": snap, "pinned": False}
            self.digest_sent = time.time()
            self._save()
            if snap and await self._pin(mid):
                self.digest["pinned"] = True
                self._save()
            return mid

    async def promo_tick(self) -> None:
        """Истёкшие коды: пост — снять, из сводки — вычеркнуть."""
        async with self._promo_lock:
            for key, e in list(self.promo_posts.items()):
                if _promo_expired(e.get("exp") or ""):
                    await self._remove_promo_post(key, e.get("title") or "")
            d = self.digest
            if d:
                keep = [i for i in d["items"] if not _promo_expired(i["exp"])]
                if len(keep) != len(d["items"]):
                    d["items"] = keep
                    await self._refresh_digest()

    async def cleanup_loop(self) -> None:
        """Раз в минуту: удаляет истёкшие сообщения о выбросах и снимает посты
        истёкших промокодов."""
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
            if self.enabled and (self.promo_posts or self.digest):
                try:
                    await self.promo_tick()
                except Exception:                  # noqa: BLE001 — цикл выбросов не должен встать
                    logger.exception("tg_bot: promo tick failed")
            await asyncio.sleep(60)

    def stats(self) -> dict:
        return {"enabled": self.enabled, "channel": config.TG_CHANNEL, "sent": self.sent,
                "errors": self.errors, "pending_deletes": len(self.pending),
                "promo_posts": len(self.promo_posts),
                "promo_digest_sent": bool(self.digest_sent)}


_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    """Фоновая отправка из API: ответ админке не ждёт Telegram (до 20 с через прокси)."""
    t = asyncio.create_task(coro)
    _tasks.add(t)

    def done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception():
            logger.error("tg_bot: background task failed", exc_info=t.exception())
    t.add_done_callback(done)


tgbot = TgBot()
