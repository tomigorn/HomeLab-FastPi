// "Movies / Series" link to Seerr: next to ABR's Wishlist button; if ABR's navbar ever changes, a small fixed bar instead.
(function () {
  var url = "https://requests.holy-grail.ch/";
  function add() {
    if (document.getElementById("hg-movies")) return;
    var a = document.createElement("a");
    a.id = "hg-movies";
    a.href = url;
    a.textContent = "Movies / Series";
    a.title = "Movies / Series";
    var wishlist = document.querySelector('nav a[title="Wishlist"]');
    if (wishlist && wishlist.parentNode) {
      a.className = "btn btn-ghost";
      wishlist.parentNode.insertBefore(a, wishlist.nextSibling);
      return;
    }
    if (/^\/(auth|login|init)/.test(location.pathname)) return;
    a.style.cssText = "position:fixed;top:0;right:0;z-index:9999;padding:4px 10px;font:14px sans-serif;background:#13223a;color:#e9b949;border-bottom-left-radius:6px;text-decoration:none";
    document.body.appendChild(a);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
})();
