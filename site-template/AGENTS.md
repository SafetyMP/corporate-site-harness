# Site contract

## Gates

| Command | Purpose |
|---|---|
| `./scripts/harness/verify.sh` | Functional and static acceptance |
| `./scripts/harness/adversarial.sh` | Authorized local adversarial probes |

Record `verification_scripts` as the site directory `scripts/harness` (exactly those
two scripts). Optional wrappers may remain at `scripts/verify.sh` /
`scripts/adversarial.sh` for humans; they are outside the digest boundary.
Oracle evidence (`site_gate_oracles`) lives outside `scripts/harness`.

The corporate handoff fixes scope. The site manager assigns ADRs; site specialists write;
operations excellence reviews current evidence. Work in isolated roots, never edit
corporate approval state, and never self-approve.

Named role launches need a sealed work order (`role`, `packet_id`, `root`,
`write_set`, `routed_model`, `success_schema`, `halt_conditions`).
`execution_target` is optional placement, not one of those seven. Legal tokens:
`worktree` (default; `.worktrees/<packet-id>`), `isolated_copy`,
`openshell:<name>`, `cloud_subagent`. Unknown tokens fail closed. Reserved
OpenShell names `hermes`, `pi`, `eval` are illegal as `openshell:<name>` and as
`site_path`. Connect with `openshell sandbox connect <name>` from a Mac terminal;
never `--editor cursor`. Reviewers use `isolated_copy` (oracle tree ≠ implementer
tree). Ceilings: `max_depth=1`, `max_children=6`, `no_redelegation=true`. Isolation
green is not a named-gate PASS. Agents never `--actor user`.
