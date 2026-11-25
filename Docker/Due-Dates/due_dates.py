#!/usr/bin/env python3
"""Due dates in one place (README.md): merges due-dates.toml (manual) with the dates fetched by other jobs (Prometheus textfiles: TLS certificates and RDAP from status-exporter, Authentik tokens) into due-dates.json.
Usage: due_dates.py [build]   writes $STATE_DIRECTORY/due-dates.json + fetched.json (default /var/lib/due-dates)
       due_dates.py md [JSON] prints the notes page (Markdown) for that JSON"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("DUE_DATES_TOML", HERE / "due-dates.toml"))
TEXTFILE_DIR = Path(os.environ.get("TEXTFILE_DIR", "/var/lib/node-exporter/textfile"))
OUT_DIR = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/due-dates"))
KINDS = ("subscription", "domain", "ddns", "token", "warranty", "reminder", "info")
SOURCES = ("manual", "rdap")
ALERTS = ("telegram", "none")
BARS = ("seerr", "books")
DDNS_DAYS = 30
LEAD = {"ddns": [5, 3, 1, 0]}
LEAD_DEFAULT = [30, 7, 0]
OPTIONAL = ("url", "notes", "howto", "registrar", "renew", "dns")
LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)")
LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def load_source(text):
    try:
        entries = tomllib.loads(text).get("due", [])
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML: {e}") from e
    if not isinstance(entries, list):
        raise ValueError("[[due]] must be a list")
    seen = set()
    for e in entries:
        name = e.get("id")
        if not isinstance(name, str) or not name or not isinstance(e.get("title"), str):
            raise ValueError(f"entry {name!r}: needs id and title")
        if name in seen:
            raise ValueError(f"entry {name!r}: duplicate id")
        seen.add(name)
        if e.get("kind") not in KINDS:
            raise ValueError(f"entry {name!r}: kind must be one of {', '.join(KINDS)}")
        if e.get("source", "manual") not in SOURCES:
            raise ValueError(f"entry {name!r}: source must be one of {', '.join(SOURCES)}")
        if e.get("alert", "telegram") not in ALERTS:
            raise ValueError(f"entry {name!r}: alert must be one of {', '.join(ALERTS)}")
        if not all(b in BARS for b in e.get("show", [])):
            raise ValueError(f"entry {name!r}: show takes {', '.join(BARS)}")
        lead = e.get("lead", [])
        if not isinstance(lead, list) or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in lead):
            raise ValueError(f"entry {name!r}: lead must be a list of whole days")
        for k in ("date", "confirmed"):
            if k in e and not isinstance(e[k], dt.date):
                raise ValueError(f"entry {name!r}: {k} must be a TOML date (YYYY-MM-DD, no quotes)")
        has_date = "date" in e or (e["kind"] == "ddns" and "confirmed" in e) or e.get("lifetime") is True or e.get("source") == "rdap"
        if not has_date:
            raise ValueError(f"entry {name!r}: needs date, lifetime = true, confirmed (ddns) or source = \"rdap\" (domain)")
    return entries


def prom(text):
    for line in text.splitlines():
        m = LINE.match(line)
        if m and not line.startswith("#"):
            try:
                yield m[1], dict(LABEL.findall(m[2] or "")), float(m[3])
            except ValueError:
                continue


def day(ts):
    return dt.datetime.fromtimestamp(ts, TZ).date().isoformat()


def read(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def fetch_textfiles(directory):
    out = {"tls": {}, "rdap": {}, "authentik": {}}
    for name, lab, v in prom(read(directory / "status_certs.prom")):
        if name == "tls_cert_not_after_timestamp_seconds":
            out["tls"][lab["host"]] = day(v)
    for name, lab, v in prom(read(directory / "status_domains.prom")):
        if name == "domain_expiry_timestamp_seconds":
            out["rdap"][lab["domain"]] = {"date": day(v), "source": lab.get("source", "rdap")}
    for name, lab, v in prom(read(directory / "authentik_tokens.prom")):
        if name == "authentik_token_expires_timestamp_seconds" and v > 0:
            out["authentik"][lab["identifier"]] = day(v)
    return out


def category(e):
    if e["kind"] == "domain":
        return "domain" + (f", {e['registrar']}" if e.get("registrar") else "") + (f" (DNS {e['dns']})" if e.get("dns") else "")
    if e["kind"] == "ddns":
        return "No-IP hostname"
    return e.get("category", "")


def item(e, fetched):
    date, source = e.get("date"), e.get("source", "manual")
    if isinstance(date, dt.date):
        date, source = date.isoformat(), "manual"
    elif e["kind"] == "ddns" and e.get("confirmed"):
        date = (e["confirmed"] + dt.timedelta(days=DDNS_DAYS)).isoformat()
    elif source == "rdap" and e["title"] in fetched["rdap"]:
        date, source = fetched["rdap"][e["title"]]["date"], fetched["rdap"][e["title"]]["source"]
    out = {"id": e["id"], "title": e["title"], "kind": e["kind"], "category": category(e), "date": date,
           "lifetime": e.get("lifetime") is True, "source": source, "lead": e.get("lead", LEAD.get(e["kind"], LEAD_DEFAULT)),
           "alert": e.get("alert", "none" if e["kind"] == "info" else "telegram"), "show": e.get("show", [])}
    if e["kind"] == "ddns" and e.get("confirmed"):
        out["confirmed"] = e["confirmed"].isoformat()
    out.update({k: e[k] for k in OPTIONAL if k in e})
    return out


def fetched_items(fetched):
    tls = [{"id": f"tls:{h}", "title": f"TLS certificate {h}", "kind": "certificate", "category": "Let's Encrypt via Traefik", "date": d,
            "lifetime": False, "source": "tls", "lead": [21, 7], "alert": "prometheus", "show": []} for h, d in fetched["tls"].items()]
    ak = [{"id": f"authentik:{t}", "title": f"Authentik token {t}", "kind": "token", "category": "rotated weekly", "date": d,
           "lifetime": False, "source": "authentik", "lead": [30], "alert": "prometheus", "show": []} for t, d in fetched["authentik"].items()]
    return tls + ak


def merge(entries, fetched, now):
    items = [item(e, fetched) for e in entries] + fetched_items(fetched)
    items.sort(key=lambda i: (i["date"] is None, i["date"] or "", i["title"].lower()))
    return {"version": 1, "generated": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def run(source, textfile_dir, out_dir, now):
    try:
        entries = load_source(Path(source).read_text())
    except (OSError, ValueError) as e:
        print(f"due-dates: {source}: {e}; old list kept", file=sys.stderr)
        return 1
    fetched = fetch_textfiles(Path(textfile_dir))
    write(Path(out_dir) / "fetched.json", {"generated": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **fetched})
    write(Path(out_dir) / "due-dates.json", merge(entries, fetched, now))
    return 0


def cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def markdown(data, today):
    rows, certs = [], []
    for i in data["items"]:
        if i["kind"] == "certificate":
            certs.append(i)
            continue
        what = cell(i["title"]) + (f" · {cell(i['category'])}" if i.get("category") else "")
        note = cell(i.get("notes", ""))
        if i["lifetime"]:
            rows.append(f"| lifetime | | {what} | {note} |")
        elif i["date"]:
            left = (dt.date.fromisoformat(i["date"]) - today).days
            when = "today" if left == 0 else f"{left} day{'' if abs(left) == 1 else 's'}" if left > 0 else f"{-left} day{'' if left == -1 else 's'} ago"
            rows.append(f"| {i['date']} | {when} | {what} | {note} |")
        else:
            rows.append(f"| unknown | | {what} | {note} |")
    if certs:
        first = certs[0]
        rows.append(f"| {first['date']} | {(dt.date.fromisoformat(first['date']) - today).days} days | TLS certificates ({len(certs)}, Prometheus alerts) | earliest: {cell(first['title'].removeprefix('TLS certificate '))}; Traefik renews 30 days ahead |")
        rows.sort(key=lambda r: (not r.startswith("| 20"), r))
    head = ["# Due dates", "",
            "Every date that needs you, soonest first. Generated from `Docker/Due-Dates/due-dates.toml` (HomeLab-FastPi) plus fetched dates; "
            f"change a date there, not here. As of {data['generated'][:10]}.", "",
            "| Date | In | What | Notes |", "|---|---|---|---|"]
    return "\n".join(head + rows) + "\n"


def main(argv):
    if argv[:1] == ["md"]:
        path = Path(argv[1]) if len(argv) > 1 else OUT_DIR / "due-dates.json"
        sys.stdout.write(markdown(json.loads(path.read_text()), dt.datetime.now(TZ).date()))
        return 0
    if argv in ([], ["build"]):
        return run(SOURCE, TEXTFILE_DIR, OUT_DIR, dt.datetime.now(dt.timezone.utc))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
