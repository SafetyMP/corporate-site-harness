#!/usr/bin/env bash
# Corporate-acceptance capture oracle for corp-harness check --run corporate_acceptance.
# Intended cwd is the corporate program root (see ADR-CAFR-002). Exits non-zero if
# program.json is absent so accidental site-root runs fail closed.
set -euo pipefail

if [[ ! -f program.json ]]; then
  echo "corporate-acceptance: program.json missing in cwd=$(pwd)" >&2
  exit 1
fi

python3 - <<'PY'
import json
from pathlib import Path

program = json.loads(Path("program.json").read_text(encoding="utf-8"))
if not isinstance(program, dict) or "program_id" not in program:
    raise SystemExit("corporate-acceptance: program.json missing program_id")
print(f"corporate_acceptance capture ok program_id={program['program_id']}")
PY
