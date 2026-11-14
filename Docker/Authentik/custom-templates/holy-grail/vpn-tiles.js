(function () {
  "use strict";

  var DOMAIN = ".holy-grail.ch";
  var LOCAL_ONLY = ["adguard", "bazarr", "grafana", "ha", "portainer", "prowlarr", "prowlarr-audiobooks", "qbittorrent",
    "qbittorrent-audiobooks", "radarr", "sabnzbd", "sabnzbd-audiobooks", "sonarr", "stonks", "traefik",
    "vpn-status-beefy", "vpn-status-mouse", "wg-easy", "wiki-admin"];
  // Traefik answers 403 here from outside (router authentik-admin, local-networks@file).
  var PROBE = "/if/admin/";
  var PROBE_EVERY_MS = 30000;
  var SCAN_EVERY_MS = 1500;
  var MARK = "data-hg-vpn";
  var LINE = "linear-gradient(to top right,transparent calc(50% - 1px),#8592a8 calc(50% - 1px),#8592a8 calc(50% + 1px),transparent calc(50% + 1px))";
  var CSS = "[" + MARK + "],[" + MARK + "]:hover{box-shadow:none!important;border-color:#8592a8!important;cursor:not-allowed}" +
    "[" + MARK + "] a{cursor:not-allowed}" +
    "[part=\"row\"][" + MARK + "]{position:relative}" +
    ".hg-vpn-veil{position:absolute;inset:0;z-index:3;pointer-events:none;background-color:rgba(226,229,235,.8);background-image:" + LINE + "}" +
    ":host([theme=\"dark\"]) .hg-vpn-veil{background-color:rgba(13,21,36,.8)}" +
    ".hg-vpn-badge{position:absolute;top:6px;left:6px;z-index:4;font-size:12px;font-weight:700;line-height:18px;padding:0 6px;color:#ffe7a3;background-color:#3a2d0c;border:1px solid #e9b949;border-radius:6px;pointer-events:none}" +
    "[part=\"row\"] .hg-vpn-badge{top:50%;left:auto;right:48px;transform:translateY(-50%)}" +
    "#hg-vpn-banner{display:flex;gap:10px;align-items:center;margin:0 0 16px;padding:9px 12px;border:1px solid #e9b949;border-radius:8px;background:#3a2d0c;color:#ffe7a3;font-size:14px}" +
    "#hg-vpn-banner b{color:#fff}" +
    "#hg-vpn-banner.hg-pulse{animation:hg-vpn-pulse .9s}" +
    "@keyframes hg-vpn-pulse{50%{box-shadow:0 0 0 4px #e9b949}}";

  function isLocalOnly(href) {
    var host;
    try {
      host = new URL(href).hostname;
    } catch (e) {
      return false;
    }
    if (host.slice(-DOMAIN.length) !== DOMAIN) return false;
    return LOCAL_ONLY.indexOf(host.slice(0, -DOMAIN.length)) !== -1;
  }

  function networkFromStatus(status) {
    if (status === 403) return "outside";
    return status >= 200 && status < 400 ? "home" : "unknown";
  }

  if (typeof module !== "undefined") {
    module.exports = {
      isLocalOnly: isLocalOnly,
      networkFromStatus: networkFromStatus,
      localOnlyHosts: function () { return LOCAL_ONLY; },
    };
    return;
  }

  var network = "unknown";
  var libraryRoot = null;

  function findLibraryRoot(root) {
    if (root.querySelector('[part="app-list"]')) return root;
    var all = root.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      if (all[i].shadowRoot) {
        var found = findLibraryRoot(all[i].shadowRoot);
        if (found) return found;
      }
    }
    return null;
  }

  function addStyle(root) {
    if (root.querySelector("#hg-vpn-style")) return;
    var style = document.createElement("style");
    style.id = "hg-vpn-style";
    style.textContent = CSS;
    root.appendChild(style);
  }

  function markCard(card, off) {
    var link = card.querySelector("a[href]");
    if (off) {
      card.setAttribute(MARK, "");
      if (!card.querySelector(".hg-vpn-veil")) {
        var veil = document.createElement("span");
        veil.className = "hg-vpn-veil";
        var badge = document.createElement("span");
        badge.className = "hg-vpn-badge";
        badge.textContent = "VPN";
        card.appendChild(veil);
        card.appendChild(badge);
      }
      if (link) {
        link.setAttribute("aria-disabled", "true");
        link.setAttribute("tabindex", "-1");
        link.setAttribute("title", "Needs the VPN or your home network");
      }
    } else if (card.hasAttribute(MARK)) {
      card.removeAttribute(MARK);
      var added = card.querySelectorAll(".hg-vpn-veil,.hg-vpn-badge");
      for (var i = 0; i < added.length; i++) added[i].remove();
      if (link) {
        link.removeAttribute("aria-disabled");
        link.setAttribute("tabindex", "0");
        link.removeAttribute("title");
      }
    }
  }

  function showBanner(root, list, show) {
    var banner = root.querySelector("#hg-vpn-banner");
    if (!show) {
      if (banner) banner.remove();
      return;
    }
    if (banner) return;
    banner = document.createElement("div");
    banner.id = "hg-vpn-banner";
    banner.setAttribute("role", "status");
    banner.innerHTML = "<span>🔒</span><span><b>You are outside your home network.</b> Greyed apps only work on the VPN or at home. Turn on the VPN, this page updates by itself.</span>";
    list.parentNode.insertBefore(banner, list);
  }

  function scan() {
    if (!libraryRoot || !libraryRoot.host || !libraryRoot.host.isConnected) libraryRoot = findLibraryRoot(document);
    if (!libraryRoot) return;
    var list = libraryRoot.querySelector('[part="app-list"]');
    if (!list) return;
    addStyle(libraryRoot);
    var cards = list.querySelectorAll('[part="card"],[part="row"]');
    var greyed = 0;
    for (var i = 0; i < cards.length; i++) {
      var link = cards[i].querySelector("a[href]");
      var off = network === "outside" && !!link && isLocalOnly(link.href);
      markCard(cards[i], off);
      if (off) greyed++;
    }
    showBanner(libraryRoot, list, greyed > 0);
  }

  function probe() {
    fetch(PROBE, { method: "HEAD", cache: "no-store", redirect: "manual" }).then(function (r) {
      var next = r.type === "opaqueredirect" ? "home" : networkFromStatus(r.status);
      if (next !== "unknown") network = next;
      scan();
    }).catch(function () {});
  }

  document.addEventListener("click", function (event) {
    var path = event.composedPath();
    for (var i = 0; i < path.length; i++) {
      if (path[i].hasAttribute && path[i].hasAttribute(MARK)) {
        if (path.some(function (n) { return n.tagName === "A"; })) {
          event.preventDefault();
          event.stopImmediatePropagation();
          var banner = libraryRoot && libraryRoot.querySelector("#hg-vpn-banner");
          if (banner) {
            banner.classList.remove("hg-pulse");
            void banner.offsetWidth;
            banner.classList.add("hg-pulse");
            banner.scrollIntoView({ block: "nearest" });
          }
        }
        return;
      }
    }
  }, true);

  probe();
  setInterval(probe, PROBE_EVERY_MS);
  setInterval(scan, SCAN_EVERY_MS);
  window.addEventListener("focus", probe);
  window.addEventListener("online", probe);
})();
