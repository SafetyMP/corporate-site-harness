#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest -q
python3 -m ruff check src tests
