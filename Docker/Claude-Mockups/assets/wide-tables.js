// Wide tables: wraps every <table> in a scroll box; on screens wider than 900 px a table that does not fit the text column breaks out to the window width (max 1600 px). Phones keep sideways scrolling.
(() => {
  const css = `.wt-box{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:1em 0}
.wt-box.wt-wide{width:min(96vw,1600px);margin-left:50%;transform:translateX(-50%)}`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  const wrap = () => {
    document.querySelectorAll("table").forEach((t) => {
      if (t.parentElement.classList.contains("wt-box")) return;
      const box = document.createElement("div");
      box.className = "wt-box";
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
    });
  };
  const widen = () => {
    document.querySelectorAll(".wt-box").forEach((box) => {
      box.classList.remove("wt-wide");
      if (window.innerWidth > 900 && box.scrollWidth > box.clientWidth + 4) box.classList.add("wt-wide");
    });
  };
  const run = () => { wrap(); widen(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
  addEventListener("resize", widen);
  window.wideTables = run;
})();
