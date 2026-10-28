// Library page (/_hg/library/): every Audiobookshelf book the viewer's own ABS account may see, searchable and sortable. Data: /_hg/library/data.json (importer /library).
(function () {
  "use strict";
  var KEY = "hg-library-sort", all = [], abs = "", sort = "added";
  var SORTS = [["added", "Newest added"], ["title", "Title"], ["author", "Author"], ["size-desc", "Largest first"], ["size-asc", "Smallest first"], ["length", "Longest first"]];
  try { sort = localStorage.getItem(KEY) || sort; } catch (e) {}
  var $ = function (id) { return document.getElementById(id); };

  function el(t, cls, text) {
    var n = document.createElement(t);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function size(b) {
    if (b == null) return null;
    var gb = b / 1073741824;
    return gb >= 1 ? gb.toFixed(1) + " GB" : Math.max(1, Math.round(b / 1048576)) + " MB";
  }
  function length(s) {
    if (!s) return null;
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return (h ? h + " h " : "") + m + " min";
  }
  function day(iso) { return iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : null; }
  function cmp(a, b) { return (a || "").localeCompare(b || "", undefined, { sensitivity: "base" }); }
  function nulls(x, y, f) { return x == null && y == null ? 0 : x == null ? 1 : y == null ? -1 : f(x, y); }
  var ORDER = {
    added: function (a, b) { return cmp(b.added, a.added); },
    title: function (a, b) { return cmp(a.title, b.title); },
    author: function (a, b) { return cmp(a.author, b.author) || cmp(a.title, b.title); },
    "size-desc": function (a, b) { return nulls(a.size, b.size, function (x, y) { return y - x; }); },
    "size-asc": function (a, b) { return nulls(a.size, b.size, function (x, y) { return x - y; }); },
    length: function (a, b) { return (b.duration || 0) - (a.duration || 0); }
  };

  function card(b) {
    var c = el("article", "book");
    c.setAttribute("data-book", b.id);
    var img = el("img", "cover");
    img.alt = "";
    img.loading = "lazy";
    img.src = "/_hg/library/cover/" + encodeURIComponent(b.id);
    c.appendChild(img);
    var info = el("div", "info");
    info.appendChild(el("div", "title", b.title || "?"));
    if (b.subtitle) info.appendChild(el("div", "muted", b.subtitle));
    if (b.series) info.appendChild(el("div", "series", b.series));
    if (b.author) info.appendChild(el("div", null, b.author));
    if (b.narrator) info.appendChild(el("div", "muted", "Read by " + b.narrator));
    info.appendChild(el("div", "muted meta", [length(b.duration), size(b.size), day(b.added) && "added " + day(b.added), b.library].filter(Boolean).join(" · ")));
    var a = el("a", "open btn btn-sm btn-primary", "Open in Audiobookshelf");
    a.href = abs + encodeURIComponent(b.id);
    a.target = "_blank";
    a.rel = "noopener";
    info.appendChild(a);
    c.appendChild(info);
    return c;
  }

  function render() {
    var q = ($("q").value || "").trim().toLowerCase(), lib = $("lib").value;
    var list = all.filter(function (b) {
      if (lib && b.library !== lib) return false;
      return !q || [b.title, b.subtitle, b.author, b.narrator, b.series].some(function (v) { return v && v.toLowerCase().indexOf(q) >= 0; });
    }).sort(function (a, b) { return (ORDER[sort] || ORDER.added)(a, b) || cmp(a.title, b.title); });
    var box = $("books");
    box.textContent = "";
    var frag = document.createDocumentFragment();
    list.forEach(function (b) { frag.appendChild(card(b)); });
    box.appendChild(frag);
    $("state").textContent = list.length === all.length ? all.length + " books" : list.length + " of " + all.length + " books";
  }

  function setup(data) {
    all = data.items || [];
    abs = data.abs || "";
    var s = $("sort");
    SORTS.forEach(function (o) { var opt = el("option", null, o[1]); opt.value = o[0]; s.appendChild(opt); });
    if (!ORDER[sort]) sort = "added";
    s.value = sort;
    var l = $("lib"), names = all.map(function (b) { return b.library; }).filter(function (n, i, a) { return n && a.indexOf(n) === i; }).sort(cmp);
    var any = el("option", null, "All libraries");
    any.value = "";
    l.appendChild(any);
    names.forEach(function (n) { var o = el("option", null, n); o.value = n; l.appendChild(o); });
    s.addEventListener("change", function () { sort = s.value; try { localStorage.setItem(KEY, sort); } catch (e) {} render(); });
    l.addEventListener("change", render);
    $("q").addEventListener("input", render);
    if (data.noAbsUser) { $("state").textContent = "No Audiobookshelf account yet: open Audiobookshelf once (Login with Holy Grail), then reload this page."; return; }
    render();
  }

  fetch("/_hg/library/data.json", { cache: "no-store", credentials: "same-origin", redirect: "manual" })
    .then(function (r) { if (!r.ok) throw new Error(r.status || "login"); return r.json(); })
    .then(setup)
    .catch(function (e) { $("state").textContent = "Could not load the library (" + e.message + ")."; });
})();
