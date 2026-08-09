# ADR-CAFR-002: Corporate-root cwd isolation for CA capture

## Status
Accepted (corporate-acceptance-factory-remediation, SITE_DELIVERY Stage 1)

## Context
`corp-harness check --run` currently forces cwd/`allowed_root` to the registered
site root for every evidence run. Corporate acceptance must evaluate against the
corporate program root and must not read or depend on `site_path` (DEF-CA-01,
ACC-CAFR-002/004/009, SEC-XS-001).

## Decision
1. For `--run corporate_acceptance` only:
   - default cwd = resolved corporate program `--root`
   - `--cwd` if supplied must equal that program root; otherwise `ContractError`
   - `run_evidence(..., allowed_root=program_root)`
2. Site-gated runs (`smoke`, `site_verify`, `operations`, `corporate_review`,
   `adversarial`) keep site-root cwd/`allowed_root`; corporate-root cwd remains
   rejected for those names.
3. Capture evaluation must not require reading or writing `program.site_path`;
   forged PASS markers under the site must not affect the corporate-root result.
4. Executable evidence validation for `corporate_acceptance` expects cwd and
   executable resolution under the program root (`evidence_validation.py`,
   create-if-missing).

## Consequences
- CA capture is confusable neither with site gates nor with site filesystem state.
- Existing site cwd denial tests remain green.
- Complements ADR-CAFR-001 (registration) and ADR-CAFR-003 (grandfather); does not
  flip Stage-2 dual-evidence currentness.
