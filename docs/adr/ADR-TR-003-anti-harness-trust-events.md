# ADR-TR-003: Anti-harness TrustEvents, mutation permits, and Cursor hooks

## Status

Accepted for WP-TR-AH-A core (classify/permit/report-event/deferred scan/anchor
protect), WP-TR-AH-B factory `.cursor` hooks (`afterFileEdit`,
`beforeShellExecution` → `trust report-event`; disabled hooks while bound →
`seal_bypass_attempt`), and WP-TR-AH-C falsifiable ACC-TR-AH_* tests plus
`scripts/harness/{verify,adversarial}.sh` collection under bound program root.

## Context

Silent editor/shell mutations of protected D8 / corporate / `.cursor` surfaces
must not leave trust at `1.0`. ADR-TR-001 routing and ADR-TR-002 audit log are
insufficient without detection, classification, a sole report path, short-lived
mutation permits for authorized harness applies, program-root binding, and
fail-closed false-genesis / unbind / hook-disable rules.

Related handoff packets: `WP-TR-AH-A`, `WP-TR-AH-B`, `WP-TR-AH-C`.

## Decision

1. **D5 theater set (exactly seven):** `vacuous_gate_pass`, `unbound_kpi`,
   `seal_bypass_attempt`, `out_of_band_mutation`, `unauthorized_actor`,
   `stale_factory_authorization`, `wrong_root_operation`. Unknown
   `theater_signal_id` rejected. Anti-harness maps to the four-id subset
   (`out_of_band_mutation`, `unauthorized_actor`, `stale_factory_authorization`,
   `wrong_root_operation`) plus `seal_bypass_attempt` for hook-disable/unbind;
   always apply as `deceptive_theater` → score `0.0`. Honest evidence/apply
   failures remain `validation_failure` (theater ids reserved).

2. **Sole report path:** `corp-harness trust report-event` →
   `runtime_engine.emit_and_apply` (Python sole writer; appends trust log).
   Hooks and deferred scan MUST NOT mutate score except through this path.

3. **Detection (both required):**
   - Cursor project hooks under `.cursor` (`afterFileEdit`,
     `beforeShellExecution`) bound to the program root.
   - Deferred dirty-surface scan on every trust-gated CLI entry (including
     `status` and mutating apply) **before** non-event short-circuit when
     program root is bound or factory `.cursor` hooks exist.
   - `verify.sh` / `adversarial.sh` MUST bind program root and exercise the
     scan (CI cannot omit root to skip anti-harness).
   - Disabling/removing required hooks while bound (or after install) →
     `seal_bypass_attempt` → `0.0`.

4. **Mutation permit** at `<corporate_root>/trust-mutation-permit.json`:
   minted only by `python_runtime_engine` for authorized harness `--apply`.
   Locked minimum fields: `schema`, `permit_id`, `program_digest`, `paths[]`,
   `ttl_seconds` (≤ 120), `minted_at` (UTC), `expires_at` (UTC),
   `single_use` (true). Clock-skew lock: reject if `now < minted_at` or
   `now > expires_at` or ttl mismatch vs `expires_at - minted_at`.
   Expired/forged/reused/mismatched → `out_of_band_mutation`. Permit file is
   itself a protected surface.

5. **Program root binding:** factory checkout resolves corporate root via
   `CORP_HARNESS_PROGRAM_ROOT` or `.corp-harness-program-root` before mutating
   protected surfaces. Missing/unresolvable root on protected touch →
   `wrong_root_operation` → `0.0` (no soft-note escape). Unbind after bind
   (delete marker / clear env) → `seal_bypass_attempt` → `0.0` and does **not**
   restore SG-03 soft-fail rights.

6. **Genesis / dual-wipe / anchor protect:** if `trust-log-anchor.json` exists
   or log was/is non-empty, deleting/truncating log and/or trust-state and/or
   anchor MUST NOT synthesize `1.0`/light; classify `out_of_band_mutation` →
   `0.0` (covers dual wipe and post-log state deletion).

7. **Trust-gated CLI always-on set:** `record` / `next` / `check --apply` /
   gov seal+validate / `trust report-event` / `archive` / `install` /
   `rollback` / `usage --record` participate in trust routing and dirty scan
   under bound root. Bound root forces `heavy_validate` always-heavy.

8. **Forbidden:** `corp-harness trust set-score`; Swift writers of sole-writer
   files; agents passing `--actor user`; forgeable permits; score restore via
   state/log/anchor wipe or digest score-reset amnesty.

## Consequences

- Work packets: `WP-TR-AH-A` (classify/permit/report-event/deferred scan/anchor
  protect), `WP-TR-AH-B` (create `.cursor` hooks; expected
  AUTHORIZED_SURFACE_MISSING until this packet), `WP-TR-AH-C` (ACC-TR-AH_*
  falsifiable tests + verify/adversarial collection).
- Depends on ADR-TR-002 log append so report-event and dirty-scan theater
  leave durable JSONL evidence.
- Clean `status` remains a non-event; dirty deferred scan is consequential
  (TR-09 carve-out).
