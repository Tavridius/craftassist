"""Render the STALZONE Helper Telegram avatars: one for the channel, one for the chat."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


SIZE = 1024
SCALE = 3
GREEN = "#71e991"
BRIGHT = "#dbffe3"


def box(coords):
    return tuple(round(value * SCALE) for value in coords)


def points(coords):
    return [tuple(round(v * SCALE) for v in p) for p in coords]


def background():
    image = Image.new("RGB", (SIZE * SCALE, SIZE * SCALE), "#09110c")
    draw = ImageDraw.Draw(image)

    # Subtle concentric field lines stay inside Telegram's circular crop.
    for radius, color, width in [
        (446, "#17291d", 2),
        (414, "#31563b", 4),
        (391, "#132719", 2),
    ]:
        draw.ellipse(box((512 - radius, 512 - radius, 512 + radius, 512 + radius)),
                     outline=color, width=width * SCALE)

    for x in range(128, 900, 48):
        draw.line(box((x, 170, x, 854)), fill="#0d1a11", width=SCALE)
    for y in range(170, 855, 48):
        draw.line(box((128, y, 896, y)), fill="#0d1a11", width=SCALE)
    return image.convert("RGBA")


def glow(image, draw_shape, radius):
    layer = Image.new("RGBA", image.size)
    draw_shape(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(radius * SCALE))
    return Image.alpha_composite(image, layer)


def prompt(draw, x, y, k):
    """Draw the site's >_ mark with its top-left at (x, y), scaled by k."""
    draw.line(points([(x, y), (x + 101 * k, y + 73 * k), (x, y + 146 * k)]),
              fill=BRIGHT, width=round(37 * k * SCALE), joint="curve")
    draw.line(box((x + 143 * k, y + 147 * k, x + 306 * k, y + 147 * k)),
              fill=GREEN, width=round(37 * k * SCALE))


def channel():
    # The bare >_ mark, as in the site favicon: the channel is the "voice"
    # of the project, so it gets the brand sign without decoration.
    image = background()
    k = 1.55
    x, y = 512 - 306 * k / 2, 512 - 147 * k / 2 - 8
    image = glow(image, lambda d: prompt(d, x, y, k), 34)
    image = glow(image, lambda d: prompt(d, x, y, k), 10)
    prompt(ImageDraw.Draw(image), x, y, k)
    return image


def chat():
    # The same mark inside a speech bubble tells the chat apart from the
    # channel in the Telegram chat list.
    image = background()
    bubble = [(282, 309), (742, 309), (781, 348), (781, 636),
              (742, 675), (464, 675), (365, 751), (379, 675),
              (282, 675), (243, 636), (243, 348)]
    # Overlap the first segment so the start corner gets a joint too.
    outline = points(bubble + bubble[:2])
    image = glow(image, lambda d: d.line(outline, fill=(104, 255, 150, 125),
                                         width=21 * SCALE, joint="curve"), 27)
    draw = ImageDraw.Draw(image)
    draw.polygon(points(bubble), fill="#102419")
    draw.line(outline, fill=GREEN, width=15 * SCALE, joint="curve")
    prompt(draw, 350, 422, 1)
    return image


output = Path(__file__).resolve().parents[1] / "assets"
output.mkdir(exist_ok=True)
for name, render in [("telegram-channel.png", channel), ("telegram-chat.png", chat)]:
    image = render().convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    image.save(output / name, optimize=True)
