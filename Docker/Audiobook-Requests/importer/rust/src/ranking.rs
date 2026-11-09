//! Release policy for AudioBookRequest's Prowlarr results: author, language, min 1 seeder; unabridged, narrator, M4B, VIP/freeleech, newest upload.
use crate::naming::{language_folder, mam_code};
use crate::util::{percent_encode_strict, str_of};
use regex::Regex;
use serde_json::Value;
use std::collections::HashSet;
use std::sync::LazyLock;
use unicode_normalization::char::is_combining_mark;
use unicode_normalization::UnicodeNormalization;

/// abr-newest-1 .. -5, scored in ABR (abr-setup.py)
const NEWEST_FLAGS: usize = 5;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Prefs {
    pub language: String,
    pub unabridged: bool,
    /// the requested book's authors; empty = unknown, no author filter
    pub authors: Vec<String>,
    /// the requested edition's narrators (ranking only)
    pub narrators: Vec<String>,
}

impl Default for Prefs {
    fn default() -> Prefs {
        Prefs { language: "EN".to_string(), unabridged: true, authors: vec![], narrators: vec![] }
    }
}

pub fn names(people: Option<&Value>) -> Vec<String> {
    people
        .and_then(Value::as_array)
        .map(|ps| ps.iter().filter_map(|p| str_of(p.get("name")).filter(|n| !n.is_empty()).map(String::from)).collect())
        .unwrap_or_default()
}

pub fn prefs_from_product(product: Option<&Value>) -> Prefs {
    let Some(product) = product else { return Prefs::default() };
    let format = str_of(product.get("format_type")).filter(|s| !s.is_empty()).unwrap_or("unabridged").to_lowercase();
    Prefs {
        language: language_folder(str_of(product.get("language"))).unwrap_or_else(|| "EN".to_string()),
        unabridged: format != "abridged",
        authors: names(product.get("authors")),
        narrators: names(product.get("narrators")),
    }
}

fn fold(c: char) -> &'static str {
    match c {
        'ø' | 'Ø' => "o",
        'æ' | 'Æ' => "ae",
        'œ' | 'Œ' => "oe",
        'ß' => "ss",
        'ł' | 'Ł' => "l",
        'đ' | 'Đ' => "d",
        'þ' => "th",
        _ => "",
    }
}

/// Case, accents, punctuation and spacing ignored: "J. R. R. Tolkien" == "J.R.R. Tolkien", "Jo Nesbø" == "jo nesbo".
pub fn norm_name(name: &str) -> String {
    let mut folded = String::with_capacity(name.len());
    for c in name.chars() {
        let f = fold(c);
        if f.is_empty() {
            folded.push(c);
        } else {
            folded.push_str(f);
        }
    }
    folded.nfkd().filter(|c| !is_combining_mark(*c)).collect::<String>().to_lowercase().chars().filter(|c| c.is_ascii_alphanumeric()).collect()
}

static BY_AUTHOR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^.* by (.+?) \[[A-Z]{3} / ").unwrap());
static FLAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[([A-Z]{3}) / ([A-Z0-9]+)\]").unwrap());

/// MAM titles read "<title> by <author>, <author> [ENG / M4B]"; the last " by " before the flags.
pub fn release_authors(title: Option<&str>) -> Vec<String> {
    let Some(m) = BY_AUTHOR.captures(title.unwrap_or("")) else { return vec![] };
    m[1].split([',', ';', '&']).map(norm_name).filter(|a| !a.is_empty()).collect()
}

fn flags(title: Option<&str>) -> (Option<String>, Option<String>) {
    match FLAGS.captures(title.unwrap_or("")) {
        Some(m) => (Some(mam_code(&m[1]).to_string()), Some(m[2].to_string())),
        None => (None, None),
    }
}

fn abridged(r: &Value) -> bool {
    let text = format!("{} {}", str_of(r.get("title")).unwrap_or(""), str_of(r.get("description")).unwrap_or("")).to_lowercase();
    text.match_indices("abridged").any(|(i, _)| !text[..i].ends_with("un"))
}

fn vip(r: &Value) -> bool {
    str_of(r.get("title")).unwrap_or("").contains("[VIP]")
        || r.get("indexerFlags").and_then(Value::as_array).is_some_and(|fs| fs.iter().any(|f| str_of(Some(f)).is_some_and(|s| s.to_lowercase() == "freeleech")))
}

fn seeders(r: &Value) -> f64 {
    r.get("seeders").and_then(Value::as_f64).unwrap_or(0.0)
}

fn by_author(r: &Value, wanted: &HashSet<String>) -> bool {
    wanted.is_empty() || release_authors(str_of(r.get("title"))).iter().any(|a| wanted.contains(a))
}

/// Owner's order (2026-10-26, author + narrator 2026-11-02). Filters: one of the book's authors (when known), requested language only
/// (no fallback), >= 1 seeder. Rank: requested abridgement (unabridged by default), requested narrator (guids in `narrated`), M4B,
/// VIP/freeleech, newest upload.
pub fn apply_policy(results: Vec<Value>, prefs: &Prefs, proxy_base: Option<&str>, narrated: &HashSet<String>) -> Vec<Value> {
    let wanted: HashSet<String> = prefs.authors.iter().map(|a| norm_name(a)).filter(|a| !a.is_empty()).collect();
    let mut by_age: Vec<Value> = results
        .into_iter()
        .filter(|r| {
            (seeders(r) >= 1.0 || str_of(r.get("protocol")) == Some("usenet"))
                && flags(str_of(r.get("title"))).0.as_deref() == Some(prefs.language.as_str())
                && by_author(r, &wanted)
        })
        .collect();
    by_age.sort_by(|a, b| str_of(b.get("publishDate")).unwrap_or("").cmp(str_of(a.get("publishDate")).unwrap_or("")));
    for (i, r) in by_age.iter_mut().enumerate() {
        let is_vip = vip(r);
        let mut fl: Vec<Value> = r.get("indexerFlags").and_then(Value::as_array).cloned().unwrap_or_default();
        if i < NEWEST_FLAGS {
            fl.push(Value::String(format!("abr-newest-{}", i + 1)));
        }
        if is_vip {
            fl.push(Value::String("abr-vip".to_string()));
        }
        let guid = str_of(r.get("guid")).unwrap_or("").to_string();
        let has_download = str_of(r.get("downloadUrl")).is_some_and(|d| !d.is_empty());
        if let Some(obj) = r.as_object_mut() {
            obj.insert("indexerFlags".to_string(), Value::Array(fl));
            // ABR fetches the .torrent once more to read its hash; the pass-through answers from qBittorrent instead of MAM.
            if let (Some(base), true) = (proxy_base, has_download) {
                obj.insert("downloadUrl".to_string(), Value::String(format!("{base}/torrent?guid={}", percent_encode_strict(&guid))));
            }
        }
    }
    let key = |r: &Value| {
        (
            abridged(r) == prefs.unabridged,
            !str_of(r.get("guid")).is_some_and(|g| narrated.contains(g)),
            flags(str_of(r.get("title"))).1.as_deref() != Some("M4B"),
            !vip(r),
        )
    };
    by_age.sort_by_key(key);
    by_age
}

/// Only the winner: ABR re-sorts by its own fixed rules (FLAC > M4B, no abridged/VIP) and grabs its first entry.
pub fn for_abr(results: Vec<Value>, prefs: &Prefs, proxy_base: Option<&str>, narrated: &HashSet<String>) -> Vec<Value> {
    let mut out = apply_policy(results, prefs, proxy_base, narrated);
    out.truncate(1);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn release(title: &str, date: &str, seeders: i64) -> Value {
        json!({"guid": format!("{title}{date}"), "title": title, "publishDate": date, "seeders": seeders, "indexerFlags": []})
    }

    fn r(title: &str) -> Value {
        release(title, "2024-01-01T00:00:00Z", 5)
    }

    fn titles(out: &[Value]) -> Vec<&str> {
        out.iter().map(|r| r["title"].as_str().unwrap()).collect()
    }

    fn authors(a: &[&str]) -> Prefs {
        Prefs { authors: a.iter().map(|s| s.to_string()).collect(), ..Prefs::default() }
    }

    fn policy(results: Vec<Value>, prefs: &Prefs) -> Vec<Value> {
        apply_policy(results, prefs, None, &HashSet::new())
    }

    #[test]
    fn format_language_abridged_and_seeders() {
        let out = policy(vec![release("B by A [ENG / MP3]", "2025-01-01T00:00:00Z", 5), r("B by A [ENG / M4B]")], &Prefs::default());
        assert_eq!(titles(&out)[0], "B by A [ENG / M4B]");
        let out = policy(vec![release("B by A [GER / M4B]", "2026-01-01T00:00:00Z", 5), r("B by A [ENG / MP3]")], &Prefs::default());
        assert_eq!(titles(&out), ["B by A [ENG / MP3]"]);
        let de = Prefs { language: "DE".into(), ..Prefs::default() };
        assert_eq!(titles(&policy(vec![r("B by A [ENG / M4B]"), r("B by A [GER / M4B]")], &de)), ["B by A [GER / M4B]"]);
        let ab = Prefs { unabridged: false, ..Prefs::default() };
        assert_eq!(policy(vec![r("B (Abridged) by A [ENG / M4B]")], &ab).len(), 1);
        let out = policy(vec![release("B by A [ENG / M4B]", "2024-01-01T00:00:00Z", 0), release("B by A [ENG / MP3]", "2024-01-01T00:00:00Z", 1)], &Prefs::default());
        assert_eq!(titles(&out), ["B by A [ENG / MP3]"]);
        assert_eq!(policy(vec![r("Some Other Release")], &Prefs::default()), Vec::<Value>::new());
    }

    #[test]
    fn newest_vip_and_flags() {
        let out = policy(vec![release("B by A [ENG / M4B]", "2019-05-01T00:00:00Z", 50), release("B by A [ENG / M4B]", "2025-05-01T00:00:00Z", 2)], &Prefs::default());
        assert_eq!(out[0]["publishDate"], "2025-05-01T00:00:00Z");
        assert_eq!(out[0]["indexerFlags"], json!(["abr-newest-1"]));
        assert_eq!(out[1]["indexerFlags"], json!(["abr-newest-2"]));
        let out = policy(vec![release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z", 5), release("B by A [ENG / M4B] [VIP]", "2020-01-01T00:00:00Z", 5)], &Prefs::default());
        assert_eq!(titles(&out)[0], "B by A [ENG / M4B] [VIP]");
        assert!(out[0]["indexerFlags"].as_array().unwrap().contains(&json!("abr-vip")));
        let mut fl = release("B by A [ENG / M4B]", "2020-01-01T00:00:00Z", 5);
        fl["indexerFlags"] = json!(["freeleech"]);
        let out = policy(vec![release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z", 5), fl], &Prefs::default());
        assert_eq!(out[0]["publishDate"], "2020-01-01T00:00:00Z");
        let out = policy(vec![r("B by A [ENG / MP3] [VIP]"), r("B by A [ENG / M4B]")], &Prefs::default());
        assert_eq!(titles(&out)[0], "B by A [ENG / M4B]");
        let out = policy(vec![release("B (Abridged) by A [ENG / M4B] [VIP]", "2026-01-01T00:00:00Z", 5), release("B by A [ENG / MP3]", "2010-01-01T00:00:00Z", 5)], &Prefs::default());
        assert_eq!(titles(&out)[0], "B by A [ENG / MP3]");
        assert_eq!(titles(&policy(vec![r("B (Abridged) by A [ENG / MP3]")], &Prefs::default())), ["B (Abridged) by A [ENG / MP3]"]);
    }

    #[test]
    fn download_url_goes_through_the_pass_through_and_abr_gets_one() {
        let mut rel = r("B by A [ENG / M4B]");
        rel["downloadUrl"] = json!("http://10.24.25.2:9697/1/download?apikey=k&link=x");
        rel["guid"] = json!("https://www.myanonamouse.net/t/1");
        let out = apply_policy(vec![rel], &Prefs::default(), Some("http://audiobook-importer:8000/prowlarr"), &HashSet::new());
        assert_eq!(out[0]["downloadUrl"], "http://audiobook-importer:8000/prowlarr/torrent?guid=https%3A%2F%2Fwww.myanonamouse.net%2Ft%2F1");
        let out = for_abr(vec![r("B by A [ENG / MP3]"), r("B by A [ENG / M4B]")], &Prefs::default(), None, &HashSet::new());
        assert_eq!(titles(&out), ["B by A [ENG / M4B]"]);
    }

    #[test]
    fn author_filter() {
        assert_eq!(policy(vec![r("B by JO NESBØ [ENG / M4B]")], &authors(&["Jo Nesbo"])).len(), 1);
        assert_eq!(policy(vec![r("B by J.R.R. Tolkien [ENG / M4B]")], &authors(&["J. R. R. Tolkien"])).len(), 1);
        assert_eq!(policy(vec![r("B by Émile Zola [ENG / M4B]")], &authors(&["Emile Zola"])).len(), 1);
        assert_eq!(policy(vec![r("B by Douglas Preston, Lincoln Child [ENG / M4B]")], &authors(&["Lincoln Child", "Douglas Preston"])).len(), 1);
        assert_eq!(policy(vec![r("B by Lincoln Child [ENG / M4B]")], &authors(&["Douglas Preston", "Lincoln Child"])).len(), 1);
        assert!(policy(vec![r("B by Jane Austenford [ENG / M4B]")], &authors(&["Jane Austen"])).is_empty());
        assert!(policy(vec![r("Sense & Sensibility by Joanna Trollope [ENG / M4B]")], &authors(&["Jane Austen"])).is_empty());
        assert_eq!(policy(vec![r("B by Anyone [ENG / M4B]")], &Prefs::default()).len(), 1);
        assert_eq!(release_authors(Some("BBC R4 CS - X by Jane Austen (Aug 2013) by Jane Austen, BBC Radio 4 [ENG / MP3]")), ["janeausten", "bbcradio4"]);
    }

    #[test]
    fn narrator_is_a_preference() {
        let prefs = Prefs { authors: vec!["A".into()], narrators: vec!["N".into()], ..Prefs::default() };
        let mut n = r("B by A [ENG / MP3]");
        n["guid"] = json!("n");
        let narrated: HashSet<String> = ["n".to_string()].into_iter().collect();
        let out = apply_policy(vec![release("B by A [ENG / M4B]", "2026-01-01T00:00:00Z", 5), n.clone()], &prefs, None, &narrated);
        assert_eq!(out[0]["guid"], "n");
        let mut ab = r("B (Abridged) by A [ENG / M4B]");
        ab["guid"] = json!("n");
        let out = apply_policy(vec![ab, r("B by A [ENG / MP3]")], &authors(&["A"]), None, &narrated);
        assert_eq!(titles(&out)[0], "B by A [ENG / MP3]");
    }

    #[test]
    fn prefs_from_audible() {
        assert_eq!(prefs_from_product(None), Prefs::default());
        let p = prefs_from_product(Some(&json!({"language": "german", "format_type": "abridged"})));
        assert_eq!((p.language.as_str(), p.unabridged), ("DE", false));
        let p = prefs_from_product(Some(&json!({"language": "english", "authors": [{"name": "Jane Austen"}], "narrators": [{"name": "Karen Savage"}]})));
        assert_eq!((p.authors, p.narrators), (vec!["Jane Austen".to_string()], vec!["Karen Savage".to_string()]));
    }
}
