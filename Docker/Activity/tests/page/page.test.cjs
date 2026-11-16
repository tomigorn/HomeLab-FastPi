// Page tests: www/index.html in headless Chromium with /api/state answered from fixtures (no service, no network).
//   node --test tests/page/page.test.cjs          the page in www/
//   PAGE=/path/to/index.html node --test ...      another copy (e.g. the last commit's, to see a test fail)
// Playwright: PLAYWRIGHT=<module dir>, else the global one, else the copy in ~/Documents/development/LoyaltyCards.
"use strict";
const { test, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

function playwright() {
  for (const p of [process.env.PLAYWRIGHT, "playwright", path.join(os.homedir(), "Documents/development/LoyaltyCards/node_modules/playwright")]) {
    if (!p) continue;
    try { return require(p); } catch { /* next */ }
  }
  throw new Error("playwright not found (set PLAYWRIGHT)");
}
const { chromium } = playwright();
const PAGE = fs.readFileSync(process.env.PAGE || path.join(__dirname, "../../www/index.html"), "utf8");
// The policy the service sends (rust/src/csp.rs): the inline script and style by hash, nothing else inline.
const hash = (tag) => [...PAGE.matchAll(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "g"))].map((m) => `'sha256-${require("node:crypto").createHash("sha256").update(m[1]).digest("base64")}'`).join(" ");
const CSP = `default-src 'none'; script-src ${hash("script")}; style-src ${hash("style")}; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`;
// Zurich, Thu 12 Nov 2026 14:00 (UTC+1)
const NOW = Date.UTC(2026, 10, 12, 13, 0, 0) / 1000;

let browser;
after(async () => browser && browser.close());

function base(over) {
  return Object.assign({
    now: NOW, beefy: "up", beefy_data: "live", watching: [], downloads: [], downloads_as_of: null,
    listening: { sessions: 0 }, audiobook_downloads: { downloading: 0, queued: 0 }, polled_at: NOW,
    streams_failed: false, downloads_failed: false, beefy_starting: false,
  }, over);
}

// Opens the page; `answers` are served in order (the last one repeats; a string = that HTTP status). Returns { page, calls, text }.
async function open(answers, opts = {}) {
  browser = browser || await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: "Europe/Zurich", locale: "en-GB" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (/Content.Security.Policy/i.test(m.text())) errors.push(m.text()); });
  if (opts.clock !== false) await page.clock.install({ time: new Date(NOW * 1000) });
  const calls = { n: 0 };
  await page.route("**/api/state", (r) => {
    const a = answers[Math.min(calls.n, answers.length - 1)];
    calls.n++;
    if (typeof a === "number") return r.fulfill({ status: a, body: "no" });
    return r.fulfill({ contentType: "application/json", body: JSON.stringify(a) });
  });
  calls.pages = 0;
  await page.route("http://activity.test/favicon.svg", (r) => r.fulfill({ contentType: "image/svg+xml", body: fs.readFileSync(path.join(__dirname, "../../www/icons/favicon.svg")) }));
  await page.route("http://activity.test/", (r) => (calls.pages++, r.fulfill({ contentType: "text/html", headers: { "content-security-policy": CSP }, body: PAGE })));
  await page.goto("http://activity.test/");
  await page.waitForFunction(() => !document.getElementById("watching").textContent.includes("loading"));
  const text = async (sel) => (await page.locator(sel).innerText()).replace(/\s+/g, " ").trim();
  return { page, calls, text, errors, ctx };
}

test("the page runs under the hashed CSP without violations", async () => {
  const p = await open([base({ watching: [{ kind: "Movie", quality: "4K HDR", mode: "direct play", paused: false, n: 1 }] })]);
  assert.match(await p.text("#watching"), /Movie/);
  assert.deepEqual(p.errors, []);
  await p.ctx.close();
});

test("as of shows the time today and the day before that", async () => {
  let p = await open([base({ beefy: "asleep", beefy_data: "stale", downloads: [{ state: "downloading", kind: "Movie", quality: null, items: 1, seasons: 0, episodes: 0 }], downloads_as_of: NOW - 2 * 3600 })]);
  assert.match(await p.text("#downloads"), /as of 12:00 /);
  await p.ctx.close();
  p = await open([base({ beefy: "asleep", beefy_data: "stale", downloads: [], downloads_as_of: Date.UTC(2026, 10, 11, 21, 40) / 1000 })]);
  assert.match(await p.text("#downloads"), /as of yesterday 22:40/);
  await p.ctx.close();
  p = await open([base({ beefy: "asleep", beefy_data: "stale", downloads: [], downloads_as_of: Date.UTC(2026, 10, 9, 21, 40) / 1000 })]);
  assert.match(await p.text("#downloads"), /as of Mon,? 9 Nov 22:40/);
  await p.ctx.close();
});

test("the gate banner names the part that failed", async () => {
  const p = await open([base({ downloads_failed: true })]);
  assert.equal(await p.page.locator("#gate").isVisible(), true);
  assert.match(await p.text("#gate"), /beefy downloads unavailable/);
  await p.ctx.close();
});

test("waking and broken are not asleep", async () => {
  let p = await open([base({ beefy: "waking", beefy_data: "none", watching: [] })]);
  assert.match(await p.text("#watching"), /waking up/);
  assert.match(await p.text("#beefy"), /waking/);
  await p.ctx.close();
  p = await open([base({ beefy: "broken", beefy_data: "none", watching: null })]);
  assert.match(await p.text("#watching"), /did not wake/);
  await p.ctx.close();
});

test("an awake beefy without live data is asked again after 5 s, not 30 s", async () => {
  const p = await open([base({ beefy_data: "none", watching: null, beefy_starting: true }), base()]);
  assert.equal(p.calls.n, 1);
  assert.match(await p.text("#watching"), /starting/);
  await p.page.clock.runFor(5500);
  await p.page.waitForFunction(() => document.getElementById("watching").textContent.includes("nobody watching"));
  assert.equal(p.calls.n, 2);
  await p.page.clock.runFor(20000);
  assert.equal(p.calls.n, 2, "live: back to every 30 s");
  await p.ctx.close();
});

test("queued, stalled and paused queue items and audiobook problems get their own rows", async () => {
  const d = (state) => ({ state, kind: "Movie", quality: null, items: 1, seasons: 0, episodes: 0 });
  const p = await open([base({ downloads: [d("queued"), d("stalled"), d("paused")], audiobook_downloads: { downloading: 0, queued: 0, paused: 1, problem: 2 } })]);
  const t = await p.text("#downloads");
  for (const want of [/queued/, /stalled/, /paused/, /Audiobook\s*problem/]) assert.match(t, want);
  assert.equal(await p.page.locator("#downloads tr").count(), 5);
  await p.ctx.close();
});

test("gaps in the downloads are named", async () => {
  const p = await open([base({ downloads: [], downloads_gaps: { series_unavailable: true, night_unavailable: true, truncated: true }, streams_series_unavailable: true })]);
  const t = await p.text("#downloads");
  assert.match(t, /more in the queue than shown/);
  assert.match(t, /series list unavailable/);
  assert.match(t, /night list unavailable/);
  await p.ctx.close();
});

const W = (kind, mode, paused, n) => ({ kind, quality: null, mode, paused, n });
const D = (state, kind, items, extra) => Object.assign({ state, kind, quality: null, items, seasons: 0, episodes: 0 }, extra);

test("the headline sums up who is on and what moves", async () => {
  let p = await open([base({
    watching: [W("Movie", "direct play", false, 1), W("Episode", "transcode", false, 1), W("Anime", "direct play", true, 1), W("Music", "direct play", false, 1)],
    listening: { sessions: 1 },
    downloads: [D("downloading", "Movie", 2), D("downloading", "Episode", 1), D("waiting for night", "Movie", 4)],
    audiobook_downloads: { downloading: 1, queued: 0, paused: 0, problem: 0 },
  })]);
  assert.equal(await p.text("#headline"), "2 watching (1 transcoding) · 1 paused · 2 listening · 4 downloading");
  assert.equal(await p.text("#listening-n"), "2", "the Listening card counts what the headline counts");
  await p.ctx.close();
  p = await open([base({ beefy: "asleep", beefy_data: "stale", downloads: [D("waiting for release", "Movie", 3)], downloads_as_of: NOW - 60 })]);
  assert.equal(await p.text("#headline"), "All quiet");
  await p.ctx.close();
  p = await open([base({ beefy: "unknown", beefy_data: "none", watching: null, listening: { sessions: 1 } })]);
  assert.equal(await p.text("#headline"), "watching unknown · 1 listening");
  await p.ctx.close();
});

test("waiting for night says when the window opens", async () => {
  let p = await open([base({ downloads: [D("waiting for night", "Movie", 2)], night_open: false })]);
  assert.match(await p.text("#downloads"), /waiting for night · from 22:05/);
  await p.ctx.close();
  p = await open([base({ downloads: [D("waiting for night", "Movie", 2)], night_open: true })]);
  assert.match(await p.text("#downloads"), /night window open/);
  await p.ctx.close();
});

test("waiting for release is one folded line, not rows", async () => {
  const p = await open([base({ downloads: [D("downloading", "Movie", 1), D("waiting for release", "Movie", 6), D("waiting for release", "Episode", 3), D("waiting for release", "Anime", 1)] })]);
  assert.equal(await p.page.locator("#downloads > table tr").count(), 1);
  const fold = p.page.locator("#downloads details");
  assert.equal((await fold.locator("summary").innerText()).replace(/\s+/g, " ").trim(), "📅 waiting for release: 6 movies, 3 series, 1 anime");
  assert.equal(await fold.locator("tr").first().isVisible(), false, "collapsed");
  await fold.locator("summary").click();
  assert.equal(await fold.locator("tr").count(), 3);
  await p.ctx.close();
});

test("a failed refresh greys the page and says how to recover", async () => {
  const p = await open([base({ watching: [W("Movie", "direct play", false, 1)] }), 302]);
  assert.equal(await p.page.locator("main.stale").count(), 0);
  await p.page.clock.runFor(30500);
  await p.page.waitForSelector("main.stale");
  const t = await p.text("#stale");
  assert.match(t, /not updated since 14:00/);
  assert.match(t, /reload/);
  assert.equal(await p.page.locator("#stale a").getAttribute("href"), "./");
  await p.ctx.close();
});

test("a failed refresh is tried again after 5 s and the page recovers", async () => {
  const p = await open([base(), 302, base()]);
  await p.page.clock.runFor(30500);
  await p.page.waitForSelector("main.stale");
  assert.equal(p.calls.n, 2);
  await p.page.clock.runFor(5500);
  await p.page.waitForTimeout(300);
  assert.equal(p.calls.n, 3, "tried again after 5 s");
  assert.equal(await p.page.locator("main.stale").count(), 0);
  assert.equal(p.calls.pages, 1, "no reload needed");
  await p.ctx.close();
});

test("a second failure reloads the page to renew the sign-in, at most once per 2 min", async () => {
  const p = await open([base(), 302]);
  await p.page.clock.runFor(30500);
  await p.page.clock.runFor(5500);
  await p.page.waitForFunction(() => document.readyState === "complete" && document.getElementById("watching"));
  await p.page.waitForTimeout(300);
  assert.equal(p.calls.pages, 2, "reloaded once");
  await p.page.clock.runFor(45000);
  await p.page.waitForTimeout(300);
  assert.equal(p.calls.pages, 2, "no reload loop");
  await p.ctx.close();
});

test("a hidden tab never reloads itself", async () => {
  const p = await open([base(), 302]);
  await p.page.clock.runFor(30500);
  await p.page.waitForSelector("main.stale");
  await p.page.evaluate(() => { Object.defineProperty(document, "hidden", { value: true, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await p.page.clock.runFor(60000);
  assert.equal(p.calls.pages, 1);
  await p.ctx.close();
});

test("Watching and Downloads use the same kind labels", async () => {
  const p = await open([base({
    watching: [W("Episode", "direct play", false, 1), W("Live TV", "direct stream", false, 1), W("Audiobook", "direct play", false, 1)],
    downloads: [D("downloading", "Episode", 1, { seasons: 1, episodes: 2 })],
  })]);
  const w = await p.text("#watching");
  assert.match(w, /Series/);
  assert.doesNotMatch(w, /Episode/);
  assert.match(w, /Live TV/);
  assert.match(await p.text("#listening"), /Audiobook/, "Jellyfin audiobooks are listed under Listening");
  assert.match(await p.text("#downloads"), /Series/);
  assert.doesNotMatch(await p.text("#downloads"), /Anime series|1 title/);
  await p.ctx.close();
});

test("a transcode says why and on which encoder", async () => {
  const p = await open([base({ watching: [Object.assign(W("Movie", "transcode", false, 1), { accel: "QSV", reasons: ["subtitles", "HDR tone-mapping"] }), Object.assign(W("Episode", "transcode", false, 1), { accel: "software", reasons: [] })] })]);
  const t = await p.text("#watching");
  assert.match(t, /transcode · configured encoder: QSV · subtitles, HDR tone-mapping/, "HardwareAccelerationType is the server setting, not this transcode");
  assert.match(t, /transcode · configured encoder: software/);
  await p.ctx.close();
});

test("bitrate, LAN or remote and people under Watching", async () => {
  let p = await open([base({ watching: [W("Movie", "direct play", false, 7)], watching_summary: { bitrate_kbps: 142960, lan: 4, remote: 3, people: 4 } })]);
  assert.match(await p.text("#watching"), /≈ 143 Mbit\/s · 4 LAN, 3 remote · 4 people on 7 streams/);
  await p.ctx.close();
  p = await open([base({ watching: [W("Movie", "direct play", false, 1)], watching_summary: { bitrate_kbps: null, lan: 0, remote: 1, people: 1 } })]);
  assert.match(await p.text("#watching"), /1 remote · 1 person on 1 stream/);
  assert.doesNotMatch(await p.text("#watching"), /Mbit/);
  await p.ctx.close();
});

test("download rows show the longest time and the size left", async () => {
  const p = await open([base({
    downloads: [D("downloading", "Movie", 1, { eta: 4205, left: 8000000000 }), D("problem", "Movie", 1, { eta: 60, left: 1000 }), D("stalled", "Movie", 1, { eta: null, left: 2000000000 })],
    audiobook_downloads: { downloading: 5, queued: 0, paused: 0, problem: 0, eta: 600, left: 170000000 },
  })]);
  const rows = await p.page.locator("#downloads tr").allInnerTexts();
  const row = (re) => rows.map((r) => r.replace(/\s+/g, " ")).find((r) => re.test(r)) || "";
  assert.match(row(/Movie downloading/), /~1 h 10 min left · 8\.0 GB to download/);
  assert.match(row(/stalled/), /2\.0 GB to download/);
  assert.doesNotMatch(row(/problem/), /left|to download/);
  assert.match(row(/Audiobook downloading/), /~10 min left · 170 MB to download/);
  await p.ctx.close();
});

test("Jellyfin music and audiobooks sit under Listening, not Watching", async () => {
  const p = await open([base({ watching: [W("Movie", "direct play", false, 1), W("Music", "direct play", false, 1)], listening: { sessions: 1 } })]);
  assert.equal(await p.text("#watching-n"), "1");
  assert.doesNotMatch(await p.text("#watching"), /Music/);
  assert.equal(await p.text("#listening-n"), "2");
  const l = await p.text("#listening");
  assert.match(l, /1 in Audiobookshelf/);
  assert.match(l, /Music/);
  assert.equal(await p.text("#headline"), "1 watching · 2 listening");
  await p.ctx.close();
});

test("audio-only transcodes are not counted as transcoding", async () => {
  const p = await open([base({ watching: [W("Movie", "transcode", false, 1), W("Episode", "transcode (audio)", false, 1)] })]);
  assert.equal(await p.text("#headline"), "2 watching (1 transcoding, 1 audio-only)");
  await p.ctx.close();
});

test("old downloads do not claim an open night window or a time left", async () => {
  const p = await open([base({ beefy: "asleep", beefy_data: "stale", night_open: true, downloads_as_of: NOW - 15 * 3600,
    downloads: [D("waiting for night", "Movie", 1), D("downloading", "Movie", 1, { eta: 600, left: 5e9 })] })]);
  const t = await p.text("#downloads");
  assert.match(t, /waiting for night/);
  assert.doesNotMatch(t, /night window open|from 22:05|left|to download/);
  await p.ctx.close();
});

test("a hidden tab cancels the pending quick refresh", async () => {
  const p = await open([base({ beefy_data: "none", watching: null }), base()]);
  assert.equal(p.calls.n, 1);
  await p.page.evaluate(() => { Object.defineProperty(document, "hidden", { value: true, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await p.page.clock.runFor(40000);
  assert.equal(p.calls.n, 1);
  await p.ctx.close();
});

test("a low bitrate shows in kbit/s", async () => {
  const p = await open([base({ watching: [W("Movie", "direct play", false, 1)], watching_summary: { bitrate_kbps: 320, lan: 1, remote: 0, people: 1 } })]);
  assert.match(await p.text("#watching"), /≈ 320 kbit\/s/);
  await p.ctx.close();
});

const GiB = 1024 ** 3;
const LOAD = { updated: NOW - 20, cpu_pct: 23.1, jellyfin_cpu_pct: 18.0, gpu_pct: 41.0, mem_used_bytes: 9.2 * GiB, mem_total_bytes: 61.4 * GiB, jellyfin_mem_bytes: 1.04 * GiB, up_kbps: 27013 };

test("beefy's load is one compact row under Watching", async () => {
  let p = await open([base({ watching: [W("Movie", "direct play", false, 2)], watching_summary: { bitrate_kbps: 27218, lan: 0, remote: 2, people: 2 }, beefy_resources: LOAD })]);
  assert.equal(await p.text("#watching .load"), "CPU 23 % (Jellyfin 18 %) · GPU 41 % · RAM 9.2 / 61 GiB (Jellyfin 1.0 GiB) · ↑ 27 Mbit/s");
  assert.match(await p.page.locator("#watching .load").getAttribute("title"), /last minute/);
  assert.deepEqual(p.errors, []);
  await p.ctx.close();
  p = await open([base({ beefy_resources: { updated: NOW, cpu_pct: 3.04, jellyfin_cpu_pct: null, gpu_pct: null, mem_used_bytes: null, mem_total_bytes: null, jellyfin_mem_bytes: null, up_kbps: 640 } })]);
  assert.equal(await p.text("#watching .load"), "CPU 3 % · ↑ 640 kbit/s", "unknown figures are left out, also with nobody watching");
  await p.ctx.close();
});

test("no load row while beefy sleeps or has no figures", async () => {
  let p = await open([base({ beefy: "asleep", beefy_data: "stale", beefy_resources: null })]);
  assert.match(await p.text("#watching"), /beefy asleep/);
  assert.equal(await p.page.locator("#watching .load").count(), 0);
  await p.ctx.close();
  p = await open([base({ watching: [W("Movie", "direct play", false, 1)] })]);
  assert.equal(await p.page.locator("#watching .load").count(), 0);
  await p.ctx.close();
});

test("beefy's GPU and Jellyfin CPU name what measured ffmpeg runs account for", async () => {
  let p = await open([base({ beefy_resources: { ...LOAD, cpu_pct: 13, jellyfin_cpu_pct: 5, gpu_pct: 24, streams_cpu_pct: 0.4, streams_gpu_pct: 0, background: [{ task: "preview images", cpu_pct: 4.2, gpu_pct: 22.3 }] } })]);
  assert.equal(await p.text("#watching .load"), "CPU 13 % (Jellyfin 5 %: streams 0.4 %, background: preview images 4.2 %) · GPU 24 % (background: preview images 22 %) · RAM 9.2 / 61 GiB (Jellyfin 1.0 GiB) · ↑ 27 Mbit/s");
  await p.ctx.close();
  p = await open([base({ beefy_resources: { ...LOAD, jellyfin_cpu_pct: 5, gpu_pct: 24, streams_cpu_pct: 0, streams_gpu_pct: 0, background: [] } })]);
  assert.match(await p.text("#watching .load"), /GPU 24 % \(not Jellyfin's ffmpeg\)/, "measured, nothing of Jellyfin's ffmpeg on the GPU");
  await p.ctx.close();
});

const SL = (kind, quality, mode, paused, cpu, gpu, kbps) => ({ kind, quality, mode, paused, cpu_pct: cpu, gpu_pct: gpu, kbps });

test("one line per stream under Watching, with only what was measured", async () => {
  const p = await open([base({
    watching: [W("Movie", "direct play", false, 1), W("Movie", "transcode", false, 1)], beefy_resources: LOAD,
    stream_loads: [SL("Movie", "4K HDR", "direct play", false, null, null, 18000), SL("Movie", "1080p SDR", "transcode", false, 34.2, 41, 8000),
      SL("Episode", "1080p HDR", "direct stream", false, 0.31, null, 12000), SL("Movie", "4K HDR", "direct play", true, null, null, null),
      SL("Music", null, "direct play", false, null, null, 320)],
  })]);
  const lines = await p.page.locator("#watching ul.each li").allInnerTexts();
  assert.deepEqual(lines.map((l) => l.replace(/\s+/g, " ")), [
    "Stream 1 · 4K HDR direct play · ≈ ↑ 18 Mbit/s",
    "Stream 2 · 1080p SDR transcode · CPU 34 % · GPU 41 % · ≈ ↑ 8 Mbit/s",
    "Stream 3 · 1080p HDR direct stream · CPU 0.3 % · ≈ ↑ 12 Mbit/s",
    "Stream 4 · 4K HDR direct play · paused",
  ], "direct play has no ffmpeg: no CPU; music goes to Listening");
  assert.match(await p.text("#listening"), /Listener 1 · Music · direct play · ≈ ↑ 320 kbit\/s/);
  assert.deepEqual(p.errors, []);
  await p.ctx.close();
});

test("Listening shows Audiobookshelf's load and one line per listener", async () => {
  const p = await open([base({
    listening: { sessions: 2, modes: ["direct play", "transcode"] },
    fastpi_load: { audiobookshelf: { cpu_pct: 0.42, mem_bytes: 45 * 1024 ** 2, up_kbps: 96, down_kbps: null }, downloads: null },
  })]);
  assert.equal(await p.text("#listening .load"), "Audiobookshelf · CPU 0.4 % · RAM 45 MiB · ↑ 96 kbit/s");
  assert.deepEqual(await p.page.locator("#listening ul.each li").allInnerTexts(), ["Listener 1 · direct play", "Listener 2 · transcode"]);
  await p.ctx.close();
});

const DL_LOAD = { ...LOAD, dl_cpu_pct: 22.04, dl_mem_bytes: 1.1 * GiB, dl_down_kbps: 432000, disk_write_kbps: 960000, sab_post: "unpacking" };
const DL = (state) => ({ state, kind: "Movie", quality: null, items: 1, seasons: 0, episodes: 0, eta: null, left: null });

test("download load lines lead the Downloads card only while something downloads", async () => {
  let p = await open([base({
    beefy_resources: DL_LOAD, downloads: [DL("downloading")],
    audiobook_downloads: { downloading: 1, queued: 0, paused: 0, problem: 0, eta: 60, left: 5e6 },
    fastpi_load: { audiobookshelf: null, downloads: { cpu_pct: 33.4, mem_bytes: 147 * 1024 ** 2, up_kbps: null, down_kbps: 54000 } },
  })]);
  const loads = await p.page.locator("#downloads .load").allInnerTexts();
  assert.deepEqual(loads.map((l) => l.replace(/\s+/g, " ")), [
    "beefy · ↓ 54 MB/s · SAB unpacking · CPU 22 % · RAM 1.1 GiB · disk write 120 MB/s",
    "fastpi audiobooks · ↓ 6.8 MB/s · CPU 33 % · RAM 147 MiB",
  ]);
  assert.equal(await p.page.locator("#downloads > :first-child").getAttribute("class"), "note load", "totals first");
  await p.ctx.close();
  p = await open([base({
    beefy_resources: { ...DL_LOAD, dl_down_kbps: 300, sab_post: null }, downloads: [DL("paused"), DL("waiting for night")],
    fastpi_load: { audiobookshelf: null, downloads: { cpu_pct: 1, mem_bytes: 1, up_kbps: null, down_kbps: 40 } },
  })]);
  assert.equal(await p.page.locator("#downloads .load").count(), 0, "nothing downloading: no load lines");
  await p.ctx.close();
  p = await open([base({ beefy_resources: { ...DL_LOAD, dl_down_kbps: 0 }, downloads: [DL("importing")] })]);
  assert.equal(await p.text("#downloads .load"), "beefy · ↓ 0.0 MB/s · SAB unpacking · CPU 22 % · RAM 1.1 GiB · disk write 120 MB/s", "importing: the unpack shows");
  await p.ctx.close();
});

test("the favicons are linked and load under the CSP", async () => {
  const p = await open([base()]);
  const links = await p.page.evaluate(() => [...document.querySelectorAll("link[rel~=icon], link[rel=apple-touch-icon]")].map((l) => l.rel + " " + l.getAttribute("href") + " " + (l.getAttribute("sizes") || l.type || "")));
  assert.deepEqual(links, ["icon favicon.svg image/svg+xml", "icon icons/favicon-32x32.png 32x32", "icon icons/favicon-16x16.png 16x16", "apple-touch-icon icons/apple-touch-icon.png "]);
  const loaded = await p.page.evaluate(() => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i.naturalWidth > 0); i.onerror = () => ok(false); i.src = "favicon.svg"; }));
  assert.equal(loaded, true, "img-src 'self'");
  assert.deepEqual(p.errors, []);
  await p.ctx.close();
});
