#!/usr/bin/env python3
"""Generates the notes page homelab-architecture.md: every container of fastpi, beefy and tower in one table per host.
Sources: docker inspect, Traefik dynamic config, auto-update.conf, backup.sh --list. Only names, ports and hosts reach the page, never env values.
beefy is read over `ssh beefy-direct` (never wakes it); when it sleeps the cached section is kept with its time. tower is never contacted: Waker /status plus the flash backup.
Usage: arch_page.py [--out FILE] [--print]   Tests: python3 test_arch_page.py"""
import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCKER = REPO / "Docker"
OUT = Path("/home/pi/notes/docs/homelab-architecture.md")
CACHE = Path("/home/pi/.cache/arch-page/beefy.json")
TOWER_STACKS = Path("/home/pi/backups/tower-flash/latest/scripts/stacks")
TOWER_STATUS = "http://192.168.1.2:9002/status"
HOST_IPS = {"192.168.1.2": "fastpi", "192.168.1.102": "beefy", "192.168.1.101": "tower"}
SSO_ENV = re.compile(r"OIDC|OAUTH|AUTHENTIK", re.I)
IGNORED_MOUNTS = ("/var/run/docker.sock", "/run/docker.sock", "/etc/localtime", "/etc/timezone", "/proc", "/sys", "/dev", "/run", "/var/run")


# ---------- docker inspect ----------

def parse_inspect(items):
    rows = []
    for d in items:
        cfg, hc, ns = d.get("Config") or {}, d.get("HostConfig") or {}, d.get("NetworkSettings") or {}
        labels = cfg.get("Labels") or {}
        image = cfg.get("Image", "")
        version = labels.get("org.opencontainers.image.version", "")
        mode = hc.get("NetworkMode", "")
        nets = []
        for name, n in sorted((ns.get("Networks") or {}).items()):
            ipam = (n.get("IPAMConfig") or {}).get("IPv4Address")
            nets.append({"name": name, "ip": n.get("IPAddress", ""), "pinned": bool(ipam)})
        ports = sorted({f"{b['HostPort']}/{p.split('/')[1]}" for p, bs in (ns.get("Ports") or {}).items() for b in (bs or []) if b.get("HostPort")},
                       key=lambda s: (int(s.split("/")[0]), s))
        mounts = [{"type": m.get("Type"), "src": m.get("Source", ""), "name": m.get("Name", ""), "rw": m.get("RW", True)} for m in d.get("Mounts") or []]
        wd = labels.get("com.docker.compose.project.working_dir", "")
        rows.append({
            "name": d.get("Name", "").lstrip("/"),
            "project": project_of(wd, labels.get("com.docker.compose.project", "")),
            "image": image, "version": version,
            "state": (d.get("State") or {}).get("Status", ""),
            "nets": nets, "host_net": mode == "host", "ports": ports,
            "aliases": sorted({a for n in (ns.get("Networks") or {}).values() for a in (n.get("Aliases") or [])}),
            "healthcheck": bool(cfg.get("Healthcheck")) and (cfg["Healthcheck"].get("Test") or ["NONE"])[0] != "NONE",
            "oidc_env": any(SSO_ENV.search(e.split("=", 1)[0]) for e in cfg.get("Env") or []),
            "mounts": mounts, "id": d.get("Id", ""), "netmode": mode,
        })
    ids = {r["id"]: r["name"] for r in rows if r["id"]}
    for r in rows:
        if r["netmode"].startswith("container:"):
            r["shares_net"] = ids.get(r["netmode"][10:], r["netmode"][10:22])
    for r in rows:
        r.pop("id")
    return sorted(rows, key=lambda r: (r["project"].lower(), r["name"].lower()))


def project_of(working_dir, compose_project):
    m = re.search(r"/Docker/(.+)$", working_dir)
    return m.group(1) if m else (compose_project or "-")


# ---------- Traefik ----------

def _scalar(s):
    s = s.strip()
    if s[:1] in "\"'" and s[-1:] == s[:1]:
        s = s[1:-1]
    return s


def parse_traefik_file(text):
    """Line-based reader for the router/service shape used in Docker/Traefik/traefik/dynamic. Returns (routers, services)."""
    routers, services = {}, {}
    section = cur = key = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        ind = len(raw) - len(raw.lstrip())
        s = raw.strip()
        if ind == 2 and s.endswith(":"):
            section = s[:-1]
            cur = key = None
            continue
        if section not in ("routers", "services"):
            continue
        if ind == 4 and s.endswith(":"):
            cur = s[:-1]
            (routers if section == "routers" else services).setdefault(cur, {"mw": [], "urls": [], "rule": ""})
            key = None
            continue
        if cur is None:
            continue
        ent = (routers if section == "routers" else services)[cur]
        if ind == 6 and ":" in s and not s.startswith("-"):
            k, _, v = s.partition(":")
            key, v = k.strip(), v.strip()
            if key == "rule":
                if v in (">-", ">", "|", "|-"):
                    parts = []
                    while i < len(lines) and (len(lines[i]) - len(lines[i].lstrip()) > 6 or not lines[i].strip()):
                        parts.append(lines[i].strip())
                        i += 1
                    v = " ".join(p for p in parts if p)
                ent["rule"] = _scalar(v)
            elif key == "service":
                ent["service"] = _scalar(v)
            elif key == "middlewares" and v.startswith("["):
                ent["mw"] += [_scalar(x) for x in v.strip("[]").split(",") if x.strip()]
        elif s.startswith("- ") and key == "middlewares":
            ent["mw"].append(_scalar(s[2:]))
        elif "url:" in s and section == "services":
            ent["urls"].append(_scalar(s.split("url:", 1)[1]))
    return routers, services


def parse_traefik_dir(path):
    routers, services = {}, {}
    for f in sorted(Path(path).glob("*.yml")):
        r, s = parse_traefik_file(f.read_text())
        routers.update(r)
        services.update(s)
    return routers, services


def route_table(routers, services):
    """upstream (host, port) -> list of {host, sso, lan} from every router with a Host() rule."""
    out = {}
    for r in routers.values():
        hosts = re.findall(r"Host\(`([^`]+)`\)", r["rule"])
        if not hosts or "PathPrefix(`/outpost" in r["rule"] or r.get("service", "").endswith("@file"):
            continue
        svc = services.get(r.get("service", ""))
        if not svc:
            continue
        mws = r["mw"]
        sso = any(m in ("authentik@file", "authentik-basic@file") for m in mws)
        lan = "local-networks@file" in mws
        for u in svc["urls"]:
            m = re.match(r"https?://([^:/]+)(?::(\d+))?", u)
            if m:
                for h in hosts:
                    out.setdefault((m.group(1), m.group(2) or "80"), []).append({"host": h, "sso": sso, "lan": lan})
    return out


def routes_for(row, table, host_ip=None):
    names = {row["name"].lower(), *(a.lower() for a in row["aliases"])}
    ips = {n["ip"] for n in row["nets"] if n["ip"]}
    found = []
    for (h, port), rs in table.items():
        hit = h.lower() in names or h in ips
        if not hit and host_ip and h == host_ip:
            hit = any(p.split("/")[0] == port for p in row["ports"])
        if hit:
            found += rs
    seen, out = set(), []
    for r in found:
        if r["host"] not in seen:
            seen.add(r["host"])
            out.append(r)
    return out


def sso_label(routes, oidc_env, project=""):
    if project == "Authentik":
        return "IdP"
    if any(r["sso"] for r in routes):
        return "forward-auth"
    if oidc_env:
        return "own OIDC"
    if routes and all(r["lan"] for r in routes):
        return "no forward-auth (LAN/VPN only)"
    return "no forward-auth" if routes else "-"


# ---------- update tier, backup ----------

def parse_update_conf(text):
    tiers = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        p = line.split()
        if len(p) >= 2:
            tiers[p[1].lower()] = p[0]
    return tiers


def tier_for(project, tiers):
    p = project.lower()
    return tiers.get(p) or tiers.get(p.split("/")[0]) or "manual"


def parse_backup_list(text):
    paths, excludes = [], []
    for line in text.splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "path":
            paths.append(rest.strip())
        elif kind == "exclude":
            excludes.append(rest.strip())
    return {"paths": paths, "excludes": excludes}


def _under(p, root):
    return p == root or p.startswith(root.rstrip("/") + "/")


def backup_state(row, bk, dumped=()):
    if row["name"] in dumped:
        return "yes (dump)"
    if bk is None:
        return "unknown"
    data = [m for m in row["mounts"] if m["rw"] and m["src"] and not any(_under(m["src"], i) for i in IGNORED_MOUNTS)]
    if not data:
        return "- (no data mount)"
    ok = 0
    for m in data:
        src = m["src"]
        if any(fnmatch.fnmatch(src, e) or _under(src, e) for e in bk["excludes"]):
            continue
        if any(_under(src, p) for p in bk["paths"]):
            ok += 1
    if ok == len(data):
        return "yes"
    return "no" if ok == 0 else f"partial ({ok}/{len(data)})"


def dumped_containers(backup_sh_text):
    return set(re.findall(r"docker exec (\S+) sh -c '[^']*pg_dump", backup_sh_text))


# ---------- rendering ----------

def flags(row):
    f = []
    if not row["host_net"] and any(not n["pinned"] for n in row["nets"]):
        f.append("!ip")
    if not row["healthcheck"] and row["state"] == "running":
        f.append("!hc")
    return " ".join(f)


def _tag(row):
    img = row["image"].split("@")[0]
    ver = row["version"]
    if ver and ver not in img:
        return f"{img} ({ver})"
    return img


def row_cells(row, table, tiers, bk, dumped=(), host_ip=None):
    routes = routes_for(row, table, host_ip)
    hosts = ", ".join(r["host"] + (" (LAN)" if r["lan"] else "") for r in routes) or "-"
    nets = "host" if row["host_net"] else f"shares netns of {row['shares_net']}" if row.get("shares_net") else "<br>".join(f"{n['name']} {n['ip']}" + ("" if n["pinned"] else " (dyn)") for n in row["nets"]) or "-"
    return [row["project"], row["name"] + ("" if row["state"] == "running" else f" ({row['state']})"), _tag(row), nets,
            ", ".join(row["ports"]) or "-", hosts, sso_label(routes, row["oidc_env"], row["project"]), backup_state(row, bk, dumped),
            tier_for(row["project"], tiers), flags(row)]


HEAD = ["Project", "Container", "Image:tag (version)", "Networks + IP", "Published ports", "Hostname(s)", "SSO", "Backed up", "Update tier", "Flags"]


def md_table(head, rows):
    esc = lambda c: str(c).replace("|", "\\|")
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows])


def host_section(title, intro, rows_cells):
    flagged = sum(1 for r in rows_cells if r[-1])
    return f"## {title}\n\n{intro} {len(rows_cells)} containers, {flagged} flagged.\n\n" + md_table(HEAD, rows_cells) + "\n"


def render(now, fastpi, beefy, tower):
    """fastpi/beefy/tower: dict(intro, cells) or None."""
    parts = [f"# Homelab architecture\n\nGenerated {now:%Y-%m-%d %H:%M} by `Docker/_global/scripts/arch_page.py` (timer `arch-page`), do not edit. "
             + "; ".join(f"{k} {len(v['cells'])} containers" for k, v in (("fastpi", fastpi), ("beefy", beefy), ("tower", tower)) if v) + ".\n"
             "\nFlags (facts from docker inspect, not a policy check): `!ip` a network IP is not pinned (`(dyn)`), `!hc` running without a healthcheck. "
             "Backed up: `yes` every data mount is in the restic paths, `partial`, `no`, `yes (dump)` pg_dump, `-` nothing to back up. "
             "Update tier: `Docker/_global/auto-update.conf` (`manual` = not listed). "
             "SSO comes from the Traefik middlewares and env var names only: `no forward-auth` also covers apps with their login set up inside (Jellyfin, Nextcloud, Audiobookshelf). "
             "Tower flags come from its stack scripts (`!hc` = no `--health-cmd`).\n"]
    for title, h in (("fastpi", fastpi), ("beefy", beefy), ("tower", tower)):
        if h and h["cells"]:
            parts.append(host_section(title, h["intro"], h["cells"]))
        else:
            parts.append(f"## {title}\n\n{h['intro'] if h else 'No data.'}\n")
    return "\n".join(parts)


# ---------- tower (flash backup only) ----------

def parse_tower_stack(text, stack):
    vars_ = dict(re.findall(r'^([A-Za-z_]\w*)="([^"$]*)"', text, re.M))
    sub = lambda s: re.sub(r"\$\{(\w+)(?::-[^}]*)?\}|\$(\w+)", lambda m: vars_.get(m.group(1) or m.group(2), ""), s)
    blocks = re.findall(r"^docker run\b((?:[^\n]*\\\n)*[^\n]*)", text, re.M)
    out = []
    for b in blocks:
        b = b.replace("\\\n", " ")
        name = re.search(r"--name\s+(\S+)", b)
        if not name:
            continue
        image = next((vars_.get(m) for m in re.findall(r'"\$\{?(\w*IMAGE\w*)\}?"', b) if vars_.get(m)), "")
        net = re.search(r'--network\s+"?\$?\{?([\w-]+)', b)
        ports = [sub(p).split(":")[-2] + "/tcp" for p in re.findall(r'-p\s+"?([^\s"]+)"?', b) if len(sub(p).split(":")) >= 2]
        vols = re.findall(r'-v\s+"?([^\s"]+)"?', b)
        out.append({"name": name.group(1), "project": stack, "image": image, "net": vars_.get(net.group(1), net.group(1)) if net else "bridge",
                    "ports": ports, "healthcheck": "--health-cmd" in b, "vols": [sub(v).split(":")[0] for v in vols]})
    return out


def tower_cells(stacks_dir, tiers):
    cells = []
    for up in sorted(Path(stacks_dir).glob("*/up.sh")):
        for c in parse_tower_stack(up.read_text(errors="replace"), up.parent.name):
            cells.append([c["project"], c["name"], c["image"] or "-", f"{c['net']} (dyn)", ", ".join(c["ports"]) or "-", "-", "-",
                          "config only (flash backup)", "manual", "!ip" + ("" if c["healthcheck"] else " !hc")])
    return cells


def tower_hosts(table):
    out = {}
    for (h, port), rs in table.items():
        if h == "192.168.1.101":
            out[port] = rs
    return out


# ---------- collection ----------

def run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def docker_inspect():
    ids = run(["docker", "ps", "-aq"], 30).stdout.split()
    return json.loads(run(["docker", "inspect", *ids], 60).stdout)


BEEFY_REMOTE = ("echo '#UPTIME'; uptime -p; echo '#INSPECT'; sudo -n docker inspect $(sudo -n docker ps -aq); echo '#CONF'; "
                "cat ~/Projects/Docker/_global/auto-update.conf; echo '#BACKUP'; "
                "f=~/Projects/Server/10-Backup/beefy-backup.sh; [ -f $f ] && bash $f --list 2>/dev/null; echo '#DUMP'; [ -f $f ] && grep -h 'docker exec .*pg_dump' $f; true")


def split_remote(text):
    parts = re.split(r"^#(UPTIME|INSPECT|CONF|BACKUP|DUMP)\n", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def collect_beefy(now, runner=run, cache=CACHE):
    """Fresh data over ssh when beefy is awake, else the cached section. Returns (rows, uptime, tiers, bk, as_of, fresh)."""
    try:
        p = runner(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "beefy-direct", BEEFY_REMOTE], 90)
        if p.returncode == 0 and "#INSPECT" in p.stdout:
            sec = split_remote(p.stdout)
            rows = parse_inspect(json.loads(sec["INSPECT"]))
            bk = parse_backup_list(sec.get("BACKUP", ""))
            data = {"as_of": now.isoformat(timespec="minutes"), "uptime": sec.get("UPTIME", "").strip(), "rows": rows,
                    "tiers": parse_update_conf(sec.get("CONF", "")), "dumped": sorted(dumped_containers(sec.get("DUMP", ""))), "bk": bk if bk["paths"] else None}
            cache.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(cache.parent, 0o700)
            atomic_write(cache, json.dumps(data))
            return data, True
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        pass
    try:
        return json.loads(cache.read_text()), False
    except (OSError, ValueError):
        return None, False


def tower_status():
    try:
        with urllib.request.urlopen(TOWER_STATUS, timeout=5) as r:
            return "up" if json.load(r).get("up") else "asleep"
    except (OSError, ValueError):
        return "unknown"


def atomic_write(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--print", action="store_true", help="print the page instead of writing it")
    a = ap.parse_args(argv)
    now = dt.datetime.now()
    conf = (DOCKER / "_global/auto-update.conf").read_text()
    tiers = parse_update_conf(conf)
    routers, services = parse_traefik_dir(DOCKER / "Traefik/traefik/dynamic")
    table = route_table(routers, services)

    backup_sh = REPO / "Server/5-Backup/backup.sh"
    try:
        bk = parse_backup_list(run(["bash", str(backup_sh), "--list"], 30).stdout)
        bk = bk if bk["paths"] else None
    except (OSError, subprocess.TimeoutExpired):
        bk = None
    dumped = dumped_containers(backup_sh.read_text())

    rows = parse_inspect(docker_inspect())
    up = run(["uptime", "-p"], 5).stdout.strip()
    fastpi = {"intro": f"Live from docker inspect, {up}.", "cells": [row_cells(r, table, tiers, bk, dumped, "192.168.1.2") for r in rows]}

    bdata, fresh = collect_beefy(now)
    if bdata:
        when = "live, " + bdata["uptime"] if fresh else f"as of {bdata['as_of'].replace('T', ' ')} (beefy asleep, cached)"
        bbk = bdata.get("bk")
        beefy = {"intro": f"{when}.", "cells": [row_cells(r, table, bdata["tiers"], bbk, bdata.get("dumped", ()), "192.168.1.102") for r in bdata["rows"]]}
    else:
        beefy = {"intro": "No data yet: beefy was asleep and nothing is cached. The nightly run inside beefy's 03:58-04:45 window fills it.", "cells": []}

    state = tower_status()
    if TOWER_STACKS.is_dir():
        flash = TOWER_STACKS.parents[1].resolve().name
        cells = tower_cells(TOWER_STACKS, {})
        for c in cells:
            routes = [r for p in c[4].split(", ") for r in tower_hosts(table).get(p.split("/")[0], [])]
            c[5] = ", ".join(dict.fromkeys(r["host"] for r in routes)) or "-"
            c[6] = sso_label(routes, False)
        tower = {"intro": f"Never contacted: Waker status `{state}`, containers from the flash backup of {flash} (stack scripts, not live state).", "cells": cells}
    else:
        tower = {"intro": f"Waker status `{state}`; no flash backup found.", "cells": []}

    page = render(now, fastpi, beefy, tower)
    if a.print:
        sys.stdout.write(page)
    else:
        atomic_write(a.out, page)
        print(f"wrote {a.out}: fastpi {len(fastpi['cells'])}, beefy {len(beefy['cells'])}, tower {len(tower['cells'])} containers")


if __name__ == "__main__":
    main()
