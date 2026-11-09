use std::path::PathBuf;
use std::{env, fs};

use jiff::tz::TimeZone;

#[derive(Clone)]
pub struct Config {
    pub gluetun_ip: String,
    pub qbit_user: String,
    pub qbit_pass: String,
    pub gluetun_user: String,
    pub gluetun_pass: String,
    pub web_user: String,
    pub web_pass: String,
    pub web_port: u16,
    pub check_interval: u64,
    pub session_check_interval: u64,
    pub zero_retry_interval: u64,
    pub zero_port_limit: u32,
    pub stack_restart_backoff: u64,
    pub stack_restart_backoff_max: u64,
    pub docker_url: Option<String>,
    pub data_file: PathBuf,
    pub tz: Option<TimeZone>,
}

/// `$(cat file)` semantics: the value without its trailing newlines.
pub fn strip_trailing_newlines(s: &str) -> &str {
    s.trim_end_matches(['\n', '\r'])
}

/// NAME_FILE (docker secrets convention) wins over NAME.
fn secret(name: &str) -> String {
    match env::var(format!("{name}_FILE")) {
        Ok(path) if !path.is_empty() => match fs::read_to_string(&path) {
            Ok(v) => strip_trailing_newlines(&v).to_string(),
            Err(e) => {
                eprintln!("cannot read {name}_FILE {path}: {e}");
                String::new()
            }
        },
        _ => env::var(name).unwrap_or_default(),
    }
}

fn var(name: &str) -> String {
    env::var(name).unwrap_or_default()
}

fn num<T: std::str::FromStr>(name: &str, default: T) -> T {
    env::var(name).ok().and_then(|v| v.trim().parse().ok()).unwrap_or(default)
}

/// tcp://host:port -> http://host:port; anything else (unix sockets) is not supported.
pub fn docker_url(docker_host: &str) -> Option<String> {
    let rest = docker_host.strip_prefix("tcp://")?;
    valid_host(rest).then(|| format!("http://{}", rest.trim_end_matches('/')))
}

/// A host or host:port that cannot smuggle a path, credentials or a query into a URL.
pub fn valid_host(h: &str) -> bool {
    !h.is_empty() && h.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | ':' | '_' | '[' | ']'))
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let gluetun_ip = env::var("GLUETUN_IP").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| "10.24.32.2".into());
        if !valid_host(&gluetun_ip) {
            return Err(format!("invalid GLUETUN_IP {gluetun_ip:?}"));
        }
        let tz = match var("TZ") {
            t if t.is_empty() => None,
            t => TimeZone::get(&t).ok(),
        };
        let data_dir = env::var("DATA_DIR").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| "/data".into());
        Ok(Config {
            gluetun_ip,
            qbit_user: var("QBIT_USER"),
            qbit_pass: secret("QBIT_PASS"),
            gluetun_user: var("GLUETUN_AUTH_USER"),
            gluetun_pass: secret("GLUETUN_AUTH_PASS"),
            web_user: var("WEB_USER"),
            web_pass: secret("WEB_PASS"),
            web_port: num("WEB_PORT", 8088),
            check_interval: num("CHECK_INTERVAL", 600),
            session_check_interval: num("SESSION_CHECK_INTERVAL", 15u64).max(1),
            zero_retry_interval: num("ZERO_RETRY_INTERVAL", 60),
            zero_port_limit: num("ZERO_PORT_LIMIT", 3),
            stack_restart_backoff: num("STACK_RESTART_BACKOFF", 240),
            stack_restart_backoff_max: num("STACK_RESTART_BACKOFF_MAX", 3600),
            docker_url: docker_url(&var("DOCKER_HOST")),
            data_file: PathBuf::from(data_dir).join("port-history.json"),
            tz,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newlines_stripped_like_command_substitution() {
        assert_eq!(strip_trailing_newlines("pw\n\n"), "pw");
        assert_eq!(strip_trailing_newlines(" pw x \n"), " pw x ");
        assert_eq!(strip_trailing_newlines("a\nb\n"), "a\nb");
    }

    #[test]
    fn docker_host_tcp_only() {
        assert_eq!(docker_url("tcp://socket-proxy-portupdater:2375").as_deref(), Some("http://socket-proxy-portupdater:2375"));
        assert_eq!(docker_url("unix:///var/run/docker.sock"), None);
        assert_eq!(docker_url("tcp://evil/x?y"), None);
        assert_eq!(docker_url("tcp://user@host:1"), None);
        assert_eq!(docker_url(""), None);
    }

    #[test]
    fn host_validation() {
        assert!(valid_host("10.24.32.2"));
        assert!(valid_host("127.0.0.1"));
        assert!(!valid_host("10.0.0.1/admin"));
        assert!(!valid_host("a@b"));
        assert!(!valid_host(""));
    }
}
