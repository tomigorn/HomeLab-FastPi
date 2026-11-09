//! Wake recovery: power-cycle beefy's plug when a signed-in wake fails, then alarm.
//! Phases: idle, waking, power_cycle, retrying, broken. One campaign at a time; the step loop is the only mover.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tokio::net::TcpStream;

use crate::client::{self, BaseUrl};
use crate::pyfmt;
use crate::wol;

pub const PHASES: [&str; 5] = ["idle", "waking", "power_cycle", "retrying", "broken"];
pub const REASONS: [&str; 4] = ["no_boot", "service_down", "plug_off", "plug_unreachable"];
const PROBE_TIMEOUT: Duration = Duration::from_secs(1);
/// An interrupted power cycle older than this is not resumed at start.
const RESUME_MAX_AGE: f64 = 600.0;
/// Plug-on budget on SIGTERM; compose stop_grace_period must cover it plus the alert (5 s).
const SHUTDOWN_PLUG_TIMEOUT: Duration = Duration::from_secs(10);
const LOOP_BACKOFF_MAX: u64 = 60;

fn reason_text(r: &str) -> &'static str {
    match r {
        "no_boot" => "beefy did not boot after a power cycle",
        "service_down" => "beefy is on but the requested service does not answer",
        "plug_off" => "the beefy plug is switched off (left alone on purpose)",
        _ => "the beefy plug does not answer or did not switch",
    }
}

const INTERRUPTED_DESCRIPTION: &str = "A waker stop or recreate fell into the 15 s plug-off window of a power cycle; the plug was switched back on, beefy stays off until the next wake. Check the beefy plug in Home Assistant.";
const LOOP_DESCRIPTION: &str = "The wake recovery loop of beefy-waker crashed and was restarted; see docker logs beefy-waker.";

fn alert_description(name: &str) -> &'static str {
    match name {
        "BeefyWakeFailed" => "Check beefy's screen and the beefy plug in Home Assistant; history: journalctl --list-boots on beefy. The wake page shows the broken message for 6 h or until beefy answers.",
        _ => "beefy answers again. If it needed a power cut, look for the cause: journalctl -b -1 on beefy.",
    }
}

/// Monotonic seconds since start (time.monotonic()).
pub fn mono() -> f64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs_f64()
}

pub fn wall() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

pub async fn tcp_up(host: &str, port: u16) -> bool {
    matches!(tokio::time::timeout(PROBE_TIMEOUT, TcpStream::connect((host, port))).await, Ok(Ok(_)))
}

pub struct Timings {
    pub t1: f64,
    pub off_seconds: f64,
    pub settle: f64,
    pub t2: f64,
    pub service_wait: f64,
    pub resend: f64,
    pub window: f64,
    pub latch: f64,
    pub watch_interval: f64,
    pub probe_interval: f64,
    pub power_floor: f64,
    pub power_grace: f64,
}

impl Timings {
    pub fn new(t1: f64, t2: f64, resend: f64, window: f64) -> Self {
        Timings {
            t1,
            off_seconds: 15.0,
            settle: 5.0,
            t2,
            service_wait: 300.0,
            resend,
            window,
            latch: 21600.0,
            watch_interval: 30.0,
            probe_interval: 5.0,
            power_floor: 10.0,
            power_grace: 120.0,
        }
    }
}

/// beefy's myStrom plug (local REST API).
pub struct Plug {
    base: Option<BaseUrl>,
}

impl Plug {
    pub fn new(url: &str) -> Self {
        Plug { base: BaseUrl::parse(url) }
    }

    async fn get(&self, path: &str) -> Option<Value> {
        let b = self.base.as_ref()?;
        let r = client::request("GET", &b.host, b.port, &format!("{}{path}", b.base), &[], None, 1 << 16, Duration::from_secs(3)).await.ok()?;
        if !(200..300).contains(&r.status) || r.truncated {
            return None;
        }
        if r.body.is_empty() {
            return Some(json!({}));
        }
        serde_json::from_slice(&r.body).ok()
    }

    async fn report(&self, key: &str) -> Option<Value> {
        self.get("/report").await?.as_object()?.get(key).cloned()
    }

    pub async fn relay(&self) -> Option<bool> {
        self.report("relay").await?.as_bool()
    }

    pub async fn power(&self) -> Option<f64> {
        match self.report("power").await? {
            Value::Number(n) => n.as_f64(),
            _ => None,
        }
    }

    pub async fn set(&self, on: bool) -> bool {
        if self.get(&format!("/relay?state={}", if on { 1 } else { 0 })).await.is_none() {
            return false;
        }
        for i in 0..3 {
            if i > 0 {
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
            if self.relay().await == Some(on) {
                return true;
            }
        }
        false
    }
}

pub async fn post_alert(url: &str, name: &str, severity: &str, summary: &str, details: &str) -> bool {
    post_alert_desc(url, name, severity, summary, details, alert_description(name)).await
}

async fn post_alert_desc(url: &str, name: &str, severity: &str, summary: &str, details: &str, description: &str) -> bool {
    let Some(b) = BaseUrl::parse(url) else { return false };
    let now = wall();
    let local = chrono::DateTime::from_timestamp(now as i64, 0).map(|t| t.with_timezone(&chrono::Local));
    let (at, time) = match local {
        Some(t) => (t.format("%Y%m%d%H%M%S").to_string(), t.format("%Y-%m-%d %H:%M:%S").to_string()),
        None => (String::new(), String::new()),
    };
    let iso = |t: f64| chrono::DateTime::from_timestamp(t as i64, 0).map(|d| d.format("%Y-%m-%dT%H:%M:%SZ").to_string()).unwrap_or_default();
    let body = json!([{
        "labels": {"alertname": name, "host": "beefy", "severity": severity, "source": "beefy-waker", "at": at},
        "annotations": {"summary": summary, "time": time, "details": details, "description": description},
        "startsAt": iso(now), "endsAt": iso(now + 3600.0)}]);
    let path = format!("{}/api/v2/alerts", b.base);
    match client::request("POST", &b.host, b.port, &path, &[("content-type", "application/json")], Some(pyfmt::dumps(&body).into_bytes()), 1 << 16, Duration::from_secs(5)).await {
        Ok(r) => (200..300).contains(&r.status),
        Err(_) => false,
    }
}

pub struct Snapshot {
    phase: &'static str,
    campaigns: [u64; 2],
    power_cycles: u64,
    failures: BTreeMap<&'static str, u64>,
    recoveries: [u64; 2],
    last: BTreeMap<&'static str, f64>,
}

pub fn textfile(s: &Snapshot) -> String {
    let mut out: Vec<String> = Vec::new();
    let mut metric = |name: &str, kind: &str, help: &str, rows: Vec<(String, String)>| {
        out.push(format!("# HELP beefy_wake_{name} {help}\n# TYPE beefy_wake_{name} {kind}"));
        for (labels, value) in rows {
            out.push(format!("beefy_wake_{name}{labels} {value}"));
        }
    };
    metric("phase", "gauge", "Current wake recovery phase (1 = active).",
        PHASES.iter().map(|p| (format!("{{phase=\"{p}\"}}"), (s.phase == *p).then_some("1").unwrap_or("0").to_string())).collect());
    metric("campaigns_total", "counter", "Wake campaigns started.",
        vec![("{signed_in=\"0\"}".into(), s.campaigns[0].to_string()), ("{signed_in=\"1\"}".into(), s.campaigns[1].to_string())]);
    metric("power_cycles_total", "counter", "Plug power-cycles done.", vec![(String::new(), s.power_cycles.to_string())]);
    metric("failures_total", "counter", "Times the broken phase was reached.",
        REASONS.iter().map(|r| (format!("{{reason=\"{r}\"}}"), s.failures.get(r).copied().unwrap_or(0).to_string())).collect());
    metric("recoveries_total", "counter", "Times beefy came back after a power cycle or broken.",
        vec![("{after=\"power_cycle\"}".into(), s.recoveries[0].to_string()), ("{after=\"broken\"}".into(), s.recoveries[1].to_string())]);
    metric("last_event_timestamp_seconds", "gauge", "Unix time of the last event.",
        s.last.iter().map(|(e, t)| (format!("{{event=\"{e}\"}}"), pyfmt::float(*t))).collect());
    out.join("\n") + "\n"
}

fn write_textfile(path: &str, s: &Snapshot) {
    static N: AtomicU64 = AtomicU64::new(0);
    let tmp = format!("{path}.{}.{}.tmp", std::process::id(), N.fetch_add(1, Ordering::Relaxed));
    let res = std::fs::write(&tmp, textfile(s)).and_then(|_| std::fs::rename(&tmp, path));
    if let Err(e) = res {
        let _ = std::fs::remove_file(&tmp);
        eprintln!("textfile write failed: {e:?}");
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Sub {
    None,
    Off,
    On,
}

struct State {
    phase: &'static str,
    reason: &'static str,
    campaigns: [u64; 2],
    power_cycles: u64,
    failures: BTreeMap<&'static str, u64>,
    recoveries: [u64; 2],
    last: BTreeMap<&'static str, f64>,
    last_cycle_t: Option<f64>,
    // campaign
    ports: Vec<(u16, bool)>,
    armed: bool,
    user: String,
    service: String,
    start_t: f64,
    last_wol: f64,
    last_watch: f64,
    host_up: bool,
    sub: Sub,
    off_t: f64,
    on_t: f64,
    t2_deadline: f64,
    broken_t: f64,
    probe_t: f64,
    svc_ok: bool,
    grace: f64,
    extended: bool,
}

impl State {
    fn reset_campaign(&mut self) {
        self.ports.clear();
        self.armed = false;
        self.user.clear();
        self.service.clear();
        self.start_t = 0.0;
        self.last_wol = 0.0;
        self.last_watch = 0.0;
        self.host_up = false;
        self.sub = Sub::None;
        self.off_t = 0.0;
        self.on_t = 0.0;
        self.t2_deadline = 0.0;
        self.broken_t = 0.0;
        self.probe_t = f64::NEG_INFINITY;
        self.svc_ok = false;
        self.grace = 0.0;
        self.extended = false;
    }

    fn port_list(&self) -> Vec<u16> {
        self.ports.iter().map(|p| p.0).collect()
    }

    fn armed_ports(&self) -> Vec<u16> {
        self.ports.iter().filter(|p| p.1).map(|p| p.0).collect()
    }
}

pub struct Status {
    pub phase: &'static str,
    pub seconds_left: Option<i64>,
    pub reason: &'static str,
}

pub struct Recovery {
    st: Mutex<State>,
    emit_lock: Mutex<()>,
    tm: Timings,
    probe_host: String,
    host_port: u16,
    mac: [u8; 6],
    broadcast: String,
    plug: Plug,
    alert_url: String,
    metrics_path: String,
    state_file: String,
    stopping: AtomicBool,
    task: Mutex<Option<tokio::task::AbortHandle>>,
    test_panic_runs: AtomicU64,
}

impl Recovery {
    pub fn new(tm: Timings, probe_host: String, host_port: u16, mac: [u8; 6], broadcast: String, plug_url: &str, alert_url: String, metrics_path: String, state_file: String) -> Self {
        let mut st = State {
            phase: "idle",
            reason: "",
            campaigns: [0, 0],
            power_cycles: 0,
            failures: REASONS.iter().map(|r| (*r, 0)).collect(),
            recoveries: [0, 0],
            last: BTreeMap::new(),
            last_cycle_t: None,
            ports: Vec::new(),
            armed: false,
            user: String::new(),
            service: String::new(),
            start_t: 0.0,
            last_wol: 0.0,
            last_watch: 0.0,
            host_up: false,
            sub: Sub::None,
            off_t: 0.0,
            on_t: 0.0,
            t2_deadline: 0.0,
            broken_t: 0.0,
            probe_t: f64::NEG_INFINITY,
            svc_ok: false,
            grace: 0.0,
            extended: false,
        };
        st.reset_campaign();
        Recovery { st: Mutex::new(st), emit_lock: Mutex::new(()), tm, probe_host, host_port, mac, broadcast, plug: Plug::new(plug_url), alert_url, metrics_path, state_file, stopping: AtomicBool::new(false), task: Mutex::new(None), test_panic_runs: AtomicU64::new(0) }
    }

    fn s(&self) -> MutexGuard<'_, State> {
        self.st.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn send_wol(&self) -> std::io::Result<()> {
        wol::send(&self.mac, &self.broadcast)
    }

    /// Send a packet now (error = nothing changes) and start or join the single campaign.
    pub fn start(&self, port: u16, signed_in: bool, user: &str, service: &str) -> std::io::Result<()> {
        let now = mono();
        self.send_wol()?;
        let mut new = false;
        {
            let mut s = self.s();
            if s.phase == "idle" {
                s.reset_campaign();
                s.phase = "waking";
                s.reason = "";
                s.start_t = now;
                s.campaigns[signed_in as usize] += 1;
                s.last.insert("campaign", wall());
                new = true;
            }
            if s.phase != "broken" {
                s.last_wol = now;
                match s.ports.iter_mut().find(|p| p.0 == port) {
                    Some(p) => p.1 = p.1 || signed_in,
                    None => s.ports.push((port, signed_in)),
                }
                if signed_in {
                    s.armed = true;
                    if s.user.is_empty() {
                        s.user = user.to_string();
                    }
                    if s.service.is_empty() {
                        s.service = service.to_string();
                    }
                }
            }
        }
        if new {
            self.emit();
        }
        Ok(())
    }

    pub fn status(&self) -> Status {
        let now = mono();
        let s = self.s();
        let tm = &self.tm;
        let left = if s.phase == "waking" && s.armed && !s.host_up {
            Some(s.start_t + tm.t1 + s.grace - now)
        } else if s.phase == "waking" && s.armed && s.host_up {
            Some(s.start_t + tm.service_wait - now)
        } else if s.phase == "power_cycle" && s.sub == Sub::Off {
            Some(s.off_t + tm.off_seconds + tm.t2 - now)
        } else if s.phase == "power_cycle" || s.phase == "retrying" {
            Some(s.t2_deadline - now)
        } else {
            None
        };
        Status { phase: s.phase, seconds_left: left.map(|l| (l.trunc() as i64).max(0)), reason: s.reason }
    }

    pub fn in_progress(&self) -> bool {
        matches!(self.s().phase, "waking" | "power_cycle" | "retrying")
    }

    fn snapshot(&self) -> Snapshot {
        let s = self.s();
        Snapshot { phase: s.phase, campaigns: s.campaigns, power_cycles: s.power_cycles, failures: s.failures.clone(), recoveries: s.recoveries, last: s.last.clone() }
    }

    fn emit(&self) {
        let _g = self.emit_lock.lock().unwrap_or_else(|e| e.into_inner());
        write_textfile(&self.metrics_path, &self.snapshot());
    }

    /// Fault injection for the black-box suite: the first `n` loop runs panic.
    pub fn set_test_panic_runs(&self, n: u64) {
        self.test_panic_runs.store(n, Ordering::Relaxed);
    }

    /// The plug-off window is persisted, so a stop or restart inside it can switch the plug back on.
    fn mark_cycle(&self) {
        let tmp = format!("{}.tmp", self.state_file);
        let res = std::fs::write(&tmp, format!("{}\n", wall())).and_then(|_| std::fs::rename(&tmp, &self.state_file));
        if let Err(e) = res {
            eprintln!("recovery: state file write failed: {e:?}");
        }
    }

    fn clear_cycle(&self) {
        match std::fs::remove_file(&self.state_file) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => eprintln!("recovery: state file remove failed: {e:?}"),
            _ => {}
        }
    }

    fn mid_cycle(&self) -> bool {
        let s = self.s();
        s.phase == "power_cycle" && s.sub == Sub::Off
    }

    async fn alert_interrupted(&self, summary: &str, details: &str) {
        post_alert_desc(&self.alert_url, "BeefyWakeFailed", "critical", summary, details, INTERRUPTED_DESCRIPTION).await;
    }

    /// At start: a recent interrupted power cycle with the plug still off gets the plug switched on (never off).
    pub async fn resume_interrupted(&self) {
        let Ok(text) = std::fs::read_to_string(&self.state_file) else { return };
        let age = text.trim().parse::<f64>().map(|t| wall() - t).unwrap_or(f64::INFINITY);
        if !(0.0..RESUME_MAX_AGE).contains(&age) {
            eprintln!("recovery: stale interrupted power cycle state ignored");
            return self.clear_cycle();
        }
        match self.plug.relay().await {
            Some(true) => eprintln!("recovery: interrupted power cycle found at start, plug already on"),
            Some(false) => {
                if self.plug.set(true).await {
                    eprintln!("recovery: interrupted power cycle found at start, plug switched back on");
                    self.alert_interrupted("Beefy wake: power cycle interrupted by a waker restart, plug switched back on", "plug=on").await;
                } else {
                    eprintln!("recovery: interrupted power cycle found at start, plug did not switch on");
                    self.alert_interrupted("Beefy wake: power cycle interrupted by a waker restart, plug did not switch back on", "plug=off").await;
                }
            }
            None => {
                eprintln!("recovery: interrupted power cycle found at start, plug unreachable");
                self.alert_interrupted("Beefy wake: power cycle interrupted by a waker restart, plug unreachable", "plug=unreachable").await;
            }
        }
        self.clear_cycle();
    }

    /// On SIGTERM: stop the loop; inside the plug-off window switch the plug back on (bounded).
    pub async fn shutdown(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        if let Some(h) = self.task.lock().unwrap_or_else(|e| e.into_inner()).take() {
            h.abort();
        }
        tokio::task::yield_now().await;
        if !self.mid_cycle() {
            return;
        }
        if matches!(tokio::time::timeout(SHUTDOWN_PLUG_TIMEOUT, self.plug.set(true)).await, Ok(true)) {
            self.clear_cycle();
            eprintln!("recovery: power cycle interrupted by shutdown, plug switched back on");
            self.alert_interrupted("Beefy wake: power cycle interrupted by a waker stop, plug switched back on", "plug=on").await;
        } else {
            eprintln!("recovery: power cycle interrupted by shutdown, plug did not switch back on (retried at next start)");
        }
    }

    /// Resume an interrupted cycle, then run the step loop; a loop that panics or ends is logged, alerted once and restarted with backoff.
    pub async fn supervise(self: Arc<Self>) {
        self.resume_interrupted().await;
        let mut backoff = 1;
        let mut alerted = false;
        loop {
            if self.stopping.load(Ordering::SeqCst) {
                return;
            }
            let r = self.clone();
            let h = tokio::spawn(async move { r.run().await });
            *self.task.lock().unwrap_or_else(|e| e.into_inner()) = Some(h.abort_handle());
            let started = mono();
            let res = h.await;
            if self.stopping.load(Ordering::SeqCst) || matches!(&res, Err(e) if e.is_cancelled()) {
                return;
            }
            if mono() - started >= LOOP_BACKOFF_MAX as f64 {
                backoff = 1;
            }
            let what = if res.is_err() { "panicked" } else { "ended" };
            eprintln!("recovery loop {what}, restarting in {backoff}s");
            if !alerted {
                alerted = true;
                post_alert_desc(&self.alert_url, "BeefyWakeFailed", "critical", &format!("Beefy wake recovery loop {what} and was restarted"), &format!("phase={}", self.s().phase), LOOP_DESCRIPTION).await;
            }
            tokio::time::sleep(Duration::from_secs(backoff)).await;
            backoff = (backoff * 2).min(LOOP_BACKOFF_MAX);
            eprintln!("recovery loop restarted");
        }
    }

    pub async fn run(&self) {
        if self.test_panic_runs.load(Ordering::Relaxed) > 0 {
            self.test_panic_runs.fetch_sub(1, Ordering::Relaxed);
            panic!("test fault injection (WAKER_TEST_PANIC_RUNS)");
        }
        self.emit();
        loop {
            self.step().await;
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }

    async fn probe(&self, port: u16) -> bool {
        tcp_up(&self.probe_host, port).await
    }

    async fn any_probe(&self, ports: &[u16]) -> bool {
        for &p in ports {
            if self.probe(p).await {
                return true;
            }
        }
        false
    }

    async fn host_answers(&self, ports: &[u16]) -> bool {
        self.probe(self.host_port).await || self.any_probe(ports).await
    }

    fn probe_due(&self, now: f64) -> bool {
        let mut s = self.s();
        if now - s.probe_t < self.tm.probe_interval {
            return false;
        }
        s.probe_t = now;
        true
    }

    async fn step(&self) {
        let now = mono();
        let phase = self.s().phase;
        match phase {
            "waking" => self.step_waking(now).await,
            "power_cycle" => self.step_power_cycle(now).await,
            "retrying" => self.step_retrying(now).await,
            "broken" => self.step_broken(now).await,
            _ => {}
        }
    }

    fn resend(&self, now: f64) {
        let due = now - self.s().last_wol >= self.tm.resend;
        if due {
            let _ = self.send_wol();
            self.s().last_wol = now;
        }
    }

    async fn step_waking(&self, now: f64) {
        let (ports, mut host_up, armed_ports) = {
            let s = self.s();
            (s.port_list(), s.host_up, s.armed_ports())
        };
        if self.probe_due(now) {
            let up = self.host_answers(&ports).await;
            if up != host_up {
                {
                    let mut s = self.s();
                    s.host_up = up;
                    if host_up {
                        s.start_t = now;
                        s.grace = 0.0;
                        s.extended = false;
                    }
                }
                if host_up {
                    eprintln!("recovery: host stopped answering, waking again");
                }
                host_up = up;
            }
            let ok = host_up && self.any_probe(&armed_ports).await;
            self.s().svc_ok = ok;
        }
        let (armed, elapsed, grace, svc_ok, extended) = {
            let s = self.s();
            (s.armed, now - s.start_t, s.grace, s.svc_ok, s.extended)
        };
        if host_up {
            if !armed || svc_ok {
                return self.to_idle(None, now).await;
            }
            if elapsed >= self.tm.service_wait {
                return self.to_broken("service_down", now).await;
            }
            return;
        }
        if !armed {
            if elapsed >= self.tm.window {
                return self.to_idle(None, now).await;
            }
            return self.resend(now);
        }
        if elapsed < self.tm.t1 + grace {
            return self.resend(now);
        }
        if self.host_answers(&ports).await {
            let mut s = self.s();
            s.host_up = true;
            s.probe_t = f64::NEG_INFINITY;
            return;
        }
        let last_cycle = self.s().last_cycle_t;
        if let Some(t) = last_cycle {
            if now - t < self.tm.latch {
                return self.to_broken("no_boot", now).await;
            }
        }
        match self.plug.relay().await {
            None => return self.to_broken("plug_unreachable", now).await,
            Some(false) => return self.to_broken("plug_off", now).await,
            Some(true) => {}
        }
        if !extended {
            if let Some(p) = self.plug.power().await {
                if p > self.tm.power_floor {
                    {
                        let mut s = self.s();
                        s.extended = true;
                        s.grace = elapsed - self.tm.t1 + self.tm.power_grace;
                    }
                    return self.resend(now);
                }
            }
        }
        {
            let mut s = self.s();
            s.phase = "power_cycle";
            s.sub = Sub::Off;
            s.off_t = now;
            s.last_cycle_t = Some(now);
        }
        self.mark_cycle();
        self.emit();
        if !self.plug.set(false).await || self.plug.relay().await != Some(false) {
            self.plug.set(true).await;
            self.leave_off();
            return self.to_broken("plug_unreachable", now).await;
        }
    }

    async fn step_power_cycle(&self, now: f64) {
        let (sub, off_t, on_t) = {
            let s = self.s();
            (s.sub, s.off_t, s.on_t)
        };
        if sub == Sub::Off {
            if now - off_t < self.tm.off_seconds {
                return;
            }
            if !self.plug.set(true).await || self.plug.relay().await != Some(true) {
                self.leave_off();
                return self.to_broken("plug_unreachable", now).await;
            }
            self.clear_cycle();
            let mut s = self.s();
            s.sub = Sub::On;
            s.on_t = now;
            s.t2_deadline = now + self.tm.t2;
        } else if now - on_t >= self.tm.settle {
            let _ = self.send_wol();
            {
                let mut s = self.s();
                s.last_wol = now;
                s.power_cycles += 1;
                s.last.insert("power_cycle", wall());
                s.phase = "retrying";
            }
            self.emit();
        }
    }

    /// Out of the plug-off window without a successful switch-on: the broken alert covers it, so nothing to resume.
    fn leave_off(&self) {
        self.s().sub = Sub::None;
        self.clear_cycle();
    }

    async fn step_retrying(&self, now: f64) {
        let (ports, deadline) = {
            let s = self.s();
            (s.port_list(), s.t2_deadline)
        };
        if now >= deadline {
            if self.host_answers(&ports).await {
                return self.to_idle(Some("power_cycle"), now).await;
            }
            return self.to_broken("no_boot", now).await;
        }
        if self.probe_due(now) && self.host_answers(&ports).await {
            return self.to_idle(Some("power_cycle"), now).await;
        }
        self.resend(now);
    }

    async fn step_broken(&self, now: f64) {
        let (ports, broken_t, last_watch, reason, armed_ports) = {
            let s = self.s();
            (s.port_list(), s.broken_t, s.last_watch, s.reason, s.armed_ports())
        };
        if now - broken_t >= self.tm.latch {
            return self.to_idle(None, now).await;
        }
        if now - last_watch < self.tm.watch_interval {
            return;
        }
        self.s().last_watch = now;
        let back = if reason == "service_down" { self.any_probe(&armed_ports).await } else { self.host_answers(&ports).await };
        if back {
            self.to_idle(Some("broken"), now).await;
        }
    }

    async fn details(&self, now: f64) -> String {
        let power = self.plug.power().await;
        let (user, service, since) = {
            let s = self.s();
            let u = if s.user.is_empty() { "-".to_string() } else { s.user.clone() };
            let v = if s.service.is_empty() { "-".to_string() } else { s.service.clone() };
            (u, v, (now - s.start_t).trunc() as i64)
        };
        let p = power.map(|p| format!("{}W", pyfmt::float(p))).unwrap_or_else(|| "n/a".into());
        format!("user={user} service={service} seconds_since_start={since} plug_power={p}")
    }

    async fn to_broken(&self, reason: &'static str, now: f64) {
        let details = self.details(now).await;
        {
            let mut s = self.s();
            s.phase = "broken";
            s.reason = reason;
            s.broken_t = now;
            s.last_watch = now;
            *s.failures.entry(reason).or_insert(0) += 1;
            s.last.insert("failure", wall());
        }
        post_alert(&self.alert_url, "BeefyWakeFailed", "critical", &format!("Beefy wake failed: {}", reason_text(reason)), &details).await;
        self.emit();
    }

    async fn to_idle(&self, recovered: Option<&'static str>, now: f64) {
        let details = if recovered.is_some() { self.details(now).await } else { String::new() };
        {
            let mut s = self.s();
            s.phase = "idle";
            s.reason = "";
            if let Some(r) = recovered {
                s.recoveries[(r == "broken") as usize] += 1;
                s.last.insert("recovery", wall());
            }
            s.reset_campaign();
        }
        if let Some(r) = recovered {
            post_alert(&self.alert_url, "BeefyWakeRecovered", "info", &format!("Beefy is back after {}", r.replace('_', " ")), &details).await;
        }
        self.emit();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn textfile_initial() {
        let s = Snapshot { phase: "idle", campaigns: [0, 0], power_cycles: 0, failures: REASONS.iter().map(|r| (*r, 0)).collect(), recoveries: [0, 0], last: BTreeMap::new() };
        let t = textfile(&s);
        assert!(t.starts_with("# HELP beefy_wake_phase Current wake recovery phase (1 = active).\n# TYPE beefy_wake_phase gauge\nbeefy_wake_phase{phase=\"idle\"} 1\n"));
        assert!(t.ends_with("# TYPE beefy_wake_last_event_timestamp_seconds gauge\n"));
        assert!(t.contains("beefy_wake_failures_total{reason=\"plug_unreachable\"} 0\n"));
    }

    #[test]
    fn textfile_events_sorted() {
        let mut last = BTreeMap::new();
        last.insert("power_cycle", 2.5);
        last.insert("campaign", 1.0);
        let s = Snapshot { phase: "broken", campaigns: [1, 2], power_cycles: 1, failures: REASONS.iter().map(|r| (*r, 0)).collect(), recoveries: [0, 1], last };
        let t = textfile(&s);
        assert!(t.ends_with("beefy_wake_last_event_timestamp_seconds{event=\"campaign\"} 1.0\nbeefy_wake_last_event_timestamp_seconds{event=\"power_cycle\"} 2.5\n"));
        assert!(t.contains("beefy_wake_campaigns_total{signed_in=\"1\"} 2\n"));
        assert!(t.contains("beefy_wake_recoveries_total{after=\"broken\"} 1\n"));
    }

    #[test]
    fn status_truncates_like_int() {
        let r = Recovery::new(Timings::new(120.0, 150.0, 20.0, 300.0), "127.0.0.1".into(), 1, [0; 6], "127.0.0.1".into(), "http://127.0.0.1:1", "http://127.0.0.1:1".into(), "/nonexistent/x".into(), "/nonexistent/s".into());
        let st = r.status();
        assert_eq!((st.phase, st.seconds_left, st.reason), ("idle", None, ""));
        r.s().phase = "waking";
        r.s().armed = true;
        r.s().start_t = mono();
        assert_eq!(r.status().seconds_left, Some(119));
    }
}
