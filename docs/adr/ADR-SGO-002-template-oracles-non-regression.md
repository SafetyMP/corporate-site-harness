# ADR-SGO-002: Template fail-closed oracles and factory non-regression

## Status

Accepted (`site-gate-oracle` factory program)

## Context

`site-template` `adversarial.sh` was a single pytest file with no deny-case
extension protocol. Factory `verify.sh` / `adversarial.sh` already collect
trust/AH/TRR tests; oracle work must not drop those collections.

## Decision

1. `site-template` verify/adversarial MUST invoke fail-closed oracle hooks
   (engine authenticity or N/A attestation; deny-case extension protocol).
   Always-green health stubs are not `site_gate_oracles` evidence.
2. Factory harness scripts keep collecting `test_TR_LOG_*`, `test_TR_AH_*`,
   and `test_TRR_*` / keeper nodes. Oracle tests are additive.
3. `swift_gov` / `_check_handoff` reports schema version and oracle pin
   currency. Handoff integrity never implies `corporate_acceptance` PASS.
4. FidusGate product sources are out of scope for this factory program.

## Consequences

New product sites inherit fail-closed oracle stubs. Factory trust/AH/TRR
falsifiers stay green.
