// answer.js — drop-in client for "pick an option, press Confirm, send to Claude".
//
// Include on any mockup page:
//   <link rel="stylesheet" href="/_assets/answer.css">
//   <body data-claude-token="REPLACE_WITH_UNIQUE_TOKEN">
//   ...mark options with  data-choice="a"  (optionally group them in
//      an element carrying  data-options ; add  data-multiselect  to allow many)...
//   <button data-confirm disabled>Confirm</button>
//   <p data-indicator></p>                      <!-- optional live status line -->
//   <textarea data-note></textarea>             <!-- optional free-text note -->
//   <script src="/_assets/answer.js" defer></script>
//
// On Confirm it POSTs to /_inbox/submit (same origin, so the page's basic-auth
// credentials ride along automatically) and shows a "sent" overlay.

(function () {
  'use strict';

  function token() {
    if (window.CLAUDE_ANSWER_TOKEN) return window.CLAUDE_ANSWER_TOKEN;
    var b = document.body;
    return (b && b.dataset && b.dataset.claudeToken) || null;
  }

  function selected() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-choice].selected'));
  }

  function update() {
    var n = selected().length;
    var ind = document.querySelector('[data-indicator]');
    if (ind) ind.textContent = n ? (n + ' selected — press Confirm to send to Claude')
                                  : 'Pick an option, then press Confirm';
    document.querySelectorAll('[data-confirm]').forEach(function (btn) { btn.disabled = n === 0; });
  }

  document.addEventListener('click', function (e) {
    var opt = e.target.closest('[data-choice]');
    if (opt) {
      var container = opt.closest('[data-options]') || opt.parentElement;
      var multi = container && container.dataset && container.dataset.multiselect !== undefined;
      if (!multi && container) {
        container.querySelectorAll('[data-choice]').forEach(function (o) { o.classList.remove('selected'); });
      }
      opt.classList.toggle('selected');
      update();
      return;
    }
    var btn = e.target.closest('[data-confirm]');
    if (btn) { e.preventDefault(); submit(btn); }
  });

  function submit(btn) {
    var tk = token();
    var sel = selected();
    if (!tk || sel.length === 0) return;

    var choices = sel.map(function (el) {
      return { choice: el.dataset.choice, label: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200) };
    });
    var noteEl = document.querySelector('[data-note]');
    var body = {
      token: tk,
      choice: choices[0].choice,
      choices: choices,
      label: choices.map(function (c) { return c.label; }).join(' | '),
      note: noteEl && noteEl.value ? noteEl.value : undefined
    };

    var prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Sending…';

    fetch('/_inbox/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok && r.status !== 204) throw new Error('HTTP ' + r.status);
      sent();
    }).catch(function (err) {
      btn.disabled = false;
      btn.textContent = prev;
      var ind = document.querySelector('[data-indicator]');
      if (ind) ind.textContent = 'Send failed (' + err.message + ') — please try again';
    });
  }

  function sent() {
    var o = document.createElement('div');
    o.className = 'claude-answer-sent';
    o.innerHTML =
      '<div class="claude-answer-card">' +
        '<div class="claude-answer-check">✓</div>' +
        '<h2>Answer sent to Claude</h2>' +
        '<p>You can switch back to Claude now — no need to type anything.</p>' +
      '</div>';
    document.body.appendChild(o);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', update);
  } else {
    update();
  }
})();
