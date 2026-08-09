# Corporate/Site Harness

Evidence-gated control plane for Cursor agents: **corporate** roles design and
review in one workspace; **site** roles implement in an isolated repository;
executable digests—not prose—decide whether work advances.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

> **How it works:** see [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the full
> phase machine, corporate↔site handoff, and every agent stakeholder.

## Why this exists

Multi-agent coding often collapses into one chat that both writes code and
declares success. This harness separates authority:

- Specs and gates live in a **corporate root** (`program.json`).
- Implementation lives in a **site** checkout.
- `corp-harness` records digest-bound evidence; agents never invent a PASS.
- Only the **user** grants `factory_authorization` and final `user_approval`.

## Install

```bash
pip install -e ".[dev]"
python3 -m pytest -q
python3 -m ruff check src tests
python -m corp_harness --help
```

Full local gate (binds an active program root when present):

```bash
./scripts/harness/verify.sh
```

### Cursor plugin

```bash
corp-harness install --source corporate/plugin/corporate-site-harness --apply
```

Slash commands: `/project-intake`, `/corp-status`, `/site-deliver`,
`/portfolio-orchestrate`. Details in
[corporate/plugin/corporate-site-harness/README.md](corporate/plugin/corporate-site-harness/README.md).

## Project flow (summary)

```text
DESIGN → CORPORATE_ACCEPTANCE → SITE_DELIVERY → SITE_VERIFICATION
      → CORPORATE_REVIEW → ADVERSARY → AWAITING_USER_APPROVAL → APPROVED
```

| Stage | Where | Who |
|-------|-------|-----|
| Design & corporate acceptance | Corporate root | CEO, specialists, COO |
| Delivery & site verification | Site root | Site manager, site specialist, operations excellence |
| Review, adversary, dossier | Corporate root | Specialists, adversary, CEO |
| Final approval | Corporate root | **User only** |

Workspaces stay separate:

```text
~/work/
  corporate-site-harness/   ← factory (this repo)
  my-app-corporate/         ← program.json + gates
  my-app/                   ← product implementation
```

Never nest the corporate root under the site. Never write `program.json` into
the site. Product sites must not edit `src/corp_harness/**`.

## Quickstart (product program)

```bash
# 1) Factory + plugin (above)

# 2) Sibling corporate folder + site checkout
mkdir -p ~/work/my-app-corporate ~/work/my-app
# scaffold site gates from the template, then customize
cp -R site-template/. ~/work/my-app/

# 3) Initialize the program contract (dry-run first)
corp-harness init \
  --root ~/work/my-app-corporate \
  --id my-app \
  --site ~/work/my-app \
  --kind product

# 4) In Cursor: /project-intake  → corporate design through handoff
# 5) Switch to the site workspace: /site-deliver
# 6) User records approval when the program reaches AWAITING_USER_APPROVAL
```

Inspect mechanical state anytime:

```bash
corp-harness status --root ~/work/my-app-corporate
```

## Factory vs product

| | Product (default) | Factory |
|--|-------------------|---------|
| Target | Application site | This checkout (`site_path` = factory) |
| Edits | Product code only | Authorized factory surfaces only |
| Extra gate | — | User-recorded `factory_authorization` before leaving `DESIGN` |

Template: [templates/factory-authorization.TEMPLATE.json](templates/factory-authorization.TEMPLATE.json).

## Repository map

| Path | Purpose |
|------|---------|
| `src/corp_harness/` | CLI and phase/evidence engine |
| `corporate/plugin/corporate-site-harness/` | Cursor agents, skills, rules, hooks |
| `site-template/` | Minimal product-site scaffold with harness scripts |
| `docs/HOW_IT_WORKS.md` | Lifecycle and stakeholder guide |
| `docs/adr/` | Architecture Decision Records |
| `scripts/harness/` | Factory verify + adversarial gates |
| `swift/` | Optional read-only gov-assist sidecar |
| `templates/` | User-facing artifact templates |

## Local runtime state (gitignored)

Created by local runs; **not** part of the published tree:

- `programs/` — optional factory-local program folders
- `evidence/` — resume / delivery receipts
- `archives/` — archived payloads
- `.corp-harness-program-root` — pointer to an active corporate root

## License

Apache License 2.0. See [LICENSE](LICENSE).
