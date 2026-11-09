#!/usr/bin/env python3
"""Black-box suite for answer-inbox: HTTP API, answers/<token>.json format, wait-for-answer.sh.

  run.py --server-cmd "node legacy/server.js"   start the server twice (normal + unwritable data dir) and test it
  run.py --url http://host:port --data DIR      test an already running server (the write-failure test is skipped)
  --record FILE                                 also write normalised results, to diff old against new
"""
import argparse, http.client, json, os, re, shlex, shutil, signal, socket, stat, subprocess, sys, tempfile, threading, time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
WAIT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'wait-for-answer.sh'))
TS_RE = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
RESULTS = {}
FAILS = []
COUNT = [0]


class Client:
    def __init__(self, url):
        u = urlparse(url)
        self.host, self.port = u.hostname, u.port

    def req(self, method, path, body=None, headers=None, raw=False):
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data


def start(cmd, port, data):
    env = dict(os.environ, PORT=str(port), DATA_DIR=data)
    p = subprocess.Popen(shlex.split(cmd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=os.path.join(HERE, '..', '..'))
    for _ in range(100):
        try:
            socket.create_connection(('127.0.0.1', port), 0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise SystemExit('server did not start: ' + cmd)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def check(name, cond, detail=''):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
        print('FAIL', name, detail)
    else:
        print('ok  ', name)


def norm_file(text):
    d = json.loads(text)
    ok = isinstance(d.get('receivedAt'), str) and TS_RE.match(d['receivedAt'])
    return re.sub(r'"receivedAt": "[^"]*"', '"receivedAt": "<ts>"', text), bool(ok)


def readf(data, token):
    with open(os.path.join(data, token + '.json')) as f:
        return f.read()


def rec(name, status, body, filetext=None):
    RESULTS[name] = {'status': status, 'body': body.decode() if isinstance(body, bytes) else body, 'file': filetext}


def suite(url, data, broken_url=None):
    c = Client(url)

    # --- routing
    s, h, b = c.req('GET', '/health')
    check('health 200', s == 200)
    check('health body', b == b'{"ok":true}', b)
    check('health content-type', h.get('content-type') == 'application/json', h)
    rec('health', s, b)
    for name, m, p in [('health query', 'GET', '/health?x=1'), ('health slash', 'GET', '/health/'), ('post health', 'POST', '/health'),
                       ('get submit', 'GET', '/submit'), ('root', 'GET', '/'), ('put submit', 'PUT', '/submit'),
                       ('delete submit', 'DELETE', '/submit'), ('submit slash', 'POST', '/submit/'), ('submit query', 'POST', '/submit?a=1'),
                       ('unknown', 'GET', '/nope'), ('inbox prefix', 'POST', '/_inbox/submit'), ('head health', 'HEAD', '/health'),
                       ('options submit', 'OPTIONS', '/submit')]:
        s, h, b = c.req(m, p, body='{"token":"routetest1"}' if m in ('POST', 'PUT') else None)
        exp = b'' if m == 'HEAD' else b'{"error":"not found"}'
        check('404 ' + name, s == 404 and b == exp, (s, b))
        rec('404 ' + name, s, b)
    check('no file from 404s', not os.path.exists(os.path.join(data, 'routetest1.json')))

    # --- minimal submit and exact file format
    s, h, b = c.req('POST', '/submit', {'token': 'minimal-01'})
    check('minimal 204', s == 204 and b == b'', (s, b))
    check('204 has no content-type', 'content-type' not in h, h)
    t = readf(data, 'minimal-01')
    n, ok = norm_file(t)
    check('minimal file format', n == '{\n  "token": "minimal-01",\n  "choice": null,\n  "receivedAt": "<ts>"\n}' and ok, t)
    rec('minimal', s, b, n)
    mode = stat.S_IMODE(os.stat(os.path.join(data, 'minimal-01.json')).st_mode)
    check('file mode 0644', mode == 0o644, oct(mode))
    now = time.time()
    check('receivedAt is recent', abs(time.mktime(time.strptime(json.loads(t)['receivedAt'][:19], '%Y-%m-%dT%H:%M:%S')) - time.timezone - now) < 30)

    # --- exact payload as answer.js sends it
    body = {'token': 'fullpay-01', 'choice': 'a', 'choices': [{'choice': 'a', 'label': 'Option A'}, {'choice': 'b', 'label': 'Option B'}],
            'label': 'Option A | Option B', 'note': 'hello\nworld "q" \\ \t'}
    s, h, b = c.req('POST', '/submit', body, {'Content-Type': 'application/json'})
    n, ok = norm_file(readf(data, 'fullpay-01'))
    exp = ('{\n  "token": "fullpay-01",\n  "choice": "a",\n  "choices": [\n    {\n      "choice": "a",\n      "label": "Option A"\n    },\n    {\n      "choice": "b",\n'
           '      "label": "Option B"\n    }\n  ],\n  "label": "Option A | Option B",\n  "note": "hello\\nworld \\"q\\" \\\\ \\t",\n  "receivedAt": "<ts>"\n}')
    check('full payload 204', s == 204)
    check('full payload file format', n == exp and ok, n)
    rec('full', s, b, n)

    # --- field handling
    def one(tok, payload, name):
        s, h, b = c.req('POST', '/submit', payload)
        n, ok = norm_file(readf(data, tok)) if s == 204 else (None, False)
        rec(name, s, b, n)
        return s, json.loads(readf(data, tok)) if s == 204 else None, n
    for i, (val, exp) in enumerate([(0, 0), (False, False), ('', ''), (None, None), ({'x': [1, 2]}, {'x': [1, 2]}), ([1, 'a'], [1, 'a']), (1.5, 1.5), ('ü€😀', 'ü€😀')]):
        tok = 'choice-%02d' % i
        s, d, n = one(tok, {'token': tok, 'choice': val}, 'choice ' + str(i))
        check('choice value %d' % i, s == 204 and d['choice'] == exp, d)
    s, d, n = one('nochoice1', {'token': 'nochoice1', 'label': 'l'}, 'nochoice')
    check('missing choice -> null', d['choice'] is None and list(d) == ['token', 'choice', 'label', 'receivedAt'], d)
    s, d, n = one('wrongtype1', {'token': 'wrongtype1', 'choices': 'x', 'label': 5, 'note': {'a': 1}}, 'wrong types')
    check('wrong-typed choices/label/note dropped', list(d) == ['token', 'choice', 'receivedAt'], d)
    s, d, n = one('emptych-01', {'token': 'emptych-01', 'choices': [], 'label': '', 'note': ''}, 'empty values')
    check('empty array/strings kept', d['choices'] == [] and d['label'] == '' and d['note'] == '', d)
    check('empty array format', '"choices": [],' in n, n)
    s, d, n = one('mixedch-01', {'token': 'mixedch-01', 'choices': [1, 'a', None, [], {}]}, 'mixed choices')
    check('choices array not validated', d['choices'] == [1, 'a', None, [], {}], d)
    s, d, n = one('keyorder-1', {'choices': [{'z': 1, 'a': 2, 'm': 3}], 'token': 'keyorder-1', 'note': 'n', 'choice': 'x', 'label': 'l'}, 'key order')
    check('record key order fixed', list(d) == ['token', 'choice', 'choices', 'label', 'note', 'receivedAt'], list(d))
    check('nested key order kept', n.index('"z"') < n.index('"a"') < n.index('"m"'), n)
    s, d, n = one('extrafield1', {'token': 'extrafield1', 'evil': 'x', 'receivedAt': 'fake'}, 'extra fields')
    check('extra fields ignored, receivedAt server-side', 'evil' not in d and d['receivedAt'] != 'fake', d)
    note = 'x' * 2000
    s, d, n = one('note-2000a', {'token': 'note-2000a', 'note': note + 'EXTRA'}, 'note 2005')
    check('note cut at 2000 chars', d['note'] == note, len(d['note']))
    s, d, n = one('note-2000b', {'token': 'note-2000b', 'note': note}, 'note 2000')
    check('note of exactly 2000 kept', d['note'] == note)
    s, d, n = one('note-uni-01', {'token': 'note-uni-01', 'note': 'ä' * 2001}, 'note unicode')
    check('note cut counts characters', d['note'] == 'ä' * 2000, len(d['note']))
    s, d, n = one('note-raw-01', {'token': 'note-raw-01', 'note': 'ä€ \u2028 <>&'}, 'note raw')
    check('non-ascii written raw', 'ä€' in readf(data, 'note-raw-01') and '\\u' not in readf(data, 'note-raw-01').replace('\\u2028', ''), readf(data, 'note-raw-01'))
    s, d, n = one('dupkey-aaa', {'token': 'dupkey-aaa'}, 'dup base')
    s, h, b = c.req('POST', '/submit', '{"token":"dupkey-xx1","token":"dupkey-xx2"}')
    check('duplicate key: last wins', s == 204 and os.path.exists(os.path.join(data, 'dupkey-xx2.json')) and not os.path.exists(os.path.join(data, 'dupkey-xx1.json')), s)
    s, h, b = c.req('POST', '/submit', '  \n{"token":"white-ws-01"}\n\t ')
    check('surrounding whitespace ok', s == 204 and os.path.exists(os.path.join(data, 'white-ws-01.json')), s)
    s, h, b = c.req('POST', '/submit', '\ufeff{"token":"bom-token-1"}'.encode('utf-8'))
    rec('bom', s, b)
    check('BOM json is invalid', s == 400 and b == b'{"error":"invalid json"}', (s, b))
    s, h, b = c.req('POST', '/submit', '{"token":"esc-tok-\\u0041"}')
    check('escaped token chars decoded then validated', s == 204 and os.path.exists(os.path.join(data, 'esc-tok-A.json')), s)

    # --- content type and encodings
    s, h, b = c.req('POST', '/submit', '{"token":"ctype-text1"}', {'Content-Type': 'text/plain'})
    check('content-type ignored', s == 204)
    s, h, b = c.req('POST', '/submit', '{"token":"ctype-none1"}', {'Content-Type': 'application/x-www-form-urlencoded'})
    check('form content-type still json', s == 204)
    sk = socket.create_connection((c.host, c.port), 5)
    pl = b'{"token":"chunked-001","choice":"z"}'
    sk.sendall(b'POST /submit HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n' + b'%x\r\n' % 10 + pl[:10] + b'\r\n' + b'%x\r\n' % (len(pl) - 10) + pl[10:] + b'\r\n0\r\n\r\n')
    resp = b''
    while True:
        x = sk.recv(4096)
        if not x: break
        resp += x
    sk.close()
    check('chunked upload 204', resp.startswith(b'HTTP/1.1 204'), resp[:40])
    check('chunked file written', json.loads(readf(data, 'chunked-001'))['choice'] == 'z')

    # --- keep-alive: several requests on one connection
    k = http.client.HTTPConnection(c.host, c.port, timeout=5)
    sts = []
    for i in range(5):
        k.request('POST', '/submit', body=json.dumps({'token': 'keepal-%03d' % i}))
        r = k.getresponse(); r.read(); sts.append(r.status)
    k.request('GET', '/health'); r = k.getresponse(); r.read(); sts.append(r.status)
    k.close()
    check('keep-alive connection reused', sts == [204] * 5 + [200], sts)

    # --- invalid json / token
    for name, body in [('empty body', ''), ('garbage', 'not json'), ('truncated', '{"token":"abcdef"'), ('trailing comma', '{"token":"abcdef",}'),
                       ('single quotes', "{'token':'abcdef'}"), ('trailing garbage', '{"token":"abcdef"} x'), ('two objects', '{"token":"abcdef"}{"token":"abcdef"}'),
                       ('nan', '{"token":"abcdef","choice":NaN}')]:
        s, h, b = c.req('POST', '/submit', body)
        rec('json ' + name, s, b)
        check('invalid json: ' + name, s == 400 and b == b'{"error":"invalid json"}' and h.get('content-type') == 'application/json', (s, b))
    for name, body in [('null', 'null'), ('array', '[]'), ('string', '"abcdef"'), ('number', '42'), ('true', 'true'), ('empty object', '{}'),
                       ('token null', {'token': None}), ('token number', {'token': 123456}), ('token array', {'token': ['abcdef']}), ('token object', {'token': {}}),
                       ('token bool', {'token': True}), ('too short', {'token': 'abcde'}), ('empty token', {'token': ''}), ('too long', {'token': 'a' * 65}),
                       ('dot', {'token': 'abc.def'}), ('slash', {'token': 'abc/def'}), ('traversal', {'token': '../../etc/x'}), ('backslash', {'token': 'abc\\defg'}),
                       ('space', {'token': 'abc def'}), ('trailing newline', {'token': 'abcdef\n'}), ('leading newline', {'token': '\nabcdef'}), ('nul', {'token': 'abcdef\u0000'}),
                       ('unicode letter', {'token': 'abcdeé'}), ('fullwidth digit', {'token': 'abcde１'}), ('colon', {'token': 'abc:def'}), ('plus', {'token': 'abc+def'}),
                       ('tilde', {'token': '~abcdef'}), ('uppercase TOKEN key', {'TOKEN': 'abcdef'})]:
        s, h, b = c.req('POST', '/submit', body)
        rec('token ' + name, s, b)
        check('invalid token: ' + name, s == 400 and b == b'{"error":"invalid token"}' and h.get('content-type') == 'application/json', (s, b))
    for name, tok in [('min 6', 'abcdef'), ('max 64', 'a' * 64), ('dash+underscore', 'a-b_c-d_'), ('digits', '0123456789'), ('upper', 'ABCDEF'), ('lead dash', '-abcdef')]:
        s, h, b = c.req('POST', '/submit', {'token': tok})
        rec('valid token ' + name, s, b)
        check('valid token: ' + name, s == 204 and os.path.exists(os.path.join(data, tok + '.json')), s)
    outside = os.path.join(os.path.dirname(data.rstrip('/')), 'etc')
    check('nothing written outside data dir', not os.path.exists(outside))

    # --- overwrite, temp files
    c.req('POST', '/submit', {'token': 'overwrite-1', 'choice': 'first'})
    c.req('POST', '/submit', {'token': 'overwrite-1', 'choice': 'second'})
    check('second submit overwrites', json.loads(readf(data, 'overwrite-1'))['choice'] == 'second')
    time.sleep(0.2)
    check('no temp files left', not [f for f in os.listdir(data) if f.endswith('.tmp')], os.listdir(data))
    check('only .json files written', all(f.endswith('.json') for f in os.listdir(data)))

    # --- size limit
    def padded(n):
        base = b'{"token":"size-limit1"}'
        return base + b' ' * (n - len(base))
    for tok, n in [('size-limit1', 65536)]:
        s, h, b = c.req('POST', '/submit', padded(n))
        check('body of exactly 64 KiB accepted', s == 204, s)
    for name, n in [('64 KiB + 1', 65537), ('1 MiB', 1 << 20), ('8 MiB', 8 << 20)]:
        try:
            s, h, b = c.req('POST', '/submit', b'{"token":"size-over-01"}' + b' ' * (n - 24))
            res = s
        except (ConnectionError, http.client.HTTPException, OSError) as e:
            res = 'closed'
        rec('oversize ' + name, 'closed' if res == 'closed' else res, '')
        check('oversize refused: ' + name, res == 'closed' or (isinstance(res, int) and res >= 400), res)
    check('oversize wrote nothing', not os.path.exists(os.path.join(data, 'size-over-01.json')))
    s, h, b = c.req('GET', '/health')
    check('server alive after oversize', s == 200)
    big_note = 'n' * 60000
    s, h, b = c.req('POST', '/submit', {'token': 'bignote-01', 'note': big_note})
    check('large note under limit accepted and cut', s == 204 and len(json.loads(readf(data, 'bignote-01'))['note']) == 2000)

    # --- slow and half-open clients do not block others
    slow = socket.create_connection((c.host, c.port), 5)
    slow.sendall(b'POST /submit HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{"tok')
    t0 = time.time()
    s, h, b = c.req('POST', '/submit', {'token': 'slowother-1'})
    check('slow client does not block others', s == 204 and time.time() - t0 < 2)
    slow.close()
    sk = socket.create_connection((c.host, c.port), 5)
    sk.sendall(b'GARBAGE\r\n\r\n')
    sk.settimeout(5)
    try:
        r = sk.recv(100)
    except OSError:
        r = b''
    sk.close()
    check('garbage request line -> 400 or close', r == b'' or r.startswith(b'HTTP/1.1 400'), r)
    check('server alive after garbage', c.req('GET', '/health')[0] == 200)

    # --- concurrency
    out = []
    def worker(i):
        s, _, _ = c.req('POST', '/submit', {'token': 'conc-%04d' % i, 'choice': i, 'note': 'x' * 500})
        out.append(s)
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check('60 parallel submits all 204', out.count(204) == 60, out)
    check('60 parallel files valid', all(json.loads(readf(data, 'conc-%04d' % i))['choice'] == i for i in range(60)))
    out = []
    def same(i):
        out.append(c.req('POST', '/submit', {'token': 'sametoken1', 'choice': i, 'note': 'y' * 3000})[0])
    ths = [threading.Thread(target=same, args=(i,)) for i in range(30)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check('30 parallel submits to one token all 204', out.count(204) == 30, out)
    check('one-token file is never partial', 0 <= json.loads(readf(data, 'sametoken1'))['choice'] < 30)
    time.sleep(0.2)
    check('no temp files after concurrency', not [f for f in os.listdir(data) if f.endswith('.tmp')])

    # --- write failure
    if broken_url:
        s, h, b = Client(broken_url).req('POST', '/submit', {'token': 'brokenwr-1'})
        check('unwritable data dir -> 500 write failed', s == 500 and b == b'{"error":"write failed"}' and h.get('content-type') == 'application/json', (s, b))
        rec('write failed', s, b)
        check('health ok with broken data dir', Client(broken_url).req('GET', '/health')[0] == 200)

    # --- wait-for-answer.sh
    td = tempfile.mkdtemp(prefix='wfa-')
    try:
        shutil.copy(WAIT, td + '/wait-for-answer.sh')
        os.symlink(data, td + '/answers')
        p = subprocess.run(['bash', td + '/wait-for-answer.sh', 'fullpay-01', '4'], capture_output=True, text=True, timeout=20)
        check('wait-for-answer prints ANSWER, exit 0', p.returncode == 0 and p.stdout.startswith("ANSWER for token 'fullpay-01'") and '"choice": "a"' in p.stdout, p.stdout)
        tok = 'waitlive-01'
        pr = subprocess.Popen(['bash', td + '/wait-for-answer.sh', tok, '20'], stdout=subprocess.PIPE, text=True)
        time.sleep(1)
        c.req('POST', '/submit', {'token': tok, 'choice': 'live', 'label': 'Live'})
        out, _ = pr.communicate(timeout=20)
        check('wait-for-answer wakes on a live submit', pr.returncode == 0 and '"choice": "live"' in out and json.loads(out.split('\n', 1)[1])['label'] == 'Live', out)
        p = subprocess.run(['bash', td + '/wait-for-answer.sh', 'never-sent-1', '2'], capture_output=True, text=True, timeout=20)
        check('wait-for-answer times out, exit 1', p.returncode == 1 and p.stdout.startswith('TIMEOUT'), p.stdout)
    finally:
        shutil.rmtree(td)


def sigterm_when_full(cmd, data):
    port = free_port()
    p = start(cmd, port, data)
    held = [socket.create_connection(('127.0.0.1', port), 5) for _ in range(160)]
    time.sleep(0.5)
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    check('SIGTERM exits promptly with all connection slots held', time.time() - t0 < 3, round(time.time() - t0, 1))
    for s in held:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server-cmd')
    ap.add_argument('--url')
    ap.add_argument('--data')
    ap.add_argument('--record')
    a = ap.parse_args()
    procs, tmp = [], []
    try:
        if a.server_cmd:
            d = tempfile.mkdtemp(prefix='inbox-data-'); tmp.append(d)
            port, bport = free_port(), free_port()
            procs.append(start(a.server_cmd, port, d))
            procs.append(start(a.server_cmd, bport, '/nonexistent-dir/x'))
            suite('http://127.0.0.1:%d' % port, d, 'http://127.0.0.1:%d' % bport)
            sigterm_when_full(a.server_cmd, d)
        elif a.url and a.data:
            suite(a.url, a.data)
        else:
            ap.error('need --server-cmd or --url and --data')
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM); p.wait()
        for d in tmp:
            shutil.rmtree(d, ignore_errors=True)
    if a.record:
        with open(a.record, 'w') as f:
            json.dump(RESULTS, f, indent=1, sort_keys=True)
    print('\n%d checks, %d failed' % (COUNT[0], len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
