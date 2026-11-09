use chrono::{DateTime, NaiveDate, NaiveDateTime, TimeZone, Utc};
use percent_encoding::{utf8_percent_encode, AsciiSet, NON_ALPHANUMERIC};
use serde_json::Value;
use std::time::{SystemTime, UNIX_EPOCH};

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

pub fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

pub fn str_of(v: Option<&Value>) -> Option<&str> {
    v.and_then(Value::as_str)
}

/// Python's truthiness for the JSON values the importer looks at.
pub fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Like urllib.parse.quote(s, safe=""): only unreserved characters stay.
const STRICT: &AsciiSet = &NON_ALPHANUMERIC.remove(b'_').remove(b'.').remove(b'-').remove(b'~');
/// Like urllib.parse.quote(s): the default keeps "/".
const PATH: &AsciiSet = &STRICT.remove(b'/');

pub fn percent_encode_strict(s: &str) -> String {
    utf8_percent_encode(s, STRICT).to_string()
}

pub fn percent_encode_path(s: &str) -> String {
    utf8_percent_encode(s, PATH).to_string()
}

/// datetime.fromisoformat(...).timestamp(): naive times count as UTC (ABR stores UTC); unparseable = 0.
pub fn iso_timestamp(value: &str) -> f64 {
    let v = value.trim();
    if let Ok(dt) = DateTime::parse_from_rfc3339(v) {
        return dt.timestamp() as f64 + f64::from(dt.timestamp_subsec_micros()) / 1e6;
    }
    for fmt in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S%.f%:z", "%Y-%m-%dT%H:%M:%S%.f%z"] {
        if let Ok(dt) = NaiveDateTime::parse_from_str(v, fmt) {
            let dt = Utc.from_utc_datetime(&dt);
            return dt.timestamp() as f64 + f64::from(dt.timestamp_subsec_micros()) / 1e6;
        }
        if let Ok(dt) = DateTime::parse_from_str(v, fmt) {
            return dt.timestamp() as f64 + f64::from(dt.timestamp_subsec_micros()) / 1e6;
        }
    }
    if let Ok(d) = NaiveDate::parse_from_str(v, "%Y-%m-%d") {
        return Utc.from_utc_datetime(&d.and_hms_opt(0, 0, 0).unwrap_or_default()).timestamp() as f64;
    }
    0.0
}

/// time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
pub fn iso_utc(ts: f64) -> String {
    Utc.timestamp_opt(ts.floor() as i64, 0).single().map(|d| d.format("%Y-%m-%dT%H:%M:%SZ").to_string()).unwrap_or_default()
}

pub fn parse_qs(query: &str) -> Vec<(String, String)> {
    form_urlencoded::parse(query.as_bytes()).into_owned().collect()
}

pub fn first_query(query: &str, key: &str) -> Option<String> {
    parse_qs(query).into_iter().find(|(k, _)| k == key).map(|(_, v)| v)
}

pub fn write_atomic(path: &std::path::Path, text: &str) -> std::io::Result<()> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamps() {
        assert_eq!(iso_timestamp("2026-01-01T00:00:00"), 1767225600.0);
        assert_eq!(iso_timestamp("2026-01-01T00:00:00.500000"), 1767225600.5);
        assert_eq!(iso_timestamp("2026-01-01T00:00:00+00:00"), 1767225600.0);
        assert_eq!(iso_timestamp("2026-01-01T01:00:00+01:00"), 1767225600.0);
        assert_eq!(iso_timestamp("2026-01-01"), 1767225600.0);
        assert_eq!(iso_timestamp("nope"), 0.0);
        assert_eq!(iso_utc(1767225600.9), "2026-01-01T00:00:00Z");
    }

    #[test]
    fn quoting() {
        assert_eq!(percent_encode_strict("https://x/t/1 a"), "https%3A%2F%2Fx%2Ft%2F1%20a");
        assert_eq!(percent_encode_path("a b/c"), "a%20b/c");
    }
}
