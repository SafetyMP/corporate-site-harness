# Corporate/Site Harness

> Evergreen OSS reference for **evidence-gated Cursor agent workflows** — corporate
> roles design and review; site roles implement in an isolated repository;
> digest-bound gates decide whether work advances. Part of the
> [SafetyMP](https://github.com/SafetyMP) open-source portfolio.

[![CI](https://github.com/SafetyMP/corporate-site-harness/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SafetyMP/corporate-site-harness/actions/workflows/ci.yml)
[![CodeQL](https://github.com/SafetyMP/corporate-site-harness/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/SafetyMP/corporate-site-harness/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/SafetyMP/corporate-site-harness/badge)](https://scorecard.dev/viewer/?uri=github.com/SafetyMP/corporate-site-harness)
[![License: Apache-2.0](https://img.shields.io/github/license/SafetyMP/corporate-site-harness)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![Code of Conduct](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

> **Scope:** Reference architecture and runnable factory control plane — **not** a
> production-hardened enterprise governance product. See [SECURITY.md](SECURITY.md).

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

## Community

| Resource | Purpose |
|----------|---------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, DCO sign-off, PR expectations |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 |
| [SECURITY.md](SECURITY.md) | Private vulnerability reporting |
| [SUPPORT.md](SUPPORT.md) | How to get help |
| [GOVERNANCE.md](GOVERNANCE.md) | Maintainer model and decisions |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
