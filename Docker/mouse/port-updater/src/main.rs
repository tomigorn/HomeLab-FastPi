mod clients;
mod config;
mod events;
mod updater;
mod web;

use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;

use tokio::signal::unix::{SignalKind, signal};

/// `port-updater probe URL [METHOD]`: prints the HTTP status (000 on failure); for checks, the image has no curl.
fn probe(url: &str, method: &str) -> ExitCode {
    if !url.starts_with("http://") {
        eprintln!("probe: only http:// URLs");
        return ExitCode::from(2);
    }
    let a = clients::agent(Duration::from_secs(5));
    let code = match method {
        "GET" => clients::status(a.get(url).call()),
        "POST" => clients::status(a.post(url).send_empty()),
        _ => {
            eprintln!("probe: method GET or POST");
            return ExitCode::from(2);
        }
    };
    println!("{code:03}");
    ExitCode::SUCCESS
}

fn self_test() -> ExitCode {
    let zh = jiff::tz::TimeZone::get("Europe/Zurich");
    let ts = zh.as_ref().map(|tz| events::timestamp(Some(tz), &jiff::Zoned::now()));
    match ts {
        Ok(ts) if ts.len() == 24 => {
            println!("ok {} {ts}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        other => {
            eprintln!("self-test failed: {other:?}");
            ExitCode::FAILURE
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        [] => {}
        ["probe", url] => return probe(url, "GET"),
        ["probe", url, m] => return probe(url, m),
        ["--self-test"] => return self_test(),
        ["--version"] => {
            println!("port-updater {}", env!("CARGO_PKG_VERSION"));
            return ExitCode::SUCCESS;
        }
        _ => {
            eprintln!("usage: port-updater [probe URL [GET|POST] | --self-test | --version]");
            return ExitCode::from(2);
        }
    }

    let cfg = match config::Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::FAILURE;
        }
    };
    let state = Arc::new(web::State::new(&cfg.web_user, &cfg.web_pass, cfg.data_file.clone()));
    let warm = state.clone();
    std::thread::spawn(move || warm.real_ip());

    let port = cfg.web_port;
    std::thread::spawn(move || {
        if let Err(e) = updater::Updater::new(cfg).run() {
            eprintln!("port-updater: fatal: {e}");
            std::process::exit(1);
        }
    });

    let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
        Ok(rt) => rt,
        Err(e) => {
            eprintln!("runtime: {e}");
            return ExitCode::FAILURE;
        }
    };
    rt.block_on(async move {
        let (Ok(mut term), Ok(mut int)) = (signal(SignalKind::terminate()), signal(SignalKind::interrupt())) else {
            eprintln!("cannot install signal handlers");
            return ExitCode::FAILURE;
        };
        tokio::spawn(async move {
            if let Err(e) = web::serve(port, state).await {
                eprintln!("[web-server] {e}");
            }
        });
        tokio::select! {
            _ = term.recv() => ExitCode::SUCCESS,
            _ = int.recv() => ExitCode::SUCCESS,
        }
    })
}
