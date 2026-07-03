# fastpi — Hardware Specifications

Home-lab "fastpi" server (always-on tier: Docker host, Traefik, Home Assistant, Authentik, and the orchestrator that wakes/sleeps `beefy`).

- **Hostname:** `fastpi`  ·  **LAN IP:** `192.168.1.2/24` (eth0)  ·  **MAC:** `2c:cf:67:26:3a:c8`
- **OS:** Debian GNU/Linux 12 (bookworm), aarch64 (64-bit)  ·  **Kernel:** `6.12.75+rpt-rpi-2712`
- **Gathered:** 2026-07-03 via `lscpu`, `lsblk`, `lspci`, `ip`, `ethtool`, `nvme`, device-tree, EEPROM.
- **Serial numbers intentionally omitted.**

---

## Case / Chassis

| | |
|---|---|
| **Model** | DIYzone 3-layer transparent acrylic case for Raspberry Pi 5 |
| **Type** | Stackable acrylic shell (3-layer), Pi 5 / cluster form factor |
| **Included fan** | PWM cooling fan (bundled with the case) |
| **Purchased** | 2024-08-23 (AliExpress, DIYzone Store) — ~CHF 8.49 |

*(Not software-detectable — from the purchase record. The active SoC cooling in use is the official Active Cooler below, wired to the Pi's 4-pin fan header.)*

## Power Supply

> Not software-detectable (USB-C PD bricks expose no OS-visible device). From the purchase record.

| | |
|---|---|
| **Model** | Official Raspberry Pi 5 27W USB-C Power Supply |
| **Output** | 5.1 V / 5 A (USB-C Power Delivery) |
| **Plug** | EU |
| **Purchased** | 2024-08-23 (AliExpress) — ~CHF 15.35 |

## Cooling

| | |
|---|---|
| **Model** | Official Raspberry Pi Active Cooler (heatsink + PWM fan) |
| **Connection** | Pi 5 4-pin fan header (temperature-controlled PWM) |
| **Detected as** | `pwm-fan` / `pwmfan` cooling device (`cooling_device0`) |
| **Purchased** | with the board — ~CHF 10.20 |

*(Throttling status at capture: `throttled=0x0` — no under-voltage or thermal throttling recorded.)*

---

## Board

| | |
|---|---|
| **Model** | Raspberry Pi 5 Model B Rev 1.0 |
| **Revision code** | `d04170` (8 GB variant, manufactured by Sony UK) |
| **RAM variant** | 8 GB |
| **Purchased** | 2024-07 — ~CHF 89.90 |

## SoC / CPU

| | |
|---|---|
| **SoC** | Broadcom BCM2712 |
| **CPU** | Arm Cortex-A76, quad-core (4C / 4T) |
| **Architecture** | `aarch64` — ARMv8.2-A (64-bit) |
| **Clock** | 2.4 GHz max / 1.5 GHz min (stepping r4p1) |
| **L1 cache** | 256 KiB data + 256 KiB instr (4× 64 KiB each) |
| **L2 cache** | 2 MiB (4× 512 KiB, per-core) |
| **L3 cache** | 2 MiB (shared) |
| **ISA extensions** | AES, PMULL, SHA1, SHA2, CRC32, atomics, FPHP, ASIMDHP/RDM/DP, LRCPC, DCPOP |

*(No discrete/usable transcode GPU worth noting — the VideoCore VII is present but this host runs headless server workloads.)*

## Memory (RAM)

| | |
|---|---|
| **Total** | 8 GB LPDDR4X (on-package, not user-replaceable) |
| **Reported** | `MemTotal: 8256576 kB` (≈ 7.9 GiB usable) |
| **Swap** | 2.0 GiB |

*(LPDDR4X-4267 is soldered on the Pi 5 module — no DIMM slots, not upgradable.)*

---

## Storage

| Dev | Model | Type / Bus | Capacity | FW | Filesystem | Mount / Role |
|---|---|---|---|---|---|---|
| `nvme0n1` | Samsung PM961 NVMe 512GB | NVMe M.2 2280 (PCIe) | 512 GB (476.9 GiB) | `CXY74D1Q` | vfat + ext4 | `/boot/firmware` (512 MB) + `/` (476.4 GiB) — **OS / boot** |
| `sda` | Seagate Expansion Portable 2TB | USB 3.0 external HDD | 2 TB (1.8 TiB) | — | ext4 | `/mnt/seagate-black` |
| `sdb` | Seagate One Touch HDD 2TB | USB 3.0 external HDD | 2 TB (1.8 TiB) | — | ext4 | `/mnt/seagate-red` |

- **Boot drive** is the NVMe (`nvme0n1p2` = `/`, `nvme0n1p1` = `/boot/firmware`).
- **NVMe carrier:** Geekworm X1001 PCIe-to-NVMe shield with metal case (purchased 2024-07-20, ~CHF 24.59).
- **NVMe cooling:** be quiet! MC1 M.2 SSD heatsink on the PM961 (~CHF 11.20, one of a 2-pack).
- **PCIe link:** running at **Gen2 x1 (5.0 GT/s)** — the Pi 5 default. The slot advertises up to 8.0 GT/s (Gen3), so `dtparam=pcie_gen=3` in `config.txt` could raise it (not currently set).
- USB IDs: `0bc2:231a` (Seagate Expansion), `0bc2:ab53` (Seagate One Touch).

**Total raw storage:** 512 GB NVMe + 2× 2 TB USB HDD = **~4.5 TB**.

---

## Networking

| Interface | Device | Speed / State |
|---|---|---|
| `eth0` (onboard) | Gigabit Ethernet via RP1 I/O controller (Broadcom BCM54213PE PHY; driver `macb`) | 1000 Mb/s, full duplex, link up |
| `wlan0` (onboard) | Cypress/Infineon CYW43455 dual-band 802.11ac Wi-Fi + Bluetooth 5.0 | DOWN (unused) |

- **eth0 MAC:** `2c:cf:67:26:3a:c8`  ·  **wlan0 MAC:** `2c:cf:67:26:3a:c9`
- The Pi 5 I/O (USB, Ethernet, GPIO) is fronted by the **Raspberry Pi RP1** southbridge (`RP1 PCIe 2.0 South Bridge`).
- *(Many `br-*` / `veth*` / `docker0` interfaces are Docker virtual bridges — omitted.)*

## USB

- Pi 5 provides **2× USB 3.0 + 2× USB 2.0** ports (plus internal). Both Seagate HDDs are on USB 3.0 root hubs.

---

## Firmware

| | |
|---|---|
| **Bootloader EEPROM (current)** | 2025-05-08 (`1746713597`) |
| **EEPROM update** | Available (latest 2025-12-08) — not yet applied |

---

## Purchase / Cost

Prices as paid (CHF). Serial numbers omitted; some drive prices are no longer on record.

| Item | Price (CHF) | Purchased |
|---|---|---|
| Raspberry Pi 5 Model B, 8 GB (board) | 89.90 | 2024-07 |
| Official Raspberry Pi Active Cooler | 10.20 | with board |
| Geekworm X1001 PCIe-to-NVMe carrier + metal case | 24.59 | 2024-07-20 |
| Samsung PM961 512 GB NVMe SSD | *n/a — not recorded* | — |
| be quiet! MC1 M.2 SSD heatsink | 11.20 | (1 of a 2-pack @ CHF 22.40) |
| Seagate Expansion Portable 2 TB (USB HDD) | 59.– | — |
| Seagate One Touch 2 TB (USB HDD) | *n/a — not recorded* | — |
| DIYzone 3-layer acrylic case (incl. PWM fan) | 8.49 | 2024-08-23 |
| Official Raspberry Pi 27W USB-C PSU | 15.35 | 2024-08-23 |
| **Total (recorded items)** | **≈ 218.73** | |

*(Two drives — the Samsung PM961 NVMe and the Seagate One Touch 2 TB — have no recorded purchase price, so the total above excludes them.)*

---

## Summary

| Component | Spec |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.0, 8 GB (Sony UK) |
| SoC / CPU | Broadcom BCM2712 — Arm Cortex-A76 quad-core @ 2.4 GHz, aarch64 |
| RAM | 8 GB LPDDR4X (soldered) + 2 GB swap |
| Case | DIYzone 3-layer transparent acrylic (with PWM fan) |
| Cooling | Official Raspberry Pi Active Cooler (PWM fan on header) |
| PSU | Official Raspberry Pi 27W USB-C (5.1 V / 5 A PD) |
| Boot | Samsung PM961 512 GB NVMe on Geekworm X1001 (PCIe Gen2 x1) |
| Data | 2× Seagate 2 TB USB 3.0 HDD (`/mnt/seagate-black`, `/mnt/seagate-red`) |
| Net | 1× Gigabit Ethernet (192.168.1.2), Wi-Fi/BT present but unused |
| OS | Debian 12 (bookworm), kernel 6.12.75+rpt-rpi-2712 |
