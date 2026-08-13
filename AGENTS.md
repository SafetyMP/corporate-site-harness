# Corporate harness

Human-oriented lifecycle and stakeholder map: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Verify

| Command | Purpose |
|---|---|
| `python3 -m pytest -q` | Contract and safety tests |
| `python3 -m ruff check src tests` | Static checks |
| `./scripts/harness/verify.sh` | Full local gate |
| `./scripts/harness/adversarial.sh` | Authorized local adversarial probes |

`verification_scripts` must bind to site-relative `scripts/harness` (only
`verify.sh` and `adversarial.sh`). Optional `scripts/verify.sh` wrappers are outside
that digest. Newly recorded `corporate_handoff` artifacts use
`corporate-site-handoff/v2` with `site_gate_oracles` (official engine, parity,
wiring, inventory, deny-case extension). Oracle evidence files must not live in
`scripts/harness`. Keep role instructions short. Put enforceable behavior in code
and tests. A passing gate must reference the current artifact digest; the harness
never grants user approval.

## Factory vs product

- Default programs are `program_kind: product` and target an application site.
- Factory platform features use `corp-harness init --kind factory` with
  `site_path` set to this checkout. Corporate roots must be a separate
  sibling directory (own workspace / git root), never nested under the
  factory or site tree.
- Factory programs cannot leave `DESIGN` for `CORPORATE_ACCEPTANCE` without a
  user-recorded `factory_authorization` artifact bound to the current
  `master_spec` digest. Agents never pass `--actor user`.
- `corp-harness portfolio` is factory platform code, not a product-site
  deliverable. Product sites must not edit `src/corp_harness/**`.

Named role and Task launches require a sealed work order (`role`, `packet_id`,
`root`, `write_set`, `routed_model`, `success_schema`, `halt_conditions`).
Unsealed `generalPurpose` output is not gate evidence. Subcontractor ceilings:
`max_depth=1`, `max_children=6`, `no_redelegation=true`; a hit is `halt_report`,
not Sol/premium.

Allow/deny is Capability + Evidence + Spend only (`ADR-TPC-001`).
`trust_score` is principal telemetry and must not route or gate allow/deny.
Light band does not skip FG-001 seals, adversary, `user_approval`, or digest
binding. FG-001 remains always-force by action name. Magnet cheat bits are
audit-only. No set-score / wipe-rebind amnesty. Process-error skip is not
enabled. Do not reopen fail-closed-runtime r1.

Reviewers launch as a new Task (prompt = packet id + digests + oracle only).
Covering a skipped gate voids involved packets (audit ledger may record
actors); the voided-actor/no-rehire ledger is not an allow/deny or route-model
control. Same-session reviewer refuse and producer-cannot-self-record still
refuse. After preToolUse deny, legal next is
`corp-harness apply|status|route-model|check` (or `halt_report`);
`mint-mutation-permit` is not required. Halt/dispatch matches only boolean
flags `unbind_sibling`, `skip_adversary`, `skip_user_approval`,
`weaken_adversary`, `weaken_user_approval` (never `halt_conditions` prose);
flag true ⇒ `halt_report`. Attest evidence is only `check --attest-packet`
stdout (hand-written `attest-*.json` is non-evidence). `halt_report` is
terminal success. Oracle evidence is only
`scripts/harness/{verify,adversarial}.sh`.
