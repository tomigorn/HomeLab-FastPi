"""Gallery thumbnails: <id>.<hash>.<width>.webp per avatar plus thumbs.json ({id: hash}).

Run in the image build (Dockerfile stage `thumbs`): python build_thumbs.py <app dir> <out dir>.
The hash covers the source PNG and the settings below, so a changed image gets a new URL.
"""
import hashlib, io, json, pathlib, sys
from PIL import Image

WIDTHS = (160, 320)
QUALITY = 82
PACK_DIRS = {None: "img", "local": "img-local"}
SETTINGS = f"webp q{QUALITY} m6 {WIDTHS}".encode()


def thumb(img, width):
    out = io.BytesIO()
    img.resize((width, width), Image.LANCZOS).save(out, "WEBP", quality=QUALITY, method=6)
    return out.getvalue()


def build(app_dir, out_dir):
    app_dir, out_dir = pathlib.Path(app_dir), pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest, keep = {}, {"thumbs.json"}
    for g in json.loads((app_dir / "gallery.json").read_text()):
        src = app_dir / PACK_DIRS.get(g.get("pack"), "img") / f"{g['id']}.png"
        if not src.is_file():
            continue
        data = src.read_bytes()
        h = hashlib.sha256(SETTINGS + data).hexdigest()[:10]
        names = {w: f"{g['id']}.{h}.{w}.webp" for w in WIDTHS}
        if not all((out_dir / n).is_file() for n in names.values()):
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
                for w, n in names.items():
                    (out_dir / n).write_bytes(thumb(im, w))
        manifest[g["id"]] = h
        keep.update(names.values())
    for f in out_dir.iterdir():
        if f.name not in keep:
            f.unlink()
    (out_dir / "thumbs.json").write_text(json.dumps(manifest, sort_keys=True))
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_thumbs.py <app dir> <out dir>")
    m = build(sys.argv[1], sys.argv[2])
    print(f"thumbs: {len(m)} avatars x {len(WIDTHS)} widths")
