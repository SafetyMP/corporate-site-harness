# ADR-PP-003: Factory verification_scripts = scripts/harness

## Status
Accepted (portfolio-platform factory program)

## Context
Whole-`scripts/` digests caused routine drift. Factory program
`verification-scripts-scope` already locked the harness boundary.

## Decision
This program binds `verification_scripts` only to site-relative `scripts/harness`
containing exactly `verify.sh` and `adversarial.sh`. Gate evidence invokes
`./scripts/harness/verify.sh` and `./scripts/harness/adversarial.sh`.

## Consequences
Unrelated `scripts/` tooling does not invalidate portfolio-platform gates.
