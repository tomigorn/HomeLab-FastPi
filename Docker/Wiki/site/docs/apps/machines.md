# Our machines

**Address:** `https://specs.holy-grail.ch`

A blueprint-style page of the three machines everything runs on: a small always-on server, a media server that sleeps when idle, and a storage server. It lists the hardware parts only.

## How many can watch at once

Measured on 3 November 2026 with real films from our library, at home and from outside.

**What we download.** Requests aim for **4K HDR** (Dolby Vision, HDR10 or HDR10+), from a 4K Blu-ray or a streaming service; **1080p** when no 4K exists. Huge 1:1 Blu-ray copies (remuxes) are skipped on purpose. A typical 4K film needs about **18 Mbit/s**, a large one 25; 1080p about **8**.

| Watching | At home | From outside |
|---|---|---|
| **⭐ 4K HDR, original quality (typical, ~18 Mbit/s): the default for new requests** | **~50 at once** | **~30–40 at once** |
| 4K HDR, original quality (large, ~25 Mbit/s) | ~35 at once | ~20–30 at once |
| 1080p, original quality (~8 Mbit/s; older series, titles without 4K) | ~100 at once | ~65–90 at once |
| Converted for your device (4K HDR → 1080p) | 4 at once | 4 at once |

⭐ = our default: requests arrive in 4K HDR.

- **Original quality is easiest on the server.** Pick the highest quality in the player and let your TV or app play the file as it is.
- **Converting is the scarce part.** It happens when your device can't play the format, when you lower the quality, or when subtitles are burnt in. The fifth conversion at the same time starts to stutter.
- **From outside, your own internet speed also counts.** A 4K film needs about 20–25 Mbit/s.
