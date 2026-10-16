# Proactivity: research and proposal

Date: 2026-10-15. Status: **approved; steps 0–2 implemented on branch `feature/attention-layer`** (attention store/gate/flush, `/inbox`, cron routing, open loops), off by default. Step 4 (connectors) is implemented as per-source watchers for every connected source (see "Source watchers" below). Steps 3, 5 and 6 remain proposals. Verification is by synthetic tests and a scripted dry run; no live provider or real delivery has been exercised. User docs: `website/docs/user-guide/features/attention.md`.

Implementation notes vs. this proposal: §8 decisions took the recommended defaults (open loops first, level `quiet`, items keep their own delivery target with an optional `attention.deliver` fallback). Open-loop extraction is a separate post-turn auxiliary call, not part of the background-review fork, because the fork must advertise the parent's exact tool surface for cache parity. The store is `<profile>/cron/attention.db` (see DECISIONS.md), and open loops live there too until the Home plan's continuity records exist. Turn-boundary delivery in the target chat (§4.2 step 5) is not implemented: digests are batched by time, and immediate alerts are sent on the next cron tick.

## Goal

An agent that tells you things, asks before doing things, and checks on things without being asked, ideally before you notice the need yourself. It should feel like Muse: useful initiative, rare but well-timed interruptions, and visible control. It should not feel like a notification firehose.

## 1. What the best products actually do

Sources accessed 2026-10-15. Vendor pages describe intended behavior, not measured quality.

| Product | Proactive mechanism | Lesson for us |
| --- | --- | --- |
| **Muse (Meta, Sept 2026)** | Keeps working "on a schedule and in response to relevant events" after the app closes. Reviews finished background work and messages only when a result is "meaningfully new or needs your input"; proactive messages must clear a high bar. Goals tab tracks each goal and its plan. Ideas tab plus proactive suggestions based on goals, patterns and past conversations. Users can say "more", "less" or "off". Out-of-turn messages appear as separate bubbles. An avatar snippet shows current work and an activity log lists actions and permissions. Hard-to-undo actions stop for deterministic approval cards. A Sentinel gates egress, and processes that ingested untrusted content lose autonomous network rights. | Proactivity is a **pipeline**: goal → trigger → work → editorial gate → delivery. Approval cards and taint tracking keep it safe. The visible activity log keeps it trusted. |
| **ChatGPT Pulse (Sept 2025)** | Overnight asynchronous research over chats, memory and opt-in Gmail/Calendar. Produces a finite morning set of ~5–10 cards that expire daily. Thumbs up/down and "curate" requests tune future cards. | A **sleep-time ideation pass** delivered as a bounded, finite digest. Feedback is the tuning signal. |
| **Google CC (Labs, Dec 2025)** | "Your Day Ahead" email built from Gmail, Calendar and Drive. Users steer it by replying, and it has thumbs feedback. | A daily anticipatory brief through a channel the user already reads. |
| **OpenClaw heartbeat** | Periodic main-session turn (default 30 min) that follows a short checklist ("scratch"). `NO_REPLY` or `HEARTBEAT_OK` keeps it silent, `activeHours` sets the window, and delivery defaults to the owner's DM. An empty checklist skips the model call, and per-check schedules move to cron. | Cheap patrol plus a silence token plus active hours. Skip the LLM when there is nothing to check. |
| **LangChain ambient agents / Agent Inbox** | Event-driven agents surface three interaction types: **notify**, **question** and **review** (draft awaiting approval). These live in an inbox, not a chat. | A small, explicit taxonomy of proactive items with durable pending state. |
| **Poke** | Texts first with briefings, alerts and automation results. Reviews mention triage misses and timezone errors. | Channel matters (SMS/chat). Correctness of time and urgency is the product. |
| **Cortana Suggested Reminders (2016–17)** | Detected commitments in sent email ("I'll send it Friday") and reminded the user. | Commitment and open-loop detection is a proven "before you notice" feature. |

## 2. What the research says

- **Decide whether to act before generating the content.** [Horvitz 1999](https://erichorvitz.com/chi99horvitz.pdf) frames every initiative as expected utility: act, ask, or stay silent, weighed against interruption cost, with deferral as an option. The 2026 [Proactive Service Agents](https://arxiv.org/abs/2609.03727) framework formalizes the same choice (silent / ask / assist / act) with interruption, misunderstanding, overreach and privacy costs. It finds that offline classifier accuracy does not predict real benefit, that long-term memory is not a defining condition of proactivity, and that reliable service needs calibrated incremental value, verifiable authorization, recoverable execution and counterfactual evidence.
- **Gate cheaply, then reason.** [Do Proactive Agents Need an LLM to Decide When to Act?](https://arxiv.org/html/2605.30152) reports that a small trigger controller beats LLM triggers on AUC. It is 4–7× faster and raised precision from 15% to 57% at about 97% recall. Keep generation off the monitoring path.
- **Agents over-act.** [ProEvent](https://arxiv.org/abs/2607.17701) (schedules inferred from chats) finds frequent responses when the agent should stay silent, weak handling of cancellations, and only 26.7% correct even for GPT-5.1. [ProactiveBench](https://arxiv.org/abs/2410.12361) reports 66% F1 for its best fine-tuned model. Treat inferred needs as candidates with evidence, never as facts.
- **Agents rarely ask the right question early.** [ATRBench](https://arxiv.org/html/2605.28108) shows frontier agents reach 15–24% on hidden preferences by default and 83–97% when the preference is known. Prompting the agent to "ask more" barely helps: question precision was 6–10%. Asking needs targeting, storage and user control.
- **Timing beats volume.** In a [five-day field study](https://arxiv.org/abs/2601.10253), proactive interventions at task boundaries got 52% engagement, and mid-task ones were dismissed 62% of the time. [Iqbal & Bailey](https://www.interruptions.net/literature/Iqbal-CHI08.pdf) show that deferring to breakpoints reduces frustration and reaction time. In [Need Help?](https://arxiv.org/html/2410.04596v2), a "persistent" high-frequency variant was preferred by only 47% of users, versus 80–90% for the calmer variants.
- **Batch the non-urgent.** A [randomized field experiment](https://communities.springernature.com/posts/batching-notifications-can-improve-attention-well-being-and-productivity) (n=237, Fitz et al. 2019) found that three batches a day improved attention, mood and sense of control. Hourly batching did little, and receiving no notifications at all increased anxiety and FoMO.
- **Unsolicited help can backfire.** Vignette studies ([Harari & Amir](https://arxiv.org/html/2509.09309v1)) find that anticipatory help can feel threatening or reduce perceived competence. Users need a visible "why now", a sense of being in control, and an easy way to say "less of this".
- **Use idle time.** Letta's [sleep-time compute](https://docs.letta.com/guides/agents/sleep-time-agents) runs reflection and reorganization while the user is away, so live turns stay cheap. [Inner Thoughts](https://arxiv.org/abs/2501.00383) keeps a covert thought stream and speaks only when relevance, information gap, impact and urgency justify it.

**Synthesis:** good proactivity rarely comes from a smarter prompt. It comes from durable concerns, cheap sensing, an editorial gate with budgets and timing, a small set of interaction types (inform / ask / propose / alert), explicit authority levels, and feedback.

## 3. What Hermes already has (source-inspected)

Hermes already contains most of the parts. What it lacks is the layer that ties them into one attention policy.

| Capability | Where | Gap for this goal |
| --- | --- | --- |
| Durable scheduler with catch-up, dedup and restart safety | `cron/scheduler.py`, `cron/jobs.py`, `cron/occurrences.py` | Each job decides delivery on its own. There are no global budgets, quiet hours or digests. |
| Change-suppressed monitors (hash diff, no LLM call when unchanged) | `cron/monitor.py` (`monitor_script` / `monitor_url`) | Exactly the "cheap gate" pattern, but limited to cron. |
| Silence token (`[SILENT]`, `NO_REPLY`) | `cron/scheduler.py` `SILENT_MARKER`, `cron/scheduler_prompt.py` | Binary deliver/suppress. There is no "hold for digest". |
| Urgency classifier (aux model scores a batch, emits only items ≥ threshold) | `cron/scripts/classify_items.py` | Usable as a scorer for the gate. |
| Per-job durable notepad (cursors, watermarks) | `cron/notepad.py` | Good state for watches. |
| Webhook-triggered jobs | `hermes_cli/webhook.py`, cron `webhook` routes | Event triggers already exist. |
| One-tap suggestions (accept creates a job; dismiss is latched by dedup key; at most 5 pending) | `cron/suggestions.py`, `/suggestions`, `cron/suggestion_catalog.py` | The "propose" interaction already exists, but only for cron jobs. Its `usage` and `integration` sources have **no producer** yet. |
| 16 automation blueprints (morning brief, important mail, bill renewals, price watch…) | `cron/blueprint_catalog.py`, `tools/blueprints.py` | Content is ready. Onboarding into it is manual. |
| Session heartbeat and `/loop` (idle-only, cache-safe user turns, silent on nothing, self-paced backoff) | `hermes_cli/heartbeat.py`, `hermes_cli/loops.py`, `gateway/run_heartbeat_*.py` | Per-session only. There is no profile-level patrol. |
| `/goal` judge loop with gates and wait barriers | `hermes_cli/goals.py` | Session-scoped. There is no durable, cross-session goal with a plan and check-ins (Muse's Goals tab). |
| Background review fork after each turn (writes memory and skills, cache-safe) | `agent/background_review.py`, `agent/review_idle_queue.py` | The natural place to detect open loops and commitments. Today it only saves memory and skills. |
| Delivery to ~20 platforms, home channel, Bot Chat, push notify, continuable replies | `cron/scheduler_delivery.py`, `gateway/delivery*.py`, `tools/send_message_tool.py` | Fine as transport. |
| Approvals (smart/human/yolo, floors) and clarify | `tools/approval*.py`, `tools/clarify_*` | Fine for "review" items. Needs per-concern grants. |
| Memory in cron runs (`MEMORY.md`/`USER.md` load) | Pinned by `tests/cron/test_cron_memory_contract.py` | `cron/AGENTS.md` still says `skip_memory=True`. **Doc drift to fix.** |
| Profile timezone | `config_defaults.py` `timezone` | Prerequisite for quiet hours. |

## 4. Proposal: an attention layer on top of existing engines

Add **no** second scheduler or memory store. Add one small, profile-owned **attention layer** that every proactive producer feeds:

```
 producers (existing + new)            attention layer (new)                     surfaces
 ─────────────────────────            ───────────────────────────               ─────────────────────
 cron / monitor / webhook ─┐         ┌─► candidate store (state.db)              ┌─► urgent push (home channel,
 heartbeat / loop / goal   ├─ emit ─►│   kind, why_now, sources, urgency,        │    Bot Chat, desktop notify)
 kanban / delegation done  │         │   expiry, dedup_key, concern, action     ├─► digest (≤3/day, finite, expiring)
 open-loop detector  (new) │         └─► gate: rules → budget → timing ─ route ─►├─► inbox: /inbox cards
 anticipation sweep  (new) │             → optional LLM editor                   │    (do it / snooze / dismiss / less)
 nightly ideation    (new) ┘             └─► activity log ("why now")            └─► Home thread out-of-turn bubble
                                    ▲                                                        │
                                    └──────────── feedback (acted / dismissed / less) ◄──────┘
```

### 4.1 Four interaction types

These follow LangChain's notify/question/review pattern, with alert added.

- **inform**: "Your 3pm moved to 4pm; you now overlap with gym." No action needed.
- **ask**: "You mentioned a dentist appointment. Want me to remember you prefer mornings?" Bounded preference acquisition (the ATRBench gap).
- **propose**: "Your passport expires in 5 months and you have a June trip. Want me to find renewal appointments?" A one-tap yes starts the work under a stated grant. Today's cron suggestions become one subtype of this.
- **alert**: a deadline or failure within a short horizon. This is the only type allowed to interrupt outside digests by default.

Every item carries a **why now**, linked sources (message UIDs, job run, URL), a confidence score, an expiry and a dedup key. An item derived from untrusted content (email, web) can **inform or propose**, but never carries authority by itself (the Muse taint principle).

### 4.2 The gate (deterministic first)

The gate checks, in order:

1. **Validity**: not expired, not superseded, source not forgotten or excluded.
2. **Duplicate and novelty**: dedup key plus a content hash. Per-concern cooldown.
3. **Authority**: what the item may do without asking (see 4.4).
4. **Route**:
   - Alert above threshold and inside the horizon → *now*.
   - Inside quiet hours (profile timezone) → hold, unless the user explicitly marked it as a hard alert.
   - Interrupt budget spent (default 3/day) → digest.
   - Otherwise → next digest.
   - Low score → inbox only.
5. **Timing**: deliver at a **turn boundary**. Never push while a turn is running in the target chat. This mirrors heartbeat's idle-only rule.

An **optional LLM editor** runs only on the held batch when composing a digest. It merges, drops stale items and writes the brief. This applies Muse's "meaningfully new" filter at digest time and never per event. All of this works with **zero model calls** on idle ticks.

### 4.3 Producers that make it feel like it gets ahead of you

1. **Open loops** (new, credential-free). After a session or turn, a background-review-style fork extracts candidate commitments and unresolved items: "I need to renew X by Friday", the agent's own promised follow-ups, questions left unanswered, decisions pending. Each is stored with source message UIDs. These are the *same records* as the Home plan's continuity open items ([HOME_THREAD_PLAN.md](HOME_THREAD_PLAN.md) §2), not a parallel store. Near the deadline it becomes a check-in: "Did you renew X? I can find slots." Conservative by design: explicit user statements only at first, and cancellations or "done" supersede the item.
2. **Anticipation sweep** (needs connectors). Calendar and email via the existing `google-workspace` skill or MCP, run as `monitor_script` cron jobs so nothing reaches the LLM when nothing changed. It covers meeting prep, conflicts, travel times, deadlines in mail, and renewals. Urgency comes from `classify_items.py`.
3. **Nightly ideation** (sleep-time). One bounded run in the user's quiet window reviews recent sessions, open loops, concerns and feedback. It produces at most N candidates (Pulse/Muse "Ideas"). These land only in the morning digest.
4. **Concern check-ins**. Durable standing goals and watches (Muse's Goals tab). Each concern links to the cron jobs and kanban tasks that do its work, and the gate enforces a check-in cadence.
5. **Existing producers** are rerouted through the gate as an opt-in: cron results (`deliver` keeps working; add `attention` routing), heartbeat/loop output, kanban/delegation completions, and failure incidents.

### 4.4 Initiative ladder (authority)

| Level | May do without asking | Example |
| --- | --- | --- |
| 0 observe | record only | watch a site silently |
| 1 inform | send to inbox or digest | "price dropped" |
| 2 ask / propose | ask a question, offer a one-tap action | "want me to book?" |
| 3 prepare | reversible, local work: research, drafts, plans | draft the reply and attach it for review |
| 4 act (granted) | reversible external actions explicitly granted per concern, within budget | add a calendar hold |
| 5 irreversible | **always** a human approval card (existing approval flow) | send email, purchase, delete |

A grant has a scope (concern), a budget (runs/day, spend), an expiry and a revocation path. Approval floors in `tools/approval_floors.py` stay authoritative, and the ladder can only lower autonomy below them, never raise it.

### 4.5 Feedback and controls

- One **proactivity dial**: `off` / `quiet` (digests only) / `balanced` (default when enabled: ≤3 interrupts/day plus digests) / `eager`. "Less like this", "never about X" and snooze apply per concern or category and are honored immediately.
- Track delivered → opened → acted / dismissed / ignored per category. Raise thresholds for categories with low engagement; never auto-raise the interrupt budget.
- `/activity` lists every candidate with its gate decision and reason, including suppressed ones. `/inbox` shows pending cards. `/concerns` shows goals and watches, and pause/cancel works everywhere. This is Muse's activity log and avatar snippet.

### 4.6 Invariants we keep

- **Prompt cache**: proactive content enters a conversation only as a labelled user-role message at a turn boundary, the way cron mirrors and heartbeats already do. No system-prompt mutation.
- **Profile scope**: the store lives in a `hermes_state_<topic>.py` sibling. Every producer that runs off-turn binds the owning profile (`gateway/AGENTS.md` § Profile scope).
- **Off by default**: no unsolicited work until the user enables a workflow (project contract). No external messages in tests.
- **Restart, duplicate, retry and cancel** behavior is defined per item before anything is enabled.

## 5. Delivery plan (each step reviewable on its own)

0. **Verify proactive seams** (P0 subset). Isolated `HERMES_HOME`. Run the existing suites for cron monitor/suggestions/silent/delivery, heartbeat, loops and goals. Fix the `cron/AGENTS.md` memory drift. Record results in `CAPABILITIES.md`.
1. **Attention store + gate + inbox + digest** (no LLM). Candidate schema, deterministic gate, quiet hours, budgets, dedup, digest composition (template), `/inbox`, `/activity`, and opt-in `attention` routing for cron results. *Done when* synthetic fixtures show: quiet hours honored, budget enforced, no duplicates across restart, urgent items delivered immediately, the rest batched, and every decision visible with a reason.
2. **First proactive workflow: open loops** (credential-free; P3 candidate). Extraction from explicit user statements, follow-up check-ins, supersede on done or cancel. *Done when* a synthetic multi-session fixture gets correct check-ins with source links, no check-in after cancellation, nothing from excluded chats, and bounded aux cost.
3. **Concerns (standing goals)**. Durable goal plus plan, linked cron/kanban work, check-in cadence, and `/concerns`. This reuses `/goal` judge machinery for "is it done?".
4. **Connectors: anticipation sweep**. Calendar and email monitors through existing skills or MCP plus the classifier. A morning brief built from real data, enabled with blueprints and one tap.
5. **Ideation + feedback learning + ask-to-remember** (≤1 question/day, inside the digest).
6. **Graduated autonomy**. Levels 3–4 with per-concern grants. The LLM editor for digests. Measure before widening defaults.

## 6. How we'll know it's good

Measured on deterministic fixtures first, then on dogfooding:

- **Interrupt precision**: share of immediate pushes the user acts on or rates useful. Target: a majority. Also **missed-needed** items in fixtures.
- **Interrupts per day**, **dismiss rate** per category, and **quiet-hour violations**. Target for quiet-hour violations and duplicate deliveries: 0.
- **Cost**: aux model calls per day and zero calls on idle ticks. Latency from trigger to alert.
- **Inference safety**: no check-in after cancellation or "done"; no invented commitments (ProEvent's failure modes).

## 7. Risks

- **Notification fatigue** is the main way this product fails. Mitigations: budgets, digests, the "less" control, and default `quiet` until the user turns it up.
- **Wrong inferences**: evidence-linked candidates, explicit statements first, and a visible source on every item.
- **Prompt injection via email or web**: untrusted-derived items carry no authority, and irreversible actions always need approval.
- **Privacy**: a connector is opt-in per source. Forget/exclude propagates to candidates (HOME plan §4).
- **Cost creep**: change-hash gating, a single nightly ideation run, and per-concern budgets.

## 8. Decisions needed from the user

1. **Where proactive messages should reach you**: messaging app (Telegram/WhatsApp/Slack…), desktop app, or CLI/TUI only. This determines the delivery surface in step 1.
2. **First workflow after the attention layer**: *open loops from your chats* (recommended: no credentials, demonstrable with fixtures) or *calendar/email anticipation* (needs a Google connection).
3. **Default dial when enabled**: `quiet` (digests only, recommended to start) or `balanced`.
4. **Data sources** you'd connect later (Gmail, Calendar, others).

## Source watchers (step 4, implemented)

The user's direction: proactive across *everything connected*, not one hand-coded integration per app. They also wanted a model in the loop for discovery, because connections are often not set up "on paper".

- **Registry** (`cron/attention_sources.py`). A headless index (no model, at most hourly from the cron tick, off-thread) covers enabled MCP servers, connected apps, the Google Workspace token, himalaya, `gh`, Notion and remindctl. A weekly discovery run (model with the normal cron tools, Wednesdays 03:00) finds the rest, each with recorded evidence, and reports broken connections. User removal is a latch, and discovery never overrides an indexed source.
- **Watchers** (`cron/attention_watch.py`). One cron job per source with only that source's toolsets. It runs outside quiet hours, every 15m to 4h. The run context covers per-kind focus, items already in the inbox, open loops and a read-only/data-not-instructions contract. Output is JSON items with stable keys, so each item is captured separately and deduplicated.
- **Replies have context.** Attention sends are mirrored into the target chat transcript, so a user can answer a "propose" item directly.
- **Dreaming hook (planned).** When the Home dreaming PR lands, a nightly or weekly pass can read dream notes to tailor each source's "look for" list. Dreaming stays tool-less and silent; only the watcher plan changes.
