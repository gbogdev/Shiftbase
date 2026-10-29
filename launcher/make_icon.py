"""Generates the app icon: three white "shift bars" on an indigo rounded square. Run: python launcher/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG = "#4a56e2"
BARS = [(56, 70, 176, 102), (92, 112, 200, 144), (56, 154, 148, 186)]  # on a 256 grid
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(px):
    s = 8  # supersample for smooth edges
    big = px * s
    k = big / 256
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=56 * k, fill=BG)
    for x0, y0, x1, y1 in BARS:
        d.rounded_rectangle((x0 * k, y0 * k, x1 * k, y1 * k), radius=16 * k, fill="white")
    return img.resize((px, px), Image.LANCZOS)


render(256).save(ROOT / "launcher" / "shiftbase.ico", sizes=[(n, n) for n in SIZES])
render(256).save(ROOT / "launcher" / "icon-preview.png")
bars = "".join(f'<rect x="{a}" y="{b}" width="{c - a}" height="{d - b}" rx="16" fill="#fff"/>' for a, b, c, d in BARS)
(ROOT / "frontend" / "public" / "favicon.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="56" fill="{BG}"/>{bars}</svg>\n',
    encoding="utf-8")
print("ok")
