# ADR-TPC-001: Three-plane control plane (Capability + Evidence + Spend)

## Status

Proposed (three-plane-control, SITE_DELIVERY revision 1)

## Context

Factory program `three-plane-control` demotes court-of-agents / trust-score
controls and binds sealed dispatch and legal apply to exactly three planes:
Capability, Evidence, and Spend. Phase-1 fail-closed invariants remain.

This ADR **cites** [`ADR-FC-001-fail-closed-runtime.md`](ADR-FC-001-fail-closed-runtime.md)
and does **not** reopen fail-closed-runtime r1 or its decision surface. Sibling
marker `.corp-harness-program-root` remains
`/Users/sagehart/Downloads/Trust Runtime Residuals`. Session bind uses
`CORP_HARNESS_PROGRAM_ROOT=/Users/sagehart/Downloads/Three Plane Harness`.
Agents never pass `--actor user`.

Implementation baseline (parent restores before packets):
`fail-closed-runtime@a8bbcb243b0328e4b953a7006e39a9263aaaa0d5`.

Trust algebra from ADR-TR-001 (TR-01 through TR-11) stays closed as a routing
control; TR-12 premium/`route-model` orthogonality is preserved. Score and
theater labels may remain as telemetry and audit.

## Decision

1. **One ADR** for this delivery: ADR-TPC-001. Work packets (all bind this ADR):
   - `WP-TPC-001` — Demote court / three-plane bind / FG-001 always-force / Magnet audit-only
   - `WP-TPC-002` — Pave legal path (apply auto-bind, WP-FC-007/008 env isolation, status cheap, actor-user scoped)
   - `WP-TPC-003` — Halt flags + dispatch kernel (≤15-line work order, attest-packet only, halt_report terminal)
   - `WP-TPC-004` — Unify pipeline + multi-program env bind + genesis not fail-closed for status/record
   - `WP-TPC-005` — Grok 4.6 aliases + strip USD/invoice/age-as-gate + no complexity auto-Sol
   - `WP-TPC-006` — Cut ceremony after auto-bind (depends on WP-TPC-002)
   - `WP-TPC-007` — Lock surface host-trusted config + dual-path plugin + stereotyped deny + invocation shell + env not fail-open
   - `WP-TPC-008` — Evidence independence + adversary weaken-probes + `REQUIRED_SGO_TESTS ∪ REQUIRED_FC_TESTS` FA lock-surface

2. **Three planes only (TPC-PLANE-001):** Allow/deny for sealed dispatch and legal
   apply evaluates Capability + Evidence + Spend only. `trust_score`, theater
   kind, USD budget, and career ledger MUST NOT gate allow/deny. Score `0.0`
   with heavy telemetry still allows when all three planes pass; any failed
   plane refuses.

3. **Court demotion (TPC-COURT-001/002):** `action_routed_layer` MUST NOT call
   `execution_layer_for_score`. Light/heavy band and theater-kind taxonomy are
   telemetry/audit, not layer-selection or allow/deny controls. Score mutation
   alone MUST NOT flip non-seal apply allow/deny or routing.

4. **FG-001 always-force (TPC-COURT-003):** FG-001 seals remain always-force by
   action name at score `1.0` and `0.0` alike, independent of theater kind or
   spend class.

5. **Magnet audit-only (TPC-COURT-004 / TPC-SEC-MAGNET-001):** Existing trust
   JSONL MAY append monotonic cheat bits (`hook_write`, `actor_skip`,
   `self_approval`) for audit. Routing and allow/deny ignore magnet bits and
   score. No Intern→Principal autonomy ladder. No new detector product.

6. **Marker / actors:** Env bind without rewriting Trust Runtime Residuals
   marker. Agents never `--actor user`. Oracle evidence remains only
   `scripts/harness/{verify,adversarial}.sh` bound to current digests.

## Consequences

- G-TPC-* remain open until digest-bound oracle evidence; specialist pytest is
  packet evidence only and does not invent named gate PASS.
- ADR-FC-001 r1 stays closed; product sites must not edit `src/corp_harness/**`
  outside this factory FA.
- Harness never grants user approval; agents never `--actor user`.
- Later WP-TPC packets land legal-path, halt kernel, cuts, lock surface, and
  REQUIRED collect merge without reopening this decision's court demotion.
