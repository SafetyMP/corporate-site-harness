# ADR-CAFR-001: Stage-1 corporate_acceptance capture registration

## Status
Accepted (corporate-acceptance-factory-remediation, SITE_DELIVERY Stage 1)

## Context
`EVIDENCE_COMMANDS` and `GATE_EXECUTION` omit `corporate_acceptance` (DEF-CA-01/02).
Without a registered allowlisted capture path, executable corporate-acceptance evidence
cannot be produced. Option B Stage 1 must land capture registration while
`CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS` remains `False`.

Live factory still concentrates contracts in `model.py`; authorized surfaces target
`contracts.py` (create-if-missing) plus `cli.py`. Factory `scripts/harness` today
must contain exactly `verify.sh` and `adversarial.sh` for `verification_scripts`.

## Decision
1. Register identical argv in both registries:
   `["./scripts/harness/corporate-acceptance.sh"]`.
2. Place registry constants (including `GATE_EXECUTION["corporate_acceptance"]`) in
   `src/corp_harness/contracts.py` (create if missing). `cli.py` adds
   `EVIDENCE_COMMANDS["corporate_acceptance"]` with the same argv.
3. Seed `./scripts/harness/corporate-acceptance.sh` for capture runs that use
   corporate-program-root cwd. On the factory checkout, allow
   `corporate-acceptance.sh` as an **optional** third file under `scripts/harness`
   without requiring it on product sites:
   - required: `{verify.sh, adversarial.sh}`
   - optional: `{corporate-acceptance.sh}`
   Reject any other entries. Do **not** flip Stage-2 currentness in this ADR.
4. `check --run corporate_acceptance` emits `corporate-site-evidence/v1` only
   (never review evidence / reviewer identity).

## Consequences
- Stage-1 capture path becomes executable and argv-exact.
- Product sites that keep only the two required harness scripts remain valid.
- Factory may ship the CA script without breaking `verification_scripts` exact-set
  product compatibility.
- Thin `model.py` facade re-exports may be required for import compatibility; that
  path is outside hard_scope and must be escalated if needed (see root receipt risks).
- Stage-2 flag flip is explicitly out of scope for this ADR.
