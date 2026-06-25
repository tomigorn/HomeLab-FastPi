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
  GET  /          interactive wake page (HTML)
  GET  /status    JSON {"up": true|false}   (TCP-probes beefy)
  POST /wake      fire the WoL magic packet; JSON {"sent": true|false}
  GET  /gate      forwardAuth gate (200 up / 503 + page down); ?host= ?port= override

Config via env (see .env):
  WAKER_LISTEN_PORT  port to listen on (host network)        default 9001
  BEEFY_MAC          MAC to wake                             required
  BEEFY_BROADCAST    broadcast address for the magic packet  default 255.255.255.255
  BEEFY_PROBE_HOST   host to TCP-probe for "is it up"        required
  BEEFY_PROBE_PORT   default probe port                      default 22
  WAKE_COUNTDOWN     page countdown seconds (typical boot)   default 60

Stdlib only; no dependencies.
"""
import json
import os
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LISTEN_PORT = int(os.environ.get("WAKER_LISTEN_PORT", "9001"))
MAC = os.environ.get("BEEFY_MAC", "")
BROADCAST = os.environ.get("BEEFY_BROADCAST", "255.255.255.255")
PROBE_HOST = os.environ.get("BEEFY_PROBE_HOST", "")
PROBE_PORT = int(os.environ.get("BEEFY_PROBE_PORT", "22"))
COUNTDOWN = int(os.environ.get("WAKE_COUNTDOWN", "60"))
SSH_USER = os.environ.get("BEEFY_SSH_USER", "buntu")  # for /history journal fetch
HISTORY_KEY = "/key"            # mounted read-only forced-command key
HISTORY_KNOWN_HOSTS = "/known_hosts"

WAKE_UDP_PORT = 9     # UDP port magic packets are sent to
PROBE_TIMEOUT = 1.0   # seconds per TCP probe

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

# Interactive manual wake page (served at /). __COUNTDOWN__ is replaced at serve time.
WAKE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wake beefy</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:30rem;padding:2rem}
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
  .tl{margin:.9rem 0 0;font-size:.82rem;line-height:1.6;
      max-height:16rem;overflow:auto}
  .tl .up{color:#3fb950}
  .tl .sleep{color:#6e7681;padding-left:.15rem}
  .muted{color:#6e7681}
  .hist a{color:#58a6ff}
</style></head>
<body><div class="card">
  <div id="waiting">
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
<script>
const TOTAL = __COUNTDOWN__;
let left = TOTAL;
const countEl = document.getElementById('count');
const subEl = document.getElementById('sub');

function showUp(){
  document.getElementById('waiting').classList.add('hidden');
  document.getElementById('done').classList.remove('hidden');
  document.title = 'beefy is up';
}
function tick(){
  left -= 1;
  if(left > 0){ countEl.textContent = '~' + left + 's'; }
  else {
    countEl.textContent = 'almost\\u2026';
    subEl.textContent = 'Taking a little longer than usual, still trying\\u2026';
  }
}
async function poll(){
  try{
    const r = await fetch('/status', {cache:'no-store'});
    const j = await r.json();
    if(j.up){ showUp(); return; }
  }catch(e){}
  setTimeout(poll, 3000);
}
// fire the magic packet, then start the clock + polling
fetch('/wake', {method:'POST'}).catch(()=>{});
setInterval(tick, 1000);
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
  if(!Array.isArray(boots) || !boots.length) return '<p class="muted">No history.</p>';
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


def is_up(host, port):
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def _route(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._page()
        elif path == "/status":
            self._status()
        elif path == "/wake":
            self._wake()
        elif path == "/history":
            self._history()
        elif path == "/gate":
            self._gate()
        else:
            self.send_error(404)

    # --- the interactive manual wake page -----------------------------------
    def _page(self):
        body = WAKE_PAGE.replace("__COUNTDOWN__", str(COUNTDOWN)).encode()
        self._send(200, "text/html; charset=utf-8", body)

    def _status(self):
        up = is_up(PROBE_HOST, PROBE_PORT)
        self._send(200, "application/json", json.dumps({"up": up}).encode())

    def _wake(self):
        try:
            send_wol(MAC, BROADCAST)
            self.log_message("manual wake -> sent WoL to %s via %s", MAC, BROADCAST)
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
                self._send(200, "application/json", out.encode())
            else:
                self.log_message("history fetch failed rc=%d: %s",
                                 r.returncode, (r.stderr or "").strip()[:120])
                self._send(503, "application/json",
                           json.dumps({"error": "beefy unreachable"}).encode())
        except Exception as e:
            self._send(503, "application/json",
                       json.dumps({"error": str(e)}).encode())

    # --- the Traefik forwardAuth gate ---------------------------------------
    def _gate(self):
        q = parse_qs(urlparse(self.path).query)
        host = q.get("host", [PROBE_HOST])[0]
        port = int(q.get("port", [str(PROBE_PORT)])[0])
        if is_up(host, port):
            self._send(200, "text/plain", b"")
            return
        try:
            send_wol(MAC, BROADCAST)
            self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                             host, port, MAC, BROADCAST)
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
        self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)

    def _send(self, status, ctype, body, retry_after=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
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
    srv = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print("beefy-waker listening on :%d - page=/ gate=/gate, wake %s via %s, probe %s:%d"
          % (LISTEN_PORT, MAC, BROADCAST, PROBE_HOST, PROBE_PORT), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
