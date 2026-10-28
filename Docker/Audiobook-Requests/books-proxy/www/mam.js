// ABR only: "MAM unsatisfied" chip and panel section in the shared bar (bar/bar.js stays unchanged), from usage.json "mam" (scripts/abr_bar_usage.py). README "Requests bar".
(function () {
  "use strict";
  if (window.__mamChip) return;
  var tag = document.querySelector("script[data-ib-data]");
  if (!tag || !tag.dataset.ibData) return;
  window.__mamChip = true;

  var DATA = tag.dataset.ibData, REFRESH = 60000, RANK = { ok: 0, yellow: 1, warn: 2, orange: 3, full: 4 };
  var mam = null;
  var WORDS = { en: { risk: function (n) { return n + " at risk"; }, off: "unavailable", next: "next free " },
    de: { risk: function (n) { return n + " Risiko"; }, off: "nicht verfügbar", next: "wieder frei " } };

  function el(t, cls, text) {
    var n = document.createElement(t);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function add(p) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) p.appendChild(arguments[i]); return p; }
  function lang() { return /^de\b/i.test(navigator.language || "") ? "de" : "en"; }
  function tr(v, l) { return v == null ? "" : typeof v === "string" ? v : v[l] || v.en || ""; }
  function at(iso) {
    var d = new Date(iso), now = new Date(), t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return t;
    return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) + " " + t;
  }
  function textCls(level) { return level === "ok" ? "" : "ib-" + level + "-text"; }
  function meter(m) {
    var box = el("span", "ib-meter ib-" + m.level), fill = el("span", "ib-fill");
    fill.style.width = Math.min(100, m.limit ? Math.round((100 * m.unsatisfied) / m.limit) : 100) + "%";
    fill.style.display = "block";
    return add(box, fill);
  }
  function hint(m, l) { return tr(m.hint, l).replace("{freesAt}", m.freesAt ? at(m.freesAt) : ""); }
  function risks(m) { return Array.isArray(m.risks) ? m.risks : []; }

  function chip(l) {
    var w = WORDS[l], c;
    if (!mam.ok) c = add(el("span", "ib-chip ib-muted"), el("span", "ib-name", tr(mam.label, l)), el("span", null, w.off));
    else {
      var r = risks(mam);
      c = add(el("span", "ib-chip"), el("span", "ib-name", tr(mam.label, l)), meter(mam),
        el("span", textCls(mam.level), mam.unsatisfied + "/" + mam.limit), r.length ? el("span", "ib-full-text", w.risk(r.length)) : null);
      c.title = hint(mam, l);
    }
    c.setAttribute("data-ib-mam", "");
    return c;
  }
  function section(l) {
    var s = el("div"), t = el("table"), w = WORDS[l];
    s.setAttribute("data-ib-mam-panel", "");
    add(t, add(el("tr"), add(el("td"), el("div", "ib-name", tr(mam.label, l)), el("div", "ib-muted", mam["class"] || "")),
      add(el("td"), add(el("div", "ib-line"), meter(mam), el("span", textCls(mam.level), mam.unsatisfied + "/" + mam.limit)),
        mam.freesAt ? add(el("div", "ib-line"), el("span", "ib-muted", w.next + at(mam.freesAt))) : null)));
    var rule = el("td", "ib-muted ib-rule", tr(mam.rule, l));
    rule.colSpan = 2;
    add(t, add(el("tr"), rule));
    add(s, el("h4", null, tr(mam.head, l)), t);
    var r = risks(mam);
    if (r.length) {
      var rt = el("table");
      r.forEach(function (x) {
        add(rt, add(el("tr"), el("td", "ib-name", x.name), el("td", "ib-full-text", tr((mam.reasons || {})[x.reason], l) + " · " + x.seededHours + " h")));
      });
      add(s, el("h4", null, tr(mam.risksHead, l)), rt);
    }
    return s;
  }

  function apply() {
    var bar = document.getElementById("indexer-bar");
    if (!bar) return;
    if (!mam) {
      [].forEach.call(bar.querySelectorAll("[data-ib-mam],[data-ib-mam-panel]"), function (n) { n.parentNode.removeChild(n); });
      return;
    }
    var l = lang(), box = bar.querySelector(".ib-chips"), mini = document.documentElement.classList.contains("ib-mini");
    if (box && !mini && !box.querySelector("[data-ib-mam]")) {
      var ix = box.querySelectorAll("[data-ib-indexer]"), after = ix.length ? ix[ix.length - 1] : null;
      box.insertBefore(chip(l), after ? after.nextSibling : box.firstChild);
    }
    var panel = bar.querySelector(".ib-panel");
    if (panel && mam.ok && !panel.querySelector("[data-ib-mam-panel]")) panel.insertBefore(section(l), panel.querySelector(".ib-note"));
    var dot = bar.querySelector(".ib-title .ib-dot"), lvl = mam.ok ? mam.level : "ok";
    if (dot) {
      var cur = (dot.className.match(/ib-(ok|yellow|warn|orange|full)\b/) || [, "ok"])[1];
      if (RANK[lvl] > RANK[cur]) dot.className = "ib-dot ib-" + lvl;
    }
  }

  function load() {
    try {
      fetch(DATA, { cache: "no-store", credentials: "same-origin", redirect: "manual" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { mam = j && j.mam && typeof j.mam === "object" ? j.mam : null; apply(); })
        .catch(function () { mam = null; apply(); });
    } catch (e) {}
  }

  function start() {
    load();
    setInterval(load, REFRESH);
    new MutationObserver(function () { try { apply(); } catch (e) {} }).observe(document.body, { childList: true, subtree: true });
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
