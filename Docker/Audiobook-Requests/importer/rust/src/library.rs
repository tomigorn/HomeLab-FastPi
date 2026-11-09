//! Library page (books-proxy /_hg/library/): the Audiobookshelf books a viewer may see in ABS itself, and book sizes for ABR's lists.
use crate::util::{str_of, truthy};
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

pub const ABS_PUBLIC: &str = "https://audiobookshelf.holy-grail.ch/item/";
pub const ACTIVE: [&str; 3] = ["pending", "unbound", "merge-wait"];

pub type ItemsByLib = Map<String, Value>;

/// The viewer's ABS account: ABS usernames come from the same Holy Grail login (preferred_username), matched exactly.
/// Only accounts linked to that login (hasOpenIDLink), never root: a local ABS account with the same name is not the viewer.
pub fn abs_user<'a>(users: &'a [Value], username: &str) -> Option<&'a Value> {
    if username.is_empty() {
        return None;
    }
    users.iter().find(|u| {
        str_of(u.get("username")) == Some(username)
            && u.get("isActive").map(|v| truthy(Some(v))).unwrap_or(true)
            && u.get("hasOpenIDLink") == Some(&Value::Bool(true))
            && str_of(u.get("type")) != Some("root")
    })
}

fn metadata(it: &Value) -> Option<&Value> {
    it.get("media").and_then(|m| m.get("metadata"))
}

pub fn can_see(user: &Value, it: &Value) -> bool {
    if str_of(user.get("type")) == Some("root") {
        return true;
    }
    let empty = Value::Object(Map::new());
    let p = user.get("permissions").unwrap_or(&empty);
    if !truthy(p.get("accessAllLibraries")) {
        let accessible = user.get("librariesAccessible").and_then(Value::as_array);
        let lib = it.get("libraryId");
        if !accessible.is_some_and(|a| lib.is_some_and(|l| a.contains(l))) {
            return false;
        }
    }
    if truthy(metadata(it).and_then(|m| m.get("explicit"))) && !truthy(p.get("accessExplicitContent")) {
        return false;
    }
    if !truthy(p.get("accessAllTags")) {
        let selected: HashSet<&str> = user.get("itemTagsSelected").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).collect()).unwrap_or_default();
        let tagged = it
            .get("media")
            .and_then(|m| m.get("tags"))
            .and_then(Value::as_array)
            .is_some_and(|tags| tags.iter().filter_map(Value::as_str).any(|t| selected.contains(t)));
        return if truthy(p.get("selectedTagsNotAccessible")) { !tagged } else { tagged };
    }
    true
}

pub fn book_library_ids(libs: &[Value]) -> Vec<String> {
    libs.iter().filter(|l| str_of(l.get("mediaType")) == Some("book")).filter_map(|l| str_of(l.get("id")).map(String::from)).collect()
}

pub fn visible<'a>(user: &Value, libs: &[Value], items_by_lib: &'a ItemsByLib) -> Vec<&'a Value> {
    book_library_ids(libs)
        .iter()
        .flat_map(|lib| items_by_lib.get(lib).and_then(Value::as_array).map(|a| a.iter()).into_iter().flatten())
        .filter(|it| can_see(user, it))
        .collect()
}

pub fn iso_ms(ms: Option<&Value>) -> Value {
    match ms.and_then(Value::as_f64) {
        Some(v) if v != 0.0 => Value::String(crate::util::iso_utc(v / 1000.0)),
        _ => Value::Null,
    }
}

fn size_of(it: &Value) -> Value {
    if truthy(it.get("size")) {
        return it["size"].clone();
    }
    it.get("media").and_then(|m| m.get("size")).cloned().unwrap_or(Value::Null)
}

pub fn row(it: &Value, names: &HashMap<String, Value>) -> Value {
    let media = it.get("media").cloned().unwrap_or_else(|| json!({}));
    let m = media.get("metadata").cloned().unwrap_or_else(|| json!({}));
    let duration = media.get("duration").and_then(Value::as_f64).unwrap_or(0.0).trunc() as i64;
    json!({
        "id": it.get("id").cloned().unwrap_or(Value::Null),
        "title": m.get("title").cloned().unwrap_or(Value::Null),
        "subtitle": m.get("subtitle").cloned().unwrap_or(Value::Null),
        "author": m.get("authorName").cloned().unwrap_or(Value::Null),
        "narrator": m.get("narratorName").cloned().unwrap_or(Value::Null),
        "series": m.get("seriesName").cloned().unwrap_or(Value::Null),
        "duration": duration,
        "size": size_of(it),
        "added": iso_ms(it.get("addedAt")),
        "library": str_of(it.get("libraryId")).and_then(|l| names.get(l)).cloned().unwrap_or(Value::Null),
        "asin": m.get("asin").cloned().unwrap_or(Value::Null),
        "year": m.get("publishedYear").cloned().unwrap_or(Value::Null),
    })
}

pub fn listing(user: Option<&Value>, libs: &[Value], items_by_lib: &ItemsByLib) -> Value {
    let Some(user) = user else {
        return json!({"count": 0, "items": [], "noAbsUser": true, "abs": ABS_PUBLIC});
    };
    let names: HashMap<String, Value> = libs.iter().filter_map(|l| str_of(l.get("id")).map(|id| (id.to_string(), l.get("name").cloned().unwrap_or(Value::Null)))).collect();
    let rows: Vec<Value> = visible(user, libs, items_by_lib).into_iter().map(|it| row(it, &names)).collect();
    json!({"count": rows.len(), "items": rows, "noAbsUser": false, "abs": ABS_PUBLIC})
}

pub fn visible_ids(user: Option<&Value>, libs: &[Value], items_by_lib: &ItemsByLib) -> HashSet<String> {
    match user {
        Some(u) => visible(u, libs, items_by_lib).into_iter().filter_map(|it| str_of(it.get("id")).map(String::from)).collect(),
        None => HashSet::new(),
    }
}

/// ASIN -> bytes: the ABS item (after import and merge) if its id is in allowed, else the torrent while it still downloads.
/// An ASIN of an ABS item outside allowed is left out entirely.
pub fn sizes(items_by_lib: &ItemsByLib, jobs: &Map<String, Value>, torrents: &[Value], allowed: &HashSet<String>) -> Map<String, Value> {
    let mut out = Map::new();
    let mut in_abs = HashSet::new();
    for items in items_by_lib.values() {
        for it in items.as_array().into_iter().flatten() {
            let Some(asin) = metadata(it).and_then(|m| str_of(m.get("asin"))).filter(|a| !a.is_empty()) else { continue };
            in_abs.insert(asin.to_string());
            if !out.contains_key(asin) && str_of(it.get("id")).is_some_and(|id| allowed.contains(id)) {
                out.insert(asin.to_string(), size_of(it));
            }
        }
    }
    let by_hash: HashMap<&str, &Value> = torrents.iter().filter_map(|t| str_of(t.get("hash")).map(|h| (h, t.get("size").unwrap_or(&Value::Null)))).collect();
    for j in jobs.values() {
        let Some(asin) = str_of(j.get("asin")).filter(|a| !a.is_empty()) else { continue };
        let active = str_of(j.get("state")).is_some_and(|s| ACTIVE.contains(&s));
        let size = str_of(j.get("hash")).and_then(|h| by_hash.get(h)).copied();
        if !in_abs.contains(asin) && active && truthy(size) {
            out.insert(asin.to_string(), size.cloned().unwrap_or(Value::Null));
        }
    }
    out
}

static COVER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^/library-cover/([A-Za-z0-9_-]{1,64})$").unwrap());

pub fn cover_id(path: &str) -> Option<String> {
    COVER.captures(path).map(|m| m[1].to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn user(name: &str, type_: &str, all_libs: bool, all_tags: bool, tags: &[&str], not_tags: bool, explicit: bool, oidc: bool) -> Value {
        json!({"username": name, "type": type_, "isActive": true, "hasOpenIDLink": oidc, "librariesAccessible": ["de"], "itemTagsSelected": tags,
               "token": "SECRET-TOKEN", "email": "x@example.com",
               "permissions": {"accessAllLibraries": all_libs, "accessAllTags": all_tags, "selectedTagsNotAccessible": not_tags, "accessExplicitContent": explicit}})
    }

    fn plain(name: &str) -> Value {
        user(name, "user", true, true, &[], false, true, true)
    }

    fn item(i: &str, lib: &str, asin: Option<&str>, size: i64, tags: &[&str], explicit: bool) -> Value {
        json!({"id": i, "libraryId": lib, "size": size, "addedAt": 1770425220177i64, "path": "/audiobooks/EN/x", "relPath": "x",
               "media": {"duration": 3600.5, "tags": tags, "metadata": {"title": format!("T{i}"), "subtitle": "Sub", "authorName": "Jane Doe",
               "narratorName": "John Roe", "seriesName": "Saga #1", "asin": asin, "explicit": explicit, "description": "long text", "publishedYear": "2010"}}})
    }

    fn libs() -> Vec<Value> {
        vec![json!({"id": "en", "name": "[EN] Audiobooks", "mediaType": "book"}), json!({"id": "de", "name": "[DE] Hörbücher", "mediaType": "book"}),
             json!({"id": "pod", "name": "Podcasts", "mediaType": "podcast"})]
    }

    fn items() -> ItemsByLib {
        let mut m = Map::new();
        m.insert("en".into(), json!([item("1", "en", Some("A1"), 100, &[], false), item("2", "en", None, 100, &["kids"], false), item("3", "en", None, 100, &[], true)]));
        m.insert("de".into(), json!([item("4", "de", None, 300, &[], false)]));
        m
    }

    fn ids(rows: Vec<&Value>) -> Vec<String> {
        rows.iter().map(|r| r["id"].as_str().unwrap().to_string()).collect()
    }

    #[test]
    fn viewer_lookup() {
        let users = vec![plain("jane"), plain("Jane2"), user("local", "user", true, true, &[], false, true, false), user("root", "root", true, true, &[], false, true, true)];
        assert_eq!(abs_user(&users, "jane").unwrap()["username"], "jane");
        assert!(abs_user(&users, "JANE").is_none());
        assert!(abs_user(&users, "").is_none());
        assert!(abs_user(&users, "local").is_none());
        assert!(abs_user(&users, "root").is_none());
        let mut off = plain("off");
        off["isActive"] = json!(false);
        assert!(abs_user(&[off], "off").is_none());
        let mut old = plain("old");
        old.as_object_mut().unwrap().remove("hasOpenIDLink");
        assert!(abs_user(&[old], "old").is_none());
        assert!(abs_user(&[user("adm", "admin", true, true, &[], false, true, true)], "adm").is_some());
    }

    #[test]
    fn visibility_rules() {
        assert_eq!(ids(visible(&plain("a"), &libs(), &items())), ["1", "2", "3", "4"]);
        assert_eq!(ids(visible(&user("a", "user", false, true, &[], false, true, true), &libs(), &items())), ["4"]);
        assert_eq!(ids(visible(&user("a", "user", true, true, &[], false, false, true), &libs(), &items())), ["1", "2", "4"]);
        assert_eq!(ids(visible(&user("a", "user", true, false, &["kids"], false, true, true), &libs(), &items())), ["2"]);
        assert_eq!(ids(visible(&user("a", "user", true, false, &["kids"], true, true, true), &libs(), &items())), ["1", "3", "4"]);
        assert_eq!(ids(visible(&user("r", "root", false, true, &[], false, false, true), &libs(), &items())), ["1", "2", "3", "4"]);
    }

    #[test]
    fn rows_and_listing() {
        let names: HashMap<String, Value> = [("en".to_string(), json!("[EN] Audiobooks"))].into_iter().collect();
        let r = row(&item("1", "en", Some("A1"), 100, &[], false), &names);
        assert_eq!(r, json!({"id": "1", "title": "T1", "subtitle": "Sub", "author": "Jane Doe", "narrator": "John Roe", "series": "Saga #1",
                             "duration": 3600, "size": 100, "added": "2026-02-07T00:47:00Z", "library": "[EN] Audiobooks", "asin": "A1", "year": "2010"}));
        let out = listing(Some(&plain("a")), &libs(), &items());
        let text = out.to_string();
        for leak in ["SECRET-TOKEN", "example.com", "/audiobooks/EN", "long text", "relPath"] {
            assert!(!text.contains(leak), "{leak}");
        }
        assert_eq!(out["count"], 4);
        let none = listing(None, &libs(), &items());
        assert_eq!(none, json!({"count": 0, "items": [], "noAbsUser": true, "abs": ABS_PUBLIC}));
    }

    #[test]
    fn sizes_by_asin() {
        let mut jobs = Map::new();
        jobs.insert("h1".into(), json!({"asin": "A1", "hash": "h1", "state": "done"}));
        jobs.insert("h9".into(), json!({"asin": "A9", "hash": "h9", "state": "pending"}));
        let torrents = vec![json!({"hash": "h9", "size": 555}), json!({"hash": "h1", "size": 999})];
        let all: HashSet<String> = ["1", "2", "3", "4"].iter().map(|s| s.to_string()).collect();
        let out = sizes(&items(), &jobs, &torrents, &all);
        assert_eq!(Value::Object(out), json!({"A1": 100, "A9": 555}));
        let out = sizes(&items(), &jobs, &torrents, &HashSet::new());
        assert_eq!(Value::Object(out), json!({"A9": 555}));
    }

    #[test]
    fn cover_ids() {
        assert_eq!(cover_id("/library-cover/li_8a7b-c9").as_deref(), Some("li_8a7b-c9"));
        for bad in ["/library-cover/../x", "/library-cover/a?b", "/library-cover/", "/library-cover/a/b"] {
            assert!(cover_id(bad).is_none(), "{bad}");
        }
    }
}
