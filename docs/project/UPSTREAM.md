# Maintaining the Hermes baseline

`UPSTREAM.json` records the source repository and exact imported commit. `LICENSE` and source attribution are retained. Agent and contributor instructions are maintained for this project; historical contribution policy is not a source of authority.

The baseline is a source snapshot without upstream Git history. Git-history investigations described by upstream guidance must use a separate upstream clone at the recorded revision; absence of history here is not evidence of intent.

## Import differences

- Root README, AGENTS, contributor entrypoints, and persona documents describe this project. Duplicate upstream README/AGENTS files were removed; useful engineering guidance lives in `docs/project/ENGINEERING.md`.
- Area instructions retain technical contracts but remove external scope bans and approval requirements. Developer-guide pages are technical references subordinate to project instructions.
- `.github/workflows/` was moved to `.github/upstream-workflows/`, so imported releases, publishing, bot writes, and organization-specific CI do not execute.
- Upstream CODEOWNERS, Dependabot configuration, and issue templates are in `.github/upstream-metadata/`; project issue/PR templates replace them.
- Our foundation workflow and project docs were added. Hermes runtime code and lockfiles were not intentionally changed by the import.
- The starter project's `assets/icon.svg` is retained.

## Updating the baseline

1. Start from a clean tree and identify the recorded base and intended upstream target by full commit SHA.
2. Use a separate upstream clone to inspect the diff, release notes, migrations, dependency changes, and license changes between those revisions.
3. Apply a reviewed three-way source update, preserving this project's changes and inactive automation. Do not replace the entire tree or run an upstream installer/update command against this checkout.
4. Resolve conflicts with current project behavior and run relevant checks/tests. Update the provenance record, engineering documentation, and decision log.

This repository does not yet configure a custom distribution/update channel. Imported installers, updater code, image references, and release links may still target Nous Research. Audit these paths before packaging or public installation instructions; do not claim a Hermes update preserves this fork's changes.
