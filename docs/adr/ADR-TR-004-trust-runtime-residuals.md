# ADR-TR-004: Trust-runtime residual closures (Swift D5 + heavy OSError)

## Status

Accepted for factory program `trust-runtime-residuals` revision 1 site delivery
(packets `WP-TR-F`, `WP-TR-G`, `WP-TR-H`).

## Context

APPROVED parent program `trust-routed-runtime` revision 4 left two non-blocking
residuals:

1. **PLAT-TR-05-SWIFT-THEATER-SUBSET** — Swift `TheaterSignalId` enumerated only
   a subset of the D5 closed set while Python already enforced all seven ids
   (ADR-TR-001 / ADR-TR-003).
2. **ADV-TR-001** — Direct `run_gov_command` `OSError` on heavy
   `validate-action` / `write-receipt` still returned `GOV_ASSIST_UNAVAILABLE`,
   contradicting parent TR-06 (empty-stdout heavy fail-closed was fixed in r4;
   OSError was not).

This ADR closes those residuals without rewriting approved parent ADR-TR-001,
ADR-TR-002, or ADR-TR-003 Decision digests for unrelated scope. Trust algebra,
FG-001 seals, sole-writer rules, genesis/anchor rules, and premium model
routing remain locked.

## Decision

1. **TRR-01 Swift TheaterSignalId full D5 mirror (closes PLAT-TR-05).**
   Swift `TheaterSignalId` MUST enumerate exactly the seven raw values identical
   to Python `THEATER_SIGNAL_IDS`:
   `vacuous_gate_pass`, `unbound_kpi`, `seal_bypass_attempt`,
   `out_of_band_mutation`, `unauthorized_actor`, `stale_factory_authorization`,
   `wrong_root_operation`. `TheaterSignalId.allCases` MUST be 7/7.
   `TrustEvent.validatePreconditions` for `deceptive_theater` MUST accept each
   signal with non-empty reasons. Swift remains propose-only; Python remains
   sole emit+apply of TrustEvents and sole writer of `trust-state.json`,
   `trust-event-log.jsonl`, and `trust-log-anchor.json`.

2. **TRR-02 Heavy OSError fail-closed at gov wrapper (closes ADV-TR-001).**
   In `src/corp_harness/swift_gov.py` `run_gov_command`:
   - When `command in HEAVY_COMMANDS` and subprocess raises `OSError` → return
     `error=GOV_REQUIRED`, `assist=false` (mirror empty-stdout heavy split).
   - When `command` is an assist command and subprocess raises `OSError` → keep
     SG-03 / `GOV_ASSIST_UNAVAILABLE`, `assist=true`.
   - Forbidden: remap heavy OSError to `GOV_ASSIST_UNAVAILABLE`.
   - Closure MUST hold on direct `validate-action` / `write-receipt` gov wrapper
     invocation (apply-path remapping is defense-in-depth only).

3. **TRR-03 Acceptance packaging.** Mandatory falsifiers:
   - `test_TRR_001_swift_theater_signal_id_seven`
   - `test_TRR_002_heavy_oserror_gov_required`
   - `test_TRR_002b_assist_oserror_sg03_preserved`
   plus keeper `test_TR_D6_004_heavy_empty_stdout_gov_required`.
   `scripts/harness/verify.sh` (and adversarial collect where applicable) MUST
   REQUIRED-collect those names so omission cannot greenwash.

4. **TRR-04 Orthogonality.** Trust routing remains orthogonal to `route-model` /
   premium model policy. Agents never pass `--actor user`.

## Consequences

- Factory `./scripts/harness/verify.sh` and `adversarial.sh` stay green with
  residual TRR nodes collected by name.
- Parent APPROVED `trust-routed-runtime` artifacts remain untouched.
- Work packets: `WP-TR-F-SWIFT-THEATER-D5`, `WP-TR-G-HEAVY-OSERROR-GOV-REQUIRED`,
  `WP-TR-H-RESIDUAL-TESTS`.
