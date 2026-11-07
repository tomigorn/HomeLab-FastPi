#!/usr/bin/env node
// Real logged-in check of the VPN hint: canary login, from the public path (outside) and the LAN (home).
// Two extra tiles exist only in this browser, the account needs no groups. Inject the script unless the page already has it.
// Run through vpn-tiles-browser-test.sh (it enables and disables the canary). Screenshots: $OUT.
const { chromium } = require("playwright");
const crypto = require("crypto"), fs = require("fs"), path = require("path"), dns = require("dns").promises;
const SCRIPTS = __dirname, JS = path.join(process.env.VPN_TILES_TEMPLATES || path.join(SCRIPTS, "..", "custom-templates"), "holy-grail", "vpn-tiles.js");
const OUT = process.env.OUT || "/tmp";
const SSO = "https://sso.holy-grail.ch";
const env = Object.fromEntries(fs.readFileSync(path.join(SCRIPTS, "..", "secrets", "canary.env"), "utf8").split("\n")
  .filter((l) => l.includes("=") && !l.startsWith("#")).map((l) => { const i = l.indexOf("="); return [l.slice(0, i), l.slice(i + 1)]; }));

function b32(s) {
  let bits = "", out = [];
  for (const c of s.replace(/=+$/, "")) bits += "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567".indexOf(c).toString(2).padStart(5, "0");
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}
function totp(step) {
  const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(step));
  const m = crypto.createHmac("sha1", b32(env.CANARY_TOTP_B32)).update(c).digest();
  return String((m.readUInt32BE(m[19] & 15) & 0x7fffffff) % 1e6).padStart(6, "0");
}
let lastStep = 0;
async function freshCode() {
  while (Math.floor(Date.now() / 30000) === lastStep) await new Promise((r) => setTimeout(r, 1000));
  lastStep = Math.floor(Date.now() / 30000);
  return totp(lastStep);
}
async function login(ctx) {
  const url = SSO + "/api/v3/flows/executor/default-authentication-flow/?query=";
  const post = async (data) => {
    const csrf = (await ctx.cookies()).find((c) => c.name === "authentik_csrf" || c.name === "csrftoken");
    return (await ctx.request.post(url, { data, headers: { "X-authentik-CSRF": csrf ? csrf.value : "" } })).json();
  };
  let d = await (await ctx.request.get(url)).json();
  for (let i = 0; i < 10; i++) {
    const c = d.component;
    if (c === "ak-stage-identification") d = await post({ uid_field: env.CANARY_USERNAME });
    else if (c === "ak-stage-password") d = await post({ password: env.CANARY_PASSWORD });
    else if (c === "ak-stage-authenticator-validate") d = await post({ component: c, selected_challenge: d.device_challenges.find((x) => x.device_class === "totp"), code: await freshCode() });
    else if (c === "ak-stage-user-login") d = await post({ component: c, remember_me: true });
    else if (c === "xak-flow-redirect" || d.type === "redirect") return;
    else throw new Error("login stopped at " + c);
  }
  throw new Error("login did not finish");
}
const fake = (t, name, slug, url) => ({ ...t, pk: crypto.randomUUID(), name, slug, launch_url: url, launchUrl: url, meta_launch_url: url, metaLaunchUrl: url, group: "Homelab", meta_description: "test tile", metaDescription: "test tile" });

async function run(where, ip, inject) {
  const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP sso.holy-grail.ch ${ip}`] });
  const ctx = await browser.newContext({ viewport: process.env.MOBILE ? { width: 412, height: 915 } : { width: 1200, height: 800 }, isMobile: !!process.env.MOBILE, hasTouch: !!process.env.MOBILE, colorScheme: process.env.SCHEME || "dark" });
  await login(ctx);
  await ctx.route("**/api/v3/core/applications/**", async (route) => {
    const res = await route.fetch(), j = await res.json();
    if (j.results && j.results[0]) j.results.unshift(fake(j.results[0], "Grafana", "fake-grafana", "https://grafana.holy-grail.ch"), fake(j.results[0], "Jellyfin", "fake-jellyfin", "https://jellyfin.holy-grail.ch"));
    await route.fulfill({ response: res, json: j });
  });
  if (inject) {
    await ctx.addInitScript({ path: JS });
    await ctx.route("**/if/user/", async (route) => {
      const res = await route.fetch();
      await route.fulfill({ response: res, body: (await res.text()).replace(/<script>\(function \(\) \{\s*"use strict";[\s\S]*?hg-vpn-banner[\s\S]*?<\/script>/, "") });
    });
  }
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(SSO + "/if/user/");
  await page.waitForTimeout(7000);
  const state = await page.evaluate(() => {
    function root(r) {
      if (r.querySelector('[part="app-list"]')) return r;
      for (const e of r.querySelectorAll("*")) if (e.shadowRoot) { const f = root(e.shadowRoot); if (f) return f; }
      return null;
    }
    const r = root(document);
    const tile = (h) => { const a = r.querySelector(`[part="app-list"] a[href*="${h}"]`); return a ? a.closest('[part="card"],[part="row"]').hasAttribute("data-hg-vpn") : null; };
    return { banner: !!r.querySelector("#hg-vpn-banner"), grafana: tile("grafana."), jellyfin: tile("jellyfin.") };
  });
  await page.waitForTimeout(2300);
  const bannerStays = await page.evaluate(() => {
    function root(r) {
      if (r.querySelector('[part="app-list"]')) return r;
      for (const e of r.querySelectorAll("*")) if (e.shadowRoot) { const f = root(e.shadowRoot); if (f) return f; }
      return null;
    }
    return !!root(document).querySelector("#hg-vpn-banner");
  });
  state.banner = state.banner && bannerStays;
  await page.screenshot({ path: path.join(OUT, `vpn-tiles-${where}-${process.env.SCHEME || "dark"}${process.env.MOBILE ? "-phone" : ""}.png`) });
  let opened = null;
  if (state.grafana) {
    ctx.on("page", () => { opened = true; });
    const a = page.locator('[part="app-list"] a[href*="grafana."]').first();
    await a.click({ force: true }).catch(() => {});
    await page.waitForTimeout(1500);
    opened = !!opened;
  }
  await browser.close();
  return { ...state, opened, errors };
}

(async () => {
  const inject = process.argv.includes("--inject");
  const publicIp = (await dns.resolve4("sso.holy-grail.ch").catch(() => []))[0] || process.env.PUBLIC_IP;
  const outside = await run("outside", process.env.PUBLIC_IP || publicIp, inject);
  const home = await run("home", "192.168.1.2", inject);
  console.log(JSON.stringify({ outside, home }));
  const ok = outside.banner && outside.grafana === true && outside.jellyfin === false && outside.opened === false && !outside.errors.length
    && !home.banner && home.grafana === false && home.jellyfin === false && !home.errors.length;
  console.log(ok ? "VPN_TILES_OK" : "VPN_TILES_FAIL");
  process.exit(ok ? 0 : 1);
})().catch((e) => { console.error(String(e).slice(0, 400)); process.exit(1); });
