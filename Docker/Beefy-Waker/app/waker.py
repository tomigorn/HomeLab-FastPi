#!/usr/bin/env python3
"""Beefy-Waker — Wake-on-LAN gate + manual LAN wake page for beefy.

Two jobs, one tiny stdlib server on fastpi (host network, :9001):

1. Traefik forwardAuth gate at **/gate** — called before proxying any beefy-bound
   route: beefy up -> 200 (proxy through); beefy asleep -> send a WoL magic packet
   and return 503 + an auto-refreshing "waking up" page.

2. Manual LAN wake page at **/** — open in a browser to wake beefy on demand:
   fires the magic packet, shows a countdown to the typical boot time, and polls
   /status in the background until beefy answers, then shows "up and running".
   Reachable LAN-only (host port, not public) e.g. via a Traefik route
   `https://beefy-wol.fastpi.homelab/`.

Endpoints:
  GET  /          state + manual wake page (HTML); no auto-wake on load
  GET  /wol       same page but auto-fires WoL on load (countdown)
  GET  /status    JSON {"up": true|false}   (TCP-probes beefy)
  POST /wake      fire the WoL magic packet; JSON {"sent": true|false}
  GET  /gate      forwardAuth gate (200 up / 503 + page down); ?port= override
                  ?policy=jellyfin: browsers get a sign-in page instead of a wake; logs "observe {...}"
  GET  /jf/       public booting page (behind Authentik at /beefy-wake/)
  GET  /jf/status JSON {"up": ...} = Jellyfin's /health says Healthy (JELLYFIN_PORT)
  GET  /jf/public-info  relay/cache of Jellyfin's /System/Info/Public (apps' connect check)
  POST /jf/wake   same as /wake

Config via env (see .env):
  WAKER_LISTEN_PORT  port to listen on (host network)        default 9001
  BEEFY_MAC          MAC to wake                             required
  BEEFY_BROADCAST    broadcast address for the magic packet  default 255.255.255.255
  BEEFY_PROBE_HOST   host to TCP-probe for "is it up"        required
  BEEFY_PROBE_PORT   default probe port                      default 22
  JELLYFIN_PORT      Jellyfin port for /jf/status            default 8096
  HOLD_SECONDS       hold app requests up to this (<=25)     default 18
  PUBLIC_INFO_CACHE  cache file for /jf/public-info          default /tmp/public-info.json
  HOLD_SLOTS         concurrent held requests                default 16
  WAKE_COUNTDOWN     page countdown seconds (typical boot)   default 60
  WAKE_RETRY_INTERVAL seconds between magic-packet resends       default 20
  WAKE_RETRY_WINDOW  stop resending after this many seconds   default 300

Stdlib only; no dependencies.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LISTEN_PORT = int(os.environ.get("WAKER_LISTEN_PORT", "9001"))
# Bind address. Default all-interfaces; set WAKER_BIND to the LAN IP so the raw
# port isn't reachable from docker bridges / other interfaces (defence in depth —
# the wake-page route is IP-allowlisted at Traefik, but :9001 itself is not).
BIND = os.environ.get("WAKER_BIND", "0.0.0.0")
MAC = os.environ.get("BEEFY_MAC", "")
BROADCAST = os.environ.get("BEEFY_BROADCAST", "255.255.255.255")
PROBE_HOST = os.environ.get("BEEFY_PROBE_HOST", "")
PROBE_PORT = int(os.environ.get("BEEFY_PROBE_PORT", "22"))
COUNTDOWN = int(os.environ.get("WAKE_COUNTDOWN", "60"))
SSH_USER = os.environ.get("BEEFY_SSH_USER", "buntu")  # for /history journal fetch
HISTORY_KEY = "/key"            # mounted read-only forced-command key
HISTORY_KNOWN_HOSTS = "/known_hosts"
# Only show boots starting at/after this epoch-MICROSECONDS cutoff (0 = show all).
# Set it to "now" to start the history fresh, hiding old experimental boots.
HISTORY_SINCE = int(os.environ.get("BEEFY_HISTORY_SINCE", "0"))

WAKE_UDP_PORT = 9     # UDP port magic packets are sent to

# How the retry campaign behaves. A single packet is not enough — see wake().
WAKE_RETRY_INTERVAL = int(os.environ.get("WAKE_RETRY_INTERVAL", "20"))  # seconds between resends
WAKE_RETRY_WINDOW = int(os.environ.get("WAKE_RETRY_WINDOW", "300"))     # give up after this long
PROBE_TIMEOUT = 1.0   # seconds per TCP probe
# Public URL prefix of the signed-in wake page (Traefik rewrites it to /jf/).
PUBLIC_WAKE_PREFIX = "/beefy-wake"
JELLYFIN_PORT = int(os.environ.get("JELLYFIN_PORT", "8096"))
_CLIENT_RE = re.compile(r'Client="([^"]*)"')


def _read_version():
    """App version from the VERSION file next to this script (bumped per release)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


VERSION = _read_version()

# Simple auto-refresh page returned by the forwardAuth gate (/gate) on a miss.
WAKING_PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>Waking beefy...</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:28rem;padding:2rem}
  .spin{width:3rem;height:3rem;margin:0 auto 1.5rem;border:4px solid #30363d;
        border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  h1{font-size:1.3rem;margin:.5rem 0}
  p{color:#8b949e;margin:.25rem 0}
</style></head>
<body><div class="card">
  <div class="spin"></div>
  <h1>Waking up beefy...</h1>
  <p>A magic packet is on its way. This page refreshes automatically.</p>
  <p>The server should be ready in under a minute.</p>
</div></body></html>"""

# Shown by the gate (policy=jellyfin) to a BROWSER while beefy is asleep. It does
# NOT wake beefy: anonymous page loads were how internet scanners kept booting it.
# The button goes to the Authentik-protected wake page instead.
SIGNIN_PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jellyfin is asleep</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:28rem;padding:2rem}
  .moon{font-size:3rem;line-height:1;margin:0 auto 1rem}
  h1{font-size:1.3rem;margin:.5rem 0}
  p{color:#8b949e;margin:.25rem 0}
  .btn{display:inline-block;text-decoration:none;font-weight:600;font-size:1.2rem;
       padding:.9rem 2.2rem;margin:1.2rem 0 .4rem;border-radius:.7rem;
       background:#238636;color:#fff}
  .btn:hover{background:#2ea043}
</style></head>
<body><div class="card">
  <div class="moon">&#128164;</div>
  <h1>Jellyfin is asleep</h1>
  <p>The media server sleeps to save power.</p>
  <a class="btn" href="/beefy-wake/">Sign in to start it</a>
  <p>It takes about a minute to start after you sign in.</p>
</div></body></html>"""

# Only works behind the /beefy-wake/ rewrite (absolute BASE), not when opened on the LAN directly.
# Public booting page, reached at https://jellyfin.holy-grail.ch/beefy-wake/ AFTER
# an Authentik login (Traefik rewrites /beefy-wake/* to /jf/*). Fires the wake on
# load, counts down, and hands over to Jellyfin as soon as port 8096 answers.
# Deliberately no history panel and no links to the LAN admin page.
JF_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Starting Jellyfin</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:30rem;padding:2rem}
  .spin{width:3.5rem;height:3.5rem;margin:0 auto 1.5rem;border:4px solid #30363d;
        border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  h1{font-size:1.4rem;margin:.4rem 0}
  p{color:#8b949e;margin:.3rem 0}
  .count{font-size:2.6rem;font-variant-numeric:tabular-nums;margin:.4rem 0;color:#58a6ff}
  .ver{margin-top:1.4rem;color:#484f58;font-size:.75rem}
</style></head>
<body><div class="card">
  <div class="spin"></div>
  <h1 id="title">Starting Jellyfin&hellip;</h1>
  <div class="count" id="count">~__COUNTDOWN__s</div>
  <p id="sub">The media server is booting. You will be taken to Jellyfin automatically.</p>
  <a id="retry" href="__BASE__" hidden>Try again</a>
  <div class="ver">v__VERSION__</div>
<script>
const BASE = '__BASE__';
let left = __COUNTDOWN__;
let gaveUp = false;
let ticker = null;
const GIVEUP_MS = __GIVEUP__ * 1000;
const countEl = document.getElementById('count');
const subEl = document.getElementById('sub');
function tick(){
  left -= 1;
  if(left > 0){ countEl.textContent = '~' + left + 's'; }
  else {
    countEl.textContent = 'almost\\u2026';
    subEl.textContent = 'Taking a little longer than usual, still trying\\u2026';
  }
}
async function isUp(){
  try{ return (await (await fetch(BASE + 'status', {cache:'no-store'})).json()).up; }
  catch(e){ return false; }
}
function giveUp(){
  gaveUp = true;
  clearInterval(ticker);
  document.querySelector('.spin').style.display = 'none';
  document.getElementById('title').textContent = "Couldn't start the server";
  countEl.textContent = '';
  subEl.textContent = 'Please try again in a minute.';
  document.getElementById('retry').hidden = false;
}
async function poll(){
  if(gaveUp) return;
  if(await isUp()){
    document.getElementById('title').textContent = 'Jellyfin is ready';
    location.replace('/web/');
    return;
  }
  setTimeout(poll, 2000);
}
(async () => {
  if(await isUp()){ location.replace('/web/'); return; }
  fetch(BASE + 'wake', {method:'POST'}).catch(()=>{});
  ticker = setInterval(tick, 1000);
  setTimeout(giveUp, GIVEUP_MS);
  setTimeout(poll, 2000);
})();
</script>
</div></body></html>"""


# Interactive manual wake page (served at /). __COUNTDOWN__ is replaced at serve time.
WAKE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wake beefy</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;width:min(95vw,80rem);padding:1.5rem}
  /* keep the hero a tidy centered column; the history log uses the full width */
  #checking,#asleep,#waiting,#done{max-width:32rem;margin:0 auto}
  .btn{display:inline-block;border:0;cursor:pointer;font:inherit;font-weight:600;
       font-size:1.35rem;padding:1rem 2.6rem;margin:.9rem 0;border-radius:.7rem;
       background:#238636;color:#fff}
  .btn:hover{background:#2ea043} .btn:active{transform:translateY(1px)}
  .moon{font-size:3rem;line-height:1;margin:0 auto 1rem}
  .spin{width:3.5rem;height:3.5rem;margin:0 auto 1.5rem;border:4px solid #30363d;
        border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite}
  .ok{width:3.5rem;height:3.5rem;margin:0 auto 1.5rem;border-radius:50%;
      background:#1f6f3f;display:flex;align-items:center;justify-content:center;font-size:2rem}
  h1{font-size:1.4rem;margin:.4rem 0}
  p{color:#8b949e;margin:.3rem 0}
  .count{font-size:2.6rem;font-variant-numeric:tabular-nums;margin:.4rem 0;color:#58a6ff}
  .hidden{display:none}
  details.hist{margin-top:2.2rem;text-align:left;border-top:1px solid #21262d;padding-top:1rem}
  summary{cursor:pointer;color:#8b949e;font-size:.95rem;user-select:none}
  .tl{margin:.9rem 0 0;font-size:.85rem;line-height:1.7;
      max-height:60vh;overflow-y:auto}
  .tl .up{color:#3fb950}
  .tl .sleep{color:#6e7681;padding-left:.15rem}
  .muted{color:#6e7681}
  .hist a{color:#58a6ff}
  .ver{margin-top:1.4rem;color:#484f58;font-size:.75rem;letter-spacing:.02em}
</style></head>
<body><div class="card">
  <div id="checking">
    <div class="spin"></div>
    <h1>Checking beefy&hellip;</h1>
    <p>Reading current state&hellip;</p>
  </div>
  <div id="asleep" class="hidden">
    <div class="moon">&#128164;</div>
    <h1>beefy is asleep</h1>
    <p>Send a wake-up packet to start it.</p>
    <button id="wakeBtn" class="btn">Wake beefy</button>
  </div>
  <div id="waiting" class="hidden">
    <div class="spin"></div>
    <h1>Waking up beefy&hellip;</h1>
    <div class="count" id="count">~__COUNTDOWN__s</div>
    <p id="sub">Magic packet sent. Checking when it answers&hellip;</p>
  </div>
  <div id="done" class="hidden">
    <div class="ok">&#10003;</div>
    <h1>beefy is up and running</h1>
    <p>You can reach its services now.</p>
  </div>
  <details class="hist" id="hist"><summary>beefy history</summary><div id="histbody"></div></details>
  <div class="ver">v__VERSION__</div>
<script>
const AUTOWAKE = __AUTOWAKE__;
const TOTAL = __COUNTDOWN__;
let left = TOTAL;
let mode = 'idle';            // 'idle' = live state view, 'waking' = countdown
let countTimer = null;
const countEl = document.getElementById('count');
const subEl = document.getElementById('sub');

function show(id){
  for(const v of ['checking','asleep','waiting','done'])
    document.getElementById(v).classList.toggle('hidden', v !== id);
}
function showUp(){ show('done'); document.title = 'beefy is up'; }
function tick(){
  left -= 1;
  if(left > 0){ countEl.textContent = '~' + left + 's'; }
  else {
    countEl.textContent = 'almost\\u2026';
    subEl.textContent = 'Taking a little longer than usual, still trying\\u2026';
  }
}
function startWaking(){
  mode = 'waking'; left = TOTAL;
  countEl.textContent = '~' + TOTAL + 's';
  subEl.textContent = 'Magic packet sent. Checking when it answers\\u2026';
  show('waiting');
  fetch('/wake', {method:'POST'}).catch(()=>{});
  if(!countTimer) countTimer = setInterval(tick, 1000);
}
async function poll(){
  let up = false;
  try{ up = (await (await fetch('/status', {cache:'no-store'})).json()).up; }
  catch(e){}
  if(up){
    if(countTimer){ clearInterval(countTimer); countTimer = null; }
    mode = 'idle'; showUp();
  } else if(mode === 'idle'){
    show('asleep');
  }
  setTimeout(poll, 3000);
}
document.getElementById('wakeBtn').addEventListener('click', startWaking);
if(AUTOWAKE) startWaking();
poll();

// --- collapsed "beefy history" panel: lazy-fetch on first open ---
const hist = document.getElementById('hist');
let histLoaded = false;
hist.addEventListener('toggle', async () => {
  if(!hist.open || histLoaded) return;
  histLoaded = true;
  const body = document.getElementById('histbody');
  body.innerHTML = '<p class="muted">Loading\\u2026</p>';
  try{
    const r = await fetch('/history', {cache:'no-store'});
    if(!r.ok) throw new Error('unreachable');
    body.innerHTML = renderHist(await r.json());
  }catch(e){
    histLoaded = false; // allow a retry
    body.innerHTML = '<p class="muted">History loads once beefy is awake. '
      + '<a href="#" id="retry">\\u21BB retry</a></p>';
    document.getElementById('retry').onclick = ev => {
      ev.preventDefault(); hist.dispatchEvent(new Event('toggle')); };
  }
});
function fmtDur(ms){
  const s = Math.max(0, Math.round(ms/1000));
  const d = Math.floor(s/86400), h = Math.floor(s%86400/3600), m = Math.floor(s%3600/60);
  if(d) return d+'d '+h+'h'; if(h) return h+'h '+m+'m'; return m+'m';
}
function fmtDate(ms){
  return new Date(ms).toLocaleString([], {month:'short', day:'numeric',
    hour:'2-digit', minute:'2-digit'});
}
function renderHist(boots){
  if(!Array.isArray(boots) || !boots.length) return '<p class="muted">No sessions recorded '
    + 'yet \\u2014 tracking from now on.</p>';
  boots.sort((a,b)=> b.index - a.index); // most recent first
  let html = '<div class="tl">';
  for(let i=0;i<boots.length;i++){
    const start = boots[i].first_entry/1000, end = boots[i].last_entry/1000;
    html += '<div class="up">\\u{1F7E2} ' + fmtDate(start) + ' \\u2192 ' + fmtDate(end)
          + ' <span class="muted">(up ' + fmtDur(end-start) + ')</span></div>';
    const older = boots[i+1];
    if(older){
      const gap = start - older.last_entry/1000;
      if(gap > 0) html += '<div class="sleep">\\u{1F634} asleep ' + fmtDur(gap) + '</div>';
    }
  }
  return html + '</div>';
}
</script>
</div></body></html>"""


def magic_packet(mac):
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        raise ValueError("invalid MAC: %r" % (mac,))
    return b"\xff" * 6 + mac_bytes * 16


def send_wol(mac, broadcast):
    pkt = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, (broadcast, WAKE_UDP_PORT))


# --- wake campaign -------------------------------------------------------
# One magic packet is not enough. A machine that has just been told to power off
# keeps ignoring packets until it actually reaches S5, and that window is both
# long and variable: measured on tower 2026-08-16, three packets across
# 20:54-20:57 UTC did nothing while a fourth at 20:59 woke it instantly — yet an
# earlier cycle the same day woke from the first packet in ~34 s. A fixed
# "wait, then send once" cannot cover a window that moves, so instead we resend
# until the host actually answers.
#
# Without this the failure is silent and expensive: the packet is UDP, nothing
# acknowledges it, and the user just sees a page that never loads.
#
# Runs on a background thread so the HTTP request returns straight away — the
# gate has to serve its 503 "waking up" page without blocking on any of this.
_campaign_lock = threading.Lock()
_campaign_running = False


def _wake_campaign():
    """Resend the magic packet until the host answers or the window expires."""
    global _campaign_running
    try:
        deadline = time.monotonic() + WAKE_RETRY_WINDOW
        while time.monotonic() < deadline:
            time.sleep(WAKE_RETRY_INTERVAL)
            if is_up(PROBE_HOST, PROBE_PORT):
                return
            try:
                send_wol(MAC, BROADCAST)
            except OSError:
                pass          # transient send error — keep trying until the window ends
    finally:
        with _campaign_lock:
            _campaign_running = False


def wake():
    """Send a packet now, then keep resending in the background until it is up.

    Single-flight on purpose: the gate is called for EVERY asset on a page, so
    without the guard one page load would spawn dozens of identical threads.
    monotonic() is used rather than wall-clock so an NTP correction cannot cut
    the window short or extend it forever.
    """
    global _campaign_running
    send_wol(MAC, BROADCAST)          # raises on failure, as the callers expect
    with _campaign_lock:
        if _campaign_running:
            return
        _campaign_running = True
    threading.Thread(target=_wake_campaign, daemon=True).start()


def wake_in_progress():
    with _campaign_lock:
        return _campaign_running


def is_browser_navigation(headers):
    """A browser page load. Browsers send Accept: text/html on navigation;
    Jellyfin API calls send application/json and image loaders image/* or */*."""
    return "text/html" in (headers.get("Accept") or "").lower()


def is_browser_subresource(headers):
    """A browser fetching a page's own assets (favicon, css, js, images, fonts).

    Browsers label these with Sec-Fetch-Dest; native Jellyfin apps send no
    Sec-Fetch-* headers at all. "document" is a navigation (handled above) and
    "empty" is a fetch/XMLHttpRequest API call, which keeps the app rule.
    Found 2026-10-14: the sign-in page's favicon request woke beefy.
    """
    dest = (headers.get("Sec-Fetch-Dest") or "").strip().lower()
    return bool(dest) and dest not in ("document", "empty")


def _forwarded_path_query(headers):
    """(path, query) of the original request; urlparse mangles a leading '//'."""
    raw = headers.get("X-Forwarded-Uri") or "/"
    raw = raw.split("#", 1)[0]
    path, _, query = raw.partition("?")
    return path, query


def _query_keys(query):
    try:
        keys = parse_qs(query, keep_blank_values=True, max_num_fields=50)
    except ValueError:
        return ["<too many>"]
    return [k[:40] for k in sorted(keys)[:20]]


def _client_ip(headers):
    for name in ("CF-Connecting-IP", "X-Real-Ip"):
        v = (headers.get(name) or "").strip()
        if v:
            return v[:45]
    return (headers.get("X-Forwarded-For") or "").split(",")[0].strip()[:45]


def is_mediabrowser_client(headers):
    """Native Jellyfin apps always send Authorization: MediaBrowser ...;
    jellyfin-web's connect check sends no Authorization header."""
    return (headers.get("Authorization") or "").strip().lower().startswith("mediabrowser")


def observe_record(headers, up, decision):
    """Redacted fingerprint of a Jellyfin request, used to design the app rule.

    Never includes a token or a query VALUE: the MediaBrowser header carries
    Token="...", and api_key/ApiKey query values are tokens.
    """
    fwd_path, fwd_query = _forwarded_path_query(headers)
    auth = headers.get("Authorization") or ""
    mb = is_mediabrowser_client(headers)
    emby_auth = headers.get("X-Emby-Authorization") or ""
    m = _CLIENT_RE.search(auth if mb else emby_auth)
    return {
        "up": up,
        "decision": decision,
        "method": headers.get("X-Forwarded-Method") or "",
        "path": fwd_path[:200],
        "query_keys": _query_keys(fwd_query),
        "auth_mediabrowser": mb,
        "x_emby_authorization": bool(emby_auth),
        "x_emby_token": bool(headers.get("X-Emby-Token")),
        "x_mediabrowser_token": bool(headers.get("X-MediaBrowser-Token")),
        "client": m.group(1)[:40] if m else "",
        "ua": (headers.get("User-Agent") or "")[:160],
        "accept": (headers.get("Accept") or "")[:80],
        "sec_fetch_mode": (headers.get("Sec-Fetch-Mode") or "")[:20],
        "sec_fetch_dest": (headers.get("Sec-Fetch-Dest") or "")[:20],
        "ip": _client_ip(headers),
    }


def is_up(host, port):
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


# Jellyfin readiness. The port opens ~5 s before Jellyfin can serve (measured
# 2026-10-13: 200 with a non-API page, then Jellyfin's own 503), so the gate asks
# Jellyfin's /health instead. The gate runs for EVERY Jellyfin request - each
# chunk of a video stream - so a healthy answer is reused for a few seconds
# rather than hitting /health each time. Unhealthy answers are never cached, so
# the moment Jellyfin is ready after a boot is seen straight away.
READY_CACHE_SECONDS = 5.0
_ready_lock = threading.Lock()
_ready_until = 0.0


def is_jellyfin_ready(host, port):
    global _ready_until
    with _ready_lock:
        if time.monotonic() < _ready_until:
            return True
    try:
        with urllib.request.urlopen("http://%s:%d/health" % (host, port),
                                    timeout=PROBE_TIMEOUT) as r:
            ready = r.status == 200 and r.read(64).strip() == b"Healthy"
    except Exception:    # refused, timeout, HTTP error (503), bad URL, anything odd
        ready = False
    if ready:
        with _ready_lock:
            _ready_until = time.monotonic() + READY_CACHE_SECONDS
    return ready


# Hold a Jellyfin app's request while beefy boots instead of answering 503 at
# once. Client timeouts: jellyfin-web's connect check 20 s, the Android TV app
# 30 s, Traefik's forwardAuth client a fixed 30 s. 18 s of hold plus one final
# 1 s probe stays under 20 s. A cold boot takes ~50 s, so the design is
# "stages": each request the app makes is held just under its timeout, and the
# chain of requests (the app retries) spans the boot. Browsers are never held.
def _clamp_hold_seconds(value):
    """0..25 (Traefik's forwardAuth limit is a fixed 30 s); 18 on bad input."""
    try:
        return max(0.0, min(float(value), 25.0))
    except (TypeError, ValueError):
        return 18.0


def _clamp_hold_slots(value):
    """At least 1; 16 on bad input."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 16


HOLD_SECONDS = _clamp_hold_seconds(os.environ.get("HOLD_SECONDS", "18"))
HOLD_SLOTS = _clamp_hold_slots(os.environ.get("HOLD_SLOTS", "16"))   # concurrent held requests
HOLD_POLL_SECONDS = 1.0
_hold_slots = threading.BoundedSemaphore(HOLD_SLOTS)


def hold_until_ready(host, port, limit, started=None):
    """Wait for Jellyfin to be healthy until `started + limit` (default: now).
    Returns (ready, seconds_held). `started` is the request's arrival time, so
    probes made before the hold count against the limit and the whole request
    never exceeds it (the last probe may take PROBE_TIMEOUT).

    Non-blocking on the slot: with every slot busy (scanners while beefy sleeps)
    the caller falls back to answering immediately.
    """
    if not _hold_slots.acquire(blocking=False):
        return False, 0.0
    t0 = time.monotonic()
    deadline = (started if started is not None else t0) + limit
    try:
        while True:
            if is_jellyfin_ready(host, port):
                return True, time.monotonic() - t0
            remaining = deadline - time.monotonic()
            if remaining <= PROBE_TIMEOUT:
                return False, time.monotonic() - t0
            time.sleep(min(HOLD_POLL_SECONDS, remaining - PROBE_TIMEOUT))
    finally:
        _hold_slots.release()


# Cached answer to Jellyfin's `GET /System/Info/Public`, the first thing every
# app asks. Served while beefy sleeps so the app believes the server is there and
# shows its own loading state instead of "server unavailable". Memory + a file so
# a `docker restart` while beefy sleeps keeps it (not a recreate: /tmp is the
# container's own layer). Only 200 answers are cached.
PUBLIC_INFO_CACHE = os.environ.get("PUBLIC_INFO_CACHE", "/tmp/public-info.json")
_public_info = None
_public_info_lock = threading.Lock()


def _load_public_info():
    global _public_info
    try:
        with open(PUBLIC_INFO_CACHE, "rb") as f:
            data = f.read()
        json.loads(data)                      # must be valid JSON
        with _public_info_lock:
            _public_info = data
    except (OSError, ValueError):
        pass


def _store_public_info(data):
    global _public_info
    with _public_info_lock:
        if data == _public_info:
            return
        _public_info = data
    try:
        tmp = PUBLIC_INFO_CACHE + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, PUBLIC_INFO_CACHE)
    except OSError:
        pass


def fetch_public_info(host, port, timeout=3.0):
    """Relay Jellyfin's /System/Info/Public; returns bytes or None.

    Only a 200 whose body (<= 64 KiB) is a JSON object with an "Id" is cached.
    Catches Exception: http.client.HTTPException is not an OSError.
    """
    try:
        with urllib.request.urlopen("http://%s:%d/System/Info/Public" % (host, port),
                                    timeout=timeout) as r:
            data = r.read(65537)
            if r.status == 200 and len(data) <= 65536:
                obj = json.loads(data)
                if isinstance(obj, dict) and "Id" in obj:
                    _store_public_info(data)
                    return data
    except Exception:
        pass
    return None


def jellyfin_decision(up, headers):
    if up:
        return "pass"
    if wake_in_progress() or is_up(PROBE_HOST, PROBE_PORT):
        return "starting"
    if is_browser_navigation(headers) or is_browser_subresource(headers):
        return "signin"
    return "wake"


class Handler(BaseHTTPRequestHandler):
    timeout = 10        # per-request socket timeout: drop slow/never-finishing
                        # clients so they can't pin a worker thread (the server is
                        # threading + memory-capped, so unbounded slow clients
                        # would otherwise risk thread/OOM exhaustion under load).

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def _route(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._page(autowake=False)
        elif path == "/wol":
            self._page(autowake=True)
        elif path == "/status":
            self._status()
        elif path == "/wake":
            self._wake()
        elif path == "/history":
            self._history()
        elif path == "/gate":
            self._gate()
        elif path == "/jf":
            self._jf_page()
        elif path == "/jf/status":
            up = is_jellyfin_ready(PROBE_HOST, JELLYFIN_PORT)
            self._send(200, "application/json", json.dumps({"up": up}).encode())
        elif path == "/jf/wake":
            self._jf_wake()
        elif path == "/jf/public-info":
            self._jf_public_info()
        else:
            self.send_error(404)

    # --- the interactive manual wake page -----------------------------------
    def _jf_page(self):
        body = (JF_PAGE
                .replace("__COUNTDOWN__", str(COUNTDOWN))
                .replace("__VERSION__", VERSION)
                .replace("__GIVEUP__", str(WAKE_RETRY_WINDOW + 60))
                .replace("__BASE__", PUBLIC_WAKE_PREFIX + "/")
                .encode())
        self._send(200, "text/html; charset=utf-8", body)

    def _jf_public_info(self):
        # GET /System/Info/Public on the Jellyfin hostname is routed here (Traefik
        # replacePathRegex). Healthy: relay + cache. Down: same decision as the
        # gate; apps are held (bounded) then get the cached identity, browsers sign-in.
        started = time.monotonic()
        up = is_jellyfin_ready(PROBE_HOST, JELLYFIN_PORT)
        decision = jellyfin_decision(up, self.headers)
        held, cached, body = 0.0, False, None
        browser = is_browser_navigation(self.headers) or is_browser_subresource(self.headers)

        def relay():
            budget = max(0.5, min(3.0, started + HOLD_SECONDS - time.monotonic()))
            return fetch_public_info(PROBE_HOST, JELLYFIN_PORT, timeout=budget)

        def cache():
            # Only native apps get the cached identity: jellyfin-web logs the user
            # out when its follow-up authenticated call fails after a "successful"
            # connect check, so for it "unavailable" is the safer answer.
            if not is_mediabrowser_client(self.headers):
                return None
            with _public_info_lock:
                return _public_info

        if decision == "pass":
            body = relay()
            if body is None:
                body = cache()
                cached = body is not None
        elif decision != "signin":
            if decision == "wake":
                try:
                    wake()
                    self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                                     PROBE_HOST, JELLYFIN_PORT, MAC, BROADCAST)
                except Exception as e:
                    self.log_message("WoL send failed: %s", e)
            # hold first (bounded), then relay if healthy, else serve the cache
            ready = False
            if decision == "wake" or not browser:     # browsers are never held
                ready, held = hold_until_ready(PROBE_HOST, JELLYFIN_PORT, HOLD_SECONDS, started)
            if ready:
                body = relay()
            if body is None:
                body = cache()
                cached = body is not None
        rec = observe_record(self.headers, up, decision)
        rec["path"] = "/System/Info/Public"     # proxied, not forwardAuth'd: no X-Forwarded-*
        rec["method"] = self.command
        rec["query_keys"] = _query_keys(urlparse(self.path).query)
        rec["held"] = round(held, 1)
        rec["cached"] = cached
        self.log_message("observe %s", json.dumps(rec, sort_keys=True))
        if decision == "signin":
            self._send(503, "text/html; charset=utf-8", SIGNIN_PAGE)
        elif body is not None:
            self._send(200, "application/json", body, cors=True)
        else:
            self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)

    def _page(self, autowake):
        body = (WAKE_PAGE
                .replace("__COUNTDOWN__", str(COUNTDOWN))
                .replace("__AUTOWAKE__", "true" if autowake else "false")
                .replace("__VERSION__", VERSION)
                .encode())
        self._send(200, "text/html; charset=utf-8", body)

    def _status(self):
        up = is_up(PROBE_HOST, PROBE_PORT)
        self._send(200, "application/json", json.dumps({"up": up}).encode())

    def _wake(self):
        if self.command != "POST":   # POST-only: avoid drive-by GET/<img> wakes
            self._send(405, "application/json",
                       json.dumps({"error": "POST only"}).encode())
            return
        try:
            wake()
            self.log_message("manual wake -> sent WoL to %s via %s", MAC, BROADCAST)
            sent = True
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
            sent = False
        self._send(200, "application/json", json.dumps({"sent": sent}).encode())

    def _jf_wake(self):
        # Public (Authentik-fronted) wake: same as _wake but attributed to the user.
        if self.command != "POST":
            self._send(405, "application/json",
                       json.dumps({"error": "POST only"}).encode())
            return
        user = (self.headers.get("X-Authentik-Username") or "?")[:64]
        try:
            wake()
            self.log_message("jf wake by %s -> sent WoL to %s via %s", user, MAC, BROADCAST)
            sent = True
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
            sent = False
        self._send(200, "application/json", json.dumps({"sent": sent}).encode())

    def _history(self):
        # Fetch beefy's boot/sleep history via the read-only forced-command key.
        # The forced command (in beefy's authorized_keys) only ever returns
        # `journalctl --list-boots -o json`; whatever we "ask" is ignored.
        if not (os.path.exists(HISTORY_KEY) and os.path.exists(HISTORY_KNOWN_HOSTS)):
            self._send(503, "application/json",
                       json.dumps({"error": "history key not installed"}).encode())
            return
        try:
            r = subprocess.run(
                ["ssh", "-T", "-i", HISTORY_KEY, "-o", "BatchMode=yes",
                 "-o", "StrictHostKeyChecking=yes",
                 "-o", "UserKnownHostsFile=" + HISTORY_KNOWN_HOSTS,
                 "-o", "ConnectTimeout=4",
                 "%s@%s" % (SSH_USER, PROBE_HOST)],
                capture_output=True, text=True, timeout=12)
            out = r.stdout.strip()
            if r.returncode == 0 and out.startswith("["):
                boots = json.loads(out)
                if not isinstance(boots, list):
                    raise ValueError("unexpected history payload")
                if HISTORY_SINCE:  # drop boots that started before the cutoff
                    boots = [b for b in boots if isinstance(b, dict)
                             and b.get("first_entry", 0) >= HISTORY_SINCE]
                self._send(200, "application/json", json.dumps(boots).encode())
            else:
                self.log_message("history fetch failed rc=%d: %s",
                                 r.returncode, (r.stderr or "").strip()[:120])
                self._send(503, "application/json",
                           json.dumps({"error": "beefy unreachable"}).encode())
        except Exception as e:
            self.log_message("history error: %s", e)   # don't leak details to client
            self._send(503, "application/json",
                       json.dumps({"error": "history unavailable"}).encode())

    # --- the Traefik forwardAuth gate ---------------------------------------
    def _gate(self):
        # host is hard-wired to beefy. `?port=` lets a sibling middleware probe a
        # specific beefy service port for precise readiness; it is range-checked and
        # falls back to the default on bad input. We intentionally do NOT honour a
        # `?host=` override (it would turn this LAN-reachable endpoint into an
        # arbitrary-host TCP-probe oracle), and a malformed `?port=` must not crash
        # this forwardAuth handler.
        self._started = time.monotonic()
        q = parse_qs(urlparse(self.path).query)
        try:
            port = int(q.get("port", [str(PROBE_PORT)])[0])
            if not (1 <= port <= 65535):
                raise ValueError(port)
        except (ValueError, TypeError):
            port = PROBE_PORT
        if q.get("policy", [""])[0] == "jellyfin":
            self._gate_jellyfin(is_jellyfin_ready(PROBE_HOST, port), port)
            return
        up = is_up(PROBE_HOST, port)
        if up:
            self._send(200, "text/plain", b"")
            return
        self._wake_and_wait_page(port)

    def _wake_and_wait_page(self, port):
        try:
            wake()
            self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                             PROBE_HOST, port, MAC, BROADCAST)
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
        self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)

    def _gate_jellyfin(self, up, port):
        # Jellyfin has no Authentik in front (native apps can't follow a login
        # redirect), so this is the only place anonymous wakes can be refused.
        # Browsers are refused and sent to the signed-in wake page; everything
        # else still wakes (until the observe log shows a safe rule for apps),
        # and is then HELD until Jellyfin is healthy (bounded) so the app sees a
        # slow server rather than an instant failure.
        decision = jellyfin_decision(up, self.headers)
        outcome = decision
        held = 0.0
        started = getattr(self, "_started", time.monotonic())
        if decision == "wake":
            try:
                wake()
                self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                                 PROBE_HOST, port, MAC, BROADCAST)
            except Exception as e:
                self.log_message("WoL send failed: %s", e)
        if decision == "wake" or (decision == "starting" and not (
                is_browser_navigation(self.headers) or is_browser_subresource(self.headers))):
            ready, held = hold_until_ready(PROBE_HOST, port, HOLD_SECONDS, started)
            if ready:
                outcome = "pass"      # logged decision stays wake/starting
        fwd_path, _ = _forwarded_path_query(self.headers)
        if not up or "/" + fwd_path.lstrip("/").lower() == "/system/info/public":
            rec = observe_record(self.headers, up, decision)
            rec["held"] = round(held, 1)
            self.log_message("observe %s", json.dumps(rec, sort_keys=True))
        if outcome == "pass":
            self._send(200, "text/plain", b"")
        elif outcome == "signin":
            self._send(503, "text/html; charset=utf-8", SIGNIN_PAGE)
        else:
            self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)

    def _send(self, status, ctype, body, retry_after=None, cors=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")   # as Jellyfin sends
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    missing = [k for k, v in (("BEEFY_MAC", MAC),
                              ("BEEFY_PROBE_HOST", PROBE_HOST)) if not v]
    if missing:
        sys.exit("missing required env: %s" % ", ".join(missing))
    magic_packet(MAC)  # validate MAC format at startup
    _load_public_info()
    srv = ThreadingHTTPServer((BIND, LISTEN_PORT), Handler)
    print("beefy-waker listening on %s:%d - page=/ gate=/gate, wake %s via %s, probe %s:%d"
          % (BIND, LISTEN_PORT, MAC, BROADCAST, PROBE_HOST, PROBE_PORT), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
