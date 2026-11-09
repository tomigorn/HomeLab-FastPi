use std::sync::{Condvar, Mutex};
use std::time::{Duration, Instant};

struct State {
    dirty: bool,
    ready_at: Instant,
}

/// "Something changed under the library": armed by inotify and the sweep, acted on once the tree has been quiet long enough.
pub struct Trigger {
    state: Mutex<State>,
    wake: Condvar,
    quiet: Duration,
}

impl Trigger {
    pub fn new(quiet: Duration) -> Trigger {
        Trigger { state: Mutex::new(State { dirty: false, ready_at: Instant::now() }), wake: Condvar::new(), quiet }
    }

    /// settled = act at once (the weekly sweep fires even when nothing changed).
    pub fn touch(&self, settled: bool) {
        let mut s = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        s.ready_at = if settled { now } else { now + self.quiet };
        s.dirty = true;
        self.wake.notify_all();
    }

    pub fn rearm(&self) {
        self.state.lock().unwrap_or_else(|e| e.into_inner()).dirty = true;
    }

    /// Blocks until armed, quiet and past `not_before`, then disarms.
    pub fn wait(&self, not_before: Option<Instant>) {
        let mut s = self.state.lock().unwrap_or_else(|e| e.into_inner());
        loop {
            if s.dirty {
                let due = not_before.map_or(s.ready_at, |r| r.max(s.ready_at));
                let now = Instant::now();
                if now >= due {
                    s.dirty = false;
                    return;
                }
                s = self.wake.wait_timeout(s, due - now).unwrap_or_else(|e| e.into_inner()).0;
            } else {
                s = self.wake.wait(s).unwrap_or_else(|e| e.into_inner());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::thread;

    const Q: Duration = Duration::from_millis(200);

    #[test]
    fn waits_for_the_quiet_period_after_the_last_touch() {
        let t = Arc::new(Trigger::new(Q));
        let start = Instant::now();
        t.touch(false);
        let t2 = t.clone();
        let h = thread::spawn(move || {
            for _ in 0..3 {
                thread::sleep(Duration::from_millis(100));
                t2.touch(false);
            }
        });
        t.wait(None);
        h.join().unwrap();
        assert!(start.elapsed() >= Duration::from_millis(300) + Q);
    }

    #[test]
    fn settled_touch_acts_at_once() {
        let t = Trigger::new(Duration::from_secs(1000));
        let start = Instant::now();
        t.touch(true);
        t.wait(None);
        assert!(start.elapsed() < Duration::from_millis(100));
    }

    #[test]
    fn not_before_holds_a_rearmed_trigger_back() {
        let t = Trigger::new(Duration::ZERO);
        t.touch(false);
        t.wait(None);
        t.rearm();
        let start = Instant::now();
        t.wait(Some(start + Q));
        assert!(start.elapsed() >= Q);
    }

    #[test]
    fn disarmed_until_touched() {
        let t = Arc::new(Trigger::new(Duration::ZERO));
        let t2 = t.clone();
        let start = Instant::now();
        let h = thread::spawn(move || {
            thread::sleep(Q);
            t2.touch(false);
        });
        t.wait(None);
        h.join().unwrap();
        assert!(start.elapsed() >= Q);
    }
}
