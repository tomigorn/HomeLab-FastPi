# Wake-on-Demand Media Backend via Traefik — Deep Analysis

**Goal:** Let the always-on Raspberry Pi (`fastpi`, runs Traefik) front a power-hungry Intel tower
(`beefy`, transcodes the media/servarr stack) and an Unraid NAS (`tower-nas`, the storage). `beefy`
(and ideally the NAS) should hibernate while nobody is watching, wake on demand when someone wants
to watch, show some kind of "booting" feedback during the wake, and go back to sleep when idle —
all to cut idle power draw.

> **Superseded where it recommends S4 (2026-08-16).** Both machines ended up on
> **S5 poweroff + WoL**, not hibernation: beefy since 2026-06-18 (S4 rejected — stateless
> Docker host, no swap/resume fragility), tower via its `idle-shutdown` User Script. The
> wake half is built and running as `Docker/Beefy-Waker` and `Docker/Tower-Waker`. Read the
> sections below as the reasoning that led there, not as current configuration.

This document is **research and analysis only**. No code, no deployment. It lays out what is
actually possible in 2025–2026, the honest limitations, and several concrete implementation
scenarios with trade-offs.

> **Revision note (2026-06-09).** This document was updated after reviewing the *actual* `beefy`
> implementation (the `HomeLab-BeefyServer` repo, `Server/5-hybernation.md` + `Server/6-WOL.md`)
> where **S4 hibernation + WoL was tested and works reliably**, plus a second round of research into
> what senior operators run in production. **The sleep-state recommendation changed: the earlier
> "target S3, anything deeper is flaky" was a myth as stated, and is now corrected — see §2.** A
> review of the `beefy` docs themselves, including a real latent bug, is in §11. Confirmed facts
> about `beefy` from the docs: Ubuntu Server, kernel 6.8, **62 GB RAM**, 64 GB swapfile on LVM,
> NIC `enp6s0` at `192.168.1.102`, hibernates via `systemctl hibernate` (S4), woken via WoL.

---

## 1. The four jobs, separated

The single feature "wake the server on demand" is really **four independent sub-problems**, and
they have very different difficulty levels. Keeping them separate is the key insight — most failed
attempts conflate them.

| # | Job | Difficulty | Verdict |
|---|-----|-----------|---------|
| A | **Wake** `beefy`/NAS from sleep (send magic packet, wait for ready) | Easy | Solved, reliable |
| B | **Sleep** `beefy`/NAS when idle (detect "nobody watching", suspend) | Easy–Medium | Solved, well-trodden |
| C | **Proxy** the request once the backend is up (hold/retry, then forward) | Easy | Solved |
| D | **Show a "booting" screen** to the user during the wait | **Hard** for native apps | Partially solved; manage expectations |

A, B and C are proven and boring. **D is where the ambition meets reality** — and it's the part the
prompt is most excited about. The honest headline: for a *browser* you can show a beautiful loading
page; for the *native Jellyfin/Plex/servarr apps* you essentially cannot, and the best achievable
is "make the app spin and retry instead of erroring out."

---

## 2. Hardware/power reality check — and which sleep state to target

**This section was rewritten.** The original recommendation ("target S3, S4/S5 is flaky for WoL")
was wrong as a general rule, and `beefy`'s working S4 setup is the proof.

### Killing the myth: WoL reliability is about standby power, not the sleep state

The belief that "S3 is the safe WoL target and S4/hibernate is flaky" is **largely a myth.** The
reliability of waking from a deep state via WoL is **not** a function of S3-vs-S4. It is a function
of two things:

1. **Does standby power (5 V SB) keep reaching the NIC?** — a **BIOS `ErP`/`EuP` property**. ErP
   enabled = board severs standby power to the NIC = no WoL from *any* deep state.
2. **Does the OS leave the NIC *armed* instead of tearing it down on the way into the state?** — the
   `ethtool ... wol g` setting, made persistent, and no suspend script powering the interface off.

Both S3 and S4 keep WoL working if those two are satisfied; both fail if they aren't. Microsoft's
own kernel docs explicitly list "**activity on a LAN**" (i.e. WoL) as a wake source **from S4**, and
Intel documents WoL as supported **from S3 *or* S4** (and *not* from Windows Fast Startup or S5 —
which is almost certainly where the "deep states are flaky" myth came from: people conflated
Windows hybrid-shutdown/S5 failures with hibernate).

A genuinely counter-intuitive corollary worth knowing: **S4 resume runs a full firmware POST**
(ACPI spec §16 — it's handled like a cold boot, then the loader restores the image). On consumer
boards with buggy S3 ACPI tables, that means **S4 can actually be the *more* reliable of the two**,
because it goes through the same robust firmware path as a power-button cold start. `beefy`'s "S4
works reliably" report is therefore the *expected* case, not luck.

### Corrected sleep-state table

| State | Name | Real power draw | Wake by WoL? | Wake latency |
|-------|------|-----------------|--------------|--------------|
| **S3** | Suspend-to-RAM (`systemctl suspend`) | Standby + 64 GB self-refresh ≈ **~3–7 W** | **Yes** (needs standby power + armed NIC) | **~1–3 s** |
| **S4** | Hibernate (`systemctl hibernate`) | Standby + NIC trickle only ≈ **~1–4 W** (RAM unpowered) | **Yes** (same requirement; POST path often *more* robust) | full POST + image read ≈ **~15–40 s** on NVMe |
| **S5** | Soft-off (full shutdown) | Standby + NIC trickle, *if* ErP off | Works if standby kept; flakier in practice | full cold boot (tens of s → min) |
| s2idle | Suspend-to-idle (S0ix) | Higher than S3 | via normal network (NIC never sleeps) | ~instant |

Two corrections to the old table: **S4 is NOT "near-zero / 0 W"** — it's standby + NIC *trickle
current* (~1–4 W), same ballpark as S5/off; and the **S3-over-S4 power delta is small** (~1–3 W,
dominated by 64 GB of RAM self-refresh), not a category difference.

### Recommendation: **target S4 hibernate on `beefy`** (what you already built)

For *this* profile — a **big tower that idles at 40–60 W, is woken infrequently, and is then used
for long sessions** (watching something) — S4 is the better default:

- **Lowest idle power** (no RAM to refresh) — and the whole point of the project is power.
- **Survives power loss / a UPS running dry** — a real bonus for a server; it resumes after mains
  returns. S3 loses everything on a blip.
- **WoL is reliable once configured** — you've proven it on `beefy`.
- **The only real cost is wake latency** (~15–40 s, POST-dominated, vs S3's 1–3 s). For an
  infrequently-woken media box this is a non-issue *behind a loading page / retry* — and it makes
  the "show a booting screen" work in §5 **more** important, not less (see the latency note there).

**When S3 would win instead:** if `beefy` were woken *frequently for short tasks* and a 15–40 s wait
each time was annoying, S3's 1–3 s resume would matter more than the ~1–3 W it costs. That's not the
media use case. A middle path, `suspend-then-hibernate` (S3 first for fast wakes, auto-escalate to
S4 after an idle timer), exists — but its **RTC wake-alarm is a documented fragility** ("wakes
itself after ~5 min" bug; fix is `rtc_cmos.use_acpi_alarm=1`, defaulted on affected Intel boards
since ~kernel 6.5). For a rarely-woken server it adds a moving part for little gain — **skip it
unless you specifically want fast daytime wakes and have tested the RTC alarm.**

**The senior fallback if `beefy`'s ACPI ever proves flaky** is *not* "switch to S3" — it's **full
shutdown + WoL** (or a smart plug + UEFI "power-on after power loss"), which sidesteps ACPI
resume entirely. Many experienced operators run exactly that.

### Config checklist for reliable WoL (identical for S3 and S4)

- BIOS: **enable** "Wake on LAN" / "Resume by PCI-E" / "Resume by LAN"; **disable** "ErP/EuP Ready".
  (`beefy` clearly has standby power to the NIC since WoL works — but verify ErP if you ever move to
  S5 shutdown.)
- OS: make `ethtool -s enp6s0 wol g` **persistent** (a systemd unit — which `beefy` does, §11) and
  ensure no suspend/TLP script powers the NIC down (`WOL_DISABLE=N` if TLP is ever installed).
- Sanity check: the NIC link LED should **stay lit** when the box is hibernated.
- (Windows note, for completeness — `beefy` is Ubuntu so N/A: disable Fast Startup; WoL from true
  S5 is unsupported on Windows.)

### Power payoff (illustrative, from real homelab writeups)

- A documented Plex-sleeps-on-idle setup (Maximilian Golla): idle **43 W → 23 W**, **asleep 89 % of
  the time over 140 days**, cost **€70/yr → ~€13/yr**.
- A HN "suspend my home server" report: active idle **43 W → ~4 W** suspended.
- NAS disks: a Dell T320 with 8 HDDs drew **126 W spun-up → 70 W spun-down**.

The numbers are board-specific and illustrative — but the order of magnitude (idle dropping from
tens of watts to single digits) is well-corroborated and clearly worth it for `beefy`. Note `beefy`
in S4 sits in the **~1–4 W** band, the lowest of the sleep options.

---

## 3. Job A — Waking the backend

### Sending the magic packet from `fastpi`

```bash
# wakeonlan (Perl): no root needed, UDP broadcast — best fit for the Pi
wakeonlan AA:BB:CC:DD:EE:FF
wakeonlan -i 192.168.1.255 -p 9 AA:BB:CC:DD:EE:FF

# etherwake: raw L2 frame, needs root + interface, but no IP/ARP dependency
sudo etherwake -i eth0 AA:BB:CC:DD:EE:FF
```

WoL is an **L2 broadcast** — it works because `fastpi`, `beefy` and the NAS are on the **same LAN**.
(Across VLANs/subnets you'd need a directed-broadcast relay on the router; keeping them on one
segment avoids that entirely.) Known quirk: some tools/clients only wake reliably when the target is
addressed by **hostname**, not IP — worth remembering if a wake mysteriously fails.

### Enabling WoL on the targets

```bash
sudo ethtool eth0                 # confirm "Supports Wake-on: ...g..." then:
sudo ethtool -s eth0 wol g        # 'g' = wake on magic packet
```

`ethtool wol g` **does not persist across reboot.** Persist it:
- On `beefy` (Linux): udev rule or systemd unit re-applying `ethtool -s eth0 wol g` on boot.
- On **Unraid**: add `/usr/sbin/ethtool -s eth0 wol g` to `/boot/config/go` (Unraid-specific). Use
  **wired Ethernet only** — Unraid explicitly does not support WoL over WiFi. If using the default
  `br0` bridge, ensure WoL is enabled on the underlying physical `eth0`, not just the bridge.

This job is fully solved and reliable.

---

## 4. Job B — Sleeping the backend when idle

Two halves: **deciding it's idle**, and **triggering the suspend securely.**

### Deciding "nobody is watching" — ask the media server, don't guess

Inferring idle from raw TCP connections is fragile (a lingering SMB mount or a polling Docker
container keeps the box "busy" forever). The robust approach polls the media server's session API:

- **Plex:** `GET http://beefy:32400/status/sessions?X-Plex-Token=...` → XML `<MediaContainer>`;
  `size` attribute = number of active playback items (0 = nothing playing). Each `<Player>` has a
  `state` (`playing`/`paused`/`buffering`) so **paused can count as idle**.
- **Jellyfin:** `GET http://beefy:8096/Sessions` with `Authorization: MediaBrowser Token=...` →
  JSON array; a session has a non-null **`NowPlayingItem`** only while playing; check
  `PlayState.IsPaused`. Key on `NowPlayingItem` + `IsPaused` + a grace period (abandoned/buffering
  VOD sessions can linger).

Proven pattern (Golla, ran 140 days): poll every **60 s**, suspend after **~15 min** of no active
playback, where paused doesn't count. Also check `lsof /mnt/*` so an in-flight backup/copy blocks
sleep.

### The clean mechanism: systemd inhibitor locks

Rather than racing a sleep timer against playback, the standard, non-bespoke approach on systemd
Linux is **inhibitor locks**: a watcher takes `systemd-inhibit --what=sleep` while a stream is live,
so `systemctl suspend` simply blocks until it's safe. Off-the-shelf tools that do exactly this:
- `sleep-inhibitor` (bulletmark) — pluggable framework, ships **Plex and Jellyfin plugins**.
- `Jellyfin-Inhibit-Sleep` (Kwakers01) — polls sessions every 45 s, holds an inhibitor lock.
- Jellyfin "prevent-sleep" plugin (jonschz) — server-side equivalent.

This aligns with the standing preference for **standard, built-in mechanisms over bespoke fragile
ones** — inhibitor locks are the idiomatic answer.

### Triggering the suspend from `fastpi` securely

Waking is a low-trust broadcast; **sleeping is the security-sensitive direction** (you don't want an
open "suspend my server" endpoint). Recommended pattern — **SSH key locked to a forced command:**

```
# on beefy: ~sleeper/.ssh/authorized_keys
command="/usr/local/bin/go-to-sleep",no-port-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... fastpi
```
```bash
# on beefy: /usr/local/bin/go-to-sleep — the ONLY thing this key can run
#!/bin/sh
exec systemctl suspend
```

`ssh sleeper@beefy` then suspends and can do literally nothing else. No new daemon, no new network
surface, mutual key auth out of the box. (Windows `beefy` equivalent: `rundll32.exe
powrprof.dll,SetSuspendState 0,1,0` over OpenSSH — same forced-command principle.)

If you specifically want **Traefik itself** to trigger sleep over HTTP, the alternative is a tiny
single-endpoint sidecar (bearer token, bound to localhost/the proxy network) — but the
SSH-forced-command path is lower-risk and is the default recommendation.

### Unraid specifics

Unraid can S3-sleep the whole box via the **Dynamix S3 Sleep** plugin (Community Apps → Settings →
Sleep Settings). Reading its actual source, it sleeps only when **all** of: array disks spun down
(+ configurable extra delay, default 30 min), network throughput below threshold, no established
SSH/Telnet sessions, no logged-in console, optional ping targets unreachable, and time-of-day
allowed. Wakes via WoL like any host.

**Honest Unraid caveat:** the #1 complaint is "**it never sleeps**" because one chatty client (an
SMB mount, a phone re-mounting a share, a Docker container) holds a connection. Debug with
`lsof -i`. **Recommendation:** for a NAS accessed semi-regularly, plain **disk spin-down** (keeps
the box reachable, parks idle HDDs, ~126 W → ~70 W in the example) is often the safer, simpler win
than full S3 sleep — reserve whole-box sleep for genuinely long idle windows. This also dodges the
"two backends asleep behind the proxy" coordination headache (see §7).

---

## 5. Job C + D — The proxy and the "booting" screen

This is the heart of the Traefik question. Findings below are **source-code-verified**, not just
docs.

### The tool landscape

| Tool | Proxy | Wakes bare metal? | Loading page? | Wait mechanism |
|------|-------|-------------------|---------------|----------------|
| **Sablier** (Traefik plugin) | Traefik | **No** — containers/LXC only | **Yes** (auto-refresh page) | Polls its own API |
| **MarkusJx/traefik-wol** (Traefik plugin) | Traefik | **Yes** | **No** — request just hangs | WoL, polls health every 5 s × `numRetries` |
| **caddy-wol** (dulli) | Caddy | **Yes** | No page; slow load | WoL on 502, re-proxy w/ long timeout |
| **caddy-jellywol / JellyWolProxy** (Stoufiler) | Caddy | **Yes** | Via 503+Retry-After | WoL + per-path block/trigger |
| **hvs-consulting/wol-proxy** (Go) | standalone | **Yes** | **Yes** (page + Start button) | Polls readiness route, Nginx failover |

### The two disappointments worth internalizing

1. **Sablier — the tool with the *best* loading page — cannot wake bare metal.** Verified at source
   level: its only providers are Docker, Swarm, Podman, Kubernetes, Proxmox-LXC. There is **no WoL,
   exec, or script provider**, and **no plugin hook** to add one without forking and writing Go. Its
   gorgeous auto-refreshing waiting page is wasted here because it can't drive a magic packet. *Only*
   relevant if you ever containerize/virtualize the workload (e.g. media stack as a Proxmox VM/LXC).

2. **MarkusJx/traefik-wol — the only Traefik-native WoL middleware — has no loading page.** Verified
   by reading its `ServeHTTP`: on a request it checks health, sends WoL if down, then **loops up to
   `numRetries` times sleeping 5 s between checks** (default 10 → ~50 s max) and only then proxies;
   if not up in time it returns **HTTP 500**. The user sees a **hanging browser tab**, not a page.
   It *does* support sleep-on-idle via `stopTimeout` + `stopUrl` (needs something like
   `SR-G/sleep-on-lan` on `beefy`). For a tower that takes 60–120 s to be ready you must raise
   `numRetries` (e.g. 30–40) **and** the client must tolerate that long hanging request.

### The universal constraint

A real browser/upstream request can only hang so long before *its own* timeout fires. A cold tower
(POST + OS + service start) is often 60–120 s+. So:
- Tools that **hold the request** (traefik-wol, caddy-wol) **race the client timeout** — fine for a
  1–3 s S3 resume, risky for a long boot.
- Tools that **return an auto-refreshing page or a 503+Retry-After** (Sablier page, JellyWolProxy,
  wol-proxy) **sidestep the timeout** — the page/client does the waiting and reloads. This is why
  they give the best UX for slow wakes.

**Latency note — and why the S4 decision (§2) reshapes this.** Because `beefy` targets **S4
hibernate**, the wake is **~15–40 s** (POST + image read), not the ~1–3 s of S3. That makes the
"hold the request" tools (traefik-wol blocking, caddy-wol) a **poor fit** — a 15–40 s hang will
exceed many native-app and some browser timeouts — and makes the **auto-refreshing page / 503 +
Retry-After** tools (JellyWolProxy, wol-proxy) the **right choice**, because the page/client does
the waiting and reloads rather than holding one socket open. In other words, choosing S4 for the
power win **raises** the importance of a proper loading/retry layer; it doesn't make the UX problem
go away the way a 1–3 s S3 resume nearly would. (If you ever needed the fast-wake UX, that's the
argument for S3 or `suspend-then-hibernate` — but for an infrequently-woken media box the loading
page is the better lever.)

### The native-app wall (Job D, the hard part)

The prompt's instinct is right: the servarr/Jellyfin/Plex **native apps are the problem.** They
speak JSON/XML to the API, not HTML — **there is nowhere to inject a "please wait, booting" page.**
When `beefy` is asleep, the app just shows its own generic "server unavailable" error.
- Jellyfin's own maintainers state plainly: an asleep server can't know a client started, and there
  is **no native wake** feature; community workaround is a *separate* WoL app fired before opening
  Jellyfin.
- Plex apps discover the server via plex.tv; **Relay** only helps a *running* server, not a sleeping
  one.

**The realistic ceiling for native apps:** return **HTTP 503 + `Retry-After`** on the streaming
paths so the client **spins and auto-retries** instead of erroring — which is exactly what
**caddy-jellywol** is built to do (TCP-ping backend → fire WoL → `trigger_paths` pass through and
wake in the background, `block_paths` return 503+Retry-After, default 10 s). But honestly:
- There is **no tested-client compatibility matrix.** Retry behavior is **not uniform** — Infuse
  retries gracefully; **Jellyfin iOS has a known bug (#770) where it locks up on a 503** instead of
  retrying cleanly.
- You generally **cannot** show branded "booting" text inside a native app, and you can't guarantee
  every client retries. Plan to **provide a manual wake fallback** (a Home Assistant button, a WoL
  phone app, or a simple "wake" web page on `fastpi`) for clients that don't.

For **browser** access (Jellyfin/Plex web UI, the *arr web UIs) you *can* show a real branded
loading page — that's the easy 20%.

---

## 6. The "cache the library on fastpi so the user browses while beefy boots" idea

This is the most attractive idea in the prompt — and the **weakest / most speculative.** Honest
assessment after researching it specifically:

- **No existing project does this.** Nobody serves a Jellyfin/Plex library for browsing from an
  always-on box while the real server sleeps.
- **Jellyfin/Plex don't separate "browse" from "stream".** The *same server process* answers both
  the metadata/API calls and the streaming/transcode. Metadata isn't an independent service.
  Jellyfin metadata/artwork live in the server's config dir (`/config/metadata/`, `…/metadata/`) +
  a SQLite DB — **served by the Jellyfin process itself.** Copying the folder to `fastpi` gives you
  inert files, not a working browse UI.
- To truly "browse on the Pi" you'd need a **second lightweight Jellyfin/Plex instance (or a custom
  catalog app) on `fastpi`** sharing/replicating the library DB + artwork, then a **session/auth
  handoff** to `beefy` at "Play". The handoff is the hard, unsolved part. **Treat this as a
  from-scratch research project, not a recipe.**

**The pragmatic substitute that achieves the same goal:** instead of caching the catalog, **wake
`beefy` early — on app connect / first browse — so it's ready by the time the user finishes
choosing.** This hides the boot latency behind the user's natural "scroll and pick" time and
requires *none* of the unsolved replication work. That's what the `trigger_paths` mechanism is for:
fire WoL on cheap, idempotent browse/login API calls; 503+Retry-After only the heavy stream paths so
a user who races ahead to Play waits rather than errors.

(One real but limited win nearby: because metadata/artwork sit on the server's fast config disk, the
**NAS drives can stay spun down during browsing** — but only while `beefy` itself is awake. It does
not let `fastpi` serve the catalog while `beefy` sleeps.)

---

## 7. Coordinating three machines (fastpi → beefy → NAS)

If both `beefy` and the NAS sleep, **wake them in the right order with the right timing:**
- `beefy` needs the NAS storage to serve media, so on a wake you likely **wake the NAS first (or
  together)**, then `beefy`, and only mark "ready" once `beefy`'s media service responds *and* its
  NAS mounts are live. A health check that only pings `beefy:8096` can report "ready" before the NAS
  mount is back, producing errors on first playback.
- Two independently-sleeping backends multiply the "won't sleep / won't wake" failure modes.
- **Simplest robust topology:** keep the **NAS on disk-spin-down only** (always reachable, no wake
  coordination, parks idle drives) and let **only `beefy` do full S3 sleep**. You get most of the
  power saving with far less orchestration risk. Escalate the NAS to full sleep later only if the
  idle windows justify it.

---

## 8. Implementation scenarios

Five concrete options, roughly increasing in UX quality and effort.

### Scenario 0 — Baseline: no sleep, just spin-down (do this first)
- NAS: disk spin-down via Dynamix. `beefy`: leave running, or only manual sleep.
- **Effort:** trivial. **Power saving:** modest (drives only). **UX:** perfect (nothing changes).
- **Use as the control** to measure how much the rest actually buys you.

### Scenario 1 — Pure Traefik, `MarkusJx/traefik-wol` (simplest "real" version)
- Traefik middleware on `fastpi` wakes `beefy` via WoL, polls health, proxies when up; sleeps via
  `stopUrl` + `sleep-on-lan` on `beefy`. NAS on spin-down (Scenario 0).
- Set `numRetries` high enough to cover the **full S4 boot (~15–40 s)** — e.g. 8–10+ retries at
  5 s each — and confirm the client tolerates that long hanging request.
- **Pros:** all-in-Traefik, no extra proxy layer, native sleep+wake in one plugin.
- **Cons:** **no loading page** — first cold request is a hanging tab, and with `beefy`'s ~15–40 s
  S4 wake that hang is long enough to trip native-app and some browser timeouts. **Weaker fit now
  that the target is S4, not S3** — this scenario was most attractive under the old fast-S3-resume
  assumption. Acceptable for browser-only access where you tolerate a long spinner.

### Scenario 2 — Caddy sidecar with `caddy-jellywol` behind Traefik (best native-app UX)
- Traefik routes the media hostnames to a small **Caddy** instance running `caddy-jellywol`, which
  TCP-pings `beefy`, fires WoL, passes `trigger_paths` through (waking in background) and returns
  **503+Retry-After** on `block_paths` (stream endpoints).
- Pair with the **auto-sleep watcher** (§4): poll Jellyfin `/Sessions` or Plex `/status/sessions`,
  inhibit-lock during playback, SSH-forced-command suspend after ~15 min idle.
- **Pros:** purpose-built for exactly this; native apps **spin-and-retry** instead of erroring;
  per-path control means wake-on-browse + protect-on-play.
- **Cons:** introduces a second proxy layer behind Traefik; retry behavior is **per-client** (test
  each; Jellyfin iOS #770 caveat); no branded screen inside native apps.

### Scenario 3 — Standalone `hvs-consulting/wol-proxy` for browser-first access (nicest page)
- Put `wol-proxy` (real waiting page + Start button, polls readiness, auto-switches to live server)
  behind Traefik for the **web UIs**. Combine with Scenario 2's approach for native apps if needed.
- **Pros:** the actual "booting…" page the prompt wants, for browser users; handles long boots.
- **Cons:** only helps HTTP/browser clients; another component to run; doesn't fix native apps.

### Scenario 4 — Wake-on-browse + manual fallback (recommended overall shape)
Combine the proven pieces into the architecture that best matches the prompt's intent:
1. **Wake early, not on play:** fire WoL on the first cheap browse/login API call (Scenario 2's
   `trigger_paths`), so `beefy` (S4 wake ~15–40 s, plus a little for the media service to be ready)
   is up before the user finishes choosing. With S4's longer wake this "wake on browse" head-start
   matters *more* — it's the realistic version of "browse while it boots", and it hides the entire
   hibernate-resume behind the user's natural scroll-and-pick time.
2. **Protect play:** 503+Retry-After the stream paths so racing ahead to Play waits, not errors.
3. **Loading page for browsers** via wol-proxy/JellyWolProxy; **graceful retry for native apps** as
   the ceiling, **plus a manual "Wake `beefy`" button** (Home Assistant / a tiny page on `fastpi`)
   for clients that won't retry.
4. **Auto-sleep** via session-API polling + systemd inhibitor locks + SSH-forced-command suspend.
5. **NAS on spin-down only** (Scenario 0) to avoid multi-box wake coordination.

### Scenario 5 — Containerize the media stack → unlock Sablier (different long game)
- If the media/servarr stack were moved into **containers on a host that itself stays awake**, or
  into a **Proxmox VM/LXC**, then **Sablier's polished auto-refresh waiting page** becomes usable
  (it scales the workload, not the metal). This trades the "sleep the whole tower" goal for
  "best-in-class loading UX + per-service scale-to-zero" — a fundamentally different architecture,
  noted for completeness, not recommended as the first move given `beefy`'s whole-box-sleep goal.

---

## 9. Honest verdict & recommended path

- **Jobs A, B, C are solved.** Wake (magic packet — already working on `beefy` from S4), sleep
  (session-poll + inhibitor + SSH forced command), and proxy-when-ready all have reliable, standard
  implementations.
- **Sleep state: target S4 hibernate, not S3** (corrected from the first draft). For a power-first,
  infrequently-woken tower it gives the lowest idle draw and survives power loss; WoL reliability is
  a config concern (ErP off + armed NIC), not a state concern. The trade-off is a ~15–40 s wake,
  which is precisely why the loading/retry layer below matters.
- **Job D (the booting screen) is genuinely limited by the clients, not by Traefik.** Browsers can
  get a real loading page; **native apps cannot** — the honest best is 503+Retry-After "spin and
  retry," which works for some clients and not others, backed by a manual wake fallback.
- **The "browse a cached catalog on fastpi while beefy boots" idea does not have an off-the-shelf
  solution and is a hard build.** The pragmatic equivalent — **wake-on-browse so beefy is ready by
  the time the user hits Play** — gets ~the same user experience with proven parts.
- **Traefik alone** (Scenario 1) is the least-effort real option but offers no loading page. For the
  UX the prompt wants, **a small purpose-built WoL proxy behind Traefik** (Scenarios 2–4) is the
  sweet spot.
- **Keep the NAS on disk spin-down, sleep only `beefy`** to avoid multi-machine wake coordination.

**Suggested first step:** `beefy`'s S4 hibernate + WoL is already proven (Jobs A and the sleep state
are done). Next, add the **auto-sleep watcher** (Job B — session-poll + inhibitor + SSH forced
command) so `beefy` puts *itself* back to sleep, then layer the proxy: go straight to **Scenario 2
(JellyWolProxy / 503 + Retry-After)** rather than Scenario 1, because `beefy`'s ~15–40 s S4 wake is
too long for the "hanging request" model. Keep the NAS on disk spin-down. Escalate toward Scenario 4
(wake-on-browse + manual fallback) once the basics are proven. Before all of this, fix the
`resume_offset` typo flagged in §11.

---

## 10. Open questions to resolve before building

Answered since the first draft (from the `beefy` docs): **`beefy` is Ubuntu Server** (so the suspend
command, persistence and Fast-Startup caveats are settled); **S4 hibernate + WoL works**; the design
targets **S4**, so the "is there true S3?" question is moot. Still open:

1. **Is `beefy` booted UEFI or legacy BIOS?** (`[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS`.)
   This is **load-bearing for the `resume_offset` typo in §11** — harmless on UEFI+systemd-255,
   a real active bug on BIOS. Verify.
2. **Is Secure Boot on or off?** Hibernate working implies it's **off** today. Note it: enabling
   Secure Boot later will **break hibernation** (kernel lockdown forbids the unencrypted image).
3. **Jellyfin or Plex?** (Or both / Emby?) Determines the exact session API and which WoL-proxy
   project fits (JellyWolProxy is Jellyfin-named but the pattern generalizes).
4. **Which clients dominate** — browser, or native TV/mobile apps? Decides how much the native-app
   wall matters and whether the manual-wake fallback is essential. (More urgent now: the ~15–40 s
   S4 wake is long enough that native-app retry behaviour really matters.)
5. **Are `fastpi`, `beefy`, NAS on the same L2 segment?** The `beefy` doc shows `192.168.1.0/24`
   and `wakeonlan` broadcasting to `255.255.255.255:9` working, so this looks like **yes** — confirm
   `fastpi`/NAS are on the same `/24`.
6. **Acceptable cold-wait?** With S4 the realistic floor is ~15–40 s; the loading/retry layer (§5)
   has to cover it gracefully.
7. **Should the NAS ever fully sleep, or is spin-down enough?** Strongly leaning spin-down-only.
8. **Is `beefy`'s root LV encrypted (LUKS)?** If not, the S4 hibernation image is a **plaintext RAM
   dump on disk** (secrets included) — see §11.

---

## 11. Review of the existing `beefy` implementation docs

Review of `HomeLab-BeefyServer/Server/5-hybernation.md` (S4 hibernate setup) and `6-WOL.md` (WoL).
Overall: **a solid, correct, well-documented setup** — the swapfile sizing, `filefrag` offset
method, `update-grub`/`update-initramfs`, the persistent `wol@.service` systemd unit, and the
end-to-end WoL test are all done right, and the result demonstrably works. The items below are
weaknesses, latent traps, and things worth adding — roughly in priority order.

### 🔴 Real bug — the `resume_offset` parameter is misspelled

In `5-hybernation.md` the GRUB line reads `resume_offeset=4831232` (and `/proc/cmdline` confirms the
typo is live: `... resume=UUID=... resume_offeset=4831232`). The correct kernel parameter is
**`resume_offset`**. The kernel silently discards unrecognised tokens, so this parameter is being
**ignored**.

Why hibernation still works anyway: **Ubuntu 24.04 ships systemd 255**, which on **UEFI** systems
auto-detects the swap location, computes the swapfile offset itself, writes it to
`/sys/power/resume_offset` at hibernate time, and records the device+offset in the
**`HibernateLocation` EFI variable**. On the next boot `systemd-hibernate-resume` reads that EFI
variable — **not** the kernel cmdline — so the misspelled parameter never gets consulted. That's
almost certainly why it "just works."

But it's a **latent trap, not harmless**:
- If `beefy` is ever **booted in legacy BIOS mode** (no EFI variables), resume falls back to the
  `resume=`/`resume_offset=` cmdline — and with the typo, **resume would fail** (cold boot, hibernate
  image discarded). *First confirm boot mode:* `[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS`.
  If it's BIOS, this is an **active bug right now**, and resume is succeeding only via the
  initramfs `conf.d/resume` value.
- The EFI-variable mechanism has had its own bugs (stale/invalid `HibernateLocation`).
- It's misleading to anyone reading the doc.

**Fix:** correct it to `resume_offset=`, re-run `update-grub` + `update-initramfs -u -k all`, and
verify after a cycle with `cat /sys/power/resume_offset`. Costs nothing, closes the trap. (Also note
the offset **silently changes** if the swapfile is ever recreated/resized or a defrag tool touches
it — so "don't defrag/recreate `/swap.img`" is worth a line in the doc.)

### 🟠 Security — the hibernation image is a plaintext RAM dump on disk

S4 writes the full contents of RAM (encryption keys, decrypted data, session tokens, SSH agent
material) into `/swap.img`. If `beefy`'s root LV (`/dev/mapper/ubuntu--vg-ubuntu--lv`) is **not
LUKS-encrypted**, that snapshot sits **in cleartext** on the disk and is readable by anyone who pulls
the drive. This is exactly why kernel lockdown forbids unencrypted hibernate under Secure Boot.
For a home box behind a locked door this may be an acceptable risk — but it should be a *conscious*
decision. Mitigation is **full-disk LUKS** (so the swapfile is encrypted at rest); note that
hibernate then requires the LUKS unlock to happen in the initramfs *before* the resume hook
(`encrypt`/`lvm2` → `resume` ordering). The random-key encrypted-swap pattern **cannot** be used
with hibernate (the key wouldn't survive the power-off). Worth at least a "⚠️ unencrypted image"
note in the doc.

### 🟠 Secure Boot will silently break this if enabled later

Hibernate working today means **Secure Boot is currently off** on `beefy` (Secure Boot → kernel
lockdown → unencrypted hibernation is hard-disabled, failing with a "hibernation is restricted"
lockdown message). If a future hardening pass enables Secure Boot, **hibernate stops working** with
a non-obvious error. Add a one-line warning to the doc so that future-you connects the two. (The
supported combo of Secure Boot + hibernate exists but needs TPM-sealed FDE + signed images — a
significant project, not a toggle.)

### 🟡 Post-resume gotchas beyond the VS Code CPU storm

The doc already documents and fixes one resume-time issue (VS Code server's ripgrep indexing the
8 TB/30 TB mounts — nicely handled via `files.watcherExclude`/`search.exclude`). That's an instance
of a **general class**: after a long hibernate, things that notice "time jumped" or had live state
can misbehave. For a media/servarr server specifically, watch for and consider a
`/usr/lib/systemd/system-sleep/` post-resume hook to handle:
- **Clock/NTP not re-syncing** after resume (known `systemd-timesyncd` issue; `chrony` handles the
  big time-step more gracefully, or `chronyc makestep` / restart timesyncd in a resume hook).
- **systemd timer thundering-herd** — calendar timers that would have fired during the hibernate
  all fire at once on resume (backups, apt, fstrim, logrotate). Tune `Persistent=`/randomized
  delays for the heavy ones.
- **Docker containers + long-lived TCP/TLS** — connections held across a multi-hour hibernate are
  usually dead on resume; containers/health-checks may flap until they reconnect. A
  `systemctl restart docker` resume hook is the common blunt fix.
- **Intel iGPU (i915) transcoding** — an in-flight hardware transcode won't survive S4, and i915 has
  a history of post-resume hiccups. **Explicitly test** a Jellyfin/Plex HW-transcode after a
  hibernate/resume on this exact kernel; restart the media service in a resume hook if needed.

### 🟡 Smaller notes

- **Swap sizing:** 64 GB swap ≥ 62 GB RAM is correctly sized. To fully kill the rare "not enough
  swap for hibernation" edge on a busy/transcoding box (where RAM is full *and* some is already
  paged out), nudge swap to **RAM + a few GB**. Minor.
- **`/etc/fstab`:** the doc verifies the swap line is present — good; that's needed so `swapon` and
  the resume path see the swapfile on boot.
- **WoL persistence:** the `wol@enp6s0.service` unit is the right, standard approach (matches the
  §4/§2 recommendation). One robustness note: `After=network-pre.target` is fine, but on some setups
  the NIC's `wol g` flag can be reset by a later NetworkManager/networkd event or driver
  re-init — worth a periodic re-check (`ethtool enp6s0 | grep Wake-on` should show `g`) if a wake
  ever mysteriously fails.
- **Docker bridge vs physical NIC:** `6-WOL.md` correctly targets `enp6s0` (the physical NIC with
  `192.168.1.102`), not `docker0`/`veth*` — good. Just keep enabling `wol g` on `enp6s0`
  specifically, never the bridge/veth interfaces.
- **ErP/BIOS:** the doc doesn't mention the BIOS `ErP/EuP` setting. Since WoL works, standby power is
  clearly reaching the NIC, so nothing to do now — but if you ever switch to **full S5 shutdown**
  instead of S4, revisit ErP (must be off) because S5 is where boards most aggressively cut NIC
  standby power.
- **Auto-sleep is out of scope of these two docs** (they cover wake + manual hibernate). The missing
  half for the Traefik project is Job B from §4: something that decides `beefy` is idle (media
  session-API poll + inhibitor lock) and triggers `systemctl hibernate` automatically. That's the
  natural next doc.

### Verdict on the docs

No changes needed to the *approach* — S4 hibernate + WoL is the right design and it's implemented
correctly. **One thing to actually fix (the `resume_offset` typo)**, two things to consciously
decide and document (unencrypted image; Secure-Boot incompatibility), and a handful of resume-time
robustness hooks to add as you put `beefy` into real always-sleeping service.

---

## Appendix — Key references

**Traefik / proxy WoL tooling**
- Sablier — https://github.com/sablierapp/sablier · Traefik plugin https://github.com/sablierapp/sablier-traefik-plugin
- MarkusJx/traefik-wol — https://github.com/MarkusJx/traefik-wol · catalog https://plugins.traefik.io/plugins/642498d26d4f66a5a8a59d25/wake-on-lan
- caddy-wol — https://github.com/dulli/caddy-wol
- caddy-jellywol / JellyWolProxy — https://github.com/Stoufiler/caddy-jellywol
- hvs-consulting/wol-proxy — https://github.com/hvs-consulting/wol-proxy
- SR-G/sleep-on-lan (sleep agent for the target) — https://github.com/SR-G/sleep-on-lan
- systemd-socket-proxyd (same-host on-demand, for context) — https://manpages.debian.org/testing/systemd/systemd-socket-proxyd.8.en.html

**WoL / sleep mechanics**
- Linux kernel sleep states — https://docs.kernel.org/admin-guide/pm/sleep-states.html
- ArchWiki Wake-on-LAN — https://wiki.archlinux.org/title/Wake-on-LAN
- ArchWiki Suspend/Hibernate — https://wiki.archlinux.org/title/Power_management/Suspend_and_hibernate
- Microsoft WoL behavior (S3/S4/S5, Fast Startup) — https://learn.microsoft.com/en-us/troubleshoot/windows-client/setup-upgrade-and-drivers/wake-on-lan-feature
- SSH forced-command pattern — https://www.simplified.guide/ssh/restrict-authorized-keys-command

**Sleep-state deep dive (S3 vs S4, the WoL myth, hibernation pitfalls — added in the §2/§11 revision)**
- Microsoft system sleeping states (S4 wakes via "activity on a LAN"; S4 = "trickle current") — https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/system-sleeping-states
- ACPI 6.5 §16 — S4 resume runs full POST (cold-boot-like) — https://uefi.org/specs/ACPI/6.5/16_Waking_and_Sleeping.html
- ErP/EuP cuts NIC standby power (the real WoL determinant) — https://sunbeamtech.com/bios-settings/what-is-erp-in-bios/ · https://forum-en.msi.com/faq/article/printer/wake-on-lan-wol
- NIC powered down on suspend = the classic Linux WoL failure — https://bbs.archlinux.org/viewtopic.php?id=243461
- S3/S4 power draw ("hibernate isn't 0 W", ~4–5 W standby) — https://forums.anandtech.com/threads/how-much-power-consumed-in-both-s3-standby-and-hibernate.1653129/
- suspend-then-hibernate RTC-alarm bug + `rtc_cmos.use_acpi_alarm=1` fix — https://community.frame.work/t/resolved-systemd-suspend-then-hibernate-wakes-up-after-5-minutes/39392 · https://github.com/systemd/systemd/issues/24279
- Real production "server sleeps, WoL wakes" setups — https://www.apalrd.net/posts/2024/pbs_hibernate/ · https://www.xda-developers.com/home-server-goes-to-sleep-when-i-dont-need-it-instantly-wakes-up/ · https://news.ycombinator.com/item?id=34797592

**Hibernation correctness & security (Ubuntu swapfile-on-LVM, S4) — for §11**
- systemd-hibernate-resume: UEFI `HibernateLocation` auto-detect (why the cmdline offset is redundant on systemd ≥255) — https://www.man7.org/linux/man-pages/man8/systemd-hibernate-resume.8.html
- Secure Boot → kernel lockdown disables unencrypted hibernation — https://discourse.ubuntu.com/t/hibernation-deliberately-turned-off-under-secure-boot/81295
- Ubuntu Secure Boot + FDE + TPM + hibernate (the supported-but-involved path) — https://elbrarc.at/blog/2024/05/30/ubuntu-fde-hibernate-tpm-secureboot.html
- Kernel swsusp: image signature check, "don't recreate the swapfile", resume-before-mount — https://docs.kernel.org/power/swsusp.html
- Encrypted swap + hibernate (persistent-key LUKS, not random-key) — https://wiki.archlinux.org/title/Dm-crypt/Swap_encryption · https://www.systemshardening.com/articles/linux/linux-swap-encryption/
- swapfile resume_offset on ext4 (StarLabs Ubuntu guide) — https://support.starlabs.systems/hc/star-labs/articles/ubuntu-enable-hibernate-s4-with-swapfile
- Post-resume timesyncd not re-syncing — https://bugs.launchpad.net/ubuntu/+source/systemd/+bug/1740666

**Unraid**
- Unraid WoL docs — https://docs.unraid.net/unraid-os/system-administration/advanced-tools/wake-on-lan/
- Dynamix S3 Sleep (forum) — https://forums.unraid.net/topic/50357-bergwares-dynamix-s3-sleep/
- Dynamix s3_sleep source — https://github.com/bergware/dynamix/blob/master/source/s3-sleep/scripts/s3_sleep
- Unraid energy efficiency — https://unraid.net/blog/energy-efficient-server

**Media-server idle/session APIs & sleep-on-idle**
- Maximilian Golla — WoL + S3 + Plex (worked, 140-day writeup) — https://maximiliangolla.com/blog/2022-10-wol-plex-server/
- sleep-inhibitor (Plex/Jellyfin plugins) — https://github.com/bulletmark/sleep-inhibitor
- Jellyfin-Inhibit-Sleep — https://github.com/Kwakers01/Jellyfin-Inhibit-Sleep
- Jellyfin "wake server when client starts" (no native wake) — https://forum.jellyfin.org/t-wake-server-when-client-starts
- Jellyfin iOS 503-lockup bug — https://github.com/jellyfin/jellyfin-ios/issues/770
- Plex sessions API — https://www.plexopedia.com/plex-media-server/api/server/sessions/
