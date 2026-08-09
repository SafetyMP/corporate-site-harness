# ADR-CAFR-004: Restore DEF-CA-03 fail-closed CA→DESIGN rework

## Status
Accepted (corporate-acceptance-factory-remediation, SITE_DELIVERY revision 3)

## Context
Live factory probe shows `REWORK_ACTORS` has no `CORPORATE_ACCEPTANCE` key.
Bootstrap program `corporate-acceptance-rework-bootstrap` was APPROVED against
this `site_path`, but the land is absent. Stage-1 test
`test_rework_corporate_acceptance_retained_after_later_phase` pinned that
absence and inverted ACC-CAFR-005/007/012. Corporate handoff r3 + user
`factory_authorization` r3 authorize restore
(`def_ca_03_disposition=restore_missing_bootstrap_land`). Stage-1 capture /
grandfather (`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS=False`)
must remain; Stage-2 flip is out of scope.

## Decision
1. Add `CORPORATE_ACCEPTANCE: "coo"` to `REWORK_ACTORS` (prefer minimal land in
   `src/corp_harness/model.py`, which hosts `REWORK_ACTORS` / `rework` today;
   create `program_state.py` only if extraction is required).
2. Isolate a fail-closed `Program.rework` branch for `CORPORATE_ACCEPTANCE`:
   - actor must be `coo`
   - recorded current `corporate_acceptance` gate with status `FAIL`
   - current report / revision / target and current failed evidence
     (`gate_is_current` is sole currentness authority)
   - remaining attempt budget before mutation
   - denials (missing, PASS, stale, wrong-target, wrong-revision,
     evidence-less, wrong-actor, exhausted budget) leave phase, revision,
     generation, gates, and artifacts unchanged
3. On success: consume one attempt, increment revision, land `DESIGN`, clear
   all gates, unregister `master_spec`, `acceptance`, and
   `factory_authorization` without deleting files on disk.
4. Later-phase rework (SITE_VERIFICATION / CORPORATE_REVIEW / ADVERSARY / …)
   continues to land `SITE_DELIVERY` and retain the `corporate_acceptance` gate.
5. Replace the inverse absence pin with positive ACC-CAFR-005 / ACC-CAFR-007 /
   ACC-CAFR-012 proofs (including dry-run generation `g` vs `--apply`
   persisted `g+1` / revision `r+1`).
6. Do not flip Stage 2; do not edit `master_spec` / `acceptance` digests;
   stay inside authorized_surfaces.

## Consequences
- ACC-CAFR-005/007/012 become executable proofs of bootstrap semantics again.
- Stage-1 grandfather for review-only CA PASS remains unchanged.
- Fresh user `factory_authorization` bound to the new revision/master digest is
  required after a successful CA rework before advancement.
- Semantics reference: bootstrap `ADR-CA-REWORK-001` (read-only).
