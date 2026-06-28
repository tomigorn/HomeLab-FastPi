# Setting the DHCP Server and DNS Server for the ISP Router
Prerequisits are:
- running AdGuard with DHCP on this Raspberry Pi
- static IP for Raspberry Pi set in nmtui

This README works for the Router Yzxel AX7501-B1

## log in to the router in the browser

http://192.168.1.1/

on the righthand side, the burger menu revels the things we're looking for:

go to: Network Setting / Home Networking

select the "Tab LAN Setup"

under DHCP Server State, disable the DHCP

Reboot the Router

---

## ⚠️ Important: you cannot use your own (local) DNS on this router

**Bottom line: with the Galaxus / Sunrise ISP firmware on the Zyxel AX7501-B1 it is _not_ possible to advertise a local DNS server (e.g. AdGuard / Pi-hole on the Pi) to LAN clients.** The router only accepts an *upstream* DNS — a public resolver like `8.8.8.8` (Google) or `1.1.1.1` (Cloudflare). This is why we take the DHCP route below instead.

### What users report

A user with the **exact same model (AX7501-B1)** documented the whole ordeal on the Pi-hole forum ([discourse.pi-hole.net](https://discourse.pi-hole.net/t/zyxel-router-ax7501-b1-dns-loop/84397)):

- The "static DNS" field in the DHCP section is **greyed out / hidden** in the UI; he had to use an "HTML trick" just to make the field editable.
- Even after the ISP enabled the static-DNS option for him, pointing it at a **local Pi-hole IP broke name resolution** (pinging IPs worked, resolving names did not).
- Testing with `dig +short CHAOS TXT id.server @1.1.1.1` showed the router was **intercepting / hijacking DNS queries** upstream, so a local resolver could never take effect.

### What the provider (Galaxus / Sunrise) says

- A provider representative confirmed in that thread: *"the static local DNS entry has been tested with external DNS like 8.8.8.8 or 1.1.1.1 only, not with a local Pi-hole instance,"* and that the local-DNS case was *"currently under investigation."* In other words, **local DNS is explicitly unsupported** — only public upstream resolvers are intended to work.
- On Galaxus/Digitec, the device is sold with the provider firmware: it gets **no firmware updates from Zyxel or the retailer**, and the config UI is the limited ISP version. (Galaxus AX7501 listing & Q&A: [galaxus.ch product Q&A](https://www.galaxus.ch/de/s1/questionandanswer/hallozwei-fragen-zu-zyxel-ax7501-b0-router-1-ist-auf-dem-angebotenen-modell-die-original-firmwar-441056), [Galaxus AX7501 install help](https://helpcenter.abos.galaxus.ch/hc/en-us/articles/22722967374098-Installation-Zyxel-AX7501))

➡️ **Conclusion: we sadly cannot run our own DNS _via the router's DNS setting_.** The only working way to get LAN clients onto our local AdGuard DNS is to stop using the router's DHCP entirely and hand out DNS from the Pi ourselves — see below.

## ✅ Good news: running our own DHCP _does_ work

Disabling the router's DHCP and running DHCP on the Pi (AdGuard) **is the confirmed working approach** — it's exactly what the same Pi-hole user ended up doing, and it's what the steps above set up:

1. **Disable DHCP on the Zyxel** and give the router a static LAN IP (e.g. `192.168.1.1`).
2. **Give the Pi a fixed static IP** (set in `nmtui`).
3. **Enable the DHCP server in AdGuard** on the Pi, copying the router's range (start/end IP, gateway, subnet) and advertising **the Pi itself as the DNS server**.

Because AdGuard's DHCP now hands out the Pi as DNS, clients use our local resolver — we get our own DNS *indirectly*, without ever touching the router's DNS field.

### Caveats users mention with this DHCP approach

- The router's **Guest WiFi / Guest network breaks** when its DHCP is disabled — guest clients get an auto-IP (169.254.x.x) and no internet, because that segment relied on the router's DHCP. ([Pi-hole forum](https://discourse.pi-hole.net/t/pihole-not-working-on-other-devices-using-a-zyxel-router/3608))
- DNS only reaches LAN clients if **the device handing out DHCP is the one advertising DNS** — so the Pi must be the *only* DHCP server on the LAN (don't leave the router's DHCP half-enabled).
- AdGuard/Pi-hole DHCP is a bit of "a patch on a wound" vs. a proper router DHCP, but it works reliably.

### Sources

- [Zyxel Router AX7501-B1 — DNS Loop? — Pi-hole Userspace](https://discourse.pi-hole.net/t/zyxel-router-ax7501-b1-dns-loop/84397) (same model; provider quote; HTML-trick; working DHCP workaround)
- [Pihole Not Working on Other Devices using a ZyXEL router — Pi-hole Userspace](https://discourse.pi-hole.net/t/pihole-not-working-on-other-devices-using-a-zyxel-router/3608) (disable-DHCP approach + Guest-network caveat)
- [Galaxus product Q&A — AX7501 firmware](https://www.galaxus.ch/de/s1/questionandanswer/hallozwei-fragen-zu-zyxel-ax7501-b0-router-1-ist-auf-dem-angebotenen-modell-die-original-firmwar-441056)
- [Galaxus Abos — Installation Zyxel AX7501](https://helpcenter.abos.galaxus.ch/hc/en-us/articles/22722967374098-Installation-Zyxel-AX7501)