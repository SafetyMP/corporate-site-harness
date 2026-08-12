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
