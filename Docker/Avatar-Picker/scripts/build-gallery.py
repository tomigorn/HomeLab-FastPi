#!/usr/bin/env python3
"""One-off: build the avatar gallery from Microsoft Fluent Emoji (MIT).

Downloads the 3D PNG of each animal, centres it on a 512x512 soft-coloured
square and writes app/img/<id>.png plus app/gallery.json. Re-run only to change
the gallery; the output is committed. Needs Pillow (dev only).
"""
import io, json, pathlib, urllib.parse, urllib.request
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/"
SIZE, EMOJI = 512, 360

# (id, display name, upstream folder, background colour)
ANIMALS = [
    ("fox", "Fox", "Fox", "#FFD8B5"), ("owl", "Owl", "Owl", "#E3D5C3"),
    ("panda", "Panda", "Panda", "#D9F2D0"), ("tiger", "Tiger", "Tiger face", "#FFE3A3"),
    ("lion", "Lion", "Lion", "#FBE0B0"), ("koala", "Koala", "Koala", "#D6E4F0"),
    ("rabbit", "Rabbit", "Rabbit face", "#F8D7E3"), ("cat", "Cat", "Cat face", "#FFE9C7"),
    ("dog", "Dog", "Dog face", "#E8DCCB"), ("penguin", "Penguin", "Penguin", "#CFE8F7"),
    ("frog", "Frog", "Frog", "#D3F0C2"), ("monkey", "Monkey", "Monkey face", "#EAD7C2"),
    ("unicorn", "Unicorn", "Unicorn", "#EBD9FA"), ("dragon", "Dragon", "Dragon face", "#CDEFD9"),
    ("octopus", "Octopus", "Octopus", "#FAD3D3"), ("turtle", "Turtle", "Turtle", "#D7F0E4"),
    ("hedgehog", "Hedgehog", "Hedgehog", "#EFE2D2"), ("bear", "Bear", "Bear", "#E6D3C3"),
    ("wolf", "Wolf", "Wolf", "#DDE3EA"), ("raccoon", "Raccoon", "Raccoon", "#E1E1E8"),
    ("sloth", "Sloth", "Sloth", "#E9E2CF"), ("otter", "Otter", "Otter", "#D8E8EC"),
    ("whale", "Whale", "Spouting whale", "#CFE3FA"), ("butterfly", "Butterfly", "Butterfly", "#F3DDF7"),
]

def fetch(folder):
    name = folder.lower().replace(" ", "_") + "_3d.png"
    url = BASE + urllib.parse.quote(f"{folder}/3D/{name}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")

def main():
    out = ROOT / "app" / "img"; out.mkdir(parents=True, exist_ok=True)
    gallery = []
    for aid, label, folder, color in ANIMALS:
        emoji = fetch(folder).resize((EMOJI, EMOJI), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), color)
        off = (SIZE - EMOJI) // 2
        canvas.alpha_composite(emoji, (off, off))
        canvas.convert("RGB").save(out / f"{aid}.png", optimize=True)
        gallery.append({"id": aid, "name": label, "file": f"{aid}.png", "color": color})
        print("ok", aid)
    (ROOT / "app" / "gallery.json").write_text(json.dumps(gallery, indent=2) + "\n")

if __name__ == "__main__":
    main()
