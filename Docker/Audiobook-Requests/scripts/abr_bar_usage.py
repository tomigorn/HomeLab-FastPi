#!/usr/bin/env python3
"""Requests bar above ABR (README "Requests bar"): Prowlarr searches (queries + RSS) and grabs per audiobook indexer inside its window from abr-bar/limits.toml, subscription deadlines (MAM VIP included), unsatisfied MyAnonamouse torrents from qBittorrent (72 h seed rule), and the fill level of the audiobook library and download filesystems; writes usage.json (names and counts only) for books-proxy.
Counting and subscriptions are a copy of Seerr's scripts/indexer-usage.py (beefy); output = the shared schema (abr-bar/indexer-bar-schema.md). Prowlarr unreachable: ok=false, storage and subscriptions stay. Run by systemd/abr-bar-usage.timer.
Usage: scripts/abr_bar_usage.py"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Zurich")
UTC = dt.timezone.utc
DAY = dt.timedelta(hours=24)
SEARCH_EVENTS = {"indexerQuery", "indexerRss"}
GRAB_EVENTS = {"releaseGrabbed"}
WINDOWS = {"rolling", "day"}
AMBER, RED = 0.70, 0.95
SUB_YELLOW_DAYS, SUB_ORANGE_DAYS, SUB_RED_DAYS = 30, 7, 0
RANK = {"ok": 0, "yellow": 1, "warn": 2, "orange": 3, "full": 4}
DISK_YELLOW, DISK_RED = 0.70, 0.80
DISKS = [{"name": "Library", "id": "library", "paths": ["/mnt/seagate-black/library/audiobooks"]},
         {"name": "Downloads", "id": "downloads", "paths": ["/mnt/seagate-red/qbittorrent/downloads", "/mnt/seagate-red/sabnzbd/config/Downloads"]}]
# Bar texts (shared bar, schema in abr-bar/indexer-bar-schema.md): bar.js has no ABR wording.
DISK_TEXT = {
    "library": {"label": {"en": "Library", "de": "Bibliothek"}, "sub": {"en": "books in Audiobookshelf", "de": "Bücher in Audiobookshelf"},
                "hint": {"en": "Audiobookshelf library. From {yellow} % plan more space, from {red} % new books may soon not fit. Nothing is deleted automatically.",
                         "de": "Audiobookshelf-Bibliothek. Ab {yellow} % mehr Platz einplanen, ab {red} % passen neue Bücher bald nicht mehr. Es wird nichts automatisch gelöscht."}},
    "downloads": {"label": {"en": "Downloads", "de": "Downloads"}, "sub": {"en": "torrents (seeding) + Usenet", "de": "Torrents (seeden) + Usenet"},
                  "hint": {"en": "Torrents keep seeding (MyAnonamouse rules), so this only grows. From {red} % make room by hand; nothing is removed automatically.",
                           "de": "Torrents seeden weiter (MyAnonamouse-Regeln), daher wächst das nur. Ab {red} % von Hand Platz schaffen; es wird nichts automatisch entfernt."}},
}
NOTE = {"en": "Searches and downloads go through Prowlarr to MyAnonamouse. A request stays open until a release in the requested language exists; searches made by hand on the indexer website are not counted.",
        "de": "Suchen und Downloads laufen über Prowlarr zu MyAnonamouse. Eine Anfrage bleibt offen, bis es eine Ausgabe in der gewünschten Sprache gibt; von Hand auf der Indexer-Website gemachte Suchen werden nicht gezählt."}
# MyAnonamouse seeding rule (rules.php 2.5): every download seeds 72 h in total within 30 days; until then it is "unsatisfied" and counts against the class limit.
MAM_HOST = "myanonamouse.net"
MAM_SEED, MAM_DAYS = 72 * 3600, 30
MAM_YELLOW, MAM_RED = 0.70, 0.90
SEEDING = {"uploading", "stalledUP", "forcedUP"}
STOPPED = {"pausedUP", "pausedDL", "stoppedUP", "stoppedDL", "error", "missingFiles"}
MAM_TEXT = {
    "label": {"en": "MAM unsatisfied", "de": "MAM unerfüllt"},
    "hint": {"en": "Unsatisfied MAM torrents: {n} of {limit} ({cls}) — each must seed 72 h within 30 days{free}.",
             "de": "Unerfüllte MAM-Torrents: {n} von {limit} ({cls}) — jeder muss innerhalb von 30 Tagen 72 h seeden{free}."},
    "free": {"en": "; oldest frees at {freesAt}", "de": "; der nächste ist frei um {freesAt}"},
    "head": {"en": "MyAnonamouse seeding", "de": "MyAnonamouse seeden"},
    "risksHead": {"en": "Rule risk: stopped before 72 h", "de": "Regelrisiko: vor 72 h gestoppt"},
    "reasons": {"paused": {"en": "paused in qBittorrent, resume it", "de": "in qBittorrent pausiert, wieder starten"},
                "removed": {"en": "removed from qBittorrent", "de": "aus qBittorrent entfernt"},
                "missed": {"en": "30 days passed without 72 h", "de": "30 Tage ohne 72 h vorbei"}},
    "rule": {"en": "MAM rule: seed every download 72 h in total within 30 days (counted here from qBittorrent's seeding time). Never stop a MAM torrent early.",
             "de": "MAM-Regel: jeden Download innerhalb von 30 Tagen insgesamt 72 h seeden (hier aus der Seed-Zeit von qBittorrent gezählt). Nie einen MAM-Torrent früher stoppen."},
}
SEERR_LIST = pathlib.Path("/var/lib/subscription-alerts/limits.toml")


class ApiError(Exception):
    pass


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def local_date(now):
    return now.astimezone(TZ).date()


def local_midnight(day):
    return dt.datetime.combine(day, dt.time(0), TZ).astimezone(UTC)


def window_start(window, now):
    return now - DAY if window == "rolling" else local_midnight(local_date(now))


def since(limits, now):
    return min([now - DAY] + [window_start(c.get("window", "rolling"), now) for c in limits.values()])


def level(used, limit):
    if limit is None:
        return "ok"
    if limit <= 0 or used / limit >= RED:
        return "full"
    return "warn" if used / limit >= AMBER else "ok"


def metric(times, limit, window, now):
    times = sorted(times)
    used = len(times)
    resets = None
    if limit is not None and times:
        resets = times[max(0, used - limit)] + DAY if window == "rolling" else local_midnight(local_date(now) + dt.timedelta(days=1))
    return {"used": used, "limit": limit, "level": level(used, limit), "resetsAt": iso(resets)}


def usage(indexers, history, limits, now):
    events = {}
    for e in history:
        try:
            events.setdefault(e["indexerId"], []).append((e["eventType"], parse_time(e["date"])))
        except (KeyError, TypeError, ValueError):
            continue
    order = list(limits)
    rows = []
    for ix in indexers:
        if not ix.get("enable", True):
            continue
        cfg = limits.get(ix["name"], {})
        window = cfg.get("window", "rolling")
        start = window_start(window, now)
        inside = [(kind, t) for kind, t in events.get(ix["id"], []) if (t > start if window == "rolling" else t >= start) and t <= now]
        searches = metric([t for kind, t in inside if kind in SEARCH_EVENTS], cfg.get("searches"), window, now)
        downloads = metric([t for kind, t in inside if kind in GRAB_EVENTS], cfg.get("downloads"), window, now)
        rows.append({"name": ix["name"], "protocol": ix.get("protocol"), "limited": bool(cfg), "window": window,
                     "level": max(searches["level"], downloads["level"], key=RANK.get), "searches": searches, "downloads": downloads})
    rows.sort(key=lambda r: (0, order.index(r["name"])) if r["limited"] else (1, r["name"].lower()))
    return {"indexers": rows}


def subscriptions(subs, today, seerr=None):
    out = []
    for s in subs:
        if s.get("seerr"):
            s = next((x for x in seerr or [] if x.get("name") == s["name"]), None)
            if s is None:
                continue
        if s.get("lifetime"):
            out.append({"name": s["name"], "kind": s.get("kind"), "lifetime": True, "expires": None, "daysLeft": None, "expired": False, "level": "ok"})
            continue
        expires = s.get("expires")
        if not isinstance(expires, dt.date):
            raise ValueError(f"subscription {s.get('name')!r}: needs expires = YYYY-MM-DD, lifetime = true or seerr = true")
        left = (expires - today).days
        lvl = "full" if left <= SUB_RED_DAYS else "orange" if left <= SUB_ORANGE_DAYS else "yellow" if left <= SUB_YELLOW_DAYS else "ok"
        out.append({"name": s["name"], "kind": s.get("kind"), "lifetime": False, "expires": expires.isoformat(), "daysLeft": left, "expired": left < 0, "level": lvl})
    return out


def seerr_subscriptions(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get("subscriptions", [])
    except (OSError, tomllib.TOMLDecodeError):
        return None


def is_mam(url):
    host = urllib.parse.urlparse(url or "").hostname or ""
    return host == MAM_HOST or host.endswith("." + MAM_HOST)


def mam(torrents, trackers, seen, cfg, now):
    """Unsatisfied count, next free slot and rule risks; seen = last run's MAM torrents under 72 h (hash -> name, added, seeded, gone), returned updated."""
    t_now = now.timestamp()
    cutoff = t_now - MAM_DAYS * 86400
    current, unsat, frees, risks = {}, 0, [], []
    for t in torrents:
        h = t.get("hash")
        if not h or not (is_mam(t.get("tracker")) or any(is_mam(u) for u in trackers.get(h, []))):
            continue
        seeded, added, state = t.get("seeding_time", 0), t.get("added_on", 0), t.get("state", "")
        if seeded >= MAM_SEED:
            continue
        current[h] = {"name": t.get("name", ""), "added": added, "seeded": seeded, "gone": False}
        if added < cutoff:
            risks.append((t.get("name", ""), "missed", seeded))
            continue
        unsat += 1
        if state in STOPPED:
            risks.append((t.get("name", ""), "paused", seeded))
        elif state in SEEDING:
            frees.append(t_now + MAM_SEED - seeded)
    for h, s in seen.items():
        if h in current or s.get("added", 0) < cutoff:
            continue
        current[h] = {**s, "gone": True}
        risks.append((s.get("name", ""), "removed", s.get("seeded", 0)))
    limit = cfg["unsatisfied_limit"]
    ratio = unsat / limit if limit else 1
    lvl = "full" if risks or ratio >= MAM_RED else "yellow" if ratio >= MAM_YELLOW else "ok"
    free_at = dt.datetime.fromtimestamp(min(frees), UTC) if frees else None
    hint = {l: MAM_TEXT["hint"][l].format(n=unsat, limit=limit, cls=cfg["class"], free=MAM_TEXT["free"][l] if free_at else "") for l in ("en", "de")}
    out = {"ok": True, "unsatisfied": unsat, "limit": limit, "class": cfg["class"], "level": lvl, "freesAt": iso(free_at),
           "seedHours": MAM_SEED // 3600, "windowDays": MAM_DAYS,
           "risks": [{"name": n, "reason": r, "seededHours": int(s // 3600)} for n, r, s in risks],
           **{k: v for k, v in MAM_TEXT.items() if k not in ("hint", "free")}, "hint": hint}
    return out, current


def mam_subscriptions(cfg):
    return [{"name": "MAM VIP", "kind": "MyAnonamouse class", "expires": cfg["vip_expires"]}] if cfg and cfg.get("vip_expires") else []


def mam_config(c):
    if not c:
        return None
    if not isinstance(c.get("class"), str) or not isinstance(c.get("unsatisfied_limit"), int) or c["unsatisfied_limit"] < 0:
        raise ValueError("[mam]: needs class = \"...\" and unsatisfied_limit = a whole number")
    vip = c.get("vip_expires") or None
    if isinstance(vip, str):
        try:
            vip = dt.date.fromisoformat(vip)
        except ValueError:
            raise ValueError("[mam]: vip_expires must be \"YYYY-MM-DD\" or empty") from None
    elif vip is not None and not isinstance(vip, dt.date):
        raise ValueError("[mam]: vip_expires must be \"YYYY-MM-DD\" or empty")
    return {"class": c["class"], "unsatisfied_limit": c["unsatisfied_limit"], "vip_expires": vip}


def storage(disks, statvfs=os.statvfs, device=lambda p: os.stat(p).st_dev):
    groups = {}
    for d in disks:
        for path in d["paths"]:
            try:
                dev, st = device(path), statvfs(path)
            except OSError:
                continue
            g = groups.setdefault(dev, {"disks": [], "st": st})
            if d not in g["disks"]:
                g["disks"].append(d)
    out = []
    for g in groups.values():
        st = g["st"]
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        ratio = used / (used + free) if used + free else 0
        lvl = "full" if ratio >= DISK_RED else "yellow" if ratio >= DISK_YELLOW else "ok"
        row = {"name": " + ".join(d["name"] for d in g["disks"]), "id": "+".join(d["id"] for d in g["disks"]),
               "total": total, "used": used, "free": free, "pct": round(100 * ratio, 1),
               "level": lvl, "yellow": round(100 * DISK_YELLOW), "red": round(100 * DISK_RED)}
        texts = [DISK_TEXT.get(d["id"], {}) for d in g["disks"]]
        for key, sep in (("label", " + "), ("sub", " · "), ("hint", " ")):
            if all(key in t for t in texts):
                row[key] = {lang: sep.join(t[key][lang].format(yellow=row["yellow"], red=row["red"]) for t in texts) for lang in ("en", "de")}
        out.append(row)
    return out


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    limits = cfg.get("indexers", {})
    for name, c in limits.items():
        if c.get("window", "rolling") not in WINDOWS:
            raise ValueError(f"indexer {name!r}: window must be one of {sorted(WINDOWS)}")
        for k in ("searches", "downloads"):
            if k in c and (not isinstance(c[k], int) or c[k] < 0):
                raise ValueError(f"indexer {name!r}: {k} must be a whole number")
    subs = cfg.get("subscriptions", [])
    subscriptions([s for s in subs if not s.get("seerr")], dt.date.today())
    return {"indexers": limits, "subscriptions": subs, "mam": mam_config(cfg.get("mam"))}


def write(path, data, mode=0o644):
    path = pathlib.Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".usage-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_seen(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}


def mam_run(cfg, qbit, seen_path, now):
    try:
        torrents = qbit("/torrents/info")
        trackers = {t["hash"]: [x.get("url", "") for x in qbit("/torrents/trackers?hash=" + t["hash"])]
                    for t in torrents if t.get("hash") and not t.get("tracker")}
    except ApiError as e:
        print(f"abr-bar-usage: qBittorrent unavailable: {e}", file=sys.stderr)
        return {"ok": False, "label": MAM_TEXT["label"]}
    out, seen = mam(torrents, trackers, read_seen(seen_path), cfg, now)
    write(seen_path, seen, 0o600)
    return out


def run(cfg, api, out, now, disks=DISKS, statvfs=os.statvfs, device=lambda p: os.stat(p).st_dev, seerr=None, qbit=None):
    mcfg = cfg.get("mam")
    data = {"ok": True, "generated": iso(now), "indexers": [], "showUnlimited": True, "note": NOTE,
            "subscriptions": subscriptions(cfg["subscriptions"] + mam_subscriptions(mcfg), local_date(now), seerr),
            "storage": storage(disks, statvfs, device)}
    try:
        indexers = api("/indexer")
        history = api("/history/since?date=" + urllib.parse.quote(iso(since(cfg["indexers"], now)), safe=":"))
        data.update(usage(indexers, history, cfg["indexers"], now))
    except ApiError as e:
        data["ok"] = False
        print(f"abr-bar-usage: Prowlarr unavailable: {e}", file=sys.stderr)
    if mcfg and qbit:
        data["mam"] = mam_run(mcfg, qbit, pathlib.Path(out).parent / "mam-seen.json", now)
    write(out, data)
    return data


def api_key(config_xml):
    try:
        return re.search(r"<ApiKey>([^<]+)</ApiKey>", pathlib.Path(config_xml).read_text()).group(1)
    except (OSError, AttributeError):
        raise ApiError("no Prowlarr API key") from None


def client(config_xml, base):
    def get(path):
        key = api_key(config_xml)
        try:
            with urllib.request.urlopen(urllib.request.Request(base + "/api/v1" + path, headers={"X-Api-Key": key}), timeout=20) as r:
                return json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")) from None
    return get


def qbit_client(pass_file, base):
    """Read-only qBittorrent Web API (torrents/info, torrents/trackers); the session cookie stays in memory."""
    import http.cookiejar
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("Referer", base)]
    state = {"in": False}

    def get(path):
        try:
            if not state["in"]:
                pw = pathlib.Path(pass_file).read_text().strip()
                body = urllib.parse.urlencode({"username": os.environ.get("BAR_QBIT_USER", "admin"), "password": pw}).encode()
                if opener.open(base + "/api/v2/auth/login", data=body, timeout=20).read().strip() not in (b"Ok.", b""):
                    raise ApiError("login refused")
                state["in"] = True
            with opener.open(base + "/api/v2" + path, timeout=20) as r:
                return json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")) from None
    return get


def main():
    cfg = load_config(os.environ.get("BAR_CONFIG", ROOT / "abr-bar" / "limits.toml"))
    state = os.environ.get("STATE_DIRECTORY", "/var/lib/abr-bar")
    creds = os.environ.get("CREDENTIALS_DIRECTORY", "")
    api = client(os.path.join(creds, "prowlarr-config.xml"), os.environ.get("BAR_PROWLARR_URL", "http://10.24.32.2:9697"))
    qbit = qbit_client(os.path.join(creds, "qbit-pass"), os.environ.get("BAR_QBIT_URL", "http://10.24.25.2:8080"))
    run(cfg, api, os.path.join(state, "usage.json"), dt.datetime.now(UTC).replace(microsecond=0),
        seerr=seerr_subscriptions(os.environ.get("BAR_SEERR_LIST", SEERR_LIST)), qbit=qbit)


if __name__ == "__main__":
    main()
