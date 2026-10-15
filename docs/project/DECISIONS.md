# Decision log

Record durable decisions with date, context, chosen approach, and consequences. Keep alternatives only when they explain a material tradeoff.

## 2026-10-15 — Use Hermes source as the foundation

The user wants to start with Hermes and evolve a polished, proactive harness with excellent context. Import the upstream source into this repository, retaining its license and recording the exact revision in `UPSTREAM.json`. Agents can edit existing execution paths and reuse the upstream test suite directly.

Keep current Python/package/command names until a separate migration is justified. Project documentation distinguishes new direction from existing Hermes behavior. This initial import is a snapshot, without importing upstream Git history; future upstream updates require an explicit reviewed comparison.

## 2026-10-15 — Separate project intent from retained upstream guidance

The root `AGENTS.md` owns this project's goals and working agreement. Technical guidance is consolidated in `docs/project/ENGINEERING.md`; nested guides describe area contracts. Long-term notes live in a small set of project docs, while task-specific private data stays out of Git.

## 2026-10-15 — Start with limited automation

Archive upstream workflows and upstream bot/ownership configuration rather than enabling deployment, publication, or organization-specific runners in a new repository. Enable a minimal read-only foundation check. Full fork lint/test CI is an explicit next milestone, not an implied guarantee of this setup.

## 2026-10-15 — Own all active development instructions

Remove duplicate upstream onboarding and external contribution governance from the active instruction path. Keep technical contracts and truthful source attribution. Core changes, providers, and integrations are allowed when justified by project goals. Normalize area instructions, contribution entrypoints, and persona Markdown without changing code, dependency files, or automation.

## 2026-10-15 — PR babysitting authorizes the review-to-merge loop

The user can invoke “babysit the PR” (including “babbysit”) to authorize review requests, feedback replies, fixes, commits/pushes, monitoring, and merge after current-revision checks and review gates pass. Require a review bot from a different model family or CodeRabbit. Keep the trigger in AGENTS.md and details in PR_BABYSITTING.md. This is an instruction workflow, not an installed review integration or background service.
