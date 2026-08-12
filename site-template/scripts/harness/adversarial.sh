#!/usr/bin/env bash
set -euo pipefail

# Deny-case extension protocol (ADR-SGO-002). Frozen YAML-only replay is insufficient.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
mkdir -p evidence/site-gate-oracles/deny-cases
if [[ ! -f evidence/site-gate-oracles/adversarial-corpus.json ]]; then
  echo "adversarial.sh: missing deny-case extension corpus (evidence/site-gate-oracles/adversarial-corpus.json)" >&2
  exit 1
fi

python3 -m pytest -q tests/test_adversarial.py
