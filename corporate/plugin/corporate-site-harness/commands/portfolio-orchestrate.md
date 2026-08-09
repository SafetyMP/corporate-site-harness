---
name: portfolio-orchestrate
description: Coordinate portfolio metas and project sites via corp-harness portfolio
---

`corp-harness portfolio` is factory platform code. Do not implement portfolio CLI
changes from a product site root.

Run the portfolio orchestrator against `specs/portfolio.json`:

1. `corp-harness portfolio check --contract specs/portfolio.json`
2. `corp-harness portfolio status --contract specs/portfolio.json`
3. For new project work:
   `corp-harness portfolio route --contract specs/portfolio.json --target <site>`
   (optional `--program-root` for an explicit corporate folder). The proposed
   init uses a dedicated corporate folder that points at the site — not this
   harness checkout and not the site itself.

Factory portfolio changes require `--kind factory` plus user
`factory_authorization`. Do not revive retired v4 portfolio profile guards. Do
not infer gate PASS or grant user approval.
