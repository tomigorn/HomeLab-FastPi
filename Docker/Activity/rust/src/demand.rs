//! Polls only while someone views the page: a viewer counts for `window` after its last `/api/state`; while one counts, a poll every `every`.
//! The first viewer after an idle spell gets one immediate poll; concurrent viewers wait for that same poll.

use std::future::Future;
use std::sync::Mutex;
use std::time::Duration;

use tokio::sync::{watch, Notify};
use tokio::time::Instant;

struct S {
    seen: Option<Instant>,
    /// Poll generation the waiting viewers need, while an immediate poll is due or running.
    pending: Option<u64>,
    done: u64,
    /// the last poll's end, or the moment polling became due after an idle spell
    progress: Option<Instant>,
}

pub struct Demand {
    every: Duration,
    window: Duration,
    s: Mutex<S>,
    kick: Notify,
    done: watch::Sender<u64>,
}

impl Demand {
    pub fn new(every: Duration, window: Duration) -> Demand {
        Demand { every, window, s: Mutex::new(S { seen: None, pending: None, done: 0, progress: None }), kick: Notify::new(), done: watch::channel(0).0 }
    }

    fn active_at(&self, s: &S, now: Instant) -> bool {
        s.seen.is_some_and(|t| now.duration_since(t) < self.window)
    }

    /// A viewer was seen within the window.
    pub fn active(&self) -> bool {
        self.s.lock().map(|s| self.active_at(&s, Instant::now())).unwrap_or(false)
    }

    /// A page asked for the state. Returns the poll to wait for when an immediate poll is due (first viewer after idle), else None.
    pub fn viewer(&self) -> Option<u64> {
        let now = Instant::now();
        let Ok(mut s) = self.s.lock() else { return None };
        let idle = !self.active_at(&s, now);
        s.seen = Some(now);
        if idle && s.pending.is_none() {
            s.pending = Some(s.done + 1);
            s.progress = Some(now);
            self.kick.notify_one();
        }
        s.pending
    }

    /// Waits until poll `target` has finished, at most `max`.
    pub async fn wait(&self, target: u64, max: Duration) {
        let mut rx = self.done.subscribe();
        let _ = tokio::time::timeout(max, rx.wait_for(|d| *d >= target)).await;
    }

    /// A poll is due but none has finished for over 2 x `every` + 60 s: the loop is stuck or gone.
    pub fn overdue(&self) -> bool {
        let now = Instant::now();
        self.s
            .lock()
            .map(|s| {
                let due = s.pending.is_some() || self.active_at(&s, now);
                due && s.progress.is_some_and(|p| now.duration_since(p) > self.every * 2 + Duration::from_secs(60))
            })
            .unwrap_or(true)
    }

    fn pending(&self) -> bool {
        self.s.lock().map(|s| s.pending.is_some()).unwrap_or(false)
    }

    fn due(&self) -> bool {
        self.s.lock().map(|s| s.pending.is_some() || self.active_at(&s, Instant::now())).unwrap_or(false)
    }

    /// The poll loop: nothing at all while nobody views.
    pub async fn run<F, Fut>(&self, mut poll: F)
    where
        F: FnMut() -> Fut,
        Fut: Future<Output = ()>,
    {
        loop {
            while !self.due() {
                self.kick.notified().await;
            }
            poll().await;
            if let Ok(mut s) = self.s.lock() {
                s.done += 1;
                s.pending = None;
                s.progress = Some(Instant::now());
                self.done.send_replace(s.done);
            }
            // a kick cuts the pause short only for a viewer that is waiting (a permit left from before the poll is stale)
            let next = Instant::now() + self.every;
            loop {
                tokio::select! {
                    _ = tokio::time::sleep_until(next) => break,
                    _ = self.kick.notified() => if self.pending() { break },
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    const EVERY: Duration = Duration::from_secs(30);
    const WINDOW: Duration = Duration::from_secs(120);

    /// The loop on the test runtime, counting polls; each poll takes `takes`.
    fn start(takes: Duration) -> (Arc<Demand>, Arc<AtomicU32>) {
        let d = Arc::new(Demand::new(EVERY, WINDOW));
        let n = Arc::new(AtomicU32::new(0));
        let (d2, n2) = (d.clone(), n.clone());
        tokio::spawn(async move {
            d2.run(|| {
                let n = n2.clone();
                async move {
                    n.fetch_add(1, Ordering::SeqCst);
                    tokio::time::sleep(takes).await;
                }
            })
            .await
        });
        (d, n)
    }

    async fn page(d: &Demand) {
        if let Some(t) = d.viewer() {
            d.wait(t, Duration::from_secs(5)).await;
        }
    }

    async fn secs(s: u64) {
        tokio::time::sleep(Duration::from_secs(s)).await;
    }

    #[tokio::test(start_paused = true)]
    async fn no_viewer_no_poll() {
        let (d, n) = start(Duration::ZERO);
        secs(3600).await;
        assert_eq!(n.load(Ordering::SeqCst), 0);
        assert!(!d.active());
    }

    #[tokio::test(start_paused = true)]
    async fn first_view_polls_at_once_then_every_30s_until_120s_after_the_last_view() {
        let (d, n) = start(Duration::ZERO);
        secs(10).await;
        page(&d).await;
        assert_eq!(n.load(Ordering::SeqCst), 1, "the first view after idle waits for one poll");
        assert!(d.active());
        secs(1).await;
        assert_eq!(n.load(Ordering::SeqCst), 1, "no second poll before 30 s");
        secs(30).await;
        assert_eq!(n.load(Ordering::SeqCst), 2);
        page(&d).await;
        assert_eq!(n.load(Ordering::SeqCst), 2, "a view while active polls nothing extra");
        // last view at ~41 s: polls at 0, 30, 60, 90, 120, 150 s after the first, none from 161 s on
        secs(600).await;
        assert_eq!(n.load(Ordering::SeqCst), 6);
        assert!(!d.active());
        secs(600).await;
        assert_eq!(n.load(Ordering::SeqCst), 6, "idle again: no poll");
    }

    #[tokio::test(start_paused = true)]
    async fn viewer_kept_alive_polls_every_30s() {
        let (d, n) = start(Duration::ZERO);
        page(&d).await;
        for _ in 0..19 {
            secs(15).await;
            page(&d).await;
        }
        // 285 s with a viewer: polls at 0, 30, ..., 270 s
        assert_eq!(n.load(Ordering::SeqCst), 10);
    }

    #[tokio::test(start_paused = true)]
    async fn concurrent_first_views_share_one_poll() {
        let (d, n) = start(Duration::from_secs(1));
        let t0 = Instant::now();
        let views: Vec<_> = (0..5).map(|_| {
            let d = d.clone();
            tokio::spawn(async move { page(&d).await; Instant::now() })
        }).collect();
        for v in views {
            let at = v.await.unwrap();
            assert!(at.duration_since(t0) >= Duration::from_secs(1), "every view waited for the poll");
        }
        assert_eq!(n.load(Ordering::SeqCst), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn a_slow_poll_answers_after_5s_with_what_is_there() {
        let (d, n) = start(Duration::from_secs(60));
        let t0 = Instant::now();
        page(&d).await;
        let waited = Instant::now().duration_since(t0);
        assert!(waited >= Duration::from_secs(5) && waited < Duration::from_secs(6), "{waited:?}");
        assert_eq!(n.load(Ordering::SeqCst), 1);
        page(&d).await;
        assert_eq!(n.load(Ordering::SeqCst), 1, "the second view does not start another poll");
    }

    #[tokio::test(start_paused = true)]
    async fn overdue_only_when_a_due_poll_does_not_come() {
        let d = Arc::new(Demand::new(EVERY, WINDOW));
        assert!(!d.overdue(), "idle is not overdue");
        let _ = d.viewer();
        secs(2 * 30 + 59).await;
        assert!(!d.overdue());
        secs(2).await;
        assert!(d.overdue(), "a viewer waits and no poll ran for over 2 x POLL_SECONDS + 60 s: the poller is dead");
        let (d, _) = start(Duration::ZERO);
        page(&d).await;
        secs(110).await;
        assert!(!d.overdue(), "a running loop is never overdue");
        secs(3600).await;
        assert!(!d.overdue(), "idle again");
    }
}
