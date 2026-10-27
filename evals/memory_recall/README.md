# Home memory recall eval

Retrieval benchmark for Home memory (Memory v2 Phase 0). It seeds identical synthetic personal history into each system and records the ranked chats each one would surface. The retrieval runs use no model; the proactive-recall eval below calls a hosted model through a disposable eval profile. Nothing here uses a personal profile or real transcripts.

## Dataset (`dataset.py`)

31 synthetic chats (gold facts, later corrections, distractors with overlapping vocabulary, chit-chat, and one secret to forget) and 35 queries:

| kind | n | passes when |
|---|---|---|
| exact | 10 | the gold chat is returned (shares distinctive terms with the fact) |
| paraphrase | 13 | the gold chat is returned despite little or no word overlap |
| correction | 4 | the newer statement ranks above the older one it replaces |
| forget | 2 | after forgetting, nothing from the forgotten chat is returned |
| negative | 6 | never discussed; ideally nothing is returned or injected |

Each query also has `kw`: the search string a model would plausibly write when calling a search tool, written from the question. Three paraphrase strings (`p_lens`, `p_allergy`, `p_wifi`) include plausible expansions that also appear in the gold chat (lens, allergy, birthday, guest network), which favors the tool-based baselines on those queries. Tool-based systems are scored on both forms.

## Running

Embeddings come from `embed_server.py`, a loopback OpenAI-compatible server. Run it in its own disposable venv, never a Hermes environment:

```bash
python -m venv /tmp/emb && /tmp/emb/bin/pip install fastembed
/tmp/emb/bin/python evals/memory_recall/embed_server.py 18555 BAAI/bge-small-en-v1.5
```

Then, with the test interpreter (`.venv/bin/python`):

```bash
.venv/bin/python evals/memory_recall/run_home.py ours --code-root . --out ours.json \
    --base-url http://127.0.0.1:18555/v1 --model BAAI/bge-small-en-v1.5
.venv/bin/python evals/memory_recall/run_home.py upstream --code-root /path/to/upstream-hermes --out upstream.json
# The scale result below used all-MiniLM-L6-v2 at 0.30: serve that model (embed_server.py 18556
# sentence-transformers/all-MiniLM-L6-v2) to reproduce it.
.venv/bin/python evals/memory_recall/run_scale.py --code-root . --out scale.json \
    --base-url http://127.0.0.1:18556/v1 --model sentence-transformers/all-MiniLM-L6-v2 \
    --min-similarity 0.30 --filler 6000
.venv/bin/python evals/memory_recall/score.py ours.json upstream.json
```

`run_openclaw.py` drives a real, isolated OpenClaw gateway whose model provider is the same server's scripted chat endpoint, so OpenClaw records the history through its own turn loop. It is slow (about 10–80 s per turn). Set `OPENCLAW_BIN`, `OPENCLAW_STATE_DIR`, `OPENCLAW_CONFIG_PATH` and `OPENCLAW_GATEWAY_TOKEN`; the config needs `memory.search.provider: "openai-compatible"` pointing at the server, `experimental.sessionMemory: true` and `sources: ["memory", "sessions"]`.

## Baseline (2026-10-20, bge-small-en-v1.5, before Memory v2)

Session-level hits; "top 8" matches Home's injection cap.

| System | exact top 8 | paraphrase top 1 / top 8 | newer correction first | negatives returning anything | forget removes it |
|---|---|---|---|---|---|
| Upstream `session_search`, model keywords | 100% | 23% / 23% | 1/4 | 1/6 | delete chat only |
| Upstream `session_search`, raw question | 90% | 0% / 38% | 0/4 | 6/6 | — |
| Home keyword | 100% | 0% / 8% | 0/4 | 1/6 | — |
| Home hybrid (min_similarity 0.55) | 100% | 46% / 100% | 0/4 (4/4 after `/home supersede`) | 1/6 | no: assistant echo remains |
| OpenClaw 2026.10.5 `memory_search`, raw | 100% | 46% / 100% | 0/4 | 6/6 | yes (session-level) |
| OpenClaw, model keywords | 100% | 85% / 100% | 1/4 | 6/6 | yes |

Scale, all-MiniLM-L6-v2 at min_similarity 0.30, 6,000 older messages followed by the dataset: before v2, indexing needed 128 manual `/home index` runs (about 9.5 minutes) and stopped at the 4,096-vector cap with **0 of 31** dataset chats indexed. Paraphrase recall fell to the keyword baseline (8%), with a 555 ms median recall latency.

The default 0.55 threshold is model-dependent. With MiniLM, paraphrase top-8 recall was 23% at 0.55 and 92% at 0.30.

## Limits

Small synthetic set, single runs, session-level scoring. The `kw` strings are hand-written. OpenClaw latency is CLI process time and is not comparable. End-to-end answer quality and cost need a disposable configured provider and are not measured here.

## Proactive recall ("magic") eval

`magic_generate.py` asks a model from a different family (GPT-6.1 Sol in our runs) to write scenarios in ten categories: a fact mentioned in passing in one of several dated past conversations (an allergy, a conflicting commitment, a medication, an expiring lease, a person described indirectly, a friend's birthday and wish…) and a later request that never mentions it, plus distractors and negatives where nothing personal should be raised. `magic_run.py` hides each scenario among 20 generic LongMemEval chats (ShareGPT/UltraChat only; personal haystack sessions belong to other personas) in a disposable Home profile and has the same answer model reply under each memory system. A judge (GPT-6 Sol), shown the memory the assistant had, scores each hidden fact as used or not and flags irrelevant personal details and invented memories. "Magic" means every hidden fact used with no intrusion or invention. `product` runs the shipped observer → profile pipeline on the real database with only the model call swapped for a cached client. Run with `HERMES_HOME` pointing at a disposable eval profile that holds the model credential; scenario files stay outside the repository.

Results (GPT-6 Luna answering; generated sets of 26–38 scenarios with hidden facts, 3–4 negatives each; v3–v5 were generated after the design they test was fixed):

| Memory | v1 | v2 | v3 | v4 | v5 (confirmation) | pooled (138) |
|---|---|---|---|---|---|---|
| none | 3% | 0% | 0% | 0% | — | — |
| Home excerpts today | 18% | 26% | 20% | 12% | 19% | ~19% |
| observations → profile (`product`) | 68% | 70% | 72% | 73% | 69% | **70%** |
| + per-turn connections over all observations (`product+connect`) | 88% | 85% | 80% | 85% | 77% | **83%** |

No invented memories with connections; every negative clean (16/16).

Model choice for the background route (observer, reflector and per-turn check) mattered more than any prompt change. On two fresh sets generated after the design was fixed, with GPT-6 Sol on all three background roles:

| Memory | v6 | v7 | both (54) |
|---|---|---|---|
| Home excerpts today | 19% | 26% | ~22% |
| profile only | 81% | 63% | 72% |
| profile + per-turn connections | 89% | 96% | **93%** (50/54) |
| upstream Hermes (`hermes`) | 41% | 56% | 48% (26/54) |
| OpenClaw 2026.10.5 (`openclaw`) | 52% | 44% | 48% (26/54) |

The two baselines (`baselines.py`) replay each system's own memory design with the same answer model, filler and judge, and are deliberately generous: GPT-6 Sol writes their memory after every past chat. Hermes runs its real background memory review prompt and `memory` tool (1,375/2,200-character stores), then answers with the frozen snapshot and the real `session_search`; upstream reviews only every 10 user turns, so short chats would usually save nothing. OpenClaw follows the default AGENTS.md memory section (daily notes, USER.md, MEMORY.md), then answers with those bootstrap files, its "Memory Recall" guidance and a hybrid `memory_search` over memory files and session transcripts; dreaming is not simulated. Both caught single salient facts (allergies, medications) but rarely connected a request to a fact it did not resemble: schedule conflicts 1/12 combined, gift ideas 2/12, entity resolution 3/12 (ours: 6/6, 5/6, 4/6). Neither invented anything; each had one intrusion.

One invented detail in 54 answers, no intrusions, every negative clean. With GPT-5.6 Luna in those roles the same v6 set scored 63% / 74%; swapping only the check model gave 67% (GPT-6 Luna), 74% (GPT-5.6 Luna) and 78% (GPT-6 Sol), so most of the gain comes from a stronger observer writing down the right details. GPT-6 Sol answering the profile on v3: 76%. Variants that did not hold up: connections over the profile only (85–88% on its tuning sets, 72% on v3), a "Keep in mind" profile section (54% vs 73% on v4), and per-turn keyword or embedding-matched observations (72% / 69% pooled). With 25–35 scenarios per set, single-set differences of a few points are noise; decide on pooled or fresh sets.
