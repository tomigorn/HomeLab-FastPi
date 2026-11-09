//! Python-compatible text formats: float repr and json.dumps (", " / ": " separators, ensure_ascii).

use serde_json::Value;

/// repr(float)
pub fn float(f: f64) -> String {
    if f.is_nan() {
        return "NaN".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    let a = f.abs();
    if a != 0.0 && !(1e-4..1e16).contains(&a) {
        let s = format!("{f:e}");
        let (m, e) = s.split_once('e').unwrap_or((&s, "0"));
        let (sign, digits) = match e.strip_prefix('-') {
            Some(d) => ('-', d),
            None => ('+', e),
        };
        return format!("{m}e{sign}{digits:0>2}");
    }
    let s = format!("{f}");
    if s.contains('.') { s } else { format!("{s}.0") }
}

/// round(x, 1) for display values like seconds held
pub fn round1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}

fn string(s: &str, out: &mut String) {
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
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{u:04x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write(v: &Value, sort: bool, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if n.is_f64() {
                out.push_str(&float(n.as_f64().unwrap_or(0.0)));
            } else {
                out.push_str(&n.to_string());
            }
        }
        Value::String(s) => string(s, out),
        Value::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write(x, sort, out);
            }
            out.push(']');
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            if sort {
                keys.sort();
            }
            out.push('{');
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                string(k, out);
                out.push_str(": ");
                write(&m[k.as_str()], sort, out);
            }
            out.push('}');
        }
    }
}

/// json.dumps(v)
pub fn dumps(v: &Value) -> String {
    let mut s = String::new();
    write(v, false, &mut s);
    s
}

/// json.dumps(v, sort_keys=True)
pub fn dumps_sorted(v: &Value) -> String {
    let mut s = String::new();
    write(v, true, &mut s);
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn float_repr() {
        assert_eq!(float(0.0), "0.0");
        assert_eq!(float(18.0), "18.0");
        assert_eq!(float(1.9), "1.9");
        assert_eq!(float(1762654321.123456), "1762654321.123456");
        assert_eq!(float(1e16), "1e+16");
        assert_eq!(float(0.00001), "1e-05");
        assert_eq!(float(-2.5), "-2.5");
    }

    #[test]
    fn dumps_like_python() {
        let v = json!({"up": false, "phase": "idle", "seconds_left": null, "reason": "", "x": [1, 2.5, "\u{e9}\u{1F7E2}\"\n"]});
        assert_eq!(dumps(&v), r#"{"up": false, "phase": "idle", "seconds_left": null, "reason": "", "x": [1, 2.5, "\u00e9\ud83d\udfe2\"\n"]}"#);
        assert_eq!(dumps_sorted(&json!({"b": 1, "a": {}})), r#"{"a": {}, "b": 1}"#);
        assert_eq!(dumps(&json!("\u{7f}/")), r#""\u007f/""#);
    }
}
