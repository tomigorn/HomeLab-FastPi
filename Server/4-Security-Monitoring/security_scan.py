#!/usr/bin/env python3
"""Security posture scan -> Prometheus textfile metrics.

Covers four concerns in one scheduled job, because they share all their
plumbing (mirror fetch, metric rendering, staleness handling) and because four
separate timers would be four things to notice had stopped:

  1. secrets   - gitleaks over the PUBLISHED history of each public repo
  2. hygiene   - every secret-ish file on this host is git-ignored
  3. patches   - pending OS updates, security ones counted separately
  4. images    - Trivy CVE counts for running container images

WHY SCAN THE GITHUB MIRROR RATHER THAN THE LOCAL CLONE: the question worth
answering is "is a secret visible to the world", and only the remote can answer
that. A local-only scan misses anything pushed from another machine (the Mac,
the Bazzite box) and keeps reporting clean while beefy - whose repo it cannot
see at all - is powered off. Mirroring from GitHub also means beefy's repo is
still checked on the nights beefy is asleep.

STALENESS, NOT ABSENCE: beefy powers itself off when idle, so any per-host
figure is routinely unobtainable. When a host cannot be reached its previous
metrics are LEFT IN PLACE rather than written as zero. Zero would read as
"beefy has no pending security updates", which is the failure this whole file
exists to avoid - see the *_last_success_timestamp_seconds metrics and the
staleness alerts in grafana/prometheus/rules/security-posture.yml.
"""
from __future__ import annotations

import datetime
import glob
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path(os.environ.get("SECSCAN_STATE", "/var/lib/security-scan"))
TEXTFILE = Path(os.environ.get("SECSCAN_TEXTFILE", "/var/lib/node-exporter/textfile"))
GITLEAKS = os.environ.get("GITLEAKS_BIN", "/usr/local/bin/gitleaks")
CONFIG = Path(os.environ.get("SECSCAN_CONFIG", "/home/pi/Projects/.gitleaks.toml"))

REPOS = {
    "fastpi": "https://github.com/tomigorn/HomeLab-FastPi.git",
    "beefy": "https://github.com/tomigorn/HomeLab-BeefyServer.git",
}

# Dotted basename components that mean "this file holds key material or
# credentials". Matched as whole components rather than as substrings, because a
# substring test flags keyboard-layout.md and pemdas.js, and a matcher that cries
# wolf is one you stop reading.
#
# Note what is absent: .crt/.cer/.pub. A certificate and a public key are public
# by definition, and flagging them would bury the private key sitting next to
# them in the same directory.
SECRET_COMPONENTS = frozenset({
    "env", "secret", "secrets",
    "key", "pem", "der",                      # raw key material
    "p12", "pfx", "p8", "pkcs8", "jks", "keystore", "ppk",   # key containers
    "kdbx", "gpg", "asc",                     # password vaults / encrypted blobs
    "ovpn",                                   # bundles an inline private key
    "tfstate", "tfvars",                      # Terraform: plaintext credentials
})
# Whole basenames that are secrets by convention and carry no revealing suffix.
SECRET_BASENAMES = frozenset({
    "secrets", "secrets.yaml", "secrets.yml", "secrets.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", "netrc", ".htpasswd", "htpasswd", ".pgpass",
})
# Committed-on-purpose templates. These are checked for real values separately.
TEMPLATE_MARKERS = (".example", ".sample", ".template", ".dist")
# Suffixes that make a file a DERIVATIVE of another: templates, and - the ones
# that matter - editor and hand-made backups. `.gitignore` entries for `.env` do
# not match `.env.bak`, so a copy made while debugging is genuinely committable
# while the original is safe. Stripped before the secret test so that
# `.env.bak` and `secrets.yaml.example` are both recognised.
DERIVATIVE_SUFFIXES = TEMPLATE_MARKERS + (
    ".bak", ".backup", ".old", ".orig", ".save", ".saved", ".copy", ".tmp",
    ".swp", ".swo", ".rej", ".new", "~",
)


# ---------------------------------------------------------------------------
# Pure functions. Everything here is exercised by test_security_scan.py; the
# I/O below is a thin shell around them so the parsing logic can be tested
# without a repo, an apt database or a Docker daemon.
# ---------------------------------------------------------------------------

def is_template(path: str) -> bool:
    """True for files committed deliberately as fill-in-the-blanks templates."""
    low = path.lower()
    return any(m in low for m in TEMPLATE_MARKERS)


def _strip_derivative_suffixes(base: str) -> str:
    """Peel template/backup suffixes off a basename, repeatedly.

    `.env.example.old` -> `.env`. Looping matters: stacked suffixes are common
    on files that have been copied more than once.
    """
    changed = True
    while changed:
        changed = False
        for suf in DERIVATIVE_SUFFIXES:
            if base.endswith(suf) and len(base) > len(suf):
                base = base[: -len(suf)]
                changed = True
    return base


def looks_like_secret_file(path: str) -> bool:
    """True for paths that should never be committed with real contents.

    Derivative suffixes are peeled off first (so `.env.bak` counts), then the
    remaining basename is matched component-wise. Component matching is what
    lets `ci.2025-10-24.private-key.pem.PKCS8` resolve - a real key found
    unchecked on fastpi, whose final suffix appears in no list - while leaving
    `keyboard-layout.md` and `environment.yml` alone.
    """
    base = _strip_derivative_suffixes(os.path.basename(path).lower())
    if base in SECRET_BASENAMES:
        return True
    # A trailing .pub marks the public half of a keypair; never a secret.
    if base.endswith(".pub"):
        return False
    return any(c in SECRET_COMPONENTS for c in base.split("."))


def classify_secret_file(path: str, *, tracked: bool, ignored: bool) -> str:
    """Verdict for one secret-ish file found in a working tree.

    'ok'        - ignored by git, or a deliberate template
    'template'  - tracked, but a template (contents checked elsewhere)
    'exposed'   - tracked and not a template: it is IN the public repo
    'at_risk'   - neither tracked nor ignored, so `git add -A` would commit it
    """
    if is_template(path):
        return "template" if tracked else "ok"
    if tracked:
        return "exposed"
    if ignored:
        return "ok"
    return "at_risk"


def triage_findings(findings: list[dict]) -> dict[str, int]:
    """Collapse a gitleaks JSON report into counts by rule."""
    out: dict[str, int] = {}
    for f in findings:
        out[f.get("RuleID", "unknown")] = out.get(f.get("RuleID", "unknown"), 0) + 1
    return out


def parse_apt_upgradable(text: str) -> dict[str, int]:
    """Count pending packages from `apt list --upgradable` output.

    A package is counted as a security update when its candidate comes from a
    -security pocket, which is the same signal unattended-upgrades acts on.
    Deliberately does not shell out to apt-get -s, whose output format has
    changed between releases.
    """
    total = security = 0
    for line in text.splitlines():
        if "/" not in line or "[upgradable from:" not in line:
            continue
        total += 1
        pocket = line.split("/", 1)[1].split()[0]
        if "-security" in pocket:
            security += 1
    return {"total": total, "security": security}


def parse_trivy(report: dict) -> dict[str, int]:
    """Count vulnerabilities by severity from a Trivy JSON report."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for res in report.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            sev = (v.get("Severity") or "UNKNOWN").upper()
            counts[sev] = counts.get(sev, 0) + 1
    return counts


def count_fixable(report: dict) -> dict[str, int]:
    """Count only the vulnerabilities that an image update could actually fix.

    Trivy sets FixedVersion when an upstream fix exists. Without one, no image
    update resolves the finding - the only options are dropping the component or
    accepting the risk. Reporting the two together turns a backlog figure into a
    to-do list that can never reach zero, which is the fastest way to teach
    yourself to ignore it.
    """
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for res in report.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            if not v.get("FixedVersion"):
                continue
            sev = (v.get("Severity") or "UNKNOWN").upper()
            counts[sev] = counts.get(sev, 0) + 1
    return counts


_ENV_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def parse_env(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = _ENV_RE.match(line)
        if m and not line.lstrip().startswith("#"):
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def resolve_vars(s: str, env: dict[str, str]) -> str | None:
    """Compose-style ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?msg}, $VAR; None when a value is missing."""
    missing = False

    def sub(m):
        nonlocal missing
        name = m.group(1) or m.group(4)
        op, arg = m.group(2), m.group(3)
        val = env.get(name)
        if op in (":-", "-") and (val is None or (op == ":-" and val == "")):
            return arg
        if val is None or (val == "" and op == ":?"):
            missing = True
            return ""
        return val
    out = _VAR_RE.sub(sub, s)
    return None if missing else out


def compose_images(text: str, env: dict[str, str], built: set | None = None) -> tuple[list[str], int]:
    """image: refs of a compose file, ${VAR} resolved; services with build: are local and skipped. -> (refs, unresolved)."""
    services: dict[str, dict] = {}
    in_services, svc_indent, cur = False, None, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_services = line.startswith("services:")
            cur = None
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = indent
        if indent == svc_indent and line.rstrip().endswith(":"):
            cur = services.setdefault(line.strip()[:-1], {})
            continue
        if cur is None or indent <= svc_indent:
            continue
        m = re.match(r"\s*(image|build)\s*:\s*(.*)$", line)
        if m:
            cur[m.group(1)] = m.group(2).split(" #", 1)[0].strip().strip("'\"")
    if built is not None:
        built.update(resolve_vars(v["image"], env) or v["image"] for v in services.values() if "build" in v and v.get("image"))
    refs, unresolved = [], 0
    for svc in services.values():
        if "build" in svc or not svc.get("image"):
            continue
        ref = resolve_vars(svc["image"], env)
        if not ref or ref.endswith(":"):
            unresolved += 1
        elif ref not in refs:
            refs.append(ref)
    return refs, unresolved


CODE_SKIP = ("Docker/_Deprecated/", )
CODE_SKIP_FILES = ("Docker/docker-compose.yaml", )


def code_image_refs(files: dict[str, str]) -> tuple[list[str], int]:
    """Every registry image a repo refers to: compose image: lines (with the dir's .env, else .env.example) and Dockerfile FROM bases."""
    refs: set[str] = set()
    built: set[str] = set()
    unresolved = 0
    for path, text in files.items():
        if path.startswith(CODE_SKIP) or path in CODE_SKIP_FILES:
            continue
        d, base = path.rsplit("/", 1) if "/" in path else ("", path)
        if re.fullmatch(r"(docker-)?compose[\w.-]*\.ya?ml", base):
            env = parse_env(files.get(f"{d}/.env") or files.get(f"{d}/.env.example") or "")
            r, u = compose_images(text, env, built)
            refs.update(r)
            unresolved += u
        elif base.startswith("Dockerfile"):
            refs.update(dockerfile_bases(text))
    return sorted(refs - built), unresolved


def fixable_findings(report: dict) -> set[tuple[str, str, str]]:
    """(id, package, severity) of the CRITICAL/HIGH vulnerabilities that have an upstream fix."""
    out = set()
    for res in report.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            sev = (v.get("Severity") or "").upper()
            if sev in ("CRITICAL", "HIGH") and v.get("FixedVersion"):
                out.add((v.get("VulnerabilityID", "?"), v.get("PkgName", "?"), sev))
    return out


def cup_snapshots(data: dict) -> dict[str, dict]:
    """Cup's JSON -> {host: {taken_at, images: [...]}}, every monitored image of the host, with or without update."""
    taken = data.get("last_updated") or ""
    out: dict[str, dict] = {}
    for img in data.get("images") or []:
        host = img.get("server") or "fastpi"
        res = img.get("result") or {}
        det = res.get("info") or {}
        update = res.get("has_update")
        kind = det.get("version_update_type") if det.get("type") == "version" else det.get("type")
        out.setdefault(host, {"taken_at": taken, "images": []})["images"].append({
            "reference": img.get("reference", "?"),
            "in_use": bool(img.get("in_use")),
            "has_update": update,
            "type": (kind or "unknown") if update else "",
            "current": det.get("current_version") or "",
            "latest": det.get("new_version") or det.get("new_tag") or "",
        })
    return out


def diff_findings(seen: dict | None, current: dict[str, str], now: float, scanned: set | None = None) -> tuple[dict, list[str]]:
    """current {image|id|pkg: severity} against the seen state -> (new state, keys new this run).

    No state yet = first run: everything becomes the accepted baseline (first_seen 0), so installing this does not page the whole backlog. Keys no longer present are dropped, unless their image was not scanned this run (`scanned`): a failed scan must not make old findings look new next time.
    """
    if seen is None:
        return {k: {"severity": v, "first_seen": 0} for k, v in current.items()}, []
    out = {k: v for k, v in seen.items() if scanned is not None and k.rsplit("|", 2)[0] not in scanned}
    new = []
    for k, sev in current.items():
        if k in seen:
            out[k] = seen[k]
        else:
            out[k] = {"severity": sev, "first_seen": now}
            new.append(k)
    return out, sorted(new)


def baseline_new_images(seen: dict | None, current: dict[str, str], known: set) -> dict | None:
    """Findings of an image the scan has never seen (a first SBOM, a ref new to the repo) join the baseline: its backlog is in the reports and CriticalImageVulnerabilities, not "new"."""
    if seen is None:
        return None
    out = dict(seen)
    for k, sev in current.items():
        if k.rsplit("|", 2)[0] not in known and k not in out:
            out[k] = {"severity": sev, "first_seen": 0}
    return out


NEW_VULN_WINDOW = 86400


def new_vuln_samples(scope: str, seen: dict, now: float, cap: int = 20) -> list:
    """Findings first seen in the last 24 h: a count, and up to `cap` info series (newest first) for the alert to quote."""
    fresh = sorted(((v["first_seen"], k, v["severity"]) for k, v in seen.items()
                    if v["first_seen"] and now - v["first_seen"] < NEW_VULN_WINDOW), reverse=True)
    out = [("security_new_vulns", {"scope": scope}, len(fresh))]
    for _, k, sev in fresh[:cap]:
        image, vid, pkg = k.rsplit("|", 2)
        out.append(("security_new_vuln_info", {"scope": scope, "image": image, "id": vid, "pkg": pkg, "severity": sev}, 1))
    return out


def sbom_refresh_order(refs: list[str], made: dict[str, float], now: float, max_age: float, budget: int) -> list[str]:
    """Which SBOMs to (re)build this run: missing ones first, then the oldest stale ones, at most `budget` (registry pulls are rate-limited)."""
    missing = [r for r in refs if r not in made]
    stale = sorted((made[r], r) for r in refs if r in made and now - made[r] >= max_age)
    return (missing + [r for _, r in stale])[:budget]


def render_metrics(samples: list[tuple[str, dict[str, str], float]], helps: dict[str, str]) -> str:
    """Render Prometheus text format.

    Emits each HELP/TYPE once, before that metric's first sample, which the
    exposition format requires - node-exporter sets node_textfile_scrape_error=1
    and drops the WHOLE file if this is wrong, so a formatting slip here is
    silent loss of every metric in the file, not just one.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for name, labels, value in samples:
        if name not in seen:
            seen.add(name)
            lines.append(f"# HELP {name} {helps.get(name, name)}")
            lines.append(f"# TYPE {name} gauge")
        if labels:
            lab = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{lab}}} {_fmt(value)}")
        else:
            lines.append(f"{name} {_fmt(value)}")
    return "\n".join(lines) + "\n"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


_SAMPLE_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{(?:\s*[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\\n]|\\.)*"\s*(?:,\s*[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\\n]|\\.)*"\s*)*,?\s*)?\})?'
    r' (?P<value>\S+)(?: (?P<ts>-?\d+))?$')
_META_RE = re.compile(r'^# (?P<kind>HELP|TYPE) (?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?: .*)?$')


def filter_exposition(text: str, prefix: str = "clamav_") -> str:
    """Keep only well-formed exposition lines for metrics starting with `prefix`.

    A file pulled from another host is republished into node-exporter's textfile
    directory, where one malformed line makes node-exporter drop the WHOLE
    file. So every line is checked and anything doubtful is dropped rather than
    passed on. HELP/TYPE are kept once and only before the metric's first
    sample, because a late or repeated TYPE is also a whole-file error.
    """
    out: list[str] = []
    meta_seen: set[tuple[str, str]] = set()
    sampled: set[str] = set()
    for line in text.splitlines():
        m = _META_RE.match(line)
        if m:
            name, kind = m["name"], m["kind"]
            if name.startswith(prefix) and name not in sampled and (name, kind) not in meta_seen:
                meta_seen.add((name, kind))
                out.append(line)
            continue
        m = _SAMPLE_RE.match(line)
        if not m or not m["name"].startswith(prefix):
            continue
        try:
            float(m["value"])
        except ValueError:
            continue
        sampled.add(m["name"])
        out.append(line)
    return "\n".join(out) + "\n" if out else ""


def parse_infected_list(text: str) -> list[tuple[str, str]]:
    """`last-infected.txt` (path TAB signature per hit) -> [(path, signature)]."""
    hits = []
    for line in text.splitlines():
        if not line.strip():
            continue
        path, _, sig = line.partition("\t")
        hits.append((path, sig.strip() or "unknown"))
    return hits


_FAILED_LOGIN_RE = re.compile(r"Failed password|Invalid user|authentication failure")
_ISO_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)\s")
_SYSLOG_TS_RE = re.compile(r"^([A-Z][a-z]{2}) +(\d{1,2}) (\d\d):(\d\d):(\d\d)\s")
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _log_timestamp(line: str, now: float) -> float | None:
    """Unix time of an ISO-8601 (rsyslog, journalctl -o short-iso) or classic syslog line."""
    from datetime import datetime
    m = _ISO_TS_RE.match(line)
    if m:
        off = m[2]
        if off == "Z":
            off = "+00:00"
        elif ":" not in off:
            off = off[:3] + ":" + off[3:]
        return datetime.fromisoformat(m[1] + off).timestamp()
    m = _SYSLOG_TS_RE.match(line)
    if m and m[1] in _MONTHS:
        year = time.localtime(now).tm_year
        fields = (_MONTHS[m[1]], int(m[2]), int(m[3]), int(m[4]), int(m[5]))
        ts = time.mktime((year, *fields, 0, 0, -1))
        if ts > now + 86400:   # classic syslog has no year: "Dec 31" read on 1 January
            ts = time.mktime((year - 1, *fields, 0, 0, -1))
        return ts
    return None


def count_failed_logins(text: str, now: float, window: int = 86400) -> int:
    """sshd lines saying Failed password / Invalid user / authentication failure within the window.

    One bad attempt usually logs two of these lines; the count is lines, which is what the threshold is set against.
    """
    n = 0
    for line in text.splitlines():
        if "sshd" not in line or not _FAILED_LOGIN_RE.search(line):
            continue
        ts = _log_timestamp(line, now)
        if ts is not None and now - window <= ts <= now + 300:
            n += 1
    return n


_SSH_ACCEPTED_RE = re.compile(r"sshd.*: Accepted \S+ for (\S+) from (\S+) port ")
SOURCE_CLASSES = (
    ("lan", ("192.168.1.0/24",)),
    ("vpn", ("10.24.5.5/32", "10.8.0.0/24")),   # wg-easy NAT address on traefik_wg, WireGuard client subnet
    ("tunnel", ("172.20.0.0/16",)),                # cloudflared's compose network
)


def classify_source(ip: str) -> str:
    """lan / vpn / tunnel / other for the address sshd saw."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "other"
    for name, nets in SOURCE_CLASSES:
        if any(addr in ipaddress.ip_network(n) for n in nets):
            return name
    return "other"


def parse_ssh_logins(text: str, now: float, window: int = 86400) -> dict[tuple[str, str], tuple[int, float]]:
    """Accepted sshd logins within the window: (user, source class) -> (count, newest timestamp)."""
    out: dict[tuple[str, str], tuple[int, float]] = {}
    for line in text.splitlines():
        m = _SSH_ACCEPTED_RE.search(line)
        if not m:
            continue
        ts = _log_timestamp(line, now)
        if ts is None or not now - window <= ts <= now + 300:
            continue
        key = (m[1], classify_source(m[2]))
        n, last = out.get(key, (0, 0.0))
        out[key] = (n + 1, max(last, ts))
    return out


INTEGRITY_PATHS = (
    "/home/*/.ssh/authorized_keys", "/root/.ssh/authorized_keys",
    "/etc/sudoers", "/etc/sudoers.d/*",
    "/etc/ssh/sshd_config", "/etc/ssh/sshd_config.d/*",
)


def integrity_targets(patterns=INTEGRITY_PATHS) -> list[str]:
    return sorted({p for pat in patterns for p in glob.glob(pat) if os.path.isfile(p)})


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integrity_diff(baseline: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    """ok / changed / new / missing per path."""
    out = {}
    for p in baseline.keys() | current.keys():
        if p not in current:
            out[p] = "missing"
        elif p not in baseline:
            out[p] = "new"
        else:
            out[p] = "ok" if baseline[p] == current[p] else "changed"
    return out


def integrity_samples(host: str, states: dict[str, str], current: dict[str, str]) -> list:
    out = [("security_integrity_files", {"host": host}, len(current))]
    for p, st in sorted(states.items()):
        out.append(("security_integrity_changed", {"host": host, "path": p}, 0 if st == "ok" else 1))
    for p, h in sorted(current.items()):
        out.append(("security_integrity_file_info", {"host": host, "path": p, "sha256_prefix": h[:12]}, 1))
    return out


def parse_rkhunter(text: str) -> list[str]:
    """One finding per `Warning:` line of `rkhunter --rwo`; indented continuation lines belong to it."""
    return [l.rstrip() for l in text.splitlines() if l.startswith("Warning:")]


_CHK_RE = re.compile(r"\bWARNING:|\bINFECTED\b", re.I)


# Scratch scripts and pages that change daily; Xor.DDoS flags any script in /tmp, the PHP check any .php there.
CHK_IGNORED_PATHS = ("/tmp/claude-*", "/tmp/*.sh")
CHK_IGNORABLE = ("Xor.DDoS", "suspicious PHP files")


def parse_chkrootkit_detail(text: str) -> list[tuple[str, list[str]]]:
    """`chkrootkit -q` -> [(finding, lines listed under it)]; findings are WARNING headers and INFECTED lines."""
    out: list[tuple[str, list[str]]] = []
    current = None
    for line in text.splitlines():
        if _CHK_RE.search(line):
            current = (line.rstrip(), [])
            out.append(current)
        elif not line.strip():
            current = None
        elif current is not None:
            current[1].append(line.strip())
    return out


def _chk_ignored(finding: str, paths: list[str]) -> bool:
    import fnmatch
    return (any(c in finding for c in CHK_IGNORABLE) and bool(paths)
            and all(any(fnmatch.fnmatch(p, g) for g in CHK_IGNORED_PATHS) for p in paths))


def parse_chkrootkit(text: str) -> list[str]:
    """chkrootkit findings by category (the header), not by listed path.

    The listed paths change every run (/proc/<pid>, scripts in /tmp), so the
    header is the stable identity. A Xor.DDoS or PHP finding whose paths are
    all scratch files (CHK_IGNORED_PATHS) is not a finding.
    """
    return [f for f, paths in parse_chkrootkit_detail(text) if not _chk_ignored(f, paths)]


def new_findings(findings: list[str], accepted: set[str]) -> list[str]:
    return [f for f in findings if f not in accepted]


def findings_fingerprint(findings: list[str]) -> int:
    """0 for no findings, else a 32-bit hash of the sorted set: RootkitWarning alerts when it changes, not while it stays."""
    if not findings:
        return 0
    return int(hashlib.sha256("\n".join(sorted(set(findings))).encode()).hexdigest()[:8], 16) or 1


def parse_lynis_report(text: str) -> tuple[int, int]:
    """(hardening index, warning count) from /var/log/lynis-report.dat."""
    index = None
    warnings = 0
    for line in text.splitlines():
        if line.startswith("hardening_index="):
            index = int(line.split("=", 1)[1])
        elif line.startswith("warning[]="):
            warnings += 1
    if index is None:
        raise ValueError("no hardening_index in the Lynis report")
    return index, warnings


def parse_audit_output(text: str) -> dict[str, tuple[str, int]]:
    """Split AUDIT_SCRIPT output into {tool: (output, return code)}."""
    out: dict[str, list] = {}
    tool = None
    for line in text.splitlines(keepends=True):
        if line.startswith("### rc ") and tool:
            out[tool][1] = int(line.split()[2])
        elif line.startswith("### "):
            tool = line[4:].strip()
            out[tool] = ["", -1]
        elif tool:
            out[tool][0] += line
    return {k: (v[0], v[1]) for k, v in out.items()}


_PLG_RE = re.compile(r'^(?P<dir>/\S+)/(?P<name>[^/]+)\.plg:<!ENTITY\s+version\s+"(?P<ver>[^"]*)"')
UNRAID_BUILTIN_PLUGINS = {"unRAIDServer", "unRAIDServer-"}


def parse_unraid_check(text: str) -> dict:
    """UNRAID_SCRIPT output -> {"os": (installed, available, newer), "plugins": {name: (installed, available|None)}}.

    Plugin versions come from `<!ENTITY version>` of the installed .plg
    (/var/log/plugins) and of the one `plugin checkall` just fetched
    (/tmp/plugins), the same comparison Unraid's own plugincheck makes.
    """
    head, _, rest = text.partition("### plugins\n")
    plg, _, os_json = rest.partition("### os\n")
    m = re.search(r'version="([^"]+)"', head)
    if not m:
        raise RuntimeError("no version in /etc/unraid-version")
    installed_os = m[1]
    installed: dict[str, str] = {}
    fetched: dict[str, str] = {}
    for line in plg.splitlines():
        pm = _PLG_RE.match(line)
        if not pm or pm["name"] in UNRAID_BUILTIN_PLUGINS:
            continue
        (installed if pm["dir"] == "/var/log/plugins" else fetched)[pm["name"]] = pm["ver"]
    try:
        os_check = json.loads(os_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"unraidcheck output is not JSON: {os_json.strip()[:200]}") from e
    if "error" in os_check or "version" not in os_check:
        raise RuntimeError(f"unraidcheck: {os_check.get('error', 'no version')}")
    newer = bool(os_check.get("isNewer"))
    available = os_check["version"] if newer else installed_os
    return {"os": (installed_os, available, newer),
            "plugins": {n: (v, fetched.get(n)) for n, v in sorted(installed.items())}}


def unraid_samples(check: dict) -> list:
    installed, available, newer = check["os"]
    out = [("security_unraid_os_update", {"installed": installed, "available": available}, 1 if newer else 0)]
    for name, (have, latest) in check["plugins"].items():
        # Unraid's plugincheck compares with strcmp; plugin versions are dates (2026.10.12).
        out.append(("security_unraid_plugin_update", {"plugin": name}, 1 if latest and latest > have else 0))
    return out


CUP_TYPES = ("major", "minor", "patch", "digest")


def parse_cup(data: dict) -> tuple[dict[str, dict[str, int]], list[tuple[str, str, str]]]:
    """Cup's /api/v3/json -> ({host: {type: count}}, [(host, reference, type)]).

    `server` null is fastpi itself. A host missing from the JSON (asleep at
    Cup's last refresh) is missing here too, never reported as zero.
    """
    hosts: dict[str, dict[str, int]] = {}
    info: set[tuple[str, str, str]] = set()
    for img in data.get("images") or []:
        host = img.get("server") or "fastpi"
        counts = hosts.setdefault(host, {"all": 0, **{t: 0 for t in CUP_TYPES}, "unknown": 0})
        res = img.get("result") or {}
        if res.get("has_update") is None:
            counts["unknown"] += 1
            continue
        if not res.get("has_update"):
            continue
        det = res.get("info") or {}
        kind = det.get("version_update_type") if det.get("type") == "version" else det.get("type")
        kind = kind if kind in CUP_TYPES else "unknown"
        if (host, img.get("reference", "?"), kind) in info:
            continue
        info.add((host, img.get("reference", "?"), kind))
        counts["all"] += 1
        counts[kind] += 1
    return hosts, sorted(info)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def write_atomic(path: Path, content: str) -> None:
    """Write via temp+rename so node-exporter never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def fetch_mirror(name: str, url: str) -> Path:
    """Keep a bare mirror of the published repo, so the scan sees what GitHub serves."""
    d = STATE / "mirrors" / f"{name}.git"
    if (d / "HEAD").exists():
        r = run(["git", "-C", str(d), "remote", "update", "--prune"], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"fetch {name}: {r.stderr.strip()[:200]}")
    else:
        d.parent.mkdir(parents=True, exist_ok=True)
        r = run(["git", "clone", "--mirror", url, str(d)], timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"clone {name}: {r.stderr.strip()[:200]}")
    return d


def scan_repo(name: str, path: Path) -> dict[str, int]:
    out = STATE / f"gitleaks-{name}.json"
    r = run([GITLEAKS, "git", str(path), "-c", str(CONFIG),
             "--report-format", "json", "--report-path", str(out),
             "--redact", "--exit-code", "0", "--log-level", "error"], timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"gitleaks {name}: rc={r.returncode} {r.stderr.strip()[:200]}")
    try:
        findings = json.loads(out.read_text() or "[]") or []
    except json.JSONDecodeError:
        findings = []
    return triage_findings(findings)


def check_hygiene(repo_dir: Path) -> dict[str, int]:
    """Classify every secret-ish file in a working tree."""
    verdicts = {"ok": 0, "template": 0, "exposed": 0, "at_risk": 0}
    details: list[str] = []
    r = run(["git", "-C", str(repo_dir), "ls-files"], timeout=120)
    tracked = set(r.stdout.splitlines())
    for p in repo_dir.rglob("*"):
        if ".git/" in str(p) or not p.is_file():
            continue
        rel = str(p.relative_to(repo_dir))
        if not looks_like_secret_file(rel):
            continue
        ig = run(["git", "-C", str(repo_dir), "check-ignore", "-q", rel], timeout=30).returncode == 0
        v = classify_secret_file(rel, tracked=rel in tracked, ignored=ig)
        verdicts[v] += 1
        if v in ("exposed", "at_risk"):
            details.append(f"{v}: {rel}")
    if details:
        (STATE / "hygiene-problems.txt").write_text("\n".join(details) + "\n")
    else:
        (STATE / "hygiene-problems.txt").write_text("")
    return verdicts


def store_cup_snapshots(data: dict) -> set[str]:
    """Keep the latest Cup snapshot per host; a host Cup dropped (offline) keeps its old file. Returns the hosts present now."""
    snaps = cup_snapshots(data)
    for host, snap in snaps.items():
        write_atomic(STATE / f"cup-snapshot-{host}.json", json.dumps(snap, indent=1, sort_keys=True))
    write_atomic(STATE / "cup-present.json", json.dumps({"present": sorted(snaps), "checked_at": time.time()}))
    return set(snaps)


def cup_asof_samples(hosts) -> list:
    """Time of the cached Cup snapshot of each host that has one; a sleeping host keeps showing its last snapshot with this time."""
    out = []
    for host in hosts:
        snap = _load_json(STATE / f"cup-snapshot-{host}.json") or {}
        try:
            ts = datetime.datetime.fromisoformat(snap["taken_at"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError, AttributeError):
            continue
        out.append(("security_cup_snapshot_timestamp_seconds", {"host": host}, ts))
    return out


def publish_cup_asof(hosts) -> None:
    """One file per host, separate from the data file (whose success time must stay the real one)."""
    for host in hosts:
        samples = cup_asof_samples([host])
        if samples:
            publish(f"cup-asof-{host}", samples, HELPS)


def _prom_name(subject: str) -> str:
    return "security_" + re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_") + ".prom"


def publish(subject: str, samples: list, helps: dict) -> None:
    """Write one subject's metrics to its OWN file.

    One file per subject rather than one combined file, specifically so that a
    subject which could not be collected keeps its previous file - and therefore
    its previous values and its previous success timestamp - untouched on disk.
    Rewriting a combined file would force a choice between inventing a zero for
    the missing host (reads as "beefy has no pending security updates") and
    dropping the series (reads as "nothing to see"). Both are the failure this
    file exists to prevent; leaving the old file to go stale is neither.
    """
    write_atomic(TEXTFILE / _prom_name(subject), render_metrics(samples, helps))


# tower's plain "tower" ssh alias fires a Wake-on-LAN (Match block in
# ~/.ssh/config), which would turn every nightly scan into a forced wake-up.
# "tower-direct" is the same box without that hook: asleep simply means
# unreachable, which guarded() already reports as staleness.
SSH_ALIAS = {"tower": "tower-direct"}
# Only the 04:00-04:30 scans (patches, images, logins) may wake beefy through plain "beefy"; the av/media/updates pulls never do (fetch_nowake) because the maintenance window keeps beefy up.
BEEFY_WAKE_WINDOW = ((4, 0), (4, 30))


def ssh_alias(host: str, now=None, wake: bool = True) -> str:
    if host == "beefy":
        t = (now or datetime.datetime.now()).timetuple()[3:5]
        return "beefy" if wake and BEEFY_WAKE_WINDOW[0] <= t < BEEFY_WAKE_WINDOW[1] else "beefy-direct"
    return SSH_ALIAS.get(host, host)


def ssh(host: str, cmd: str, timeout: int = 300, wake: bool = True) -> subprocess.CompletedProcess:
    return run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new", ssh_alias(host, wake=wake), cmd,
    ], timeout=timeout)


def host_reachable(host: str) -> bool:
    return ssh(host, "true", timeout=30).returncode == 0


# ---------------------------------------------------------------------------
# Collectors. Each returns samples, or raises. A raise leaves the previous
# .prom file in place.
# ---------------------------------------------------------------------------

def collect_patches(host: str) -> dict[str, int]:
    """Pending OS updates, with security ones counted separately.

    `apt list --upgradable` is used because it needs no privileges, so this runs
    as an ordinary user over SSH with no sudoers entry to maintain.
    """
    if host == "fastpi":
        r = run(["apt", "list", "--upgradable"], timeout=300)
    else:
        r = ssh(host, "apt list --upgradable")
    if r.returncode != 0:
        raise RuntimeError(f"apt on {host}: rc={r.returncode} {r.stderr.strip()[:200]}")
    return parse_apt_upgradable(r.stdout)


# buntu is not in beefy's docker group; tower's ssh user is root.
REMOTE_DOCKER = {"beefy": "sudo docker"}


def docker_cmd(host: str) -> str:
    return REMOTE_DOCKER.get(host, "docker")


def dockerfile_bases(text: str) -> list[str]:
    """External base images of a Dockerfile, in order: no scratch, earlier build stages or ARG variables."""
    stages: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        m = re.match(r"\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if not m:
            continue
        ref, alias = m.group(1), m.group(2)
        if alias:
            stages.add(alias.lower())
        if ref.lower() == "scratch" or ref.lower() in stages or "$" in ref or ref in out:
            continue
        out.append(ref)
    return out


def parse_local_bases(text: str) -> dict[str, list[str]]:
    """`## <image>` headers each followed by that image's Dockerfile text -> {image: bases}; images without a base are left out."""
    sections: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    return {img: b for img, lines in sections.items() if (b := dockerfile_bases("\n".join(lines)))}


def _repo(ref: str) -> str:
    """Repository part of an image reference: no digest, no tag."""
    ref = ref.split("@", 1)[0]
    return ref.rsplit(":", 1)[0] if ":" in ref.rsplit("/", 1)[-1] else ref


# Compose project dirs of the running containers on a remote host, with the FROM lines of the Dockerfiles in them (one level deep), read once while the host is awake.
LOCAL_BASES: dict[str, dict[str, list[str]]] = {}


def read_local_bases(host: str) -> dict[str, list[str]]:
    d = docker_cmd(host)
    cmd = (f"{d} ps --format '{{{{.Image}}}} {{{{.Label \"com.docker.compose.project.working_dir\"}}}}' | sort -u | "
           "while read i w; do [ -n \"$w\" ] || continue; echo \"## $i\"; cat \"$w\"/Dockerfile \"$w\"/*/Dockerfile 2>/dev/null; done; true")
    r = ssh(host, cmd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"local base images on {host}: {r.stderr.strip()[:200]}")
    return parse_local_bases(r.stdout)


def running_images(host: str) -> list[str]:
    if host in REMOTE_SCAN_HOSTS:
        return running_image_digests(host)
    cmd = f"{docker_cmd(host)} ps --format '{{{{.Image}}}}'"
    r = run(["docker", "ps", "--format", "{{.Image}}"], timeout=120) if host == "fastpi" else ssh(host, cmd)
    if r.returncode != 0:
        raise RuntimeError(f"docker ps on {host}: {r.stderr.strip()[:200]}")
    seen, out = set(), []
    for line in r.stdout.split():
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


# Hosts whose images are scanned FROM fastpi, straight from the registry, instead
# of on the host. tower (Unraid) hit a kernel ZFS oops on 2026-10-17 a minute
# after a Trivy container started writing its cache and image layers to the pool
# (since replaced by btrfs); nothing heavy runs there any more. Scanning the registry
# copy is only accurate if it is the SAME image, so running_image_digests()
# resolves each running container to its repo digest (repo@sha256:...), and the
# scan pins the platform because fastpi is arm64 and tower is amd64.
# beefy joined 2026-10-19: it is up until about 04:45, so after reading its digest list over ssh nothing more may need beefy. A locally built image (no registry copy) is not scanned itself: its Dockerfile base images are (LOCAL_BASES), and it is counted in security_images_local_only only when no base is known.
REMOTE_SCAN_HOSTS = {"tower": "linux/amd64", "beefy": "linux/amd64"}


def running_image_digests(host: str) -> list[str]:
    d = docker_cmd(host)
    cmd = (f"for i in $({d} ps --format '{{{{.Image}}}}' | sort -u); do "
           f"{d} image inspect -f '{{{{if .RepoDigests}}}}{{{{index .RepoDigests 0}}}}{{{{else}}}}'\"$i\"'{{{{end}}}}' \"$i\"; done")
    r = ssh(host, cmd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"docker ps on {host}: {r.stderr.strip()[:200]}")
    LOCAL_BASES[host] = read_local_bases(host)
    return sorted({line.strip() for line in r.stdout.splitlines() if line.strip()})


# Per-host Trivy wiring. Each host already runs a strictly read-only Docker
# socket proxy (POST=0) for Cup and telegraf, and Trivy needs exactly what those
# allow: GET /images/{name}/json and GET /images/{name}/get. Reusing it means no
# new socket consumer - the socket-hardening work cut that list down to Portainer
# on purpose, and a `:ro` socket mount would not have helped anyway, since it
# protects the socket FILE and not the root-equivalent API behind it.
# multi-arch index digest; update: see README, Trivy pin
TRIVY_IMAGE = "aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa"
TRIVY_HOSTS = {
    "fastpi": {
        "network": "socket_proxy",
        "docker_host": "tcp://socket-proxy-ro:2375",
        "cache": "/var/lib/security-scan/trivy-cache",
    },
}


def _trivy_cmd(host: str, args: list[str], *, attach_proxy: bool) -> list[str]:
    """Build a Trivy invocation; it always runs on fastpi."""
    if host in REMOTE_SCAN_HOSTS:   # runs on fastpi, needs the internet, no socket
        return ["docker", "run", "--rm",
                "-v", f"{TRIVY_HOSTS['fastpi']['cache']}:/root/.cache/trivy",
                "-v", _vex_mount(),
                TRIVY_IMAGE, *args]
    cfg = TRIVY_HOSTS[host]
    net = ["--network", cfg["network"], "-e", f"DOCKER_HOST={cfg['docker_host']}"] if attach_proxy else []
    return ["docker", "run", "--rm", *net,
            "-v", f"{cfg['cache']}:/root/.cache/trivy",
            "-v", _vex_mount(),
            TRIVY_IMAGE, *args]


def _trivy_run(host: str, args: list[str], *, attach_proxy: bool, timeout: int):
    return run(_trivy_cmd(host, args, attach_proxy=attach_proxy), timeout=timeout)


def download_trivy_db(host: str) -> None:
    """Fetch the vulnerability DB with internet access and NO socket attached.

    Split from the scan because both socket proxies sit on `internal: true`
    networks - correctly, nothing there has any business reaching the internet -
    so a container attached to one cannot resolve mirror.gcr.io. Trivy fails with
    a DB download error that looks like a network fault rather than a design
    decision, which is worth the two-phase split to avoid rediscovering.
    """
    for args, label in (
        (["image", "--download-db-only"], "vuln"),
        # Trivy keeps a SEPARATE index for Java archives and fetches it lazily,
        # at scan time, the first time it meets a .jar - from inside the internal
        # network, where it cannot. Observed on 2026-10-09: every Java image
        # (languagetool, jenkins) came back unscannable with a DNS error for
        # mirror.gcr.io while non-Java images scanned fine. Pre-fetching it here
        # is the fix; --skip-java-db-update in the scan then keeps it offline.
        (["image", "--download-java-db-only"], "java"),
    ):
        r = _trivy_run(host, args, attach_proxy=False, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError(f"trivy {label}-db download on {host}: {r.stderr.strip()[-300:]}")


_REGISTRY_MISSING_RE = re.compile(r"UNAUTHORIZED|MANIFEST_UNKNOWN|NAME_UNKNOWN|repository does not exist")


def image_only_local(ref: str, trivy_error: str = "") -> bool:
    """True for an image a remote-source scan cannot reach: built locally, in no registry.

    Either it resolved to no repo digest, or the registry refused it (Docker
    Hub answers UNAUTHORIZED for a repository that does not exist).
    """
    return "@sha256:" not in ref or bool(_REGISTRY_MISSING_RE.search(trivy_error))


def scan_all_images(hosts, lister, scan) -> None:
    """Read every host's running-image list first, then scan.

    The lists are the only part that needs the host; the Trivy part runs on
    fastpi against the registry and may take an hour, by which time beefy has
    powered itself off. A failed list is handed to that host's scan as the
    exception, so the scan reports it.
    """
    lists = {}
    for h in hosts:
        try:
            lists[h] = lister(h)
        except Exception as e:  # noqa: BLE001
            lists[h] = e
    for h in hosts:
        scan(h, lists[h])


# host -> {image|id|pkg: severity} of the last nightly scan, diffed into security_new_vulns{scope=host}.
IMAGE_FINDINGS: dict[str, dict[str, str]] = {}
SCANNED: dict[str, set] = {}


def collect_images(host: str, images: list[str]) -> tuple[dict[str, int], dict[str, int], int, int, int]:
    """Trivy CVE counts across the images actually in use on a host.

    Only running images are scanned. Cup already reports that 11 of beefy's 12
    and a minority of fastpi's images are in use; a CVE in an image nothing runs
    is not a finding, and padding the totals with them would make a genuinely
    rising count impossible to notice.

    --skip-db-update because download_trivy_db() has already run; without it
    every image scan re-checks the registry from inside a network that cannot
    reach it.
    """
    totals = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    fixables = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    scanned = unscannable = 0
    local_only: list[str] = []
    # Per-image detail goes to a file rather than into labels. 60+ images times
    # five severities is cardinality Prometheus does not need to carry for a
    # figure that is read once a week, and an aggregate alert that cannot say
    # WHICH image is just a number to feel bad about.
    detail: list[tuple[int, int, str]] = []
    download_trivy_db(host)
    platform = REMOTE_SCAN_HOSTS.get(host)
    src = ["--image-src", "remote", "--platform", platform] if platform else ["--image-src", "docker"]
    bases_of = {_repo(k): v for k, v in LOCAL_BASES.get(host, {}).items()}
    queue = [(i, False) for i in images]
    seen = set(images)
    while queue:
        image, is_base = queue.pop(0)
        if platform and not is_base and image_only_local(image):
            bases = bases_of.get(_repo(image), [])
            for b in bases:
                if b not in seen:
                    seen.add(b)
                    queue.append((b, True))
            if not bases:
                local_only.append(image)
            continue
        r = _trivy_run(host, [
            "image", *src, "--scanners", "vuln",
            "--skip-db-update", "--skip-java-db-update",
            "--quiet", "--format", "json", *vex_args(host, image),
            "--timeout", "10m", image,
        ], attach_proxy=not platform, timeout=1200)
        if r.returncode != 0 or not r.stdout.strip():
            if platform and not is_base and image_only_local(image, r.stderr):
                bases = bases_of.get(_repo(image), [])
                for b in bases:
                    if b not in seen:
                        seen.add(b)
                        queue.append((b, True))
                if not bases:
                    local_only.append(image)
                continue
            unscannable += 1
            print(f"  unscannable on {host}: {image} ({r.stderr.strip()[-160:]})", file=sys.stderr)
            continue
        try:
            report = json.loads(r.stdout)
            counts = parse_trivy(report)
        except json.JSONDecodeError:
            unscannable += 1
            print(f"  unparseable on {host}: {image}", file=sys.stderr)
            continue
        scanned += 1
        fixable = count_fixable(report)
        SCANNED.setdefault(host, set()).add(image)
        for vid, pkg, sev in fixable_findings(report):
            IMAGE_FINDINGS.setdefault(host, {})[f"{image}|{vid}|{pkg}"] = sev
        detail.append((counts.get("CRITICAL", 0), counts.get("HIGH", 0),
                       fixable.get("CRITICAL", 0), f"{image} (base of a local image)" if is_base else image))
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        for k, v in fixable.items():
            fixables[k] = fixables.get(k, 0) + v

    detail.sort(reverse=True)
    lines = [f"# Trivy CVE counts for images in use on {host}, worst first.",
             "# 'fixable' = criticals with an upstream FixedVersion; the rest cannot",
             "# be resolved by any image update.",
             "# critical  fixable  high  image", ""]
    lines += [f"{c:>8}  {f:>7}  {h:>4}  {img}" for c, h, f, img in detail]
    if unscannable:
        lines += ["", f"# {unscannable} image(s) could not be scanned - see journalctl -u security-image-scan"]
    if local_only:
        lines += ["", "# built locally, in no registry, no base image known, not scanned:"] + [f"#   {i}" for i in local_only]
    (STATE / f"image-cves-{host}.txt").write_text("\n".join(lines) + "\n")
    return totals, fixables, scanned, unscannable, len(local_only)


# ---- hourly code scan: images the repos refer to, matched against a fresh DB via cached SBOMs

CODE_REPOS = {"fastpi": "linux/arm64", "beefy": "linux/amd64"}
SBOM_DIR = STATE / "sbom"
SBOM_MAX_AGE = 86400
# Docker Hub allows 100 manifest requests an hour and answers bursts with 429; the nightly scan and Cup need it too.
SBOM_BUDGET_HUB = int(os.environ.get("SECSCAN_SBOM_BUDGET_HUB", "4"))
SBOM_BUDGET_OTHER = int(os.environ.get("SECSCAN_SBOM_BUDGET_OTHER", "12"))


def is_docker_hub(ref: str) -> bool:
    first = ref.split("/", 1)[0]
    return "/" not in ref or first == "docker.io" or not ("." in first or ":" in first or first == "localhost")


def code_files(repo: str) -> dict[str, str]:
    """Compose files, Dockerfiles and env files: fastpi's working tree (with its .env), beefy's published mirror (.env.example only)."""
    want = lambda p: (b := p.rsplit("/", 1)[-1]).startswith("Dockerfile") or b == ".env.example" or re.fullmatch(r"(docker-)?compose[\w.-]*\.ya?ml", b)  # noqa: E731
    files: dict[str, str] = {}
    if repo == "fastpi":
        root = Path("/home/pi/Projects")
        r = run(["git", "-C", str(root), "ls-files"], timeout=60)
        for p in filter(want, r.stdout.split()):
            try:
                files[p] = (root / p).read_text(errors="replace")
                env = (root / p).with_name(".env")
                if p.endswith(".env.example") and env.exists():
                    files[p[:-len(".example")]] = env.read_text(errors="replace")
            except OSError:
                continue
        return files
    d = fetch_mirror(repo, REPOS[repo])
    r = run(["git", "-C", str(d), "ls-tree", "-r", "--name-only", "HEAD"], timeout=60)
    for p in filter(want, r.stdout.split()):
        files[p] = run(["git", "-C", str(d), "show", f"HEAD:{p}"], timeout=60).stdout
    return files


def _sbom_name(platform: str, ref: str) -> str:
    return hashlib.sha256(f"{platform}|{ref}".encode()).hexdigest()[:24]


def _trivy_mounted(args: list[str], *, entrypoint: str | None = None, timeout: int = 1800):
    cmd = ["docker", "run", "--rm", "-v", f"{TRIVY_HOSTS['fastpi']['cache']}:/root/.cache/trivy",
           "-v", f"{SBOM_DIR}:/sbom", "-v", _vex_mount()]
    if entrypoint:
        cmd += ["--entrypoint", entrypoint]
    return run(cmd + [TRIVY_IMAGE, *args], timeout=timeout)


def refresh_sboms(platform: str, refs: list[str], index: dict) -> None:
    """Build missing/stale CycloneDX SBOMs from the registry, within the per-run budget. index[key] = {made, ok, ref, platform}."""
    now = time.time()
    made = {r: index[f"{platform}|{r}"]["made"] for r in refs if f"{platform}|{r}" in index}
    hub = [r for r in refs if is_docker_hub(r)]
    other = [r for r in refs if not is_docker_hub(r)]
    todo = sbom_refresh_order(hub, made, now, SBOM_MAX_AGE, SBOM_BUDGET_HUB) + \
        sbom_refresh_order(other, made, now, SBOM_MAX_AGE, SBOM_BUDGET_OTHER)
    for ref in todo:
        name = _sbom_name(platform, ref)
        r = _trivy_mounted(["image", "--image-src", "remote", "--platform", platform,
                            "--skip-db-update", "--skip-java-db-update", "--quiet",
                            "--format", "cyclonedx", "--output", f"/sbom/{name}.cdx.json", "--timeout", "10m", ref])
        ok = r.returncode == 0 and (SBOM_DIR / f"{name}.cdx.json").exists()
        local = not ok and bool(_REGISTRY_MISSING_RE.search(r.stderr))
        if local:
            print(f"  local-only {platform} {ref}: not in any registry, skipped", file=sys.stderr)
        elif not ok:
            print(f"  sbom failed {platform} {ref}: {r.stderr.strip()[-160:]}", file=sys.stderr)
        prev = index.get(f"{platform}|{ref}", {})
        index[f"{platform}|{ref}"] = {"made": time.time(), "ok": ok or prev.get("ok", False), "local": local, "ref": ref, "platform": platform}


def match_script(names: dict[str, str], host: str) -> str:
    """Shell loop for one Trivy container: every SBOM against the local DB, with the VEX file of its DT project when there is one."""
    return "".join(
        f"trivy sbom --skip-db-update --skip-java-db-update --quiet --scanners vuln --format json "
        f"{' '.join(shlex.quote(a) for a in vex_args(host, ref))} --output /sbom/out/{n}.json /sbom/{n}.cdx.json || echo FAIL {n} >&2; "
        for n, ref in sorted(names.items()))


def match_sboms(names: dict[str, str], host: str) -> dict[str, dict]:
    """One Trivy container matches every SBOM against the local DB (no registry): name -> report."""
    out_dir = SBOM_DIR / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    script = match_script(names, host)
    r = _trivy_mounted(["-c", script], entrypoint="sh", timeout=3600)
    if r.stderr.strip():
        print(f"  sbom match: {r.stderr.strip()[-300:]}", file=sys.stderr)
    reports = {}
    for n in names:
        try:
            reports[n] = json.loads((out_dir / f"{n}.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def findings_samples(scope: str, current: dict[str, str], scanned: set) -> list:
    """Diff against vulns-seen-<scope>.json, persist, and return the new-vulnerability samples."""
    path = STATE / f"vulns-seen-{scope}.json"
    state = _load_json(path)
    known = set(state["images"]) if state else set()
    prev = baseline_new_images(state["findings"] if state else None, current, known)
    seen, new = diff_findings(prev, current, time.time(), scanned)
    write_atomic(path, json.dumps({"images": sorted(known | scanned), "findings": seen}, indent=1, sort_keys=True))
    for k in new:
        print(f"  NEW {scope}: {k} ({current[k]})", file=sys.stderr)
    return new_vuln_samples(scope, seen, time.time())


def resource_floor() -> str:
    with open("/proc/meminfo") as fh:
        avail = next(int(l.split()[1]) // 1024 for l in fh if l.startswith("MemAvailable:"))
    disk = shutil.disk_usage(str(STATE)).free // 2**30
    return f"{avail} MB available, {disk} GB free" if avail < 1200 or disk < 20 else ""


def collect_code(repo: str) -> list:
    if floor := resource_floor():
        raise NoData(f"resource floor: {floor}")
    platform = CODE_REPOS[repo]
    refs, unresolved = code_image_refs(code_files(repo))
    refs = sorted({*refs, TRIVY_IMAGE})
    SBOM_DIR.mkdir(parents=True, exist_ok=True)
    index = _load_json(SBOM_DIR / "index.json") or {}
    download_trivy_db("fastpi")
    refresh_sboms(platform, refs, index)
    write_atomic(SBOM_DIR / "index.json", json.dumps(index, indent=1, sort_keys=True))
    names = {_sbom_name(platform, r): r for r in refs if index.get(f"{platform}|{r}", {}).get("ok")}
    reports = match_sboms(names, repo)
    current: dict[str, str] = {}
    sev = {"CRITICAL": 0, "HIGH": 0}
    lines = [f"# Fixable CRITICAL/HIGH in images the {repo} repo refers to (SBOM {platform}), worst first.", "# critical  high  image", ""]
    rows = []
    for n, rep in reports.items():
        f = fixable_findings(rep)
        c = sum(1 for x in f if x[2] == "CRITICAL")
        h = len(f) - c
        sev["CRITICAL"] += c
        sev["HIGH"] += h
        rows.append((c, h, names[n]))
        for vid, pkg, s in f:
            current[f"{names[n]}|{vid}|{pkg}"] = s
    rows.sort(reverse=True)
    lines += [f"{c:>8}  {h:>4}  {img}" for c, h, img in rows]
    missing = sorted(set(refs) - {names[n] for n in reports})
    if missing:
        lines += ["", "# no SBOM yet (a few are built per hour) or not in a registry (retried after 24 h):"] + [f"#   {m}" for m in missing]
    (STATE / f"code-cves-{repo}.txt").write_text("\n".join(lines) + "\n")
    scope = f"code-{repo}"
    out = [("security_code_images", {"scope": scope}, len(refs)),
           ("security_code_images_scanned", {"scope": scope}, len(reports)),
           ("security_code_images_unresolved", {"scope": scope}, unresolved)]
    out += [("security_code_vulnerabilities_fixable", {"scope": scope, "severity": k}, v) for k, v in sorted(sev.items())]
    return out + findings_samples(scope, current, {names[n] for n in reports})


class NoData(Exception):
    """The source exists but has nothing to report yet: leave old data, flag nothing."""


# Hit lists are labels on an info series so the MalwareFound alert can quote them; capped so a mass infection cannot blow up cardinality.
AV_HIT_LIMIT = 20
AV_PATHS = {
    "fastpi": {"infected": "/var/lib/clamav-scan/last-infected.txt",
               "index": "/mnt/seagate-red/antivirus-quarantine/index.txt"},
    "beefy": {"prom": "/var/lib/clamav-scan/textfile/clamav.prom",
              "hook": "/var/lib/clamav-scan/textfile/clamav-hook.prom",   # SABnzbd/qBittorrent completion hook, mode="hook"
              "infected": "/var/lib/clamav-scan/last-infected.txt",
              # clamav-hook.py: time, mode (hook/queue), title, path, signature of each hit it quarantined
              "hits": "/var/lib/clamav-scan/textfile/clamav-hits.tsv",
              # the SSD branch, not the /srv/video union (same file): reading it never spins up the HDD
              "index": "/srv/.disks/ssd-hot/quarantine/index.txt"},
    "tower": {"prom": "/mnt/data/appdata/clamav/textfile/clamav.prom",
              "infected": "/mnt/data/system/clamav/state/last-infected.txt",   # STATE in tower up.sh, outside the scan roots
              "index": "/mnt/data/appdata/clamav/quarantine/index.txt"},
}
# index.txt lines older than this were there before MalwareQuarantined existed (the EICAR tests of 2026-10-26): baseline, no alert.
AV_HITS_SINCE = datetime.datetime.fromisoformat("2026-10-26T21:00:00+01:00").timestamp()
AV_HITS_WINDOW = 86400
# Modes per host: scan = scan.sh (nightly new, or a path scan by hand); beefy also hook (SABnzbd/qBittorrent completion, synchronous) and queue (background media scan).
AV_HIT_MODES = {"beefy": ("scan", "hook", "queue")}
# clamav-hook.py's MEDIA_EXT: these go to the background queue, everything else is scanned by the hook itself.
AV_QUEUE_EXT = {"mkv", "mp4", "m4v", "avi", "mov", "wmv", "ts", "m2ts", "webm", "m4a", "m4b", "mp3", "flac", "opus", "ogg",
                "aac", "srt", "ass", "ssa", "sub", "idx", "sup", "nfo", "txt", "jpg", "jpeg", "png"}


def collect_av(host: str, fetch) -> list:
    """Republish a host's clamav.prom as clamav_<host>.prom and its hit list.

    `fetch(what)` returns the file's text, or None when the file does not exist.
    fastpi's own clamav.prom is written by its scanner straight into the
    textfile directory, so only its hit list is collected here.
    """
    if "prom" in AV_PATHS.get(host, {"prom": None}):
        raw = fetch("prom")
        if raw is None:
            raise NoData(f"no clamav.prom on {host} yet")
        prom = filter_exposition(raw)
        if not prom:
            raise NoData(f"clamav.prom on {host} has no clamav_ samples")
    else:
        prom = None
    infected = fetch("infected") or ""
    hits = parse_infected_list(infected)
    (STATE / f"last-infected-{host}.txt").write_text(infected)
    if prom is not None:
        write_atomic(TEXTFILE / f"clamav_{host}.prom", prom)
    if "hook" in AV_PATHS.get(host, {}):
        # Optional: no hook run yet just means no hook file; the nightly file decides NoData.
        hook = filter_exposition(fetch("hook") or "")
        if hook:
            write_atomic(TEXTFILE / f"clamav_hook_{host}.prom", hook)
    return [("security_av_infected_info", {"host": host, "path": p, "signature": sig}, 1)
            for p, sig in hits[:AV_HIT_LIMIT]]


def parse_quarantine_index(text: str) -> list[dict]:
    """index.txt of a quarantine (time TAB original path TAB signature [TAB restored <time>]) -> hits, malformed lines dropped."""
    hits = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 3 or not f[1]:
            continue
        try:
            ts = datetime.datetime.fromisoformat(f[0]).timestamp()
        except ValueError:
            continue
        hits.append({"time": f[0], "ts": ts, "path": f[1], "signature": f[2].strip() or "unknown",
                     "restored": any(x.startswith("restored") for x in f[3:])})
    return hits


def hit_title(path: str) -> str:
    """The download (folder below complete/ or downloads/), else the folder the file was in."""
    parts = path.split("/")
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] in ("complete", "downloads") and i + 1 < len(parts) - 1:
            return parts[i + 1]
    return parts[-2] if len(parts) > 1 and parts[-2] else parts[-1]


def parse_hits_log(text: str) -> dict:
    """clamav-hits.tsv (time TAB mode TAB title TAB path TAB signature) -> {index line key: (mode, title)}."""
    out = {}
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) == 5 and f[1] and f[3]:
            out[f"{f[0]}\t{f[3]}\t{f[4].strip()}"] = (f[1], f[2].strip())
    return out


def hit_mode(host: str, path: str, nightly_paths: set) -> str:
    """index.txt does not record who wrote a line: scan.sh hits are in last-infected.txt, on beefy media names went to the queue."""
    if host not in AV_HIT_MODES or path in nightly_paths:
        return "scan"
    return "queue" if path.rsplit(".", 1)[-1].lower() in AV_QUEUE_EXT else "hook"


def _hit_time_label(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%a, %d %b %Y %H:%M")


def collect_av_hits(host: str, fetch, now: float | None = None) -> list:
    """Quarantined hits from index.txt, sticky for 24 h from when fastpi first saw them (not the resettable last-run gauge).

    `fetch(what)` returns "index" / "infected" text or None. Seen lines are kept in av-hits-seen-<host>.json; on the first
    run lines older than AV_HITS_SINCE are baseline (first_seen 0) and never alert.
    """
    now = time.time() if now is None else now
    text = fetch("index")
    if text is None:
        raise NoData(f"no quarantine index.txt on {host} yet")
    nightly = {p for p, _ in parse_infected_list(fetch("infected") or "")}
    logged = parse_hits_log((fetch("hits") if "hits" in AV_PATHS.get(host, {}) else None) or "")
    hits = parse_quarantine_index(text)
    import fcntl
    # security-av (nightly) and security-av-hits (15 min) can overlap: one reader-writer of the seen file at a time.
    with open(STATE / f".av-hits-{host}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _av_hit_samples(host, hits, nightly, now, logged)


def _av_hit_samples(host: str, hits: list, nightly: set, now: float, logged: dict | None = None) -> list:
    path = STATE / f"av-hits-seen-{host}.json"
    seen = _load_json(path)
    if seen is None:
        seen = {_hit_key(h): 0 for h in hits if h["ts"] < AV_HITS_SINCE}
    keys = set()
    active = []
    for h in hits:
        k = _hit_key(h)
        keys.add(k)
        first = seen.setdefault(k, now)
        if first and now - first < AV_HITS_WINDOW and not h["restored"]:
            active.append((first, h))
    write_atomic(path, json.dumps({k: v for k, v in seen.items() if k in keys}, indent=1, sort_keys=True))
    counts = {m: 0 for m in AV_HIT_MODES.get(host, ("scan",))}
    out = []
    for first, h in sorted(active, key=lambda a: (a[1]["ts"], a[0]), reverse=True):
        # The hook's own record wins; without one (scan.sh, an older line) mode and title are inferred from the path.
        mode, title = (logged or {}).get(_hit_key(h), (None, None))
        mode = mode or hit_mode(host, h["path"], nightly)
        counts[mode] = counts.get(mode, 0) + 1
        if len(out) < AV_HIT_LIMIT:
            out.append(("clamav_quarantine_hit_first_seen_timestamp_seconds",
                        {"host": host, "mode": mode, "title": title or hit_title(h["path"]), "file": h["path"].rsplit("/", 1)[-1],
                         "path": h["path"], "signature": h["signature"], "time": _hit_time_label(h["ts"])}, first))
    return out + [("clamav_quarantine_hits_24h", {"host": host, "mode": m}, n) for m, n in counts.items()]


def _hit_key(h: dict) -> str:
    return f"{h['time']}\t{h['path']}\t{h['signature']}"


# Movie-Downloads' language-missing.py (titles still waiting for a Swiss German release); alerts: grafana/prometheus/rules/media-language.yml.
MEDIA_PATHS = {"beefy": "/home/buntu/.local/state/movie-downloads/media-language.prom"}


def collect_media(host: str, fetch) -> list:
    """Republish beefy's media-language.prom as media_language_<host>.prom (only media_language_ samples)."""
    raw = fetch()
    if raw is None:
        raise NoData(f"no media-language.prom on {host} yet")
    prom = filter_exposition(raw, prefix="media_language_")
    if not prom:
        raise NoData(f"media-language.prom on {host} has no media_language_ samples")
    write_atomic(TEXTFILE / f"media_language_{host}.prom", prom)
    return []


# beefy's nightly image auto-update (Docker/_global/scripts/auto_update.py, the same file as fastpi's); alerts: grafana/prometheus/rules/auto-updates.yml.
UPDATES_PATHS = {"beefy": "/var/lib/auto-update/textfile/auto_update.prom"}


def collect_updates(host: str, fetch) -> list:
    """Republish a host's auto_update.prom as auto_update_<host>.prom.

    Only samples labelled host="<host>" pass, so they can never collide with fastpi's own auto_update.prom (one duplicate series breaks node-exporter's whole textfile collector). HELP is dropped (auto_update.py writes none): node-exporter rejects a family whose files disagree on HELP.
    """
    raw = fetch()
    if raw is None:
        raise NoData(f"no auto_update.prom on {host} yet")
    mine = f'host="{host}"'
    keep = [ln for ln in filter_exposition(raw, prefix="auto_update_").splitlines()
            if ln.startswith("# TYPE ") or (not ln.startswith("#") and mine in ln.split("}", 1)[0])]
    if not any(not ln.startswith("#") for ln in keep):
        raise NoData(f"auto_update.prom on {host} has no samples for host {host}")
    write_atomic(TEXTFILE / f"auto_update_{host}.prom", "\n".join(keep) + "\n")
    return []


def fetch_file(host: str, path: str, wake: bool = True) -> str | None:
    """A file's text, locally on fastpi or over ssh; None when it does not exist."""
    if host == "fastpi":
        try:
            return Path(path).read_text()
        except FileNotFoundError:
            return None
    r = ssh(host, f"test -e {path} || exit 3; cat {path}", timeout=60, wake=wake)
    if r.returncode == 3:
        return None
    if r.returncode != 0:
        raise RuntimeError(f"read {path} on {host}: rc={r.returncode} {r.stderr.strip()[:200]}")
    return r.stdout


def fetch_nowake(host: str, path: str) -> str | None:
    """Like fetch_file, but never wakes beefy or tower: a host the Waker sees down is skipped."""
    if host != "fastpi" and not host_awake(host):
        raise NoData(f"{host} asleep, skipped")
    return fetch_file(host, path, wake=False)


AUTH_LOGS = {"beefy": "/var/log/auth.log", "tower": "/var/log/syslog"}


def collect_failed_logins(host: str) -> int:
    if host == "fastpi":
        r = run(["journalctl", "_COMM=sshd", "_COMM=sshd-session", "--since", "-24h",
                 "-o", "short-iso", "--no-pager", "-q"], timeout=120)
    else:
        log = AUTH_LOGS[host]
        # The rotated file too: the 24 h window crosses the weekly rotation once a week.
        r = ssh(host, f"for f in {log}.1 {log}; do [ -r $f ] && grep -hE "
                      f"'sshd.*(Failed password|Invalid user|authentication failure)' $f; done; [ -r {log} ]",
                timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"auth log on {host}: rc={r.returncode} {r.stderr.strip()[:200]}")
    return count_failed_logins(r.stdout, time.time())


def collect_ssh_logins(host: str = "fastpi") -> list:
    r = run(["journalctl", "_COMM=sshd", "_COMM=sshd-session", "--since", "-24h",
             "-o", "short-iso", "--no-pager", "-q"], timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"journalctl: rc={r.returncode} {r.stderr.strip()[:200]}")
    out = []
    for (user, cls), (n, last) in sorted(parse_ssh_logins(r.stdout, time.time()).items()):
        labels = {"host": host, "user": user, "source_class": cls}
        out.append(("security_ssh_logins", labels, n))
        out.append(("security_ssh_last_login_timestamp_seconds", labels, last))
    return out


def collect_integrity(host: str = "fastpi") -> list:
    """Hashes against the baseline in STATE; the first run accepts what it finds (like rkhunter --propupd)."""
    current = {p: hash_file(Path(p)) for p in integrity_targets()}
    baseline_file = STATE / f"integrity-baseline-{host}.json"
    if not baseline_file.exists():
        write_atomic(baseline_file, json.dumps(current, indent=1, sort_keys=True) + "\n")
    baseline = json.loads(baseline_file.read_text())
    return integrity_samples(host, integrity_diff(baseline, current), current)


# beefy first: it is only up until about 04:45.
AUDIT_HOSTS = ("beefy", "fastpi")
# rc lines are separate so a tool that failed is told apart from one that found something. rkhunter exits 1 when it has warnings.
AUDIT_SCRIPT = (
    "echo '### rkhunter'; sudo -n rkhunter --check --sk --rwo --nocolors 2>&1; echo \"### rc $?\"; "
    "echo '### chkrootkit'; sudo -n chkrootkit -q 2>&1; echo \"### rc $?\"; "
    "echo '### lynis'; sudo -n lynis audit system --quick --quiet --no-colors >/dev/null 2>&1; echo \"### rc $?\"; "
    "sudo -n cat /var/log/lynis-report.dat"
)
AUDIT_OK_RC = {"rkhunter": (0, 1), "chkrootkit": (0,), "lynis": (0,)}


def audit_samples(host: str, text: str) -> list:
    """Metrics from one host's AUDIT_SCRIPT output, against the accepted baseline.

    Both rootkit checkers report known false positives on a stock system
    (uutils coreutils on Ubuntu 26.04 reads as INFECTED to chkrootkit). The
    first run accepts what it finds, the way `rkhunter --propupd` accepts the
    current binaries; afterwards only findings not in the baseline count.
    Re-accept: delete /var/lib/security-scan/audit-accepted-<host>-<tool>.txt.
    """
    sections = parse_audit_output(text)
    for tool, ok in AUDIT_OK_RC.items():
        if tool not in sections or sections[tool][1] not in ok:
            rc = sections.get(tool, ("", "missing"))[1]
            raise RuntimeError(f"{tool} on {host}: rc={rc} {sections.get(tool, ('', 0))[0].strip()[-200:]}")
    samples = []
    report = [f"# rkhunter / chkrootkit findings on {host}. NEW = not in the accepted baseline.",
              f"# Re-accept a tool: rm /var/lib/security-scan/audit-accepted-{host}-<tool>.txt", ""]
    for tool, parse in (("rkhunter", parse_rkhunter), ("chkrootkit", parse_chkrootkit)):
        findings = parse(sections[tool][0])
        base = STATE / f"audit-accepted-{host}-{tool}.txt"
        if not base.exists():
            base.write_text("".join(f + "\n" for f in findings))
        accepted = set(base.read_text().splitlines())
        new = new_findings(findings, accepted)
        samples.append(("security_rootkit_warnings", {"host": host, "tool": tool}, len(new)))
        samples.append(("security_rootkit_findings", {"host": host, "tool": tool}, len(findings)))
        samples.append(("security_rootkit_new_fingerprint", {"host": host, "tool": tool}, findings_fingerprint(new)))
        report.append(f"## {tool}")
        if tool == "chkrootkit":
            for f, paths in parse_chkrootkit_detail(sections[tool][0]):
                report.append(("ignored  " if f not in findings else "NEW      " if f in new else "ok       ") + f)
                report += [f"        {p}" for p in paths]
        else:
            report += [("NEW      " if f in new else "ok       ") + f for f in findings]
        report.append("")
    index, warnings = parse_lynis_report(sections["lynis"][0])
    samples.append(("security_lynis_hardening_index", {"host": host}, index))
    samples.append(("security_lynis_warnings", {"host": host}, warnings))
    report += ["## lynis", f"hardening_index={index} warnings={warnings}"]
    report += [l for l in sections["lynis"][0].splitlines() if l.startswith("warning[]=")]
    (STATE / f"audit-{host}.txt").write_text("\n".join(report) + "\n")
    return samples


def collect_audit(host: str) -> list:
    if host == "fastpi":
        r = run(["bash", "-c", AUDIT_SCRIPT], timeout=3600)
    else:
        r = ssh(host, AUDIT_SCRIPT, timeout=3600)
    if r.returncode != 0 and "### lynis" not in r.stdout:
        raise RuntimeError(f"audit on {host}: rc={r.returncode} {r.stderr.strip()[:200]}")
    return audit_samples(host, r.stdout)


# `plugin checkall` only downloads the latest .plg files into /tmp/plugins (RAM). Not plugincheck/unraidcheck as they are: both send an Unraid notification per update; json=true makes unraidcheck print its result and exit before notifying.
UNRAID_SCRIPT = (
    "cat /etc/unraid-version; echo '### plugins'; plugin checkall >/dev/null 2>&1; "
    "grep -m1 -H 'ENTITY version' /var/log/plugins/*.plg /tmp/plugins/*.plg 2>/dev/null; echo '### os'; "
    "QUERY_STRING=json=true /usr/local/emhttp/plugins/dynamix.plugin.manager/scripts/unraidcheck"
)


def collect_unraid() -> list:
    r = ssh("tower", UNRAID_SCRIPT, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"unraid check on tower: rc={r.returncode} {r.stderr.strip()[:200]}")
    return unraid_samples(parse_unraid_check(r.stdout))


CUP_URL = os.environ.get("SECSCAN_CUP_URL", "http://172.24.0.1:8000")
# Waker status endpoints answer without waking anything; Cup's own refresh runs Sundays 04:00, when beefy and tower are usually off.
WAKER_STATUS = {"beefy": "http://192.168.1.2:9001/status", "tower": "http://192.168.1.2:9002/status"}


def _http_get(url: str, timeout: int) -> bytes:
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def host_awake(host: str) -> bool:
    try:
        return bool(json.loads(_http_get(WAKER_STATUS[host], 5)).get("up"))
    except Exception:  # noqa: BLE001
        return False


def cup_missing_reason(host: str, awake: dict[str, bool]) -> str:
    if awake.get(host) is False:
        return f"{host} not reachable (asleep or off), skipped"
    return f"{host} not in Cup's last result (its agent did not answer or is not in cup.json servers)"


def read_cup() -> tuple[dict, dict[str, bool]]:
    awake_map = {h: host_awake(h) for h in WAKER_STATUS}
    awake = [h for h, up in awake_map.items() if up]
    if awake:
        print(f"cup refresh, awake: {', '.join(awake)}", file=sys.stderr)
        try:
            _http_get(f"{CUP_URL}/api/v3/refresh", 300)
        except Exception as e:  # noqa: BLE001
            print(f"cup refresh failed, using the last result: {e}", file=sys.stderr)
    return json.loads(_http_get(f"{CUP_URL}/api/v3/json", 60)), awake_map


# ---- Triage in Dependency-Track -> VEX for Trivy: DT analysis decisions exported per project, cached under STATE/vex
VEX_STATES = {"NOT_AFFECTED": "not_affected", "FALSE_POSITIVE": "not_affected", "RESOLVED": "fixed"}


def vex_dir() -> Path:
    return STATE / "vex"


def _vex_mount() -> str:
    try:
        vex_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return f"{vex_dir()}:/vex:ro"


def vex_filename(name: str, version: str) -> str:
    return hashlib.sha256(f"{name}|{version}".encode()).hexdigest()[:24] + ".openvex.json"


def vex_statements(findings: list[dict]) -> list[dict]:
    """DT findings -> OpenVEX statements for the triage decisions only (one per vulnerability id and alias, product = the component purl)."""
    out = []
    for f in findings:
        an = f.get("analysis") or {}
        status = VEX_STATES.get(an.get("state"))
        purl = (f.get("component") or {}).get("purl")
        if not status or not purl:
            continue
        vuln = f.get("vulnerability") or {}
        ids = [vuln.get("vulnId")]
        for al in vuln.get("aliases") or []:
            ids += list(al.values()) if isinstance(al, dict) else [al]
        for vid in dict.fromkeys(i for i in ids if i):
            st = {"vulnerability": {"name": vid}, "products": [{"@id": purl}], "status": status}
            if status == "not_affected":
                st["justification"] = "vulnerable_code_not_in_execute_path"
            if an.get("detail"):
                st["impact_statement" if status == "not_affected" else "status_notes"] = str(an["detail"])[:500]
            out.append(st)
    return out


def build_openvex(statements: list[dict], now: float) -> dict:
    return {"@context": "https://openvex.dev/ns/v0.2.0", "@id": "https://holy-grail.ch/vex/dependency-track",
            "author": "Dependency-Track triage", "version": 1,
            "timestamp": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "statements": statements}


def export_dt_vex(dt, projects: list[dict]) -> list:
    """One OpenVEX file per DT project that has decisions. A project whose export fails keeps its cached file; projects gone from DT or without decisions lose theirs."""
    d = vex_dir()
    d.mkdir(parents=True, exist_ok=True)
    keep, total, failed = set(), 0, 0
    for p in projects:
        if not p.get("version"):
            continue
        name = vex_filename(p["name"], p["version"])
        try:
            st = vex_statements(dt.findings(p["uuid"]))
        except Exception as e:  # noqa: BLE001
            failed += 1
            keep.add(name)
            print(f"  vex export failed for {p['name']} {p['version']}: {e}", file=sys.stderr)
            continue
        if st:
            keep.add(name)
            total += len(st)
            write_atomic(d / name, json.dumps(build_openvex(st, time.time()), indent=1))
    for f in d.glob("*.openvex.json"):
        if f.name not in keep:
            f.unlink()
    files = len([k for k in keep if (d / k).exists()])
    return [("security_dt_vex_projects", {}, files), ("security_dt_vex_statements", {}, total),
            ("security_dt_vex_export_failed", {}, failed)]


def vex_args(host: str, ref: str) -> list[str]:
    """`--vex <file>` for the DT project of an image (matched by name+tag, or by digest through dt-index.json); empty when it has no decisions."""
    names = [dt_project(host, ref)]
    index = _load_json(STATE / "dt-index.json") or {}
    names += [tuple(k.rsplit("|", 1)) for k, v in index.items() if v == ref and k.startswith(host + "/")]
    for name, version in names:
        if (vex_dir() / vex_filename(name, version)).exists():
            return ["--vex", f"/vex/{vex_filename(name, version)}"]
    return []


# ---- Dependency-Track feed (group dt): SBOMs of the running images and of the host OS -> DT on beefy (HomeLab-BeefyServer Docker/Dependency-Track)
DT_URL = os.environ.get("SECSCAN_DT_URL", "http://192.168.1.102:8090")
DT_KEY = Path(os.environ.get("SECSCAN_DT_KEY", "/var/lib/security-scan/secrets/dt-api-key"))
# None = images from the local Docker (socket proxy); a platform = SBOM from the registry copy of the running digest, built on fastpi.
DT_HOSTS = {"fastpi": None, "beefy": "linux/amd64"}
# Own layer cache: Trivy's cache is a single-writer bolt DB, and an SBOM needs no vulnerability DB.
DT_TRIVY_CACHE = "/var/lib/security-scan/trivy-cache-dt"
_IMAGE_ID_RE = re.compile(r"(sha256:)?[0-9a-f]{12,64}")


def dt_project(host: str, ref: str) -> tuple[str, str]:
    """Image reference -> DT project (host/repository without registry, tag; digest-only refs get sha256:<12 hex>)."""
    base, _, digest = ref.partition("@")
    repo = _repo(base)
    tag = base[len(repo) + 1:] if len(base) > len(repo) else ""
    parts = repo.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        parts = parts[1:]
    if parts[0] == "library" and len(parts) > 1:
        parts = parts[1:]
    version = tag or (digest[:19] if digest else "latest")
    return f"{host}/{'/'.join(parts)}", version


def parse_image_lines(text: str) -> list[dict]:
    """`ref|repo digest|image id` lines (one per running image) -> dicts."""
    out = []
    for line in text.splitlines():
        if line.strip():
            ref, digest, iid = (line.strip().split("|") + ["", ""])[:3]
            out.append({"ref": ref, "digest": digest, "id": iid})
    return out


def dt_plan(host: str, images: list[dict], bases: dict[str, list[str]], local: set = frozenset()) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Running images -> [(project, version, cache key, Trivy source)] and the images that cannot be scanned (local build, no base known).

    local: repo digests the registry refused (built on the host; a digest alone does not tell).
    """
    plan, skipped, seen = [], [], set()
    bases_of = {_repo(k): v for k, v in bases.items()}
    for img in images:
        ref, digest = img["ref"], img["digest"]
        named = digest if _IMAGE_ID_RE.fullmatch(ref) and digest else ref
        name, version = dt_project(host, named)
        if DT_HOSTS.get(host) is None:
            key, src = img["id"], ref
        elif digest and digest not in local:
            key = src = digest
        elif b := bases_of.get(_repo(ref)):
            version, key, src = f"{version} (base {b[-1]})", f"base:{b[-1]}", b[-1]
        else:
            skipped.append(ref)
            continue
        if (name, version) not in seen:
            seen.add((name, version))
            plan.append((name, version, key, src))
    return plan, skipped


def dt_os_project(host: str, os_release: str) -> tuple[str, str]:
    env = parse_env(os_release)
    return f"{host}/os", f"{env.get('ID', 'linux').strip(chr(34))} {env.get('VERSION_ID', '').strip(chr(34))}".strip()


def dt_stale(projects: list[dict], keep: set, hosts: set) -> list[dict]:
    """Projects under host/ that the host no longer runs (removed image, older tag); the host parent projects stay."""
    return [p for p in projects if "/" in p["name"] and p["name"].split("/", 1)[0] in hosts
            and (p["name"], p.get("version")) not in keep]


def dt_bom_payload(name: str, version: str, parent_uuid: str, bom: bytes) -> dict:
    import base64
    return {"projectName": name, "projectVersion": version, "parentUUID": parent_uuid,
            "autoCreate": True, "isLatest": True, "bom": base64.b64encode(bom).decode()}


def collect_dt(host: str, dt, plan: list, build_sbom, os_entry) -> list:
    """Upload what changed since the last upload (or vanished from DT), delete projects of images the host no longer runs."""
    path = STATE / "dt-index.json"
    index = _load_json(path) or {}
    projects = dt.projects()
    existing = {(p["name"], p.get("version")) for p in projects}
    parent = dt.ensure_parent(host, projects)
    entries = [(n, v, k, (lambda src=src, k=k: build_sbom(k, src))) for n, v, k, src in plan]
    if os_entry:
        entries.append(os_entry)
    keep, uploaded, failed = set(), 0, 0
    for name, version, key, build in entries:
        keep.add((name, version))
        if index.get(f"{name}|{version}") == key and (name, version) in existing:
            continue
        bom = build()
        if bom is None:
            failed += 1
            continue
        dt.upload(dt_bom_payload(name, version, parent, bom))
        index[f"{name}|{version}"] = key
        uploaded += 1
        write_atomic(path, json.dumps(index, indent=1, sort_keys=True))
    stale = dt_stale(projects, keep, {host})
    for p in stale:
        dt.delete(p["uuid"])
        index.pop(f"{p['name']}|{p.get('version')}", None)
    write_atomic(path, json.dumps(index, indent=1, sort_keys=True))
    return [("security_dt_projects", {"host": host}, len(keep)),
            ("security_dt_uploads", {"host": host}, uploaded),
            ("security_dt_sbom_failed", {"host": host}, failed),
            ("security_dt_stale_deleted", {"host": host}, len(stale))]


class DtClient:
    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key

    def _call(self, method: str, path: str, body=None, timeout: int = 120):
        return self._fetch(method, path, body, timeout)[0]

    def _fetch(self, method: str, path: str, body=None, timeout: int = 120):
        """(parsed body, X-Total-Count as int or None)"""
        import urllib.request
        req = urllib.request.Request(f"{self.url}/api{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-Api-Key": self.key, "Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode()
            total = r.headers.get("X-Total-Count")
            return (json.loads(text) if text.strip() else None), (int(total) if total and total.isdigit() else None)

    def projects(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._call("GET", f"/v1/project?pageSize=500&pageNumber={page}&excludeInactive=false") or []
            out += batch
            if len(batch) < 500:
                return out
            page += 1

    def ensure_parent(self, name: str, projects: list[dict]) -> str:
        """uuid of the host's parent project (name only, no version), created on first use."""
        for p in projects:
            if p["name"] == name and not p.get("version"):
                return p["uuid"]
        return self._call("PUT", "/v1/project", {"name": name, "classifier": "PLATFORM", "collectionLogic": "AGGREGATE_DIRECT_CHILDREN",
                                                  "description": f"Images and OS of {name}, uploaded by security_scan.py dt"})["uuid"]

    def upload(self, payload: dict) -> None:
        self._call("PUT", "/v1/bom", payload, timeout=300)

    def delete(self, uuid: str) -> None:
        self._call("DELETE", f"/v1/project/{uuid}")

    def findings(self, uuid: str) -> list[dict]:
        """All findings, paged (v5 defaults to 100 per page): stops at X-Total-Count, else on a short or empty page."""
        out, page, size = [], 1, 100
        while True:
            batch, total = self._fetch("GET", f"/v1/finding/project/{uuid}?suppressed=true&pageSize={size}&pageNumber={page}")
            batch = batch or []
            out += batch
            if not batch or (total is not None and len(out) >= total) or (total is None and len(batch) < size):
                return out
            page += 1


def dt_reachable() -> bool:
    """A TCP probe of DT's port: beefy asleep reads as unreachable, and nothing here wakes it."""
    import socket
    import urllib.parse
    u = urllib.parse.urlparse(DT_URL)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=3):
            return True
    except OSError:
        return False


def dt_images(host: str) -> tuple[list[dict], dict[str, list[str]]]:
    d = docker_cmd(host)
    cmd = (f"{d} ps --format '{{{{.Image}}}}' | sort -u | while read -r i; do "
           f"echo \"$i|$({d} image inspect -f '{{{{if .RepoDigests}}}}{{{{index .RepoDigests 0}}}}{{{{end}}}}|{{{{.Id}}}}' \"$i\")\"; done")
    r = run(["sh", "-c", cmd], timeout=120) if host == "fastpi" else ssh(host, cmd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"image list on {host}: {r.stderr.strip()[:200]}")
    bases = read_local_bases(host) if DT_HOSTS.get(host) else {}
    return parse_image_lines(r.stdout), bases


def _trivy_sbom_cmd(args: list[str], *, socket_proxy: bool = False, rootfs: Path | None = None) -> list[str]:
    cmd = ["docker", "run", "--rm"]
    if socket_proxy:
        cmd += ["--network", TRIVY_HOSTS["fastpi"]["network"], "-e", f"DOCKER_HOST={TRIVY_HOSTS['fastpi']['docker_host']}"]
    # the Java DB (jar identification, 1.5 GB) is the image scan's copy, read-only
    cmd += ["-v", f"{DT_TRIVY_CACHE}:/root/.cache/trivy",
            "-v", f"{TRIVY_HOSTS['fastpi']['cache']}/java-db:/root/.cache/trivy/java-db:ro"]
    if rootfs:
        cmd += ["-v", f"{rootfs}:/rootfs:ro"]
    return cmd + [TRIVY_IMAGE, args[0], "--format", "cyclonedx", "--quiet", "--skip-db-update",
                  "--skip-java-db-update", "--timeout", "15m", *args[1:]]


def _trivy_sbom(args: list[str], *, socket_proxy: bool = False, rootfs: Path | None = None) -> tuple[bytes | None, str]:
    r = run(_trivy_sbom_cmd(args, socket_proxy=socket_proxy, rootfs=rootfs), timeout=1800)
    if r.returncode != 0 or not r.stdout.strip().startswith("{"):
        print(f"  dt sbom failed {args[-1]}: {r.stderr.strip()[-200:]}", file=sys.stderr)
        return None, r.stderr
    return r.stdout.encode(), ""


def dt_image_sbom(host: str, key: str, src: str) -> bytes | None:
    """CycloneDX SBOM of one image, cached by key (image id or digest: the same key is the same content)."""
    cache = STATE / "sbom-dt"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{hashlib.sha256(f'{host}|{key}'.encode()).hexdigest()[:24]}.cdx.json"
    if f.exists() and not key.startswith("base:"):
        return f.read_bytes()
    platform = DT_HOSTS.get(host)
    args = ["image", "--image-src", "remote", "--platform", platform, src] if platform else ["image", "--image-src", "docker", src]
    bom, err = _trivy_sbom(args, socket_proxy=platform is None)
    if bom:
        write_atomic(f, bom.decode())
    elif platform and "@sha256:" in key and _REGISTRY_MISSING_RE.search(err):
        known = set(_load_json(STATE / "dt-local.json") or [])
        write_atomic(STATE / "dt-local.json", json.dumps(sorted(known | {key}), indent=1))
    return bom


def parse_os_dump(text: str) -> dict[str, str]:
    """`=== /path` headers each followed by that file -> {relative path: text}; files that came back empty (absent) are left out."""
    files, cur = {}, None
    for line in text.splitlines(keepends=True):
        if line.startswith("=== /"):
            cur = line[5:].strip()
            files[cur] = ""
        elif cur:
            files[cur] += line
    return {k: v for k, v in files.items() if v}


# Trivy detects Debian by debian_version and Ubuntu by lsb-release (Ubuntu also has a debian_version, "forky/sid").
DT_OS_FILES = ("etc/os-release", "etc/lsb-release", "etc/debian_version", "var/lib/dpkg/status")


def dt_os_entry(host: str):
    """(project, version, key, builder) for the host OS: Trivy rootfs over a tree of os-release, lsb-release, debian_version and the dpkg status."""
    cmd = "for f in " + " ".join("/" + f for f in DT_OS_FILES) + "; do echo \"=== $f\"; cat \"$f\" 2>/dev/null; done; true"
    r = run(["sh", "-c", cmd], timeout=120) if host == "fastpi" else ssh(host, cmd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"os files on {host}: {r.stderr.strip()[:200]}")
    texts = parse_os_dump(r.stdout)
    if "etc/os-release" not in texts or "var/lib/dpkg/status" not in texts:
        raise RuntimeError(f"os files on {host}: no os-release or dpkg status")
    name, version = dt_os_project(host, texts["etc/os-release"])
    key = hashlib.sha256("".join(f"{f}\0{texts[f]}" for f in sorted(texts)).encode()).hexdigest()[:24]

    def build():
        tree = STATE / "dt-os" / host
        shutil.rmtree(tree, ignore_errors=True)
        for f, text in texts.items():
            (tree / f).parent.mkdir(parents=True, exist_ok=True)
            (tree / f).write_text(text)
        return _trivy_sbom(["rootfs", "/rootfs"], rootfs=tree)[0]
    return name, version, key, build


HELPS = {
    "security_repo_leaks": "Secrets found by gitleaks in a repository's PUBLISHED history, by rule.",
    "security_repo_leaks_total": "Total secrets found by gitleaks in a repository's published history.",
    "security_scan_last_success_timestamp_seconds": "Unix time of the last successful collection of this subject.",
    "security_scan_errors": "1 if the last collection of this subject failed for a reason other than the host being asleep.",
    "security_scan_host_unreachable": "1 if the host could not be reached (expected for beefy, which powers off when idle).",
    "security_secret_files": "Secret-bearing files in the working tree, by verdict.",
    "security_pending_updates": "Pending OS package updates.",
    "security_image_vulnerabilities": "Trivy CVE count across images in use, by severity.",
    "security_image_vulnerabilities_fixable": "Subset of the above that an image update could actually fix (Trivy reports a FixedVersion).",
    "security_images_scanned": "Images successfully scanned by Trivy.",
    "security_images_unscannable": "Images Trivy could not scan, for any reason.",
    "security_images_local_only": "Images on beefy/tower built locally (in no registry), skipped by the registry scan.",
    "security_failed_logins_total": "Failed SSH logins in the last 24 h (log lines: Failed password, Invalid user, authentication failure).",
    "security_ssh_logins": "Accepted SSH logins in the last 24 h by user and source class (lan, vpn, tunnel, other).",
    "security_ssh_last_login_timestamp_seconds": "Time of the newest accepted SSH login of that user and source class in the last 24 h.",
    "security_integrity_changed": "1 if the file differs from, is new to, or is missing from the baseline integrity-baseline-<host>.json.",
    "security_integrity_files": "Files watched for integrity (authorized_keys, sudoers, sshd_config).",
    "security_integrity_file_info": "Current SHA-256 prefix (12 hex) of each watched file.",
    "security_rootkit_warnings": "rkhunter/chkrootkit findings NOT in the accepted baseline (audit-accepted-<host>-<tool>.txt).",
    "security_rootkit_findings": "All rkhunter/chkrootkit findings, accepted ones included.",
    "security_rootkit_new_fingerprint": "Hash of the set of findings NOT in the accepted baseline, 0 if none; changes when that set changes.",
    "security_lynis_hardening_index": "Lynis hardening index (0-100) from the weekly quick audit.",
    "security_lynis_warnings": "Lynis warnings in the weekly quick audit.",
    "security_unraid_os_update": "1 if a newer Unraid OS release is available on tower.",
    "security_unraid_plugin_update": "1 if a newer version of this Unraid plugin is available on tower.",
    "security_image_updates": "Images with an update according to Cup, per host and update type.",
    "security_cup_snapshot_timestamp_seconds": "Time of the Cup snapshot behind the host's image-update figures (a sleeping host shows its last snapshot).",
    "security_image_update_info": "One series per image with an update according to Cup (host, reference, type).",
    "security_code_images": "Registry images the repo refers to (compose image:, Dockerfile FROM; local builds excluded).",
    "security_code_images_scanned": "Of those, images with an SBOM matched against the current Trivy DB.",
    "security_code_images_unresolved": "image: lines whose ${VAR} could not be resolved from .env/.env.example.",
    "security_code_vulnerabilities_fixable": "Fixable CVEs across the images the repo refers to, by severity (CRITICAL/HIGH).",
    "security_new_vulns": "Fixable CRITICAL/HIGH findings (image, CVE, package) first seen in the last 24 h; scope = host (running images) or code-<repo>.",
    "security_new_vuln_info": "One series per finding first seen in the last 24 h (newest 20).",
    "security_av_infected_info": "One series per ClamAV hit of the host's last scan (path, signature), capped at 20.",
    "clamav_quarantine_hit_first_seen_timestamp_seconds": "One series per quarantined ClamAV hit (index.txt) first seen in the last 24 h, newest 20; value = when fastpi first saw it.",
    "clamav_quarantine_hits_24h": "Quarantined ClamAV hits (index.txt, not restored) first seen in the last 24 h, by mode (scan, hook, queue).",
    "security_dt_projects": "Dependency-Track projects of the host (running images + OS) after the last upload run.",
    "security_dt_uploads": "SBOMs uploaded to Dependency-Track in the last run (new or changed images).",
    "security_dt_sbom_failed": "Images whose SBOM could not be built in the last run (retried next run).",
    "security_dt_vex_projects": "DT projects with triage decisions (not affected, false positive, resolved) exported as VEX files for Trivy.",
    "security_dt_vex_statements": "VEX statements (one per vulnerability id) across those files.",
    "security_dt_vex_export_failed": "Projects whose decisions could not be read from DT in the last export (cached file kept).",
    "security_dt_stale_deleted": "Dependency-Track projects deleted in the last run (image no longer running).",
}


def guarded(subject: str, fn, *, host: str | None = None) -> None:
    """Run one collector; publish data on success, leave stale data on failure.

    The status metrics (errors, unreachable) live ONLY in the -status file and
    the data metrics ONLY in the data file. They must not overlap: the first
    version of this put errors=0 in the data file too, so when a collection
    failed the preserved data file kept asserting errors=0 while the status file
    said errors=1. Two samples, identical labels, and the exposition served the
    stale zero - the failure was hidden by its own fallback. Keeping each series
    in exactly one file is what makes that impossible rather than unlikely.
    """
    now = time.time()
    status_path = TEXTFILE / _prom_name(f"{subject}-status")
    try:
        samples = fn()
    except NoData as e:
        print(f"NODATA {subject}: {e}", file=sys.stderr)
        write_atomic(status_path, render_metrics([
            ("security_scan_errors", {"subject": subject}, 0),
            ("security_scan_host_unreachable", {"subject": subject}, 0),
        ], HELPS))
        return
    except Exception as e:  # noqa: BLE001
        # beefy powering off when idle is normal operation, not a fault; it is
        # reported on its own metric so the alert for a genuinely broken scan
        # does not fire every night that beefy happened to be asleep. Either way
        # the data file is left untouched and its timestamp goes stale, which is
        # what the staleness alert watches.
        unreachable = bool(host) and host != "fastpi" and not host_reachable(host)
        print(f"{'ASLEEP' if unreachable else 'ERROR'} {subject}: {e}", file=sys.stderr)
        write_atomic(status_path, render_metrics([
            ("security_scan_errors", {"subject": subject}, 0 if unreachable else 1),
            ("security_scan_host_unreachable", {"subject": subject}, 1 if unreachable else 0),
        ], HELPS))
        return
    publish(subject, samples + [
        ("security_scan_last_success_timestamp_seconds", {"subject": subject}, now),
    ], HELPS)
    write_atomic(status_path, render_metrics([
        ("security_scan_errors", {"subject": subject}, 0),
        ("security_scan_host_unreachable", {"subject": subject}, 0),
    ], HELPS))


def main() -> int:
    only = set(sys.argv[1:]) or None
    STATE.mkdir(parents=True, exist_ok=True)
    TEXTFILE.mkdir(parents=True, exist_ok=True)

    def want(group: str) -> bool:
        return only is None or group in only

    if want("secrets"):
        for name, url in REPOS.items():
            def _repo(name=name, url=url):
                counts = scan_repo(name, fetch_mirror(name, url))
                out = [("security_repo_leaks_total", {"repo": name}, sum(counts.values()))]
                out += [("security_repo_leaks", {"repo": name, "rule": r}, n) for r, n in sorted(counts.items())]
                return out
            guarded(f"repo-{name}", _repo)

        def _hyg():
            v = check_hygiene(Path("/home/pi/Projects"))
            return [("security_secret_files", {"host": "fastpi", "verdict": k}, n) for k, n in sorted(v.items())]
        guarded("hygiene-fastpi", _hyg)

    if want("patches"):
        for host in ("fastpi", "beefy"):
            def _pat(host=host):
                c = collect_patches(host)
                return [
                    ("security_pending_updates", {"host": host, "type": "all"}, c["total"]),
                    ("security_pending_updates", {"host": host, "type": "security"}, c["security"]),
                ]
            guarded(f"patches-{host}", _pat, host=host)
        guarded("patches-tower", collect_unraid, host="tower")

    if want("logins"):
        for host in ("fastpi", "beefy", "tower"):
            def _logins(host=host):
                return [("security_failed_logins_total", {"host": host}, collect_failed_logins(host))]
            guarded(f"logins-{host}", _logins, host=host)

    if only and "access" in only:
        guarded("ssh-logins-fastpi", collect_ssh_logins, host="fastpi")
        guarded("integrity-fastpi", collect_integrity, host="fastpi")

    if want("audit"):
        for host in AUDIT_HOSTS:
            guarded(f"audit-{host}", lambda host=host: collect_audit(host), host=host)

    if want("cup"):
        cup: dict = {}
        for host in ("fastpi", "beefy", "tower"):
            def _cup(host=host):
                if not cup:
                    # one attempt per run: a failed refresh is not retried for every host
                    try:
                        data, awake_map = read_cup()
                        store_cup_snapshots(data)
                        cup.update(zip(("hosts", "info"), parse_cup(data)), awake=awake_map)
                    except Exception as e:  # noqa: BLE001
                        cup["error"] = e
                if "error" in cup:
                    raise cup["error"]
                if host not in cup["hosts"]:
                    raise NoData(cup_missing_reason(host, cup["awake"]))
                out = [("security_image_updates", {"host": host, "type": t}, n)
                       for t, n in sorted(cup["hosts"][host].items())]
                out += [("security_image_update_info", {"host": h, "reference": ref, "type": t}, 1)
                        for h, ref, t in cup["info"] if h == host]
                return out
            guarded(f"cup-{host}", _cup)
        publish_cup_asof(("fastpi", "beefy", "tower"))

    if want("av"):
        for host in AV_PATHS:
            def _av(host=host):
                return collect_av(host, lambda what: fetch_nowake(host, AV_PATHS[host][what]))
            guarded(f"av-{host}", _av, host=host)
            guarded(f"avhits-{host}", lambda host=host: collect_av_hits(host, lambda what: fetch_nowake(host, AV_PATHS[host][what])), host=host)

    if only and "avhits" in only:
        # Every 15 min (security-av-hits.timer): beefy and tower only while the Waker sees them up, and never through a waking ssh alias.
        for host in AV_PATHS:
            def _hits(host=host):
                if host != "fastpi" and not host_awake(host):
                    raise NoData(f"{host} asleep, skipped")
                return collect_av_hits(host, lambda what: fetch_file(host, AV_PATHS[host][what], wake=False))
            guarded(f"avhits-{host}", _hits, host=host)

    if want("media"):
        for host in MEDIA_PATHS:
            guarded(f"media-{host}", lambda host=host: collect_media(host, lambda: fetch_nowake(host, MEDIA_PATHS[host])), host=host)

    if want("updates"):
        for host in UPDATES_PATHS:
            guarded(f"updates-{host}", lambda host=host: collect_updates(host, lambda: fetch_nowake(host, UPDATES_PATHS[host])), host=host)

    if only and "code" in only:
        for repo in CODE_REPOS:
            guarded(f"code-{repo}", lambda repo=repo: collect_code(repo))

    if only and "dt" in only:
        dt = DtClient(DT_URL, DT_KEY.read_text().strip()) if DT_KEY.exists() else None
        up = dt is not None and dt_reachable()
        for host in DT_HOSTS:
            def _dt(host=host):
                if dt is None:
                    raise RuntimeError(f"no API key at {DT_KEY}")
                if not up:
                    raise NoData(f"Dependency-Track at {DT_URL} not reachable (beefy asleep), skipped")
                if floor := resource_floor():
                    raise NoData(f"resource floor: {floor}")
                images, bases = dt_images(host)
                plan, skipped = dt_plan(host, images, bases, set(_load_json(STATE / "dt-local.json") or []))
                for ref in skipped:
                    print(f"  dt {host}: {ref} built locally, no base image known, skipped", file=sys.stderr)
                return collect_dt(host, dt, plan, lambda k, src: dt_image_sbom(host, k, src), dt_os_entry(host))
            guarded(f"dt-{host}", _dt, host=host)

        def _vex():
            if dt is None or not up:
                raise NoData("Dependency-Track not reachable (beefy asleep), cached VEX files stay in use")
            return export_dt_vex(dt, dt.projects())
        guarded("dt-vex", _vex)

    if want("images"):
        def _scan(host, images):
            def _img():
                if isinstance(images, Exception):
                    raise images
                totals, fixables, scanned, bad, local = collect_images(host, images)
                out = [("security_image_vulnerabilities", {"host": host, "severity": k}, v)
                       for k, v in sorted(totals.items())]
                out += [("security_image_vulnerabilities_fixable", {"host": host, "severity": k}, v)
                        for k, v in sorted(fixables.items())]
                out.append(("security_images_scanned", {"host": host}, scanned))
                out.append(("security_images_unscannable", {"host": host}, bad))
                out.append(("security_images_local_only", {"host": host}, local))
                return out + findings_samples(host, IMAGE_FINDINGS.get(host, {}), SCANNED.get(host, set()))
            guarded(f"images-{host}", _img, host=host)
        scan_all_images(("fastpi", "beefy", "tower"), running_images, _scan)

    return 0


if __name__ == "__main__":
    sys.exit(main())
