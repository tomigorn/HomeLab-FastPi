import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { load, tick } from "./fixture.mjs";

const GB = 1024 ** 3, MB = 1024 ** 2;
const BODY = `<main><input id="q"><select id="sort"></select><select id="lib"></select><p id="state"></p><div id="books"></div></main>`;
function book(id, o = {}) {
  return { id, title: "Title " + id, subtitle: null, author: "Jane Doe", narrator: "John Roe", series: null, duration: 3600, size: 100 * MB,
    added: "2026-01-01T10:00:00Z", library: "[EN] Audiobooks", asin: null, year: "2010", ...o };
}
const ITEMS = [
  book("a", { title: "Alpha", author: "Zed Writer", size: 2 * GB, added: "2026-03-01T10:00:00Z", duration: 48120, series: "Saga #2" }),
  book("b", { title: "Beta", author: "Amy Author", narrator: "Nora Narrator", size: 300 * MB, added: "2026-05-01T10:00:00Z", library: "[DE] Hörbücher" }),
  book("c", { title: "<img src=x onerror=alert(1)>", author: "Bob", size: null, added: "2025-12-01T10:00:00Z" }),
];
const DATA = { count: 3, items: ITEMS, noAbsUser: false, abs: "https://audiobookshelf.example.com/item/" };

const open = [];
afterEach(() => { while (open.length) open.pop().close(); });

async function page({ data = DATA, status = 200, calls = [] } = {}) {
  const w = load("library/library.js", BODY, (win) => {
    win.fetch = (u, o) => { calls.push([u, o]); return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(data) }); };
  }, "https://books.example.com/_hg/library/", "");
  open.push(w);
  for (let i = 0; i < 6; i++) await tick();
  return w;
}
const $ = (w, s) => w.document.querySelector(s);
const titles = (w) => [...w.document.querySelectorAll("#books [data-book] .title")].map((n) => n.textContent);
function choose(w, id, value) {
  const s = $(w, id);
  s.value = value;
  s.dispatchEvent(new w.Event("change"));
}

test("newest first by default, with count and every field", async () => {
  const calls = [];
  const w = await page({ calls });
  assert.equal(calls[0][0], "/_hg/library/data.json");
  assert.deepEqual(titles(w), ["Beta", "Alpha", "<img src=x onerror=alert(1)>"]);
  assert.equal($(w, "#state").textContent, "3 books");
  const a = $(w, '[data-book="a"]');
  assert.match(a.textContent, /Zed Writer/);
  assert.match(a.textContent, /Saga #2/);
  assert.match(a.textContent, /13 h 22 min/);
  assert.match(a.textContent, /2\.0 GB/);
  assert.match(a.textContent, /\[EN\] Audiobooks/);
  assert.match(a.textContent, /1 Mar 2026/);
  assert.match($(w, '[data-book="b"]').textContent, /Nora Narrator/);
  const link = a.querySelector("a.open");
  assert.equal(link.href, "https://audiobookshelf.example.com/item/a");
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener");
  assert.equal(a.querySelector("img").getAttribute("src"), "/_hg/library/cover/a");
  assert.equal(a.querySelector("img").loading, "lazy");
  assert.equal(w.document.querySelectorAll("#books img[onerror]").length, 0);
});

test("sort by size, title, author, length", async () => {
  const w = await page();
  choose(w, "#sort", "size-desc");
  assert.deepEqual(titles(w).slice(0, 2), ["Alpha", "Beta"]);
  choose(w, "#sort", "size-asc");
  assert.deepEqual(titles(w), ["Beta", "Alpha", "<img src=x onerror=alert(1)>"]);
  choose(w, "#sort", "title");
  assert.deepEqual(titles(w), ["<img src=x onerror=alert(1)>", "Alpha", "Beta"]);
  choose(w, "#sort", "author");
  assert.deepEqual(titles(w), ["Beta", "<img src=x onerror=alert(1)>", "Alpha"]);
  choose(w, "#sort", "length");
  assert.equal(titles(w)[0], "Alpha");
  assert.equal(w.localStorage.getItem("hg-library-sort"), "length");
});

test("search over title, author, narrator and series; library filter", async () => {
  const w = await page();
  const q = $(w, "#q");
  q.value = "nora"; q.dispatchEvent(new w.Event("input"));
  assert.deepEqual(titles(w), ["Beta"]);
  assert.equal($(w, "#state").textContent, "1 of 3 books");
  q.value = "saga"; q.dispatchEvent(new w.Event("input"));
  assert.deepEqual(titles(w), ["Alpha"]);
  q.value = ""; q.dispatchEvent(new w.Event("input"));
  assert.deepEqual([...$(w, "#lib").options].map((o) => o.textContent), ["All libraries", "[DE] Hörbücher", "[EN] Audiobooks"]);
  choose(w, "#lib", "[DE] Hörbücher");
  assert.deepEqual(titles(w), ["Beta"]);
});

test("no Audiobookshelf account: says how to get one", async () => {
  const w = await page({ data: { count: 0, items: [], noAbsUser: true, abs: DATA.abs } });
  assert.match($(w, "#state").textContent, /open Audiobookshelf once/);
});

test("not logged in: error, no books", async () => {
  const w = await page({ status: 401 });
  assert.match($(w, "#state").textContent, /Could not load the library \(401\)/);
  assert.equal(titles(w).length, 0);
});
