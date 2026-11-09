//! Subcommands for the healthcheck, post-update check, smoke test and token rotation (the image has no shell or Python).
//! Secrets are read inside the container and never printed.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use serde_json::Value;

use crate::{app_dir, client_from_env, core, listen_addr, load_gallery};

const USAGE: &str = "usage: avatar-picker [healthcheck | version | check local-pack|favicon|state [user]|thumbs|secret-required|queue|picked|token]";

struct Resp {
    status: u16,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

impl Resp {
    fn header(&self, name: &str) -> &str {
        self.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str()).unwrap_or("None")
    }
}

fn get(path: &str, headers: &[(&str, &str)]) -> std::io::Result<Resp> {
    let addr: SocketAddr = listen_addr().replace("0.0.0.0", "127.0.0.1").parse().map_err(|_| std::io::Error::other("bad LISTEN"))?;
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_secs(5))?;
    s.set_read_timeout(Some(Duration::from_secs(15)))?;
    let mut req = format!("GET {path} HTTP/1.0\r\nHost: localhost\r\n");
    for (k, v) in headers {
        req.push_str(&format!("{k}: {v}\r\n"));
    }
    req.push_str("\r\n");
    s.write_all(req.as_bytes())?;
    let mut raw = Vec::new();
    s.read_to_end(&mut raw)?;
    let split = raw.windows(4).position(|w| w == b"\r\n\r\n").ok_or_else(|| std::io::Error::other("bad response"))?;
    let head = String::from_utf8_lossy(&raw[..split]).to_string();
    let mut lines = head.split("\r\n");
    let status = lines.next().and_then(|l| l.split(' ').nth(1)).and_then(|c| c.parse().ok()).unwrap_or(0);
    let headers = lines.filter_map(|l| l.split_once(':').map(|(k, v)| (k.trim().to_string(), v.trim().to_string()))).collect();
    Ok(Resp { status, headers, body: raw[split + 4..].to_vec() })
}

fn secret() -> String {
    std::env::var("PICKER_SECRET_FILE").ok().and_then(|p| std::fs::read_to_string(p).ok()).map(|s| s.trim().to_string()).unwrap_or_default()
}

fn status_of(r: std::io::Result<Resp>) -> String {
    r.map(|r| r.status.to_string()).unwrap_or_else(|e| format!("error {e}"))
}

pub async fn run(args: &[String]) -> i32 {
    let a: Vec<&str> = args.iter().map(String::as_str).collect();
    match a.as_slice() {
        ["healthcheck"] => match get("/healthz", &[]) {
            Ok(r) if r.status == 200 => 0,
            _ => 1,
        },
        ["version"] => {
            println!("{}", std::fs::read_to_string(app_dir().join("VERSION")).map(|s| s.trim().to_string()).unwrap_or_else(|_| "dev".into()));
            0
        }
        ["check", "local-pack"] => {
            let dir = app_dir();
            let gallery: Vec<Value> = std::fs::read(dir.join("gallery.json")).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default();
            let local: Vec<&str> = gallery.iter().filter(|g| g.get("pack").and_then(Value::as_str) == Some("local")).filter_map(|g| g.get("file").and_then(Value::as_str)).collect();
            let missing = local.iter().filter(|f| !dir.join("img-local").join(f).exists()).count();
            println!("{} local, {missing} missing", local.len());
            0
        }
        ["check", "favicon"] => {
            println!("{} {}", status_of(get("/favicon.svg", &[])), status_of(get("/favicon-32.png", &[])));
            0
        }
        ["check", "state", rest @ ..] => {
            let user = rest.first().copied().unwrap_or("post-update-check");
            let s = secret();
            match get("/api/state", &[("X-Picker-Secret", &s), ("X-authentik-username", user)]) {
                Ok(r) if r.status == 200 => {
                    let d: Value = serde_json::from_slice(&r.body).unwrap_or_default();
                    let avatars = d["avatars"].as_array().cloned().unwrap_or_default();
                    let lotr = avatars.iter().filter(|x| x["group"] == "lotr").count();
                    println!("200 groups={} avatars={} lotr={lotr}", d["groups"].as_array().map_or(0, Vec::len), avatars.len());
                }
                Ok(r) => println!("{} {}", r.status, String::from_utf8_lossy(&r.body).chars().take(60).collect::<String>()),
                Err(e) => println!("error {e}"),
            }
            0
        }
        ["check", "thumbs"] => {
            let Ok(g) = load_gallery(&app_dir()) else {
                println!("gallery unreadable");
                return 1;
            };
            let s = secret();
            let mut thumbs: Vec<(&String, &String)> = g.thumbs.iter().collect();
            thumbs.sort();
            let (aid, h) = thumbs.first().map(|(a, h)| (a.as_str(), h.as_str())).unwrap_or(("-", "-"));
            let cc = get(&format!("/thumb/{aid}.{h}.320.webp"), &[("X-Picker-Secret", &s)]).map(|r| r.header("Cache-Control").to_string()).unwrap_or_else(|e| format!("error {e}"));
            let cc = if cc == "private, max-age=31536000, immutable" { "private immutable".to_string() } else { cc };
            let z = get("/", &[("X-Picker-Secret", &s), ("X-authentik-username", "post-update-check"), ("Accept-Encoding", "gzip")]).map(|r| r.header("Content-Encoding").to_string()).unwrap_or_else(|e| format!("error {e}"));
            let n = if g.thumb_files.len() == 2 * g.thumbs.len() { g.thumbs.len().to_string() } else { "missing files".into() };
            println!("{n}/{} thumbs, {cc}, {z}", g.ids.len());
            0
        }
        ["check", "secret-required"] => {
            println!("{}", status_of(get("/api/state", &[("X-authentik-username", "post-update-check")])));
            0
        }
        ["check", "queue"] => {
            let ok = std::env::var("QUEUE_FILE").ok().and_then(|p| std::fs::read(p).ok()).and_then(|b| serde_json::from_slice::<Value>(&b).ok()).is_some();
            println!("{}", if ok { "ok" } else { "unreadable" });
            i32::from(!ok)
        }
        ["check", "picked"] => {
            let Ok(g) = load_gallery(&app_dir()) else {
                println!("gallery unreadable");
                return 1;
            };
            let base = std::env::var("PUBLIC_BASE_URL").unwrap_or_default();
            match client_from_env().list_users().await {
                Ok(users) => {
                    let held = core::picked_ids(&users, &base);
                    let mut ids: Vec<&String> = g.ids.iter().collect();
                    ids.sort();
                    let picked = ids.iter().find(|i| held.contains(i.as_str())).map_or("-", |s| s.as_str());
                    let unpicked = ids.iter().find(|i| !held.contains(i.as_str())).map_or("-", |s| s.as_str());
                    println!("{picked} {unpicked}");
                    0
                }
                Err(e) => {
                    println!("error {e}");
                    1
                }
            }
        }
        ["check", "token"] => match client_from_env().call(hyper::Method::GET, "/api/v3/core/users/?page_size=1", None).await {
            Ok(d) if d.get("results").is_some() => {
                println!("TOKEN_OK");
                0
            }
            _ => {
                println!("TOKEN_BAD");
                1
            }
        },
        _ => {
            eprintln!("{USAGE}");
            2
        }
    }
}
