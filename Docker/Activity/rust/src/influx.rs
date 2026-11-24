//! fastpi container load from Telegraf's docker input in InfluxDB: Audiobookshelf and the mouse download stack; fastpi as a whole from its cpu, mem, swap and disk inputs.
//! Telegraf collects every 30 s anyway; this asks only while the page is viewed (one Flux query per poll, read-only token).

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use crate::client::{self, BaseUrl};
use crate::state::{Disk, FastpiLoad, Host, Load};

const TIMEOUT: Duration = Duration::from_secs(3);
const LIMIT: usize = 64 << 10;

/// fastpi's disks as Telegraf sees them under its `/:/rootfs:ro` mount (grafana docker-compose.yaml), in page order.
const DISKS: [(&str, &str); 3] = [("nvme", "/rootfs"), ("seagate-red", "/rootfs/mnt/seagate-red"), ("seagate-black", "/rootfs/mnt/seagate-black")];

pub struct Influx {
    pub base: BaseUrl,
    pub token_file: PathBuf,
    pub org: String,
    pub bucket: String,
    pub abs: String,
    /// the download containers; the first is the VPN whose netns the others share (its received bytes = the downloads)
    pub downloads: Vec<String>,
}

fn valid(name: &str) -> bool {
    !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
}

impl Influx {
    /// None when a name could break out of the Flux string literals.
    pub fn new(base: BaseUrl, token_file: PathBuf, org: &str, bucket: &str, abs: &str, downloads: &str) -> Option<Influx> {
        let downloads: Vec<String> = downloads.split_whitespace().map(str::to_string).collect();
        (valid(org) && valid(bucket) && valid(abs) && !downloads.is_empty() && downloads.iter().all(|d| valid(d)))
            .then(|| Influx { base, token_file, org: org.into(), bucket: bucket.into(), abs: abs.into(), downloads })
    }

        /// CPU time and traffic as rates over Telegraf's last two samples, memory and the host's CPU count as last values.
    /// Plain equality filters only: InfluxDB pushes them down to the storage (a `contains()` filter scans everything, 4.5 s instead of 40 ms).
    pub fn query(&self) -> String {
        let names: Vec<String> = std::iter::once(&self.abs).chain(&self.downloads).map(|n| format!("r.container_name == \"{n}\"")).collect();
        let from = format!("from(bucket: \"{}\") |> range(start: -90s)", self.bucket);
        format!(
            r#"c = (r) => {names}
cpu = {from} |> filter(fn: (r) => r._measurement == "docker_container_cpu" and r._field == "usage_total" and r.cpu == "cpu-total") |> filter(fn: c) |> derivative(unit: 1s, nonNegative: true) |> last()
net = {from} |> filter(fn: (r) => r._measurement == "docker_container_net" and (r._field == "rx_bytes" or r._field == "tx_bytes") and r.network == "total") |> filter(fn: c) |> derivative(unit: 1s, nonNegative: true) |> last()
mem = {from} |> filter(fn: (r) => r._measurement == "docker_container_mem" and (r._field == "usage" or r._field == "inactive_file")) |> filter(fn: c) |> last() |> toFloat()
cpus = {from} |> filter(fn: (r) => r._measurement == "system" and r._field == "n_cpus") |> last() |> toFloat()
host = {from} |> filter(fn: (r) => (r._measurement == "cpu" and r._field == "usage_idle") or (r._measurement == "mem" and (r._field == "available" or r._field == "total")) or (r._measurement == "swap" and (r._field == "used" or r._field == "total")) or (r._measurement == "disk" and ({paths}) and (r._field == "used" or r._field == "free"))) |> last() |> toFloat()
union(tables: [cpu, net, mem, cpus, host]) |> keep(columns: ["_value", "_field", "container_name", "_measurement", "cpu", "path"]) |> group()
"#,
            names = names.join(" or "),
            paths = DISKS.iter().map(|(_, p)| format!("r.path == \"{p}\"")).collect::<Vec<_>>().join(" or ")
        )
    }

    pub async fn load(&self) -> Result<FastpiLoad, String> {
        let token = std::fs::read_to_string(&self.token_file).map_err(|_| "secret file unreadable".to_string())?;
        let auth = format!("Token {}", token.trim());
        let path = format!("{}/api/v2/query?org={}", self.base.base, self.org);
        let headers = [("authorization", auth.as_str()), ("content-type", "application/vnd.flux"), ("accept", "application/csv")];
        let r = client::request("POST", &self.base.host, self.base.port, &path, &headers, Some(self.query().into_bytes()), LIMIT, TIMEOUT).await?;
        if r.status != 200 {
            return Err(format!("HTTP {}", r.status));
        }
        if r.truncated {
            return Err(format!("answer over {LIMIT} bytes"));
        }
        parse(&String::from_utf8_lossy(&r.body), &self.abs, &self.downloads)
    }
}

/// The annotated-CSV answer (`,result,table,_value,_field,container_name,_measurement,cpu,path`) into the two loads; a container without samples leaves its figures out.
pub fn parse(csv: &str, abs: &str, downloads: &[String]) -> Result<FastpiLoad, String> {
    let mut lines = csv.lines().map(str::trim_end).filter(|l| !l.is_empty() && !l.starts_with('#'));
    let header: Vec<&str> = lines.next().ok_or("empty answer")?.split(',').collect();
    let col = |name: &str| header.iter().position(|h| *h == name).ok_or_else(|| format!("no {name} column"));
    let (iv, ifield, iname) = (col("_value")?, col("_field")?, col("container_name")?);
    let (imeas, icpu, ipath) = (col("_measurement").ok(), col("cpu").ok(), col("path").ok());
    let mut v: HashMap<(String, String), f64> = HashMap::new();
    let mut h: HashMap<(String, String, String), f64> = HashMap::new();
    for l in lines {
        let f: Vec<&str> = l.split(',').collect();
        let at = |i: Option<usize>| i.and_then(|i| f.get(i)).copied().unwrap_or("").to_string();
        if let (Some(val), Some(field)) = (f.get(iv).and_then(|x| x.parse::<f64>().ok()), f.get(ifield)) {
            let (name, meas) = (at(Some(iname)), at(imeas));
            if name.is_empty() && matches!(meas.as_str(), "cpu" | "mem" | "swap" | "disk") {
                let tag = if meas == "disk" { at(ipath) } else { at(icpu) };
                h.insert((meas, tag, field.to_string()), val);
            } else {
                v.insert((name, field.to_string()), val);
            }
        }
    }
    let cpus = v.get(&(String::new(), "n_cpus".into())).copied().filter(|n| *n >= 1.0);
    let get = |c: &str, field: &str| v.get(&(c.to_string(), field.to_string())).copied();
    let cpu = |c: &str| Some(get(c, "usage_total")? / 1e9 / cpus? * 100.0).map(|p| (p * 10.0).round() / 10.0);
    let mem = |c: &str| Some((get(c, "usage")? - get(c, "inactive_file").unwrap_or(0.0)).max(0.0) as u64);
    let kbit = |x: Option<f64>| x.map(|b| (b * 8.0 / 1000.0).round() as u64);
    let some = |l: Load| (l != Load::default()).then_some(l);
    let audiobookshelf = some(Load { cpu_pct: cpu(abs), mem_bytes: mem(abs), up_kbps: kbit(get(abs, "tx_bytes")), down_kbps: None });
    let sum = |xs: Vec<Option<f64>>| xs.iter().any(Option::is_some).then(|| xs.iter().flatten().sum::<f64>());
    let dl_cpu = sum(downloads.iter().map(|c| cpu(c)).collect());
    let dl_mem = sum(downloads.iter().map(|c| mem(c).map(|m| m as f64)).collect());
    let dl = some(Load { cpu_pct: dl_cpu.map(|p| (p * 10.0).round() / 10.0), mem_bytes: dl_mem.map(|m| m as u64), up_kbps: None, down_kbps: kbit(downloads.first().and_then(|c| get(c, "rx_bytes"))) });
    Ok(FastpiLoad { audiobookshelf, downloads: dl, host: host(&h) })
}

fn host(h: &HashMap<(String, String, String), f64>) -> Option<Host> {
    let get = |m: &str, cpu: &str, field: &str| h.get(&(m.to_string(), cpu.to_string(), field.to_string())).copied();
    let busy = |idle: f64| ((100.0 - idle).clamp(0.0, 100.0) * 10.0).round() / 10.0;
    let mut cores: Vec<(u32, f64)> = h
        .iter()
        .filter(|((m, c, f), _)| m == "cpu" && f == "usage_idle" && c.starts_with("cpu") && c != "cpu-total")
        .filter_map(|((_, c, _), idle)| Some((c[3..].parse().ok()?, busy(*idle))))
        .collect();
    cores.sort_by_key(|c| c.0);
    let bytes = |x: Option<f64>| x.filter(|x| *x >= 0.0).map(|x| x as u64);
    let (mem_total, available) = (get("mem", "", "total"), get("mem", "", "available"));
    let host = Host {
        cpu_pct: get("cpu", "cpu-total", "usage_idle").map(busy),
        cores_pct: cores.into_iter().map(|c| c.1).collect(),
        mem_used_bytes: bytes(mem_total.zip(available).map(|(t, a)| t - a)),
        mem_total_bytes: bytes(mem_total),
        swap_used_bytes: bytes(get("swap", "", "used")),
        swap_total_bytes: bytes(get("swap", "", "total")),
        disks: DISKS
            .iter()
            .filter_map(|(disk, path)| {
                let (used, free) = (bytes(get("disk", path, "used"))?, bytes(get("disk", path, "free"))?);
                Some(Disk { disk: disk.to_string(), used_bytes: used, total_bytes: used + free })
            })
            .collect(),
    };
    (host != Host::default()).then_some(host)
}

#[cfg(test)]
mod tests {
    use super::*;

    const ANSWER: &str = include_str!("../fixtures/influx-load.csv");

    fn dl() -> Vec<String> {
        ["gluetun_mouse", "qbittorrent_mouse", "sabnzbd"].map(String::from).to_vec()
    }

    #[test]
    fn loads_from_telegraf_rates_and_last_values() {
        let l = parse(ANSWER, "audiobookshelf", &dl()).unwrap();
        assert_eq!(
            l.audiobookshelf,
            Some(Load { cpu_pct: Some(2.1), mem_bytes: Some(46_481_408 - 4_751_360), up_kbps: Some(1_293), down_kbps: None }),
            "usage_total 84 ms/s on 4 CPUs = 2.1 %; memory without inactive_file; tx 161.6 kB/s = 1293 kbit/s"
        );
        assert_eq!(
            l.downloads,
            Some(Load { cpu_pct: Some(33.4), mem_bytes: Some(39_747_584 - 3_948_544 + 74_825_728 - 24_248_320 + 63_029_248 - 1_769_472), up_kbps: None, down_kbps: Some(54_000) }),
            "CPU and memory summed over the three; download = what the VPN container receives (6.75 MB/s)"
        );
    }

    #[test]
    fn fastpi_host_from_telegraf_system_inputs() {
        let l = parse(ANSWER, "audiobookshelf", &dl()).unwrap();
        assert_eq!(
            l.host,
            Some(Host {
                cpu_pct: Some(71.0),
                cores_pct: vec![59.0, 90.1, 80.3, 54.2],
                mem_used_bytes: Some(8_453_947_392 - 2_225_078_272),
                mem_total_bytes: Some(8_453_947_392),
                swap_used_bytes: Some(4_642_357_248),
                swap_total_bytes: Some(10_737_401_856),
                disks: vec![
                    Disk { disk: "nvme".into(), used_bytes: 252_914_872_320, total_bytes: 252_914_872_320 + 225_066_844_160 },
                    Disk { disk: "seagate-red".into(), used_bytes: 273_804_165_120, total_bytes: 273_804_165_120 + 1_696_741_621_760 },
                    Disk { disk: "seagate-black".into(), used_bytes: 408_021_393_408, total_bytes: 408_021_393_408 + 1_562_524_393_472 },
                ],
            }),
            "busy = 100 - usage_idle, cores in cpu order; RAM used = total - available; disk total = used + free (as df); the root and the two HDDs in that order, /boot left out"
        );
        let l = parse(",result,table,_value,_field,container_name\r\n,,0,46481408,usage,audiobookshelf\r\n", "audiobookshelf", &dl()).unwrap();
        assert_eq!(l.host, None, "no host rows: no host block");
    }

    #[test]
    fn missing_samples_leave_figures_out() {
        let l = parse(",result,table,_value,_field,container_name\r\n,,0,46481408,usage,audiobookshelf\r\n", "audiobookshelf", &dl()).unwrap();
        assert_eq!(l.audiobookshelf, Some(Load { mem_bytes: Some(46_481_408), ..Load::default() }), "no n_cpus: no CPU share");
        assert_eq!(l.downloads, None);
        let l = parse(",result,table,_value,_field,container_name,_measurement,cpu,path\r\n,,0,9,used,,disk,,/rootfs\r\n,,0,5,used,,disk,,/rootfs/mnt/seagate-red\r\n,,0,5,free,,disk,,/rootfs/mnt/seagate-red\r\n", "audiobookshelf", &dl()).unwrap();
        assert_eq!(l.host.map(|h| h.disks), Some(vec![Disk { disk: "seagate-red".into(), used_bytes: 5, total_bytes: 10 }]), "a disk without free is left out, the others stay");
        assert_eq!(parse("\r\n", "audiobookshelf", &dl()).map_err(|_| ()), Err(()));
        assert!(parse("{\"code\":\"unauthorized\"}", "audiobookshelf", &dl()).is_err());
    }

    #[test]
    fn names_are_checked_before_they_go_into_the_query() {
        let b = BaseUrl::parse("http://influxdb:8086").unwrap();
        assert!(Influx::new(b.clone(), "/k".into(), "myorg", "rpi", "audiobookshelf", "gluetun_mouse sabnzbd").is_some());
        assert!(Influx::new(b.clone(), "/k".into(), "myorg", "rpi", "abs\"]) |> drop", "x").is_none());
        assert!(Influx::new(b.clone(), "/k".into(), "myorg", "rpi", "abs", "").is_none());
        let q = Influx::new(b, "/k".into(), "myorg", "rpi", "audiobookshelf", "gluetun_mouse sabnzbd").unwrap().query();
        assert!(q.starts_with(r#"c = (r) => r.container_name == "audiobookshelf" or r.container_name == "gluetun_mouse" or r.container_name == "sabnzbd""#), "{q}");
        assert!(!q.contains("contains("), "no filter InfluxDB cannot push down");
        for part in [r#"r._measurement == "cpu" and r._field == "usage_idle""#, r#"r._measurement == "swap""#, r#"r.path == "/rootfs" or r.path == "/rootfs/mnt/seagate-red" or r.path == "/rootfs/mnt/seagate-black""#, r#"keep(columns: ["_value", "_field", "container_name", "_measurement", "cpu", "path"])"#] {
            assert!(q.contains(part), "{part} in {q}");
        }
    }
}
