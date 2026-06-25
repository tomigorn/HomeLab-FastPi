#!/usr/bin/env python3
"""Beefy-Waker — tiny Wake-on-LAN gate for Traefik's forwardAuth.

Traefik calls GET / (forwardAuth) before proxying any beefy-bound route:
  - beefy reachable -> 200, Traefik proxies the request straight through.
  - beefy asleep    -> send a WoL magic packet and return 503 + an
                       auto-refreshing "waking up" page. Each refresh re-probes;
                       once beefy answers, the next call returns 200.

Config via env (see .env):
  WAKER_LISTEN_PORT  port to listen on (host network)        default 9001
  BEEFY_MAC          MAC to wake                             required
  BEEFY_BROADCAST    broadcast address for the magic packet  default 255.255.255.255
  BEEFY_PROBE_HOST   host to TCP-probe for "is it up"        required
  BEEFY_PROBE_PORT   default probe port                      default 22

Per-request overrides via query string:  /?port=8973  (and optional ?host=)
Stdlib only; no dependencies.
"""
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

WAKE_UDP_PORT = 9     # UDP port magic packets are sent to
PROBE_TIMEOUT = 1.0   # seconds per TCP probe

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
        q = parse_qs(urlparse(self.path).query)
        host = q.get("host", [PROBE_HOST])[0]
        port = int(q.get("port", [str(PROBE_PORT)])[0])

        if is_up(host, port):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # Asleep: fire the magic packet and serve the waiting page.
        try:
            send_wol(MAC, BROADCAST)
            self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                             host, port, MAC, BROADCAST)
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
        self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(WAKING_PAGE)))
        self.send_header("Retry-After", "5")
        self.end_headers()
        self.wfile.write(WAKING_PAGE)

    do_POST = do_GET  # forwardAuth uses GET, but accept POST defensively

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
    print("beefy-waker listening on :%d - wake %s via %s, probe %s:%d"
          % (LISTEN_PORT, MAC, BROADCAST, PROBE_HOST, PROBE_PORT), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
