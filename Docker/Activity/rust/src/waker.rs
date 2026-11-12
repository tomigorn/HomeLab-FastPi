//! Beefy-Waker `/status` (fastpi, never wakes beefy): up, asleep, waking, broken or unknown.

use std::time::Duration;

use serde::Deserialize;

use crate::client::{self, BaseUrl};
use crate::state::WakerState;

pub const TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Deserialize)]
struct Status {
    up: Option<bool>,
    phase: Option<String>,
}

/// `up`, else the wake phase: idle = asleep, waking/retrying/power_cycle = waking, broken = the wake failed.
pub fn parse_status(body: &[u8]) -> WakerState {
    let Ok(s) = serde_json::from_slice::<Status>(body) else { return WakerState::Unknown };
    match (s.up, s.phase.as_deref()) {
        (Some(true), _) => WakerState::Up,
        (Some(false), None | Some("idle")) => WakerState::Down,
        (Some(false), Some("waking" | "retrying" | "power_cycle")) => WakerState::Waking,
        (Some(false), Some("broken")) => WakerState::Broken,
        _ => WakerState::Unknown,
    }
}

pub async fn status(waker: &BaseUrl) -> WakerState {
    match client::get(waker, "/status", &[("accept", "application/json")], 4096, TIMEOUT).await {
        Ok(body) => parse_status(&body),
        Err(_) => WakerState::Unknown,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_up_down_unknown() {
        assert_eq!(parse_status(br#"{"up": true, "phase": "idle", "seconds_left": null, "reason": ""}"#), WakerState::Up);
        assert_eq!(parse_status(br#"{"up": false, "phase": "idle"}"#), WakerState::Down);
        assert_eq!(parse_status(br#"{"up": false}"#), WakerState::Down);
        assert_eq!(parse_status(br#"{"phase": "idle"}"#), WakerState::Unknown);
        assert_eq!(parse_status(b"<html>"), WakerState::Unknown);
    }

    #[test]
    fn a_wake_in_progress_or_failed_is_not_asleep() {
        for phase in ["waking", "retrying", "power_cycle"] {
            assert_eq!(parse_status(format!(r#"{{"up": false, "phase": "{phase}"}}"#).as_bytes()), WakerState::Waking, "{phase}");
        }
        assert_eq!(parse_status(br#"{"up": false, "phase": "broken"}"#), WakerState::Broken);
        assert_eq!(parse_status(br#"{"up": false, "phase": "something new"}"#), WakerState::Unknown);
        assert_eq!(parse_status(br#"{"up": true, "phase": "waking"}"#), WakerState::Up, "up wins");
    }

    #[tokio::test]
    async fn unreachable_waker_is_unknown() {
        let closed = BaseUrl::parse("http://127.0.0.1:9").unwrap();
        assert_eq!(status(&closed).await, WakerState::Unknown);
    }
}
