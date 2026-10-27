"""Prototype associative recall: think of what the user did not mention, then look it up.

A fast model turns the request (plus the profile, when available) into short search probes for
past facts that could change the right answer; each probe searches the observation notes by
embedding similarity, and the union of hits is injected. Experimental (Memory v2 research).
"""
import json
import math
import operator
import re
import urllib.request

from llm import complete

_dot = getattr(math, 'sumprod', None) or (lambda a, b: sum(map(operator.mul, a, b)))  # 3.11-safe

PROBES = """Before answering the user, a thoughtful personal assistant asks: what from this person's \
past could change the right answer here, even though they didn't mention it? Think about the people \
involved, health and safety, dates and commitments that could conflict, deadlines and expiries, \
goals and budgets, things that changed, and past experiences that went well or badly.

{profile}Request (today is {date}): {request}

Return JSON only: {{"probes": ["short description of a past fact worth checking", ...]}} with 3 to 6 \
probes, each phrased like the fact itself would be written (e.g. "guest has a food allergy", \
"commitment on May 17", "takes a blood thinner"). Return [] if nothing personal could matter."""


def probes(request, date, *, profile='', model, provider='openai-codex'):
    block = f'What you already know about the user:\n{profile}\n\n' if profile else ''
    text = complete([{'role': 'user', 'content': PROBES.format(profile=block, date=date, request=request)}],
                    model=model, provider=provider)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return [p for p in (json.loads(match.group(0)).get('probes', []) if match else []) if isinstance(p, str)][:6]


def embed(texts, base_url, model):
    vectors = []
    for start in range(0, len(texts), 32):
        body = json.dumps({'model': model, 'input': texts[start:start + 32]}).encode()
        request = urllib.request.Request(base_url.rstrip('/') + '/embeddings', body,
                                         {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read())['data']
        for item in sorted(data, key=lambda d: d['index']):
            norm = math.hypot(*item['embedding']) or 1.0
            vectors.append([x / norm for x in item['embedding']])
    return vectors


def recall(probe_texts, observations, request, *, base_url, model, per_probe=4, limit=16):
    """Top observations for the request and each probe, de-duplicated, best first."""
    if not observations:
        return []
    obs_vectors = embed([o['text'] for o in observations], base_url, model)
    queries = embed([request, *probe_texts], base_url, model)
    best = {}
    for q in queries:
        scored = sorted(((_dot(q, v), i) for i, v in enumerate(obs_vectors)), reverse=True)[:per_probe]
        for score, i in scored:
            best[i] = max(best.get(i, -1.0), score)
    ranked = sorted(best, key=lambda i: -best[i])[:limit]
    return [observations[i] for i in sorted(ranked, key=lambda i: observations[i]['session_date'])]
