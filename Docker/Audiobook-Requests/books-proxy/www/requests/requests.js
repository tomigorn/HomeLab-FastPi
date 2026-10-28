// "All requests" page: everyone's requests from /_hg/requests/data.json, newest first or by size.
(function () {
  "use strict";
  var LABEL = { "open": ["open", ""], "downloading": ["downloading", "dl"], "in library": ["in library", "lib"] };
  var rows = [];
  function cell(tr, child) { var td = document.createElement("td"); if (child) td.appendChild(child); tr.appendChild(td); return td; }
  function text(t, cls) { var s = document.createElement("span"); s.textContent = t || ""; if (cls) s.className = cls; return s; }
  function size(b) {
    if (b == null) return "–";
    var gb = b / 1073741824;
    return gb >= 1 ? (Math.round(gb * 10) / 10) + " GB" : Math.max(1, Math.round(b / 1048576)) + " MB";
  }
  function render() {
    var order = document.getElementById("sort").value, body = document.getElementById("rows");
    var list = rows.map(function (r, i) { return [r, i]; }).sort(function (a, b) {
      var x = a[0].size, y = b[0].size;
      if (!order || (x == null && y == null)) return a[1] - b[1];
      if (x == null || y == null) return x == null ? 1 : -1;
      return (order === "desc" ? y - x : x - y) || a[1] - b[1];
    });
    body.textContent = "";
    list.forEach(function (p) {
      var r = p[0], tr = document.createElement("tr"), img = document.createElement("img");
      img.className = "cover"; img.alt = ""; img.loading = "lazy";
      if (r.cover && /^https:\/\//.test(r.cover)) img.src = r.cover;
      cell(tr, img);
      var book = cell(tr, text(r.title, "font-bold"));
      book.appendChild(document.createElement("br"));
      book.appendChild(text(r.author, "muted"));
      cell(tr, text(r.requested_by));
      cell(tr, text((r.requested || "").slice(0, 10), "muted"));
      cell(tr, text(size(r.size), "muted")).style.whiteSpace = "nowrap";
      var l = LABEL[r.status] || [r.status, ""];
      cell(tr, text(l[0], "pill " + l[1]));
      body.appendChild(tr);
    });
  }
  fetch("/_hg/requests/data.json", { credentials: "same-origin" }).then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).then(function (data) {
    rows = data;
    document.getElementById("state").textContent = rows.length + " requests";
    document.getElementById("sort").addEventListener("change", render);
    render();
  }).catch(function (e) {
    document.getElementById("state").textContent = "Could not load the requests (" + e.message + ").";
  });
})();
