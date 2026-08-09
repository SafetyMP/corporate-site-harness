from __future__ import annotations


class ContractError(ValueError):
    """Raised when a workflow contract is invalid."""


# Stage 2 active: corporate_acceptance PASS requires dual evidence (executable + review).
CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS = True
CA_CURRENTNESS_MODE = (
    "dual_evidence_required"
    if CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS
    else "migration_review_only_ok"
)

CORPORATE_ACCEPTANCE_ARGV = ["./scripts/harness/corporate-acceptance.sh"]

GATE_EXECUTION = {
    "corporate_acceptance": ("corporate_acceptance", list(CORPORATE_ACCEPTANCE_ARGV)),
    "site_verify": ("site_verify", ["./scripts/harness/verify.sh"]),
    "operations": ("operations", ["./scripts/harness/verify.sh"]),
    "corporate_review": ("corporate_review", ["./scripts/harness/verify.sh"]),
    "adversary": ("adversarial", ["./scripts/harness/adversarial.sh"]),
}


def assert_migration_currentness_invariant() -> None:
    """N-MW1: dual-evidence currentness requires capture registries first."""
    if (
        CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS
        and "corporate_acceptance" not in GATE_EXECUTION
    ):
        raise ContractError(
            "premature dual-evidence currentness flip without corporate_acceptance capture"
        )


RECAPTURE_DEFERRAL_MARKERS = (
    "fails until recapture",
    "fail later until recapture",
    "fail until recapture",
    "until executable recapture",
)


def is_recapture_deferral_claim(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in RECAPTURE_DEFERRAL_MARKERS)


def assert_recapture_claim_has_capture_path(
    claim: str,
    *,
    gate_execution: dict | None = None,
    evidence_commands: dict | None = None,
) -> None:
    """N-MW2: recapture deferral claims require Stage-1 capture registries."""
    if not is_recapture_deferral_claim(claim):
        return
    ge = gate_execution if gate_execution is not None else GATE_EXECUTION
    if "corporate_acceptance" not in ge:
        raise ContractError(
            "recapture deferral claim requires corporate_acceptance in GATE_EXECUTION"
        )
    if evidence_commands is None:
        raise ContractError(
            "recapture deferral claim requires EVIDENCE_COMMANDS inspection"
        )
    if "corporate_acceptance" not in evidence_commands:
        raise ContractError(
            "recapture deferral claim requires corporate_acceptance in EVIDENCE_COMMANDS"
        )

VERIFICATION_SCRIPTS_RELATIVE = "scripts/harness"
VERIFICATION_SCRIPTS_REQUIRED = frozenset({"verify.sh", "adversarial.sh"})
VERIFICATION_SCRIPTS_OPTIONAL = frozenset({"corporate-acceptance.sh"})
# Backward-compatible alias: required set only (product sites).
VERIFICATION_SCRIPTS_FILES = VERIFICATION_SCRIPTS_REQUIRED

# check --run names bound to corporate program root (not site_path).
CORPORATE_ROOT_EVIDENCE_RUNS = frozenset({"corporate_acceptance"})
