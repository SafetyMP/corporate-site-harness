# ADR-CAFR-006: Stage-2 user-only migration redesign (rework precedence)

## Status
Accepted (corporate-acceptance-stage2-migration-recapture, SITE_DELIVERY revision 1)

## Context
Stage 2 is live (`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS=True`,
`CA_CURRENTNESS_MODE=dual_evidence_required`). Programs that hold review-only
or missing `corporate_acceptance` gates are non-current and blocked from
advancement. DEF-CA-03 (`actor=coo`, `CORPORATE_ACCEPTANCE` + current FAIL →
`DESIGN`) works but is unreachable from post-CA phases. User reopen from
`APPROVED` / `AWAITING_USER_APPROVAL` lands `SITE_DELIVERY` and retains stale
CA; user `--rework` from `SITE_DELIVERY`, `SITE_VERIFICATION`,
`CORPORATE_REVIEW`, or `ADVERSARY` is denied because those phases are not
bound in `REWORK_ACTORS` (and must not be permanently bound to `user`).

Live `Program.rework` evaluates `REWORK_ACTORS` before any migration branch;
`SITE_DELIVERY` has no rework actor today.

## Decision
1. Add a **migration-eligible** predicate evaluated **first** in
   `Program.rework`, before `REWORK_ACTORS` role enforcement and before
   `USER_REOPEN_PHASES` retain-CA landing:
   - Stage 2 active (`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS` is True)
   - `actor_role == "user"`
   - `phase ∈ {AWAITING_USER_APPROVAL, APPROVED, SITE_DELIVERY, SITE_VERIFICATION,
     CORPORATE_REVIEW, ADVERSARY}`
   - `corporate_acceptance` missing **or** `gate_is_current("corporate_acceptance")`
     is False
   - Never activates from `CORPORATE_ACCEPTANCE`
2. On migration match (§3.2 effect; does **not** consume review attempt budget):
   - `revision += 1`
   - `phase = DESIGN`
   - Clear **all** gates
   - Unregister `master_spec`, `acceptance`, `factory_authorization`,
     `user_approval`, `final_dossier`, `corporate_handoff` (files may remain)
   - Do **not** increment `attempts`
3. **Do not** permanently expand `REWORK_ACTORS` to bind
   `SITE_DELIVERY`, `SITE_VERIFICATION`, `CORPORATE_REVIEW`, or `ADVERSARY`
   to `user`.
4. Preserve existing semantics when migration-eligible is false:
   - Stage 2 + **current** dual-evidence CA: user reopen from
     `APPROVED` / `AWAITING_USER_APPROVAL` → `SITE_DELIVERY` retain CA
     (unchanged); user `--rework` from mid-flight phases → `ContractError`,
     state unchanged
   - Stage 1 (`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS` False):
     migration branch inactive; prior reopen / denial semantics unchanged
   - Non-user `REWORK_ACTORS` mid-flight rework → `SITE_DELIVERY` retain CA
     (must not take migration wipe path)
   - DEF-CA-03 CA→DESIGN (`actor=coo`, current FAIL at `CORPORATE_ACCEPTANCE`)
     unchanged; consumes one attempt
5. Implementation surface: `src/corp_harness/model.py` only for behavior;
   `src/corp_harness/cli.py` is **not** authorized. Operator guidance in
   `corp-status` and `gate-evidence` (ACC-MIG-006). Agents never pass
   `--actor user` (ACC-CAFR-008).

## Consequences
- Cold / blocked Stage-2 programs can user-migrate to `DESIGN` for dual-evidence
  recapture without weakening currentness or DEF-CA-03.
- Operators batch-migrate stale inventory via
  `corp-harness next --root <p> --rework --actor user --apply`, then re-record
  design, factory auth (if factory), and dual-evidence CA PASS.
- ACC-CAFR-005/007/012 regression suite must remain green; migration attempts
  must not burn review budget unlike DEF-CA-03.

## References
- Master spec §3 (rework evaluation order)
- ACC-MIG-001..006, ACC-CAFR-008
- ADR-CAFR-004 (DEF-CA-03), ADR-CAFR-005 (Stage-2 flip)
