//! port-history.json: one JSON object per line, appended; the format is the legacy one byte for byte.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use jiff::Zoned;
use jiff::tz::TimeZone;
use serde_json::Value;

/// `date +%Y-%m-%dT%H:%M:%S%z` in TZ, or `date -u +%Y-%m-%dT%H:%M:%SZ` without one.
pub fn timestamp(tz: Option<&TimeZone>, now: &Zoned) -> String {
    match tz {
        Some(tz) => now.with_time_zone(tz.clone()).strftime("%Y-%m-%dT%H:%M:%S%z").to_string(),
        None => now.with_time_zone(TimeZone::UTC).strftime("%Y-%m-%dT%H:%M:%SZ").to_string(),
    }
}

pub fn banner_time(tz: Option<&TimeZone>, now: &Zoned) -> String {
    match tz {
        Some(tz) => now.with_time_zone(tz.clone()).strftime("%Y-%m-%d %H:%M:%S %Z").to_string(),
        None => now.with_time_zone(TimeZone::UTC).strftime("%Y-%m-%d %H:%M:%S UTC").to_string(),
    }
}

fn js(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"\"".into())
}

pub fn event_line(ts: &str, event: &str, port: u64, old_port: u64, vpn_ip: &str, message: &str) -> String {
    format!(
        "{{\"timestamp\":{},\"event\":{},\"port\":{port},\"old_port\":{old_port},\"vpn_ip\":{},\"message\":{}}}\n",
        js(ts),
        js(event),
        js(vpn_ip),
        js(message)
    )
}

pub fn append(file: &Path, line: &str) {
    if let Some(dir) = file.parent() {
        let _ = fs::create_dir_all(dir);
    }
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(file) {
        let _ = f.write_all(line.as_bytes());
    }
}

/// The history as a JSON array: every line that parses, unchanged, in file order.
pub fn history_json(content: &str) -> String {
    let mut out = String::with_capacity(content.len() + 2);
    out.push('[');
    let mut first = true;
    for line in content.lines().map(str::trim).filter(|l| !l.is_empty()) {
        if serde_json::from_str::<Value>(line).is_err() {
            continue;
        }
        if !first {
            out.push_str(", ");
        }
        out.push_str(line);
        first = false;
    }
    out.push(']');
    out
}

/// vpn_ip of the newest event that has one.
pub fn latest_vpn_ip(content: &str) -> Option<String> {
    content.lines().rev().find_map(|line| match serde_json::from_str::<Value>(line.trim()) {
        Ok(Value::Object(m)) => match m.get("vpn_ip") {
            Some(Value::String(s)) if !s.is_empty() => Some(s.clone()),
            _ => None,
        },
        _ => None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(s: &str) -> Zoned {
        s.parse().unwrap()
    }

    #[test]
    fn timestamp_in_zone_and_utc() {
        let now = at("2026-07-01T12:34:56Z[UTC]");
        let zh = TimeZone::get("Europe/Zurich").unwrap();
        assert_eq!(timestamp(Some(&zh), &now), "2026-07-01T14:34:56+0200");
        assert_eq!(timestamp(Some(&zh), &at("2026-01-01T00:00:00Z[UTC]")), "2026-01-01T01:00:00+0100");
        assert_eq!(timestamp(None, &now), "2026-07-01T12:34:56Z");
        assert_eq!(banner_time(Some(&zh), &now), "2026-07-01 14:34:56 CEST");
        assert_eq!(banner_time(None, &now), "2026-07-01 12:34:56 UTC");
    }

    #[test]
    fn line_matches_legacy_printf() {
        assert_eq!(
            event_line("2026-11-09T02:38:44+0100", "port_update", 43688, 1, "185.159.157.74", "ProtonVPN assigned new port 43688 (was 1)"),
            "{\"timestamp\":\"2026-11-09T02:38:44+0100\",\"event\":\"port_update\",\"port\":43688,\"old_port\":1,\"vpn_ip\":\"185.159.157.74\",\"message\":\"ProtonVPN assigned new port 43688 (was 1)\"}\n"
        );
        assert_eq!(
            event_line("t", "stack_restart", 0, 0, "", "Port remained 0 for 3 cycles — restarting stack"),
            "{\"timestamp\":\"t\",\"event\":\"stack_restart\",\"port\":0,\"old_port\":0,\"vpn_ip\":\"\",\"message\":\"Port remained 0 for 3 cycles — restarting stack\"}\n"
        );
    }

    #[test]
    fn hostile_strings_stay_valid_json() {
        let l = event_line("t", "e", 1, 2, "1.2.3.4\",\"x\":\"", "a\nb");
        let v: Value = serde_json::from_str(l.trim()).unwrap();
        assert_eq!(v["vpn_ip"], "1.2.3.4\",\"x\":\"");
        assert_eq!(v.as_object().unwrap().len(), 6);
    }

    #[test]
    fn history_skips_junk_and_blank_lines() {
        let c = "{\"a\":1}\nnot json\n\n  {\"b\":2}  \n{broken\n";
        assert_eq!(history_json(c), "[{\"a\":1}, {\"b\":2}]");
        assert_eq!(history_json(""), "[]");
        let v: Value = serde_json::from_str(&history_json(c)).unwrap();
        assert_eq!(v.as_array().unwrap().len(), 2);
    }

    #[test]
    fn latest_vpn_ip_is_newest_non_empty() {
        let c = "{\"vpn_ip\":\"1.1.1.1\"}\n{\"vpn_ip\":\"2.2.2.2\"}\n{\"vpn_ip\":\"\"}\njunk\n";
        assert_eq!(latest_vpn_ip(c).as_deref(), Some("2.2.2.2"));
        assert_eq!(latest_vpn_ip("{\"vpn_ip\":\"\"}\n"), None);
        assert_eq!(latest_vpn_ip(""), None);
    }

    #[test]
    fn append_creates_dir_and_appends() {
        let dir = std::env::temp_dir().join(format!("pu-test-{}", std::process::id()));
        let f = dir.join("sub/port-history.json");
        append(&f, "a\n");
        append(&f, "b\n");
        assert_eq!(fs::read_to_string(&f).unwrap(), "a\nb\n");
        let _ = fs::remove_dir_all(dir);
    }
}
