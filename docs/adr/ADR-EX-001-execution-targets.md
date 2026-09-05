# ADR-EX-001: Execution targets for site compute

## Status

Accepted (`sep-2026-isolation`, SITE_DELIVERY revision 1)

## Context

September 2026 Cursor isolation (VM subagents, self-hosted machines, partner
sandboxes) is compute placement. An August-calibrated harness already isolates
corporate vs site vs factory and already puts site-specialist work in
`.worktrees/<packet-id>`. Isolation is blast-radius and context hygiene, not
evidence.

This ADR **cites** [`ADR-FC-001-fail-closed-runtime.md`](ADR-FC-001-fail-closed-runtime.md)
and [`ADR-TPC-001-three-plane-control.md`](ADR-TPC-001-three-plane-control.md).
It does **not** reopen fail-closed-runtime r1 or three-plane allow/deny.
`execution_target` is not a fourth plane, not trust-score routing, and not an
Evidence substitute. It does **not** join ADR-FC-001's required seven sealed
fields.

## Decision

1. **One ADR** for this delivery: ADR-EX-001. Work packets (all bind this ADR):
   - `WP-EX-001` — Policy field `execution_target`
   - `WP-EX-002` — Plugin and operator text
   - `WP-EX-003` — Deny corpus `EX-DENY-001` through `EX-DENY-007`

2. **Allowlist (case-sensitive).** Legal tokens: `worktree`, `isolated_copy`,
   `openshell:<name>`, `cloud_subagent`. Omitted or empty means `worktree`.
   Any other token or alias fails closed and is not coerced to default.

3. **OpenShell names.** `name` matches `^[a-z][a-z0-9-]{0,62}$`. Reserved
   names `hermes`, `pi`, and `eval` are illegal as `openshell:<name>` and as
   `program.site_path` (casefold, basename, symlink).

4. **Role map.** Corporate control roles stay local (`worktree`).
   site-specialist defaults to `worktree` and may opt into the other three.
   `independent_review` (operations-excellence, corporate-adversary) requires
   `isolated_copy` and must not follow the implementer into OpenShell or
   `cloud_subagent`. `design_review` stays `worktree`.

5. **Corporate root.** Non-worktree targets cannot write `program.json`,
   specs, gates, `factory_authorization`, or `user_approval`. Parent
   `corp-harness` on the local corporate folder remains the only writer.

6. **No sandbox product.** No corp-harness subcommand creates, starts,
   attaches, or hosts a sandbox or VM. `sandbox_fallback` stays OOS.

7. **Isolation is not PASS.** A green worktree, isolated copy, OpenShell, or
   VM run is not a named-gate PASS. Oracles remain only
   `scripts/harness/{verify,adversarial}.sh` bound to current digests.
   Cursor Remote / `openshell sandbox connect --editor cursor` is denied.
   Agents never pass `--actor user`.

8. **Ceilings unchanged.** `max_depth=1`, `max_children=6`,
   `no_redelegation=true`. A Cursor VM subagent or OpenShell sandbox **is**
   the depth-1 worker, not extra nesting. Ceiling hit → `halt_report`, not
   Sol/premium.

## Consequences

- G-EX-001..012 remain open until digest-bound oracle evidence; specialist
  pytest is packet evidence only.
- Partner workers (Vercel, E2B, Cloudflare, …), Origin hosting, raising
  ceilings, and a CLI sandbox runtime stay deferred.
- Factory plugin documents this allowlist. `site-template` and
  `docs/HOW_IT_WORKS.md` were outside this program's `factory_authorization`
  and wait on a user FA extension.
