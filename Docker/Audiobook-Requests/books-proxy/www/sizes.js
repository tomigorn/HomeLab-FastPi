// ABR wishlist tables (Requests, Downloaded): a "Size" column after "Length (hrs)" and a size sort (largest, smallest, ABR's order). Sizes from /_hg/sizes.json (importer: Audiobookshelf item, else the torrent). Rows are only re-ordered, never re-created, so ABR's htmx keeps working.
(function () {
  "use strict";
  if (window.__hgSizes) return;
  window.__hgSizes = true;
  var KEY = "hg-size-sort", sizes = null, order = "";
  try { order = localStorage.getItem(KEY) || ""; } catch (e) {}

  function fmt(b) {
    if (b == null) return "–";
    var gb = b / 1073741824;
    return gb >= 1 ? (Math.round(gb * 10) / 10) + " GB" : Math.max(1, Math.round(b / 1048576)) + " MB";
  }
  function arrow() { return order === "desc" ? " ▼" : order === "asc" ? " ▲" : " ⇅"; }
  function lengthIndex(head) {
    var ths = head.children;
    for (var i = 0; i < ths.length; i++) if (/^\s*Length\b/.test(ths[i].textContent)) return i;
    return -1;
  }
  // Release has a desktop cell and a phone-only duplicate ("lg:hidden") under one header.
  function cellsLikeHeader(tr) {
    return [].filter.call(tr.children, function (c) { return !c.classList.contains("lg:hidden") && c.dataset.hgSize === undefined; });
  }
  function sortRows(body) {
    var rows = [].slice.call(body.children);
    rows.sort(function (a, b) {
      if (!order) return a.dataset.hgI - b.dataset.hgI;
      var x = a.dataset.hgBytes === "" ? null : +a.dataset.hgBytes, y = b.dataset.hgBytes === "" ? null : +b.dataset.hgBytes;
      if (x == null || y == null) return x == null && y == null ? a.dataset.hgI - b.dataset.hgI : x == null ? 1 : -1;
      return order === "desc" ? y - x || a.dataset.hgI - b.dataset.hgI : x - y || a.dataset.hgI - b.dataset.hgI;
    });
    var sorted = rows.every(function (r, i) { return body.children[i] === r; });
    if (!sorted) rows.forEach(function (r) { body.appendChild(r); });
  }
  function apply() {
    var t = document.getElementById("book-table-body");
    if (!t || !sizes) return;
    var head = t.querySelector("thead tr"), body = t.tBodies[0];
    if (!head || !body) return;
    var k = lengthIndex(head);
    if (k < 0) return;
    var th = head.querySelector("[data-hg-size]");
    if (!th) {
      th = document.createElement("th");
      th.setAttribute("data-hg-size", "");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-ghost btn-xs";
      b.title = "Sort by size";
      b.addEventListener("click", function () {
        order = order === "" ? "desc" : order === "desc" ? "asc" : "";
        try { localStorage.setItem(KEY, order); } catch (e) {}
        b.textContent = "Size" + arrow();
        apply();
      });
      th.appendChild(b);
      head.insertBefore(th, head.children[k + 1] || null);
    }
    if (th.firstChild.textContent !== "Size" + arrow()) th.firstChild.textContent = "Size" + arrow();
    [].forEach.call(body.children, function (tr, i) {
      if (tr.querySelector("[data-hg-size]")) return;
      var cells = cellsLikeHeader(tr), td = document.createElement("td"), bytes = sizes[tr.id];
      if (tr.dataset.hgI === undefined) tr.dataset.hgI = i;
      tr.dataset.hgBytes = bytes == null ? "" : bytes;
      td.setAttribute("data-hg-size", "");
      td.className = "whitespace-nowrap";
      td.textContent = fmt(bytes);
      var at = cells[k];
      tr.insertBefore(td, at ? at.nextSibling : null);
    });
    sortRows(body);
  }
  function start() {
    if (!document.getElementById("book-table-body")) return;
    fetch("/_hg/sizes.json", { cache: "no-store", credentials: "same-origin", redirect: "manual" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        sizes = j && typeof j === "object" ? j : null;
        apply();
        if (sizes) new MutationObserver(function () { try { apply(); } catch (e) {} }).observe(document.body, { childList: true, subtree: true });
      })
      .catch(function () {});
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
