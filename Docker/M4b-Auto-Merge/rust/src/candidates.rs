use std::fs;
use std::path::{Path, PathBuf};

const AUDIO_EXT: [&str; 7] = [".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".flac", ".wav"];
const IN_PROGRESS: [&str; 5] = [".part", ".!qb", ".crdownload", ".tmp", ".filepart"];

/// Extension the way Python's os.path.splitext sees it: leading dots belong to the name.
pub fn extension(name: &str) -> &str {
    let stem_start = name.len() - name.trim_start_matches('.').len();
    match name[stem_start..].rfind('.') {
        Some(i) => &name[stem_start + i..],
        None => "",
    }
}

/// Does this folder (lower-cased file names) hold a book worth starting a run for?
pub fn is_candidate(files: &[String]) -> bool {
    if files.iter().any(|f| f.contains(".m4b.part") || f == ".m4b-merge-promoting") {
        return false;
    }
    if files.iter().any(|f| IN_PROGRESS.iter().any(|s| f.ends_with(s))) {
        return false;
    }
    files.iter().filter(|f| AUDIO_EXT.contains(&extension(f))).count() >= 2
}

/// Every folder under `root` (itself included, hidden folders and symlinked folders not descended) holding two or more audio files.
pub fn candidates(root: &Path) -> Vec<PathBuf> {
    let mut found = Vec::new();
    walk(root, &mut found);
    found
}

fn walk(dir: &Path, found: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else { return };
    let mut dirs = Vec::new();
    let mut files = Vec::new();
    for e in entries.flatten() {
        let name = e.file_name().to_string_lossy().to_lowercase();
        let Ok(ft) = e.file_type() else { continue };
        if ft.is_symlink() {
            // like os.walk: a link to a folder is neither descended nor a file
            if !fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false) {
                files.push(name);
            }
        } else if ft.is_dir() {
            if !e.file_name().to_string_lossy().starts_with('.') {
                dirs.push(e.path());
            }
        } else {
            files.push(name);
        }
    }
    if is_candidate(&files) {
        found.push(dir.to_path_buf());
    }
    for d in dirs {
        walk(&d, found);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn scratch(files: &[&str]) -> PathBuf {
        static N: AtomicUsize = AtomicUsize::new(0);
        let d = std::env::temp_dir().join(format!("cand-{}-{}", std::process::id(), N.fetch_add(1, Ordering::SeqCst)));
        for f in files {
            let p = d.join(f);
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(p, b"x").unwrap();
        }
        fs::create_dir_all(&d).unwrap();
        d
    }

    fn names(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn extension_follows_python_splitext() {
        assert_eq!(extension("a.mp3"), ".mp3");
        assert_eq!(extension("a.b.flac"), ".flac");
        assert_eq!(extension(".mp3"), "");
        assert_eq!(extension("..mp3"), "");
        assert_eq!(extension("...a.mp3"), ".mp3");
        assert_eq!(extension("noext"), "");
        assert_eq!(extension("trailing."), ".");
    }

    #[test]
    fn two_audio_files_make_a_candidate() {
        assert!(is_candidate(&names(&["01.mp3", "02.m4a"])));
        assert!(!is_candidate(&names(&["01.mp3", "cover.jpg", "x.aac"])));
        assert!(!is_candidate(&names(&[".mp3", "a.mp3"])));
    }

    #[test]
    fn markers_skip_the_folder() {
        for m in ["x.part", "x.!qb", "x.crdownload", "x.tmp", "x.filepart", ".m4b-merge-promoting", "..b.m4b.part.ab12"] {
            assert!(!is_candidate(&names(&["01.mp3", "02.mp3", m])), "{m}");
        }
    }

    #[test]
    fn walk_counts_root_nested_and_case_but_not_hidden() {
        let d = scratch(&["01.mp3", "02.mp3", "U/A.MP3", "U/B.Flac", "P/1.ogg", "P/2.opus", "P/C/1.wav", "P/C/2.m4b",
                          "S/1.mp3", ".h/1.mp3", ".h/2.mp3", "V/.t/1.mp3", "V/.t/2.mp3"]);
        let mut got: Vec<_> = candidates(&d).into_iter().map(|p| p.strip_prefix(&d).unwrap().to_string_lossy().into_owned()).collect();
        got.sort();
        assert_eq!(got, ["", "P", "P/C", "U"]);
    }

    #[test]
    fn symlinks_count_as_files_unless_they_point_at_folders() {
        let d = scratch(&["Real/01.mp3", "Real/02.mp3", "Links/01.mp3"]);
        std::os::unix::fs::symlink(d.join("Real/01.mp3"), d.join("Links/02.mp3")).unwrap();
        std::os::unix::fs::symlink(d.join("Real"), d.join("Links/dir.mp3")).unwrap();
        fs::create_dir_all(d.join("Broken")).unwrap();
        std::os::unix::fs::symlink(d.join("nope1.mp3"), d.join("Broken/a.mp3")).unwrap();
        std::os::unix::fs::symlink(d.join("nope2.mp3"), d.join("Broken/b.mp3")).unwrap();
        fs::create_dir_all(d.join("Via")).unwrap();
        std::os::unix::fs::symlink(d.join("Real"), d.join("Via/link")).unwrap();
        assert_eq!(candidates(&d).len(), 3);
    }

    #[test]
    fn missing_root_has_no_candidates() {
        assert!(candidates(Path::new("/nonexistent-m4b-root")).is_empty());
    }
}
