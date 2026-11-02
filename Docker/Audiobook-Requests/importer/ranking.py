"""Release policy for AudioBookRequest's Prowlarr results: author, language, min 1 seeder; unabridged, narrator, M4B, VIP/freeleech, newest upload."""
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

from naming import MAM_CODES, language_folder

NEWEST_FLAGS = 5   # abr-newest-1 .. -5, scored in ABR (abr-setup.py)


@dataclass
class Prefs:
    language: str = "EN"
    unabridged: bool = True
    authors: tuple = ()     # the requested book's authors; empty = unknown, no author filter
    narrators: tuple = ()   # the requested edition's narrators (ranking only)


def _names(people):
    return tuple(p["name"] for p in people or [] if p.get("name"))


def prefs_from_product(product):
    if not product:
        return Prefs()
    return Prefs(language_folder(product.get("language")) or "EN",
                 (product.get("format_type") or "unabridged").lower() != "abridged",
                 _names(product.get("authors")), _names(product.get("narrators")))


_FOLD = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "þ": "th"})


def norm_name(name):
    """Case, accents, punctuation and spacing ignored: "J. R. R. Tolkien" == "J.R.R. Tolkien", "Jo Nesbø" == "jo nesbo"."""
    text = unicodedata.normalize("NFKD", (name or "").translate(_FOLD))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def release_authors(title):
    """MAM titles read "<title> by <author>, <author> [ENG / M4B]"; the last " by " before the flags."""
    m = re.match(r".* by (.+?) \[[A-Z]{3} / ", title or "")
    return [a for a in (norm_name(x) for x in re.split(r"[,;&]", m.group(1))) if a] if m else []


def _by_author(r, wanted):
    return not wanted or bool(wanted & set(release_authors(r.get("title"))))


def _flags(title):
    m = re.search(r"\[([A-Z]{3}) / ([A-Z0-9]+)\]", title or "")
    return (MAM_CODES.get(m.group(1), "Other"), m.group(2)) if m else (None, None)


def _abridged(r):
    text = f"{r.get('title') or ''} {r.get('description') or ''}"
    return re.search(r"(?<!un)abridged", text, re.I) is not None


def _vip(r):
    return "[VIP]" in (r.get("title") or "") or "freeleech" in [f.lower() for f in r.get("indexerFlags") or []]


def apply_policy(results, prefs, proxy_base=None, narrated=frozenset()):
    """Owner's order (2026-10-26, author + narrator 2026-11-02). Filters: one of the book's authors (when known), requested language only
    (no fallback), >= 1 seeder. Rank: requested abridgement (unabridged by default), requested narrator (guids in `narrated`), M4B,
    VIP/freeleech, newest upload."""
    wanted = {a for a in map(norm_name, prefs.authors) if a}
    kept = [r for r in results if ((r.get("seeders") or 0) >= 1 or r.get("protocol") == "usenet")
            and _flags(r.get("title"))[0] == prefs.language and _by_author(r, wanted)]
    by_age = sorted(kept, key=lambda r: r.get("publishDate") or "", reverse=True)
    for i, r in enumerate(by_age):
        extra = [f"abr-newest-{i + 1}"] if i < NEWEST_FLAGS else []
        r["indexerFlags"] = list(r.get("indexerFlags") or []) + extra + (["abr-vip"] if _vip(r) else [])
        # ABR fetches the .torrent once more to read its hash; the pass-through answers from qBittorrent instead of MAM.
        if proxy_base and r.get("downloadUrl"):
            r["downloadUrl"] = f"{proxy_base}/torrent?guid={urllib.parse.quote(r.get('guid') or '', safe='')}"
    return sorted(by_age, key=lambda r: (_abridged(r) == prefs.unabridged, r.get("guid") not in narrated,
                                         _flags(r["title"])[1] != "M4B", not _vip(r)))


def for_abr(results, prefs, proxy_base=None, narrated=frozenset()):
    """Only the winner: ABR re-sorts by its own fixed rules (FLAC > M4B, no abridged/VIP) and grabs its first entry."""
    return apply_policy(results, prefs, proxy_base, narrated)[:1]
