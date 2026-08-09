# ADR-PP-002: Portfolio sensors are readonly

## Status
Accepted (portfolio-platform factory program)

## Context
Portfolio orchestration must not become a second control plane that mutates program
phase or invents corporate gate PASS.

## Decision
`corp-harness portfolio` remains a readonly coordinator:
- Observational sensor PASS/FAIL is not corporate gate evidence.
- `route` proposes `corp-harness init` only (`apply: false`, `wrote: false`).
- Retired identifiers `portfolio-ops`, `harnessctl`, `harness_profile` stay rejected.

## Consequences
All phase/gate mutations stay on `corp-harness record` / `next` / `check` with
explicit actors and digests.
