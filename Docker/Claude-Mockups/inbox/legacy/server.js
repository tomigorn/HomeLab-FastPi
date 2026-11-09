// answer-inbox — a tiny, dependency-free HTTP server.
//
// Receives a single selection from a mockup page and writes it to disk so that
// Claude (running on the host) can read the answer without the user retyping it
// in the terminal. Reachable only from the Caddy container over the internal
// network; the whole site is already behind basic auth, so POSTs carry the
// browser's cached credentials automatically.
//
//   POST /submit   { token, choice, choices?, label?, note? }  ->  204
//   GET  /health                                               ->  200

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 8080);
const DATA_DIR = process.env.DATA_DIR || '/data';
const TOKEN_RE = /^[A-Za-z0-9_-]{6,64}$/; // also blocks path traversal
const MAX_BODY = 64 * 1024;

function json(res, code, body) {
  if (code === 204) { res.writeHead(204); res.end(); return; }
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return json(res, 200, { ok: true });
  }

  if (req.method === 'POST' && req.url === '/submit') {
    let data = '';
    let aborted = false;
    req.on('data', (chunk) => {
      data += chunk;
      if (data.length > MAX_BODY) { aborted = true; req.destroy(); }
    });
    req.on('end', () => {
      if (aborted) return;

      let payload;
      try { payload = JSON.parse(data); }
      catch { return json(res, 400, { error: 'invalid json' }); }

      const token = payload && payload.token;
      if (typeof token !== 'string' || !TOKEN_RE.test(token)) {
        return json(res, 400, { error: 'invalid token' });
      }

      const record = {
        token,
        choice: payload.choice ?? null,
        choices: Array.isArray(payload.choices) ? payload.choices : undefined,
        label: typeof payload.label === 'string' ? payload.label : undefined,
        note: typeof payload.note === 'string' ? payload.note.slice(0, 2000) : undefined,
        receivedAt: new Date().toISOString(),
      };

      const file = path.join(DATA_DIR, token + '.json');
      const tmp = `${file}.${process.pid}.tmp`;
      try {
        fs.writeFileSync(tmp, JSON.stringify(record, null, 2));
        fs.renameSync(tmp, file); // atomic publish — Claude never sees a partial file
      } catch {
        return json(res, 500, { error: 'write failed' });
      }
      return json(res, 204);
    });
    return;
  }

  json(res, 404, { error: 'not found' });
});

server.listen(PORT, () => console.log(`answer-inbox listening on :${PORT}, writing to ${DATA_DIR}`));
