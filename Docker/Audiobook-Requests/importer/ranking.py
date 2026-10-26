"""Release policy for AudioBookRequest's Prowlarr results: language, unabridged, M4B first, newest upload, min 1 seeder."""
import re
from dataclasses import dataclass

from naming import MAM_CODES, language_folder

FORMATS = {"M4B": 0, "MP3": 1}
NEWEST_FLAGS = 5   # abr-newest-1 .. -5, scored in ABR (abr-setup.py)


@dataclass
class Prefs:
    language: str = "EN"
    unabridged: bool = True


def prefs_from_product(product):
    if not product:
        return Prefs()
    return Prefs(language_folder(product.get("language")) or "EN",
                 (product.get("format_type") or "unabridged").lower() != "abridged")


def _flags(title):
    m = re.search(r"\[([A-Z]{3}) / ([A-Z0-9]+)\]", title or "")
    return (MAM_CODES.get(m.group(1), "Other"), m.group(2)) if m else (None, None)


def _abridged(r):
    text = f"{r.get('title') or ''} {r.get('description') or ''}"
    return re.search(r"(?<!un)abridged", text, re.I) is not None


def apply_policy(results, prefs):
    kept = [r for r in results if (r.get("seeders") or 0) >= 1 or r.get("protocol") == "usenet"]
    if prefs.unabridged:
        kept = [r for r in kept if not _abridged(r)]
    langs = [_flags(r["title"])[0] for r in kept]
    if prefs.language in langs:
        kept = [r for r, lang in zip(kept, langs) if lang in (prefs.language, None)]
    formats = [_flags(r["title"])[1] for r in kept]
    if "M4B" in formats:
        kept = [r for r, f in zip(kept, formats) if f != "FLAC"]
    by_age = sorted(kept, key=lambda r: r.get("publishDate") or "", reverse=True)
    for i, r in enumerate(by_age[:NEWEST_FLAGS]):
        r["indexerFlags"] = list(r.get("indexerFlags") or []) + [f"abr-newest-{i + 1}"]
    return sorted(by_age, key=lambda r: FORMATS.get(_flags(r["title"])[1], 2))
