// Seerr-style phone bottom bar (Discover, Movies, Series, Audiobooks, Manual interaction, Requests), so books and Seerr feel like one app.
// Phone bar below 1024 px (Seerr's lg), left sidebar from 1024 px; icons are Seerr's own (Heroicons, filled when active). No Manual count: Seerr's count endpoint needs Seerr's session cookie, not reachable from this origin.
(function () {
  var S = "https://requests.holy-grail.ch";
  var LINKS = [
    { label: "Discover", de: "Entdecken", href: S + "/", icon: "M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" },
    { label: "Movies", de: "Filme", href: S + "/discover/movies", icon: "M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 0 1-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-1.5A1.125 1.125 0 0 1 18 18.375M20.625 4.5H3.375m17.25 0c.621 0 1.125.504 1.125 1.125M20.625 4.5h-1.5C18.504 4.5 18 5.004 18 5.625m3.75 0v1.5c0 .621-.504 1.125-1.125 1.125M3.375 4.5c-.621 0-1.125.504-1.125 1.125M3.375 4.5h1.5C5.496 4.5 6 5.004 6 5.625m-3.75 0v1.5c0 .621.504 1.125 1.125 1.125m0 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m1.5-3.75C5.496 8.25 6 7.746 6 7.125v-1.5M4.875 8.25C5.496 8.25 6 8.754 6 9.375v1.5m0-5.25v5.25m0-5.25C6 5.004 6.504 4.5 7.125 4.5h9.75c.621 0 1.125.504 1.125 1.125m1.125 2.625h1.5m-1.5 0A1.125 1.125 0 0 1 18 7.125v-1.5m1.125 2.625c-.621 0-1.125.504-1.125 1.125v1.5m2.625-2.625c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125M18 5.625v5.25M7.125 12h9.75m-9.75 0A1.125 1.125 0 0 1 6 10.875M7.125 12C6.504 12 6 12.504 6 13.125m0-2.25C6 11.496 5.496 12 4.875 12M18 10.875c0 .621-.504 1.125-1.125 1.125M18 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m-12 5.25v-5.25m0 5.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125m-12 0v-1.5c0-.621-.504-1.125-1.125-1.125M18 18.375v-5.25m0 5.25v-1.5c0-.621.504-1.125 1.125-1.125M18 13.125v1.5c0 .621.504 1.125 1.125 1.125M18 13.125c0-.621.504-1.125 1.125-1.125M6 13.125v1.5c0 .621-.504 1.125-1.125 1.125M6 13.125C6 12.504 5.496 12 4.875 12m-1.5 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M19.125 12h1.5m0 0c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h1.5m14.25 0h1.5" },
    { label: "Series", de: "Serien", href: S + "/discover/tv", icon: "M6 20.25h12m-7.5-3v3m3-3v3m-10.125-3h17.25c.621 0 1.125-.504 1.125-1.125V4.875c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125Z" },
    { label: "Audiobooks", de: "Hörbücher", href: "/", solid: "M11.25 4.533A9.707 9.707 0 0 0 6 3a9.735 9.735 0 0 0-3.25.555.75.75 0 0 0-.5.707v14.25a.75.75 0 0 0 1 .707A8.237 8.237 0 0 1 6 18.75c1.995 0 3.823.707 5.25 1.886V4.533ZM12.75 20.636A8.214 8.214 0 0 1 18 18.75c.966 0 1.89.166 2.75.47a.75.75 0 0 0 1-.708V4.262a.75.75 0 0 0-.5-.707A9.735 9.735 0 0 0 18 3a9.707 9.707 0 0 0-5.25 1.533v16.103Z", icon: "M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25", active: true },
    { label: "Manual interaction", de: "Manuell beheben", href: S + "/_manual/", deHref: S + "/_manual/?lang=de", icon: "M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z" },
    { label: "Requests", de: "Anfragen", href: S + "/requests", icon: "M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" }
  ];
  var CSS = "#hg-nav{display:none}.hg-nav-logo{display:none}" +
    "@media (max-width:1023px){" +
    "#hg-nav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:40;background:rgba(31,41,55,.9);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-top:1px solid #4b5563;padding-bottom:env(safe-area-inset-bottom)}" +
    "#hg-nav a{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;height:3.5rem;color:#f3f4f6;text-decoration:none;font:500 10px/1.1 system-ui,sans-serif;text-align:center;padding:0 2px}" +
    "#hg-nav a span{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}" +
    "#hg-nav a svg{width:1.5rem;height:1.5rem}" +
    "#hg-nav a.hg-nav-active{color:#6366f1}" +
    "body{padding-bottom:calc(3.5rem + env(safe-area-inset-bottom))}" +
    "}" +
    "@media (min-width:1024px){" +
    "#hg-nav{display:flex;flex-direction:column;position:fixed;left:0;top:0;bottom:0;width:16rem;z-index:30;box-sizing:border-box;background:linear-gradient(#1f2937 0%,#131928 100%);border-right:1px solid #374151;padding:0 1rem 1rem;overflow-y:auto}" +
    "#hg-nav .hg-nav-logo{display:flex;align-items:center;gap:.75rem;height:7rem;box-sizing:border-box;flex:none;padding:.5rem;color:#f9fafb;font:600 1.5rem/1 Inter,ui-sans-serif,system-ui,sans-serif}" +
    "#hg-nav .hg-nav-logo svg{width:2.5rem;height:2.5rem;flex:none;padding:.5rem;box-sizing:border-box;border-radius:9999px;background:linear-gradient(135deg,#4f46e5,#9333ea);color:#fff}" +
    "#hg-nav a{display:flex;align-items:center;gap:.75rem;margin-top:1rem;padding:.5rem;border-radius:.375rem;color:#fff;text-decoration:none;font:500 1.125rem/1.5rem Inter,ui-sans-serif,system-ui,sans-serif;transition:background .15s}" +
    "#hg-nav .hg-nav-logo+a{margin-top:2rem}" +
    "#hg-nav a:hover,#hg-nav a:focus-visible{background:#374151;outline:none}" +
    "#hg-nav a svg{width:1.5rem;height:1.5rem;flex:none}" +
    "#hg-nav a span{position:static;width:auto;height:auto;overflow:visible;clip:auto;white-space:normal}" +
    "#hg-nav a.hg-nav-active{color:#fff;background:linear-gradient(135deg,#4f46e5,#9333ea)}" +
    "#hg-nav a.hg-nav-active:hover{background:linear-gradient(135deg,#6366f1,#a855f7)}" +
    "html.ib-on #hg-nav{top:var(--ib-h)}" +
    "body{padding-left:16rem}" +
    "}";
  function add() {
    if (document.getElementById("hg-nav") || /^\/(auth|login|init)/.test(location.pathname)) return;
    var de = /^de/i.test(navigator.language || "");
    var style = document.createElement("style");
    style.id = "hg-nav-style";
    style.textContent = CSS;
    document.head.appendChild(style);
    var nav = document.createElement("nav");
    nav.id = "hg-nav";
    var ns = "http://www.w3.org/2000/svg";
    LINKS.forEach(function (l) {
      var label = de ? l.de : l.label;
      var a = document.createElement("a");
      a.href = de && l.deHref ? l.deHref : l.href;
      a.title = label;
      if (l.active) { a.className = "hg-nav-active"; a.setAttribute("aria-current", "page"); }
      var svg = document.createElementNS(ns, "svg");
      var p = document.createElementNS(ns, "path");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
      if (l.solid) { svg.setAttribute("fill", "currentColor"); p.setAttribute("fill-rule", "evenodd"); p.setAttribute("d", l.solid); }
      else { svg.setAttribute("fill", "none"); svg.setAttribute("stroke-width", "1.5"); svg.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); p.setAttribute("d", l.icon); }
      svg.appendChild(p);
      var t = document.createElement("span");
      t.textContent = label;
      a.appendChild(svg); a.appendChild(t);
      nav.appendChild(a);
    });
    var book = LINKS[3], logo = document.createElement("div");
    logo.className = "hg-nav-logo";
    var lsvg = nav.querySelector("a.hg-nav-active svg").cloneNode(true), lt = document.createElement("span");
    lt.textContent = de ? book.de : book.label;
    logo.appendChild(lsvg); logo.appendChild(lt);
    nav.insertBefore(logo, nav.firstChild);
    document.body.appendChild(nav);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
})();
