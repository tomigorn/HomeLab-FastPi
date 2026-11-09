//! Copies finished AudioBookRequest downloads (qBittorrent category abr) into the Audiobookshelf library, then scans it.
mod app;
mod clients;
mod config;
mod http;
mod library;
mod naming;
mod pipeline;
mod quota;
mod ranking;
mod util;

use std::net::SocketAddr;
use std::sync::Arc;

struct Logger;

impl log::Log for Logger {
    fn enabled(&self, m: &log::Metadata) -> bool {
        m.level() <= log::Level::Info
    }

    fn log(&self, record: &log::Record) {
        if self.enabled(record.metadata()) && record.target().starts_with("audiobook_importer") {
            let level = if record.level() == log::Level::Warn { "WARNING" } else { record.level().as_str() };
            eprintln!("{} {level} {}", util::log_stamp(), record.args());
        }
    }

    fn flush(&self) {}
}

static LOGGER: Logger = Logger;

/// `--health`: the container healthcheck (the image has no shell or curl). Exit 0 when /health answers ok.
fn health_probe(port: u16) -> bool {
    use std::io::{Read, Write};
    let Ok(mut s) = std::net::TcpStream::connect_timeout(&SocketAddr::from(([127, 0, 0, 1], port)), std::time::Duration::from_secs(5)) else { return false };
    let _ = s.set_read_timeout(Some(std::time::Duration::from_secs(5)));
    if s.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n").is_err() {
        return false;
    }
    let mut out = String::new();
    let _ = s.read_to_string(&mut out);
    out.starts_with("HTTP/1.") && out.contains(" 200 ") && out.ends_with("ok")
}

/// `--probe http://<ipv4>:<port>/<path>`: prints the answer's status code (exit 0), 1 when nothing answers, 2 for anything but a plain-http IPv4 URL.
fn probe(url: &str) -> i32 {
    use std::io::{Read, Write};
    let Some(rest) = url.strip_prefix("http://") else { return 2 };
    let (authority, path) = rest.split_once('/').map(|(a, p)| (a, format!("/{p}"))).unwrap_or((rest, "/".to_string()));
    let Ok(addr) = authority.parse::<std::net::SocketAddrV4>().or_else(|_| authority.parse::<std::net::Ipv4Addr>().map(|ip| std::net::SocketAddrV4::new(ip, 80))) else { return 2 };
    if path.chars().any(|c| c.is_ascii_whitespace() || c.is_ascii_control()) {
        return 2;
    }
    let timeout = std::time::Duration::from_secs(5);
    let Ok(mut s) = std::net::TcpStream::connect_timeout(&SocketAddr::V4(addr), timeout) else { return 1 };
    let _ = s.set_read_timeout(Some(timeout));
    if s.write_all(format!("GET {path} HTTP/1.0\r\nHost: {authority}\r\n\r\n").as_bytes()).is_err() {
        return 1;
    }
    let mut head = [0u8; 64];
    let n = s.read(&mut head).unwrap_or(0);
    let line = String::from_utf8_lossy(&head[..n]);
    match line.strip_prefix("HTTP/1.").and_then(|l| l.get(2..5)).filter(|c| c.chars().all(|d| d.is_ascii_digit())) {
        Some(code) => {
            println!("{code}");
            0
        }
        None => 1,
    }
}

#[tokio::main]
async fn main() {
    if std::env::args().nth(1).as_deref() == Some("--health") {
        let port = std::env::var("PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8000);
        std::process::exit(if health_probe(port) { 0 } else { 1 });
    }
    if std::env::args().nth(1).as_deref() == Some("--probe") {
        std::process::exit(probe(&std::env::args().nth(2).unwrap_or_default()));
    }
    let _ = log::set_logger(&LOGGER).map(|()| log::set_max_level(log::LevelFilter::Info));
    let cfg = Arc::new(config::Config::from_env());
    let app = Arc::new(app::App::new(cfg.clone(), config::secret(&cfg.qbit_pass_file), config::secret(&cfg.abr_key_file)));
    tokio::spawn(pipeline::poll(app.clone()));
    let router = axum::Router::new().fallback(http::dispatch).with_state(app);
    let listener = match tokio::net::TcpListener::bind(("0.0.0.0", cfg.port)).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("cannot listen on port {}: {e}", cfg.port);
            std::process::exit(1);
        }
    };
    log::info!("listening on {}", cfg.port);
    if let Err(e) = axum::serve(listener, router.into_make_service_with_connect_info::<SocketAddr>()).await {
        eprintln!("server: {e}");
        std::process::exit(1);
    }
}
