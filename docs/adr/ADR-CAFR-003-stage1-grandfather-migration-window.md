# ADR-CAFR-003: Stage-1 grandfather / migration window (no Stage-2 flip)

## Status
Accepted (corporate-acceptance-factory-remediation, SITE_DELIVERY Stage 1)

## Context
Immediate dual-evidence `require_current` would orphan this program’s matching-revision
review-only CA PASS after SITE_DELIVERY edits the live factory
(DEF-CAFR-SELFHOST-001 / DEF-CAFR-RECAPTURE-001). Option B lands capture first with a
grandfather window.

## Decision
1. Introduce `CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS = False` in
   `contracts.py` (Stage 1 ≡ `migration_review_only_ok`). **Do not set True** in
   this delivery.
2. Wire the flag into `gate_is_current` / CA evidence currentness
   (`evidence_validation.py` / `program_state.py` as created):
   - Stage 1 (`False`): matching-revision/target review-only CA PASS remains current;
     if executable refs are present they must be successful + canonical.
   - Stage 2 (`True`): deferred — review-only alone fails currentness; dual-evidence
     PASS succeeds. Not implemented here.
3. `require_current=false` structural load of persisted legacy review-only gates
   remains available for load paths that do not assert currentness.
4. Do **not** redesign DEF-CA-03 rework (`REWORK_ACTORS`, CA→DESIGN prerequisites,
   generation semantics). ACC-CAFR-005/007/012 stay green/unchanged.

## Consequences
- Self-host can complete Stage-1 implementation without orphaning the current
  review-only CA PASS.
- Stage-2 flip remains a separate, fail-closed follow-up after dual-evidence
  recapture proofs (ACC-CAFR-013 P-MW2..P-MW4 / N-MW1).
- Premature Stage-2 flip in this packet is FAIL.
