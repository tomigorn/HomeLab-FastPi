"""Wake recovery for Beefy-Waker: power-cycle beefy's plug when a signed-in wake fails, then alarm.

Phases: idle, waking, power_cycle, retrying, broken. One campaign at a time.
All I/O (probe, plug, alert, metrics) runs outside the state lock; step() is the only mover.
"""
import sys
import threading
import time

PHASES = ("idle", "waking", "power_cycle", "retrying", "broken")
REASONS = ("no_boot", "service_down", "plug_off", "plug_unreachable")
REASON_TEXT = {
    "no_boot": "beefy did not boot after a power cycle",
    "service_down": "beefy is on but the requested service does not answer",
    "plug_off": "the beefy plug is switched off (left alone on purpose)",
    "plug_unreachable": "the beefy plug does not answer or did not switch",
}


class Recovery:
    def __init__(self, probe, send_wol, plug, alert, write_metrics, clock=time.monotonic, wall=time.time,
                 host_port=22, t1=120, off_seconds=15, settle=5, t2=150, service_wait=300,
                 resend=20, window=300, latch=21600, watch_interval=30):
        self.probe, self.send_wol, self.plug = probe, send_wol, plug
        self.alert, self.write_metrics = alert, write_metrics
        self.clock, self.wall, self.host_port = clock, wall, host_port
        self.t1, self.off_seconds, self.settle, self.t2 = t1, off_seconds, settle, t2
        self.service_wait, self.resend, self.window = service_wait, resend, window
        self.latch, self.watch_interval = latch, watch_interval
        self._lock = threading.Lock()
        self._step_lock = threading.Lock()
        self.phase = "idle"
        self.reason = ""
        self.campaigns = {"0": 0, "1": 0}
        self.power_cycles = 0
        self.failures = {r: 0 for r in REASONS}
        self.recoveries = {"power_cycle": 0, "broken": 0}
        self.last = {}
        self._reset_campaign()

    def _reset_campaign(self):
        self.ports = {}
        self.armed = False
        self.user = self.service = ""
        self.start_t = self.last_wol = self.last_watch = 0.0
        self.host_up = False
        self.sub = ""
        self.off_t = self.on_t = self.t2_deadline = self.broken_t = 0.0

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
        self.write_metrics(self.snapshot())

    def _host_answers(self, ports):
        return self.probe(self.host_port) or any(self.probe(p) for p in ports)

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
            self.last_wol = now

    def _step_waking(self, now):
        with self._lock:
            ports = list(self.ports)
            host_up = self.host_up
        if not host_up:
            host_up = self._host_answers(ports)
            if host_up:
                with self._lock:
                    self.host_up = True
        with self._lock:
            armed, elapsed = self.armed, now - self.start_t
            armed_ports = [p for p, a in self.ports.items() if a]
        if host_up:
            if not armed:
                return self._to_idle()
            if any(self.probe(p) for p in armed_ports):
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
        relay = self.plug.relay()
        if relay is None:
            return self._to_broken("plug_unreachable", now)
        if not relay:
            return self._to_broken("plug_off", now)
        with self._lock:
            self.phase, self.sub, self.off_t = "power_cycle", "off", now
        self._emit()
        if not self.plug.set(False) or self.plug.relay() is not False:
            return self._to_broken("plug_unreachable", now)

    def _step_power_cycle(self, now):
        with self._lock:
            sub, off_t, on_t = self.sub, self.off_t, self.on_t
        if sub == "off":
            if now - off_t < self.off_seconds:
                return
            if not self.plug.set(True) or self.plug.relay() is not True:
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
        if self._host_answers(ports):
            return self._to_idle("power_cycle", now)
        if now >= deadline:
            return self._to_broken("no_boot", now)
        self._resend(now)

    def _step_broken(self, now):
        with self._lock:
            ports, broken_t, last_watch = list(self.ports), self.broken_t, self.last_watch
        if now - broken_t >= self.latch:
            return self._to_idle()
        if now - last_watch < self.watch_interval:
            return
        with self._lock:
            self.last_watch = now
        if self._host_answers(ports):
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
        self._emit()
        self.alert("BeefyWakeFailed", "critical", f"Beefy wake failed: {REASON_TEXT[reason]}", details)

    def _to_idle(self, recovered=None, now=0.0):
        details = self._details(now) if recovered else ""
        with self._lock:
            self.phase, self.reason = "idle", ""
            if recovered:
                self.recoveries[recovered] += 1
                self.last["recovery"] = self.wall()
            self._reset_campaign()
        self._emit()
        if recovered:
            self.alert("BeefyWakeRecovered", "info", f"Beefy is back after {recovered.replace('_', ' ')}", details)
