use std::collections::{HashMap, HashSet};

use serde_json::{json, Map, Value};

#[derive(Debug, PartialEq)]
pub enum PickError {
    Taken,
    UnknownUser,
}

pub fn avatar_url(base: &str, id: &str) -> String {
    format!("{}/img/{id}.png", base.trim_end_matches('/'))
}

pub fn id_from_url(base: &str, url: Option<&Value>) -> Option<String> {
    let url = url?.as_str()?;
    let prefix = format!("{}/img/", base.trim_end_matches('/'));
    url.strip_prefix(&prefix)?.strip_suffix(".png").map(str::to_string)
}

fn avatar_attr(user: &Value) -> Option<&Value> {
    user.get("attributes")?.as_object()?.get("avatar")
}

pub fn username(user: &Value) -> &str {
    user.get("username").and_then(Value::as_str).unwrap_or("")
}

/// avatar id -> username of its holder
pub fn holders(users: &[Value], base: &str) -> HashMap<String, String> {
    let mut held = HashMap::new();
    for u in users {
        if let Some(aid) = id_from_url(base, avatar_attr(u)) {
            held.insert(aid, username(u).to_string());
        }
    }
    held
}

pub fn picked_ids(users: &[Value], base: &str) -> HashSet<String> {
    holders(users, base).into_keys().collect()
}

pub fn gallery_state(gallery: &[Value], users: &[Value], base: &str, caller: &str, thumbs: &HashMap<String, String>) -> Vec<Value> {
    let held = holders(users, base);
    gallery
        .iter()
        .map(|g| {
            let id = g.get("id").and_then(Value::as_str).unwrap_or("");
            let status = match held.get(id) {
                None => "free",
                Some(h) if h == caller => "mine",
                Some(_) => "taken",
            };
            let mut o = Map::new();
            o.insert("id".into(), json!(id));
            o.insert("name".into(), g.get("name").cloned().unwrap_or(Value::Null));
            o.insert("url".into(), json!(avatar_url(base, id)));
            o.insert("color".into(), g.get("color").cloned().unwrap_or(Value::Null));
            o.insert("group".into(), g.get("group").cloned().unwrap_or(Value::Null));
            o.insert("status".into(), json!(status));
            if let Some(h) = thumbs.get(id) {
                o.insert("thumb".into(), json!(format!("thumb/{id}.{h}")));
            }
            Value::Object(o)
        })
        .collect()
}

/// Validates a pick of a known avatar id; returns the caller's user pk.
pub fn check_pick(users: &[Value], base: &str, caller: &str, id: &str) -> Result<i64, PickError> {
    if let Some(holder) = holders(users, base).get(id) {
        if holder != caller {
            return Err(PickError::Taken);
        }
    }
    users
        .iter()
        .find(|u| username(u) == caller)
        .and_then(|u| u.get("pk").and_then(Value::as_i64))
        .ok_or(PickError::UnknownUser)
}

pub fn merged_attributes(current: Option<&Value>, base: &str, id: &str) -> Value {
    let mut m = current.and_then(Value::as_object).cloned().unwrap_or_default();
    m.insert("avatar".into(), json!(avatar_url(base, id)));
    Value::Object(m)
}

pub fn session_cookie(header: &str) -> &str {
    for part in header.split(';') {
        let part = part.trim();
        let (name, value) = part.split_once('=').unwrap_or((part, ""));
        if name == "authentik_session" {
            return value.trim();
        }
    }
    ""
}

pub fn thumb_name_ok(name: &str) -> bool {
    let Some(rest) = name.strip_suffix(".webp") else { return false };
    let Some((rest, width)) = rest.rsplit_once('.') else { return false };
    if width != "160" && width != "320" {
        return false;
    }
    let Some((id, hash)) = rest.rsplit_once('.') else { return false };
    !id.is_empty()
        && id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        && hash.len() == 10
        && hash.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// Header bytes as UTF-8; anything else as Latin-1, like the previous server.
pub fn header_text(raw: &[u8]) -> String {
    match std::str::from_utf8(raw) {
        Ok(s) => s.to_string(),
        Err(_) => raw.iter().map(|&b| b as char).collect(),
    }
}

pub fn utc_timestamp(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", rem / 3600, rem % 3600 / 60, rem % 60)
}

#[cfg(test)]
mod tests {
    use super::*;

    const B: &str = "https://sso.example.com/avatar-img";

    fn users() -> Vec<Value> {
        vec![
            json!({"pk": 1, "username": "alice", "attributes": {"avatar": format!("{B}/img/alpha.png")}}),
            json!({"pk": 2, "username": "bob", "attributes": {"theme": "dark"}}),
            json!({"pk": 3, "username": "carol", "attributes": null}),
            json!({"pk": 4, "username": "dave", "attributes": {"avatar": "https://other/img/beta.png"}}),
        ]
    }

    #[test]
    fn urls() {
        assert_eq!(avatar_url(&format!("{B}/"), "x"), format!("{B}/img/x.png"));
        assert_eq!(id_from_url(B, Some(&json!(format!("{B}/img/x-1.png")))), Some("x-1".into()));
        assert_eq!(id_from_url(B, Some(&json!(format!("{B}/img/x.jpg")))), None);
        assert_eq!(id_from_url(B, Some(&json!(format!("{B}/img/.png")))), Some("".into()));
        assert_eq!(id_from_url(B, Some(&json!(5))), None);
        assert_eq!(id_from_url(B, None), None);
    }

    #[test]
    fn picks() {
        let u = users();
        assert_eq!(picked_ids(&u, B), HashSet::from(["alpha".to_string()]));
        assert_eq!(check_pick(&u, B, "bob", "alpha"), Err(PickError::Taken));
        assert_eq!(check_pick(&u, B, "alice", "alpha"), Ok(1));
        assert_eq!(check_pick(&u, B, "bob", "beta"), Ok(2));
        assert_eq!(check_pick(&u, B, "zed", "beta"), Err(PickError::UnknownUser));
    }

    #[test]
    fn state_hides_holder() {
        let g = vec![json!({"id": "alpha", "name": "A", "color": "#1", "group": "g"}), json!({"id": "beta", "name": "B", "color": "#2"})];
        let t = HashMap::from([("beta".to_string(), "0123456789".to_string())]);
        let s = gallery_state(&g, &users(), B, "bob", &t);
        assert_eq!(s[0]["status"], "taken");
        assert_eq!(s[1]["status"], "free");
        assert_eq!(s[1]["group"], Value::Null);
        assert_eq!(s[1]["thumb"], "thumb/beta.0123456789");
        assert!(s[0].get("thumb").is_none());
        assert_eq!(gallery_state(&g, &users(), B, "alice", &t)[0]["status"], "mine");
    }

    #[test]
    fn merge_keeps_other_attributes() {
        assert_eq!(merged_attributes(Some(&json!({"theme": "dark"})), B, "x"), json!({"theme": "dark", "avatar": format!("{B}/img/x.png")}));
        assert_eq!(merged_attributes(Some(&Value::Null), B, "x"), json!({"avatar": format!("{B}/img/x.png")}));
    }

    #[test]
    fn cookies() {
        assert_eq!(session_cookie("a=1; authentik_session=abc ; b=2"), "abc");
        assert_eq!(session_cookie("xauthentik_session=abc"), "");
        assert_eq!(session_cookie(""), "");
        assert_eq!(session_cookie("authentik_session"), "");
    }

    #[test]
    fn thumb_names() {
        assert!(thumb_name_ok("a-1.0123456789.160.webp"));
        assert!(thumb_name_ok("a.abcdef0123.320.webp"));
        assert!(!thumb_name_ok("a.abcdef0123.640.webp"));
        assert!(!thumb_name_ok("A.abcdef0123.320.webp"));
        assert!(!thumb_name_ok("a.abcdef012.320.webp"));
        assert!(!thumb_name_ok("a.ABCDEF0123.320.webp"));
        assert!(!thumb_name_ok(".abcdef0123.320.webp"));
        assert!(!thumb_name_ok("../a.abcdef0123.320.webp"));
        assert!(!thumb_name_ok("a.b.abcdef0123.320.webp"));
    }

    #[test]
    fn secrets_compare() {
        assert!(constant_time_eq(b"abc", b"abc"));
        assert!(!constant_time_eq(b"abc", b"abd"));
        assert!(!constant_time_eq(b"abc", b"abcd"));
    }

    #[test]
    fn header_decoding() {
        assert_eq!(header_text("jörg".as_bytes()), "jörg");
        assert_eq!(header_text(&[b'j', 0xf6, b'r', b'g']), "jörg");
    }

    #[test]
    fn timestamps() {
        assert_eq!(utc_timestamp(0), "1970-01-01T00:00:00Z");
        assert_eq!(utc_timestamp(1_709_210_096), "2024-02-29T12:34:56Z");
        assert_eq!(utc_timestamp(1_798_761_599), "2026-12-31T23:59:59Z");
    }
}
