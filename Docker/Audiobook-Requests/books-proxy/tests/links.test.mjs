import { test } from "node:test";
import assert from "node:assert/strict";
import { load, NAVBAR, tick } from "./fixture.mjs";

test("navbar: All requests, Library, Movies / Series after Wishlist", async () => {
  const w = load("links.js", NAVBAR, null, "https://books.example.com/search", "");
  await tick();
  const after = [];
  for (let n = w.document.querySelector('nav a[title="Wishlist"]').nextElementSibling; n; n = n.nextElementSibling) after.push([n.textContent, n.getAttribute("href")]);
  assert.deepEqual(after, [["All requests", "/_hg/requests/"], ["Library", "/_hg/library/"], ["Movies / Series", "https://requests.holy-grail.ch/"]]);
  w.close();
});

test("no navbar on the login page: nothing added", () => {
  const w = load("links.js", "<main></main>", null, "https://books.example.com/login", "");
  assert.equal(w.document.getElementById("hg-library"), null);
  w.close();
});
