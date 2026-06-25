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
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LISTEN_PORT = int(os.environ.get("WAKER_LISTEN_PORT", "9001"))
MAC = os.environ.get("BEEFY_MAC", "")
BROADCAST = os.environ.get("BEEFY_BROADCAST", "255.255.255.255")
PROBE_HOST = os.environ.get("BEEFY_PROBE_HOST", "")
PROBE_PORT = int(os.environ.get("BEEFY_PROBE_PORT", "22"))
COUNTDOWN = int(os.environ.get("WAKE_COUNTDOWN", "60"))

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
