use std::env;
use std::path::PathBuf;

fn get(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

fn num<T: std::str::FromStr>(name: &str, default: T) -> T {
    env::var(name).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

#[derive(Clone, Debug)]
pub struct Config {
    pub qbit_url: String,
    pub qbit_user: String,
    pub category: String,
    pub library: PathBuf,
    pub state: PathBuf,
    pub abs_url: String,
    pub abs_folder: String,
    pub audible_regions: Vec<String>,
    pub audible_base: String,
    pub audnexus_url: String,
    pub poll_seconds: u64,
    pub give_up_days: f64,
    pub merge_wait_hours: f64,
    pub match_give_up_hours: f64,
    pub prowlarr_url: String,
    pub proxy_base: String,
    pub quota_books: usize,
    pub quota_days: f64,
    pub quota_ledger: PathBuf,
    pub books_proxy_ip: String,
    pub abr_ip: String,
    pub abr_host: String,
    pub abr_url: String,
    pub qbit_pass_file: String,
    pub abs_key_file: String,
    pub abr_key_file: String,
    pub port: u16,
}

pub const MAX_BODY: usize = 1024 * 1024;
pub const WEBHOOK_BODY: usize = 65536;

impl Config {
    pub fn from_env() -> Config {
        Config {
            qbit_url: get("QBIT_URL", "http://10.24.25.2:8080"),
            qbit_user: get("QBIT_USER", "admin"),
            category: get("CATEGORY", "abr"),
            library: PathBuf::from(get("LIBRARY", "/library")),
            state: PathBuf::from(get("STATE", "/data/jobs.json")),
            abs_url: get("ABS_URL", "https://audiobookshelf.holy-grail.ch"),
            abs_folder: get("ABS_FOLDER", "/audiobooks"),
            audible_regions: get("AUDIBLE_REGIONS", "com,de,co.uk").split(',').map(str::to_string).collect(),
            audible_base: get("AUDIBLE_BASE", "https://api.audible"),
            audnexus_url: get("AUDNEXUS_URL", "https://api.audnex.us"),
            poll_seconds: num("POLL_SECONDS", 60),
            give_up_days: num("GIVE_UP_DAYS", 14.0),
            merge_wait_hours: num("MERGE_WAIT_HOURS", 48.0),
            match_give_up_hours: num("MATCH_GIVE_UP_HOURS", 24.0),
            prowlarr_url: get("PROWLARR_URL", "http://10.24.25.2:9697"),
            proxy_base: get("PROXY_BASE", "http://audiobook-importer:8000/prowlarr"),
            quota_books: num("QUOTA_BOOKS", 5),
            quota_days: num("QUOTA_DAYS", 7.0),
            quota_ledger: PathBuf::from(get("QUOTA_LEDGER", "/data/quota.json")),
            books_proxy_ip: get("BOOKS_PROXY_IP", "10.24.25.6"),
            abr_ip: get("ABR_IP", "10.24.25.4"),
            abr_host: get("ABR_HOST", "audiobookrequest"),
            abr_url: get("ABR_URL", "http://audiobookrequest:8000"),
            qbit_pass_file: get("QBIT_PASS_FILE", ""),
            abs_key_file: get("ABS_KEY_FILE", ""),
            abr_key_file: get("ABR_KEY_FILE", ""),
            port: num("PORT", 8000),
        }
    }

    pub fn abs_path(&self, rel: &str) -> String {
        format!("{}/{}", self.abs_folder, rel)
    }
}

pub fn secret(path: &str) -> String {
    if path.is_empty() {
        return String::new();
    }
    std::fs::read_to_string(path).map(|s| s.trim().to_string()).unwrap_or_default()
}
