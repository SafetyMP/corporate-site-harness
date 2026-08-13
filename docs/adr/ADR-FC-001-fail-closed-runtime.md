# ADR-FC-001: Fail-closed control plane runtime

## Status

Proposed (fail-closed-runtime, SITE_DELIVERY revision 1)

## Context

Factory program `fail-closed-runtime` redefines the harness control plane so illegal
or unsigned work cannot finish. The 2026-08-12 DESIGN incident
(`evidence/chain-incident-r1.json` under the Fail Closed Harness corporate root)
is the r1 proving ground: unlocked JSONL append forked `seq 6312`, dirty scan
flooded the live factory tree with `out_of_band_mutation`, and mutating record
remains `GOV_REQUIRED`.

This ADR does **not** reopen trust-score algebra from ADR-TR-001 (TR-01 through
TR-11). It cites **ADR-TR-001 TR-12 orthogonality**: trust routing does not
subsume `route-model` / premium model policy. Premium/Sol is never a trust
reward, ceiling bypass, or recovery mechanism.

Sibling marker `.corp-harness-program-root` remains bound to
`/Users/sagehart/Downloads/Trust Runtime Residuals`. Agents must not unbind,
wipe, or re-point it. Agents never pass `--actor user`. No `trust set-score`.

## Decision

1. **One ADR** for this delivery: ADR-FC-001. Work packets (all bind this ADR):
   - `WP-FC-006` — Exclusive log append + user `recover-chain` + incident fixture
     (**finish + falsify** existing partial work; not greenfield)
   - `WP-FC-004` — Multi-program bind + dirty-scan scope + wrong_root + exclusions
   - `WP-FC-001` — Before-write deny + legal next + afterFileEdit insufficient
   - `WP-FC-002` — Sealed work orders + subcontractor ceilings (premium orthogonal)
   - `WP-FC-003` — Trust telemetry + locked mandates + no process-error cheat
   - `WP-FC-005` — Split-context + collusion/no-rehire + halt unbind + oracle binding
   - `WP-FC-007` — Forward `CORP_HARNESS_PROGRAM_ROOT` through `run_evidence` /
     `check --run` without rewriting the sibling marker; record SITE_VERIFICATION
     artifacts (`adr:*`, implementation, verification, verification_scripts,
     runtime_manifest)
   - `WP-FC-008` — Isolate `CORP_HARNESS_ACTIVE_PACKET` from oracle pytest so a
     leaked ops-review `write_set` cannot launder `evidence/` or factory edits
     into fixture tests

2. **Before-write deny (FC-01):** `preToolUse` (or equivalent) denies writes to
   protected corporate and factory surfaces unless a non-expired mutation permit
   or sealed packet `write_set` covers the exact path. `afterFileEdit` report-only
   does not satisfy the control. Deny names a legal next among
   `{mint-mutation-permit|status|route-model|check}` or `halt_report`.

3. **Sealed work orders + ceilings (FC-02 / FC-04):** Every named role and Task
   carries a sealed work order (`role`, `packet_id`, `root`, `write_set`,
   `routed_model`, `success_schema`, `halt_conditions`). Ceilings:
   `max_depth=1`, `max_children=6`, `no_redelegation=true`. Ceiling hit → halt,
   not Sol/premium. Premium only via `route-model` + escalation + budget ≠ hard_stop
   (TR-12).

4. **Split-context + collusion (FC-03 / FC-05):** Reviewers launch as NEW Task;
   prompt = packet id + digests + oracle only. Covering a skip voids packets;
   voided actor/session cannot be redispatched until user reinstate.
   Producer cannot record own gate. Unbind sibling / weaken approval → `halt_report`.

5. **Trust as telemetry (FC-06):** Light band must not skip FG-001 seals,
   adversary, `user_approval`, or digest binding. No set-score / amnesty.
   Process-error vs theater labels must not create cheat paths; until a
   cheat-free classifier exists, process-error skip is not enabled.

6. **Multi-program bind + scan (FC-07 / FC-10):** `CORP_HARNESS_PROGRAM_ROOT`
   overrides marker when valid. Dirty/OOB scan scopes to active program +
   authorized surfaces + write-set/permits. Exclude `__pycache__/`, `*.pyc`,
   `.build/`, sibling corporate dirt alone. `wrong_root_operation` on mutating
   mismatch. `run_evidence` / `check --run` MUST forward
   `CORP_HARNESS_PROGRAM_ROOT` into the oracle subprocess so formal evidence
   binds the env-selected program; it MUST NOT rewrite
   `.corp-harness-program-root`.

7. **Exclusive append + user recover (FC-09 / FC-11):** Log append shares the
   same exclusive critical-section discipline as trust-state writes (read tip +
   assign seq + append under flock). Duplicate seq 6312 class must be impossible.
   `corp-harness trust recover-chain --actor user --apply` seals broken log
   without wipe, truncate, or 1.0/light amnesty. Agent invoke → `unauthorized_actor`.

8. **Completion (FC-08):** Oracle only over `scripts/harness/{verify,adversarial}.sh`
   bound to current digests. Uncommitted recover-chain / log-lock / scan work is
   **not** a PASS until those oracles are green with current digests. Oracle
   pytest MUST NOT inherit `CORP_HARNESS_ACTIVE_PACKET`: `verify.sh` /
   `adversarial.sh` unset it before pytest, and fail-closed autouse fixtures
   `delenv` it so tmp write_set files stay authoritative. `run_evidence` MUST
   NOT add that key to `SAFE_ENV_KEYS`.

## Consequences

- Factory surfaces under `factory_authorization.authorized_surfaces` may change;
  product sites must not edit `src/corp_harness/**`.
- G-FC-* gates stay open until site oracle evidence references current digests.
- Sibling marker remains Trust Runtime Residuals; do not unbind.
- ADR-TR-001 trust algebra stays closed; TR-12 premium orthogonality is preserved.
- Agents never `--actor user`; prose is not a receipt; harness never grants user approval.
