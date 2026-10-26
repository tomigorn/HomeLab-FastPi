"""Release policy for AudioBookRequest's Prowlarr results: language, unabridged, M4B first, VIP/freeleech, newest upload, min 1 seeder."""
import re
import urllib.parse
from dataclasses import dataclass

from naming import MAM_CODES, language_folder

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


def _vip(r):
    return "[VIP]" in (r.get("title") or "") or "freeleech" in [f.lower() for f in r.get("indexerFlags") or []]


def apply_policy(results, prefs, proxy_base=None):
    """Owner's order (2026-10-26). Filters: requested language only (no fallback), >= 1 seeder.
    Rank: requested abridgement (unabridged by default), M4B, VIP/freeleech, newest upload."""
    kept = [r for r in results if ((r.get("seeders") or 0) >= 1 or r.get("protocol") == "usenet")
            and _flags(r.get("title"))[0] == prefs.language]
    by_age = sorted(kept, key=lambda r: r.get("publishDate") or "", reverse=True)
    for i, r in enumerate(by_age):
        extra = [f"abr-newest-{i + 1}"] if i < NEWEST_FLAGS else []
        r["indexerFlags"] = list(r.get("indexerFlags") or []) + extra + (["abr-vip"] if _vip(r) else [])
        # ABR fetches the .torrent once more to read its hash; the pass-through answers from qBittorrent instead of MAM.
        if proxy_base and r.get("downloadUrl"):
            r["downloadUrl"] = f"{proxy_base}/torrent?guid={urllib.parse.quote(r.get('guid') or '', safe='')}"
    return sorted(by_age, key=lambda r: (_abridged(r) == prefs.unabridged,
                                         _flags(r["title"])[1] != "M4B", not _vip(r)))


def for_abr(results, prefs, proxy_base=None):
    """Only the winner: ABR re-sorts by its own fixed rules (FLAC > M4B, no abridged/VIP) and grabs its first entry."""
    return apply_policy(results, prefs, proxy_base)[:1]
