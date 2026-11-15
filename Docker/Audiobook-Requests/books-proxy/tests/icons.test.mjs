import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const ICONS = new URL("../www/icons/", import.meta.url);
const CONF = readFileSync(new URL("../nginx.conf", import.meta.url), "utf8");

// Every icon URL ABR's BaseLayout.jinja links (plus the browser's default /favicon.ico) → our file.
const OVERRIDES = {
  "/static/favicon.svg": "favicon.svg",
  "/static/favicon-32x32.png": "favicon-32x32.png",
  "/static/favicon-16x16.png": "favicon-16x16.png",
  "/static/apple-touch-icon.png": "apple-touch-icon.png",
  "/static/site.webmanifest": "site.webmanifest",
  "/favicon.ico": "favicon.ico",
};

const icon = (f) => readFileSync(new URL(f, ICONS));
const pngSize = (b) => {
  assert.equal(b.subarray(1, 4).toString(), "PNG");
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
};

test("each ABR icon URL has an exact location serving our file", () => {
  for (const [path, file] of Object.entries(OVERRIDES)) {
    const block = CONF.match(new RegExp(`location = ${path.replace(/[.]/g, "\\.")} \\{([^}]*)\\}`));
    assert.ok(block, `no location = ${path}`);
    assert.match(block[1], new RegExp(`alias /srv/www/icons/${file.replace(/[.]/g, "\\.")};`), path);
    assert.match(block[1], /Cache-Control "public, max-age=3600"/, path);
    assert.ok(existsSync(new URL(file, ICONS)), file);
  }
  assert.match(CONF.match(/location = \/static\/site\.webmanifest \{([^}]*)\}/)[1], /default_type application\/manifest\+json;/);
});

test("PNGs have the sizes ABR and the manifest announce", () => {
  for (const [file, n] of [["favicon-16x16.png", 16], ["favicon-32x32.png", 32], ["apple-touch-icon.png", 180], ["android-chrome-192x192.png", 192], ["android-chrome-512x512.png", 512]]) {
    assert.deepEqual(pngSize(icon(file)), [n, n], file);
  }
});

test("favicon.ico holds 16, 32 and 48 px", () => {
  const b = icon("favicon.ico");
  assert.deepEqual([b.readUInt16LE(0), b.readUInt16LE(2)], [0, 1]);
  const sizes = Array.from({ length: b.readUInt16LE(4) }, (_, i) => b[6 + 16 * i] || 256).sort((x, y) => x - y);
  assert.deepEqual(sizes, [16, 32, 48]);
});

test("SVG master: sidebar logo gradient and a white book glyph", () => {
  const svg = icon("favicon.svg").toString();
  assert.match(svg, /#4f46e5/);
  assert.match(svg, /#9333ea/);
  assert.match(svg, /<circle/);
  assert.match(svg, /fill="#fff"/);
});

test("manifest: Audiobooks, our android icons", () => {
  const m = JSON.parse(icon("site.webmanifest"));
  assert.equal(m.name, "Audiobooks");
  assert.equal(m.short_name, "Audiobooks");
  assert.deepEqual(m.icons.map((i) => [i.src, i.sizes, i.type]), [
    ["/_hg/icons/android-chrome-192x192.png", "192x192", "image/png"],
    ["/_hg/icons/android-chrome-512x512.png", "512x512", "image/png"],
  ]);
  for (const i of m.icons) assert.ok(existsSync(new URL(i.src.replace("/_hg/icons/", ""), ICONS)), i.src);
});

test("pages point to our icon URLs, never ABR's /static ones (browsers keep those cached for a year)", () => {
  const conf = readFileSync(new URL("../nginx.conf", import.meta.url), "utf8");
  const root = conf.slice(conf.indexOf("        location / {"));
  for (const file of ["apple-touch-icon.png", "favicon.svg", "favicon-32x32.png", "favicon-16x16.png", "site.webmanifest"]) {
    assert.ok(root.includes(`sub_filter '/static/${file}?v=' '/_hg/icons/${file}?hg=1&v=';`), file);
  }
});
