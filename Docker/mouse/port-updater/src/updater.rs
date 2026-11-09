//! The port loop: keeps qBittorrent's listen port on gluetun's forwarded port, reattaches the VPN clients, restarts the stack after repeated zero ports.
//! Log lines are the legacy ones: post-update checks, smoke-test and the reattach exporter grep for them.
use std::thread::sleep;
use std::time::Duration;

use jiff::Zoned;
use ureq::Agent;

use crate::clients::{self, Docker};
use crate::config::Config;
use crate::events;

const CLIENTS: [&str; 3] = ["qbittorrent_mouse", "mousehole", "sabnzbd"];
const GLUETUN: &str = "gluetun_mouse";

type Fatal = String;

pub struct Updater {
    cfg: Config,
    http: Agent,
    quick: Agent,
    docker: Docker,
    cookie: Option<String>,
}

fn secs(n: u64) {
    sleep(Duration::from_secs(n));
}

/// Wait before the next stack restart after `failed` restarts that brought no port: base, 2x base, 4x base ... capped.
pub fn backoff(base: u64, max: u64, failed: u32) -> u64 {
    let shift = failed.saturating_sub(1).min(32);
    base.saturating_mul(1u64 << shift).min(max)
}

impl Updater {
    pub fn new(cfg: Config) -> Self {
        let docker = Docker::new(cfg.docker_url.clone());
        Updater { cfg, http: clients::agent(Duration::from_secs(15)), quick: clients::agent(Duration::from_secs(5)), docker, cookie: None }
    }

    fn qbit(&self, path: &str) -> String {
        format!("http://{}:8080{path}", self.cfg.gluetun_ip)
    }

    fn gluetun(&self, path: &str) -> String {
        format!("http://{}:8000{path}", self.cfg.gluetun_ip)
    }

    fn log_event(&self, event: &str, port: u64, old_port: u64, message: &str, vpn_ip: &str) {
        let ts = events::timestamp(self.cfg.tz.as_ref(), &Zoned::now());
        events::append(&self.cfg.data_file, &events::event_line(&ts, event, port, old_port, vpn_ip, message), events::MAX_LINES);
    }

    fn qbit_code(&self, path: &str, with_cookie: bool) -> u16 {
        let mut req = self.quick.get(&self.qbit(path));
        if let (true, Some(c)) = (with_cookie, &self.cookie) {
            req = req.header("Cookie", c);
        }
        clients::status(req.call())
    }

    fn is_qbittorrent_available(&self) -> bool {
        matches!(self.qbit_code("/", false), 200 | 302)
    }

    fn wait_for_gluetun(&self) -> bool {
        println!("Waiting for gluetun to become healthy...");
        for _ in 0..60 {
            if self.docker.health(GLUETUN).as_deref() == Some("healthy") {
                println!("Gluetun is healthy.");
                return true;
            }
            secs(5);
        }
        println!("WARNING: Gluetun did not become healthy within 5 minutes.");
        false
    }

    fn wait_for_qbittorrent(&self) -> bool {
        println!("Waiting for qBittorrent web UI...");
        for _ in 0..24 {
            if self.is_qbittorrent_available() {
                println!("qBittorrent is ready.");
                return true;
            }
            secs(5);
        }
        println!("WARNING: qBittorrent did not become ready within 2 minutes.");
        false
    }

    fn try_reattach_qbittorrent(&self) -> bool {
        println!("Attempting to reattach qBittorrent/mousehole/sabnzbd to gluetun network...");
        let _ = self.docker.act("restart", &CLIENTS);
        secs(5);
        println!("Waiting for qBittorrent after reattach...");
        self.wait_for_qbittorrent();
        self.is_qbittorrent_available()
    }

    fn login(&mut self) -> Result<(), Fatal> {
        let resp = self
            .http
            .post(&self.qbit("/api/v2/auth/login"))
            .send_form([("username", self.cfg.qbit_user.as_str()), ("password", self.cfg.qbit_pass.as_str())])
            .map_err(|e| format!("qBittorrent login failed: {e}"))?;
        self.cookie = clients::cookies(&resp);
        Ok(())
    }

    fn set_preferences(&self, json: &str) -> Result<(), Fatal> {
        let mut req = self.http.post(&self.qbit("/api/v2/app/setPreferences"));
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c);
        }
        req.send_form([("json", json)]).map(|_| ()).map_err(|e| format!("qBittorrent setPreferences failed: {e}"))
    }

    fn qbit_interface(&self) -> Option<String> {
        let mut req = self.http.get(&self.qbit("/api/v2/app/preferences"));
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c);
        }
        clients::jq_field(&clients::body(req.call())?, "current_network_interface").ok().flatten().map(|v| clients::raw(&v))
    }

    /// At start the binding usually survives from the last run: restart qBittorrent only when it is not on tun0 yet.
    fn ensure_qbittorrent_bound(&mut self) -> Result<(), Fatal> {
        if self.qbit_interface().as_deref() == Some("tun0") {
            println!("qBittorrent already bound to tun0 - no restart needed");
            return Ok(());
        }
        self.apply_qbittorrent_settings()
    }

    fn apply_qbittorrent_settings(&mut self) -> Result<(), Fatal> {
        println!("Setting qBittorrent to use tun0 interface...");
        self.set_preferences(r#"{"current_network_interface":"tun0"}"#)?;
        println!("Restarting qBittorrent to apply interface binding...");
        self.docker.act("restart", &CLIENTS[..1])?;
        secs(15);
        self.login()
    }

    /// Sleeps until the next cycle, cut short when the session cookie turns invalid (403 = qBittorrent restarted).
    fn sleep_until_next_cycle(&self) {
        let mut waited = 0;
        while waited < self.cfg.check_interval {
            secs(self.cfg.session_check_interval);
            waited += self.cfg.session_check_interval;
            if self.qbit_code("/api/v2/app/version", true) == 403 {
                println!("qBittorrent session expired (restart?) - re-applying port now");
                return;
            }
        }
    }

    /// Err = gluetun answered with an error or non-JSON (port unknown); Ok(None) = no value or no answer at all (counts as zero).
    fn gluetun_get(&self, path: &str, key: &str) -> Result<Option<serde_json::Value>, String> {
        let resp = self.http.get(&self.gluetun(path)).header("Authorization", &clients::basic(&self.cfg.gluetun_user, &self.cfg.gluetun_pass)).call();
        clients::jq_field(&clients::api_body(resp)?.unwrap_or_default(), key)
    }

    /// Waits `delay` s before the next stack restart, polling gluetun quietly; true when a port arrived meanwhile.
    fn back_off(&self, delay: u64) -> bool {
        let step = self.cfg.zero_retry_interval.max(1);
        let mut waited = 0;
        while waited < delay {
            let n = step.min(delay - waited);
            secs(n);
            waited += n;
            if let Some(p) = self.gluetun_get("/v1/portforward", "port").ok().and_then(|v| clients::port(v.as_ref())).filter(|p| *p != 0) {
                println!("Port {p} arrived during back-off");
                return true;
            }
        }
        false
    }

    fn qbit_listen_port(&self) -> Result<String, Fatal> {
        let mut req = self.http.get(&self.qbit("/api/v2/app/preferences"));
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c);
        }
        Ok(clients::jq_field(&clients::body(req.call()).unwrap_or_default(), "listen_port")?.map(|v| clients::raw(&v)).unwrap_or_default())
    }

    fn post_cookie(&self, path: &str, form: [(&str, &str); 1]) -> Result<(), Fatal> {
        let mut req = self.http.post(&self.qbit(path));
        if let Some(c) = &self.cookie {
            req = req.header("Cookie", c);
        }
        req.send_form(form).map(|_| ()).map_err(|e| format!("qBittorrent {path} failed: {e}"))
    }

    /// Stops the VPN clients, restarts gluetun for a new lease, starts them again: they share gluetun's netns.
    fn restart_stack(&mut self) -> Result<(), Fatal> {
        println!("Stopping qbittorrent, mousehole and sabnzbd before gluetun restart...");
        let _ = self.docker.act("stop", &CLIENTS);
        println!("Restarting gluetun to obtain a new VPN port lease...");
        self.docker.act("restart", &[GLUETUN])?;
        self.wait_for_gluetun();
        println!("Starting qbittorrent, mousehole and sabnzbd...");
        self.docker.act("start", &CLIENTS)?;
        self.wait_for_qbittorrent();
        self.login()?;
        self.apply_qbittorrent_settings()
    }

    fn banner(&self) {
        let started = events::banner_time(self.cfg.tz.as_ref(), &Zoned::now());
        println!("\n============================================\n\n=============== port-updater ===============\n");
        println!("Service: port-updater  Container: port_updater");
        println!("Version: {}", env!("CARGO_PKG_VERSION"));
        println!("Started : {started}\n");
        println!("--- Purpose: keep qBittorrent listen port in sync with VPN forwarded port ---\n");
        println!("============================================\n");
    }

    pub fn run(mut self) -> Result<(), Fatal> {
        self.banner();
        self.log_event("startup", 0, 0, "Port updater started", "");
        println!("Waiting for qBittorrent to be ready...");
        if !self.wait_for_qbittorrent() {
            println!("qBittorrent did not become ready within timeout; attempting to reattach containers...");
            self.try_reattach_qbittorrent();
        }
        self.login()?;
        self.ensure_qbittorrent_bound()?;

        println!("Starting port monitoring loop...");
        let mut last_port: u64 = 0;
        let mut zero_count: u32 = 0;
        let mut failed_restarts: u32 = 0;
        let limit = self.cfg.zero_port_limit;
        loop {
            if !self.is_qbittorrent_available() {
                println!("qBittorrent unreachable from port-updater; attempting reattach...");
                self.try_reattach_qbittorrent();
            }
            self.login()?;

            let port = match self.gluetun_get("/v1/portforward", "port") {
                Ok(v) => clients::port(v.as_ref()),
                Err(e) => {
                    println!("gluetun API error: {e} - port unknown, keeping {last_port}, retrying next cycle");
                    self.sleep_until_next_cycle();
                    continue;
                }
            };
            let vpn_ip = clients::vpn_ip(self.gluetun_get("/v1/publicip/ip", "public_ip").ok().flatten().as_ref());
            let qbit_port = self.qbit_listen_port()?;
            let shown = port.map(|p| p.to_string()).unwrap_or_default();

            match port {
                Some(p) if p != 0 && (p != last_port || qbit_port == "1" || qbit_port.is_empty()) => {
                    println!(">>>\n      ProtonVPN assigned a new forwarded port: {p} (was: {last_port}) — triggering qBittorrent update\n<<<");
                    println!("Port update needed: VPN={p}, qBit={qbit_port} (last={last_port})");
                    self.set_preferences(&format!("{{\"listen_port\":{p}}}"))?;
                    println!("Port updated to {p}");
                    self.log_event("port_update", p, last_port, &format!("ProtonVPN assigned new port {p} (was {last_port})"), &vpn_ip);
                    last_port = p;
                    zero_count = 0;
                    failed_restarts = 0;
                    println!("Reannouncing all torrents...");
                    self.post_cookie("/api/v2/torrents/reannounce", [("hashes", "all")])?;
                    println!("Reannounce triggered.");
                }
                None | Some(0) => {
                    zero_count += 1;
                    println!("Port is 0 ({zero_count}/{limit}): VPN={shown}, qBit={qbit_port}");
                    self.log_event("zero_port", 0, last_port, &format!("Port is 0 ({zero_count}/{limit})"), &vpn_ip);
                    if zero_count >= limit && failed_restarts > 0 {
                        let delay = backoff(self.cfg.stack_restart_backoff, self.cfg.stack_restart_backoff_max, failed_restarts);
                        println!("No port after stack restart - backing off {} min ({delay} s) before the next one", delay / 60);
                        if self.back_off(delay) {
                            zero_count = 0;
                            continue;
                        }
                    }
                    if zero_count >= limit {
                        println!("Port has been 0 for {} minutes — restarting stack...", u64::from(zero_count) * self.cfg.check_interval / 60);
                        self.log_event("stack_restart", 0, last_port, &format!("Port remained 0 for {zero_count} cycles — restarting stack"), &vpn_ip);
                        self.restart_stack()?;
                        failed_restarts += 1;
                        zero_count = 0;
                        last_port = 0;
                        println!("Stack restarted. Checking for new port immediately...");
                    } else {
                        println!("Port is 0 — will retry in {} seconds (faster retry)...", self.cfg.zero_retry_interval);
                        secs(self.cfg.zero_retry_interval);
                    }
                    continue;
                }
                Some(_) => {
                    failed_restarts = 0;
                    println!("Port OK: VPN={shown}, qBit={qbit_port}");
                }
            }
            self.sleep_until_next_cycle();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backoff_doubles_and_caps() {
        let seq: Vec<u64> = (1..=7).map(|n| backoff(240, 3600, n)).collect();
        assert_eq!(seq, [240, 480, 960, 1920, 3600, 3600, 3600]);
        assert_eq!(backoff(240, 3600, 0), 240);
        assert_eq!(backoff(240, 3600, u32::MAX), 3600);
        assert_eq!(backoff(2, 5, 3), 5);
    }
}
