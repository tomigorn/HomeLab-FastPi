#![forbid(unsafe_code)]
//! Triggers m4b-merge/orchestrate.py when the audiobook library holds a multi-file book; holds no merge logic of its own.
mod candidates;
mod config;
mod oserror;
mod schedule;
mod trigger;
mod watch;

use chrono::Local;
use signal_hook::consts::{SIGINT, SIGTERM};
use signal_hook::iterator::Signals;
use std::io::Write;
use std::os::unix::process::ExitStatusExt;
use std::process::{Command, ExitCode};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use config::Config;
use trigger::Trigger;

pub fn log(msg: &str) {
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{}  {msg}", Local::now().format("%Y-%m-%dT%H:%M:%S"));
    let _ = out.flush();
}

fn secs(n: i64) -> Duration {
    Duration::from_secs(n.max(0) as u64)
}

#[derive(Default)]
struct Run {
    busy: bool,
    stop: bool,
}

/// Stop at once when idle; during a merge, only once the orchestrator returns (docker's kill timeout still applies, as before).
fn handle_signals(run: Arc<Mutex<Run>>) -> std::io::Result<()> {
    let mut signals = Signals::new([SIGTERM, SIGINT])?;
    thread::spawn(move || {
        for _ in signals.forever() {
            let mut r = run.lock().unwrap_or_else(|e| e.into_inner());
            if !r.busy {
                std::process::exit(0);
            }
            r.stop = true;
        }
    });
    Ok(())
}

/// Returns true when the run is done with (finished, or failed books that must not be retried).
fn run_merge(cfg: &Config, reason: &str, run: &Mutex<Run>) -> bool {
    let books = candidates::candidates(&cfg.lib);
    if books.is_empty() {
        log(&format!("{reason}: nothing to merge"));
        return true;
    }
    log(&format!("{reason}: {} candidate folder(s) - starting merge", books.len()));
    let orch = cfg.merge_dir.join("orchestrate.py");
    {
        let mut r = run.lock().unwrap_or_else(|e| e.into_inner());
        if r.stop {
            std::process::exit(0);
        }
        r.busy = true;
    }
    let status = Command::new(&orch).args(["--jobs", &cfg.jobs, "--include-multipart"]).current_dir(&cfg.merge_dir).status();
    {
        let mut r = run.lock().unwrap_or_else(|e| e.into_inner());
        r.busy = false;
        if r.stop {
            std::process::exit(0);
        }
    }
    let status = match status {
        Ok(s) => s,
        Err(e) => {
            log(&format!("could not start the orchestrator: {}", oserror::python_style(&e, &orch)));
            return false;
        }
    };
    let code = status.code().unwrap_or_else(|| -status.signal().unwrap_or(0));
    match code {
        // another run holds runs/merge.lock; it scans the whole library anyway, so stay armed and retry later
        3 => {
            log(&format!("another merge run holds the lock; retrying in {}s", cfg.retry));
            false
        }
        0 => {
            log("merge run finished cleanly");
            true
        }
        n => {
            log(&format!("orchestrator exited {n} (some books failed); see runs/run.jsonl"));
            true
        }
    }
}

fn sweep(cfg: &Config, trigger: &Trigger) {
    let time = match cfg.sweep_time {
        Ok(t) => t,
        Err(ref e) => {
            log(&format!("weekly sweep disabled: {e}"));
            return;
        }
    };
    loop {
        let next = schedule::next_sweep(cfg.sweep_dow, time, Local::now().naive_local());
        log(&format!("weekly sweep scheduled for {}", next.format("%Y-%m-%dT%H:%M")));
        loop {
            let left = next - Local::now().naive_local();
            match left.to_std() {
                Ok(d) if !d.is_zero() => thread::sleep(d.min(Duration::from_secs(3600))),
                _ => break,
            }
        }
        trigger.touch(true);
        thread::sleep(Duration::from_secs(90));
    }
}

fn main() -> ExitCode {
    let cfg = match Config::from_env() {
        Ok(c) => Arc::new(c),
        Err(e) => {
            log(&e);
            return ExitCode::from(1);
        }
    };
    if !cfg.lib.is_dir() {
        log(&format!("library {} is not a directory", cfg.lib.display()));
        return ExitCode::from(1);
    }
    let orch = cfg.merge_dir.join("orchestrate.py");
    if !orch.is_file() {
        log(&format!("orchestrator not found at {}", orch.display()));
        return ExitCode::from(1);
    }
    log(&format!("watching {}", cfg.lib.display()));
    log(&format!("quiet period {}s, {} parallel jobs, retry {}s", cfg.quiet, cfg.jobs, cfg.retry));

    let run = Arc::new(Mutex::new(Run::default()));
    if let Err(e) = handle_signals(run.clone()) {
        log(&format!("cannot install signal handlers: {e}"));
        return ExitCode::from(1);
    }
    let trigger = Arc::new(Trigger::new(secs(cfg.quiet)));
    let watcher = match watch::Watcher::new(&cfg.lib) {
        Ok(w) => w,
        Err(e) => {
            log(&format!("cannot watch {}: {e}", cfg.lib.display()));
            return ExitCode::from(1);
        }
    };
    {
        let t = trigger.clone();
        thread::spawn(move || watcher.run(&t));
    }
    {
        let (c, t) = (cfg.clone(), trigger.clone());
        thread::spawn(move || sweep(&c, &t));
    }

    // books may have arrived while the container was down
    trigger.touch(false);
    let mut retry_at: Option<Instant> = None;
    loop {
        trigger.wait(retry_at);
        if !run_merge(&cfg, "trigger", &run) {
            trigger.rearm();
            retry_at = Some(Instant::now() + secs(cfg.retry));
        }
    }
}
