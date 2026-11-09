//! Request limit: QUOTA_BOOKS per user in a rolling QUOTA_DAYS window, for everyone (admins too). A ledger keeps deleted requests counting.
use crate::util::{iso_timestamp, iso_utc, str_of};
use serde_json::{json, Map, Value};

fn ts(value: Option<&Value>) -> f64 {
    match value {
        Some(Value::String(s)) => iso_timestamp(s),
        _ => 0.0,
    }
}

fn label(v: Option<&Value>) -> String {
    // str(None) in the Python keys
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        _ => "None".to_string(),
    }
}

fn entry(user: Option<&Value>, at: f64) -> Value {
    json!({"user": user.cloned().unwrap_or(Value::Null), "at": at})
}

/// ABR's live requests as {user|book: {user, at}}.
pub fn quota_entries(wishlist: &[Value], manual: &[Value]) -> Map<String, Value> {
    let mut out = Map::new();
    for w in wishlist {
        let asin = w.get("book").and_then(|b| b.get("asin"));
        for r in w.get("requests").and_then(Value::as_array).into_iter().flatten() {
            let user = r.get("user_username");
            out.insert(format!("{}|{}", label(user), label(asin)), entry(user, ts(r.get("updated_at"))));
        }
    }
    for (i, m) in manual.iter().enumerate() {
        let user = m.get("user_username");
        let id = match m.get("id") {
            Some(v) if crate::util::truthy(Some(v)) => label(Some(v)),
            _ => i.to_string(),
        };
        out.insert(format!("{}|manual-{}", label(user), id), entry(user, ts(m.get("updated_at"))));
    }
    out
}

fn at(v: &Value) -> f64 {
    v.get("at").and_then(Value::as_f64).unwrap_or(0.0)
}

/// Every request ever seen in the window, so deleting a request does not give its slot back. First sighting wins.
pub fn merge_ledger(ledger: &Map<String, Value>, entries: &Map<String, Value>, now: f64, quota_days: f64) -> Map<String, Value> {
    let since = now - quota_days * 86400.0;
    let mut merged: Map<String, Value> = ledger.iter().filter(|(_, v)| at(v) >= since).map(|(k, v)| (k.clone(), v.clone())).collect();
    for (k, v) in entries {
        if at(v) >= since && !merged.contains_key(k) {
            merged.insert(k.clone(), v.clone());
        }
    }
    merged
}

pub fn quota_ok(wishlist: &[Value], manual: &[Value], user: &str, now: f64, ledger: &Map<String, Value>, books: usize, days: f64) -> bool {
    if user.is_empty() {
        return false;
    }
    let entries = merge_ledger(ledger, &quota_entries(wishlist, manual), now, days);
    entries.values().filter(|v| str_of(v.get("user")) == Some(user)).count() < books
}

/// The caller's own count for the requests bar: no other user's data.
pub fn my_quota(ledger: &Map<String, Value>, user: &str, now: f64, books: usize, days: f64) -> Option<Value> {
    if user.is_empty() {
        return None;
    }
    let since = now - days * 86400.0;
    let mut ats: Vec<f64> = ledger.values().filter(|v| str_of(v.get("user")) == Some(user) && at(v) >= since).map(at).collect();
    ats.sort_by(f64::total_cmp);
    let frees = if ats.len() >= books { Value::String(iso_utc(ats[ats.len() - books] + days * 86400.0)) } else { Value::Null };
    Some(json!({"used": ats.len(), "limit": books, "days": days as i64, "freesAt": frees}))
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW: f64 = 1_800_000_000.0;

    fn iso(days_ago: f64) -> String {
        iso_utc(NOW - days_ago * 86400.0).trim_end_matches('Z').to_string()
    }

    fn wish(entries: &[(&str, &str, f64)]) -> Vec<Value> {
        entries.iter().map(|(a, u, d)| json!({"book": {"asin": a}, "requests": [{"user_username": u, "updated_at": iso(*d)}]})).collect()
    }

    fn ok(w: &[Value], m: &[Value], user: &str, ledger: &Map<String, Value>) -> bool {
        quota_ok(w, m, user, NOW, ledger, 5, 7.0)
    }

    #[test]
    fn fifth_allowed_sixth_refused_and_the_rest() {
        let empty = Map::new();
        let four = wish(&[("B0", "jane", 1.0), ("B1", "jane", 1.0), ("B2", "jane", 1.0), ("B3", "jane", 1.0)]);
        let five = wish(&[("B0", "jane", 1.0), ("B1", "jane", 1.0), ("B2", "jane", 1.0), ("B3", "jane", 1.0), ("B4", "jane", 1.0)]);
        assert!(ok(&four, &[], "jane", &empty));
        assert!(!ok(&five, &[], "jane", &empty));
        let old = wish(&[("B0", "jane", 8.0), ("B1", "jane", 8.0), ("B2", "jane", 8.0), ("B3", "jane", 8.0), ("B4", "jane", 8.0)]);
        assert!(ok(&old, &[], "jane", &empty));
        let john = wish(&[("B0", "john", 1.0), ("B1", "john", 1.0), ("B2", "john", 1.0), ("B3", "john", 1.0), ("B4", "john", 1.0)]);
        assert!(ok(&john, &[], "jane", &empty));
        let manual = vec![json!({"user_username": "jane", "updated_at": iso(2.0)}), json!({"user_username": "jane", "updated_at": iso(2.0)})];
        let three = wish(&[("B0", "jane", 1.0), ("B1", "jane", 1.0), ("B2", "jane", 1.0)]);
        assert!(!ok(&three, &manual, "jane", &empty));
        assert_eq!(quota_entries(&[], &manual).len(), 2);
        assert!(!ok(&[], &[], "", &empty));
    }

    #[test]
    fn ledger_keeps_deleted_requests() {
        let five = wish(&[("B0", "jane", 1.0), ("B1", "jane", 1.0), ("B2", "jane", 1.0), ("B3", "jane", 1.0), ("B4", "jane", 1.0)]);
        let ledger = merge_ledger(&Map::new(), &quota_entries(&five, &[]), NOW, 7.0);
        assert!(!ok(&[], &[], "jane", &ledger));
        let four = wish(&[("B0", "jane", 1.0), ("B1", "jane", 1.0), ("B2", "jane", 1.0), ("B3", "jane", 1.0)]);
        let ledger = merge_ledger(&Map::new(), &quota_entries(&four, &[]), NOW, 7.0);
        assert!(ok(&four, &[], "jane", &ledger));
        let old = merge_ledger(&Map::new(), &quota_entries(&wish(&[("B1", "jane", 6.0)]), &[]), NOW, 7.0);
        let new = merge_ledger(&old, &quota_entries(&wish(&[("B1", "jane", 0.0)]), &[]), NOW, 7.0);
        assert_eq!(new, old);
        let gone = merge_ledger(&Map::new(), &quota_entries(&wish(&[("B1", "jane", 8.0)]), &[]), NOW, 7.0);
        assert_eq!(merge_ledger(&gone, &Map::new(), NOW, 7.0), Map::new());
    }

    #[test]
    fn my_quota_counts_only_me() {
        let ledger = |entries: &[(&str, f64)]| -> Map<String, Value> {
            entries.iter().enumerate().map(|(i, (u, d))| (format!("{u}|B{i}"), json!({"user": u, "at": NOW - d * 86400.0}))).collect()
        };
        let q = my_quota(&ledger(&[("jane", 1.0), ("jane", 2.0), ("john", 1.0)]), "jane", NOW, 5, 7.0).unwrap();
        assert_eq!(q, json!({"used": 2, "limit": 5, "days": 7, "freesAt": null}));
        let q = my_quota(&ledger(&[("jane", 1.0), ("jane", 2.0), ("jane", 3.0), ("jane", 4.0), ("jane", 6.5)]), "jane", NOW, 5, 7.0).unwrap();
        assert_eq!((q["used"].as_i64(), q["freesAt"].as_str()), (Some(5), Some("2027-01-15T20:00:00Z")));
        assert_eq!(my_quota(&ledger(&[("jane", 8.0)]), "jane", NOW, 5, 7.0).unwrap()["used"], 0);
        assert!(my_quota(&ledger(&[("jane", 1.0)]), "", NOW, 5, 7.0).is_none());
    }
}
