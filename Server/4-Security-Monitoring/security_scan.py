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

import json
import os
import re
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


def ssh(host: str, cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new", host, cmd,
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


def running_images(host: str) -> list[str]:
    cmd = "docker ps --format '{{.Image}}'"
    r = run(["docker", "ps", "--format", "{{.Image}}"], timeout=120) if host == "fastpi" else ssh(host, cmd)
    if r.returncode != 0:
        raise RuntimeError(f"docker ps on {host}: {r.stderr.strip()[:200]}")
    seen, out = set(), []
    for line in r.stdout.split():
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


# Per-host Trivy wiring. Each host already runs a strictly read-only Docker
# socket proxy (POST=0) for Cup and telegraf, and Trivy needs exactly what those
# allow: GET /images/{name}/json and GET /images/{name}/get. Reusing it means no
# new socket consumer - the socket-hardening work cut that list down to Portainer
# on purpose, and a `:ro` socket mount would not have helped anyway, since it
# protects the socket FILE and not the root-equivalent API behind it.
TRIVY_HOSTS = {
    "fastpi": {
        "network": "socket_proxy",
        "docker_host": "tcp://socket-proxy-ro:2375",
        "cache": "/var/lib/security-scan/trivy-cache",
    },
    "beefy": {
        "network": "cup_socket",
        "docker_host": "tcp://cup-socket-proxy-ro:2375",
        "cache": "$HOME/.cache/trivy",   # no sudoers entry needed on beefy
    },
}


def _trivy_cmd(host: str, args: list[str], *, attach_proxy: bool) -> list[str] | str:
    """Build a Trivy invocation, local (list) or remote (shell string)."""
    cfg = TRIVY_HOSTS[host]
    net = ["--network", cfg["network"], "-e", f"DOCKER_HOST={cfg['docker_host']}"] if attach_proxy else []
    if host == "fastpi":
        return ["docker", "run", "--rm", *net,
                "-v", f"{cfg['cache']}:/root/.cache/trivy",
                "aquasec/trivy:latest", *args]
    return ("mkdir -p ~/.cache/trivy && docker run --rm " + " ".join(net) +
            f' -v "{cfg["cache"]}":/root/.cache/trivy aquasec/trivy:latest ' + " ".join(args))


def _trivy_run(host: str, args: list[str], *, attach_proxy: bool, timeout: int):
    cmd = _trivy_cmd(host, args, attach_proxy=attach_proxy)
    return run(cmd, timeout=timeout) if host == "fastpi" else ssh(host, cmd, timeout=timeout)


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


def collect_images(host: str) -> tuple[dict[str, int], int, int]:
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
    scanned = unscannable = 0
    # Per-image detail goes to a file rather than into labels. 60+ images times
    # five severities is cardinality Prometheus does not need to carry for a
    # figure that is read once a week, and an aggregate alert that cannot say
    # WHICH image is just a number to feel bad about.
    detail: list[tuple[int, int, str]] = []
    download_trivy_db(host)
    for image in running_images(host):
        r = _trivy_run(host, [
            "image", "--image-src", "docker", "--scanners", "vuln",
            "--skip-db-update", "--skip-java-db-update",
            "--quiet", "--format", "json",
            "--timeout", "10m", image,
        ], attach_proxy=True, timeout=1200)
        if r.returncode != 0 or not r.stdout.strip():
            unscannable += 1
            print(f"  unscannable on {host}: {image} ({r.stderr.strip()[-160:]})", file=sys.stderr)
            continue
        try:
            counts = parse_trivy(json.loads(r.stdout))
        except json.JSONDecodeError:
            unscannable += 1
            print(f"  unparseable on {host}: {image}", file=sys.stderr)
            continue
        scanned += 1
        detail.append((counts.get("CRITICAL", 0), counts.get("HIGH", 0), image))
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v

    detail.sort(reverse=True)
    report = [f"# Trivy CVE counts for images in use on {host}, worst first.",
              "# critical  high  image", ""]
    report += [f"{c:>8}  {h:>4}  {img}" for c, h, img in detail]
    if unscannable:
        report += ["", f"# {unscannable} image(s) could not be scanned - see journalctl -u security-image-scan"]
    (STATE / f"image-cves-{host}.txt").write_text("\n".join(report) + "\n")
    return totals, scanned, unscannable


HELPS = {
    "security_repo_leaks": "Secrets found by gitleaks in a repository's PUBLISHED history, by rule.",
    "security_repo_leaks_total": "Total secrets found by gitleaks in a repository's published history.",
    "security_scan_last_success_timestamp_seconds": "Unix time of the last successful collection of this subject.",
    "security_scan_errors": "1 if the last collection of this subject failed for a reason other than the host being asleep.",
    "security_scan_host_unreachable": "1 if the host could not be reached (expected for beefy, which powers off when idle).",
    "security_secret_files": "Secret-bearing files in the working tree, by verdict.",
    "security_pending_updates": "Pending OS package updates.",
    "security_image_vulnerabilities": "Trivy CVE count across images in use, by severity.",
    "security_images_scanned": "Images successfully scanned by Trivy.",
    "security_images_unscannable": "Images Trivy could not scan, for any reason.",
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

    if want("images"):
        for host in ("fastpi", "beefy"):
            def _img(host=host):
                totals, scanned, bad = collect_images(host)
                out = [("security_image_vulnerabilities", {"host": host, "severity": k}, v)
                       for k, v in sorted(totals.items())]
                out.append(("security_images_scanned", {"host": host}, scanned))
                out.append(("security_images_unscannable", {"host": host}, bad))
                return out
            guarded(f"images-{host}", _img, host=host)

    return 0


if __name__ == "__main__":
    sys.exit(main())
