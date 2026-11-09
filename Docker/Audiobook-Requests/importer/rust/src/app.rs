//! Shared state: clients, locks and the two caches (ABS listing, book preferences per search).
use crate::clients::{abr_json, audible, Abs, Qbit};
use crate::config::Config;
use crate::library::{book_library_ids, ItemsByLib};
use crate::ranking::{prefs_from_product, Prefs};
use crate::util::{str_of, Result};
use reqwest::Client;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

pub struct App {
    pub cfg: Arc<Config>,
    pub http: Client,
    pub qbit: Qbit,
    pub abs: Abs,
    pub abr_key: String,
    pub jobs_lock: Mutex<()>,
    pub quota_lock: Mutex<()>,
    prefs_cache: Mutex<HashMap<String, (Instant, Prefs)>>,
    abs_cache: Mutex<AbsCache>,
}

/// ABS libraries, book items and users for the library page and sizes, fetched with the importer's ABS key (GET only), kept a few minutes.
#[derive(Default)]
struct AbsCache {
    at: Option<Instant>,
    users_at: Option<Instant>,
    data: Option<(Vec<Value>, ItemsByLib)>,
    users: Vec<Value>,
}

const ABS_TTL: Duration = Duration::from_secs(300);
const USERS_TTL: Duration = Duration::from_secs(60);
const PREFS_TTL: Duration = Duration::from_secs(600);

impl App {
    pub fn new(cfg: Arc<Config>, qbit_password: String, abr_key: String) -> App {
        let http = crate::clients::new_client();
        App {
            qbit: Qbit::new(cfg.clone(), qbit_password),
            abs: Abs::new(cfg.clone(), http.clone()),
            cfg,
            http,
            abr_key,
            jobs_lock: Mutex::new(()),
            quota_lock: Mutex::new(()),
            prefs_cache: Mutex::new(HashMap::new()),
            abs_cache: Mutex::new(AbsCache::default()),
        }
    }

    pub async fn abs_books(&self) -> Result<(Vec<Value>, ItemsByLib)> {
        let mut cache = self.abs_cache.lock().await;
        let stale = cache.data.is_none() || cache.at.is_none_or(|t| t.elapsed() > ABS_TTL);
        if stale {
            let libs = self.abs.libraries().await?;
            let mut items = Map::new();
            for id in book_library_ids(&libs) {
                let found = self.abs.items(&id).await?;
                items.insert(id, Value::Array(found));
            }
            cache.data = Some((libs, items));
            cache.at = Some(Instant::now());
        }
        Ok(cache.data.clone().unwrap_or_default())
    }

    pub async fn abs_users(&self) -> Result<Vec<Value>> {
        let mut cache = self.abs_cache.lock().await;
        if cache.users_at.is_none_or(|t| t.elapsed() > USERS_TTL) {
            cache.users = self.abs.users().await?;
            cache.users_at = Some(Instant::now());
        }
        Ok(cache.users.clone())
    }

    /// Preferences of the book behind a Prowlarr search: language + abridged from its Audible edition, authors + narrators from ABR's request.
    pub async fn prefs(&self, query: &str) -> Prefs {
        if let Some((at, prefs)) = self.prefs_cache.lock().await.get(query) {
            if at.elapsed() < PREFS_TTL {
                return prefs.clone();
            }
        }
        let mut wishlist: Vec<Value> = vec![];
        let mut product = None;
        if !self.abr_key.is_empty() {
            match abr_json(&self.cfg, &self.http, "/api/requests", &self.abr_key).await {
                Ok(v) => {
                    wishlist = v.as_array().cloned().unwrap_or_default();
                    let asin = wishlist
                        .iter()
                        .find(|w| w.get("book").and_then(|b| str_of(b.get("title"))) == Some(query))
                        .and_then(|w| w.get("book").and_then(|b| str_of(b.get("asin"))))
                        .map(String::from);
                    product = audible(&self.cfg, &self.http, asin.as_deref()).await.0;
                }
                Err(e) => log::warn!("request lookup for {query:?}: {e}"),
            }
        }
        let prefs = book_prefs(query, &wishlist, product.as_ref());
        self.prefs_cache.lock().await.insert(query.to_string(), (Instant::now(), prefs.clone()));
        prefs
    }
}

/// Every request with this title counts (ABR searches by title only); ABR's names first, the Audible product as fallback.
pub fn book_prefs(query: &str, wishlist: &[Value], product: Option<&Value>) -> Prefs {
    let base = prefs_from_product(product);
    let books: Vec<&Value> = wishlist.iter().filter_map(|w| w.get("book")).filter(|b| str_of(b.get("title")) == Some(query)).collect();
    let names = |key: &str| -> Vec<String> {
        let mut out: Vec<String> = vec![];
        for b in &books {
            for n in b.get(key).and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str) {
                if !n.is_empty() && !out.iter().any(|o| o == n) {
                    out.push(n.to_string());
                }
            }
        }
        out
    };
    let authors = names("authors");
    let narrators = names("narrators");
    Prefs {
        authors: if authors.is_empty() { base.authors } else { authors },
        narrators: if narrators.is_empty() { base.narrators } else { narrators },
        ..base
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn wishlist() -> Vec<Value> {
        vec![json!({"book": {"title": "Sense and Sensibility", "asin": "0473434644", "authors": ["Jane Austen"], "narrators": ["Karen Savage"]}}),
             json!({"book": {"title": "Other", "asin": "B000000001", "authors": ["Someone"], "narrators": ["Reader"]}})]
    }

    #[test]
    fn prefs_of_the_requested_book() {
        let p = book_prefs("Sense and Sensibility", &wishlist(), Some(&json!({"language": "english"})));
        assert_eq!((p.language.as_str(), p.authors.clone(), p.narrators.clone()), ("EN", vec!["Jane Austen".to_string()], vec!["Karen Savage".to_string()]));
        let mut more = wishlist();
        more.push(json!({"book": {"title": "Sense and Sensibility", "asin": "B000000002", "authors": ["Joanna Trollope"], "narrators": []}}));
        assert_eq!(book_prefs("Sense and Sensibility", &more, None).authors, ["Jane Austen", "Joanna Trollope"]);
        let p = book_prefs("T", &[json!({"book": {"title": "T", "asin": "B000000003"}})], Some(&json!({"authors": [{"name": "A"}], "narrators": [{"name": "N"}]})));
        assert_eq!((p.authors, p.narrators), (vec!["A".to_string()], vec!["N".to_string()]));
        assert!(book_prefs("Nope", &wishlist(), None).authors.is_empty());
    }
}
