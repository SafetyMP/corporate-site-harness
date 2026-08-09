#!/usr/bin/env bash
# Factory adversarial gate: authorized probes + AH collection under bound root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}src"

REQUIRED_AH_TESTS=(
  test_TR_AH_001_d5_seven_theater_fixtures_and_rejection
  test_TR_AH_002_report_event_anti_harness_zeros_and_appends
  test_TR_AH_003_validation_failure_excludes_anti_harness_theater_ids
  test_TR_AH_004_authorized_apply_valid_permit_not_anti_harness
  test_TR_AH_004b_forged_expired_permit_is_theater
  test_TR_AH_004c_clock_rollback_invalidates_permit
  test_TR_AH_005_oob_d8_sole_writer_zeros_trust_with_program_root
  test_TR_AH_005b_oob_enumerated_corporate_artifacts
  test_TR_AH_006_missing_program_root_fail_closed_wrong_root
  test_TR_AH_007_dirty_deferred_scan_consequential_clean_status_non_event
  test_TR_AH_008_stale_factory_authorization_theater
  test_TR_AH_009_wrong_root_operation_theater
  test_TR_AH_010_forbidden_set_score_swift_writer_actor_user
  test_TR_AH_011_verify_adversarial_collect_ah_tests
  test_TR_AH_012_post_log_trust_state_deletion_is_theater
  test_TR_AH_013_disabled_hooks_bound_root_seal_bypass
  test_TR_AH_014_dual_wipe_or_anchor_delete_is_theater
  test_TR_AH_014b_anchor_blocks_false_genesis
  test_TR_AH_015_unbind_program_root_seal_bypass_no_sg03
  test_TR_AH_016_status_and_gated_cli_run_dirty_scan
  test_TR_AH_016b_verify_scripts_require_program_root
  test_TR_AH_017_trust_gated_cli_surfaces
)

# ADR-TR-004 / ACC-TRR-003 (WP-TR-H) — residual falsifiers + keeper.
REQUIRED_TRR_TESTS=(
  test_TRR_001_swift_theater_signal_id_seven
  test_TRR_002_heavy_oserror_gov_required
  test_TRR_002b_assist_oserror_sg03_preserved
  test_TR_D6_004_heavy_empty_stdout_gov_required
)

ensure_program_root_binding() {
  if [[ -n "${CORP_HARNESS_PROGRAM_ROOT:-}" ]]; then
    if [[ ! -f "${CORP_HARNESS_PROGRAM_ROOT}/program.json" ]]; then
      echo "adversarial.sh: CORP_HARNESS_PROGRAM_ROOT must point at a corporate root with program.json" >&2
      exit 1
    fi
  elif [[ -f "${ROOT}/.corp-harness-program-root" ]]; then
    local marker_target
    # Trim leading/trailing whitespace only — preserve spaces inside the path
    # (e.g. ".../Trust Routed Runtime"). Do not strip interior whitespace.
    marker_target="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' <"${ROOT}/.corp-harness-program-root")"
    if [[ -z "${marker_target}" || ! -f "${marker_target}/program.json" ]]; then
      echo "adversarial.sh: .corp-harness-program-root must resolve to a corporate root with program.json" >&2
      exit 1
    fi
  elif [[ "${CORP_HARNESS_REQUIRE_BOUND_ROOT:-}" == "1" ]]; then
    echo "adversarial.sh: program root binding required (CORP_HARNESS_PROGRAM_ROOT or .corp-harness-program-root)" >&2
    exit 1
  fi

  PYTHONPATH=src python3 - "$ROOT" "${CORP_HARNESS_PROGRAM_ROOT:-}" <<'PY'
import os
import tempfile
import sys
from pathlib import Path

from corp_harness import runtime_engine as tre
from corp_harness.model import Program

factory = Path(sys.argv[1]).resolve()
env_root = (sys.argv[2] or "").strip()
marker = factory / tre.PROGRAM_ROOT_MARKER

if env_root:
    corp = Path(env_root).expanduser().resolve()
elif marker.is_file():
    raw = marker.read_text(encoding="utf-8").strip()
    corp = Path(raw).expanduser()
    if not corp.is_absolute():
        corp = (factory / corp).resolve()
    else:
        corp = corp.resolve()
else:
    corp = Path(tempfile.mkdtemp(prefix="corp-harness-ah-adversarial.")).resolve()
    program = Program.create(
        "ah-adversarial-fixture",
        factory,
        ["platform", "quality"],
        program_root=corp,
        program_kind="factory",
    )
    program.save(corp / "program.json")

if not (corp / "program.json").is_file():
    raise SystemExit(f"adversarial.sh: missing program.json under {corp}")

os.environ[tre.PROGRAM_ROOT_ENV] = str(corp)
program = Program.load(corp / "program.json")
tre.update_surface_baseline(corp, factory_root=factory)
result = tre.run_deferred_dirty_scan(
    corp, factory_root=factory, program=program, force=True
)
if result.get("skipped"):
    raise SystemExit("adversarial.sh: deferred dirty scan skipped despite bound root")
print(f"adversarial.sh: bound program root exercised dirty scan at {corp}")
PY
}

ensure_program_root_binding

# Scrub inherited bind env so pytest tmp fixtures remain authoritative.
unset CORP_HARNESS_PROGRAM_ROOT || true

collected="$(python3 -m pytest --collect-only -q tests/test_trust_runtime.py)"
for name in "${REQUIRED_AH_TESTS[@]}" "${REQUIRED_TRR_TESTS[@]}"; do
  if ! grep -q "::${name}$" <<<"${collected}"; then
    echo "adversarial.sh: missing collected AH/TRR test: ${name}" >&2
    exit 1
  fi
done

python3 -m pytest -q tests/test_adversarial.py
python3 -m pytest -q \
  tests/test_trust_runtime.py::test_TR_AH_011_verify_adversarial_collect_ah_tests \
  tests/test_trust_runtime.py::test_TR_AH_015_unbind_program_root_seal_bypass_no_sg03 \
  tests/test_trust_runtime.py::test_TR_AH_016_status_and_gated_cli_run_dirty_scan \
  tests/test_trust_runtime.py::test_TR_AH_016b_verify_scripts_require_program_root \
  tests/test_trust_runtime.py::test_TR_AH_017_trust_gated_cli_surfaces
