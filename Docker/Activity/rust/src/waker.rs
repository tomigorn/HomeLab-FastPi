//! Beefy-Waker `/status` (fastpi, never wakes beefy): up, down or unknown.

use std::time::Duration;

use serde::Deserialize;

use crate::client::{self, BaseUrl};
use crate::state::WakerState;

pub const TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Deserialize)]
struct Status {
    up: Option<bool>,
}

pub fn parse_status(body: &[u8]) -> WakerState {
    match serde_json::from_slice::<Status>(body).ok().and_then(|s| s.up) {
        Some(true) => WakerState::Up,
        Some(false) => WakerState::Down,
        None => WakerState::Unknown,
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
        assert_eq!(parse_status(br#"{"up": false, "phase": "waking"}"#), WakerState::Down);
        assert_eq!(parse_status(br#"{"phase": "idle"}"#), WakerState::Unknown);
        assert_eq!(parse_status(b"<html>"), WakerState::Unknown);
    }

    #[tokio::test]
    async fn unreachable_waker_is_unknown() {
        let closed = BaseUrl::parse("http://127.0.0.1:9").unwrap();
        assert_eq!(status(&closed).await, WakerState::Unknown);
    }
}
