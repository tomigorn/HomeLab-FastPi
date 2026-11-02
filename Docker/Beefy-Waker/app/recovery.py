"""Wake recovery for Beefy-Waker: power-cycle beefy's plug when a signed-in wake fails, then alarm.

Phases: idle, waking, power_cycle, retrying, broken. One campaign at a time.
All I/O (probe, plug, alert, metrics) runs outside the state lock; step() is the only mover.
"""
import json
import os
import sys
import threading
import time
import urllib.request

PHASES = ("idle", "waking", "power_cycle", "retrying", "broken")
REASONS = ("no_boot", "service_down", "plug_off", "plug_unreachable")
REASON_TEXT = {
    "no_boot": "beefy did not boot after a power cycle",
    "service_down": "beefy is on but the requested service does not answer",
    "plug_off": "the beefy plug is switched off (left alone on purpose)",
    "plug_unreachable": "the beefy plug does not answer or did not switch",
}


class MyStromPlug:
    def __init__(self, base_url, timeout=3.0, sleep=time.sleep):
        self.base, self.timeout, self.sleep = base_url.rstrip("/"), timeout, sleep

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def _report(self, key):
        try:
            return self._get("/report").get(key)
        except Exception:
            return None

    def relay(self):
        v = self._report("relay")
        return v if isinstance(v, bool) else None

    def power(self):
        v = self._report("power")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def set(self, on):
        try:
            self._get(f"/relay?state={1 if on else 0}")
        except Exception:
            return False
        for i in range(3):
            if i:
                self.sleep(1)
            if self.relay() is on:
                return True
        return False


def post_alert(url, alertname, severity, summary, details, description, wall=time.time):
    try:
        now = wall()
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        body = json.dumps([{
            "labels": {"alertname": alertname, "host": "beefy", "severity": severity, "source": "beefy-waker",
                       "at": time.strftime("%Y%m%d%H%M%S", time.localtime(now))},
            "annotations": {"summary": summary, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                            "details": details, "description": description},
            "startsAt": iso(now), "endsAt": iso(now + 3600)}]).encode()
        req = urllib.request.Request(url.rstrip("/") + "/api/v2/alerts", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def write_textfile(path, snapshot):
    try:
        out = []

        def metric(name, kind, help_, rows):
            out.append(f"# HELP beefy_wake_{name} {help_}\n# TYPE beefy_wake_{name} {kind}")
            out.extend(f"beefy_wake_{name}{labels} {value}" for labels, value in rows)

        metric("phase", "gauge", "Current wake recovery phase (1 = active).",
               [(f'{{phase="{p}"}}', int(snapshot["phase"] == p)) for p in PHASES])
        metric("campaigns_total", "counter", "Wake campaigns started.",
               [(f'{{signed_in="{k}"}}', snapshot["campaigns"].get(k, 0)) for k in ("0", "1")])
        metric("power_cycles_total", "counter", "Plug power-cycles done.", [("", snapshot["power_cycles"])])
        metric("failures_total", "counter", "Times the broken phase was reached.",
               [(f'{{reason="{r}"}}', snapshot["failures"].get(r, 0)) for r in REASONS])
        metric("recoveries_total", "counter", "Times beefy came back after a power cycle or broken.",
               [(f'{{after="{a}"}}', snapshot["recoveries"].get(a, 0)) for a in ("power_cycle", "broken")])
        metric("last_event_timestamp_seconds", "gauge", "Unix time of the last event.",
               [(f'{{event="{e}"}}', t) for e, t in sorted(snapshot["last"].items())])
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    except Exception as e:
        print(f"textfile write failed: {e!r}", file=sys.stderr, flush=True)


class Recovery:
    def __init__(self, probe, send_wol, plug, alert, write_metrics, clock=time.monotonic, wall=time.time,
                 host_port=22, t1=120, off_seconds=15, settle=5, t2=150, service_wait=300,
                 resend=20, window=300, latch=21600, watch_interval=30, probe_interval=5):
        self.probe, self.send_wol, self.plug = probe, send_wol, plug
        self.alert, self.write_metrics = alert, write_metrics
        self.clock, self.wall, self.host_port = clock, wall, host_port
        self.t1, self.off_seconds, self.settle, self.t2 = t1, off_seconds, settle, t2
        self.service_wait, self.resend, self.window = service_wait, resend, window
        self.latch, self.watch_interval, self.probe_interval = latch, watch_interval, probe_interval
        self._lock = threading.Lock()
        self._step_lock = threading.Lock()
        self.phase = "idle"
        self.reason = ""
        self.campaigns = {"0": 0, "1": 0}
        self.power_cycles = 0
        self.failures = {r: 0 for r in REASONS}
        self.recoveries = {"power_cycle": 0, "broken": 0}
        self.last = {}
        self.last_cycle_t = None
        self._reset_campaign()

    def _reset_campaign(self):
        self.ports = {}
        self.armed = False
        self.user = self.service = ""
        self.start_t = self.last_wol = self.last_watch = 0.0
        self.host_up = False
        self.sub = ""
        self.off_t = self.on_t = self.t2_deadline = self.broken_t = 0.0
        self.probe_t = float('-inf')
        self.svc_ok = False

    def start(self, port, signed_in, user="", service=""):
        now = self.clock()
        self.send_wol()
        new = False
        with self._lock:
            if self.phase == "idle":
                self._reset_campaign()
                self.phase, self.reason = "waking", ""
                self.start_t = now
                self.campaigns["1" if signed_in else "0"] += 1
                self.last["campaign"] = self.wall()
                new = True
            if self.phase != "broken":
                self.last_wol = now
                self.ports[port] = self.ports.get(port, False) or signed_in
                if signed_in:
                    self.armed = True
                    self.user = self.user or user
                    self.service = self.service or service
        if new:
            self._emit()

    def status(self):
        now = self.clock()
        with self._lock:
            left = None
            if self.phase == "waking" and self.armed and not self.host_up:
                left = self.start_t + self.t1 - now
            elif self.phase == "waking" and self.armed and self.host_up:
                left = self.start_t + self.service_wait - now
            elif self.phase == "power_cycle" and self.sub == "off":
                left = self.off_t + self.off_seconds + self.t2 - now
            elif self.phase == "power_cycle" or self.phase == "retrying":
                left = self.t2_deadline - now
            return {"phase": self.phase, "seconds_left": None if left is None else max(0, int(left)),
                    "reason": self.reason}

    def in_progress(self):
        with self._lock:
            return self.phase in ("waking", "power_cycle", "retrying")

    def snapshot(self):
        with self._lock:
            return {"phase": self.phase, "campaigns": dict(self.campaigns), "power_cycles": self.power_cycles,
                    "failures": dict(self.failures), "recoveries": dict(self.recoveries), "last": dict(self.last)}

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:
                print(f"recovery step failed: {e!r}", file=sys.stderr, flush=True)
            time.sleep(1)

    def _emit(self):
        try:
            self.write_metrics(self.snapshot())
        except Exception as e:
            print(f"recovery metrics write failed: {e!r}", file=sys.stderr, flush=True)

    def _alert(self, *args):
        try:
            self.alert(*args)
        except Exception as e:
            print(f"recovery alert failed: {e!r}", file=sys.stderr, flush=True)

    def _relay(self):
        try:
            return self.plug.relay()
        except Exception:
            return None

    def _set(self, on):
        try:
            return bool(self.plug.set(on))
        except Exception:
            return False

    def _host_answers(self, ports):
        return self.probe(self.host_port) or any(self.probe(p) for p in ports)

    def _probe_due(self, now):
        if now - self.probe_t < self.probe_interval:
            return False
        self.probe_t = now
        return True

    def step(self):
        with self._step_lock:
            now = self.clock()
            with self._lock:
                phase = self.phase
            if phase == "waking":
                self._step_waking(now)
            elif phase == "power_cycle":
                self._step_power_cycle(now)
            elif phase == "retrying":
                self._step_retrying(now)
            elif phase == "broken":
                self._step_broken(now)

    def _resend(self, now):
        if now - self.last_wol >= self.resend:
            self.send_wol()
            with self._lock:
                self.last_wol = now

    def _step_waking(self, now):
        with self._lock:
            ports = list(self.ports)
            host_up = self.host_up
            armed_ports = [p for p, a in self.ports.items() if a]
        if self._probe_due(now):
            if not host_up:
                host_up = self._host_answers(ports)
                if host_up:
                    with self._lock:
                        self.host_up = True
            self.svc_ok = host_up and any(self.probe(p) for p in armed_ports)
        with self._lock:
            armed, elapsed = self.armed, now - self.start_t
        if host_up:
            if not armed or self.svc_ok:
                return self._to_idle()
            if elapsed >= self.service_wait:
                return self._to_broken("service_down", now)
            return
        if not armed:
            if elapsed >= self.window:
                return self._to_idle()
            return self._resend(now)
        if elapsed < self.t1:
            return self._resend(now)
        if self._host_answers(ports):
            with self._lock:
                self.host_up = True
            self.probe_t = float('-inf')
            return
        if self.last_cycle_t is not None and now - self.last_cycle_t < self.latch:
            return self._to_broken("no_boot", now)
        relay = self._relay()
        if relay is None:
            return self._to_broken("plug_unreachable", now)
        if not relay:
            return self._to_broken("plug_off", now)
        with self._lock:
            self.phase, self.sub, self.off_t = "power_cycle", "off", now
            self.last_cycle_t = now
        self._emit()
        if not self._set(False):
            return self._to_broken("plug_unreachable", now)
        if self._relay() is not False:
            self._set(True)
            return self._to_broken("plug_unreachable", now)

    def _step_power_cycle(self, now):
        with self._lock:
            sub, off_t, on_t = self.sub, self.off_t, self.on_t
        if sub == "off":
            if now - off_t < self.off_seconds:
                return
            if not self._set(True) or self._relay() is not True:
                return self._to_broken("plug_unreachable", now)
            with self._lock:
                self.sub, self.on_t, self.t2_deadline = "on", now, now + self.t2
        elif now - on_t >= self.settle:
            self.send_wol()
            with self._lock:
                self.last_wol = now
                self.power_cycles += 1
                self.last["power_cycle"] = self.wall()
                self.phase = "retrying"
            self._emit()

    def _step_retrying(self, now):
        with self._lock:
            ports, deadline = list(self.ports), self.t2_deadline
        if now >= deadline:
            if self._host_answers(ports):
                return self._to_idle("power_cycle", now)
            return self._to_broken("no_boot", now)
        if self._probe_due(now) and self._host_answers(ports):
            return self._to_idle("power_cycle", now)
        self._resend(now)

    def _step_broken(self, now):
        with self._lock:
            ports, broken_t, last_watch = list(self.ports), self.broken_t, self.last_watch
            reason = self.reason
            armed_ports = [p for p, a in self.ports.items() if a]
        if now - broken_t >= self.latch:
            return self._to_idle()
        if now - last_watch < self.watch_interval:
            return
        with self._lock:
            self.last_watch = now
        if reason == "service_down":
            back = any(self.probe(p) for p in armed_ports)
        else:
            back = self._host_answers(ports)
        if back:
            self._to_idle("broken", now)

    def _details(self, now):
        try:
            power = self.plug.power()
        except Exception:
            power = None
        with self._lock:
            user, service, since = self.user or "-", self.service or "-", int(now - self.start_t)
        return f"user={user} service={service} seconds_since_start={since} plug_power={'n/a' if power is None else f'{power}W'}"

    def _to_broken(self, reason, now):
        details = self._details(now)
        with self._lock:
            self.phase, self.reason, self.broken_t, self.last_watch = "broken", reason, now, now
            self.failures[reason] += 1
            self.last["failure"] = self.wall()
        self._alert("BeefyWakeFailed", "critical", f"Beefy wake failed: {REASON_TEXT[reason]}", details)
        self._emit()

    def _to_idle(self, recovered=None, now=0.0):
        details = self._details(now) if recovered else ""
        with self._lock:
            self.phase, self.reason = "idle", ""
            if recovered:
                self.recoveries[recovered] += 1
                self.last["recovery"] = self.wall()
            self._reset_campaign()
        if recovered:
            self._alert("BeefyWakeRecovered", "info", f"Beefy is back after {recovered.replace('_', ' ')}", details)
        self._emit()
