# Copilot / community agents

This repository is the factory: `corp-harness` plus Cursor plugin roles.
Do not move factory voice out of `AGENTS.md`.

## Verify

- `python3 -m pytest -q`
- `python3 -m ruff check src tests`
- `./scripts/harness/verify.sh`
- `./scripts/harness/adversarial.sh` (authorized probes only)

## Never

- Never pass `--actor user`. Only a human records user approval.
- Never self-approve, invent a gate PASS, or type success by hand.
- Never weaken digest binding, skip adversary, or grant agents final approval.
- Never nest the corporate root under the site, or write `program.json` into the site.
- Never edit `src/corp_harness/**` from a product site.

Record gate evidence with `corp-harness check --run`.
Lifecycle: [docs/HOW_IT_WORKS.md](../docs/HOW_IT_WORKS.md).
Factory rules: [AGENTS.md](../AGENTS.md).
