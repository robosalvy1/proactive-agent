"""Proactive-recall ("magic") eval: does the assistant bring up what the user didn't think of?

Each scenario (magic_generate.py) is loaded into a fresh disposable Home profile together with
unrelated filler conversations, and the same answer model responds to the final request under
different memory systems. A judge from a different model checks, per hidden fact, whether the
answer used it unprompted, and whether it dragged in distractors or invented memories.

Systems: none | home (what Home injects today) | obs (full observation log) | more via --systems.

    HERMES_HOME=<eval profile> python magic_run.py --code-root . --scenarios magic.jsonl \\
        --filler lme_s.jsonl --out magic_results.json --base-url http://127.0.0.1:18556/v1 \\
        --embed-model sentence-transformers/all-MiniLM-L6-v2 --min-similarity 0.30
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading

ap = argparse.ArgumentParser()
ap.add_argument('--code-root', required=True)
ap.add_argument('--scenarios', required=True)
ap.add_argument('--filler', help='LongMemEval JSONL to borrow unrelated conversations from')
ap.add_argument('--filler-sessions', type=int, default=20)
ap.add_argument('--out', required=True)
ap.add_argument('--systems', default='none,home,obs')
ap.add_argument('--base-url')
ap.add_argument('--embed-model')
ap.add_argument('--min-similarity', type=float, default=0.30)
ap.add_argument('--provider', default='openai-codex')
ap.add_argument('--answer-model', default='gpt-6-luna')
ap.add_argument('--observer-model', default='gpt-6-sol')
ap.add_argument('--judge-model', default='gpt-6-sol')
ap.add_argument('--reflect-model', default='gpt-6-sol')
ap.add_argument('--assoc-model', default='gpt-6-sol')
ap.add_argument('--writer-model', default='gpt-6-sol', help='memory writer for the hermes/openclaw baselines')
ap.add_argument('--workers', type=int, default=3)
ap.add_argument('--embed-batch', type=int, default=8)
ap.add_argument('--rejudge', action='store_true', help='re-grade stored replies (needs stored memory)')
ARGS = ap.parse_args()

ROOT = Path(tempfile.mkdtemp(prefix='magic-'))
os.environ.setdefault('HERMES_HOME', str(ROOT / 'home'))
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm import complete
from observe import observe_batch, render_log, session_key
from reflect import reflect
from hermes_state_home_observations import profile_block
import assoc
import baselines

SYSTEM = """You are the user's personal assistant. You remember past conversations with them; \
relevant memory is provided below when available. Use what you remember when it genuinely \
helps with the current request, the way a thoughtful assistant who knows them would. Do not \
bring up personal details that don't matter for this request, and never invent memories."""

JUDGE = """You grade a personal assistant's reply for proactive use of memory.

Past facts the user did NOT mention in the request, which an excellent reply should account for:
{hidden}
Personal details that are NOT relevant and should not be brought up:
{distractors}
What an excellent reply does: {ideal}

Everything the assistant remembered (the only memory it had):
<<<
{memory}
>>>

User request (date {date}): {request}

Assistant reply:
<<<
{reply}
>>>

Return JSON only:
{{"used": [true/false for each hidden fact in order: true only if the reply handles that specific fact \
the way "why it matters" describes (which can mean correctly AVOIDING something, e.g. not using an \
outdated value); generic advice that merely happens to fit is false], "intrusion": true if the reply \
brings up an irrelevant personal detail or past conversation, "invented": true if the reply \
claims a memory or personal fact that is supported neither by the remembered memory above nor by the request, "notes": "one short sentence"}}"""


def connections(memory, scenario):
    """The product's own per-turn connections step; only the model call is the cached eval client."""
    import hermes_state_home_observations as product

    return product.connections_block(
        None, None, memory, scenario['request']['text'], today=scenario['request']['date'],
        model=lambda block, request, today: complete(product.connect_messages(block, request, today),
                                                     model=ARGS.assoc_model, provider=ARGS.provider))


def epoch(date):
    return datetime.fromisoformat(date).timestamp()


def load_filler():
    if not ARGS.filler or not ARGS.filler_sessions:
        return []
    picked = []
    with open(os.path.expanduser(ARGS.filler)) as handle:
        for line in handle:
            q = json.loads(line)
            for sid, turns in zip(q['haystack_session_ids'], q['haystack_sessions']):
                # Generic chats only: LongMemEval's personal sessions belong to other personas and
                # would blend a second person into this user's memory.
                if sid.split('_')[0] in ('sharegpt', 'ultrachat') and 4 <= len(turns) <= 12:
                    picked.append((f'filler-{len(picked)}', turns))
                if len(picked) >= ARGS.filler_sessions:
                    return picked
    return picked


def history(scenario, filler):
    """[(session id, ISO date, turns)] oldest first; filler interleaved across the same span."""
    sessions = [(f"s{i}", s['date'], s['turns']) for i, s in enumerate(scenario['sessions'])]
    start, end = epoch(sessions[0][1]), epoch(scenario['request']['date'])
    for n, (sid, turns) in enumerate(filler):
        when = datetime.fromtimestamp(start + (end - start) * (n + 0.5) / max(1, len(filler)) * 0.95)
        sessions.append((sid, when.date().isoformat(), turns))
    return sorted(sessions, key=lambda s: s[1])


def home_context(scenario, sessions, profile):
    from hermes_state import SessionDB
    from hermes_state_home import HomeStore
    from hermes_state_home_context import home_context_on
    import hermes_state_home_semantic as semantic

    profile.mkdir(parents=True)
    cfg = 'memory:\n  home_recall:\n    enabled: true\n'
    if ARGS.base_url:
        cfg += (f'    base_url: {ARGS.base_url}\n    model: {ARGS.embed_model}\n    api_key_env: ""\n'
                f'    timeout_seconds: 10\n    min_similarity: {ARGS.min_similarity}\n')
    (profile / 'config.yaml').write_text(cfg if ARGS.base_url else 'memory: {}\n')
    db = SessionDB(profile / 'state.db')
    try:
        home = HomeStore(db).ensure_home()
        for sid, date, turns in sessions:
            db.create_session(sid, 'cli')
            for n, turn in enumerate(turns):
                if turn['content'].strip():
                    db.append_message(sid, turn['role'], turn['content'], timestamp=epoch(date) + 60 * n)
        query = scenario['request']['text']
        plan = None
        if ARGS.base_url:
            semantic.MAX_BATCH = ARGS.embed_batch
            from agent.home_embeddings import load_embedding_config, reset_embedding_health
            for _ in range(2000):
                try:
                    if not semantic.HomeIndex(db).index(home, refresh=False)['more']:
                        break
                except OSError:
                    reset_embedding_health(load_embedding_config(db))
            plan = semantic.prepare_semantic_query(db, home, query)
        with db._read_ctx() as conn:
            context = home_context_on(db, conn, None, home, query, semantic_plan=plan)['context']
        wants = any(x.startswith('product') for x in ARGS.systems.split(','))
        return context, (product_profile(db, scenario) if wants else ('', {}))
    finally:
        db.close()
        shutil.rmtree(profile, ignore_errors=True)


def product_profile(db, scenario):
    """The shipped pipeline on the real Home database: observer batches → validation and the
    poisoning filter → profile fold. Only the model call is swapped for the cached eval client."""
    import time

    import hermes_state_home_observations as product

    later = time.time() + 86400
    store = product.Observations(db)
    observe = lambda batch: complete(product.observe_messages(batch), model=ARGS.observer_model, provider=ARGS.provider)
    fold = lambda previous, notes, today: complete(product.profile_messages(previous, notes, today),
                                                  model=ARGS.reflect_model, provider=ARGS.provider)
    while store.observe_once(model=observe, now=later, manual=True) is not None:
        pass
    store.refresh_profile(model=fold, now=later, min_new=1, today=scenario['request']['date'])
    with db._read_ctx() as conn:  # Exactly what the product injects at session start, on the request's date.
        block = store.session_block_on(conn, today=scenario['request']['date'])
        current = store.current_on(conn)
        keyword = store.recall_on(conn, scenario['request']['text'])
        all_notes = store.notes_text_on(conn, today=scenario['request']['date'])
    semantic = []
    if ARGS.base_url and current:
        import math
        vectors = assoc.embed([o['text'] for o in current], ARGS.base_url, ARGS.embed_model)
        query = assoc.embed([scenario['request']['text']], ARGS.base_url, ARGS.embed_model)[0]
        ranked = sorted(range(len(current)), key=lambda i: -math.sumprod(query, vectors[i]))[:8]
        semantic = [current[i] for i in sorted(ranked)]
    fmt = lambda rows: '\n'.join(f"- {o['text']}" for o in rows)
    return block, {'kw': fmt(keyword), 'sem': fmt(semantic), 'all': all_notes}


def observations(sessions, cache, lock):
    keyed = [(session_key(sid, date, turns), (sid, date, turns)) for sid, date, turns in sessions]
    with lock:
        todo = [(k, s) for k, s in keyed if k not in cache]
    for start in range(0, len(todo), 6):
        chunk = todo[start:start + 6]
        found = observe_batch([s for _, s in chunk], model=ARGS.observer_model, provider=ARGS.provider)
        with lock:
            for k, (sid, date, _) in chunk:
                cache[k] = [dict(o, session_date=date) for o in found.get(sid, [])]
    with lock:
        return [o for k, _ in keyed for o in cache[k]]


def memory_block(system, context, obs, profile='', assoc_hits=(), product_text='', check='', notes=None, connect=''):
    notes = notes or {}
    if system == 'none':
        return ''
    excerpts = ('Relevant excerpts from past conversations:\n' + context) if context else ''
    if system == 'profile':
        return profile_block(profile)
    if system == 'product':
        return product_text
    if system == 'product+connect':
        return product_text + ('\n\n' + connect if connect else '')
    if system in ('product+kw', 'product+sem'):
        found = notes.get(system.split('+')[1], '')
        return product_text + ('\n\n## Related notes from past conversations (Home memory; fallible)\n' + found if found else '')
    if system == 'product+check':
        return product_text + ('\n\n' + check if check else '')
    if system.endswith('assoc'):
        notes = '\n'.join(f"[{o['session_date']}] {o['text']}" for o in assoc_hits)
        recalled = 'Recalled notes that may matter for this request:\n' + notes if notes else ''
        if system == 'assoc':
            return recalled
        return profile_block(profile) + ('\n\n' + recalled if recalled else '')
    if system == 'profile+home':
        return profile_block(profile) + ('\n\n' + excerpts if excerpts else '')
    if system == 'home':
        return ('Memory (excerpts from past conversations):\n' + context) if context else ''
    if system == 'obs':
        return 'Memory (observations about the user, oldest first):\n' + render_log(obs)
    raise ValueError(system)


def judge(scenario, reply, memory=''):
    hidden = '\n'.join(f"{i + 1}. {h['fact']} (why it matters: {h['why']})"
                       for i, h in enumerate(scenario.get('hidden_facts', []))) or '(none: nothing should be brought up)'
    prompt = JUDGE.format(hidden=hidden, distractors='\n'.join('- ' + d for d in scenario.get('distractors', [])),
                          ideal=scenario.get('ideal', ''), date=scenario['request']['date'],
                          request=scenario['request']['text'], reply=reply, memory=memory or '(no memory)')
    text = complete([{'role': 'user', 'content': prompt}], model=ARGS.judge_model, provider=ARGS.provider)
    verdict = json.loads(re.search(r'\{.*\}', text, re.DOTALL).group(0))
    used = [bool(u) for u in verdict.get('used', [])][:len(scenario.get('hidden_facts', []))]
    clean = not verdict.get('intrusion') and not verdict.get('invented')
    magic = clean and (all(used) and len(used) == len(scenario.get('hidden_facts', [])))
    return {'used': used, 'intrusion': bool(verdict.get('intrusion')), 'invented': bool(verdict.get('invented')),
            'magic': magic, 'notes': verdict.get('notes', '')}


def rejudge():
    out = Path(ARGS.out)
    data = json.load(open(out))
    scenarios = {s['id']: s for s in map(json.loads, open(os.path.expanduser(ARGS.scenarios)))}

    def one(row):
        for system in ARGS.systems.split(','):
            entry = row.get(system)
            if not entry:
                continue
            memory = entry.get('memory')
            if memory is None:
                memory = row.get('product_text', '') if system == 'product' else '' if system == 'none' else None
            if memory is None:
                continue  # Older result without its memory: cannot be re-graded faithfully.
            entry.update(judge(scenarios[row['id']], entry['reply'], memory), memory=memory)
    with ThreadPoolExecutor(ARGS.workers) as pool:
        list(pool.map(one, data['results']))
    json.dump(data, open(out, 'w'), indent=1)


def main():
    if ARGS.rejudge:
        return rejudge()
    scenarios = [json.loads(line) for line in open(os.path.expanduser(ARGS.scenarios))]
    filler = load_filler()
    systems = ARGS.systems.split(',')
    out = Path(ARGS.out)
    obs_path = out.with_suffix('.observations.json')
    cache = json.load(open(obs_path)) if obs_path.exists() else {}
    results = json.load(open(out))['results'] if out.exists() else []
    done = {(r['id']) for r in results}
    lock = threading.Lock()
    def prepare(item):
        n, scenario = item
        sessions = history(scenario, filler)
        context, (product_text, notes) = home_context(scenario, sessions, ROOT / f'p{n}') \
            if 'home' in systems or any(x.startswith('product') for x in systems) else ('', ('', {}))
        product_text = (product_text, notes)
        return scenario, sessions, context, product_text

    todo = [(n, s) for n, s in enumerate(scenarios) if s['id'] not in done]
    with ThreadPoolExecutor(ARGS.workers) as pool:  # One database per scenario: safe to overlap.
        prepared = list(pool.map(prepare, todo))

    def run(item):
        scenario, sessions, context, (product_text, notes) = item
        eval_obs = {'obs', 'profile', 'profile+home', 'assoc', 'profile+assoc'}
        obs = observations(sessions, cache, lock) if eval_obs & set(systems) else []
        profile = reflect(obs, model=ARGS.reflect_model, provider=ARGS.provider,
                          as_of=scenario['request']['date']) if any(s.startswith('profile') for s in systems) else ''
        assoc_hits, probe_texts = [], []
        if any(s.endswith('assoc') for s in systems):
            probe_texts = assoc.probes(scenario['request']['text'], scenario['request']['date'],
                                       profile=profile if 'profile+assoc' in systems else '',
                                       model=ARGS.assoc_model, provider=ARGS.provider)
            assoc_hits = assoc.recall(probe_texts, obs, scenario['request']['text'],
                                      base_url=ARGS.base_url, model=ARGS.embed_model)
        check = connections(product_text, scenario) if 'product+check' in systems and product_text else ''
        if 'product+connect' in systems and product_text:
            full = product_text + ('\n\n## All notes from past conversations\n' + notes['all'] if notes.get('all') else '')
            connect = connections(full, scenario)
        else:
            connect = ''
        row = {'id': scenario['id'], 'category': scenario['category'], 'observations': len(obs), 'check': check, 'connect': connect,
               'home_context_chars': len(context), 'profile_text': profile, 'product_text': product_text,
               'probes': probe_texts}
        for system in systems:
            if system in ('hermes', 'openclaw'):
                common = dict(system=SYSTEM, writer_model=ARGS.writer_model, answer_model=ARGS.answer_model,
                              provider=ARGS.provider)
                if system == 'hermes':
                    reply, memory = baselines.hermes(scenario, sessions, ROOT / f"hermes-{scenario['id']}", **common)
                else:
                    reply, memory = baselines.openclaw(scenario, sessions, base_url=ARGS.base_url,
                                                       embed_model=ARGS.embed_model, **common)
                row[system] = {'reply': reply, 'memory': memory, **judge(scenario, reply, memory)}
                continue
            memory = memory_block(system, context, obs, profile, assoc_hits, product_text, check, notes, connect)
            messages = [{'role': 'system', 'content': SYSTEM + ('\n\n' + memory if memory else '')},
                        {'role': 'user', 'content': f"(Today is {scenario['request']['date']}.)\n"
                                                    + scenario['request']['text']}]
            reply = complete(messages, model=ARGS.answer_model, provider=ARGS.provider)
            row[system] = {'reply': reply, 'memory': memory, **judge(scenario, reply, memory)}
        with lock:
            results.append(row)
            json.dump(cache, open(obs_path, 'w'))
            json.dump({'args': vars(ARGS), 'results': results}, open(out, 'w'), indent=1)
            marks = ' '.join(f"{s}={'M' if row[s]['magic'] else ('i' if row[s]['intrusion'] else '-')}"
                             f"{sum(row[s]['used'])}/{len(row[s]['used'])}" for s in systems)
            print(f"[{len(results)}] {row['id']:14} {marks}", flush=True)

    with ThreadPoolExecutor(ARGS.workers) as pool:
        list(pool.map(run, prepared))
    shutil.rmtree(ROOT, ignore_errors=True)


if __name__ == '__main__':
    main()
