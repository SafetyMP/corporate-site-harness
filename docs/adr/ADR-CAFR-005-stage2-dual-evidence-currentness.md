# ADR-CAFR-005: Stage-2 dual-evidence currentness flip

## Status
Accepted (corporate-acceptance-stage2-currentness, SITE_DELIVERY revision 1)

## Context
Option B Stage 1 landed under `corporate-acceptance-factory-remediation`:
`corporate_acceptance` is registered in `EVIDENCE_COMMANDS` and `GATE_EXECUTION`,
corporate-root cwd isolation holds, N-MW1/N-MW2 fail closed, and
`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS=False`
(`CA_CURRENTNESS_MODE=migration_review_only_ok`) grandfathered matching-revision
review-only CA PASS. DEF-CA-03 CA→DESIGN rework is restored and must stay intact
(ACC-CAFR-005/007/012).

This factory program holds a current dual-evidence `corporate_acceptance` PASS
and authorizes the deferred Stage-2 flip so review-only alone is no longer
current while dual-evidence PASS remains current and self-host can advance
`SITE_DELIVERY` → `SITE_VERIFICATION` without a DESIGN deadlock escape.

## Decision
1. Flip `CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS` from `False` to
   `True` in `contracts.py`, which sets
   `CA_CURRENTNESS_MODE = "dual_evidence_required"`.
2. Remove the Stage-1 pin in `model.py`
   (`assert CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS is False`).
3. Keep Stage-2 enforcement paths in `evidence_validation.py` /
   `gate_is_current` aligned with dual-evidence currentness; update plugin
   docs (`gate-evidence` skill, `corp-status`) to state Stage 2 is active.
4. Land executable ACC-CAFR-013 Stage-2 proofs:
   - **P-MW2**: matching-revision/target review-only CA PASS fails
     `require_current=true` / `gate_is_current` after the flip.
   - **P-MW3**: dual-evidence CA PASS succeeds `gate_is_current` after the flip.
   - **P-MW4**: factory self-host advances `SITE_DELIVERY` → `SITE_VERIFICATION`
     without returning to DESIGN for deadlock escape.
5. Keep fail-closed Stage-1 guards:
   - **N-MW1**: premature dual-evidence currentness without
     `corporate_acceptance` in `GATE_EXECUTION` raises `ContractError`.
   - **N-MW2**: recapture deferral claims without Stage-1 capture registries
     fail closed.
6. Do **not** weaken DEF-CA-03 (`REWORK_ACTORS['CORPORATE_ACCEPTANCE']='coo'`
   and CA→DESIGN prerequisites/generation semantics). ACC-CAFR-005/007/012
   remain green regression guards. Do not edit `master_spec` / `acceptance`.

## Consequences
- Older review-only CA gates become non-current after the flip.
- New CA PASS recordings require successful executable evidence plus
  independent COO review when dual-evidence recording rules are active.
- Cold programs past CA that hold review-only evidence use delivered DEF-CA-03
  to re-record under dual-evidence rules.
- Completes ACC-CAFR-013 Stage-2 deferred proofs from the Stage-1 program.
