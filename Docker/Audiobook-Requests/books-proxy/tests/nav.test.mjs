import { test } from "node:test";
import assert from "node:assert/strict";
import { load, NAVBAR, tick } from "./fixture.mjs";

const items = (w) => [...w.document.querySelectorAll("#hg-nav a")].map((a) => [a.getAttribute("href"), a.textContent.trim()]);

test("bottom bar: Seerr's six entries, Audiobooks active", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/search", "");
  await tick();
  assert.deepEqual(items(w), [
    ["https://requests.holy-grail.ch/", "Discover"],
    ["https://requests.holy-grail.ch/discover/movies", "Movies"],
    ["https://requests.holy-grail.ch/discover/tv", "Series"],
    ["/", "Audiobooks"],
    ["https://requests.holy-grail.ch/_manual/", "Manual interaction"],
    ["https://requests.holy-grail.ch/requests", "Requests"],
  ]);
  const active = [...w.document.querySelectorAll("#hg-nav a.hg-nav-active")];
  assert.deepEqual(active.map((a) => a.textContent.trim()), ["Audiobooks"]);
  assert.equal(active[0].getAttribute("aria-current"), "page");
  assert.equal(w.document.querySelectorAll("#hg-nav svg").length, 6);
  w.close();
});

test("German browser: German labels and manual link", async () => {
  const w = load("nav.js", NAVBAR, (win) => Object.defineProperty(win.navigator, "language", { value: "de-CH" }), "https://books.example.com/", "");
  await tick();
  assert.deepEqual(items(w).map((i) => i[1]), ["Entdecken", "Filme", "Serien", "Hörbücher", "Manuell beheben", "Anfragen"]);
  assert.equal(w.document.querySelector('#hg-nav a[href*="_manual"]').getAttribute("href"), "https://requests.holy-grail.ch/_manual/?lang=de");
  w.close();
});

test("no bar on login, auth and init pages", async () => {
  for (const p of ["/login", "/auth/oidc", "/init"]) {
    const w = load("nav.js", "<main></main>", null, "https://books.example.com" + p, "");
    await tick();
    assert.equal(w.document.getElementById("hg-nav"), null, p);
    w.close();
  }
});

test("added once, styles narrow-only with safe area and body padding", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/wishlist", "");
  await tick();
  w.eval(require_nav());
  assert.equal(w.document.querySelectorAll("#hg-nav").length, 1);
  const css = w.document.getElementById("hg-nav-style").textContent;
  assert.match(css, /max-width:\s*639px/);
  assert.match(css, /safe-area-inset-bottom/);
  assert.match(css, /body\s*\{[^}]*padding-bottom/);
  w.close();
});

import { readFileSync } from "node:fs";
function require_nav() { return readFileSync(new URL("../www/nav.js", import.meta.url), "utf8"); }
