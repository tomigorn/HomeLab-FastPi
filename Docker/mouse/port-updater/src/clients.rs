//! Outbound HTTP: qBittorrent WebUI, gluetun control server, Docker API (through socket-proxy-portupdater). Every call has a timeout.
use std::time::Duration;

use base64::Engine;
use serde_json::Value;
use ureq::Agent;

pub fn agent(timeout: Duration) -> Agent {
    Agent::config_builder()
        .timeout_global(Some(timeout))
        .http_status_as_error(false)
        .max_redirects(0)
        .max_redirects_will_error(false)
        .proxy(None)
        .user_agent("port-updater/2")
        .build()
        .into()
}

pub fn basic(user: &str, pass: &str) -> String {
    format!("Basic {}", base64::engine::general_purpose::STANDARD.encode(format!("{user}:{pass}")))
}

/// `curl -s -o /dev/null -w %{http_code}`: 0 when the request failed.
pub fn status(resp: Result<ureq::http::Response<ureq::Body>, ureq::Error>) -> u16 {
    resp.map(|r| r.status().as_u16()).unwrap_or(0)
}

/// `curl -s URL`: the body whatever the status, None when the request failed.
pub fn body(resp: Result<ureq::http::Response<ureq::Body>, ureq::Error>) -> Option<String> {
    let mut r = resp.ok()?;
    r.body_mut().with_config().limit(1 << 20).read_to_string().ok()
}

/// `jq -r '.KEY // empty'`: Ok(None) for no output, Err where jq would fail (the input is not JSON or not an object).
pub fn jq_field(body: &str, key: &str) -> Result<Option<Value>, String> {
    if body.trim().is_empty() {
        return Ok(None);
    }
    let v: Value = serde_json::from_str(body).map_err(|e| format!("jq: error: cannot parse {:?}: {e}", short(body)))?;
    match v {
        Value::Null => Ok(None),
        Value::Object(mut m) => Ok(m.remove(key).filter(|v| !matches!(v, Value::Null | Value::Bool(false)))),
        other => Err(format!("jq: error: cannot index {} with \"{key}\"", kind(&other))),
    }
}

fn kind(v: &Value) -> &'static str {
    match v {
        Value::Array(_) => "array",
        Value::String(_) => "string",
        Value::Number(_) => "number",
        Value::Bool(_) => "boolean",
        _ => "value",
    }
}

fn short(s: &str) -> String {
    s.chars().take(80).collect()
}

/// What `jq -r` prints for a value.
pub fn raw(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// A forwarded port is a number in 1..=65535 or 0; anything else counts as no answer.
pub fn port(v: Option<&Value>) -> Option<u64> {
    v.and_then(Value::as_u64).filter(|p| *p <= 65535)
}

/// Every Set-Cookie name=value pair, joined like a Cookie header.
pub fn cookies(resp: &ureq::http::Response<ureq::Body>) -> Option<String> {
    let pairs: Vec<&str> = resp
        .headers()
        .get_all("set-cookie")
        .iter()
        .filter_map(|v| v.to_str().ok())
        .filter_map(|v| v.split(';').next())
        .map(str::trim)
        .filter(|p| p.contains('='))
        .collect();
    (!pairs.is_empty()).then(|| pairs.join("; "))
}

pub struct Docker {
    base: Option<String>,
    agent: Agent,
}

impl Docker {
    pub fn new(base: Option<String>) -> Self {
        Docker { base, agent: agent(Duration::from_secs(120)) }
    }

    fn url(&self, path: &str) -> Result<String, String> {
        match &self.base {
            Some(b) => Ok(format!("{b}{path}")),
            None => Err("Cannot connect to the Docker daemon: DOCKER_HOST must be tcp://host:port".into()),
        }
    }

    /// `docker inspect --format '{{.State.Health.Status}}' NAME`.
    pub fn health(&self, name: &str) -> Option<String> {
        let url = self.url(&format!("/containers/{name}/json")).ok()?;
        let mut r = self.agent.get(&url).config().timeout_global(Some(Duration::from_secs(10))).build().call().ok()?;
        if r.status().as_u16() != 200 {
            return None;
        }
        let v: Value = serde_json::from_str(&r.body_mut().with_config().limit(4 << 20).read_to_string().ok()?).ok()?;
        v.pointer("/State/Health/Status").and_then(Value::as_str).map(str::to_string)
    }

    /// `docker ACTION NAME...`: every container is tried; Err lists the failures, like the CLI's non-zero exit.
    pub fn act(&self, action: &str, names: &[&str]) -> Result<(), String> {
        let mut errs = Vec::new();
        for name in names {
            let res = self.url(&format!("/containers/{name}/{action}")).and_then(|url| self.agent.post(&url).send_empty().map_err(|e| e.to_string()));
            match res {
                Ok(r) if r.status().is_success() || r.status().as_u16() == 304 => println!("{name}"),
                Ok(mut r) => {
                    let code = r.status().as_u16();
                    let b = r.body_mut().with_config().limit(64 << 10).read_to_string().unwrap_or_default();
                    errs.push(format!("Error response from daemon ({code}) for {name}: {}", b.trim()));
                }
                Err(e) => errs.push(format!("{name}: {e}")),
            }
        }
        if errs.is_empty() {
            Ok(())
        } else {
            for e in &errs {
                eprintln!("{e}");
            }
            Err(errs.join("; "))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn jq_like_extraction() {
        assert_eq!(jq_field("{\"port\":43688}", "port").unwrap(), Some(json!(43688)));
        assert_eq!(jq_field("{\"port\":0}", "port").unwrap(), Some(json!(0)));
        assert_eq!(jq_field("{\"port\":null}", "port").unwrap(), None);
        assert_eq!(jq_field("{\"other\":1}", "port").unwrap(), None);
        assert_eq!(jq_field("{\"port\":false}", "port").unwrap(), None);
        assert_eq!(jq_field("", "port").unwrap(), None);
        assert_eq!(jq_field("  \n", "port").unwrap(), None);
        assert_eq!(jq_field("null", "port").unwrap(), None);
        assert!(jq_field("Unauthorized\n", "port").is_err());
        assert!(jq_field("Forbidden", "listen_port").is_err());
        assert!(jq_field("[1]", "port").is_err());
    }

    #[test]
    fn raw_output() {
        assert_eq!(raw(&json!(1)), "1");
        assert_eq!(raw(&json!("tun0")), "tun0");
    }

    #[test]
    fn port_validation() {
        assert_eq!(port(Some(&json!(45000))), Some(45000));
        assert_eq!(port(Some(&json!(0))), Some(0));
        assert_eq!(port(Some(&json!(70000))), None);
        assert_eq!(port(Some(&json!("45000"))), None);
        assert_eq!(port(Some(&json!(-1))), None);
        assert_eq!(port(None), None);
    }

    #[test]
    fn basic_header() {
        assert_eq!(basic("user", "pa:ss"), "Basic dXNlcjpwYTpzcw==");
    }
}
