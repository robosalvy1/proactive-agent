"""Generate "magic" proactive-recall scenarios with a model from a different family.

A scenario hides facts in passing remarks across dated past conversations, then makes a later
request that never mentions them. A magical assistant brings the relevant facts up unprompted
("your sister is coming Saturday and she's allergic to peanuts"); it does not drag in the
distractors. Output is synthetic and written outside the repository (one JSON per line).

    HERMES_HOME=<eval profile> python magic_generate.py --out magic.jsonl --per-category 4
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import complete

CATEGORIES = {
    'constraint': 'a standing constraint about a person (allergy, diet, mobility, phobia, budget) that must shape a new plan',
    'schedule': 'a dated commitment that conflicts with or affects something the user is now planning',
    'entity': 'a named person/place/thing with history (landlord, mechanic, coworker) that a new task involves without naming',
    'goal': 'an ongoing goal or project (training, studying, saving, recovering) that a new request should account for',
    'changed': 'a fact that changed in a later conversation (moved, switched job, broke up, sold the car) that a new request depends on',
    'outcome': 'a past experience with an outcome (bad reaction, great result, refund, injury) that should change a recommendation',
    'health': 'a medication, condition or treatment that interacts with what the user is now asking about',
    'deadline': 'an expiry or deadline (passport, warranty, lease, visa, membership) that a new plan runs into',
    'gift': 'separately mentioned facts about someone (birthday soon + a hobby or wish) that combine into a thoughtful idea',
    'negative': 'NO hidden fact is relevant: the request is self-contained and every remembered detail would be an intrusion',
}

PROMPT = """You are writing one test scenario for a personal AI assistant's long-term memory.

Category: {category} — {description}.
Scenario seed: {seed}

Write realistic past conversations between ONE user and their assistant, then a later request.
Rules:
- 5 to 7 past sessions over 1–4 months, each 4–8 turns, about everyday topics (cooking, work, \
travel, tech help, fitness, shopping, family). Natural, specific, not robotic.
- Mention each hidden fact ONCE, casually, inside a conversation about a DIFFERENT topic, in the \
user's own words. Never let the assistant summarize or repeat it.
- Include 2–3 distractor facts: personal details that sound related to the request's domain but \
must NOT matter for it.
- The final request is natural and must NOT mention the hidden facts, their people's names, or \
their distinctive words. The user has not thought of the connection.
- For category "negative": include personal details, but the request must be fully self-contained \
so bringing any of them up would be irrelevant or creepy; hidden_facts is [].
- Dates are ISO (YYYY-MM-DD), increasing; the request date is after the last session.

Return JSON only:
{{"category": "{category}", "sessions": [{{"date": "...", "turns": [{{"role": "user", "content": "..."}}, \
{{"role": "assistant", "content": "..."}}]}}], "request": {{"date": "...", "text": "..."}}, \
"hidden_facts": [{{"fact": "...", "session": <0-based index>, "why": "how it should change the answer"}}], \
"distractors": ["..."], "ideal": "one sentence: what an excellent, non-creepy answer does"}}"""

SEEDS = [
    'a busy parent', 'a grad student', 'a nurse working night shifts', 'a freelance designer', 'a retiree',
    'a software engineer who travels', 'a small-business owner', 'a new homeowner', 'a college athlete',
    'someone caring for an elderly parent', 'a teacher', 'a remote worker who just moved cities',
    'a paramedic', 'a startup founder with a toddler', 'a musician who teaches lessons', 'a long-haul trucker',
    'a recently divorced dad', 'a pharmacist', 'a landscape architect', 'an exchange student',
]


def generate(category, index, model, provider):
    seed = SEEDS[(index * 7 + sum(map(ord, category))) % len(SEEDS)]
    text = complete([{'role': 'user', 'content': PROMPT.format(
        category=category, description=CATEGORIES[category], seed=f'{seed} (variant {index})')}],
        model=model, provider=provider)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    scenario = json.loads(match.group(0))
    scenario['id'] = f'{category}-{index}'
    scenario['category'] = category  # Never trust the echoed category.
    return scenario


def valid(s):
    """Reject anything magic_run.py would crash on or score wrongly."""
    try:
        dates = [datetime.fromisoformat(sess['date']) for sess in s['sessions']]
        ok = (len(s['sessions']) >= 4 and isinstance(s['request']['text'], str) and s['request']['text'].strip()
              and datetime.fromisoformat(s['request']['date']) >= max(dates)
              and all(t['role'] in ('user', 'assistant') and isinstance(t['content'], str)
                      for sess in s['sessions'] for t in sess['turns']))
        facts = s.get('hidden_facts') or []
        if s['category'] == 'negative':
            return bool(ok) and not facts
        return bool(ok and facts and all(isinstance(h['fact'], str) and isinstance(h['why'], str)
                                         and 0 <= h['session'] < len(s['sessions']) for h in facts))
    except (KeyError, TypeError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--per-category', type=int, default=4)
    ap.add_argument('--model', default='gpt-6-sol')
    ap.add_argument('--provider', default='openai-codex')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--offset', type=int, default=0, help='variant offset: a different, held-out scenario set')
    args = ap.parse_args()
    jobs = [(c, i) for c in CATEGORIES for i in range(args.offset, args.offset + args.per_category)]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda job: _safe(job, args), jobs))
    good = [s for s in results if s and valid(s)]
    with open(os.path.expanduser(args.out), 'w') as handle:
        handle.writelines(json.dumps(scenario) + '\n' for scenario in good)
    print(f'{len(good)}/{len(jobs)} valid scenarios -> {args.out}')


def _safe(job, args):
    try:
        return generate(*job, args.model, args.provider)
    except (ValueError, KeyError, AttributeError, TypeError, RuntimeError, OSError) as exc:
        # A malformed generation (bad JSON, missing fields) is dropped, not fatal.
        print(f'  {job}: {type(exc).__name__}: {str(exc)[:120]}', flush=True)
        return None


if __name__ == '__main__':
    main()
