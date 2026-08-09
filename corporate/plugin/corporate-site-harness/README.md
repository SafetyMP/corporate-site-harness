# Corporate/Site Harness

User-scoped Cursor roles and commands for evidence-gated project delivery.

Lifecycle, corporate↔site handoff, and stakeholder roles:
[docs/HOW_IT_WORKS.md](../../../docs/HOW_IT_WORKS.md).

Install with:

```bash
corp-harness install \
  --source corporate/plugin/corporate-site-harness \
  --apply
```

Use `/project-intake` for a new idea, `/corp-status` for current evidence, and
`/site-deliver` from an initialized site repository.

Premium models (Sol, Claude Fable) are routed via `corp-harness route-model`
and attested on work packets. See the `model-routing` skill and
`premium-model-policy` rule. Record invoice totals with
`corp-harness usage record --actor user`.

## Gov assist (factory, read-only)

Optional `corp-harness gov` / `corp-gov-check` commands diagnose, scaffold
non-granting drafts, explain staleness/handoffs, and
`check-authorized-surfaces`. They never record artifacts, advance phases, or
grant approvals. Agents never pass `--actor user`. Missing Swift soft-fails
with `GOV_ASSIST_UNAVAILABLE`; core `init`/`record`/`next`/`check` still work.
