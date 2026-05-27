import os
import random
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

PHOTOS_DIR = Path(os.getenv("PHOTOS_DIR", "/photos"))
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


def get_photos() -> list[Path]:
    return [f for f in PHOTOS_DIR.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONS]


@app.get("/random")
def random_photo():
    photos = get_photos()
    if not photos:
        return JSONResponse({"error": "no photos available"}, status_code=404)
    photo = random.choice(photos)
    return FileResponse(photo, media_type=MEDIA_TYPES.get(photo.suffix.lower(), "application/octet-stream"))


@app.get("/")
def list_photos(request: Request):
    photos = get_photos()
    base = str(request.base_url).rstrip("/")
    return [{"name": p.name, "url": f"{base}/photo/{p.name}"} for p in sorted(photos)]


@app.get("/photo/{name}")
def get_photo(name: str):
    photo = (PHOTOS_DIR / name).resolve()
    if not str(photo).startswith(str(PHOTOS_DIR.resolve())):
        return JSONResponse({"error": "not found"}, status_code=404)
    if not photo.is_file() or photo.suffix.lower() not in EXTENSIONS:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(photo, media_type=MEDIA_TYPES.get(photo.suffix.lower(), "application/octet-stream"))
