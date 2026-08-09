# ADR-PP-001: corp-harness portfolio is factory-owned

## Status
Accepted (portfolio-platform factory program)

## Context
`corp-harness portfolio {status,check,route}` lives in factory sources. Treating it as
a product-site deliverable under Portfolio Orchestrator created ownership drift and
stale evidence.

## Decision
Factory program `portfolio-platform` owns `src/corp_harness/portfolio.py` and CLI
wiring. Product `portfolio-orchestrator` is meta-rollout helpers only and must not
edit `src/corp_harness/**`.

## Consequences
- Factory changes to portfolio CLI require this program's `factory_authorization`
  and gate evidence.
- Product handoffs declare factory CLI ownership / readonly coordinator authority.
