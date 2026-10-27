"""Drive a real OpenClaw gateway: record sessions via scripted turns, then memory_search.

Env: OPENCLAW_BIN, OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH, OPENCLAW_GATEWAY_TOKEN, and a
PATH whose node satisfies OpenClaw's engine range. Start an isolated gateway first (see README).
python run_openclaw.py <out.json> [--skip-seed]
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from dataset import QUERIES, SESSIONS

OC = os.environ['OPENCLAW_BIN']
OUT = sys.argv[1]
LOG = open(os.path.join(os.environ['OPENCLAW_STATE_DIR'], 'driver.log'), 'a')


def oc(*args, timeout=600):
    t0 = time.perf_counter()
    p = subprocess.run([OC, *args], capture_output=True, text=True, timeout=timeout, check=False)
    LOG.write(f'$ openclaw {" ".join(args)[:200]}\nexit={p.returncode} {time.perf_counter() - t0:.1f}s\n'
              f'{p.stderr[-1500:]}\n')
    LOG.flush()
    return p, time.perf_counter() - t0


def parse_json(text):
    """The first JSON value in CLI output (trailing text ignored), or None."""
    start = min((i for i in (text.find('{'), text.find('[')) if i >= 0), default=-1)
    try:
        return json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else None
    except json.JSONDecodeError:
        return None


if '--skip-seed' not in sys.argv:
    for sid, turns in SESSIONS:
        for role, text in turns:
            if role != 'user':
                continue
            p, secs = oc('agent', '--session-id', sid, '--message', text, '--json', '--timeout', '300')
            print(f'{sid}: exit {p.returncode} in {secs:.1f}s', flush=True)
            if p.returncode != 0:
                sys.exit(f'turn failed for {sid}; see driver.log')

result = {'system': 'openclaw', 'runs': {}}
p, secs = oc('memory', 'index', '--force', '--verbose', timeout=1800)
result['index'] = {'exit': p.returncode, 'seconds': secs, 'stdout_tail': p.stdout[-1500:]}
p, _ = oc('memory', 'status', '--deep', '--json')
result['status'] = parse_json(p.stdout) if p.returncode == 0 else p.stdout[-2000:] + p.stderr[-2000:]


def search(text):
    p, secs = oc('memory', 'search', '--query', text, '--max-results', '10', '--json')
    data = parse_json(p.stdout) if p.returncode == 0 else None
    if not isinstance(data, dict):
        # An empty result here would score as "nothing returned": stop instead of recording it.
        sys.exit(f'memory search failed (exit {p.returncode}) for {text!r}; see driver.log')
    hits, raw = [], []
    for r in data.get('results', []):
        raw.append({k: r.get(k) for k in ('path', 'source', 'score', 'snippet', 'sessionId', 'sessionKey')})
        blob = json.dumps(r)
        sid = next((s for s, _ in SESSIONS if s in blob), None)
        if sid and sid not in hits:
            hits.append(sid)
    return {'hits': hits, 'raw': raw, 'ms': secs * 1000, 'stale': data.get('stale')}


for variant in ('raw', 'kw'):
    result['runs'][f'memory_search/{variant}'] = {
        q['id']: search(q['q'] if variant == 'raw' else q['kw']) for q in QUERIES}
    print('searched', variant, flush=True)

# OpenClaw's per-source deletion: forget the whole session, then re-ask.
p, _ = oc('memory', 'forget', '--session', 's_pin', '--json')
result['forget_report'] = parse_json(p.stdout) if p.returncode == 0 else p.stdout[-1500:] + p.stderr[-1500:]
rows = {}
for q in QUERIES:
    if q['kind'] == 'forget':
        for variant in ('raw', 'kw'):
            rows[f"{q['id']}/{variant}"] = search(q['q'] if variant == 'raw' else q['kw'])
result['runs']['after_forget_session'] = rows
json.dump(result, open(OUT, 'w'), indent=1)
print('wrote', OUT)
