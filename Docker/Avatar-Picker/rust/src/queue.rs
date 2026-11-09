//! Pending-pick queue on disk (username -> latest pick), read by scripts/avatar-sync.py on the host.
//! Written byte-identical to Python's json.dumps(indent=1, sort_keys=True) + "\n".

use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use serde_json::{json, Map, Value};

use crate::core;

pub fn load(path: &Path) -> Map<String, Value> {
    fs::read(path)
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        .and_then(|v| match v {
            Value::Object(m) => Some(m),
            _ => None,
        })
        .unwrap_or_default()
}

fn escape(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_value(v: &Value, depth: usize, out: &mut String) {
    match v {
        Value::Object(m) if !m.is_empty() => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            out.push('{');
            for (i, k) in keys.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                out.push_str(&" ".repeat(depth + 1));
                escape(k, out);
                out.push_str(": ");
                write_value(&m[k.as_str()], depth + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(depth));
            out.push('}');
        }
        Value::Array(a) if !a.is_empty() => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                out.push_str(&" ".repeat(depth + 1));
                write_value(x, depth + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(depth));
            out.push(']');
        }
        Value::String(s) => escape(s, out),
        other => out.push_str(&other.to_string()),
    }
}

pub fn render(data: &Map<String, Value>) -> String {
    let mut out = String::new();
    write_value(&Value::Object(data.clone()), 0, &mut out);
    out.push('\n');
    out
}

fn save(path: &Path, data: &Map<String, Value>) -> io::Result<()> {
    let mut name = path.file_name().ok_or_else(|| io::Error::other("queue path has no file name"))?.to_os_string();
    name.push(".tmp");
    let tmp = path.with_file_name(name);
    let mut f = fs::File::create(&tmp)?;
    f.write_all(render(data).as_bytes())?;
    drop(f);
    fs::set_permissions(&tmp, fs::Permissions::from_mode(0o644))?;
    fs::rename(&tmp, path)
}

pub fn record(path: &Path, username: &str, avatar: &str, now: &str) -> io::Result<()> {
    let mut data = load(path);
    data.insert(username.to_string(), json!({"avatar": avatar, "at": now}));
    save(path, &data)
}

/// Queues the current pick of every user not in the queue yet.
pub fn backfill(path: &Path, users: &[Value], base: &str, now: &str) -> io::Result<Vec<String>> {
    let mut data = load(path);
    let mut added = Vec::new();
    for u in users {
        let avatar = u.get("attributes").and_then(Value::as_object).and_then(|a| a.get("avatar"));
        if let Some(aid) = core::id_from_url(base, avatar) {
            let name = core::username(u);
            if !data.contains_key(name) {
                data.insert(name.to_string(), json!({"avatar": aid, "at": now}));
                added.push(name.to_string());
            }
        }
    }
    if !added.is_empty() {
        save(path, &data)?;
    }
    Ok(added)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("apq-{}-{name}", std::process::id()));
        fs::create_dir_all(&d).unwrap();
        d.join("queue.json")
    }

    #[test]
    fn python_layout() {
        let mut m = Map::new();
        m.insert("zed".into(), json!({"avatar": "a", "at": "t"}));
        m.insert("jörg".into(), json!({"avatar": "b", "at": "t"}));
        m.insert("amy".into(), json!({"list": [1, "x"], "e": {}, "n": null, "f": [], "q": "a\"b\\\n\u{1}"}));
        let want = "{\n \"amy\": {\n  \"e\": {},\n  \"f\": [],\n  \"list\": [\n   1,\n   \"x\"\n  ],\n  \"n\": null,\n  \"q\": \"a\\\"b\\\\\\n\\u0001\"\n },\n \"j\\u00f6rg\": {\n  \"at\": \"t\",\n  \"avatar\": \"b\"\n },\n \"zed\": {\n  \"at\": \"t\",\n  \"avatar\": \"a\"\n }\n}\n";
        assert_eq!(render(&m), want);
        assert_eq!(render(&Map::new()), "{}\n");
    }

    #[test]
    fn astral_chars_as_surrogates() {
        let mut m = Map::new();
        m.insert("k".into(), json!("😀\u{7f}"));
        assert_eq!(render(&m), "{\n \"k\": \"\\ud83d\\ude00\\u007f\"\n}\n");
    }

    #[test]
    fn record_and_backfill() {
        let p = tmp("rb");
        fs::write(&p, b"[1,2]").unwrap();
        assert!(load(&p).is_empty());
        record(&p, "bob", "beta", "T1").unwrap();
        assert_eq!(fs::metadata(&p).unwrap().permissions().mode() & 0o777, 0o644);
        let base = "https://x/avatar-img";
        let users = vec![
            json!({"username": "alice", "attributes": {"avatar": "https://x/avatar-img/img/alpha.png"}}),
            json!({"username": "bob", "attributes": {"avatar": "https://x/avatar-img/img/gamma.png"}}),
            json!({"username": "carol", "attributes": null}),
        ];
        assert_eq!(backfill(&p, &users, base, "T2").unwrap(), vec!["alice".to_string()]);
        let q = load(&p);
        assert_eq!(q["alice"], json!({"avatar": "alpha", "at": "T2"}));
        assert_eq!(q["bob"], json!({"avatar": "beta", "at": "T1"}));
        assert!(!p.with_file_name("queue.json.tmp").exists());
        fs::remove_dir_all(p.parent().unwrap()).unwrap();
    }
}
