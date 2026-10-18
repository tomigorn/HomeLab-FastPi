#!/usr/bin/env python3
"""One-off: build the avatar gallery (6 rows of human-made art, no AI art).

Row 1 comes from Microsoft Fluent Emoji (MIT, 3D PNGs centred on a soft square);
rows 2-6 are DiceBear styles rendered by the DiceBear HTTP API at 512x512.
Writes app/img/<id>.png, app/gallery.json (flat list) and app/groups.json
(ordered rows), and deletes images no longer in the gallery. Re-run only to
change the gallery; the output is committed. Needs Pillow (dev only).
"""
import colorsys, io, json, pathlib, urllib.parse, urllib.request
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/"
DICEBEAR = "https://api.dicebear.com/9.x/{style}/png?seed={seed}&size=512&backgroundColor={bg}"
SIZE, EMOJI = 512, 360

GROUPS = [
    ("animals3d", "3D animals"), ("illustrated", "Illustrated characters"),
    ("cartoon", "Cartoon faces"), ("pixel", "Pixel art"),
    ("robots", "Robots"), ("sketch", "Sketch people"),
]

# (id, display name, upstream folder, background colour)
ANIMALS = [
    ("fox", "Fox", "Fox", "#FFD8B5"), ("owl", "Owl", "Owl", "#E3D5C3"),
    ("panda", "Panda", "Panda", "#D9F2D0"), ("tiger", "Tiger", "Tiger face", "#FFE3A3"),
    ("cat", "Cat", "Cat face", "#FFE9C7"), ("dog", "Dog", "Dog face", "#E8DCCB"),
    ("penguin", "Penguin", "Penguin", "#CFE8F7"), ("unicorn", "Unicorn", "Unicorn", "#EBD9FA"),
]

# (group, style, id prefix, [(seed, display name), ...])
DICE = [
    ("illustrated", "adventurer", "adventurer", [
        ("adv1", "Zap"), ("adv3", "Skye"), ("adv5", "Plum"), ("adv9", "Pigtails")]),
    ("illustrated", "lorelei", "lorelei", [
        ("lor1", "Grin"), ("lor6", "Curly"), ("lor9", "Bun"), ("lor15", "Beardie")]),
    ("cartoon", "avataaars", "avataaars", [
        ("ava0", "Sunny"), ("ava1", "Blazer"), ("ava6", "Frosty"), ("ava9", "Cheeky")]),
    ("cartoon", "big-smile", "big-smile", [
        ("big1", "Gold"), ("big3", "Clown"), ("big6", "Shades"), ("big9", "Braids")]),
    ("pixel", "pixel-art", "pixel", [
        ("pix0", "Pixel Knight"), ("pix1", "Lime"), ("pix4", "Sprout"), ("pix5", "Specs"),
        ("pix9", "Rusty"), ("pix12", "Flame"), ("pix13", "Goggles"), ("pix14", "Spike")]),
    ("robots", "bottts", "robot", [
        ("bot0", "Bolt"), ("bot1", "Cyclops"), ("bot2", "Visor"), ("bot5", "Rusty Bot"),
        ("bot7", "Pulse"), ("bot9", "Slate"), ("bot12", "Azure"), ("bot14", "Chatter")]),
    ("sketch", "open-peeps", "peep", [
        ("ope0", "Sketchy"), ("ope4", "Scarf"), ("ope7", "Afro"), ("ope14", "Redhead")]),
    ("sketch", "notionists", "notion", [
        ("not1", "Quiff"), ("not5", "Spiky"), ("not7", "Cap"), ("not10", "Bob")]),
]


def pastel(i, n):
    """Distinct soft colour: hue stepped around the wheel."""
    r, g, b = colorsys.hls_to_rgb((i * 0.381966) % 1.0, 0.86, 0.6)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "avatar-picker-build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def fetch(folder):
    name = folder.lower().replace(" ", "_") + "_3d.png"
    return Image.open(io.BytesIO(get(BASE + urllib.parse.quote(f"{folder}/3D/{name}")))).convert("RGBA")

def main():
    out = ROOT / "app" / "img"; out.mkdir(parents=True, exist_ok=True)
    gallery = []
    for aid, label, folder, color in ANIMALS:
        emoji = fetch(folder).resize((EMOJI, EMOJI), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), color)
        off = (SIZE - EMOJI) // 2
        canvas.alpha_composite(emoji, (off, off))
        canvas.convert("RGB").save(out / f"{aid}.png", optimize=True)
        gallery.append({"id": aid, "name": label, "file": f"{aid}.png", "color": color, "group": "animals3d"})
        print("ok", aid)
    n = 0
    for group, style, prefix, items in DICE:
        for k, (seed, label) in enumerate(items, 1):
            color = pastel(n, 40); n += 1
            aid = f"{prefix}-{k}"
            img = Image.open(io.BytesIO(get(DICEBEAR.format(
                style=style, seed=urllib.parse.quote(seed), bg=color[1:])))).convert("RGB")
            if img.size != (SIZE, SIZE):
                img = img.resize((SIZE, SIZE), Image.LANCZOS)
            img.save(out / f"{aid}.png", optimize=True)
            gallery.append({"id": aid, "name": label, "file": f"{aid}.png", "color": color, "group": group})
            print("ok", aid)
    keep = {g["file"] for g in gallery}
    for f in out.iterdir():
        if f.suffix == ".png" and f.name not in keep:
            f.unlink(); print("removed", f.name)
    (ROOT / "app" / "gallery.json").write_text(json.dumps(gallery, indent=2) + "\n")
    (ROOT / "app" / "groups.json").write_text(
        json.dumps([{"id": i, "label": l} for i, l in GROUPS], indent=2) + "\n")

if __name__ == "__main__":
    main()
