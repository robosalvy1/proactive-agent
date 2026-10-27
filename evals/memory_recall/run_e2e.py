"""End-to-end LongMemEval answers: the same model answers from different memory contexts.

Systems (``--systems``):
  home      what Home injects today (saved by run_longmemeval.py --save-context)
  obs       the full chronological observation log of the question's history (observe.py)
  obs+home  both
  full      the entire raw history (long-context reference; expensive)
Answers are graded with LongMemEval's official yes/no judge prompts (MIT, Di Wu 2024).
All model calls are cached (llm.py). Run with HERMES_HOME set to a disposable eval profile.

    python run_e2e.py --code-root . --data lme_s.jsonl --contexts lme_ctx.json --out e2e.json \\
        --answer-model gpt-6-luna --observer-model gpt-6-luna --judge-model gpt-6-luna
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading

ap = argparse.ArgumentParser()
ap.add_argument('--code-root', required=True)
ap.add_argument('--data', required=True)
ap.add_argument('--contexts', required=True, help='run_longmemeval.py --save-context output (defines the sample)')
ap.add_argument('--out', required=True)
ap.add_argument('--systems', default='home,obs,obs+home')
ap.add_argument('--provider', default='openai-codex')
ap.add_argument('--answer-model', required=True)
ap.add_argument('--observer-model', required=True)
ap.add_argument('--judge-model', required=True)
ap.add_argument('--batch', type=int, default=6, help='sessions per observer call')
ap.add_argument('--workers', type=int, default=3)
ap.add_argument('--limit', type=int, default=0)
ARGS = ap.parse_args()


def save_json(path, data, **kw):
    """Written whole, then swapped in: an interrupted save keeps the previous file."""
    partial = Path(f'{path}.tmp')
    with open(partial, 'w') as handle:
        json.dump(data, handle, **kw)
    os.replace(partial, path)
sys.path.insert(0, str(Path(ARGS.code_root).resolve()))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm import complete
from observe import observe_batch, render_log, session_key

ANSWER = """You are a personal assistant with long-term memory of your past conversations with the user.
Current date: {date}

{memory}

Question: {question}

Answer from the memory above. Use the dates to reason about time, order, durations and the most \
recent value when facts changed; count carefully across all entries when asked "how many". If the \
memory does not contain the information, say that you don't know rather than guessing. Give a \
short final answer."""


def judge_prompt(task, question, answer, response, abstention):
    # Verbatim from LongMemEval src/evaluation/evaluate_qa.py (MIT License, Copyright (c) 2024 Di Wu).
    if abstention:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
    elif task in ('single-session-user', 'single-session-assistant', 'multi-session'):
        template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
    elif task == 'temporal-reasoning':
        template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
    elif task == 'knowledge-update':
        template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
    elif task == 'single-session-preference':
        template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
    else:
        raise NotImplementedError(task)
    return template.format(question, answer, response)


def load_questions(ids):
    with open(os.path.expanduser(ARGS.data)) as handle:
        return [q for q in map(json.loads, handle) if q['question_id'] in ids]


def observations_for(question, cache, lock):
    sessions = list(zip(question['haystack_session_ids'], question['haystack_dates'], question['haystack_sessions']))
    keyed = [(f'{ARGS.observer_model}:{session_key(*s)}', s) for s in sessions]  # Observations depend on the model.
    with lock:
        todo = [(k, s) for k, s in keyed if k not in cache]
    for start in range(0, len(todo), ARGS.batch):
        chunk = todo[start:start + ARGS.batch]
        found = observe_batch([s for _, s in chunk], model=ARGS.observer_model, provider=ARGS.provider)
        with lock:
            for k, (sid, date, _) in chunk:
                cache[k] = [dict(o, session_date=date) for o in found.get(sid, [])]
    with lock:
        return [o for k, _ in keyed for o in cache[k]]


def memory_for(system, question, context, observations):
    raw = ('Relevant excerpts from past conversations (Home recall):\n' + context) if context else \
        'Relevant excerpts from past conversations (Home recall): none found.'
    log = 'Observations about the user, oldest first:\n' + render_log(observations)
    if system == 'home':
        return raw
    if system == 'obs':
        return log
    if system == 'obs+home':
        return log + '\n\n' + raw
    if system == 'full':
        parts = []
        for sid, date, turns in sorted(zip(question['haystack_session_ids'], question['haystack_dates'],
                                           question['haystack_sessions']), key=lambda s: s[1]):
            parts.append(f'[{date}]\n' + '\n'.join(f"{t['role']}: {t['content']}" for t in turns))
        return 'Full conversation history:\n' + '\n\n'.join(parts)
    raise ValueError(system)


def main():
    saved = json.load(open(os.path.expanduser(ARGS.contexts)))['results']
    if any('context' not in row for row in saved):
        sys.exit(f'{ARGS.contexts} has no saved Home context; rerun run_longmemeval.py with --save-context.')
    contexts = {row['id']: row['context'] for row in saved}
    questions = load_questions(set(contexts))
    if ARGS.limit:
        questions = questions[:ARGS.limit]
    systems = ARGS.systems.split(',')
    out_path = Path(ARGS.out)
    obs_path = out_path.with_suffix('.observations.json')
    cache = json.load(open(obs_path)) if obs_path.exists() else {}
    lock, results = threading.Lock(), []

    def run(question):
        abstention = question['question_id'].endswith('_abs')
        observations = observations_for(question, cache, lock) if any('obs' in s for s in systems) else []
        row = {'id': question['question_id'], 'type': question['question_type'], 'abstention': abstention,
               'observations': len(observations)}
        for system in systems:
            memory = memory_for(system, question, contexts[question['question_id']], observations)
            prompt = ANSWER.format(date=question['question_date'], memory=memory, question=question['question'])
            answer = complete([{'role': 'user', 'content': prompt}], model=ARGS.answer_model, provider=ARGS.provider)
            verdict = complete([{'role': 'user', 'content': judge_prompt(
                question['question_type'], question['question'], question['answer'], answer, abstention)}],
                model=ARGS.judge_model, provider=ARGS.provider)
            row[system] = {'correct': 'yes' in verdict.strip().lower()[:5], 'answer': answer,
                           'memory_chars': len(memory)}
        with lock:
            results.append(row)
            save_json(obs_path, cache)
            save_json(out_path, {'args': vars(ARGS), 'results': results}, indent=1)
            marks = ' '.join(f"{s}={'Y' if row[s]['correct'] else 'n'}" for s in systems)
            print(f"[{len(results)}/{len(questions)}] {row['type']:26} obs={row['observations']:4} {marks}", flush=True)

    with ThreadPoolExecutor(ARGS.workers) as pool:
        list(pool.map(run, questions))


if __name__ == '__main__':
    main()
