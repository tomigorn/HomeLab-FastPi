import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { load, NAVBAR, tick } from "./fixture.mjs";

const TB = 1024 ** 4, GB = 1024 ** 3;
// Texts as scripts/abr_bar_usage.py writes them.
const LIB = { name: "Library", id: "library", total: 1.8 * TB, used: 377 * GB, free: 1.4 * TB, pct: 21.9, level: "ok", yellow: 70, red: 80,
  label: { en: "Library", de: "Bibliothek" }, sub: { en: "books in Audiobookshelf", de: "Bücher in Audiobookshelf" },
  hint: { en: "Audiobookshelf library. From 70 % plan more space, from 80 % new books may soon not fit. Nothing is deleted automatically.",
    de: "Audiobookshelf-Bibliothek. Ab 70 % mehr Platz einplanen, ab 80 % passen neue Bücher bald nicht mehr. Es wird nichts automatisch gelöscht." } };
const DL = { name: "Downloads", id: "downloads", total: 1.8 * TB, used: 253 * GB, free: 1.6 * TB, pct: 14.4, level: "ok", yellow: 70, red: 80,
  label: { en: "Downloads", de: "Downloads" }, sub: { en: "torrents (seeding) + Usenet", de: "Torrents (seeden) + Usenet" },
  hint: { en: "Torrents keep seeding (MyAnonamouse rules), so this only grows. From 80 % make room by hand; nothing is removed automatically.",
    de: "Torrents seeden weiter (MyAnonamouse-Regeln), daher wächst das nur. Ab 80 % von Hand Platz schaffen; es wird nichts automatisch entfernt." } };
const MAM = { name: "MyAnonamouse", limited: false, window: "rolling", level: "ok",
  searches: { used: 4, limit: null, level: "ok" }, downloads: { used: 2, limit: null, level: "ok" } };
const VPN = { name: "ProtonVPN Plus", kind: "VPN", lifetime: false, expires: "2027-06-15", daysLeft: 230, expired: false, level: "ok" };

function usage(extra = {}) {
  return { ok: true, generated: new Date().toISOString(), showUnlimited: true, note: { en: "Searches and downloads go through Prowlarr to MyAnonamouse.", de: "Suchen und Downloads laufen über Prowlarr." },
    indexers: [MAM], subscriptions: [VPN], storage: [LIB, DL], ...extra };
}
const QUOTA = { used: 2, limit: 5, days: 7, freesAt: null };

const open = [];
afterEach(() => { while (open.length) open.pop().close(); });

function respond(data, status = 200) {
  return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(data) });
}
async function bar({ data = usage(), quota = QUOTA, status = 200, url, lang, calls = [] } = {}) {
  const w = load("bar/bar.js", NAVBAR, (win) => {
    win.fetch = (u, opts) => {
      calls.push([u, opts]);
      if (/my-quota/.test(u)) return quota ? respond(quota) : respond(null, 400);
      return typeof status === "function" ? status(u) : status === "reject" ? Promise.reject(new TypeError("cors")) : respond(data, status);
    };
    if (lang) Object.defineProperty(win.navigator, "language", { value: lang });
  }, url);
  open.push(w);
  for (let i = 0; i < 6; i++) await tick();
  return w;
}
const $ = (w, s) => w.document.querySelector(s);
const disk = (w, id) => [...w.document.querySelectorAll("#indexer-bar .ib-chips [data-ib-disk]")].find((c) => c.dataset.ibDisk === id);

test("bar shows disk chips: used/total and percent", async () => {
  const w = await bar();
  assert.match(disk(w, "library").textContent, /^Library\s*377 GB\/1\.8 TB\s*22 %$/);
  assert.match(disk(w, "downloads").textContent, /^Downloads\s*253 GB\/1\.8 TB\s*14 %$/);
  assert.equal(disk(w, "library").querySelector(".ib-fill").style.width, "21.9%");
  assert.ok($(w, "html").classList.contains("ib-on"));
});

test("disk colour follows the collector's level", async () => {
  const w = await bar({ data: usage({ storage: [{ ...LIB, pct: 75, level: "yellow" }, { ...DL, pct: 85, level: "full" }] }) });
  assert.ok(disk(w, "library").querySelector(".ib-meter.ib-yellow"));
  assert.ok(disk(w, "downloads").querySelector(".ib-meter.ib-full"));
  assert.ok($(w, "#indexer-bar .ib-title .ib-dot.ib-full"));
});

test("disk hints in English", async () => {
  const w = await bar();
  assert.equal(disk(w, "library").title, "Library: 1.4 TB free. Audiobookshelf library. From 70 % plan more space, from 80 % new books may soon not fit. Nothing is deleted automatically.");
  assert.equal(disk(w, "downloads").title, "Downloads: 1.6 TB free. Torrents keep seeding (MyAnonamouse rules), so this only grows. From 80 % make room by hand; nothing is removed automatically.");
});

test("German browser: German disk names, hints and decimal comma", async () => {
  const w = await bar({ lang: "de-CH" });
  assert.match(disk(w, "library").textContent, /^Bibliothek\s*377 GB\/1,8 TB/);
  assert.equal(disk(w, "library").title, "Bibliothek: 1,4 TB frei. Audiobookshelf-Bibliothek. Ab 70 % mehr Platz einplanen, ab 80 % passen neue Bücher bald nicht mehr. Es wird nichts automatisch gelöscht.");
  assert.match(disk(w, "downloads").title, /^Downloads: 1,6 TB frei\. Torrents seeden weiter/);
});

test("one filesystem for both: one chip, both hints", async () => {
  const w = await bar({ data: usage({ storage: [{ ...LIB, name: "Library + Downloads", id: "library+downloads",
    label: { en: "Library + Downloads", de: "Bibliothek + Downloads" }, hint: { en: LIB.hint.en + " " + DL.hint.en, de: LIB.hint.de + " " + DL.hint.de } }] }) });
  const c = disk(w, "library+downloads");
  assert.match(c.textContent, /^Library \+ Downloads/);
  assert.match(c.title, /Audiobookshelf library\..*Torrents keep seeding/);
});

test("unlimited indexer: counts with ∞ in the bar", async () => {
  const w = await bar();
  const c = $(w, "#indexer-bar [data-ib-indexer='MyAnonamouse']");
  assert.match(c.textContent, /^MyAnonamouse\s*4\/∞ searches\s*2\/∞ downloads$/);
});

test("own request quota chip", async () => {
  const w = await bar();
  const c = $(w, "#indexer-bar [data-ib-quota]");
  assert.match(c.textContent, /^My requests\s*2\/5 in 7 days$/);
  assert.equal(c.title, "5 requests per person in 7 days, deleted requests count too.");
  assert.ok(c.querySelector(".ib-meter.ib-ok"));
});

test("quota used up: red with the time the next slot frees", async () => {
  const w = await bar({ quota: { used: 5, limit: 5, days: 7, freesAt: "2030-01-02T10:00:00Z" } });
  const c = $(w, "#indexer-bar [data-ib-quota]");
  assert.ok(c.querySelector(".ib-meter.ib-full"));
  assert.match(c.textContent, /next free /);
  assert.ok($(w, "#indexer-bar .ib-title .ib-dot.ib-full"));
});

test("quota unavailable: no quota chip, rest unchanged", async () => {
  const w = await bar({ quota: null });
  assert.equal($(w, "#indexer-bar [data-ib-quota]"), null);
  assert.ok(disk(w, "library"));
});

test("next renewal from the subscriptions", async () => {
  const w = await bar();
  assert.match($(w, "#indexer-bar .ib-chips").textContent, /Next renewal: ProtonVPN Plus in 230 d/);
});

test("panel lists indexers, subscriptions and storage", async () => {
  const w = await bar();
  $(w, "#indexer-bar .ib-more").click();
  const h4 = [...w.document.querySelectorAll("#indexer-bar .ib-panel h4")].map((h) => h.textContent);
  assert.deepEqual(h4, ["Unlimited (last 24 h)", "Subscriptions", "Storage", "My requests"]);
  assert.match($(w, "#indexer-bar .ib-panel").textContent, /1\.4 TB free/);
});

test("nothing shown before the data arrives", async () => {
  let release;
  const w = await bar({ status: () => new Promise((r) => { release = r; }) });
  assert.equal($(w, "#indexer-bar"), null);
  assert.ok(!$(w, "html").classList.contains("ib-on"));
  release({ ok: true, status: 200, json: () => Promise.resolve(usage()) });
  for (let i = 0; i < 4; i++) await tick();
  assert.ok($(w, "#indexer-bar"));
});

test("not logged in (401, redirect, network error): no bar at all", async () => {
  for (const status of [401, 0, "reject"]) {
    const w = await bar({ status });
    assert.equal($(w, "#indexer-bar"), null, String(status));
    assert.ok(!$(w, "html").classList.contains("ib-on"));
  }
});

test("fetch does not follow the login redirect and sends the session cookie", async () => {
  const calls = [];
  await bar({ calls });
  const [u, opts] = calls.find((c) => /usage/.test(c[0]));
  assert.equal(u, "/_hg/bar/usage.json");
  assert.equal(opts.redirect, "manual");
  assert.equal(opts.credentials, "same-origin");
});

test("login, OIDC and init pages: no bar even with data", async () => {
  for (const path of ["/login", "/login?backup=1", "/auth/oidc", "/init"]) {
    const w = await bar({ url: "https://books.example.com" + path });
    assert.equal($(w, "#indexer-bar"), null, path);
  }
  assert.ok($(await bar({ url: "https://books.example.com/authors" }), "#indexer-bar"));
});

test("no session: the quota is not even asked", async () => {
  const calls = [];
  await bar({ status: 401, calls });
  assert.deepEqual(calls.map((c) => c[0]), ["/_hg/bar/usage.json"]);
});

test("panel note from the data, German for German browsers", async () => {
  const w = await bar({ lang: "de-CH" });
  $(w, "#indexer-bar .ib-more").click();
  assert.match($(w, "#indexer-bar .ib-panel").textContent, /Suchen und Downloads laufen über Prowlarr\./);
  assert.match($(w, "#indexer-bar .ib-panel").textContent, /Bücher in Audiobookshelf/);
});

test("bar disappears when the session ends", async () => {
  let ok = true;
  const w = await bar({ status: () => respond(usage(), ok ? 200 : 401) });
  assert.ok($(w, "#indexer-bar"));
  ok = false;
  Object.defineProperty(w.document, "hidden", { value: false });
  w.document.dispatchEvent(new w.Event("visibilitychange"));
  for (let i = 0; i < 4; i++) await tick();
  assert.equal($(w, "#indexer-bar"), null);
  assert.ok(!$(w, "html").classList.contains("ib-on"));
});

test("an htmx body swap keeps the bar", async () => {
  const w = await bar();
  w.document.body.innerHTML = NAVBAR;
  await tick();
  assert.ok($(w, "#indexer-bar"));
});

test("Prowlarr down: usage unavailable, disks still shown", async () => {
  const w = await bar({ data: usage({ ok: false, indexers: [] }) });
  assert.match($(w, "#indexer-bar .ib-chips").textContent, /Indexer usage unavailable/);
  assert.ok(disk(w, "library"));
});
