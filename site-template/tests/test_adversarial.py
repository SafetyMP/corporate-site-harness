"""Authorized local adversarial probes for the site template."""

from pathlib import Path

from siteapp import health


def test_health_rejects_empty_claim() -> None:
    assert health() != ""


def test_harness_scripts_present() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts/harness/verify.sh").is_file()
    assert (root / "scripts/harness/adversarial.sh").is_file()
