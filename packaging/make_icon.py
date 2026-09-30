# Developed by ::> Gehan Fernando
"""Draws src/assets/audio8d.ico: the sidebar's headphones on the app's purple."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "src" / "assets" / "audio8d.ico"
FONT = Path(r"C:\Windows\Fonts\SegoeIcons.ttf")
HEADPHONES = "\ue7f6"


def draw() -> Image.Image:
    """A rounded square with a diagonal purple-to-pink blend and white headphones."""
    blend = Image.new("RGBA", (SIZE, SIZE))
    pixels = blend.load()
    # A brand-new image always gives pixel access; this tells type checkers too
    assert pixels is not None
    start, end = (0x7B, 0x2F, 0xF7), (0xFF, 0x4F, 0xD8)
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * (SIZE - 1))
            pairs = zip(start, end, strict=True)
            pixels[x, y] = (*(round(lo + (hi - lo) * t) for lo, hi in pairs), 255)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), 56, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(blend, mask=mask)
    font = ImageFont.truetype(str(FONT), 168)
    ImageDraw.Draw(icon).text(
        (SIZE / 2, SIZE / 2 + 6), HEADPHONES, font=font, fill="white", anchor="mm"
    )
    return icon


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().save(OUT, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    print(OUT)
