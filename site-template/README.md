# Site template

Minimal product-site scaffold for [corporate-site-harness](../README.md).

Copy into a sibling application repo, then customize:

```bash
cp -R site-template/. ~/work/my-app/
cd ~/work/my-app
pip install -e ".[dev]"
./scripts/harness/verify.sh
```

Set `.corp-harness/site.json` (`site_id`, verify/adversarial argv). Keep both
`scripts/harness/verify.sh` and `scripts/harness/adversarial.sh` — those two
paths are the digest boundary for site gates.

Site roles (manager, specialist, operations excellence) live under `.cursor/`.
Sealed packets may set `execution_target`: `worktree` (default), `isolated_copy`,
`openshell:<name>`, or `cloud_subagent`. Unknown tokens fail closed. Reserved
OpenShell names `hermes`, `pi`, `eval` are illegal. Never `--editor cursor`.
Isolation green is not a named-gate PASS. Agents never `--actor user`.
Corporate program state stays in a **separate** corporate root; never place
`program.json` here.

See [docs/HOW_IT_WORKS.md](../docs/HOW_IT_WORKS.md) for the corporate↔site flow.
