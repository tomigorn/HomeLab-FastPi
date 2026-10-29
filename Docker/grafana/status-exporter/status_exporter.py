#!/usr/bin/env python3
"""Expiry and status figures -> Prometheus textfiles (README "Expiry and disk health").

  certs          TLS handshake with Traefik (127.0.0.1:443, SNI) for every hostname routed with a certResolver in Traefik/traefik/dynamic: the cert users really get, its end date and whether it verifies. A TLS handshake runs no middleware, so wake-gated routes never wake beefy/tower.
  domains        RDAP (no account, no paid API) for the domains in domains.toml: registration end, status. .ch RDAP has no end date: a date set in domains.toml wins, else the next registration anniversary (a .ch registration runs in whole years from it, so an active domain is paid at least until then).
                 Also resolves the DDNS hostnames in domains.toml and compares them with the WAN address (Cloudflare's /cdn-cgi/trace).
  subscriptions  the subscription list cached by subscription-alerts.py (Seerr limits.toml) + MAM VIP from Audiobook-Requests/abr-bar/limits.toml.
  indexers       the audiobook indexer bar's usage.json (Audiobook-Requests).
A failed source leaves its old file in place; each file carries its own timestamp for the staleness alerts.
Usage: status_exporter.py certs|domains|subscriptions|indexers [...]"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TEXTFILE_DIR = Path(os.environ.get("TEXTFILE_DIR", "/var/lib/node-exporter/textfile"))
DYNAMIC = Path(os.environ.get("TRAEFIK_DYNAMIC", REPO / "Traefik" / "traefik" / "dynamic"))
TRAEFIK = (os.environ.get("TRAEFIK_ADDR", "127.0.0.1"), 443)
DOMAINS = Path(os.environ.get("DOMAINS_TOML", HERE / "domains.toml"))
SUBS_CACHE = Path(os.environ.get("SUBS_CACHE", "/var/lib/subscription-alerts/limits.toml"))
ABR_LIMITS = Path(os.environ.get("ABR_LIMITS", REPO / "Audiobook-Requests" / "abr-bar" / "limits.toml"))
ABR_USAGE = Path(os.environ.get("ABR_USAGE", "/var/lib/abr-bar/usage.json"))
IANA = "https://data.iana.org/rdap/dns.json"
# TLDs whose registry runs RDAP without being in the IANA bootstrap file.
RDAP_EXTRA = {"ch": "https://rdap.nic.ch/", "li": "https://rdap.nic.ch/"}
BAD_STATUS = ("inactive", "hold", "pending delete", "redemption", "pending restore")
HOST_RE = re.compile(r"Host\(([^)]*)\)")
UA = {"User-Agent": "homelab-status-exporter", "Accept": "application/rdap+json, application/json"}


def esc(s) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def local_midnight(day: dt.date) -> float:
    return dt.datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()


# --- certs -----------------------------------------------------------------

def routed_hosts(docs) -> list[str]:
    hosts = set()
    for doc in docs:
        routers = ((doc or {}).get("http") or {}).get("routers") or {}
        for r in routers.values():
            if not isinstance(r, dict) or not (r.get("tls") or {}).get("certResolver"):
                continue
            for args in HOST_RE.findall(r.get("rule", "")):
                hosts.update(re.findall(r"`([^`]+)`", args))
    return sorted(hosts)


def load_dynamic(directory: Path) -> list:
    import yaml
    docs = []
    for f in sorted(glob.glob(str(directory / "*.yml")) + glob.glob(str(directory / "*.yaml"))):
        with open(f) as fh:
            docs.append(yaml.safe_load(fh))
    return docs


def probe(host: str, addr=TRAEFIK, timeout=10) -> dict:
    from cryptography import x509
    try:
        ctx = ssl.create_default_context()
        verified = True
        try:
            with socket.create_connection(addr, timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host) as t:
                der = t.getpeercert(binary_form=True)
        except ssl.SSLCertVerificationError:
            verified = False
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection(addr, timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host) as t:
                der = t.getpeercert(binary_form=True)
        cert = x509.load_der_x509_certificate(der)
        return {"ok": True, "verified": verified, "not_after": cert.not_valid_after_utc.timestamp()}
    except (OSError, ValueError) as e:
        print(f"status-exporter: tls {host}: {e}", file=sys.stderr)
        return {"ok": False}


def cert_lines(results: dict, now: float) -> str:
    out = []
    for host in sorted(results):
        r, lab = results[host], f'host="{esc(host)}"'
        out.append(f"tls_cert_probe_success{{{lab}}} {1 if r['ok'] else 0}")
        if r["ok"]:
            out.append(f"tls_cert_not_after_timestamp_seconds{{{lab}}} {int(r['not_after'])}")
            out.append(f"tls_cert_verified{{{lab}}} {1 if r['verified'] else 0}")
    out.append(f"tls_cert_exporter_last_run_timestamp_seconds {int(now)}")
    return "\n".join(out) + "\n"


def run_certs() -> int:
    hosts = routed_hosts(load_dynamic(DYNAMIC))
    if not hosts:
        print("status-exporter: no routed hostnames found", file=sys.stderr)
        return 1
    write_atomic(TEXTFILE_DIR / "status_certs.prom", cert_lines({h: probe(h) for h in hosts}, time.time()))
    return 0


# --- domains ---------------------------------------------------------------

def _ts(value: str) -> float:
    if len(value) == 10:
        return local_midnight(dt.date.fromisoformat(value))
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def domain_info(rdap: dict, conf: dict, now: float) -> dict:
    events = {e.get("eventAction"): e.get("eventDate") for e in rdap.get("events", [])}
    status = [s.lower() for s in rdap.get("status", [])]
    ok = 0 if any(b in s for s in status for b in BAD_STATUS) else 1
    if isinstance(conf.get("expires"), dt.date):
        return {"expires": local_midnight(conf["expires"]), "source": "manual", "status_ok": ok}
    if events.get("expiration"):
        return {"expires": _ts(events["expiration"]), "source": "rdap", "status_ok": ok}
    reg = events.get("registration")
    if not reg:
        return {"expires": None, "source": "unknown", "status_ok": ok}
    r = dt.date.fromisoformat(reg[:10])
    today = dt.datetime.fromtimestamp(now, TZ).date()
    year = today.year
    while True:
        try:
            nxt = r.replace(year=year)
        except ValueError:
            nxt = dt.date(year, 3, 1)
        if nxt > today:
            break
        year += 1
    return {"expires": local_midnight(nxt), "source": "anniversary", "status_ok": ok}


def rdap_url(domain: str, bootstrap: dict) -> str:
    tld = domain.rsplit(".", 1)[-1]
    base = RDAP_EXTRA.get(tld)
    for tlds, urls in (bootstrap or {}).get("services", []):
        if tld in tlds:
            base = urls[0]
    if not base:
        raise ValueError(f"no RDAP server for .{tld}")
    return base.rstrip("/") + "/domain/" + domain


def domain_lines(infos: dict, now: float) -> str:
    out = []
    for d in sorted(infos):
        info, lab = infos[d], f'domain="{esc(d)}"'
        out.append(f"domain_rdap_success{{{lab}}} {0 if info is None else 1}")
        if info is None:
            continue
        out.append(f"domain_rdap_status_ok{{{lab}}} {info['status_ok']}")
        if info["expires"] is not None:
            out.append(f'domain_expiry_timestamp_seconds{{{lab},source="{info["source"]}"}} {int(info["expires"])}')
    out.append(f"domain_exporter_last_run_timestamp_seconds {int(now)}")
    return "\n".join(out) + "\n"


def wan_from_trace(text: str):
    m = re.search(r"^ip=([0-9a-fA-F.:]+)$", text, re.M)
    return m[1] if m else None


def ddns_lines(resolved: dict, wan) -> str:
    out = []
    for h in sorted(resolved):
        lab = f'host="{esc(h)}"'
        out.append(f"ddns_hostname_resolves{{{lab}}} {1 if resolved[h] else 0}")
        if wan and resolved[h]:
            out.append(f"ddns_hostname_matches_wan{{{lab}}} {1 if wan in resolved[h] else 0}")
    return "\n".join(out) + "\n"


def get_json(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def resolve(host: str) -> list[str]:
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, None, socket.AF_INET)})
    except OSError:
        return []


def run_domains() -> int:
    conf = tomllib.loads(DOMAINS.read_text())
    try:
        boot = get_json(IANA)
    except (OSError, ValueError) as e:
        print(f"status-exporter: IANA bootstrap: {e}", file=sys.stderr)
        boot = {}
    now, infos = time.time(), {}
    for d, c in (conf.get("domains") or {}).items():
        try:
            infos[d] = domain_info(get_json(rdap_url(d, boot)), c or {}, now)
        except (OSError, ValueError, KeyError) as e:
            print(f"status-exporter: rdap {d}: {e}", file=sys.stderr)
            infos[d] = None
    try:
        with urllib.request.urlopen(urllib.request.Request("https://1.1.1.1/cdn-cgi/trace", headers=UA), timeout=10) as r:
            wan = wan_from_trace(r.read().decode())
    except OSError as e:
        print(f"status-exporter: WAN address: {e}", file=sys.stderr)
        wan = None
    text = domain_lines(infos, now) + ddns_lines({h: resolve(h) for h in (conf.get("ddns") or {})}, wan)
    write_atomic(TEXTFILE_DIR / "status_domains.prom", text)
    return 1 if any(v is None for v in infos.values()) else 0


# --- subscriptions ---------------------------------------------------------

def subscription_lines(seerr_toml: str, mam: dict, updated: float) -> str:
    subs = list(tomllib.loads(seerr_toml).get("subscriptions") or [])
    if (mam or {}).get("vip_expires"):
        subs.append({"name": "MAM VIP", "kind": "MyAnonamouse class", "expires": dt.date.fromisoformat(mam["vip_expires"])})
    # one series per label set (node-exporter rejects the whole file on a duplicate); the earliest expiry wins
    lifetime, expiry = {}, {}
    for s in subs:
        lab = f'name="{esc(s["name"])}",kind="{esc(s.get("kind", ""))}"'
        if s.get("lifetime"):
            lifetime[lab] = 1
        elif isinstance(s.get("expires"), dt.date):
            expiry[lab] = min(expiry.get(lab, s["expires"]), s["expires"])
    out = [f"subscription_lifetime{{{lab}}} 1" for lab in lifetime]
    out += [f"subscription_expiry_timestamp_seconds{{{lab}}} {int(local_midnight(d))}" for lab, d in expiry.items()]
    out.append(f"subscription_list_updated_timestamp_seconds {int(updated)}")
    return "\n".join(out) + "\n"


def run_subscriptions() -> int:
    with open(ABR_LIMITS, "rb") as f:
        mam = tomllib.load(f).get("mam") or {}
    write_atomic(TEXTFILE_DIR / "status_subscriptions.prom",
                 subscription_lines(SUBS_CACHE.read_text(), mam, SUBS_CACHE.stat().st_mtime))
    return 0


# --- indexers --------------------------------------------------------------

def indexer_lines(usage: dict, host: str) -> str:
    h = f'host="{esc(host)}"'
    out = []
    for ix in usage.get("indexers", []):
        for kind in ("searches", "downloads"):
            q = ix.get(kind)
            if not isinstance(q, dict) or q.get("used") is None:
                continue
            lab = f'{h},indexer="{esc(ix["name"])}",kind="{kind}"'
            out.append(f"indexer_used{{{lab}}} {q['used']}")
            if q.get("limit") is not None:
                out.append(f"indexer_limit{{{lab}}} {q['limit']}")
    out.append(f"indexer_bar_ok{{{h}}} {1 if usage.get('ok') else 0}")
    if usage.get("generated"):
        out.append(f"indexer_bar_generated_timestamp_seconds{{{h}}} {int(_ts(usage['generated']))}")
    return "\n".join(out) + "\n"


def run_indexers() -> int:
    write_atomic(TEXTFILE_DIR / "status_indexers_fastpi.prom", indexer_lines(json.loads(ABR_USAGE.read_text()), "fastpi"))
    return 0


MODES = {"certs": run_certs, "domains": run_domains, "subscriptions": run_subscriptions, "indexers": run_indexers}


def main(argv) -> int:
    if not argv or any(a not in MODES for a in argv):
        print(__doc__, file=sys.stderr)
        return 2
    rc = 0
    for a in argv:
        try:
            rc |= MODES[a]()
        except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
            print(f"status-exporter: {a}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
