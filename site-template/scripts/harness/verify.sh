#!/usr/bin/env bash
set -euo pipefail

# Fail-closed site-gate oracle hook (ADR-SGO-002). Health stubs are not oracle evidence.
# policy_engine none|cedar|equivalent must be attested; mock evaluators must not PASS.
if [[ -f .corp-harness/site.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
site = json.loads(Path(".corp-harness/site.json").read_text(encoding="utf-8"))
engine = site.get("policy_engine")
if engine not in {"none", "cedar", "equivalent"}:
    raise SystemExit("verify.sh: site.json policy_engine must be none, cedar, or equivalent")
print(f"verify: policy_engine={engine} oracle hook ok")
PY
fi

python3 -m pytest -q
python3 -m ruff check src tests
