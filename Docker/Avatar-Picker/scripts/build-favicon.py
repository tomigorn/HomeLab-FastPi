#!/usr/bin/env python3
"""Render the tab icons in app/static/ from the same shapes as favicon.svg (navy disc,
gold glow, navy person), which is the SSO dashboard's Avatar Picker icon. Needs Pillow."""
import pathlib
from PIL import Image, ImageChops, ImageDraw

STATIC = pathlib.Path(__file__).resolve().parents[1] / "app" / "static"
NAVY, RIM = (11, 22, 40), (255, 243, 196)
GLOW = [(0.0, (255, 231, 163)), (0.6, (233, 185, 73)), (1.0, (192, 136, 82))]


def glow(n):
    """Radial gradient centred at (0.5, 0.35) with radius 0.65 of the 64-unit box, like the SVG."""
    img = Image.new("RGB", (n, n)); px = img.load()
    cx, cy, r = 0.5 * n, 0.35 * n, 0.65 * n
    for y in range(n):
        for x in range(n):
            t = min(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / r, 1.0)
            for (t0, c0), (t1, c1) in zip(GLOW, GLOW[1:]):
                if t <= t1:
                    f = (t - t0) / (t1 - t0)
                    px[x, y] = tuple(round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
                    break
    return img


def icon(size):
    n = size * 8; u = n / 64
    def circle(d, cx, cy, r, **kw):
        d.ellipse(((cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u), **kw)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    circle(ImageDraw.Draw(out), 32, 32, 30, fill=NAVY)
    disc = Image.new("L", (n, n), 0); circle(ImageDraw.Draw(disc), 32, 32, 27, fill=255)
    inner = glow(n).convert("RGBA"); d = ImageDraw.Draw(inner)
    circle(d, 32, 25, 9.5, fill=NAVY)
    d.chord((12 * u, 38 * u, 52 * u, 82 * u), 180, 360, fill=NAVY)
    d.rectangle((12 * u, 60 * u, 52 * u, n), fill=NAVY)
    out.paste(inner, (0, 0), disc)
    ring = Image.new("L", (n, n), 0); circle(ImageDraw.Draw(ring), 32, 32, 27, outline=204, width=round(1.5 * u))
    out.paste(Image.new("RGBA", (n, n), RIM), (0, 0), ImageChops.multiply(ring, disc.point(lambda v: 255)))
    return out.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    icon(32).save(STATIC / "favicon-32.png", optimize=True)
    # iOS draws touch icons on its own square; give it the navy background edge to edge
    touch = Image.new("RGBA", (180, 180), NAVY + (255,)); touch.alpha_composite(icon(180))
    touch.convert("RGB").save(STATIC / "apple-touch-icon.png", optimize=True)
