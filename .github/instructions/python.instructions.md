---
applyTo: "**/*.py"
---

# Python coding standards (September 2026)

- Type-annotate public functions and module-level APIs.
- Follow the existing Ruff / pyproject configuration. Do not disable rules repository-wide to land a change.
- Tests use pytest and the existing `tests/` layout.
- Never print, log, or commit secrets, `.env` values, or private keys.
- Do not claim a gate passed from prose. Run the documented verify command and keep the output.

## This repository

- This is the factory CLI (`corp-harness`) plus Cursor plugin roles.
- Never pass `--actor user`. Only a human records user approval.
- Never self-approve, invent a gate PASS, or type success by hand.
- Record evidence with `corp-harness check --run`.
- Product sites must not edit `src/corp_harness/**`.
- Do not nest a corporate root under a site, or write `program.json` into the site.
