# beefy — Hardware Specifications

Home-lab "beefy" server (data/compute tier: Audiobookshelf, downloads, Samba, media).
Runs S5 poweroff + Wake-on-LAN (woken on demand from fastpi).

- **Hostname:** `beefy`  ·  **LAN IP:** `192.168.1.102/24` (enp6s0)  ·  **WoL MAC:** `74:56:3c:96:79:a3`
- **OS:** Ubuntu 26.04 LTS (Resolute Raccoon), x86_64  ·  **Kernel:** 7.0.0-22-generic
- **Gathered:** 2026-07-01 via SSH (`lscpu`, `lsblk`, `lspci`, DMI sysfs, `dmidecode -t 16,17`).
- **Serial numbers intentionally omitted.**

---

## Case / Chassis

| | |
|---|---|
| **Model** | Jonsbo Z20 (Black) |
| **Type** | Portable MATX / Mini-ITX chassis, ~20 L |
| **PSU support** | SFX / ATX |
| **Front I/O** | USB-C Gen2 |
| **Purchased** | 2024-08-23 |

*(DMI chassis vendor reads "Default string", type 3 / Desktop — the board firmware has no chassis identity; case info above is from the purchase record.)*

## Power Supply

> Not software-detectable (the Seasonic Prime PX has no digital/USB monitoring interface — no PSU device appears on USB/PCI). Details below are from the purchase record and **may be corrected later**.

| | |
|---|---|
| **Model** | Seasonic Prime PX-1000 (MPN `PRIME-PX-1000`) |
| **Wattage** | 1000 W |
| **Form factor** | ATX |
| **Efficiency** | 80 PLUS Platinum (~92%) |
| **Modularity** | Fully modular |
| **Fan** | 135 mm FDB, hybrid (fanless at low load) |
| **Protections** | OCP, OPP, OTP, OVP, SCP, UVP |
| **Connectors** | 14× SATA, 1× 24-pin ATX, 1× 4+4 EPS12V, 6× 6+2 PCIe, 1× Molex |

## Motherboard

| | |
|---|---|
| **Model** | Gigabyte H510M H V2 (rev `-CF`, board version `x.x`) |
| **Form factor** | Micro-ATX |
| **Chipset** | Intel H510 (PCH silicon reports as "Comet Lake") |
| **Socket** | LGA1200 |
| **Vendor** | Gigabyte Technology Co., Ltd. |

## BIOS / Firmware

| | |
|---|---|
| **Vendor** | American Megatrends Inc. (AMI) |
| **Version** | F3 |
| **Date** | 2023-12-20 |

---

## CPU

| | |
|---|---|
| **Model** | Intel Core i5-11400 (11th Gen, Rocket Lake-S) |
| **Socket** | LGA1200 |
| **Cores / Threads** | 6 C / 12 T |
| **Base clock** | 2.60 GHz |
| **Max turbo** | 4.40 GHz (min 800 MHz) |
| **TDP** | 65 W (spec) |
| **L1** | 288 KiB data + 192 KiB instr (6× each) |
| **L2** | 3 MiB (6× 512 KiB) |
| **L3** | 12 MiB (shared) |
| **Virtualization** | VT-x (VMX), VT-d capable |
| **Notable ISA** | AVX-512, VAES, SHA-NI, AVX2 |

## Integrated GPU

| | |
|---|---|
| **Model** | Intel UHD Graphics 730 (Rocket Lake-S GT1) |
| **PCI ID** | `8086:4c8b` (rev 04), bus `00:02.0` |
| **Architecture** | Xe (Gen 12.1), 24 EUs |
| **Max clock** | ~1.30 GHz |
| **Render node** | `/dev/dri/renderD128` (+ `card0`) — available for VA-API transcoding |

**Quick Sync Video — Version 8 (Gen 12, Rocket Lake).** Hardware decode: H.264/AVC, HEVC (8/10/12-bit), VP9 (8/10/12-bit), MPEG-2, VC-1, VP8, JPEG. Hardware encode: H.264, HEVC (8/10-bit), VP9 (8-bit), MPEG-2, JPEG. **Includes hardware HDR10 tone-mapping** (added in QSV v7 / Ice Lake) — so HDR→SDR transcodes are accelerated. **No AV1** (Rocket Lake has neither AV1 decode nor encode). Good fit for Plex/Jellyfin HW transcoding up to 4K HEVC/H.264 10-bit incl. HDR tone-map.

---

## Memory (RAM)

- **Total:** 64 GB DDR4 (2× 32 GB), dual-channel.
- **Modules:** Corsair Vengeance LPX — kit `CMK64GX4M2A2666C16` (64 GB 2×32 GB kit, rated **DDR4-2666 CL16**, dual-rank, 1.2 V).
- **Running speed:** **2133 MT/s** (JEDEC default). H510 does not support XMP / memory OC, so the modules run below their rated 2666.
- **Slots:** board has **2 physical DIMM slots, both populated** → no free slot; max board capacity 64 GB (already maxed). *(SMBIOS advertises 4 logical devices — ChannelA/B-DIMM0/1 — but only the two DIMM0 sockets exist and are filled; DIMM1 entries report "No Module Installed".)*

| Slot (locator) | Populated | Size | Type | Rated | Running | Module |
|---|---|---|---|---|---|---|
| ChannelA-DIMM0 | ✅ | 32 GB | DDR4, dual-rank | 2666 CL16 | 2133 MT/s | Corsair Vengeance LPX `CMK64GX4M2A2666C16` |
| ChannelB-DIMM0 | ✅ | 32 GB | DDR4, dual-rank | 2666 CL16 | 2133 MT/s | Corsair Vengeance LPX `CMK64GX4M2A2666C16` |
| ChannelA-DIMM1 | — | empty | — | — | — | (no physical slot / not installed) |
| ChannelB-DIMM1 | — | empty | — | — | — | (no physical slot / not installed) |

---

## Storage

| Dev | Model | Type / Bus | Capacity | FW | Filesystem | Mount / Role |
|---|---|---|---|---|---|---|
| `nvme0n1` | Samsung SSD 970 EVO 1TB | NVMe M.2 (PCIe) | 1 TB (1000 GB) | 2B2QEXE7 | vfat + ext4 | `/boot/efi` (1 GB) + `/` (930 GB) — **OS / boot** |
| `sda` | Samsung SSD 870 QVO 8TB | SATA III 2.5" SSD (QLC) | 8 TB (8001 GB) | — | ext4 | `/srv/.disks/ssd-hot` — **SSD hot tier** |
| `sdb` | Samsung SSD 870 QVO 8TB | SATA III 2.5" SSD (QLC) | 8 TB (8001 GB) | — | ext4 | `/srv/audio` — **Audiobookshelf audio** |
| `sdc` | Seagate ST30000NM004K-3RM133 (Exos M) | SATA III 3.5" HDD, 7200 RPM | 30 TB (30000 GB) | — | xfs | `/srv/.disks/hdd-cold` — **cold tier** |

- **mergerfs pool:** `/srv/video` (`fuse.mergerfs`) — unifies the hot-SSD + cold-HDD tiers for the video library.
- **SATA controller:** Intel H510/Comet Lake AHCI (`00:17.0`).
- **NVMe:** Samsung controller (SM981/PM981-class) on PCIe `05:00.0`.
- *(SATA drive firmware revisions require root/SMART — not captured; serials intentionally omitted.)*

**Total raw storage:** 1 TB NVMe + 2× 8 TB SATA SSD + 30 TB HDD = **47 TB** (~46 TB usable data across data mounts).

---

## Networking

| Interface | Device | Speed |
|---|---|---|
| `enp6s0` (onboard) | Realtek RTL8111/8168/8211/8411 PCIe Gigabit Ethernet (`06:00.0`, rev 15) | 1000 Mb/s |

*(docker0 / br-* / veth* are Docker virtual bridges.)*

## USB / Audio / Sensors

- **USB:** Intel H510/Comet Lake USB 3.1 xHCI host controller (`00:14.0`) — USB 2.0 + 3.0 root hubs.
- **Audio:** Intel Rocket Lake PCH HD Audio (`00:1f.3`, device `f1c8`).
- **hwmon sensors:** `coretemp`, `acpitz`, `nvme`, `pch_cometlake`, `gigabyte_wmi`.

---

## Summary

| Component | Spec |
|---|---|
| Case | Jonsbo Z20 (Black, ~20 L MATX) |
| PSU | Seasonic Prime PX-1000, 1000 W, 80+ Platinum *(unverified)* |
| Board | Gigabyte H510M H V2, H510, LGA1200, mATX |
| CPU | Intel Core i5-11400 — 6C/12T, up to 4.4 GHz, 65 W |
| iGPU | Intel UHD Graphics 730 (QSV v8, HDR tone-map, no AV1) |
| RAM | 64 GB DDR4 (2×32 GB Corsair Vengeance LPX @ 2133 MT/s), 2/2 slots full |
| Boot | Samsung 970 EVO 1 TB NVMe |
| Data | 2× Samsung 870 QVO 8 TB SATA SSD + Seagate Exos 30 TB HDD |
| Net | 1× Gigabit Ethernet (Realtek) |
| OS | Ubuntu 26.04 LTS, kernel 7.0.0-22 |
