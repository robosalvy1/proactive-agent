"""Score ranked session hits: python score.py result.json [...] > table"""
import json
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from dataset import QUERIES

BY_ID = {q['id']: q for q in QUERIES}


def rank(hits, sid):
    return hits.index(sid) + 1 if sid in hits else None


def score_run(rows):
    out = {}
    for kind in ('exact', 'paraphrase', 'correction'):
        qs = [q for q in QUERIES if q['kind'] == kind and q['id'] in rows]
        if not qs:
            continue
        ranks = [rank(rows[q['id']]['hits'], q['gold']) for q in qs]
        out[kind] = {
            'n': len(qs),
            'hit@1': sum(1 for r in ranks if r == 1) / len(qs),
            'hit@3': sum(1 for r in ranks if r and r <= 3) / len(qs),
            'hit@8': sum(1 for r in ranks if r and r <= 8) / len(qs),
            'mrr': sum(1 / r for r in ranks if r) / len(qs),
            'missed': [q['id'] for q, r in zip(qs, ranks) if not r or r > 8],
        }
        if kind == 'correction' or any('stale' in q for q in qs):
            stale_q = [q for q in qs if 'stale' in q]
            ok = 0
            for q in stale_q:
                g, s = rank(rows[q['id']]['hits'], q['gold']), rank(rows[q['id']]['hits'], q['stale'])
                ok += bool(g and (s is None or g < s))
            out[kind]['newer_above_stale'] = f'{ok}/{len(stale_q)}'
            out[kind]['stale_returned'] = sum(1 for q in stale_q if q['stale'] in rows[q['id']]['hits'])
    neg = [q for q in QUERIES if q['kind'] == 'negative' and q['id'] in rows]
    if neg:
        counts = [len(rows[q['id']]['hits']) for q in neg]
        out['negative'] = {'n': len(neg), 'any_returned': sum(1 for c in counts if c) / len(neg),
                           'avg_sessions_returned': statistics.mean(counts)}
    fq = [q for q in QUERIES if q['kind'] == 'forget' and q['id'] in rows]
    if fq:
        out['forget'] = {'found': sum(1 for q in fq if q['forbidden'] in rows[q['id']]['hits']), 'n': len(fq)}
    ms = [r['ms'] for r in rows.values() if 'ms' in r]
    if ms:
        out['latency_ms'] = {'median': statistics.median(ms), 'max': max(ms)}
    return out


if __name__ == '__main__':
    report = {}
    for path in sys.argv[1:]:
        data = json.load(open(path))
        for name, rows in data['runs'].items():
            if all('/' in k for k in rows):  # forget variants keyed id/variant
                continue
            report[f"{data['system']}:{name}"] = score_run(rows)
    print(json.dumps(report, indent=1))
