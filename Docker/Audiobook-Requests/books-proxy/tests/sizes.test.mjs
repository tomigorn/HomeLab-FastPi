import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { load, NAVBAR, tick } from "./fixture.mjs";

const GB = 1024 ** 3, MB = 1024 ** 2;
// ABR's wishlist table (Requests / Downloaded tab), reduced: Release has a desktop and a phone cell.
function row(asin, n, title) {
  return `<tr class="text-xs" id="${asin}"><th>${n}</th><td><img></td><td><a class="font-bold">${title}</a></td><td>Author</td><td>Narrator</td>
    <td class="hidden lg:table-cell">March 2008</td><td class="lg:hidden">2008</td><td>0.6</td><td title="1"><button>1</button></td>
    <td><button hx-post="/wishlist/hx-auto-download/${asin}" hx-target="#book-table-body">dl</button></td></tr>`;
}
function table(rows) {
  return `<table id="book-table-body" class="table"><thead><tr><th></th><th></th><th>Title</th><th>Author</th><th>Narrator</th><th>Release</th>
    <th>Length (hrs)</th><th># Requested</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}
const ROWS = [row("A1", 1, "Small"), row("A2", 2, "Big"), row("A3", 3, "Unknown"), row("A4", 4, "Middle")];
const SIZES = { A1: 300 * MB, A2: 2.5 * GB, A4: 900 * MB };

const open = [];
afterEach(() => { while (open.length) open.pop().close(); });

async function page({ rows = ROWS, sizes = SIZES, status = 200, url = "https://books.example.com/wishlist/downloaded", calls = [] } = {}) {
  const w = load("sizes.js", NAVBAR.replace("<main></main>", `<main>${table(rows)}</main>`), (win) => {
    win.fetch = (u, o) => { calls.push([u, o]); return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(sizes) }); };
  }, url, "");
  open.push(w);
  for (let i = 0; i < 6; i++) await tick();
  return w;
}
const titles = (w) => [...w.document.querySelectorAll("#book-table-body tbody tr")].map((tr) => tr.querySelector("a").textContent);
const sizeCells = (w) => [...w.document.querySelectorAll("#book-table-body tbody td[data-hg-size]")].map((td) => td.textContent);
const head = (w) => w.document.querySelector("#book-table-body thead [data-hg-size] button");

test("size column right after Length, formatted, unknown as a dash", async () => {
  const calls = [];
  const w = await page({ calls });
  const ths = [...w.document.querySelectorAll("#book-table-body thead th")].map((t) => t.textContent.trim());
  assert.match(ths[ths.indexOf("Length (hrs)") + 1], /^Size ⇅$/);
  assert.deepEqual(sizeCells(w), ["300 MB", "2.5 GB", "–", "900 MB"]);
  const tr = w.document.getElementById("A1");
  const cells = [...tr.children];
  assert.equal(cells[cells.findIndex((c) => c.dataset.hgSize !== undefined) - 1].textContent, "0.6");
  assert.equal(calls[0][0], "/_hg/sizes.json");
  assert.equal(calls[0][1].credentials, "same-origin");
});

test("header click: largest first, then smallest first, then ABR's order", async () => {
  const w = await page();
  head(w).click(); await tick();
  assert.deepEqual(titles(w), ["Big", "Middle", "Small", "Unknown"]);
  assert.match(head(w).textContent, /▼/);
  head(w).click(); await tick();
  assert.deepEqual(titles(w), ["Small", "Middle", "Big", "Unknown"]);
  assert.match(head(w).textContent, /▲/);
  head(w).click(); await tick();
  assert.deepEqual(titles(w), ["Small", "Big", "Unknown", "Middle"]);
});

test("htmx swap of the table: column and sort come back, rows keep their htmx attributes", async () => {
  const w = await page();
  head(w).click(); await tick();
  const t = w.document.getElementById("book-table-body");
  const fresh = w.document.createElement("div");
  fresh.innerHTML = table([row("A1", 1, "Small"), row("A2", 2, "Big")]);
  t.replaceWith(fresh.firstElementChild);
  for (let i = 0; i < 4; i++) await tick();
  assert.deepEqual(titles(w), ["Big", "Small"]);
  assert.equal(w.document.querySelectorAll("#book-table-body thead [data-hg-size]").length, 1);
  assert.equal(w.document.querySelector("#A2 [hx-post]").getAttribute("hx-target"), "#book-table-body");
});

test("sort choice is remembered across pages", async () => {
  let w = await page();
  head(w).click(); await tick();
  const saved = w.localStorage.getItem("hg-size-sort");
  assert.equal(saved, "desc");
});

test("no session or no table: nothing added", async () => {
  let w = await page({ status: 401 });
  assert.equal(w.document.querySelector("[data-hg-size]"), null);
  w = await page({ rows: [], url: "https://books.example.com/search" });
  assert.equal(w.document.querySelectorAll("tbody [data-hg-size]").length, 0);
});

test("manual tab without a Length column: no size column", async () => {
  const w = load("sizes.js", NAVBAR.replace("<main></main>", `<main><table id="book-table-body"><thead><tr><th></th><th>Title</th><th>Info</th></tr></thead><tbody><tr id="x"><th>1</th><td>T</td><td>i</td></tr></tbody></table></main>`), (win) => {
    win.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SIZES) });
  }, "https://books.example.com/wishlist/manual", "");
  open.push(w);
  for (let i = 0; i < 6; i++) await tick();
  assert.equal(w.document.querySelector("[data-hg-size]"), null);
});
