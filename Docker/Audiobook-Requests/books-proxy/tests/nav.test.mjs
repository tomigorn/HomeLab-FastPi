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
  assert.equal(w.document.querySelectorAll("#hg-nav a svg").length, 6);
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

test("added once, styles below lg only with safe area and body padding", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/wishlist", "");
  await tick();
  w.eval(require_nav());
  assert.equal(w.document.querySelectorAll("#hg-nav").length, 1);
  const css = w.document.getElementById("hg-nav-style").textContent;
  assert.match(css, /max-width:\s*1023px/);
  assert.match(css, /safe-area-inset-bottom/);
  assert.match(css, /body\s*\{[^}]*padding-bottom/);
  w.close();
});

test("desktop sidebar: Seerr's lg breakpoint, 16rem wide, content shifted, indexer bar stays on top", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/search", "");
  await tick();
  const css = w.document.getElementById("hg-nav-style").textContent;
  const wide = css.slice(css.indexOf("min-width:1024px"));
  assert.ok(css.includes("@media (min-width:1024px)"));
  assert.match(wide, /#hg-nav\{[^}]*position:fixed[^}]*width:16rem/);
  assert.match(wide, /top:var\(--ib-h,0px\)/);
  assert.match(wide, /linear-gradient\(#1f2937/);
  assert.match(wide, /body\{[^}]*padding-left:16rem/);
  assert.match(wide, /hg-nav-active\{[^}]*linear-gradient\([^}]*#4f46e5/);
  assert.match(wide, /#hg-nav a span\{[^}]*position:static/);
  w.close();
});

test("logo block: book icon and the title, EN and DE, not a link", async () => {
  const en = load("nav.js", NAVBAR, null, "https://books.example.com/", "");
  await tick();
  const logo = en.document.querySelector("#hg-nav .hg-nav-logo");
  assert.equal(logo.textContent.trim(), "Audiobooks");
  assert.ok(logo.querySelector("svg"));
  assert.equal(logo.closest("a"), null);
  en.close();
  const de = load("nav.js", NAVBAR, (win) => Object.defineProperty(win.navigator, "language", { value: "de-DE" }), "https://books.example.com/", "");
  await tick();
  assert.equal(de.document.querySelector("#hg-nav .hg-nav-logo").textContent.trim(), "Hörbücher");
  de.close();
});

test("logo is hidden below lg", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/", "");
  await tick();
  assert.match(w.document.getElementById("hg-nav-style").textContent, /\.hg-nav-logo\{display:none\}/);
  w.close();
});

import { readFileSync } from "node:fs";
function require_nav() { return readFileSync(new URL("../www/nav.js", import.meta.url), "utf8"); }

test("bottom bar colours match Seerr's mobile menu, active icon filled", async () => {
  const w = load("nav.js", NAVBAR, null, "https://books.example.com/search", "");
  await tick();
  const css = w.document.getElementById("hg-nav-style").textContent;
  const narrow = css.slice(css.indexOf("max-width:1023px"), css.indexOf("min-width:1024px"));
  assert.match(narrow, /#hg-nav\{[^}]*background:rgba\(31,41,55,\.9\)/);
  assert.match(narrow, /#hg-nav\{[^}]*backdrop-filter:blur/);
  assert.match(narrow, /#hg-nav\{[^}]*border-top:1px solid #4b5563/);
  assert.match(narrow, /#hg-nav a\{[^}]*color:#f3f4f6/);
  const svg = w.document.querySelector("#hg-nav a.hg-nav-active svg");
  assert.equal(svg.getAttribute("fill"), "currentColor");
  assert.equal(w.document.querySelector("#hg-nav a:not(.hg-nav-active) svg").getAttribute("fill"), "none");
  w.close();
});
