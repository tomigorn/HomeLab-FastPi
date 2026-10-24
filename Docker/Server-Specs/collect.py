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
echo '###lsblk'; lsblk -d -b -o NAME,SIZE,VENDOR,MODEL,TRAN,ROTA -J
echo '###memory'; $S dmidecode -t memory 2>/dev/null || true
echo '###pci'; $S lspci -vv 2>/dev/null | grep -E '^[0-9a-f]|LnkSta:' || true
echo '###dmi'; { $S dmidecode -s baseboard-manufacturer; $S dmidecode -s baseboard-product-name; } 2>/dev/null || true
echo '###sysfs_vendor'; cat /sys/class/dmi/id/board_vendor 2>/dev/null
echo '###sysfs_name'; cat /sys/class/dmi/id/board_name 2>/dev/null
echo '###dt'; tr -d '\0' < /proc/device-tree/model 2>/dev/null; echo
echo '###dtcompat'; tr '\0' '\n' < /proc/device-tree/compatible 2>/dev/null
i=$(ip route show default | awk '{print $5; exit}')
echo '###phy'; cat /sys/class/net/$i/phydev/phy_id 2>/dev/null
echo '###sata'; for d in /sys/block/sd*; do n=${d##*/}; a=$(readlink -f $d | grep -o 'ata[0-9]*' | head -1); [ -n "$a" ] && echo "$n $(cat /sys/class/ata_link/link${a#ata}/sata_spd 2>/dev/null)"; done
echo '###rpm'; if command -v smartctl >/dev/null; then for d in /sys/block/sd*; do n=${d##*/}; echo "$n $($S smartctl -i /dev/$n 2>/dev/null | grep -i 'Rotation Rate')"; done; fi
echo '###speed'; cat /sys/class/net/$i/speed 2>/dev/null
echo '###end'
exit 0
"""


CPU_MAKES = (("Intel", "Intel"), ("AMD", "AMD"), ("Apple", "Apple"))

SOC = {
    "brcm,bcm2712": {
        "cpu": ("Broadcom", "BCM2712 (Arm Cortex-A76)"),
        "ram": {"make": "Raspberry Pi (on-board)", "part": "LPDDR4X", "type": "LPDDR4X", "speed_mts": 4267},
    },
}

PHYS = {0x600D84A0: ("Broadcom", "BCM54213PE")}


def soc_from_compat(text):
    for line in (text or "").splitlines():
        if line.strip() in SOC:
            return SOC[line.strip()]
    return None


def phy_nic(phy_id):
    try:
        return PHYS.get(int((phy_id or "").strip(), 16) & 0xFFFFFFF0)
    except ValueError:
        return None


def split_cpu(model):
    base = re.search(r"@\s*([\d.]+)\s*GHz", model)
    s = re.sub(r"\((R|TM)\)", "", model)
    s = re.sub(r"@.*$", "", s)
    s = re.sub(r"\b\d+(st|nd|rd|th) Gen\b", "", s)
    s = re.sub(r"\b(\d+-Core Processor|Processor)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*\bCPU$", "", s)
    make = "unknown"
    for word, name in CPU_MAKES:
        if re.search(rf"\b{word}\b", s):
            make = name
            s = re.sub(rf"\b{word}\b", "", s, count=1).strip()
            break
    return make, s, float(base.group(1)) if base else None


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
    make, model, base = split_cpu(f.get("Model name", "Unknown CPU"))
    return {
        "make": make,
        "model": model,
        "cores": cores,
        "threads": threads,
        "base_ghz": base,
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


DISK_PREFIX = (
    (r"^ST\d", "Seagate"),
    (r"^(WDC\b|WD\d)", "Western Digital"),
    (r"^CT\d", "Crucial"),
)
DISK_WORDS = {"seagate": "Seagate", "samsung": "Samsung", "kingston": "Kingston", "toshiba": "Toshiba", "hgst": "HGST",
              "crucial": "Crucial", "intel": "Intel", "sandisk": "SanDisk", "western digital": "Western Digital"}
SEAGATE_FAMILY = {"NM": "Exos", "VN": "IronWolf", "DM": "BarraCuda"}
GENERIC_VENDORS = {"", "ata", "usb", "nvme"}


def split_disk(vendor, model):
    vendor = (vendor or "").strip()
    model = (model or "").strip()
    make = None
    for pat, name in DISK_PREFIX:
        if re.match(pat, model):
            make = name
            model = re.sub(r"^WDC\s+", "", model)
            break
    if make is None:
        for word, name in DISK_WORDS.items():
            if re.search(rf"\b{word}\b", f"{vendor} {model}", re.I):
                make = name
                model = re.sub(rf"\b{word}\b", "", model, count=1, flags=re.I)
                model = re.sub(r"\b(SSD|NVMe)\b|\b\d+(GB|TB)\b", "", model)
                model = re.sub(r"\s+", " ", model).strip()
                break
    if make is None:
        return ("unknown" if vendor.lower() in GENERIC_VENDORS else vendor), model
    if re.search(r"\d", model):
        model = re.sub(r"-[A-Z0-9]+$", "", model)
    if make == "Seagate":
        fam = re.match(r"^ST\d+([A-Z]{2})", model)
        if fam and fam.group(1) in SEAGATE_FAMILY:
            model = f"{SEAGATE_FAMILY[fam.group(1)]} {model}"
    return make, model


def sata_label(spd):
    m = re.match(r"\s*([\d.]+)\s*Gbps", spd or "")
    return f"SATA {float(m.group(1)):g} Gb/s" if m else None


def parse_sata_links(text):
    out = {}
    for line in (text or "").splitlines():
        name, _, spd = line.strip().partition(" ")
        label = sata_label(spd)
        if label:
            out[name] = label
    return out


def parse_rpm(text):
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"(\S+)\s+Rotation Rate:\s*(\d+)\s*rpm", line.strip(), re.I)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


GEN = {2.5: 1, 5: 2, 8: 3, 16: 4, 32: 5}


def parse_pcie_link(text, cls):
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if re.match(r"[0-9a-f]", line) and cls in line:
            for nxt in lines[i + 1:]:
                if re.match(r"[0-9a-f]", nxt):
                    break
                m = re.search(r"LnkSta:\s*Speed ([\d.]+)GT/s.*?Width x(\d+)", nxt)
                if m and float(m.group(1)) in GEN:
                    return f"PCIe Gen {GEN[float(m.group(1))]} ×{m.group(2)}"
    return None


def pci_desc(text, cls):
    for line in (text or "").splitlines():
        if re.match(r"[0-9a-f]", line) and f"{cls}:" in line:
            return re.sub(r"\s*\(rev [^)]*\)|\s*\(prog-if[^)]*\)", "", line.split(f"{cls}:", 1)[1]).strip()
    return None


PCI_VENDORS = {"intel": "Intel", "realtek": "Realtek", "broadcom": "Broadcom", "qualcomm": "Qualcomm", "marvell": "Marvell",
               "aquantia": "Aquantia", "mellanox": "Mellanox", "amd": "AMD", "advanced micro devices": "AMD", "nvidia": "NVIDIA"}


def split_pci(desc):
    for word, name in PCI_VENDORS.items():
        if desc.lower().startswith(word):
            return name, desc[len(word):].strip()
    return "unknown", desc


def parse_nic(text):
    desc = pci_desc(text, "Ethernet controller")
    if not desc:
        return None
    make, rest = split_pci(desc)
    rest = re.sub(r"^(Semiconductor Co\.?,? Ltd\.?|Corporation|Inc\.?|and subsidiaries)\s*", "", rest).strip()
    m = re.search(r"\b[A-Z]{1,4}\d[\w/\-]*", rest)
    return make, (m.group(0) if m else rest)


def parse_gpu(text):
    for cls in ("VGA compatible controller", "3D controller", "Display controller"):
        desc = pci_desc(text, cls)
        if desc:
            make, rest = split_pci(desc)
            m = re.search(r"\[(.+?)\]", rest)
            model = m.group(1) if m else re.sub(r"^(Corporation|Inc\.?)\s*", "", rest).strip()
            return {"make": make, "model": model}
    return None


def parse_lsblk(text, min_bytes=0, links=None, rpms=None):
    links, rpms = links or {}, rpms or {}
    disks = []
    for d in json.loads(text)["blockdevices"]:
        name = d["name"]
        size = int(d["size"])
        if name.startswith(("loop", "zram", "mmcblk")) or size < min_bytes:
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
        make, model = split_disk(d.get("vendor"), (d.get("model") or "Unknown disk").strip())
        disks.append({"make": make, "model": model, "size": human_size(size), "kind": kind,
                      "link": links.get(name) or links.get(kind), "rpm": rpms.get(name)})
    return disks


def clean_make(value):
    v = (value or "").strip()
    while True:
        n = re.sub(r"[\s,]+(Technology|Corporation|Corp\.?|Inc\.?|Co\.?|Ltd\.?)\s*$", "", v, flags=re.I).strip(" ,.")
        if n == v:
            break
        v = n
    if re.fullmatch(r"[0-9A-Fa-f]{4}([0-9A-Fa-f]{4,})?", v):
        return JEDEC.get(v[:4].upper(), "unknown")
    if v.lower() in MEM_PLACEHOLDERS:
        return "unknown"
    return v


JEDEC = {"029E": "Corsair", "802C": "Micron", "80AD": "SK hynix", "80CE": "Samsung", "859B": "Crucial", "04CD": "G.Skill", "9801": "Kingston", "0198": "Kingston"}

MEM_PLACEHOLDERS = {"", "not specified", "unknown", "[empty]", "undefined", "none", "to be filled by o.e.m."}


def parse_dmidecode_memory(text):
    modules = []
    parts = re.split(r"Handle [^\n]*DMI type (\d+)[^\n]*\n", text)
    for kind, block in zip(parts[1::2], parts[2::2]):
        if kind != "17":
            continue
        m = re.search(r"Size:\s*(\d+)\s*(MB|GB)", block)
        if not m:
            continue
        size = int(m.group(1)) // (1024 if m.group(2) == "MB" else 1)
        t = re.search(r"Type:\s*(\S+)", block)
        sp = re.search(r"Configured (?:Memory|Clock) Speed:\s*(\d+)", block) or re.search(r"\bSpeed:\s*(\d+)", block)
        mk = re.search(r"Manufacturer:\s*(.*)", block)
        pn = re.search(r"Part Number:\s*(.*)", block)
        part = pn.group(1).strip().split(".")[0] if pn else ""
        modules.append({
            "make": clean_make(mk.group(1) if mk else ""),
            "part": "" if part.lower() in MEM_PLACEHOLDERS else part,
            "size_gb": size,
            "type": t.group(1) if t else "RAM",
            "speed_mts": int(sp.group(1)) if sp else None,
        })
    return modules


PLACEHOLDERS = {"to be filled by o.e.m.", "default string", "not applicable", "system product name", "system manufacturer", "none", "unknown"}


def clean_dmi(value):
    v = (value or "").strip()
    return "" if v.lower() in PLACEHOLDERS else v


def parse_board(dmi, sysfs_vendor, sysfs_name, dt_model):
    dt = (dt_model or "").strip("\x00 \n")
    if dt:
        dt = re.sub(r"\s+Rev\s+[\d.]+$", "", dt)
        if dt.startswith("Raspberry Pi "):
            return {"make": "Raspberry Pi", "model": dt[len("Raspberry Pi "):]}
        return {"make": "unknown", "model": dt}
    lines = [l.strip() for l in (dmi or "").splitlines() if l.strip()]
    if len(lines) >= 2 and all(clean_dmi(l) for l in lines[:2]):
        return {"make": clean_make(lines[0]), "model": lines[1]}
    return {"make": clean_make(clean_dmi(sysfs_vendor)) or "unknown", "model": clean_dmi(sysfs_name)}


def fmt_speed(s):
    if not s or not s.strip().isdigit() or int(s) <= 0:
        return None
    n = int(s)
    return f"{n / 1000:g} Gbit/s" if n >= 1000 else f"{n} Mbit/s"


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
    if not all(k in s for k in ("lscpu", "free", "lsblk", "end")):
        return None
    cpu = parse_lscpu(s["lscpu"])
    soc = soc_from_compat(s.get("dtcompat"))
    if soc:
        cpu["make"], cpu["model"] = soc["cpu"]
    modules = parse_dmidecode_memory(s.get("memory", ""))
    free_gb = parse_free_gb(s["free"])
    ram_total = total_ram_gb(modules, free_gb)
    if not modules and soc:
        modules = [{**soc["ram"], "size_gb": ram_total}]
    pci = s.get("pci", "")
    links = parse_sata_links(s.get("sata"))
    nvme_link = parse_pcie_link(pci, "Non-Volatile memory controller")
    if nvme_link:
        links["nvme"] = nvme_link
    nic = phy_nic(s.get("phy")) or parse_nic(pci)
    return {
        "name": name,
        "role": role,
        "shape": shape,
        "collected": today,
        "os": s.get("osrel", "").strip() or "Linux",
        "board": parse_board(s.get("dmi"), s.get("sysfs_vendor"), s.get("sysfs_name"), s.get("dt")),
        "cpu": cpu,
        "ram": {"total_gb": ram_total, "modules": modules},
        "graphics": parse_gpu(pci),
        "disks": parse_lsblk(s["lsblk"], TOWER_MIN_BYTES if shape == "nas" else 0, links, parse_rpm(s.get("rpm"))),
        "network": {"make": nic[0] if nic else "unknown", "model": nic[1] if nic else "", "speed": fmt_speed(s.get("speed", "").strip())},
        "source": "live",
    }


def notes_tower(today):
    ram = {"make": "Crucial", "part": "CT8G4SFS832A", "size_gb": 8, "type": "DDR4", "speed_mts": 3200}
    return {
        "name": "tower",
        "role": "NAS",
        "shape": "nas",
        "collected": today,
        "os": "Unraid OS",
        "board": {"make": "unknown", "model": "(Celeron N5105 board)"},
        "cpu": {"make": "Intel", "model": "Celeron N5105", "cores": 4, "threads": 4, "base_ghz": 2.0, "max_ghz": 2.9},
        "ram": {"total_gb": 16, "modules": [dict(ram), dict(ram)]},
        "graphics": None,
        "disks": [{"make": "Western Digital", "model": "Red WD60EFAX (SMR)", "size": "6 TB", "kind": "hdd", "link": None, "rpm": 5400}],
        "network": {"make": "unknown", "model": "", "speed": None},
        "source": "notes",
    }


def needs_notes(previous, fresh_tower):
    if fresh_tower is not None:
        return False
    old = next((m for m in previous["machines"] if m["name"] == "tower"), None)
    return old is None or old.get("source") == "notes"


def run_host(alias):
    if alias is None:
        cmd = ["bash", "-s"]
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", alias, "bash -s"]
    try:
        r = subprocess.run(cmd, input=REMOTE, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def load_previous(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {"machines": []}
    except (ValueError, OSError):
        print(f"warning: {path.name} unreadable, starting empty", file=sys.stderr)
        return {"machines": []}


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
    previous = load_previous(OUT)
    fresh = collect(today)
    if needs_notes(previous, fresh["tower"]):
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
