// "Movies / Series" link to Seerr: next to ABR's Wishlist button; if ABR's navbar ever changes, a small fixed bar instead.
// Also "All requests" (/_hg/requests/) and "Library" (/_hg/library/), books-proxy pages.
(function () {
  var links = [["hg-all", "/_hg/requests/", "All requests"], ["hg-library", "/_hg/library/", "Library"], ["hg-movies", "https://requests.holy-grail.ch/", "Movies / Series"]];
  function add() {
    if (document.getElementById("hg-movies")) return;
    var wishlist = document.querySelector('nav a[title="Wishlist"]');
    if (!wishlist && /^\/(auth|login|init)/.test(location.pathname)) return;
    var bar = null;
    if (!wishlist) {
      bar = document.createElement("div");
      bar.style.cssText = "position:fixed;top:0;right:0;z-index:9999;display:flex;gap:12px;padding:4px 10px;font:14px sans-serif;background:#13223a;border-bottom-left-radius:6px";
      document.body.appendChild(bar);
    }
    var after = wishlist;
    links.forEach(function (l) {
      var a = document.createElement("a");
      a.id = l[0]; a.href = l[1]; a.textContent = l[2]; a.title = l[2];
      if (wishlist) {
        a.className = "btn btn-ghost";
        after.parentNode.insertBefore(a, after.nextSibling);
        after = a;
      } else {
        a.style.cssText = "color:#e9b949;text-decoration:none";
        bar.appendChild(a);
      }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
})();
