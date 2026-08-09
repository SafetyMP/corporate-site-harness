# ADR-SGA-003: P2 check-authorized-surfaces and factory boundary green

## Status
Accepted (swift-governance-assist, SITE_DELIVERY revision 1) — design; depends on ADR-SGA-001 (and P1 preferred before ops close)

## Context
Factory delivery must prove assist changes stay inside the user-recorded
`factory_authorization.authorized_surfaces` and that factory
`verify.sh` / `adversarial.sh` remain green. A dedicated assist check for
authorized surfaces is consequential: false allow/deny can hide factory drift
or block legitimate assist work.

## Decision
1. Add `corp-harness gov check-authorized-surfaces` (P2) that evaluates
   allow/deny against the authorized factory surfaces **after** Python
   existence checks already present in the harness. The check itself must not
   mutate the factory tree or `program.json`.
2. Keep assist-only / soft-fail / Stage-2 contracts from ADR-SGA-001 intact.
3. Optionally update `scripts/harness/verify.sh` to run Swift tests when the
   toolchain is present; never make Swift mandatory for core Python gates.
4. Optionally add short skill notes under
   `corporate/plugin/corporate-site-harness/**` describing `gov` assist usage
   without granting approvals.
5. Close ACC-P2-001 and ACC-SG-004 with path allowlist audit evidence plus
   green `./scripts/harness/verify.sh` and `./scripts/harness/adversarial.sh`.

## Consequences
- Final packet in the assist delivery sequence; integrates P0/P1 surfaces.
- Agents still never pass `--actor user`; Stage-2 substrate files remain out of
  authorized write set for this program.
