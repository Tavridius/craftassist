"""Патчноуты с форума EXBO: поллинг, санитизация HTML, зеркало картинок.

forum.exbo.net — Flarum с открытым JSON API. Тег `news-updates` («Обновления»)
содержит все патчноуты; include=firstPost отдаёт готовый contentHtml первого
поста. Мы: раз в PATCH_POLL_MIN тянем свежие темы, новые/правленные (маркер
lastPostedAt) инжестим — HTML прогоняется через санитайзер по белому списку,
картинки скачиваются в data/news_img/{id}/ (не зависим от их CDN), src
переписывается. При пустой базе — разовый бэкфилл всего тега (постранично,
с паузами: API публичный, но недокументированный — ведём себя вежливо).
"""
import asyncio
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app import config
from app.db import news

logger = logging.getLogger(__name__)

UA = {"User-Agent": "StalZone-Helper/1.0 (+https://stalzone-helper.ru)"}

# теги, которые сохраняем как есть (h1 понижается до h2 — заголовок страницы наш)
_ALLOWED = {"p", "br", "h2", "h3", "h4", "ul", "ol", "li", "blockquote",
            "strong", "b", "em", "i", "u", "s", "hr", "code", "pre",
            "table", "thead", "tbody", "tr", "th", "td"}
_VOID = {"br", "hr", "img"}


class _Sanitizer(HTMLParser):
    """Белый список тегов; a/img/iframe — с фильтрованными атрибутами.

    Скрипты/стили выбрасываются с содержимым, у остального чужого тега
    остаётся только текст. Картинки собираются в self.images для зеркала
    (src подменяется плейсхолдером __IMG{n}__ до скачивания).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.images: list[str] = []   # исходные URL по порядку
        self._skip = 0                # внутри script/style/невидимого
        self._a_stack: list[bool] = []  # True — настоящий <a>, False — деградировал в <span>

    def handle_starttag(self, tag, attrs):
        if self._skip:
            return
        if tag in ("script", "style", "noscript"):
            self._skip += 1
            return
        a = dict(attrs)
        if tag == "h1":
            tag = "h2"
        if tag in _ALLOWED:
            self.out.append(f"<{tag}>")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            real = href.startswith(("http://", "https://", "/"))
            self._a_stack.append(real)
            self.out.append(
                f'<a href="{_esc(href)}" target="_blank" rel="noopener nofollow">'
                if real else "<span>")
        elif tag == "img":
            src = (a.get("src") or "").strip()
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith(("http://", "https://")):
                # \x00 не переживает пользовательский текст — безопасный плейсхолдер
                self.out.append(f"\x00IMG{len(self.images)}\x00")
                self.images.append(src)
        elif tag == "iframe":
            src = (a.get("src") or "").strip()
            if src.startswith("//"):
                src = "https:" + src
            # разрешаем только видео VK (s9e mediaembed патчноутов)
            if re.match(r"^https://vk\.com/video_ext\.php\?", src):
                self.out.append(
                    f'<div class="patch-video"><iframe src="{_esc(src)}" '
                    f'loading="lazy" allowfullscreen></iframe></div>')

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "h1":
            tag = "h2"
        if tag in _ALLOWED and tag not in _VOID:
            self.out.append(f"</{tag}>")
        elif tag == "a":
            real = self._a_stack.pop() if self._a_stack else True
            self.out.append("</a>" if real else "</span>")

    def handle_data(self, data):
        if not self._skip and data:
            self.out.append(_esc(data))


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


_EMPTY_P = re.compile(r"<p>\s*</p>")
_TAGS = re.compile(r"<[^>]+>")


def sanitize(html: str) -> tuple[str, list[str]]:
    p = _Sanitizer()
    p.feed(html or "")
    p.close()
    out = _EMPTY_P.sub("", "".join(p.out))
    return out, p.images


def _plain(html: str, limit: int = 220) -> str:
    txt = " ".join(_TAGS.sub(" ", html).split())
    txt = (txt.replace("&amp;", "&").replace("&lt;", "<")
              .replace("&gt;", ">").replace("&quot;", '"'))
    return txt[:limit].rstrip() + ("…" if len(txt) > limit else "")


class PatchWatch:
    def __init__(self) -> None:
        self.last_poll: float | None = None
        self.errors = 0

    # ---------- HTTP ----------
    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        try:
            r = await client.get(url, headers=UA, timeout=30.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.errors += 1
            logger.warning("patch_watch: GET %s failed: %s", url, e)
            return None

    def _list_url(self, offset: int = 0, limit: int = 20) -> str:
        # скобки Flarum-фильтров обязаны быть URL-encoded
        return (f"{config.FORUM_API}/api/discussions?filter%5Btag%5D={config.PATCH_TAG}"
                f"&sort=-createdAt&page%5Blimit%5D={limit}&page%5Boffset%5D={offset}"
                f"&include=firstPost")

    # ---------- инжест ----------
    async def _mirror_images(self, client: httpx.AsyncClient, pid: int,
                             urls: list[str]) -> list[str]:
        """Скачиваем картинки в data/news_img/{pid}/, возвращаем локальные src.
        Неудачная загрузка — оставляем внешний URL (лучше hotlink, чем дыра)."""
        out = []
        dest = config.NEWS_IMG_DIR / str(pid)
        for n, url in enumerate(urls):
            ext = Path(url.split("?")[0]).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                ext = ".png"
            local = dest / f"{n}{ext}"
            if local.exists():
                out.append(f"/news-img/{pid}/{n}{ext}")
                continue
            try:
                r = await client.get(url, headers=UA, timeout=30.0,
                                     follow_redirects=True)
                r.raise_for_status()
                dest.mkdir(parents=True, exist_ok=True)
                local.write_bytes(r.content)
                out.append(f"/news-img/{pid}/{n}{ext}")
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning("patch_watch: image %s failed: %s", url, e)
                out.append(url)
        return out

    async def _ingest(self, client: httpx.AsyncClient, disc: dict,
                      posts: dict[str, dict]) -> None:
        pid = int(disc["id"])
        a = disc["attributes"]
        first_id = (((disc.get("relationships") or {}).get("firstPost") or {})
                    .get("data") or {}).get("id")
        post = posts.get(str(first_id))
        if not post:
            return
        html = (post.get("attributes") or {}).get("contentHtml") or ""
        clean, img_urls = sanitize(html)
        local = await self._mirror_images(client, pid, img_urls)
        for n, src in enumerate(local):
            clean = clean.replace(f"\x00IMG{n}\x00",
                                  f'<img src="{_esc(src)}" loading="lazy" alt="">')
        clean = re.sub(r"\x00IMG\d+\x00", "", clean)  # на случай несоответствия
        title = " ".join((a.get("title") or f"Патч {pid}").split())
        news.upsert_patch(
            pid, title, a.get("createdAt") or "", clean, _plain(clean),
            f"{config.FORUM_API}/d/{pid}", a.get("lastPostedAt"))
        logger.info("patch_watch: ingested %s «%s» (%d imgs)", pid, title, len(img_urls))

    async def _poll_page(self, client: httpx.AsyncClient, offset: int,
                         limit: int = 20) -> tuple[int, bool]:
        """Одна страница списка: инжестим новые/правленные. -> (кол-во тем, есть ли ещё)."""
        doc = await self._get_json(client, self._list_url(offset, limit))
        if not doc:
            return 0, False
        posts = {p["id"]: p for p in doc.get("included", []) if p.get("type") == "posts"}
        for disc in doc.get("data", []):
            try:
                pid = int(disc["id"])
                a = disc["attributes"]
                known = news.patch_meta(pid)
                if known and known.get("last_posted") == a.get("lastPostedAt"):
                    continue
                await self._ingest(client, disc, posts)
            except Exception:
                logger.exception("patch_watch: ingest %s failed", disc.get("id"))
        return len(doc.get("data", [])), bool((doc.get("links") or {}).get("next"))

    async def loop(self) -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            # бэкфилл всего тега при (почти) пустой базе — разово, постранично
            if news.patch_count() < 5:
                logger.info("patch_watch: backfill start")
                offset = 0
                while True:
                    n, more = await self._poll_page(client, offset, 20)
                    offset += n
                    if not more or n == 0 or offset >= config.PATCH_BACKFILL_MAX:
                        break
                    await asyncio.sleep(1.5)
                logger.info("patch_watch: backfill done (%d patches)", news.patch_count())
            while True:
                try:
                    await self._poll_page(client, 0, 20)
                    self.last_poll = asyncio.get_event_loop().time()
                except Exception:
                    logger.exception("patch_watch: poll failed")
                await asyncio.sleep(config.PATCH_POLL_MIN * 60)


pwatch = PatchWatch()
