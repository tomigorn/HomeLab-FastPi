#!/usr/bin/env python3
import json
import os
import http.server
import socketserver
import threading
import time
import urllib.request
import urllib.error

DATA_FILE = "/data/port-history.json"
PORT = int(os.getenv("WEB_PORT", "8088"))

_real_ip_cache: dict = {"ip": None, "ts": 0.0}
_real_ip_lock = threading.Lock()


def _fetch_real_ip() -> str | None:
    try:
        req = urllib.request.Request(
            "https://api.ipify.org",
            headers={"User-Agent": "port-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def get_real_ip() -> str:
    with _real_ip_lock:
        now = time.monotonic()
        if _real_ip_cache["ip"] is None or now - _real_ip_cache["ts"] > 600:
            ip = _fetch_real_ip()
            if ip:
                _real_ip_cache["ip"] = ip
                _real_ip_cache["ts"] = now
        return _real_ip_cache["ip"] or "unknown"


def get_latest_vpn_ip() -> str | None:
    for event in reversed(load_history()):
        vpn_ip = event.get("vpn_ip", "")
        if vpn_ip:
            return vpn_ip
    return None

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Port Updater</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; padding: 2rem; }
    h1 { font-size: 1.8rem; font-weight: 700; color: #7dd3fc; margin-bottom: 0.25rem; }
    .subtitle { color: #64748b; font-size: 0.875rem; margin-bottom: 2rem; }
    .cards { display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }
    .card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; padding: 1.25rem 1.5rem; min-width: 170px; flex: 1; }
    .card-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 0.5rem; }
    .card-value { font-size: 1.5rem; font-weight: 700; }
    .green  { color: #4ade80; }
    .yellow { color: #facc15; }
    .red    { color: #f87171; }
    .muted  { color: #94a3b8; }
    .section-title { font-size: 0.8rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.75rem; }
    table { width: 100%; border-collapse: collapse; background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; overflow: hidden; }
    thead th { background: #111827; color: #64748b; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.08em; padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #2d3748; }
    tbody tr:not(:last-child) { border-bottom: 1px solid #1e2536; }
    tbody tr:hover { background: #1e2a3a; }
    td { padding: 0.7rem 1rem; font-size: 0.875rem; vertical-align: middle; }
    .badge { display: inline-flex; align-items: center; padding: 0.2rem 0.65rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.03em; white-space: nowrap; }
    .badge-port_update   { background: #172554; color: #93c5fd; }
    .badge-stack_restart { background: #431407; color: #fdba74; }
    .badge-zero_port     { background: #450a0a; color: #fca5a5; }
    .badge-startup       { background: #1c2334; color: #94a3b8; }
    .port-val { font-family: 'Courier New', monospace; font-size: 0.95rem; }
    .empty-row td { text-align: center; color: #334155; padding: 3rem 0; font-size: 0.875rem; }
    .footer { margin-top: 1rem; color: #334155; font-size: 0.75rem; text-align: right; }
    #status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #4ade80; margin-right: 8px; vertical-align: middle; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
    .ts { color: #475569; white-space: nowrap; font-size: 0.8rem; }
    .msg { color: #4b5563; font-size: 0.8rem; max-width: 300px; }
    .num { color: #2d3748; }
    .card-value.ip { font-size: 1.05rem; font-family: 'Courier New', monospace; }
    .uptime { color: #a78bfa; font-size: 0.82rem; white-space: nowrap; }
    .uptime-dash { color: #2d3748; }
  </style>
</head>
<body>
  <h1><span id="status-dot"></span>Port Updater</h1>
  <p class="subtitle">ProtonVPN &rarr; qBittorrent port forwarding monitor</p>

  <div class="cards">
    <div class="card">
      <div class="card-label">Current Port</div>
      <div class="card-value green port-val" id="current-port">—</div>
    </div>
    <div class="card">
      <div class="card-label">VPN IP</div>
      <div class="card-value green ip" id="vpn-ip-card">—</div>
    </div>
    <div class="card">
      <div class="card-label">Real IP</div>
      <div class="card-value muted ip" id="real-ip-card">—</div>
    </div>
    <div class="card">
      <div class="card-label">Time Since Last Update</div>
      <div class="card-value yellow" id="last-update-ago">—</div>
    </div>
    <div class="card">
      <div class="card-label">Total Port Updates</div>
      <div class="card-value muted" id="total-updates">—</div>
    </div>
    <div class="card">
      <div class="card-label">Stack Restarts</div>
      <div class="card-value muted" id="total-restarts">—</div>
    </div>
  </div>

  <p class="section-title">Event History</p>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Event</th>
        <th>Timestamp</th>
        <th>New Port</th>
        <th>Old Port</th>
        <th>Port Uptime</th>
        <th>VPN IP</th>
        <th>Message</th>
      </tr>
    </thead>
    <tbody id="history-body">
      <tr class="empty-row"><td colspan="8">Loading&hellip;</td></tr>
    </tbody>
  </table>
  <p class="footer" id="footer"></p>

  <script>
    let lastUpdateTs = null;

    function fmtDuration(ms) {
      if (ms < 0) return '—';
      const s = Math.floor(ms / 1000);
      if (s < 60)    return s + 's';
      if (s < 3600)  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
      if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
      return Math.floor(s / 86400) + 'd ' + Math.floor((s % 86400) / 3600) + 'h';
    }

    function fmtTimeSince(ts) {
      if (!ts) return 'never';
      const delta = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
      if (delta < 0) return 'just now';
      if (delta < 60) return delta + 's ago';
      if (delta < 3600) return Math.floor(delta / 60) + 'm ' + (delta % 60) + 's ago';
      if (delta < 86400) return Math.floor(delta / 3600) + 'h ' + Math.floor((delta % 3600) / 60) + 'm ago';
      return Math.floor(delta / 86400) + 'd ' + Math.floor((delta % 86400) / 3600) + 'h ago';
    }

    function badgeClass(event)  { return 'badge badge-' + (event || 'startup'); }
    function badgeLabel(event) {
      return { port_update: 'port update', stack_restart: 'stack restart', zero_port: 'zero port', startup: 'startup' }[event] || event;
    }

    function portCell(val) {
      return (val !== undefined && val !== 0 && val !== null)
        ? `<span class="port-val">${val}</span>`
        : `<span style="color:#2d3748">—</span>`;
    }

    function ipCell(val) {
      return (val && val !== '')
        ? `<span class="port-val">${val}</span>`
        : `<span style="color:#2d3748">—</span>`;
    }

    function render(history) {
      const rev = [...history].reverse();
      const lastUpdate = rev.find(e => e.event === 'port_update');
      lastUpdateTs = lastUpdate ? lastUpdate.timestamp : null;

      document.getElementById('current-port').textContent = lastUpdate ? lastUpdate.port : '—';
      document.getElementById('last-update-ago').textContent = fmtTimeSince(lastUpdateTs);
      document.getElementById('total-updates').textContent = history.filter(e => e.event === 'port_update').length;

      const restarts = history.filter(e => e.event === 'stack_restart').length;
      const el = document.getElementById('total-restarts');
      el.textContent = restarts;
      el.className = 'card-value ' + (restarts > 0 ? 'red' : 'muted');

      // Build uptime map: for each port_update (except the first and the most recent),
      // compute how long the PREVIOUS port was active.
      const portUpdates = history
        .map((e, idx) => ({ idx, ts: e.timestamp, event: e.event }))
        .filter(e => e.event === 'port_update');
      const uptimeMap = {};
      // portUpdates[0] = first ever (no predecessor → no uptime)
      // portUpdates[last] = current active port → no uptime (live counter shows it)
      for (let i = 1; i < portUpdates.length - 1; i++) {
        const ms = new Date(portUpdates[i].ts) - new Date(portUpdates[i - 1].ts);
        uptimeMap[portUpdates[i].idx] = fmtDuration(ms);
      }

      const tbody = document.getElementById('history-body');
      if (!rev.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="8">No events recorded yet</td></tr>';
        return;
      }
      tbody.innerHTML = rev.map((e, i) => {
        const num = history.length - i;
        const histIdx = history.length - 1 - i;
        const uptime = uptimeMap[histIdx];
        const uptimeCell = uptime
          ? `<span class="uptime">${uptime}</span>`
          : `<span class="uptime-dash">—</span>`;
        return `<tr>
          <td class="num">${num}</td>
          <td><span class="${badgeClass(e.event)}">${badgeLabel(e.event)}</span></td>
          <td class="ts">${e.timestamp || ''}</td>
          <td>${portCell(e.port)}</td>
          <td>${portCell(e.old_port)}</td>
          <td>${uptimeCell}</td>
          <td>${ipCell(e.vpn_ip)}</td>
          <td class="msg">${e.message || ''}</td>
        </tr>`;
      }).join('');
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const s = await res.json();
        document.getElementById('vpn-ip-card').textContent = s.vpn_ip || '—';
        document.getElementById('real-ip-card').textContent = s.real_ip || '—';
      } catch (err) {}
    }

    async function fetchData() {
      try {
        const res = await fetch('/api/history');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        render(await res.json());
        document.getElementById('footer').textContent = 'Last synced: ' + new Date().toLocaleTimeString();
      } catch (err) {
        document.getElementById('footer').textContent = 'Error fetching data: ' + err.message;
      }
    }

    fetchData();
    fetchStatus();
    setInterval(fetchData, 30000);
    setInterval(fetchStatus, 60000);
    setInterval(() => {
      if (lastUpdateTs) {
        document.getElementById('last-update-ago').textContent = fmtTimeSince(lastUpdateTs);
      }
    }, 1000);
  </script>
</body>
</html>"""


def load_history():
    if not os.path.exists(DATA_FILE):
        return []
    events = []
    try:
        with open(DATA_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return events


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress per-request access logs

    def do_GET(self):
        if self.path == "/api/history":
            data = json.dumps(load_history()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/status":
            data = json.dumps({
                "real_ip": get_real_ip(),
                "vpn_ip": get_latest_vpn_ip(),
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


threading.Thread(target=get_real_ip, daemon=True).start()
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"[web-server] Listening on port {PORT}", flush=True)
    httpd.serve_forever()
