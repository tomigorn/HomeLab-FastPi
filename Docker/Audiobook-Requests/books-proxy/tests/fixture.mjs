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

// A DOM with the given body; `before` runs in the window before the script (stubs), then the vendored tip.js before bar.js (as books-proxy injects it; `tip: false` = without), then the script itself.
export function load(script, body, before, url = "https://books.example.com/search", head = BAR_TAG, { tip = true } = {}) {
  const dom = new JSDOM(`<!doctype html><html lang="en"><head>${head}</head><body>${body}</body></html>`, { runScripts: "outside-only", url });
  if (before) before(dom.window);
  if (script === "bar/bar.js" && tip) dom.window.eval(readFileSync(new URL("bar/tip.js", WWW), "utf8"));
  dom.window.eval(readFileSync(new URL(script, WWW), "utf8"));
  return dom.window;
}

export const tick = () => new Promise((r) => setTimeout(r, 0));

// An element's hint (tip.js) as it opens: the bold headline, every line, the number of sections.
export function hintOf(w, el) {
  if (!w.hgTip || !w.hgTip.get(el)) return null;
  w.hgTip.show(el);
  const box = w.document.getElementById("hg-tip");
  const out = { title: box.querySelector(".hg-tip-title")?.textContent ?? null, text: [...box.querySelectorAll("[data-hg-tip-line]")].map((e) => e.textContent).join("\n"), sections: box.querySelectorAll(".hg-tip-sep").length + 1 };
  w.hgTip.hide();
  return out;
}
