//! beefy's boot list over the read-only forced-command SSH key (beefy answers `journalctl --list-boots -o json` whatever is asked).

use std::sync::Arc;
use std::time::Duration;

use russh::client;
use russh::keys::{load_secret_key, PrivateKeyWithHashAlg, PublicKeyOrCertificate};
use russh::ChannelMsg;
use tokio::net::TcpStream;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(4);
pub const TOTAL_TIMEOUT: Duration = Duration::from_secs(12);
const MAX_OUTPUT: usize = 4 << 20;

/// Outcome in the shape of the old `ssh` subprocess: exit code (255 = ssh itself failed), stdout, error text.
pub struct Run {
    pub code: i32,
    pub stdout: String,
    pub error: String,
}

/// Keys pinned for `host` (port 22) in a plain known_hosts file: (type, base64).
pub fn known_keys(text: &str, host: &str) -> Vec<(String, String)> {
    let bracket = format!("[{host}]:22");
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#') && !l.starts_with('@'))
        .filter_map(|l| {
            let mut f = l.split_whitespace();
            let (hosts, kind, b64) = (f.next()?, f.next()?, f.next()?);
            hosts.split(',').any(|h| h == host || h == bracket).then(|| (kind.to_string(), b64.to_string()))
        })
        .collect()
}

struct Pinned {
    keys: Vec<(String, String)>,
}

impl client::Handler for Pinned {
    type Error = russh::Error;

    async fn check_server_key(&mut self, key: &PublicKeyOrCertificate) -> Result<bool, Self::Error> {
        let PublicKeyOrCertificate::PublicKey { key, .. } = key else { return Ok(false) };
        let Ok(text) = key.to_openssh() else { return Ok(false) };
        let mut f = text.split_whitespace();
        let (kind, b64) = (f.next().unwrap_or(""), f.next().unwrap_or(""));
        Ok(self.keys.iter().any(|(k, b)| k == kind && b == b64))
    }
}

pub async fn fetch(host: &str, user: &str, key_path: &str, known_hosts: &str) -> Result<Run, String> {
    match tokio::time::timeout(TOTAL_TIMEOUT, run(host, user, key_path, known_hosts)).await {
        Ok(r) => Ok(r),
        Err(_) => Err(format!("ssh timed out after {} seconds", TOTAL_TIMEOUT.as_secs())),
    }
}

async fn run(host: &str, user: &str, key_path: &str, known_hosts: &str) -> Run {
    match session(host, user, key_path, known_hosts).await {
        Ok((code, out)) => Run { code, stdout: String::from_utf8_lossy(&out).into_owned(), error: String::new() },
        Err(e) => Run { code: 255, stdout: String::new(), error: e },
    }
}

async fn session(host: &str, user: &str, key_path: &str, known_hosts: &str) -> Result<(i32, Vec<u8>), String> {
    let text = std::fs::read_to_string(known_hosts).map_err(|e| format!("known_hosts: {e}"))?;
    let keys = known_keys(&text, host);
    if keys.is_empty() {
        return Err(format!("no host key for {host} in known_hosts"));
    }
    let key = load_secret_key(key_path, None).map_err(|e| format!("key: {e}"))?;
    let tcp = match tokio::time::timeout(CONNECT_TIMEOUT, TcpStream::connect((host, 22))).await {
        Ok(Ok(s)) => s,
        Ok(Err(e)) => return Err(format!("connect to {host} port 22: {e}")),
        Err(_) => return Err(format!("connect to {host} port 22: Connection timed out")),
    };
    let config = Arc::new(client::Config { inactivity_timeout: Some(TOTAL_TIMEOUT), ..Default::default() });
    let mut s = client::connect_stream(config, tcp, Pinned { keys }).await.map_err(|e| format!("handshake: {e}"))?;
    let hash = s.best_supported_rsa_hash().await.map_err(|e| e.to_string())?.flatten();
    let auth = s
        .authenticate_publickey(user, PrivateKeyWithHashAlg::new(Arc::new(key), hash))
        .await
        .map_err(|e| format!("auth: {e}"))?;
    if !auth.success() {
        return Err("Permission denied (publickey).".into());
    }
    let mut ch = s.channel_open_session().await.map_err(|e| e.to_string())?;
    ch.request_shell(true).await.map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    let mut code = None;
    while let Some(msg) = ch.wait().await {
        match msg {
            ChannelMsg::Data { data } => {
                if out.len() + data.len() > MAX_OUTPUT {
                    return Err("output too large".into());
                }
                out.extend_from_slice(&data);
            }
            ChannelMsg::ExitStatus { exit_status } => code = Some(exit_status as i32),
            _ => {}
        }
    }
    let _ = s.disconnect(russh::Disconnect::ByApplication, "", "en").await;
    Ok((code.unwrap_or(255), out))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_hosts_lines() {
        let t = "# c\n192.0.2.1 ssh-ed25519 AAAA1\n[192.0.2.1]:22,other ssh-rsa BBBB\n192.0.2.10 ssh-ed25519 CCCC\n@revoked 192.0.2.1 ssh-ed25519 DDDD\n|1|hash|x ssh-ed25519 EEEE\n";
        assert_eq!(known_keys(t, "192.0.2.1"), vec![("ssh-ed25519".into(), "AAAA1".into()), ("ssh-rsa".into(), "BBBB".into())]);
        assert!(known_keys(t, "192.0.2.2").is_empty());
    }
}
