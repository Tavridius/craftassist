"""Сжатие зеркалируемых картинок патчноутов.

Форум EXBO отдаёт баннеры и скриншоты в исходном разрешении: страница патча от
22.07.2026 весила 47.9 МБ в 34 картинках (одна — 4.8 МБ), от 15.07 — 30.8 МБ.
На телефоне это 53.8% отказов при 10 секундах на странице (AUDIT-METRIKA-2026-07.md).
Ужимаем до ширины экрана и WebP.

Анимированные GIF переводим в анимированный WebP: их на зеркале два десятка,
но весят они до 19 МБ штука (патч «Новогодний ивент» — 44 МБ в трёх гифках).
"""
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_W = 1280          # шире телефона и ретины в вёрстке патча (.patch-article 860px)
QUALITY = 82
SUFFIX = ".webp"
# Кадры анимации приходится держать в памяти целиком (save_all требует список),
# поэтому ограничиваем суммарную площадь: 374 кадра 1080p — это под гигабайт RGB
# в контейнере. Что не влезло — остаётся исходным GIF.
MAX_ANIM_MPX = 250


def _pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:                       # без Pillow просто не сжимаем
        return None


def _anim_frames(Image, im) -> list:
    """Кадры анимации, ужатые по ширине. Пусто — значит анимация слишком
    объёмная, чтобы держать её в памяти: такую оставляем исходной."""
    from PIL import ImageSequence
    n = getattr(im, "n_frames", 1)
    w = min(im.width, MAX_W)
    h = round(im.height * w / im.width)
    if n * w * h > MAX_ANIM_MPX * 1e6:
        logger.info("imgopt: анимация %d кадров %dx%d — не ужимаем, слишком объёмно", n, w, h)
        return []
    out = []
    for frame in ImageSequence.Iterator(im):
        f = frame.convert("RGBA")
        if f.width > MAX_W:
            f = f.resize((w, h), Image.LANCZOS)
        out.append(f)
    return out


def compress(data: bytes, src_name: str = "") -> tuple[bytes, str] | None:
    """Ужать картинку. Возвращает (байты, расширение) либо None, если сжимать
    нечего или нельзя — вызывающий тогда сохраняет оригинал как есть."""
    Image = _pillow()
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        if getattr(im, "is_animated", False):
            frames = _anim_frames(Image, im)
            if not frames:
                return None
            frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:],
                           quality=QUALITY, method=4,      # method=6 на сотне кадров слишком долгий
                           duration=im.info.get("duration", 80),
                           loop=im.info.get("loop", 0))
        else:
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            if im.width > MAX_W:
                im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
            im.save(buf, "WEBP", quality=QUALITY, method=6)
    except Exception as e:
        logger.warning("imgopt: не смог сжать %s: %s", src_name or "<bytes>", e)
        return None
    out = buf.getvalue()
    if len(out) >= len(data):
        return None                           # исходник уже легче — не портим
    return out, SUFFIX


def compress_file(path: Path) -> tuple[Path, int, int] | None:
    """Сжать файл на диске в соседний .webp. Возвращает (новый путь, было, стало)."""
    data = path.read_bytes()
    res = compress(data, path.name)
    if not res:
        return None
    out, suffix = res
    dest = path.with_suffix(suffix)
    dest.write_bytes(out)
    return dest, len(data), len(out)
