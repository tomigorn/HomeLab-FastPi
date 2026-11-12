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
  if (opts.clock !== false) await page.clock.install({ time: new Date(NOW * 1000) });
  const calls = { n: 0 };
  await page.route("**/api/state", (r) => {
    const a = answers[Math.min(calls.n, answers.length - 1)];
    calls.n++;
    if (typeof a === "number") return r.fulfill({ status: a, body: "no" });
    return r.fulfill({ contentType: "application/json", body: JSON.stringify(a) });
  });
  await page.route("http://activity.test/", (r) => r.fulfill({ contentType: "text/html", body: PAGE }));
  await page.goto("http://activity.test/");
  await page.waitForFunction(() => !document.getElementById("watching").textContent.includes("loading"));
  const text = async (sel) => (await page.locator(sel).innerText()).replace(/\s+/g, " ").trim();
  return { page, calls, text, errors, ctx };
}

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
