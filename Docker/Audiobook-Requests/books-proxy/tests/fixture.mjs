import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const WWW = new URL("../www/", import.meta.url);

// ABR's navbar as BaseLayout.jinja renders it, reduced to what the scripts look at.
export const NAVBAR = `
<div class="hidden" id="toast-block"></div>
<header class="shadow-lg"><nav class="navbar">
  <div class="flex-1">
    <a href="/" class="btn btn-ghost text-lg hidden sm:inline-flex">AudioBookRequest</a>
    <a href="/search" class="btn btn-ghost btn-square" title="Search"></a>
    <a href="/wishlist" class="btn btn-ghost btn-square group relative" title="Wishlist"></a>
  </div>
  <div class="flex-none flex pr-4"><a href="/settings/account" class="btn btn-ghost btn-square group" title="Settings"></a></div>
</nav></header>
<main></main>`;

// bar.js config as books-proxy injects it (nginx.conf sub_filter).
export const BAR_TAG = `<script data-ib-data="/_hg/bar/usage.json" data-ib-quota="/_hg/bar/my-quota.json" data-ib-no-bar="^/(login|auth|init)\\b"></script>`;

// A DOM with the given body; `before` runs in the window before the script (stubs), then the script itself.
export function load(script, body, before, url = "https://books.example.com/search", head = BAR_TAG) {
  const dom = new JSDOM(`<!doctype html><html lang="en"><head>${head}</head><body>${body}</body></html>`, { runScripts: "outside-only", url });
  if (before) before(dom.window);
  dom.window.eval(readFileSync(new URL(script, WWW), "utf8"));
  return dom.window;
}

export const tick = () => new Promise((r) => setTimeout(r, 0));
