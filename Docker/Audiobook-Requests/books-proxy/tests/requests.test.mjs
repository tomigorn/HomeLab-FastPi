import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { load, tick } from "./fixture.mjs";

const GB = 1024 ** 3, MB = 1024 ** 2;
const BODY = `<p id="state"></p><select id="sort"><option value="">newest first</option><option value="desc">largest first</option><option value="asc">smallest first</option></select><table><tbody id="rows"></tbody></table>`;
const ROWS = [
  { title: "New", author: "A", cover: "https://img/1.jpg", requested_by: "jane", requested: "2026-10-26T09:00:00", status: "downloading", asin: "A1", size: 400 * MB },
  { title: "Mid", author: "B", cover: null, requested_by: "john", requested: "2026-10-25T09:00:00", status: "in library", asin: "A2", size: 3 * GB },
  { title: "Old", author: "C", cover: "javascript:alert(1)", requested_by: "jane", requested: "2026-10-20T09:00:00", status: "open", asin: "A3", size: null },
];
const open = [];
afterEach(() => { while (open.length) open.pop().close(); });

async function page() {
  const w = load("requests/requests.js", BODY, (win) => {
    win.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(ROWS) });
  }, "https://books.example.com/_hg/requests/", "");
  open.push(w);
  for (let i = 0; i < 6; i++) await tick();
  return w;
}
const col = (w, i) => [...w.document.querySelectorAll("#rows tr")].map((tr) => tr.children[i].textContent.trim());
function choose(w, v) { const s = w.document.getElementById("sort"); s.value = v; s.dispatchEvent(new w.Event("change")); }

test("rows with size, newest first; unknown size as a dash; only https covers", async () => {
  const w = await page();
  assert.deepEqual(col(w, 4), ["400 MB", "3 GB", "–"]);
  assert.match(col(w, 1)[0], /^New/);
  assert.equal(w.document.querySelectorAll("#rows img[src]").length, 1);
  assert.equal(w.document.getElementById("state").textContent, "3 requests");
});

test("sort by size both ways and back", async () => {
  const w = await page();
  choose(w, "desc");
  assert.deepEqual(col(w, 4), ["3 GB", "400 MB", "–"]);
  choose(w, "asc");
  assert.deepEqual(col(w, 4), ["400 MB", "3 GB", "–"]);
  choose(w, "");
  assert.deepEqual(col(w, 1), ["NewA", "MidB", "OldC"]);
});
