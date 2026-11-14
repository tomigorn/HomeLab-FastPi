const USUAL = __COUNTDOWN__;
function fmtWait(s){ s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
function showWait(s){
  const late = s > USUAL;
  document.getElementById('count').textContent = fmtWait(s);
  document.getElementById('fill').style.width = (late || USUAL <= 0 ? 100 : Math.min(95, Math.floor(s * 100 / USUAL))) + '%';
  document.getElementById('longer').hidden = !late;
}
