import json
import sys

from collect import (
    FORBIDDEN_KEYS,
    build_machine,
    fmt_speed,
    merge,
    needs_notes,
    parse_board,
    parse_dmidecode_memory,
    parse_free_gb,
    parse_lscpu,
    parse_lsblk,
    parse_nic,
    parse_pcie_link,
    parse_rpm,
    parse_sata_links,
    phy_nic,
    sata_label,
    soc_from_compat,
    split_disk,
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
\tSpeed: 3200 MT/s
\tManufacturer: Crucial Technology
\tPart Number: CT8G4SFS832A.M8FE
\tConfigured Memory Speed: 3200 MT/s

Handle 0x0011, DMI type 17, 40 bytes
Memory Device
\tSize: No Module Installed
\tType: Unknown

Handle 0x0012, DMI type 17, 40 bytes
Memory Device
\tSize: 8192 MB
\tType: DDR4
\tSpeed: 3200 MT/s
\tManufacturer: 802C0000802C
\tPart Number: Not Specified
\tConfigured Memory Speed: 2133 MT/s
"""


def test_parse_lscpu():
    cpu = parse_lscpu(LSCPU)
    assert cpu == {"make": "unknown", "model": "Example CPU 9000", "cores": 6, "threads": 12, "base_ghz": None, "max_ghz": 2.4}


def test_parse_lscpu_intel_make_model_base():
    cpu = parse_lscpu("Model name: 11th Gen Intel(R) Core(TM) i5-11400 @ 2.60GHz\nThread(s) per core: 2\nCore(s) per socket: 6\nSocket(s): 1\nCPU max MHz: 4400.0000\n")
    assert (cpu["make"], cpu["model"], cpu["base_ghz"], cpu["max_ghz"]) == ("Intel", "Core i5-11400", 2.6, 4.4)
    cpu = parse_lscpu("Model name: Intel(R) Celeron(R) N5105 @ 2.00GHz\nThread(s) per core: 1\nCore(s) per socket: 4\nSocket(s): 1\n")
    assert (cpu["make"], cpu["model"], cpu["base_ghz"]) == ("Intel", "Celeron N5105", 2.0)


def test_parse_lscpu_amd_make():
    cpu = parse_lscpu("Model name: AMD Ryzen 5 5600X 6-Core Processor\nThread(s) per core: 2\nCore(s) per socket: 6\nSocket(s): 1\n")
    assert cpu["make"] == "AMD" and cpu["model"].startswith("Ryzen 5 5600X")


def test_soc_from_compat():
    soc = soc_from_compat("raspberrypi,5-model-b\nbrcm,bcm2712\n")
    assert soc["cpu"] == ("Broadcom", "BCM2712 (Arm Cortex-A76)")
    assert soc["ram"] == {"make": "Raspberry Pi (on-board)", "part": "LPDDR4X", "type": "LPDDR4X", "speed_mts": 4267}
    assert soc_from_compat("acme,thing") is None
    assert soc_from_compat("") is None


def test_phy_nic_lookup():
    assert phy_nic("0x600d84a2") == ("Broadcom", "BCM54213PE")
    assert phy_nic("0x600d84a0") == ("Broadcom", "BCM54213PE")
    assert phy_nic("0x12345678") is None
    assert phy_nic("") is None


LSPCI = """00:02.0 VGA compatible controller: Intel Corporation RocketLake-S GT1 [UHD Graphics 730] (rev 04)
\t\tLnkSta:\tSpeed 2.5GT/s, Width x1
01:00.0 Non-Volatile memory controller: Samsung Electronics Co Ltd NVMe SSD Controller SM981/PM981/PM983 (prog-if 02 [NVM Express])
\t\tLnkSta:\tSpeed 8GT/s (ok), Width x4 (ok)
03:00.0 Ethernet controller: Realtek Semiconductor Co., Ltd. RTL8111/8168/8211/8411 PCI Express Gigabit Ethernet Controller (rev 15)
\t\tLnkSta:\tSpeed 2.5GT/s, Width x1
"""


def test_parse_pcie_link_maps_generation():
    assert parse_pcie_link(LSPCI, "Non-Volatile memory controller") == "PCIe Gen 3 ×4"
    assert parse_pcie_link(LSPCI.replace("8GT/s (ok), Width x4 (ok)", "5GT/s (downgraded), Width x1 (downgraded)"), "Non-Volatile memory controller") == "PCIe Gen 2 ×1"
    assert parse_pcie_link(LSPCI.replace("8GT/s (ok)", "16GT/s"), "Non-Volatile memory controller") == "PCIe Gen 4 ×4"
    assert parse_pcie_link(LSPCI, "SATA controller") is None
    assert parse_pcie_link("", "Non-Volatile memory controller") is None


def test_parse_nic_from_lspci():
    assert parse_nic(LSPCI) == ("Realtek", "RTL8111/8168/8211/8411")
    assert parse_nic("00:1f.6 Ethernet controller: Intel Corporation Ethernet Controller I225-V (rev 03)\n") == ("Intel", "I225-V")
    assert parse_nic("") is None


def test_sata_links_and_labels():
    assert parse_sata_links("sda 6.0 Gbps\nsdb 3.0 Gbps\nsdc\n") == {"sda": "SATA 6 Gb/s", "sdb": "SATA 3 Gb/s"}
    assert sata_label("1.5 Gbps") == "SATA 1.5 Gb/s"
    assert sata_label("") is None


def test_parse_rpm():
    assert parse_rpm("sda Rotation Rate:    7200 rpm\nsdb Rotation Rate:    Solid State Device\nsdc\n") == {"sda": 7200}


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
    assert [(d["make"], d["model"], d["size"], d["kind"]) for d in disks] == [
        ("unknown", "ACME NVMe 512", "512 GB", "nvme"),
        ("unknown", "ACME HDD 8TB", "8 TB", "hdd"),
        ("unknown", "ACME SSD 1TB", "1 TB", "ssd"),
        ("unknown", "ACME Ext 4TB", "4 TB", "usb-hdd"),
        ("unknown", "ACME Flash", "32 GB", "ssd"),
    ]


def test_parse_lsblk_adds_link_rpm_by_name_or_kind():
    disks = parse_lsblk(LSBLK, links={"sda": "SATA 6 Gb/s", "nvme": "PCIe Gen 3 ×4"}, rpms={"sda": 7200})
    assert disks[0]["link"] == "PCIe Gen 3 ×4" and disks[0]["rpm"] is None
    assert disks[1]["link"] == "SATA 6 Gb/s" and disks[1]["rpm"] == 7200
    assert disks[2]["link"] is None


def test_parse_lsblk_uses_vendor_column():
    text = json.dumps({"blockdevices": [{"name": "sda", "size": 2000398934016, "vendor": "Seagate ", "model": "Expansion", "tran": "usb", "rota": True}]})
    d = parse_lsblk(text)[0]
    assert (d["make"], d["model"]) == ("Seagate", "Expansion")


def test_split_disk_make_model():
    assert split_disk("", "Samsung SSD 870 QVO 8TB") == ("Samsung", "870 QVO")
    assert split_disk("", "ST30000NM004K-3RM133") == ("Seagate", "Exos ST30000NM004K")
    assert split_disk("", "PM961 NVMe SAMSUNG 512GB") == ("Samsung", "PM961")
    assert split_disk("Seagate", "Expansion") == ("Seagate", "Expansion")
    assert split_disk("ATA", "WDC WD60EFAX-68JH4N1") == ("Western Digital", "WD60EFAX")
    assert split_disk("", "CT500MX500SSD1") == ("Crucial", "CT500MX500SSD1")
    assert split_disk("", "KINGSTON SA400S37480G") == ("Kingston", "SA400S37480G")
    assert split_disk("", "ACME HDD 8TB") == ("unknown", "ACME HDD 8TB")


def test_parse_lsblk_drops_small_flash_on_tower():
    disks = parse_lsblk(LSBLK, min_bytes=64 * 10**9)
    assert [d["model"] for d in disks] == ["ACME NVMe 512", "ACME HDD 8TB", "ACME SSD 1TB", "ACME Ext 4TB"]


def test_parse_dmidecode_memory_skips_empty_slots():
    assert parse_dmidecode_memory(DMI_MEM) == [
        {"make": "Crucial", "part": "CT8G4SFS832A", "size_gb": 8, "type": "DDR4", "speed_mts": 3200},
        {"make": "Micron", "part": "", "size_gb": 8, "type": "DDR4", "speed_mts": 2133},
    ]


def test_dmidecode_jedec_manufacturer_ids():
    one = lambda mk: parse_dmidecode_memory(f"Handle 0x1, DMI type 17, 40 bytes\nMemory Device\n\tSize: 8 GB\n\tType: DDR4\n\tManufacturer: {mk}\n")[0]["make"]
    assert one("029E") == "Corsair"
    assert one("802C0000802C") == "Micron"
    assert one("FFFF") == "unknown"


def test_total_ram_prefers_module_sum():
    assert total_ram_gb([{"size_gb": 32}, {"size_gb": 32}], 61) == 64
    assert total_ram_gb([], 8) == 8


def test_parse_board_from_dmidecode():
    assert parse_board("ACME\nBoard X1\n", None, None, None) == {"make": "ACME", "model": "Board X1"}
    assert parse_board("Gigabyte Technology Co., Ltd.\nH510M H V2\n", None, None, None) == {"make": "Gigabyte", "model": "H510M H V2"}


def test_parse_board_falls_back_to_sysfs():
    assert parse_board(None, "Vendor", "Name", None) == {"make": "Vendor", "model": "Name"}
    assert parse_board("", "Vendor", None, None) == {"make": "Vendor", "model": ""}


def test_parse_board_raspberry_pi_uses_device_tree():
    assert parse_board(None, None, None, "Raspberry Pi 9 Model B Rev 1.0\x00") == {"make": "Raspberry Pi", "model": "9 Model B"}
    assert parse_board(None, None, None, "Example Pi 9 Model B Rev 1.0\x00") == {"make": "unknown", "model": "Example Pi 9 Model B"}


def test_parse_board_unknown():
    assert parse_board(None, None, None, None) == {"make": "unknown", "model": ""}


FIXTURE = """###osrel
Example OS 1.0
###lscpu
""" + LSCPU + """###free
""" + FREE + """###lsblk
""" + LSBLK + """
###memory
###pci
""" + LSPCI + """###dmi
###sysfs_vendor
Vendor
###sysfs_name
Name
###dt
###speed
###end
"""


def strip_sections(text, *names):
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith("###"):
            skip = line[3:] in names
        if not skip:
            out.append(line)
    return "\n".join(out) + "\n"


def test_build_machine_full_fixture():
    m = build_machine("beefy", "media server", "tower", FIXTURE, "2026-10-24")
    assert m == {
        "name": "beefy",
        "role": "media server",
        "shape": "tower",
        "collected": "2026-10-24",
        "os": "Example OS 1.0",
        "board": {"make": "Vendor", "model": "Name"},
        "cpu": {"make": "unknown", "model": "Example CPU 9000", "cores": 6, "threads": 12, "base_ghz": None, "max_ghz": 2.4},
        "ram": {"total_gb": 16, "modules": []},
        "graphics": {"make": "Intel", "model": "UHD Graphics 730"},
        "disks": [
            {"make": "unknown", "model": "ACME NVMe 512", "size": "512 GB", "kind": "nvme", "link": "PCIe Gen 3 ×4", "rpm": None},
            {"make": "unknown", "model": "ACME HDD 8TB", "size": "8 TB", "kind": "hdd", "link": None, "rpm": None},
            {"make": "unknown", "model": "ACME SSD 1TB", "size": "1 TB", "kind": "ssd", "link": None, "rpm": None},
            {"make": "unknown", "model": "ACME Ext 4TB", "size": "4 TB", "kind": "usb-hdd", "link": None, "rpm": None},
            {"make": "unknown", "model": "ACME Flash", "size": "32 GB", "kind": "ssd", "link": None, "rpm": None},
        ],
        "network": {"make": "Realtek", "model": "RTL8111/8168/8211/8411", "speed": None},
        "source": "live",
    }


def test_build_machine_raspberry_pi_soc_ram_and_phy():
    text = FIXTURE.replace("###dt\n", "###dt\nRaspberry Pi 5 Model B Rev 1.0\n").replace("###end", "###dtcompat\nraspberrypi,5-model-b\nbrcm,bcm2712\n###phy\n0x600d84a2\n###speed\n1000\n###end", 1)
    m = build_machine("fastpi", "x", "sbc", text, "2026-10-24")
    assert m["cpu"]["make"] == "Broadcom" and m["cpu"]["model"] == "BCM2712 (Arm Cortex-A76)" and m["cpu"]["max_ghz"] == 2.4
    assert m["ram"]["modules"] == [{"make": "Raspberry Pi (on-board)", "part": "LPDDR4X", "size_gb": 16, "type": "LPDDR4X", "speed_mts": 4267}]
    assert m["network"] == {"make": "Broadcom", "model": "BCM54213PE", "speed": "1 Gbit/s"}
    assert m["board"] == {"make": "Raspberry Pi", "model": "5 Model B"}


def test_notes_tower_make_model_speed():
    from collect import notes_tower
    t = notes_tower("2026-10-24")
    assert t["cpu"]["make"] == "Intel" and t["cpu"]["model"] == "Celeron N5105" and (t["cpu"]["base_ghz"], t["cpu"]["max_ghz"]) == (2.0, 2.9)
    assert t["ram"]["modules"] == [{"make": "Crucial", "part": "CT8G4SFS832A", "size_gb": 8, "type": "DDR4", "speed_mts": 3200}] * 2
    assert t["disks"][0]["make"] == "Western Digital" and "WD60EFAX" in t["disks"][0]["model"] and t["disks"][0]["rpm"] == 5400
    assert t["board"] == {"make": "unknown", "model": "(Celeron N5105 board)"}


def test_needs_notes_reseeds_old_notes_only():
    assert needs_notes({"machines": []}, None)
    assert needs_notes({"machines": [{"name": "tower", "source": "notes"}]}, None)
    assert not needs_notes({"machines": [{"name": "tower", "source": "live"}]}, None)
    assert not needs_notes({"machines": []}, {"name": "tower"})


def test_missing_speed_still_live_machine():
    m = build_machine("beefy", "x", "tower", strip_sections(FIXTURE, "speed"), "2026-10-24")
    assert m is not None and m["network"]["speed"] is None


def test_partial_output_gives_none():
    assert build_machine("beefy", "x", "tower", strip_sections(FIXTURE, "lsblk"), "d") is None
    assert build_machine("beefy", "x", "tower", strip_sections(FIXTURE, "end"), "d") is None
    assert build_machine("beefy", "x", "tower", "", "d") is None


def test_fmt_speed():
    assert fmt_speed("2500") == "2.5 Gbit/s"
    assert fmt_speed("1000") == "1 Gbit/s"
    assert fmt_speed("10000") == "10 Gbit/s"
    assert fmt_speed("100") == "100 Mbit/s"
    assert fmt_speed("-1") is None
    assert fmt_speed("") is None
    assert fmt_speed(None) is None


def test_parse_board_ignores_placeholders():
    assert parse_board("To Be Filled By O.E.M.\nTo Be Filled By O.E.M.\n", "Vendor", "Name", None) == {"make": "Vendor", "model": "Name"}
    assert parse_board("Default string\nDefault string", None, "Name", None) == {"make": "unknown", "model": "Name"}
    assert parse_board("ACME\nSystem Product Name", "Vendor", "Name", None) == {"make": "Vendor", "model": "Name"}
    assert parse_board("Not Applicable\nNot Applicable", None, None, None) == {"make": "unknown", "model": ""}


def test_parse_lsblk_skips_mmcblk():
    text = json.dumps({"blockdevices": [{"name": "mmcblk0", "size": 32000000000, "model": None, "tran": None, "rota": False}]})
    assert parse_lsblk(text) == []


def test_dmidecode_ignores_other_handle_types():
    text = DMI_MEM + """Handle 0x0020, DMI type 20, 35 bytes
Memory Device Mapped Address
\tSize: 8 GB
"""
    assert len(parse_dmidecode_memory(text)) == 2


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
    from collect import notes_tower
    for m in (build_machine("beefy", "x", "tower", FIXTURE, "2026-10-24"), notes_tower("2026-10-24")):
        text = json.dumps(m).lower()
        for key in FORBIDDEN_KEYS:
            assert f'"{key}"' not in text


def test_corrupt_snapshot_is_treated_as_empty(tmp_path=None):
    import tempfile
    from pathlib import Path
    from collect import load_previous
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "specs.json"
        p.write_text("{not json")
        assert load_previous(p) == {"machines": []}
        p.write_text('{"machines": [{"name": "beefy"}]}')
        assert load_previous(p)["machines"][0]["name"] == "beefy"
        assert load_previous(Path(d) / "missing.json") == {"machines": []}


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
