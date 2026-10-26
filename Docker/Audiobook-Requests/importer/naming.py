"""Library path of a book: LANG/Author/[Series]/NN - Title (see the project README)."""
import re
import unicodedata
from dataclasses import dataclass, field

LANGUAGES = {"english": "EN", "german": "DE", "deutsch": "DE"}
MAM_CODES = {"ENG": "EN", "GER": "DE", "DEU": "DE"}


@dataclass
class Book:
    title: str
    authors: list = field(default_factory=list)
    series: str | None = None
    position: str | None = None
    language: str = "EN"


def clean(text):
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if set(text) <= {"."} else text


def number(position):
    m = re.search(r"\d+(?:\.\d+)?", position or "")
    if not m:
        return None
    whole, _, frac = m.group(0).partition(".")
    return f"{int(whole):02d}" + (f".{frac}" if frac else "")


def book_dir(book):
    author = clean(book.authors[0]) if book.authors else ""
    title = clean(book.title) or "Unknown Title"
    parts = [book.language, author or "Unknown Author"]
    series = re.sub(r"\s+Series$", "", clean(book.series), flags=re.I)
    if series:
        parts.append(series)
        n = number(book.position)
        title = f"{n} - {title}" if n else title
    return "/".join(parts + [title])


def language_folder(name):
    if not name:
        return None
    return LANGUAGES.get(name.strip().lower(), "Other")


def mam_language(source_title):
    m = re.search(r"\[([A-Z]{3}) /", source_title or "")
    return MAM_CODES.get(m.group(1), "Other") if m else None
