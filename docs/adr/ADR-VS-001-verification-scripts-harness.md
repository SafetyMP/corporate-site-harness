# ADR-VS-001: verification_scripts binds to scripts/harness

## Decision
Corporate programs record `verification_scripts` as site-relative `scripts/harness`
containing only `verify.sh` and `adversarial.sh`. Gate evidence invokes those paths.

## Consequences
Unrelated `scripts/` tooling drift no longer invalidates verification gates.
