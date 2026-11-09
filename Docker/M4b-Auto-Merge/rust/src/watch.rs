use inotify::{EventMask, Inotify, WatchDescriptor, WatchMask};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use crate::log;
use crate::trigger::Trigger;

// No IN_OPEN, IN_ACCESS or IN_CLOSE_NOWRITE: a read (an ABS scan, a find) changes nothing.
fn mask() -> WatchMask {
    WatchMask::MODIFY
        | WatchMask::ATTRIB
        | WatchMask::CLOSE_WRITE
        | WatchMask::MOVED_FROM
        | WatchMask::MOVED_TO
        | WatchMask::CREATE
        | WatchMask::DELETE
        | WatchMask::DELETE_SELF
        | WatchMask::MOVE_SELF
}

pub struct Watcher {
    inotify: Inotify,
    dirs: HashMap<WatchDescriptor, PathBuf>,
}

impl Watcher {
    pub fn new(root: &Path) -> std::io::Result<Watcher> {
        let mut w = Watcher { inotify: Inotify::init()?, dirs: HashMap::new() };
        w.add_tree(root);
        Ok(w)
    }

    /// Watch `dir` and every folder below it (symlinks not followed); re-adding a known folder refreshes its path after a move.
    fn add_tree(&mut self, dir: &Path) {
        let mut stack = vec![dir.to_path_buf()];
        while let Some(d) = stack.pop() {
            match self.inotify.watches().add(&d, mask()) {
                Ok(wd) => {
                    self.dirs.insert(wd, d.clone());
                }
                Err(e) => {
                    log(&format!("cannot watch {}: {e}", d.display()));
                    continue;
                }
            }
            if let Ok(entries) = fs::read_dir(&d) {
                for e in entries.flatten() {
                    if e.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                        stack.push(e.path());
                    }
                }
            }
        }
    }

    pub fn run(mut self, trigger: &Trigger) {
        let mut buf = vec![0u8; 64 * 1024];
        loop {
            let mut changed = false;
            let mut new_dirs = Vec::new();
            match self.inotify.read_events_blocking(&mut buf) {
                Ok(events) => {
                    for ev in events {
                        if ev.mask.contains(EventMask::Q_OVERFLOW) {
                            changed = true;
                            continue;
                        }
                        if ev.mask.contains(EventMask::IGNORED) {
                            self.dirs.remove(&ev.wd);
                            continue;
                        }
                        changed = true;
                        if ev.mask.contains(EventMask::ISDIR) && ev.mask.intersects(EventMask::CREATE | EventMask::MOVED_TO) {
                            if let (Some(parent), Some(name)) = (self.dirs.get(&ev.wd), ev.name) {
                                new_dirs.push(parent.join(name));
                            }
                        }
                    }
                }
                Err(e) => {
                    log(&format!("inotify read failed: {e}"));
                    std::thread::sleep(std::time::Duration::from_secs(1));
                }
            }
            for d in new_dirs {
                self.add_tree(&d);
            }
            if changed {
                trigger.touch(false);
            }
        }
    }
}
