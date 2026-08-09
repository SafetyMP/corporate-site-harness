# ADR-SGA-002: P1 explain-stale and check-handoff assist commands

## Status
Accepted (swift-governance-assist, SITE_DELIVERY revision 1) — design; depends on ADR-SGA-001

## Context
ADR-SGA-001 locks the assist-only splash and P0 command surface. Agents also need
read-only explainers for stale digests and handoff integrity without gaining
mutation authority. These commands are consequential because incorrect
“current/stale” signaling can mislead gate recording and site delivery.

## Decision
1. Extend `corp-harness gov` / `corp-gov-check` with **P1** commands
   `explain-stale` and `check-handoff` under the same assist-only contract
   (SG-01): no record/next/authorization side effects; `program.json` digest
   and phase unchanged.
2. Reuse Stage-2 dual-evidence currentness awareness from ADR-SGA-001 (SG-02)
   when explaining staleness or handoff digest mismatch.
3. Keep soft-fail `GOV_ASSIST_UNAVAILABLE` when the Swift binary is absent
   (SG-03); do not invent a second Python-only authority path for these
   explainers in this packet unless required to preserve soft-fail clarity.
4. Cover both commands with digest-pinned fixtures and before/after digest
   asserts (ACC-P1-001).

## Consequences
- P1 lands only after P0 bridge/CLI plumbing from ADR-SGA-001 is available.
- Does not authorize surface-tree mutation checks (reserved for ADR-SGA-003).
