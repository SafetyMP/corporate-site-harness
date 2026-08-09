# ADR-SGA-001: Assist-only Swift governance splash architecture

## Status
Accepted (swift-governance-assist, SITE_DELIVERY revision 1) — design; implementation via work packets

## Context
Factory program `swift-governance-assist` adds a typed Swift assist splash for
Cursor agents (`corp-harness gov` / `corp-gov-check`) so diagnose, non-granting
scaffolds, and transition explainers stay digest-bound without giving Swift
write authority over `program.json`. Python remains the sole writer for program
state. Stage-2 dual-evidence currentness is already active on the factory
substrate; assist output must not treat review-only corporate_acceptance PASS as
current. Swift must stay optional for product sites and pure-Python clones.

## Decision
1. **Assist splash, not authority.** Ship an optional Swift package under
   `swift/` exposing `corp-gov-check`, bridged by
   `src/corp_harness/swift_gov.py` and wired into `corp-harness gov` in
   `src/corp_harness/cli.py`. Assist may diagnose, scaffold non-granting drafts,
   and explain transitions. It must not record artifacts, advance phases, grant
   user/factory authorization, or mutate `program.json`.
2. **Python sole write authority.** All durable program mutations stay on the
   existing Python `record` / `next` / authorization paths. Swift never becomes
   a second write path for capability artifacts.
3. **Stage-2 awareness (SG-02).** Diagnose/explain consume the same currentness
   rules as Stage-2 dual-evidence CA. Review-only CA PASS is reported as not
   current; scaffolds must not imply current CA PASS.
4. **Soft-fail without Swift (SG-03).** When `corp-gov-check` is missing,
   `corp-harness gov` returns a clear `GOV_ASSIST_UNAVAILABLE` error; core
   `init` / `record` / `next` / `check` continue to work.
5. **P0 command surface.** First implementation packet lands
   `diagnose`, `scaffold-approval`, `scaffold-factory-auth`, and
   `explain-transition` with digest-pinned fixtures under
   `tests/fixtures/governance/`.

## Consequences
- Factory verify/adversarial remain green without requiring Swift toolchain on
  every host; soft-fail tests cover the missing-binary path.
- P1/P2 commands extend this architecture under follow-on ADRs without
  reversing SG-01/02/03.
- Out of scope for this ADR: rewriting evidence/portfolio/archive/model write
  paths in Swift; silent dual-check as primary design; agent `--actor user`.
