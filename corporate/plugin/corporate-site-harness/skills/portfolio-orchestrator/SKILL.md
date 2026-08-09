---
name: portfolio-orchestrator
description: Coordinates SafetyMP meta and project sites via corp-harness portfolio without restoring portfolio-ops authority.
---

# Portfolio orchestrator

`corp-harness portfolio` is **factory platform** code (`src/corp_harness/portfolio.py`),
not a product-site deliverable. Meta-rollout helpers may live in a separate site
checkout; they must not own or edit factory portfolio sources.

Use from a meta checkout when work spans the portfolio contract:

1. Read `specs/portfolio.json` (schema `corporate-site-portfolio/v1`).
2. Run `corp-harness portfolio check --contract specs/portfolio.json`.
3. Run `corp-harness portfolio status --contract specs/portfolio.json` for bound programs.
4. For new project work, run
   `corp-harness portfolio route --contract specs/portfolio.json --target <site>`
   (optional `--program-root` for an explicit corporate folder). Execute the
   printed `corp-harness init` only after user confirmation — never nest
   `program.json` inside an app checkout.
5. Domain sensors (parity, security-alerts) are declared in the contract; do not revive
   `portfolio-ops`, `harnessctl`, or `harness_profile` guards.

Changing portfolio platform behavior requires `init --kind factory` and a
user-recorded `factory_authorization` before corporate acceptance.

The orchestrator is readonly. Digests and `corp-harness` gates remain the only authority.
Never infer PASS, never pass `--actor user`, and never self-approve.
