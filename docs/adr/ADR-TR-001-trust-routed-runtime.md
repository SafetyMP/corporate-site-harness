# ADR-TR-001: Trust-routed dual-layer runtime

## Status

Accepted (trust-routed-runtime, SITE_DELIVERY revision 4 remediation B–E)

## Context

Factory program `trust-routed-runtime` requires a unified CLI control surface while
routing mutations/validations through Python (light) or Swift ADT validation
(heavy) based on a rolling trust score. TrustEvents are consequential: each
applied event changes `trust_score`, recomputes `execution_layer`, and determines
`action_routed_layer` for the next apply. FG-001 always-force seals remain gated
at any score. Model routing (ADR-PP-004 / `execution_policy`) stays orthogonal.

## Decision

1. **One ADR** for this delivery: ADR-TR-001. Work packets:
   - `WP-TR-A-SWIFT-ADTS` — GovernanceTypes ADTs/protocols + D9/D10 type semantics
   - `WP-TR-B-PYTHON-RUNTIME` — `runtime_engine` + CLI sole emit+apply
   - `WP-TR-C-HEAVY-VALIDATE-FG001` — `validate-action` + FG-001 coexistence
   - `WP-TR-D-WRITE-RECEIPT` — `write-receipt` / `mint_gov_receipt` FG-001 seal entry
   - `WP-TR-E-TEST-HARDENING` — falsifiable test coverage for quantize, non-events, soft-fail, dry-run/apply trust fields

2. **Trust score algebra (TR-01):** domain `[0.0, 1.0]`; 2dp half-up quantize;
   light band iff `trust_score >= 0.7`; `strict_success` +0.05 clamp 1.0;
   `validation_failure` → `min(score, 0.69)`; `deceptive_theater` → `0.0`.

3. **trust-state (TR-03 / TR-08 D7):** schema `corporate-site-trust-state/v1` at
   `<corporate_root>/trust-state.json` with `generation`. Missing file synthesizes
   1.0/light (true genesis only). Digest mismatch is a **load-visible rebind** that
   preserves score/layer/`last_event` (no amnesty reset); persist + log append happen
   on the next writer path. Python is sole writer via flocked atomic replace;
   stale `generation` rejects lost updates.

4. **Always-force heavy (TR-04 / FG-001):**
   `record_artifact:{gates,kpis,corporate_handoff,factory_authorization,user_approval}`
   and `mint_gov_receipt`. Callable seal entry:
   `corp-harness gov write-receipt --root PATH` (corp-gov-check →
   `mint_gov_receipt` ProofEnvelope, kind `gov_seal`; never mutates
   `program.json`). `heavy_validate` / `validate-action` is distinct and
   **not** an always-force seal member; however a **bound** program root
   (`CORP_HARNESS_PROGRAM_ROOT` / `.corp-harness-program-root`) always forces
   heavy_validate on mutating apply. Unbound score 1.0 skips that gate.

5. **TrustEvent (TR-09):** closed kinds `strict_success` | `validation_failure` |
   `deceptive_theater`. Python `runtime_engine` sole emit+apply; Swift propose-only.
   Ordering: rejected/theater → event without program write; accepted mutating →
   save then event with post-write digest; validate-only → event without program
   write; `requires_heavy` → no event. Non-events: status, dry-run, route-model,
   check without `--apply`, gov assist without write-receipt.

6. **Consequences (TR-10):** persisted `execution_layer` from score band;
   `action_routed_layer` heavy if score `< 0.7` OR always-force OR heavy_validate.
   Soft-fail forbidden when routed heavy (`GOV_REQUIRED` if Swift missing).
   Recovery only via successive `strict_success` (14 from 0.0 to light).
   No `corp-harness trust set-score`.

7. **Soft-fail matrix (TR-06):** unbound ungated light + missing Swift →
   `GOV_ASSIST_UNAVAILABLE` (SG-03). Heavy route, bound-root light, FG-001 seals,
   or empty stdout on heavy corp-gov-check commands → `GOV_REQUIRED` (not soft).
   Seal (`write-receipt` / `mint_gov_receipt`) is always routed heavy.

8. **Orthogonality (TR-12):** trust routing does not subsume `route-model` /
   premium model policy.

## Consequences

- CLI `status` / `--apply` responses expose `trust_score`, `execution_layer`,
  `last_event.kind`.
- `./scripts/harness/verify.sh` and `adversarial.sh` remain the verification
  binding and must stay green with trust tests.
- Agents never pass `--actor user`. Factory authorization remains user-recorded.
