import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "site-template"


def test_site_template_has_lean_role_surface() -> None:
    agents = sorted(path.stem for path in (TEMPLATE / ".cursor/agents").glob("*.md"))

    assert agents == ["operations-excellence", "site-manager", "site-specialist"]
    assert (TEMPLATE / ".cursor/skills/site-delivery/SKILL.md").is_file()
    assert (TEMPLATE / ".cursor/rules/site-contract.mdc").is_file()
    assert not (TEMPLATE / ".cursor/hooks.json").exists()


def test_site_template_commands_are_executable() -> None:
    assert (TEMPLATE / "scripts/harness/verify.sh").stat().st_mode & 0o111
    assert (TEMPLATE / "scripts/harness/adversarial.sh").stat().st_mode & 0o111
    assert (TEMPLATE / "scripts/verify.sh").stat().st_mode & 0o111
    assert (TEMPLATE / "scripts/adversarial.sh").stat().st_mode & 0o111


def test_site_template_config_is_valid_json() -> None:
    config = json.loads((TEMPLATE / ".corp-harness/site.json").read_text())

    assert config["schema"] == "corporate-site-site/v1"
    assert config["verify_argv"] == ["./scripts/harness/verify.sh"]
    assert config["adversarial_argv"] == ["./scripts/harness/adversarial.sh"]
    assert config["policy_engine"] == "none"


def test_SGO_011_template_verify_has_engine_or_na_hook() -> None:
    verify = (TEMPLATE / "scripts/harness/verify.sh").read_text(encoding="utf-8")
    assert "policy_engine" in verify


def test_SGO_011_template_adversarial_has_deny_case_extension_protocol() -> None:
    adversarial = (TEMPLATE / "scripts/harness/adversarial.sh").read_text(encoding="utf-8")
    assert "deny-case" in adversarial or "deny_case" in adversarial
    assert "evidence/site-gate-oracles" in adversarial


def test_SGO_011_template_always_green_stub_not_oracle_evidence() -> None:
    adversarial = (TEMPLATE / "scripts/harness/adversarial.sh").read_text(encoding="utf-8")
    assert "adversarial-corpus.json" in adversarial
    assert "exit 0" not in adversarial.split("pytest")[0] or "missing deny-case" in adversarial


def test_site_template_docs_prescribe_harness_verification_scripts() -> None:
    agents = (TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
    skill = (TEMPLATE / ".cursor/skills/site-delivery/SKILL.md").read_text(encoding="utf-8")
    plugin_skill = (
        ROOT
        / "corporate/plugin/corporate-site-harness/skills/site-delivery/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "scripts/harness/verify.sh" in agents
    assert "verification_scripts" in agents
    assert "scripts/harness" in skill
    assert "scripts/harness" in plugin_skill
    assert "whole `scripts/`" in plugin_skill
