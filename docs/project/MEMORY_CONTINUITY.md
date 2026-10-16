# Memory continuity

Home keeps its existing small native notes, transcript store, optional external provider and stable prompt prefixes. This change adds optional semantic retrieval, explicit private-conversation grants and source controls. It does not enable a provider or alter a personal profile.

## Semantic retrieval

Keyword recall works without configuration or network access. To add semantic retrieval, configure an OpenAI-compatible embedding endpoint in the owning profile:

```yaml
memory:
  home_recall:
    enabled: true
    base_url: https://your-embedding-provider.example/v1
    model: your-embedding-model
    api_key_env: HOME_EMBEDDING_API_KEY
    timeout_seconds: 5
    min_similarity: 0.55
```

Set the default credential through `hermes config set HOME_EMBEDDING_API_KEY` or the profile's secret environment, not YAML. A custom `api_key_env` can reference another existing profile secret. HTTPS is required except for loopback HTTP. Local endpoints can omit a credential. No chat-provider credential is silently borrowed. Changing endpoint or model selects a new embedding space.

Open `/home`, then run `/home index`. Each invocation scans at most 256 message rows and sends at most 32 excerpts/16,000 characters in one request. The batch budget accounts for redaction expansion before dispatch. A single source still over budget is skipped and reported so later sources can advance. Repeat when instructed; a durable cursor reaches later sources. A completed pass starts again on the next explicit invocation, reusing unchanged vectors and refreshing edits. Indexing is explicit: no daemon, model download, recurring job or background transcript upload is installed.

The index holds at most 4,096 source vectors. Source excerpts are capped at 900 characters. `/home index clear` clears derived vectors and indexing cursors, and revokes publication by an in-flight indexing request; it preserves history and source controls. Recall makes at most one query-embedding request and combines semantic and keyword results by reciprocal rank. It keeps Home's eight-excerpt/6,000-character context cap. Invalid responses, unavailable endpoints and optional query failures retain keyword recall. The embedding model and similarity threshold determine relevance; the runtime cannot guarantee semantic accuracy.

Derived vectors live in the existing profile SQLite database. Every result must still match canonical content and current participation. Deletion, edits, exclusion, forgetting and access revocation are rechecked before use. Provider I/O runs outside read transactions; managed workers validate their assignment before and after it. Inputs are redacted in the database owner's profile before egress. Vectors are derived sensitive data: excluding a source prevents retrieval, but is not secure deletion of database pages or backups.

## Private messaging

From a local personal chat, use `/home link <session-id>` to grant an existing private messaging conversation access to Home. `/home links` lists grants; `/home unlink <session-id>` revokes one. Find the session ID through the existing session list/history controls. No messaging conversation participates merely because it shares a username or numeric sender ID with another app.

A grant binds the exact persisted platform, sender, chat, thread, receiving-bot profile, session key and routing scope. The current gateway source must match. Groups, broadcasts, unknown identities, jobs and subagents are excluded. Compression may preserve a grant when its identity is unchanged; a new/reset conversation requires relinking. Profile and local-owner authorization still apply. Grants enable source retrieval as well as replies using Home context; they do not authorize external actions.

## Corrections and forgetting

Home evidence exposes canonical message IDs. Local controls are:

```text
/home supersede <old-message-id> <new-user-message-id>
/home forget <message-id>
/home sources
```

Supersession follows a newer explicit user correction, even if its wording no longer matches the original query. It never substitutes an assistant suggestion as a user fact. Forgetting suppresses the stable source identity, including compression copies, across keyword recall, semantic recall and dream processing. Revocation survives restart and physical message deletion. An unavailable/excluded replacement does not restore its original. Source controls are capped at 10,000; existing controls are never evicted to admit another.

These controls affect future Home retrieval. They do not erase raw transcripts, every independently written paraphrase, native `MEMORY.md`/`USER.md`, external providers, exports or backups. Start a new chat to remove previously loaded context; resuming an old chat retains its old prompt bytes. Native/external memory deletion uses its own controls. This source-level feature does not claim general learned-fact erasure or automatic contradiction detection.

## Learning and compression

Automatic memory/skill review defaults off. An explicit `auxiliary.background_review.enabled: true` preserves opt-in; `/refine` and foreground memory saves remain available. The reviewer may do nothing when there is no durable, supported lesson. Home dreaming remains a separate opt-in with its existing budgets and source gates.

Compression retains its existing transcript persistence and provider-checkpoint hooks. There is no new unattended native-fact extraction call: its quality and cost have not been established. Explicit saves remain the way to curate small always-loaded notes; source-backed Home recall supplies detailed history.

## Evaluation boundary

The regression suite uses synthetic conversations, local HTTP servers and controlled vectors. It covers paraphrase retrieval versus the keyword baseline, distractors, exact matches, correction and revocation, profile/identity isolation, restart, provider errors and prompt-prefix preservation. Controlled vectors verify retrieval mechanics, not a real embedding model's understanding. Live embedding quality, end-to-end answer quality and monetary cost require a disposable configured provider evaluation before choosing defaults or enabling broader automation. No comparison here establishes universal superiority over OpenClaw.
