---
applyTo: "**/*test*.py,**/tests/**/*.py"
---

# Test standards (September 2026)

- pytest is the runner. Add tests next to the existing `tests/` layout.
- Do not skip or weaken verify, ruff, or adversarial gates.
- Do not invent a passing gate from prose.
- Fixtures are synthetic. Never commit secrets or live tenant data.

## This repository

- `python3 -m pytest -q`, `python3 -m ruff check src tests`, then `./scripts/harness/verify.sh`.
- Oracle evidence files must not live in `scripts/harness`.
