#!/usr/bin/env python3
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "specs.json"

HOSTS = [
    ("fastpi", None, "sbc", "edge, SSO, DNS, VPN"),
    ("beefy", "beefy-direct", "tower", "media server"),
    ("tower", "tower-direct", "nas", "NAS"),
]
FORBIDDEN_KEYS = ("serial", "mac", "ip", "bios")
TOWER_MIN_BYTES = 64 * 10**9

REMOTE = r"""
[ "$(id -u)" = 0 ] && S= || S="sudo -n"
echo '###osrel'; . /etc/os-release 2>/dev/null; echo "$PRETTY_NAME"
echo '###lscpu'; lscpu
echo '###free'; free -b
echo '###lsblk'; lsblk -d -b -o NAME,SIZE,MODEL,TRAN,ROTA -J
echo '###memory'; $S dmidecode -t memory 2>/dev/null || true
echo '###dmi'; { $S dmidecode -s baseboard-manufacturer; $S dmidecode -s baseboard-product-name; } 2>/dev/null || true
echo '###sysfs_vendor'; cat /sys/class/dmi/id/board_vendor 2>/dev/null
echo '###sysfs_name'; cat /sys/class/dmi/id/board_name 2>/dev/null
echo '###dt'; tr -d '\0' < /proc/device-tree/model 2>/dev/null; echo
echo '###gpu'; lspci 2>/dev/null | grep -i vga
echo '###speed'; i=$(ip route show default | awk '{print $5; exit}'); cat /sys/class/net/$i/speed 2>/dev/null
"""


def parse_lscpu(text):
    f = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        f[k.strip()] = v.strip()
    def num(key):
        v = f.get(key, "")
        return int(v) if v.isdigit() else 1

    per = "Core(s) per socket" if "Core(s) per socket" in f else "Core(s) per cluster"
    cores = num(per) * num("Socket(s)") * (num("Cluster(s)") if per.endswith("cluster") else 1)
    threads = cores * num("Thread(s) per core")
    mhz = f.get("CPU max MHz")
    return {
        "model": f.get("Model name", "Unknown CPU"),
        "cores": cores,
        "threads": threads,
        "max_ghz": round(float(mhz) / 1000, 1) if mhz else None,
    }


def parse_free_gb(text):
    for line in text.splitlines():
        if line.startswith("Mem:"):
            return round(int(line.split()[1]) / 1024**3)
    raise ValueError("no Mem line")


def total_ram_gb(modules, free_gb):
    return sum(m["size_gb"] for m in modules) or free_gb


def human_size(n):
    if n >= 10**12:
        t = round(n / 10**12, 1)
        return f"{t:g} TB"
    return f"{round(n / 10**9)} GB"


def parse_lsblk(text, min_bytes=0):
    disks = []
    for d in json.loads(text)["blockdevices"]:
        name = d["name"]
        size = int(d["size"])
        if name.startswith(("loop", "zram")) or size < min_bytes:
            continue
        rota = d.get("rota")
        spinning = rota in (True, 1, "1")
        if d.get("tran") == "nvme":
            kind = "nvme"
        elif d.get("tran") == "usb":
            kind = "usb-hdd"
        elif not spinning:
            kind = "ssd"
        else:
            kind = "hdd"
        disks.append({"model": (d.get("model") or "Unknown disk").strip(), "size": human_size(size), "kind": kind})
    return disks


def parse_dmidecode_memory(text):
    modules = []
    for block in text.split("Memory Device")[1:]:
        m = re.search(r"Size:\s*(\d+)\s*(MB|GB)", block)
        if not m:
            continue
        size = int(m.group(1)) // (1024 if m.group(2) == "MB" else 1)
        t = re.search(r"Type:\s*(\S+)", block)
        modules.append({"size_gb": size, "type": t.group(1) if t else "RAM"})
    return modules


def parse_board(dmi, sysfs_vendor, sysfs_name, dt_model):
    if dt_model and dt_model.strip("\x00 \n"):
        return dt_model.strip("\x00 \n")
    lines = [l.strip() for l in (dmi or "").splitlines() if l.strip()]
    if len(lines) >= 2:
        return " ".join(lines[:2])
    parts = [(sysfs_vendor or "").strip(), (sysfs_name or "").strip()]
    joined = " ".join(p for p in parts if p)
    return joined or "Unknown board"


def merge(previous, fresh):
    old = {m["name"]: m for m in previous.get("machines", [])}
    machines = []
    for name, _, _, _ in HOSTS:
        m = fresh.get(name) or old.get(name)
        if m:
            machines.append(m)
    return {"machines": machines}


def sections(text):
    out, key = {}, None
    for line in text.splitlines():
        if line.startswith("###"):
            key = line[3:]
            out[key] = []
        elif key:
            out[key].append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def build_machine(name, role, shape, text, today):
    s = sections(text)
    cpu = parse_lscpu(s["lscpu"])
    modules = parse_dmidecode_memory(s.get("memory", ""))
    ram_total = total_ram_gb(modules, parse_free_gb(s["free"]))
    gpu = re.sub(r"^\S+\s+VGA compatible controller:\s*", "", s.get("gpu", "").splitlines()[0]) if s.get("gpu") else None
    speed = s.get("speed", "").strip()
    network = f"{int(speed) // 1000 if int(speed) >= 1000 else int(speed)} {'Gbit/s' if int(speed) >= 1000 else 'Mbit/s'}" if speed.lstrip("-").isdigit() and int(speed) > 0 else None
    return {
        "name": name,
        "role": role,
        "shape": shape,
        "collected": today,
        "os": s.get("osrel", "").strip() or "Linux",
        "model": parse_board(s.get("dmi"), s.get("sysfs_vendor"), s.get("sysfs_name"), s.get("dt")),
        "cpu": cpu,
        "ram": {"total_gb": ram_total, "modules": modules},
        "graphics": gpu,
        "disks": parse_lsblk(s["lsblk"], TOWER_MIN_BYTES if shape == "nas" else 0),
        "network": network,
        "source": "live",
    }


def notes_tower(today):
    return {
        "name": "tower",
        "role": "NAS",
        "shape": "nas",
        "collected": today,
        "os": "Unraid OS",
        "model": "Celeron N5105 board",
        "cpu": {"model": "Intel Celeron N5105", "cores": 4, "threads": 4, "max_ghz": None},
        "ram": {"total_gb": 16, "modules": [{"size_gb": 8, "type": "DDR4"}, {"size_gb": 8, "type": "DDR4"}]},
        "graphics": None,
        "disks": [{"model": "WD Red 6 TB (SMR)", "size": "6 TB", "kind": "hdd"}],
        "network": None,
        "source": "notes",
    }


def run_host(alias):
    if alias is None:
        cmd = ["bash", "-s"]
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", alias, "bash -s"]
    try:
        r = subprocess.run(cmd, input=REMOTE, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 and "###lscpu" in r.stdout else None


def collect(today):
    fresh = {}
    for name, alias, shape, role in HOSTS:
        text = run_host(alias)
        try:
            fresh[name] = build_machine(name, role, shape, text, today) if text else None
        except (KeyError, ValueError):
            fresh[name] = None
    return fresh


def main():
    today = datetime.date.today().isoformat()
    previous = json.loads(OUT.read_text()) if OUT.exists() else {"machines": []}
    fresh = collect(today)
    have_tower = any(m["name"] == "tower" for m in previous["machines"])
    if fresh["tower"] is None and not have_tower:
        fresh["tower"] = notes_tower(today)
    result = merge(previous, fresh)
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    tmp.replace(OUT)
    for name, _, _, _ in HOSTS:
        m = next((m for m in result["machines"] if m["name"] == name), None)
        if fresh[name] is not None:
            print(f"{name}: {'notes (seeded)' if fresh[name]['source'] == 'notes' else 'live'}")
        elif m:
            print(f"{name}: kept previous (asleep)")
        else:
            print(f"{name}: no data")


if __name__ == "__main__":
    sys.exit(main())
