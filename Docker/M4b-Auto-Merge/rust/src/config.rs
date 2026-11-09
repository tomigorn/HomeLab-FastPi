use chrono::NaiveTime;
use std::path::PathBuf;

pub struct Config {
    pub lib: PathBuf,
    pub merge_dir: PathBuf,
    pub quiet: i64,
    pub retry: i64,
    pub jobs: String,
    pub sweep_dow: i64,
    pub sweep_time: Result<NaiveTime, String>,
}

fn int(get: &dyn Fn(&str) -> Option<String>, name: &str, default: i64) -> Result<i64, String> {
    match get(name) {
        None => Ok(default),
        Some(v) => v.trim().parse().map_err(|_| format!("{name} must be an integer, got {v:?}")),
    }
}

impl Config {
    pub fn from(get: &dyn Fn(&str) -> Option<String>) -> Result<Config, String> {
        let hour = int(get, "SWEEP_HOUR", 4)?;
        let minute = int(get, "SWEEP_MINUTE", 0)?;
        let sweep_time = u32::try_from(hour)
            .ok()
            .zip(u32::try_from(minute).ok())
            .and_then(|(h, m)| NaiveTime::from_hms_opt(h, m, 0))
            .ok_or_else(|| format!("SWEEP_HOUR={hour} SWEEP_MINUTE={minute} is not a time of day"));
        Ok(Config {
            lib: get("LIB_DIR").unwrap_or_else(|| "/mnt/seagate-black/library/audiobooks".into()).into(),
            merge_dir: get("MERGE_DIR").unwrap_or_else(|| "/home/pi/Projects/Docker/audiobookshelf/m4b-merge".into()).into(),
            quiet: int(get, "QUIET_SECONDS", 300)?,
            retry: int(get, "RETRY_SECONDS", 900)?,
            jobs: get("JOBS").unwrap_or_else(|| "10".into()),
            sweep_dow: int(get, "SWEEP_DOW", 5)?,
            sweep_time,
        })
    }

    pub fn from_env() -> Result<Config, String> {
        Config::from(&|k| std::env::var(k).ok())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn cfg(pairs: &[(&str, &str)]) -> Result<Config, String> {
        let m: HashMap<String, String> = pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        Config::from(&move |k| m.get(k).cloned())
    }

    #[test]
    fn defaults_match_the_python_watcher() {
        let c = cfg(&[]).unwrap();
        assert_eq!(c.lib, PathBuf::from("/mnt/seagate-black/library/audiobooks"));
        assert_eq!(c.merge_dir, PathBuf::from("/home/pi/Projects/Docker/audiobookshelf/m4b-merge"));
        assert_eq!((c.quiet, c.retry, c.jobs.as_str(), c.sweep_dow), (300, 900, "10", 5));
        assert_eq!(c.sweep_time, Ok(NaiveTime::from_hms_opt(4, 0, 0).unwrap()));
    }

    #[test]
    fn integers_are_trimmed_and_checked() {
        let c = cfg(&[("QUIET_SECONDS", " 12 "), ("RETRY_SECONDS", "+7"), ("JOBS", "abc")]).unwrap();
        assert_eq!((c.quiet, c.retry, c.jobs.as_str()), (12, 7, "abc"));
        assert!(cfg(&[("QUIET_SECONDS", "5m")]).is_err());
    }

    #[test]
    fn a_bad_sweep_time_only_disables_the_sweep() {
        assert!(cfg(&[("SWEEP_HOUR", "25")]).unwrap().sweep_time.is_err());
        assert!(cfg(&[("SWEEP_MINUTE", "-1")]).unwrap().sweep_time.is_err());
    }
}
