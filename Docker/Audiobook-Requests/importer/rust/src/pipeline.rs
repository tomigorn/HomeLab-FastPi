//! Webhook jobs: bind to the torrent, copy the finished download into the library (never move: it keeps seeding), wait for the merge, scan and match in ABS.
use crate::app::App;
use crate::clients::audible;
use crate::naming::{book_dir, language_folder, mam_language, Book};
use crate::quota::{merge_ledger, quota_entries};
use crate::util::{now, str_of, truthy, write_atomic, Result};
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

const AUDIO: [&str; 9] = [".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus", ".wma", ".wav"];

fn is_hex40(h: &str) -> bool {
    h.len() == 40 && h.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

fn placeholder(v: &str) -> bool {
    v.len() > 2 && v.starts_with('{') && v.ends_with('}') && v[1..v.len() - 1].chars().all(|c| c.is_alphanumeric() || c == '_')
}

fn text(v: Option<&Value>) -> String {
    // str(body.get(key) or "").strip()
    match v {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.trim().to_string(),
        Some(Value::Bool(false)) => String::new(),
        Some(Value::Bool(true)) => "True".to_string(),
        Some(Value::Number(n)) => if n.as_f64() == Some(0.0) { String::new() } else { n.to_string() },
        Some(other) => other.to_string(),
    }
}

pub fn parse_webhook(body: &Value) -> std::result::Result<Value, String> {
    let obj = body.as_object().ok_or("body must be a JSON object")?;
    let h = text(obj.get("hash")).to_lowercase();
    // ABR sends no hash when an admin picks the source by hand: bind() matches the torrent later.
    let unbound = h.is_empty() || h == "{torrentinfohash}";
    if !unbound && !is_hex40(&h) {
        return Err("hash must be 40 hex characters".to_string());
    }
    let value = |key: &str| {
        let v = text(obj.get(key));
        if placeholder(&v) { String::new() } else { v }
    };
    let asin = value("asin");
    let authors: Vec<Value> = value("authors").split(',').map(str::trim).filter(|a| !a.is_empty()).map(|a| json!(a)).collect();
    Ok(json!({
        "hash": if unbound { Value::Null } else { json!(h) },
        "asin": if asin.is_empty() { Value::Null } else { json!(asin) },
        "title": value("title"),
        "authors": authors,
        "source": value("source"),
        "indexer": value("indexer"),
        "state": if unbound { "unbound" } else { "pending" },
        "added": now(),
    }))
}

pub fn load(path: &Path) -> Result<Map<String, Value>> {
    match fs::read_to_string(path) {
        Ok(text) => Ok(serde_json::from_str::<Value>(&text)?.as_object().cloned().unwrap_or_default()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Map::new()),
        Err(e) => Err(e.into()),
    }
}

pub fn save(path: &Path, jobs: &Map<String, Value>) -> Result<()> {
    let mut buf = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b" ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
    serde::Serialize::serialize(jobs, &mut ser)?;
    write_atomic(path, std::str::from_utf8(&buf)?)?;
    Ok(())
}

/// Hash of the abr torrent added closest after the webhook (within window seconds) that no job owns yet.
pub fn bind(job: &Value, torrents: &[Value], known: &HashSet<String>, category: &str, window: f64) -> Option<String> {
    let added = job.get("added").and_then(Value::as_f64)?;
    torrents
        .iter()
        .filter(|t| {
            let delta = t.get("added_on").and_then(Value::as_f64).unwrap_or(f64::NAN) - added;
            str_of(t.get("category")) == Some(category) && str_of(t.get("hash")).is_some_and(|h| !known.contains(h)) && (-60.0..=window).contains(&delta)
        })
        .min_by(|a, b| {
            let d = |t: &Value| (t.get("added_on").and_then(Value::as_f64).unwrap_or(0.0) - added).abs();
            d(a).total_cmp(&d(b))
        })
        .and_then(|t| str_of(t.get("hash")).map(String::from))
}

fn strings(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default()
}

pub fn resolve_book(job: &Value, product: Option<&Value>) -> Book {
    let language = mam_language(str_of(job.get("source"))).unwrap_or_else(|| "Other".to_string());
    if let Some(p) = product.filter(|p| truthy(p.get("title"))) {
        let series = p.get("series").and_then(Value::as_array).and_then(|s| s.first()).cloned().unwrap_or_else(|| json!({}));
        let mut authors = crate::ranking::names(p.get("authors"));
        if authors.is_empty() {
            authors = strings(job.get("authors"));
        }
        let sequence = match series.get("sequence") {
            Some(Value::String(s)) => Some(s.clone()),
            Some(Value::Number(n)) => Some(n.to_string()),
            _ => None,
        };
        return Book::new(
            str_of(p.get("title")).unwrap_or(""),
            authors,
            str_of(series.get("title")).map(String::from),
            sequence,
            &language_folder(str_of(p.get("language"))).unwrap_or(language),
        );
    }
    Book::new(str_of(job.get("title")).unwrap_or(""), strings(job.get("authors")), None, None, &language)
}

pub fn needs_merge(names: &[String]) -> bool {
    names.iter().filter(|n| AUDIO.iter().any(|a| n.to_lowercase().ends_with(a))).count() >= 2
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) -> io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let p = entry?.path();
        if p.is_dir() {
            walk(&p, out)?;
        } else if p.is_file() {
            out.push(p);
        }
    }
    Ok(())
}

pub fn files_under(dir: &Path) -> io::Result<Vec<PathBuf>> {
    let mut out = vec![];
    walk(dir, &mut out)?;
    out.sort();
    Ok(out)
}

pub fn file_names(dir: &Path) -> io::Result<Vec<String>> {
    Ok(files_under(dir)?.iter().filter_map(|p| p.file_name().map(|n| n.to_string_lossy().into_owned())).collect())
}

/// shutil.copy2: contents and modification time.
fn copy2(src: &Path, dst: &Path) -> io::Result<()> {
    fs::copy(src, dst)?;
    if let Ok(modified) = fs::metadata(src).and_then(|m| m.modified()) {
        let _ = fs::File::options().write(true).open(dst).and_then(|f| f.set_modified(modified));
    }
    Ok(())
}

/// Copies the download into library/rel through a hidden temp folder; an existing non-empty folder is never touched (AlreadyExists).
pub fn copy_into(src: &Path, library: &Path, rel: &str) -> io::Result<PathBuf> {
    let dest = library.join(rel);
    if dest.exists() && fs::read_dir(&dest)?.next().is_some() {
        return Err(io::Error::new(io::ErrorKind::AlreadyExists, dest.display().to_string()));
    }
    let parent = dest.parent().ok_or_else(|| io::Error::other("no parent"))?;
    let name = dest.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let tmp = parent.join(format!(".{name}.importing"));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(parent)?;
    fs::create_dir(&tmp)?;
    if src.is_dir() {
        // M4b-Auto-Merge works per folder: CD1/01.mp3 becomes "CD1 - 01.mp3" (order kept, names otherwise original).
        for f in files_under(src)? {
            let flat = f.strip_prefix(src).map_err(io::Error::other)?.components().map(|c| c.as_os_str().to_string_lossy().into_owned()).collect::<Vec<_>>().join(" - ");
            copy2(&f, &tmp.join(flat))?;
        }
    } else {
        copy2(src, &tmp.join(src.file_name().ok_or_else(|| io::Error::other("no file name"))?))?;
    }
    if dest.exists() {
        fs::remove_dir(&dest)?;
    }
    fs::rename(&tmp, &dest)?;
    Ok(dest)
}

fn set(job: &mut Value, key: &str, v: Value) {
    if let Some(o) = job.as_object_mut() {
        o.insert(key.to_string(), v);
    }
}

fn fail(job: &mut Value, error: &str) {
    set(job, "state", json!("failed"));
    set(job, "error", json!(error));
}

fn number(job: &Value, key: &str) -> f64 {
    job.get(key).and_then(Value::as_f64).unwrap_or(0.0)
}

pub async fn step(app: &App, job: &mut Value, now: f64) -> Result<()> {
    let cfg = &app.cfg;
    match str_of(job.get("state")) {
        Some("pending") => {
            let hash = str_of(job.get("hash")).unwrap_or("").to_string();
            let Some(t) = app.qbit.torrent(&hash).await? else {
                if now - number(job, "added") > cfg.give_up_days * 86400.0 {
                    fail(job, "torrent never appeared in qBittorrent");
                }
                return Ok(());
            };
            if str_of(t.get("category")) != Some(cfg.category.as_str()) {
                let shown = match t.get("category") {
                    Some(Value::String(s)) => format!("'{s}'"),
                    _ => "None".to_string(),
                };
                fail(job, &format!("category is {shown}, not '{}'", cfg.category));
                return Ok(());
            }
            if t.get("progress").and_then(Value::as_f64).unwrap_or(0.0) < 1.0 {
                return Ok(());
            }
            let (product, region) = audible(cfg, &app.http, str_of(job.get("asin"))).await;
            let book = resolve_book(job, product.as_ref());
            let rel = book_dir(&book);
            set(job, "region", region.map(Value::String).unwrap_or(Value::Null));
            set(job, "book", json!({"title": book.title, "authors": book.authors}));
            let src = PathBuf::from(str_of(t.get("content_path")).unwrap_or(""));
            let library = cfg.library.clone();
            let rel_for_copy = rel.clone();
            let copied = tokio::task::spawn_blocking(move || copy_into(&src, &library, &rel_for_copy)).await?;
            let dest = match copied {
                Ok(d) => d,
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                    set(job, "state", json!("exists"));
                    set(job, "dest", json!(rel));
                    log::warn!("{rel} already in the library, not overwritten");
                    return Ok(());
                }
                Err(e) => return Err(e.into()),
            };
            let names = tokio::task::spawn_blocking(move || file_names(&dest)).await??;
            set(job, "state", json!(if needs_merge(&names) { "merge-wait" } else { "done" }));
            set(job, "dest", json!(rel));
            set(job, "imported", json!(now));
            log::info!("imported {rel} ({} files)", names.len());
        }
        Some("merge-wait") => {
            let dest = cfg.library.join(str_of(job.get("dest")).unwrap_or(""));
            let names = tokio::task::spawn_blocking(move || file_names(&dest)).await??;
            if !needs_merge(&names) || now - number(job, "imported") > cfg.merge_wait_hours * 3600.0 {
                set(job, "state", json!("done"));
                if let Some(o) = job.as_object_mut() {
                    o.remove("scanned");
                }
                log::info!("merged or waited long enough: {}", str_of(job.get("dest")).unwrap_or(""));
            }
        }
        _ => {}
    }
    Ok(())
}

pub async fn match_step(app: &App, job: &mut Value, now: f64) -> Result<()> {
    // Only after M4b-Auto-Merge is through (state done), so ABS never indexes the loose parts.
    if str_of(job.get("state")) != Some("done") || truthy(job.get("matched")) || app.abs.key().is_empty() || job.get("book").is_none() {
        return Ok(());
    }
    let dest = str_of(job.get("dest")).unwrap_or("").to_string();
    if !truthy(job.get("scanned")) {
        app.abs.scan(&dest).await?;
        set(job, "scanned", json!(now));
        return Ok(());
    }
    if app.abs.match_job(job).await? {
        set(job, "matched", json!(now));
    } else if now - number(job, "scanned") > app.cfg.match_give_up_hours * 3600.0 {
        set(job, "matched", json!("gave up: item never appeared in ABS"));
    }
    Ok(())
}

pub fn load_ledger(path: &Path) -> Result<Map<String, Value>> {
    load(path)
}

/// Adds ABR's live requests to the ledger; returns (wishlist, manual, ledger).
pub async fn snapshot_quota(app: &App) -> Result<(Vec<Value>, Vec<Value>, Map<String, Value>)> {
    let wishlist = crate::clients::abr_json(&app.cfg, &app.http, "/api/requests", &app.abr_key).await?.as_array().cloned().unwrap_or_default();
    let manual = crate::clients::abr_json(&app.cfg, &app.http, "/api/requests/manual", &app.abr_key).await?.as_array().cloned().unwrap_or_default();
    let _guard = app.quota_lock.lock().await;
    let ledger = merge_ledger(&load_ledger(&app.cfg.quota_ledger)?, &quota_entries(&wishlist, &manual), now(), app.cfg.quota_days);
    write_atomic(&app.cfg.quota_ledger, &serde_json::to_string(&ledger)?)?;
    Ok((wishlist, manual, ledger))
}

pub async fn poll_once(app: &App) {
    {
        let _guard = app.jobs_lock.lock().await;
        let mut jobs = match load(&app.cfg.state) {
            Ok(j) => j,
            Err(e) => {
                log::error!("jobs: {e}");
                return;
            }
        };
        let keys: Vec<String> = jobs.keys().cloned().collect();
        for key in keys {
            let Some(job) = jobs.get(&key).cloned() else { continue };
            if str_of(job.get("state")) != Some("unbound") {
                continue;
            }
            let known: HashSet<String> = jobs.keys().cloned().collect();
            let hash = match app.qbit.category().await {
                Ok(torrents) => bind(&job, &torrents, &known, &app.cfg.category, 600.0),
                Err(e) => {
                    log::error!("bind {key}: {e}");
                    None
                }
            };
            if let Some(h) = hash {
                let mut bound = jobs.remove(&key).unwrap_or(job);
                set(&mut bound, "hash", json!(h));
                set(&mut bound, "state", json!("pending"));
                log::info!("bound {} to {}", str_of(bound.get("title")).unwrap_or(""), &h[..8.min(h.len())]);
                jobs.insert(h, bound);
            } else if now() - number(&job, "added") > 3600.0 {
                if let Some(j) = jobs.get_mut(&key) {
                    fail(j, "no new abr torrent appeared for this request");
                }
            }
        }
        for (_, job) in jobs.iter_mut() {
            let result = async {
                if matches!(str_of(job.get("state")), Some("pending") | Some("merge-wait")) {
                    step(app, job, now()).await?;
                }
                match_step(app, job, now()).await
            }
            .await;
            if let Err(e) = result {
                // one bad job must not stop the others
                log::error!("{}: {e}", str_of(job.get("hash")).unwrap_or("unbound"));
            }
        }
        if let Err(e) = save(&app.cfg.state, &jobs) {
            log::error!("save jobs: {e}");
        }
    }
    if let Err(e) = snapshot_quota(app).await {
        log::error!("quota snapshot: {e}");
    }
}

pub async fn poll(app: std::sync::Arc<App>) {
    loop {
        poll_once(&app).await;
        tokio::time::sleep(std::time::Duration::from_secs(app.cfg.poll_seconds)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HASH: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    #[test]
    fn webhook_parsing() {
        let job = parse_webhook(&json!({"hash": HASH.to_uppercase(), "asin": "B00ABC1234", "title": "T", "authors": "A B,C D", "source": "T by A B [ENG / M4B]", "indexer": "MyAnonamouse"})).unwrap();
        assert_eq!(job["hash"], HASH);
        assert_eq!(job["authors"], json!(["A B", "C D"]));
        assert_eq!(job["state"], "pending");
        assert!(parse_webhook(&json!({"hash": "../../etc", "asin": "B00ABC1234"})).is_err());
        assert!(parse_webhook(&json!([1, 2])).is_err());
        let job = parse_webhook(&json!({"hash": HASH, "asin": "{bookASIN}", "title": "{bookTitle}", "authors": "", "source": ""})).unwrap();
        assert_eq!((job["asin"].clone(), job["title"].clone()), (Value::Null, json!("")));
        let job = parse_webhook(&json!({"hash": "{torrentInfoHash}", "asin": "B00ABC1234", "title": "T"})).unwrap();
        assert_eq!((job["hash"].clone(), job["state"].clone()), (Value::Null, json!("unbound")));
    }

    #[test]
    fn binding() {
        let job = json!({"added": 1000.0});
        let torrents = vec![json!({"hash": "a", "added_on": 900, "category": "abr"}), json!({"hash": "b", "added_on": 1003, "category": "abr"}),
                            json!({"hash": "c", "added_on": 1001, "category": "other"}), json!({"hash": "d", "added_on": 1002, "category": "abr"})];
        let known: HashSet<String> = ["d".to_string()].into_iter().collect();
        assert_eq!(bind(&job, &torrents, &known, "abr", 600.0).as_deref(), Some("b"));
        assert_eq!(bind(&job, &[json!({"hash": "a", "added_on": 500, "category": "abr"})], &HashSet::new(), "abr", 600.0), None);
    }

    #[test]
    fn book_resolution() {
        let job = json!({"title": "Webhook Title", "authors": ["Hook Author"], "source": "X by Y [GER / MP3]"});
        let product = json!({"title": "The Final Empire", "authors": [{"name": "Brandon Sanderson"}], "series": [{"title": "Mistborn", "sequence": "1"}], "language": "english"});
        assert_eq!(resolve_book(&job, Some(&product)), Book::new("The Final Empire", vec!["Brandon Sanderson".into()], Some("Mistborn".into()), Some("1".into()), "EN"));
        assert_eq!(resolve_book(&job, None), Book::new("Webhook Title", vec!["Hook Author".into()], None, None, "DE"));
        assert_eq!(resolve_book(&json!({"title": "T", "authors": []}), None).language, "Other");
    }

    #[test]
    fn merge_detection() {
        let n = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(needs_merge(&n(&["01.mp3", "02.mp3", "cover.jpg"])));
        assert!(!needs_merge(&n(&["book.m4b", "book.cue", "cover.jpg"])));
        assert!(!needs_merge(&n(&["one.mp3"])));
        assert!(needs_merge(&n(&["Part 1.m4b", "Part 2.m4b", "cover.jpg"])));
    }

    #[test]
    fn copying() {
        let root = std::env::temp_dir().join(format!("importer-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let lib = root.join("lib");
        fs::create_dir_all(&lib).unwrap();
        let src = root.join("dl/Some Torrent");
        fs::create_dir_all(src.join("CD1")).unwrap();
        fs::write(src.join("01.mp3"), b"1").unwrap();
        fs::write(src.join("CD1/02.mp3"), b"2").unwrap();
        let dest = copy_into(&src, &lib, "EN/A B/T").unwrap();
        assert_eq!(file_names(&dest).unwrap(), ["01.mp3", "CD1 - 02.mp3"]);
        assert!(src.join("01.mp3").exists());
        assert!(fs::read_dir(lib.join("EN/A B")).unwrap().all(|e| !e.unwrap().file_name().to_string_lossy().starts_with('.')));
        let single = root.join("book.m4b");
        fs::write(&single, b"m").unwrap();
        let dest = copy_into(&single, &lib, "EN/A B/S").unwrap();
        assert_eq!(file_names(&dest).unwrap(), ["book.m4b"]);
        assert!(single.exists());
        let err = copy_into(&single, &lib, "EN/A B/T").unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::AlreadyExists);
        assert_eq!(file_names(&lib.join("EN/A B/T")).unwrap(), ["01.mp3", "CD1 - 02.mp3"]);
        fs::remove_dir_all(&root).unwrap();
    }
}
