from corp_harness.cli import EVIDENCE_COMMANDS
from corp_harness.model import GATE_EXECUTION, VERIFICATION_SCRIPTS_RELATIVE


def test_gate_execution_uses_harness_paths() -> None:
    assert GATE_EXECUTION["site_verify"][1] == ["./scripts/harness/verify.sh"]
    assert GATE_EXECUTION["adversary"][1] == ["./scripts/harness/adversarial.sh"]
    assert EVIDENCE_COMMANDS["smoke"] == ["./scripts/harness/verify.sh"]
    assert EVIDENCE_COMMANDS["adversarial"] == ["./scripts/harness/adversarial.sh"]
    assert VERIFICATION_SCRIPTS_RELATIVE == "scripts/harness"
