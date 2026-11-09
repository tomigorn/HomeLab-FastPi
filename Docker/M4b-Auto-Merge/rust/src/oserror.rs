use std::io;
use std::path::Path;

/// An OS error the way Python prints an OSError: `[Errno 13] Permission denied: '/path'`.
pub fn python_style(e: &io::Error, path: &Path) -> String {
    match e.raw_os_error() {
        Some(code) => {
            let text = e.to_string();
            let text = text.strip_suffix(&format!(" (os error {code})")).unwrap_or(&text).to_string();
            format!("[Errno {code}] {text}: '{}'", path.display())
        }
        None => format!("{e}: '{}'", path.display()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errno_text_and_quoted_path() {
        let e = io::Error::from_raw_os_error(13);
        assert_eq!(python_style(&e, Path::new("/m/orchestrate.py")), "[Errno 13] Permission denied: '/m/orchestrate.py'");
        let e = io::Error::from_raw_os_error(2);
        assert_eq!(python_style(&e, Path::new("/x")), "[Errno 2] No such file or directory: '/x'");
    }

    #[test]
    fn non_os_error_keeps_its_message() {
        let e = io::Error::new(io::ErrorKind::Other, "boom");
        assert_eq!(python_style(&e, Path::new("/x")), "boom: '/x'");
    }
}
