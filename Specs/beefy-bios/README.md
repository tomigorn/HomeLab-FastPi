# beefy BIOS baseline (Gigabyte H510M H V2, BIOS F3)

Photos of the BIOS screens taken 2026-10-13 live in this folder but are
gitignored (26 MB). The accepted, final settings after the boot-time
experiments of that day:

- Favorites: CPU/Ring ratio Auto, XMP Disabled, Vcore Auto 1.200 V, CSM Disabled,
  Secure Boot Standard, VT-d Enabled, SATA controller Enabled,
  **ErP Disabled** (needed for S5 Wake-on-LAN).
- Boot: Fast Boot **Disable Link**, Windows 10 Features = Windows 10,
  Full Screen LOGO Enabled.
- SATA: AHCI, Aggressive LPM Disabled, Hot Plug Disabled except SATA3, PUIS off.
- Cold boot with these: firmware ~32 s, WoL → ssh ~48 s, → Jellyfin ~50 s.
  Boot-time tuning is closed: Fast Boot / Ultra Fast gained ~1 s, and the
  Exos HDD's POST wait (~14 s) dominates.

To enter the BIOS remotely: `sudo systemctl reboot --firmware-setup` on beefy
(Del at POST no longer works with Ultra Fast boot).
