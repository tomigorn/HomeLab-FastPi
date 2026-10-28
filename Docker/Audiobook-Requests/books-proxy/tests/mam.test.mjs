import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { load, NAVBAR, tick } from "./fixture.mjs";

const MAMIX = { name: "MyAnonamouse", limited: false, window: "rolling", level: "ok",
  searches: { used: 4, limit: null, level: "ok" }, downloads: { used: 2, limit: null, level: "ok" } };
// As scripts/abr_bar_usage.py writes it.
const TEXTS = {
  label: { en: "MAM unsatisfied", de: "MAM unerfüllt" },
  head: { en: "MyAnonamouse seeding", de: "MyAnonamouse seeden" },
  risksHead: { en: "Rule risk: stopped before 72 h", de: "Regelrisiko: vor 72 h gestoppt" },
  reasons: { paused: { en: "paused in qBittorrent, resume it", de: "in qBittorrent pausiert, wieder starten" },
    removed: { en: "removed from qBittorrent", de: "aus qBittorrent entfernt" }, missed: { en: "30 days passed without 72 h", de: "30 Tage ohne 72 h vorbei" } },
  rule: { en: "MAM rule: seed every download 72 h in total within 30 days.", de: "MAM-Regel: jeden Download innerhalb von 30 Tagen insgesamt 72 h seeden." },
};
function mam(extra = {}) {
  const freesAt = new Date(Date.now() + 2 * 3600e3).toISOString();
  return { ok: true, unsatisfied: 12, limit: 150, class: "VIP", level: "ok", freesAt, seedHours: 72, windowDays: 30, risks: [], ...TEXTS,
    hint: { en: "Unsatisfied MAM torrents: 12 of 150 (VIP) — each must seed 72 h within 30 days; oldest frees at {freesAt}.",
      de: "Unerfüllte MAM-Torrents: 12 von 150 (VIP) — jeder muss innerhalb von 30 Tagen 72 h seeden; der nächste ist frei um {freesAt}." }, ...extra };
}
function usage(m = mam()) {
  const d = { ok: true, generated: new Date().toISOString(), showUnlimited: true, indexers: [MAMIX], subscriptions: [], storage: [] };
  if (m) d.mam = m;
  return d;
}

const open = [];
afterEach(() => { while (open.length) open.pop().close(); });

async function page({ data = usage(), status = 200, lang } = {}) {
  const w = load("bar/bar.js", NAVBAR, (win) => {
    win.fetch = (u) => /my-quota/.test(u) ? Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve(null) })
      : Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(data) });
    if (lang) Object.defineProperty(win.navigator, "language", { value: lang });
  });
  open.push(w);
  w.eval(readFileSync(new URL("../www/mam.js", import.meta.url), "utf8"));
  for (let i = 0; i < 8; i++) await tick();
  return w;
}
const $ = (w, s) => w.document.querySelector(s);
const chip = (w) => $(w, "#indexer-bar .ib-chips [data-ib-mam]");

test("MAM unsatisfied chip right after the MyAnonamouse chip", async () => {
  const w = await page();
  assert.match(chip(w).textContent, /^MAM unsatisfied\s*12\/150$/);
  assert.equal(chip(w).previousElementSibling.dataset.ibIndexer, "MyAnonamouse");
  assert.equal(chip(w).querySelector(".ib-fill").style.width, "8%");
  assert.ok(chip(w).querySelector(".ib-meter.ib-ok"));
  assert.match(chip(w).title, /^Unsatisfied MAM torrents: 12 of 150 \(VIP\) — each must seed 72 h within 30 days; oldest frees at \d\d:\d\d\.$/);
});

test("colour follows the collector's level, the bar dot too", async () => {
  let w = await page({ data: usage(mam({ unsatisfied: 120, level: "yellow" })) });
  assert.ok(chip(w).querySelector(".ib-meter.ib-yellow"));
  assert.ok($(w, "#indexer-bar .ib-title .ib-dot.ib-yellow"));
  w = await page({ data: usage(mam({ unsatisfied: 140, level: "full" })) });
  assert.ok(chip(w).querySelector(".ib-full-text"));
  assert.ok($(w, "#indexer-bar .ib-title .ib-dot.ib-full"));
});

test("risk: red count in the chip, names and reasons under more", async () => {
  const w = await page({ data: usage(mam({ level: "full", risks: [{ name: "Some Book", reason: "paused", seededHours: 5 }, { name: "Gone Book", reason: "removed", seededHours: 1 }] })) });
  assert.match(chip(w).textContent, /2 at risk$/);
  $(w, "#indexer-bar .ib-more").click();
  for (let i = 0; i < 3; i++) await tick();
  const sec = $(w, "#indexer-bar .ib-panel [data-ib-mam-panel]");
  assert.match(sec.textContent, /MyAnonamouse seeding/);
  assert.match(sec.textContent, /MAM rule: seed every download 72 h/);
  assert.match(sec.textContent, /Rule risk: stopped before 72 h/);
  assert.match(sec.textContent, /Some Book\s*paused in qBittorrent, resume it · 5 h/);
  assert.match(sec.textContent, /Gone Book\s*removed from qBittorrent · 1 h/);
  assert.equal(w.document.querySelectorAll("[data-ib-mam]").length, 1);
});

test("stays once after the bar re-renders", async () => {
  const w = await page();
  $(w, "#indexer-bar .ib-more").click();
  for (let i = 0; i < 3; i++) await tick();
  $(w, "#indexer-bar .ib-more").click();
  for (let i = 0; i < 3; i++) await tick();
  assert.equal(w.document.querySelectorAll("[data-ib-mam]").length, 1);
  assert.equal($(w, "[data-ib-mam-panel]"), null);
});

test("qBittorrent unavailable: muted chip", async () => {
  const w = await page({ data: usage({ ok: false, label: TEXTS.label }) });
  assert.match(chip(w).textContent, /^MAM unsatisfied\s*unavailable$/);
  assert.ok(chip(w).classList.contains("ib-muted"));
});

test("no mam data or no session: no chip", async () => {
  let w = await page({ data: usage(null) });
  assert.ok($(w, "#indexer-bar"));
  assert.equal(chip(w), null);
  w = await page({ status: 401 });
  assert.equal($(w, "[data-ib-mam]"), null);
});

test("German browser: German texts", async () => {
  const w = await page({ lang: "de-CH", data: usage(mam({ risks: [{ name: "Some Book", reason: "paused", seededHours: 5 }], level: "full" })) });
  assert.match(chip(w).textContent, /^MAM unerfüllt\s*12\/150\s*1 Risiko$/);
  assert.match(chip(w).title, /^Unerfüllte MAM-Torrents: 12 von 150/);
});
