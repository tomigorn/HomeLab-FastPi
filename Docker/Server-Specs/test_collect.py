import json
import sys

from collect import (
    FORBIDDEN_KEYS,
    merge,
    parse_board,
    parse_dmidecode_memory,
    parse_free_gb,
    parse_lscpu,
    parse_lsblk,
    total_ram_gb,
)

LSCPU = """Architecture:                         x86_64
Model name:                           Example CPU 9000
Thread(s) per core:                   2
Core(s) per socket:                   6
Socket(s):                            1
CPU max MHz:                          2400.0000
"""

FREE = """               total        used        free      shared  buff/cache   available
Mem:     16664715264  2000000000  9000000000    10000000  5000000000 14000000000
Swap:     2147479552           0  2147479552
"""

LSBLK = json.dumps({"blockdevices": [
    {"name": "nvme0n1", "size": 512110190592, "model": "ACME NVMe 512", "tran": "nvme", "rota": False},
    {"name": "sda", "size": 8001563222016, "model": "ACME HDD 8TB", "tran": "sata", "rota": True},
    {"name": "sdb", "size": 1000204886016, "model": "ACME SSD 1TB", "tran": "sata", "rota": False},
    {"name": "sdc", "size": 4000787030016, "model": "ACME Ext 4TB", "tran": "usb", "rota": True},
    {"name": "loop0", "size": 100000000, "model": None, "tran": None, "rota": False},
    {"name": "zram0", "size": 2147483648, "model": None, "tran": None, "rota": False},
    {"name": "sdd", "size": 31914983424, "model": "ACME Flash", "tran": None, "rota": "0"},
]})

DMI_MEM = """Handle 0x0010, DMI type 17, 40 bytes
Memory Device
\tSize: 8 GB
\tType: DDR4

Handle 0x0011, DMI type 17, 40 bytes
Memory Device
\tSize: No Module Installed
\tType: Unknown

Handle 0x0012, DMI type 17, 40 bytes
Memory Device
\tSize: 8192 MB
\tType: DDR4
"""


def test_parse_lscpu():
    cpu = parse_lscpu(LSCPU)
    assert cpu == {"model": "Example CPU 9000", "cores": 6, "threads": 12, "max_ghz": 2.4}


def test_parse_lscpu_without_max_mhz():
    cpu = parse_lscpu("Model name: Cortex-X\nThread(s) per core: 1\nCore(s) per socket: 4\nSocket(s): 1\n")
    assert cpu["max_ghz"] is None and cpu["cores"] == 4 and cpu["threads"] == 4


def test_parse_lscpu_arm_dash_socket():
    cpu = parse_lscpu("Model name: Cortex-X\nThread(s) per core: 1\nCore(s) per socket: 4\nSocket(s): -\n")
    assert cpu["cores"] == 4


def test_parse_lscpu_arm_cluster_cores():
    cpu = parse_lscpu("Model name: Cortex-X\nThread(s) per core: 1\nCore(s) per cluster: 4\nSocket(s): -\nCluster(s): 1\n")
    assert cpu["cores"] == 4 and cpu["threads"] == 4


def test_parse_free_gb():
    assert parse_free_gb(FREE) == 16


def test_parse_lsblk_kinds_and_sizes():
    disks = parse_lsblk(LSBLK)
    assert disks == [
        {"model": "ACME NVMe 512", "size": "512 GB", "kind": "nvme"},
        {"model": "ACME HDD 8TB", "size": "8 TB", "kind": "hdd"},
        {"model": "ACME SSD 1TB", "size": "1 TB", "kind": "ssd"},
        {"model": "ACME Ext 4TB", "size": "4 TB", "kind": "usb-hdd"},
        {"model": "ACME Flash", "size": "32 GB", "kind": "ssd"},
    ]


def test_parse_lsblk_drops_small_flash_on_tower():
    disks = parse_lsblk(LSBLK, min_bytes=64 * 10**9)
    assert [d["model"] for d in disks] == ["ACME NVMe 512", "ACME HDD 8TB", "ACME SSD 1TB", "ACME Ext 4TB"]


def test_parse_dmidecode_memory_skips_empty_slots():
    assert parse_dmidecode_memory(DMI_MEM) == [
        {"size_gb": 8, "type": "DDR4"},
        {"size_gb": 8, "type": "DDR4"},
    ]


def test_total_ram_prefers_module_sum():
    assert total_ram_gb([{"size_gb": 32, "type": "DDR4"}, {"size_gb": 32, "type": "DDR4"}], 61) == 64
    assert total_ram_gb([], 8) == 8


def test_parse_board_from_dmidecode():
    assert parse_board("ACME\nBoard X1\n", None, None, None) == "ACME Board X1"


def test_parse_board_falls_back_to_sysfs():
    assert parse_board(None, "Vendor", "Name", None) == "Vendor Name"
    assert parse_board("", "Vendor", None, None) == "Vendor"


def test_parse_board_raspberry_pi_uses_device_tree():
    assert parse_board(None, None, None, "Example Pi 9 Model B Rev 1.0\x00") == "Example Pi 9 Model B Rev 1.0"


def test_parse_board_unknown():
    assert parse_board(None, None, None, None) == "Unknown board"


def machine(name, collected):
    return {"name": name, "collected": collected, "source": "live"}


def test_merge_keeps_previous_when_host_unreachable():
    previous = {"machines": [machine("fastpi", "2026-10-01"), machine("beefy", "2026-10-01")]}
    fresh = {"fastpi": machine("fastpi", "2026-10-24"), "beefy": None, "tower": None}
    out = merge(previous, fresh)
    assert [m["name"] for m in out["machines"]] == ["fastpi", "beefy"]
    assert out["machines"][0]["collected"] == "2026-10-24"
    assert out["machines"][1]["collected"] == "2026-10-01"


def test_merge_orders_hosts():
    previous = {"machines": [machine("tower", "2026-10-01")]}
    fresh = {"tower": None, "beefy": machine("beefy", "2026-10-24"), "fastpi": machine("fastpi", "2026-10-24")}
    assert [m["name"] for m in merge(previous, fresh)["machines"]] == ["fastpi", "beefy", "tower"]


def test_output_has_no_forbidden_keys():
    for key in ("serial", "mac", "ip", "bios"):
        assert key in FORBIDDEN_KEYS
    from collect import notes_tower
    text = json.dumps(notes_tower("2026-10-24")).lower()
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in text


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in fns:
        try:
            f()
        except Exception:  # noqa: BLE001
            bad += 1
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
