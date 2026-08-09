from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from corp_harness.contracts import (
    CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS,
    GATE_EXECUTION,
    VERIFICATION_SCRIPTS_FILES,
    VERIFICATION_SCRIPTS_OPTIONAL,
    VERIFICATION_SCRIPTS_RELATIVE,
    VERIFICATION_SCRIPTS_REQUIRED,
    ContractError,
)
from corp_harness.evidence_validation import (
    enforce_pass_evidence_classes,
    executable_evidence_root,
)

# Facade re-export anchors (currentness flag lives in contracts.py).
assert VERIFICATION_SCRIPTS_FILES == VERIFICATION_SCRIPTS_REQUIRED

SCHEMA = "corporate-site-program/v1"
SITE_SCHEMA = "corporate-site-site/v1"
FACTORY_AUTH_SCHEMA = "corporate-site-factory-authorization/v1"
PROGRAM_KINDS = frozenset({"product", "factory"})
# User-gated artifacts/transitions only; agents must not forge --actor user (TR-14).
USER_GATED_ARTIFACTS = frozenset({"factory_authorization", "user_approval"})
PHASES = (
    "DESIGN",
    "CORPORATE_ACCEPTANCE",
    "SITE_DELIVERY",
    "SITE_VERIFICATION",
    "CORPORATE_REVIEW",
    "ADVERSARY",
    "AWAITING_USER_APPROVAL",
    "APPROVED",
)

FORWARD_TRANSITIONS = {
    ("DESIGN", "CORPORATE_ACCEPTANCE"): "ceo",
    ("CORPORATE_ACCEPTANCE", "SITE_DELIVERY"): "coo",
    ("SITE_DELIVERY", "SITE_VERIFICATION"): "site-manager",
    ("SITE_VERIFICATION", "CORPORATE_REVIEW"): "operations-excellence",
    ("CORPORATE_REVIEW", "ADVERSARY"): "corporate-specialist",
    ("ADVERSARY", "AWAITING_USER_APPROVAL"): "ceo",
    ("AWAITING_USER_APPROVAL", "APPROVED"): "user",
}

REWORK_ACTORS = {
    "CORPORATE_ACCEPTANCE": "coo",
    "SITE_VERIFICATION": "operations-excellence",
    "CORPORATE_REVIEW": "corporate-specialist",
    "ADVERSARY": "corporate-adversary",
    "AWAITING_USER_APPROVAL": "user",
    "APPROVED": "user",
}
USER_REOPEN_PHASES = frozenset({"AWAITING_USER_APPROVAL", "APPROVED"})
MIGRATION_REDESIGN_PHASES = frozenset(
    {
        "AWAITING_USER_APPROVAL",
        "APPROVED",
        "SITE_DELIVERY",
        "SITE_VERIFICATION",
        "CORPORATE_REVIEW",
        "ADVERSARY",
    }
)
MIGRATION_UNREGISTER_ARTIFACTS = (
    "master_spec",
    "acceptance",
    "factory_authorization",
    "user_approval",
    "final_dossier",
    "corporate_handoff",
)

REQUIRED_ARTIFACTS = {
    "CORPORATE_ACCEPTANCE": ("master_spec", "acceptance"),
    "SITE_DELIVERY": ("master_spec", "acceptance", "corporate_handoff"),
    "SITE_VERIFICATION": (
        "adr:*",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "CORPORATE_REVIEW": (
        "adr:*",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "ADVERSARY": (
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "AWAITING_USER_APPROVAL": ("implementation", "final_dossier"),
    "APPROVED": ("implementation", "final_dossier", "user_approval"),
}

REQUIRED_GATES = {
    "SITE_DELIVERY": ("corporate_acceptance",),
    "SITE_VERIFICATION": ("corporate_acceptance",),
    "CORPORATE_REVIEW": ("corporate_acceptance", "site_verify", "operations"),
    "ADVERSARY": (
        "corporate_acceptance",
        "site_verify",
        "operations",
        "corporate_review",
    ),
    "AWAITING_USER_APPROVAL": (
        "corporate_acceptance",
        "site_verify",
        "operations",
        "corporate_review",
        "adversary",
    ),
    "APPROVED": (
        "corporate_acceptance",
        "site_verify",
        "operations",
        "corporate_review",
        "adversary",
    ),
}

GATE_TARGETS = {
    "corporate_acceptance": ("master_spec", "acceptance"),
    "site_verify": (
        "master_spec",
        "acceptance",
        "corporate_handoff",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "operations": (
        "master_spec",
        "acceptance",
        "corporate_handoff",
        "adr:*",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "corporate_review": (
        "master_spec",
        "acceptance",
        "corporate_handoff",
        "adr:*",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
    "adversary": (
        "master_spec",
        "acceptance",
        "corporate_handoff",
        "adr:*",
        "implementation",
        "verification",
        "verification_scripts",
        "runtime_manifest",
    ),
}

GATE_ROLES = {
    "corporate_acceptance": "coo",
    "site_verify": "operations-excellence",
    "operations": "operations-excellence",
    "corporate_review": "corporate-specialist",
    "adversary": "corporate-adversary",
}

GATE_PHASES = {
    "corporate_acceptance": "CORPORATE_ACCEPTANCE",
    "site_verify": "SITE_VERIFICATION",
    "operations": "SITE_VERIFICATION",
    "corporate_review": "CORPORATE_REVIEW",
    "adversary": "ADVERSARY",
}

ARTIFACT_ROLES = {
    "master_spec": "ceo",
    "acceptance": "ceo",
    "corporate_handoff": "coo",
    "implementation": "site-specialist",
    "verification": "site-specialist",
    "verification_scripts": "site-specialist",
    "runtime_manifest": "site-specialist",
    "final_dossier": "ceo",
    "user_approval": "user",
    "factory_authorization": "user",
}

IGNORED_DIGEST_PARTS = {
    ".git",
    ".corp-harness",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str
    revision: int
    producer_role: str


@dataclass(frozen=True)
class Gate:
    status: str
    report_path: str
    report_sha256: str
    target_sha256: str
    revision: int
    reviewer_role: str


@dataclass
class Program:
    program_id: str
    site_path: str
    generation: int = 0
    phase: str = "DESIGN"
    revision: int = 1
    attempts: int = 0
    max_attempts: int = 3
    selected_domains: list[str] = field(default_factory=list)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    gates: dict[str, Gate] = field(default_factory=dict)
    schema: str = SCHEMA
    program_kind: str = "product"
    execution_policy: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        program_id: str,
        site_path: Path,
        selected_domains: list[str] | None = None,
        *,
        program_root: Path | None = None,
        program_kind: str = "product",
    ) -> Program:
        if not program_id or any(char.isspace() for char in program_id):
            raise ContractError("program_id must be a non-empty, whitespace-free identifier")
        if program_kind not in PROGRAM_KINDS:
            raise ContractError(f"unsupported program_kind: {program_kind!r}")
        resolved_site = site_path.expanduser().resolve()
        if not resolved_site.is_dir():
            raise ContractError(f"site path is not a directory: {resolved_site}")
        if (resolved_site / "program.json").is_file():
            raise ContractError(
                f"site path contains program.json; refuse corporate root as site: {resolved_site}"
            )
        if program_kind == "factory" and not is_factory_root(resolved_site):
            raise ContractError(
                "factory programs require site_path to be a factory root "
                "(src/corp_harness + corporate/plugin/corporate-site-harness)"
            )
        _validate_optional_site_manifest(resolved_site)
        if program_root is not None:
            require_separate_roots(program_root, resolved_site)
        return cls(
            program_id=program_id,
            site_path=str(resolved_site),
            selected_domains=sorted(set(selected_domains or [])),
            program_kind=program_kind,
        )

    @classmethod
    def load(cls, path: Path) -> Program:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("program root must be an object")
            if raw.get("schema") != SCHEMA:
                raise ContractError(f"unsupported program schema: {raw.get('schema')!r}")
            if raw.get("phase") not in PHASES:
                raise ContractError(f"unknown phase: {raw.get('phase')!r}")
            artifacts_raw = raw.get("artifacts", {})
            gates_raw = raw.get("gates", {})
            if not isinstance(artifacts_raw, dict) or not isinstance(gates_raw, dict):
                raise TypeError("artifacts and gates must be objects")
            artifacts = {str(name): Artifact(**value) for name, value in artifacts_raw.items()}
            gates = {str(name): Gate(**value) for name, value in gates_raw.items()}
            program_kind = str(raw.get("program_kind", "product"))
            if program_kind not in PROGRAM_KINDS:
                raise ContractError(f"unsupported program_kind: {program_kind!r}")
            execution_policy_raw = raw.get("execution_policy")
            execution_policy = None
            if execution_policy_raw is not None:
                # Lazy import: execution_policy imports ContractError from this module.
                from corp_harness.execution_policy import (  # noqa: PLC0415
                    validate_execution_policy,
                )

                execution_policy = validate_execution_policy(execution_policy_raw)
            program = cls(
                schema=str(raw["schema"]),
                program_id=str(raw["program_id"]),
                site_path=str(raw["site_path"]),
                generation=int(raw.get("generation", 0)),
                phase=str(raw["phase"]),
                revision=int(raw["revision"]),
                attempts=int(raw.get("attempts", 0)),
                max_attempts=int(raw.get("max_attempts", 3)),
                selected_domains=[str(value) for value in raw.get("selected_domains", [])],
                artifacts=artifacts,
                gates=gates,
                program_kind=program_kind,
                execution_policy=execution_policy,
            )
            program.validate_structure(path.parent.resolve())
            return program
        except ContractError:
            raise
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read program: {exc}") from exc

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current_generation = 0
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    current_generation = int(current.get("generation", 0))
                except (
                    AttributeError,
                    OSError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    raise ContractError(f"cannot compare program generation: {exc}") from exc
            if current_generation != self.generation:
                raise ContractError(
                    "program changed concurrently; reload before recording new state"
                )
            next_generation = self.generation + 1
            payload = self.to_dict()
            payload["generation"] = next_generation
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    delete=False,
                ) as temporary:
                    temporary_name = temporary.name
                    json.dump(payload, temporary, indent=2, sort_keys=True)
                    temporary.write("\n")
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, path)
                self.generation = next_generation
            finally:
                if temporary_name and Path(temporary_name).exists():
                    Path(temporary_name).unlink()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("execution_policy") is None:
            payload.pop("execution_policy", None)
        return payload

    def validate_structure(self, program_root: Path) -> None:
        if not self.program_id or any(char.isspace() for char in self.program_id):
            raise ContractError("program_id must be a non-empty, whitespace-free identifier")
        if self.program_kind not in PROGRAM_KINDS:
            raise ContractError(f"unsupported program_kind: {self.program_kind!r}")
        if self.revision < 1 or self.generation < 0:
            raise ContractError("program revision and generation are invalid")
        if not 1 <= self.max_attempts <= 5 or not 0 <= self.attempts <= self.max_attempts:
            raise ContractError("program attempt budget is invalid")
        if self.execution_policy is not None:
            # Lazy import: execution_policy imports ContractError from this module.
            from corp_harness.execution_policy import (  # noqa: PLC0415
                validate_execution_policy,
            )

            self.execution_policy = validate_execution_policy(self.execution_policy)
        site_root = _resolve_without_symlinks(Path(self.site_path))
        if not site_root.is_dir():
            raise ContractError(f"site path is not a directory: {site_root}")
        if self.program_kind == "factory" and not is_factory_root(site_root):
            raise ContractError(
                "factory programs require site_path to be a factory root "
                "(src/corp_harness + corporate/plugin/corporate-site-harness)"
            )
        for name, artifact in self.artifacts.items():
            expected_role = _artifact_role(name)
            if expected_role is not None and artifact.producer_role != expected_role:
                raise ContractError(f"{name} must be produced by {expected_role}")
            if artifact.revision < 1 or artifact.revision > self.revision:
                raise ContractError(f"artifact {name} has an invalid revision")
            if not _is_sha256(artifact.sha256):
                raise ContractError(f"artifact {name} has an invalid digest")
            resolved = _resolve_without_symlinks(Path(artifact.path))
            _require_allowed_path(resolved, program_root, site_root)
            if name == "user_approval":
                _validate_user_approval(resolved, self)
            if name == "factory_authorization":
                if self.program_kind != "factory":
                    raise ContractError(
                        "factory_authorization is only valid for factory programs"
                    )
                _validate_factory_authorization(resolved, self)
        for name, gate in self.gates.items():
            if name not in GATE_TARGETS:
                raise ContractError(f"unknown persisted gate: {name}")
            if gate.reviewer_role != GATE_ROLES[name]:
                raise ContractError(f"{name} must be reviewed by {GATE_ROLES[name]}")
            if gate.status not in {"PASS", "FAIL"}:
                raise ContractError(f"{name} has an invalid status")
            if gate.revision < 1 or gate.revision > self.revision:
                raise ContractError(f"{name} has an invalid revision")
            if not _is_sha256(gate.report_sha256) or not _is_sha256(gate.target_sha256):
                raise ContractError(f"{name} has an invalid digest")
            report_path = _resolve_without_symlinks(Path(gate.report_path))
            if report_path != program_root and program_root not in report_path.parents:
                raise ContractError("gate reports must be stored in the corporate program root")
            report = _load_gate_report(report_path)
            if (
                report["gate"] != name
                or report["reviewer_role"] != gate.reviewer_role
                or report["status"] != gate.status
                or report["revision"] != gate.revision
                or report["target_sha256"] != gate.target_sha256
            ):
                raise ContractError(f"persisted gate metadata mismatch: {name}")
            producers = {
                artifact.producer_role for artifact in self._target_artifacts(name).values()
            }
            if gate.reviewer_role in producers:
                raise ContractError("an artifact producer cannot approve its own work")
            _validate_evidence_refs(
                report["evidence_refs"],
                program_root,
                site_root,
                name,
                gate.status,
                gate.revision,
                gate.target_sha256,
                gate.reviewer_role,
                require_current=False,
            )

    def record_artifact(
        self,
        name: str,
        artifact_path: Path,
        producer_role: str,
        program_root: Path,
    ) -> Artifact:
        if not name or not producer_role:
            raise ContractError("artifact name and producer role are required")
        expected_role = _artifact_role(name)
        if expected_role is not None and producer_role != expected_role:
            raise ContractError(f"{name} must be produced by {expected_role}")
        resolved = _resolve_without_symlinks(artifact_path)
        site_root = Path(self.site_path)
        _require_allowed_path(resolved, program_root.resolve(), site_root)
        if name == "verification_scripts":
            _validate_verification_scripts(resolved, site_root)
        digest = digest_path(resolved)
        artifact = Artifact(
            path=str(resolved),
            sha256=digest,
            revision=self.revision,
            producer_role=producer_role,
        )
        if name == "user_approval":
            _validate_user_approval(resolved, self)
        if name == "factory_authorization":
            if self.program_kind != "factory":
                raise ContractError("factory_authorization is only valid for factory programs")
            _validate_factory_authorization(resolved, self)
        self.artifacts[name] = artifact
        return artifact

    def record_gate(
        self,
        name: str,
        status_value: str,
        report_path: Path,
        reviewer_role: str,
        program_root: Path,
    ) -> Gate:
        if name not in GATE_TARGETS:
            raise ContractError(f"unknown gate: {name}")
        if self.phase != GATE_PHASES[name]:
            raise ContractError(f"{name} may only be recorded during {GATE_PHASES[name]}")
        expected_role = GATE_ROLES[name]
        if reviewer_role != expected_role:
            raise ContractError(f"{name} must be reviewed by {expected_role}")
        targets = self._target_artifacts(name)
        if not targets:
            raise ContractError(f"{name} has no current target artifacts")
        if any(digest_path(Path(item.path)) != item.sha256 for item in targets.values()):
            raise ContractError(f"{name} target artifacts are stale")
        producers = {artifact.producer_role for artifact in targets.values()}
        if reviewer_role in producers:
            raise ContractError("an artifact producer cannot approve its own work")
        resolved_report = _resolve_without_symlinks(report_path)
        resolved_root = program_root.resolve()
        if resolved_report != resolved_root and resolved_root not in resolved_report.parents:
            raise ContractError("gate reports must be stored in the corporate program root")
        target_sha256 = _artifact_map_digest(targets)
        report = _load_gate_report(resolved_report)
        if report["gate"] != name:
            raise ContractError(f"gate report is for {report['gate']}, not {name}")
        if report["reviewer_role"] != expected_role or reviewer_role != report["reviewer_role"]:
            raise ContractError(f"{name} report must be authored by {expected_role}")
        report_status = report["status"]
        if status_value.upper() != report_status:
            raise ContractError("CLI gate status does not match the signed report status")
        if report["revision"] != self.revision:
            raise ContractError("gate report revision does not match current program revision")
        if report["target_sha256"] != target_sha256:
            raise ContractError("gate report target digest does not match current artifacts")
        _validate_evidence_refs(
            report["evidence_refs"],
            resolved_root,
            Path(self.site_path),
            name,
            report_status,
            self.revision,
            target_sha256,
            reviewer_role,
            require_current=True,
        )
        gate = Gate(
            status=report_status,
            report_path=str(resolved_report),
            report_sha256=digest_path(resolved_report),
            target_sha256=target_sha256,
            revision=self.revision,
            reviewer_role=reviewer_role,
        )
        self.gates[name] = gate
        return gate

    def gate_target_digest(self, name: str) -> str:
        if name not in GATE_TARGETS:
            raise ContractError(f"unknown gate: {name}")
        targets = self._target_artifacts(name)
        if not targets:
            raise ContractError(f"{name} has no current target artifacts")
        return _artifact_map_digest(targets)

    def advance(self, target_phase: str, actor_role: str) -> None:
        expected_role = FORWARD_TRANSITIONS.get((self.phase, target_phase))
        if expected_role is None:
            raise ContractError(f"transition not allowed: {self.phase} -> {target_phase}")
        if actor_role != expected_role:
            raise ContractError(f"transition requires role {expected_role}")
        issues = self.phase_requirements(target_phase)
        if issues:
            raise ContractError("; ".join(issues))
        self.phase = target_phase

    def migration_redesign_eligible(self, actor_role: str) -> bool:
        """Stage-2 user-only migrate-to-DESIGN when CA is missing or not current."""
        if not CORPORATE_ACCEPTANCE_REQUIRE_EXECUTABLE_CURRENTNESS:
            return False
        if actor_role != "user":
            return False
        if self.phase not in MIGRATION_REDESIGN_PHASES:
            return False
        gate = self.gates.get("corporate_acceptance")
        if gate is None:
            return True
        return not self.gate_is_current("corporate_acceptance")

    def rework(self, actor_role: str) -> None:
        # ADR-CAFR-006 / ACC-MIG-001: migration short-circuits before REWORK_ACTORS.
        if self.migration_redesign_eligible(actor_role):
            # Does not consume review attempt budget.
            self.revision += 1
            self.phase = "DESIGN"
            self.gates = {}
            for name in MIGRATION_UNREGISTER_ARTIFACTS:
                self.artifacts.pop(name, None)
            return

        expected_role = REWORK_ACTORS.get(self.phase)
        if expected_role is None:
            raise ContractError(f"rework is not allowed from {self.phase}")
        if actor_role != expected_role:
            raise ContractError(f"rework from {self.phase} requires role {expected_role}")
        if self.phase == "CORPORATE_ACCEPTANCE":
            gate = self.gates.get("corporate_acceptance")
            if gate is None:
                raise ContractError("corporate_acceptance gate is required for rework")
            if gate.status != "FAIL":
                raise ContractError("corporate_acceptance rework requires a FAIL gate")
            if gate.revision != self.revision:
                raise ContractError(
                    "corporate_acceptance gate revision does not match program revision"
                )
            if not self.gate_is_current("corporate_acceptance"):
                raise ContractError("corporate_acceptance gate is not current")
            if self.attempts >= self.max_attempts:
                raise ContractError("review attempt budget exhausted; escalate to the user")
            self.attempts += 1
            self.revision += 1
            self.phase = "DESIGN"
            self.gates = {}
            for name in ("master_spec", "acceptance", "factory_authorization"):
                self.artifacts.pop(name, None)
            return
        user_reopen = self.phase in USER_REOPEN_PHASES
        if user_reopen:
            # User reopen for migration/re-gate does not consume review budget.
            self.artifacts.pop("user_approval", None)
            self.artifacts.pop("final_dossier", None)
        else:
            if self.attempts >= self.max_attempts:
                raise ContractError("review attempt budget exhausted; escalate to the user")
            self.attempts += 1
        self.revision += 1
        self.phase = "SITE_DELIVERY"
        self.gates = {
            name: gate for name, gate in self.gates.items() if name == "corporate_acceptance"
        }

    def phase_requirements(self, phase: str) -> list[str]:
        issues: list[str] = []
        requirements = list(REQUIRED_ARTIFACTS.get(phase, ()))
        if self.program_kind == "factory" and phase == "CORPORATE_ACCEPTANCE":
            if "factory_authorization" not in requirements:
                requirements.append("factory_authorization")
        for requirement in requirements:
            matching = self._matching_artifacts(requirement)
            if not matching:
                issues.append(f"missing artifact {requirement}")
                continue
            for name, artifact in matching.items():
                try:
                    if digest_path(Path(artifact.path)) != artifact.sha256:
                        issues.append(f"artifact {name} is stale")
                except ContractError:
                    issues.append(f"artifact {name} is stale")
                if name == "factory_authorization":
                    try:
                        _validate_factory_authorization(Path(artifact.path), self)
                    except ContractError:
                        issues.append("artifact factory_authorization is stale")
        for gate_name in REQUIRED_GATES.get(phase, ()):
            gate = self.gates.get(gate_name)
            if gate is None:
                issues.append(f"missing gate {gate_name}")
            elif gate.status != "PASS":
                issues.append(f"gate {gate_name} is {gate.status}")
            elif not self.gate_is_current(gate_name):
                issues.append(f"gate {gate_name} is stale")
        return issues

    def gate_is_current(self, name: str) -> bool:
        gate = self.gates.get(name)
        if gate is None:
            return False
        try:
            if digest_path(Path(gate.report_path)) != gate.report_sha256:
                return False
            report = _load_gate_report(Path(gate.report_path))
            if (
                report["gate"] != name
                or report["reviewer_role"] != gate.reviewer_role
                or report["status"] != gate.status
                or report["revision"] != gate.revision
                or report["target_sha256"] != gate.target_sha256
            ):
                return False
            if not _evidence_refs_current(
                report["evidence_refs"],
                Path(gate.report_path).parent,
                Path(self.site_path),
                name,
                gate.status,
                gate.revision,
                gate.target_sha256,
                gate.reviewer_role,
            ):
                return False
            targets = self._target_artifacts(name)
            return bool(targets) and _artifact_map_digest(targets) == gate.target_sha256
        except ContractError:
            return False

    def current_issues(self, *, program_root: Path | None = None) -> list[str]:
        issues: list[str] = []
        if program_root is not None:
            try:
                require_separate_roots(program_root, Path(self.site_path))
            except ContractError as exc:
                issues.append(str(exc))
        if not Path(self.site_path).is_dir():
            issues.append(f"site path missing: {self.site_path}")
        for name, artifact in self.artifacts.items():
            try:
                if digest_path(Path(artifact.path)) != artifact.sha256:
                    issues.append(f"artifact {name} is stale")
            except ContractError as exc:
                issues.append(f"artifact {name}: {exc}")
            if name == "verification_scripts":
                try:
                    _validate_verification_scripts(Path(artifact.path), Path(self.site_path))
                except ContractError as exc:
                    issues.append(f"artifact verification_scripts: {exc}")
            if name == "factory_authorization":
                try:
                    _validate_factory_authorization(Path(artifact.path), self)
                except ContractError as exc:
                    issues.append(f"artifact factory_authorization: {exc}")
        for name in self.gates:
            if not self.gate_is_current(name):
                issues.append(f"gate {name} is stale")
        if self.phase != "DESIGN":
            issues.extend(self.phase_requirements(self.phase))
        elif self.program_kind == "factory" and "master_spec" in self.artifacts:
            auth = self.artifacts.get("factory_authorization")
            if auth is None:
                issues.append("missing artifact factory_authorization")
            else:
                try:
                    if digest_path(Path(auth.path)) != auth.sha256:
                        issues.append("artifact factory_authorization is stale")
                    else:
                        _validate_factory_authorization(Path(auth.path), self)
                except ContractError:
                    issues.append("artifact factory_authorization is stale")
        return sorted(set(issues))

    def _matching_artifacts(self, requirement: str) -> dict[str, Artifact]:
        if requirement.endswith(":*"):
            prefix = requirement[:-1]
            return {
                name: artifact
                for name, artifact in self.artifacts.items()
                if name.startswith(prefix)
            }
        artifact = self.artifacts.get(requirement)
        return {requirement: artifact} if artifact is not None else {}

    def _target_artifacts(self, gate_name: str) -> dict[str, Artifact]:
        targets: dict[str, Artifact] = {}
        for requirement in GATE_TARGETS[gate_name]:
            targets.update(self._matching_artifacts(requirement))
        return targets


def _allowed_evidence_argv(gate_name: str, *, require_current: bool) -> list[list[str]]:
    _, expected_argv = GATE_EXECUTION[gate_name]
    if gate_name == "corporate_acceptance":
        # Canonical argv only — never alias to ./scripts/verify.sh.
        return [list(expected_argv)]
    if require_current:
        return [list(expected_argv)]
    if gate_name == "adversary":
        return [list(expected_argv), ["./scripts/adversarial.sh"]]
    return [list(expected_argv), ["./scripts/verify.sh"]]


def _validate_verification_scripts(path: Path, site_root: Path) -> None:
    resolved = _resolve_without_symlinks(path)
    site = _resolve_without_symlinks(site_root)
    try:
        relative = resolved.relative_to(site)
    except ValueError as exc:
        raise ContractError(
            "verification_scripts must bind exactly to site-relative scripts/harness"
        ) from exc
    if relative.as_posix() != VERIFICATION_SCRIPTS_RELATIVE:
        raise ContractError(
            "verification_scripts must bind exactly to site-relative scripts/harness"
        )
    info = resolved.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ContractError(f"symlink is not allowed: {resolved}")
    if not resolved.is_dir():
        raise ContractError("verification_scripts must be the scripts/harness directory")
    names: set[str] = set()
    for item in sorted(resolved.iterdir()):
        item_info = item.lstat()
        if stat.S_ISLNK(item_info.st_mode):
            raise ContractError(f"symlink is not allowed: {item}")
        if item.is_dir():
            raise ContractError(
                "verification_scripts scripts/harness must not contain subdirectories"
            )
        if not item.is_file():
            raise ContractError(
                f"verification_scripts scripts/harness has unsupported entry: {item.name}"
            )
        names.add(item.name)
    allowed = VERIFICATION_SCRIPTS_REQUIRED | VERIFICATION_SCRIPTS_OPTIONAL
    if not VERIFICATION_SCRIPTS_REQUIRED.issubset(names):
        raise ContractError(
            "verification_scripts scripts/harness must contain required "
            "verify.sh and adversarial.sh"
        )
    if not names.issubset(allowed):
        raise ContractError(
            "verification_scripts scripts/harness may only contain "
            "verify.sh, adversarial.sh, and optional corporate-acceptance.sh"
        )


def digest_path(path: Path) -> str:
    resolved = _resolve_without_symlinks(path)
    if not resolved.exists():
        raise ContractError(f"path does not exist: {resolved}")
    info = resolved.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ContractError(f"symlink is not allowed: {resolved}")
    digest = hashlib.sha256()
    if resolved.is_file():
        _update_stat_digest(digest, ".", info, "file")
        digest.update(resolved.read_bytes())
        return digest.hexdigest()
    if not resolved.is_dir():
        raise ContractError(f"unsupported artifact type: {resolved}")
    _update_stat_digest(digest, ".", info, "directory")
    for item in sorted(resolved.rglob("*")):
        rel = item.relative_to(resolved)
        if any(part in IGNORED_DIGEST_PARTS for part in rel.parts):
            continue
        item_info = item.lstat()
        if stat.S_ISLNK(item_info.st_mode):
            raise ContractError(f"symlink is not allowed: {item}")
        kind = "directory" if item.is_dir() else "file"
        _update_stat_digest(digest, rel.as_posix(), item_info, kind)
        if item.is_file():
            digest.update(item.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _artifact_map_digest(artifacts: dict[str, Artifact]) -> str:
    digest = hashlib.sha256()
    for name, artifact in sorted(artifacts.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(digest_path(Path(artifact.path)).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _update_stat_digest(
    digest: Any,
    relative_path: str,
    info: os.stat_result,
    kind: str,
) -> None:
    digest.update(relative_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(kind.encode("ascii"))
    digest.update(b"\0")
    digest.update(str(stat.S_IMODE(info.st_mode)).encode("ascii"))
    digest.update(b"\0")


def _artifact_role(name: str) -> str | None:
    if name.startswith("adr:"):
        return "site-specialist"
    return ARTIFACT_ROLES.get(name)


def _validate_user_approval(path: Path, program: Program) -> None:
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(approval, dict):
            raise TypeError("approval root must be an object")
        if approval.get("schema") != "corporate-site-user-approval/v1":
            raise ValueError("unsupported user approval schema")
        if approval.get("approved") is not True or approval.get("granted_by") != "user":
            raise ValueError("approval must be explicitly granted by the user")
        if approval.get("program_id") != program.program_id:
            raise ValueError("approval program does not match")
        if int(approval.get("revision")) != program.revision:
            raise ValueError("approval revision does not match")
        dossier = program.artifacts.get("final_dossier")
        if dossier is None or approval.get("final_dossier_sha256") != dossier.sha256:
            raise ValueError("approval is not bound to the current final dossier")
        gate_digests = {name: gate.report_sha256 for name, gate in sorted(program.gates.items())}
        if approval.get("gate_report_sha256") != gate_digests:
            raise ValueError("approval is not bound to the current gate reports")
        if not isinstance(approval.get("granted_at"), str) or not approval["granted_at"]:
            raise ValueError("approval timestamp is required")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid user approval {path}: {exc}") from exc


def is_factory_root(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return (resolved / "src" / "corp_harness").is_dir() and (
        resolved / "corporate" / "plugin" / "corporate-site-harness"
    ).is_dir()


def require_separate_roots(program_root: Path, site_path: Path) -> None:
    """Reject identical or nested corporate/site roots for every program kind."""
    resolved_root = program_root.expanduser().resolve()
    resolved_site = site_path.expanduser().resolve()
    if _paths_nested(resolved_root, resolved_site):
        raise ContractError(
            "program_root and site_path must not be the same or nested; "
            "keep corporate and site roots separate"
        )


def _validate_factory_authorization(path: Path, program: Program) -> None:
    try:
        authorization = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(authorization, dict):
            raise TypeError("authorization root must be an object")
        if authorization.get("schema") != FACTORY_AUTH_SCHEMA:
            raise ValueError("unsupported factory authorization schema")
        if (
            authorization.get("authorized") is not True
            or authorization.get("granted_by") != "user"
        ):
            raise ValueError("authorization must be explicitly granted by the user")
        if authorization.get("program_id") != program.program_id:
            raise ValueError("authorization program does not match")
        if int(authorization.get("revision")) != program.revision:
            raise ValueError("authorization revision does not match")
        master = program.artifacts.get("master_spec")
        if master is None or authorization.get("master_spec_sha256") != master.sha256:
            raise ValueError("authorization is not bound to the current master spec")
        factory_root = Path(program.site_path).expanduser().resolve()
        auth_root = Path(str(authorization.get("factory_root", ""))).expanduser().resolve()
        if auth_root != factory_root:
            raise ValueError("factory_root does not match program site_path")
        surfaces = authorization.get("authorized_surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            raise ValueError("authorized_surfaces must be a non-empty list")
        for surface in surfaces:
            if not isinstance(surface, str) or not surface.strip():
                raise ValueError("authorized_surfaces entries must be non-empty strings")
            if surface.startswith("/") or ".." in Path(surface).parts:
                raise ValueError(f"authorized surface must be a relative path: {surface}")
            resolved_surface = (factory_root / surface).resolve()
            try:
                resolved_surface.relative_to(factory_root)
            except ValueError as exc:
                raise ValueError(
                    f"authorized surface escapes factory root: {surface}"
                ) from exc
        if not isinstance(authorization.get("granted_at"), str) or not authorization[
            "granted_at"
        ]:
            raise ValueError("authorization timestamp is required")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid factory authorization {path}: {exc}") from exc


def _load_gate_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise TypeError("gate report root must be an object")
        required = {
            "schema",
            "gate",
            "reviewer_role",
            "status",
            "revision",
            "target_sha256",
            "evidence_refs",
        }
        missing = sorted(required - set(report))
        if missing:
            raise KeyError(", ".join(missing))
        if report["schema"] != "corporate-site-gate/v1":
            raise ValueError("unsupported gate report schema")
        if report["status"] not in {"PASS", "FAIL"}:
            raise ValueError("gate report status must be PASS or FAIL")
        if not isinstance(report["evidence_refs"], list) or not report["evidence_refs"]:
            raise TypeError("gate report evidence_refs must be a non-empty list")
        report["revision"] = int(report["revision"])
        return report
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid gate report {path}: {exc}") from exc


def _validate_evidence_refs(
    evidence_refs: list[Any],
    program_root: Path,
    site_root: Path,
    gate_name: str,
    gate_status: str,
    revision: int,
    target_sha256: str,
    reviewer_role: str,
    *,
    require_current: bool,
) -> None:
    saw_executable = False
    saw_executable_ref = False
    saw_review = False
    saw_failure = False
    for item in evidence_refs:
        if not isinstance(item, dict):
            raise ContractError("gate evidence references must be objects")
        path_value = item.get("path")
        expected_digest = item.get("sha256")
        if not isinstance(path_value, str) or not isinstance(expected_digest, str):
            raise ContractError("gate evidence references require path and sha256 strings")
        path = _resolve_without_symlinks(Path(path_value))
        _require_allowed_path(path, program_root, site_root)
        if not _is_sha256(expected_digest):
            raise ContractError("gate evidence reference has an invalid digest")
        if require_current and digest_path(path) != expected_digest:
            raise ContractError(f"gate evidence is stale: {path}")
        evidence = _load_evidence_record(path)
        if evidence["schema"] == "corporate-site-evidence/v1":
            saw_executable_ref = True
            if evidence["revision"] != revision or evidence["target_sha256"] != target_sha256:
                raise ContractError("executable evidence is bound to a different revision")
            expected_name, expected_argv = GATE_EXECUTION[gate_name]
            allowed_argv = _allowed_evidence_argv(gate_name, require_current=require_current)
            if evidence["name"] != expected_name or evidence["argv"] not in allowed_argv:
                raise ContractError("executable evidence command does not match the gate")
            expected_root = executable_evidence_root(gate_name, program_root, site_root)
            if Path(evidence["cwd"]).resolve() != expected_root:
                raise ContractError("executable evidence command does not match the gate")
            evidence_argv = list(evidence["argv"])
            evidence_executable = (expected_root / evidence_argv[0]).resolve()
            if Path(evidence["executable_path"]).resolve() != evidence_executable:
                raise ContractError("executable evidence command does not match the gate")
            if require_current:
                # New gate recordings must use canonical harness argv and live digest.
                if (
                    evidence_argv != expected_argv
                    or evidence["executable_sha256"] != digest_path(evidence_executable)
                ):
                    raise ContractError("executable evidence command does not match the gate")
            if hashlib.sha256(evidence["stdout"].encode("utf-8")).hexdigest() != evidence[
                "stdout_sha256"
            ] or hashlib.sha256(evidence["stderr"].encode("utf-8")).hexdigest() != evidence[
                "stderr_sha256"
            ]:
                raise ContractError("executable evidence output digest is invalid")
            passed = (
                evidence["passed"] is True
                and evidence["exit_code"] == 0
                and evidence["timed_out"] is False
                and evidence["truncated"] is False
            )
            if gate_status == "PASS" and not passed:
                raise ContractError("PASS gate references failed executable evidence")
            saw_executable = saw_executable or passed
            saw_failure = saw_failure or not passed
        else:
            if (
                evidence["reviewer"] != reviewer_role
                or evidence["revision"] != revision
                or evidence["target_sha256"] != target_sha256
            ):
                raise ContractError("review evidence is bound to a different gate")
            passed = evidence["verdict"] == "PASS"
            if gate_status == "PASS" and not passed:
                raise ContractError("PASS gate references failed review evidence")
            saw_review = saw_review or passed
            saw_failure = saw_failure or not passed

    if require_current:
        enforce_pass_evidence_classes(
            gate_name,
            gate_status,
            saw_executable=saw_executable,
            saw_review=saw_review,
            saw_failure=saw_failure,
            saw_executable_ref=saw_executable_ref,
        )


def _evidence_refs_current(
    evidence_refs: list[Any],
    program_root: Path,
    site_root: Path,
    gate_name: str,
    gate_status: str,
    revision: int,
    target_sha256: str,
    reviewer_role: str,
) -> bool:
    try:
        _validate_evidence_refs(
            evidence_refs,
            program_root,
            site_root,
            gate_name,
            gate_status,
            revision,
            target_sha256,
            reviewer_role,
            require_current=True,
        )
    except ContractError:
        return False
    return True


def _load_evidence_record(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("evidence record exceeds size limit")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            raise TypeError("evidence root must be an object")
        schema = evidence.get("schema")
        if schema == "corporate-site-evidence/v1":
            required = {
                "schema",
                "revision",
                "target_sha256",
                "name",
                "argv",
                "cwd",
                "executable_path",
                "executable_sha256",
                "passed",
                "exit_code",
                "timed_out",
                "truncated",
                "stdout",
                "stderr",
                "stdout_sha256",
                "stderr_sha256",
            }
            if not required <= set(evidence):
                raise KeyError(", ".join(sorted(required - set(evidence))))
            if not isinstance(evidence["passed"], bool):
                raise TypeError("passed must be boolean")
            if not isinstance(evidence["name"], str) or not isinstance(evidence["argv"], list):
                raise TypeError("evidence name and argv are invalid")
            if not all(isinstance(item, str) for item in evidence["argv"]):
                raise TypeError("evidence argv must contain strings")
            if not isinstance(evidence["cwd"], str):
                raise TypeError("evidence cwd must be a string")
            if not isinstance(evidence["executable_path"], str) or not _is_sha256(
                str(evidence["executable_sha256"])
            ):
                raise TypeError("evidence executable binding is invalid")
            if not isinstance(evidence["timed_out"], bool) or not isinstance(
                evidence["truncated"], bool
            ):
                raise TypeError("timeout and truncation fields must be boolean")
            evidence["revision"] = int(evidence["revision"])
            evidence["exit_code"] = int(evidence["exit_code"])
        elif schema == "corporate-site-review-evidence/v1":
            required = {
                "schema",
                "reviewer",
                "revision",
                "verdict",
                "target_sha256",
            }
            if not required <= set(evidence):
                raise KeyError(", ".join(sorted(required - set(evidence))))
            if evidence["verdict"] not in {"PASS", "FAIL"}:
                raise ValueError("review verdict must be PASS or FAIL")
            evidence["revision"] = int(evidence["revision"])
        else:
            raise ValueError("unsupported evidence schema")
        if not _is_sha256(str(evidence["target_sha256"])):
            raise ValueError("evidence target digest is invalid")
        return evidence
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid evidence record {path}: {exc}") from exc


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _require_allowed_path(path: Path, program_root: Path, site_root: Path) -> None:
    roots = (program_root.resolve(), site_root.expanduser().resolve())
    if not any(path == root or root in path.parents for root in roots):
        raise ContractError(f"path is outside corporate and site roots: {path}")


def _paths_nested(left: Path, right: Path) -> bool:
    left_r = left.resolve()
    right_r = right.resolve()
    return left_r == right_r or left_r in right_r.parents or right_r in left_r.parents


def _validate_optional_site_manifest(site_root: Path) -> None:
    site_json = site_root / ".corp-harness" / "site.json"
    if not site_json.is_file():
        return
    try:
        data = json.loads(site_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid site.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("site.json root must be an object")
    if data.get("schema") != SITE_SCHEMA:
        raise ContractError(
            f"site.json schema is {data.get('schema')!r}, expected {SITE_SCHEMA}"
        )
    site_id = data.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ContractError("site.json site_id must be a non-empty string")


def _resolve_without_symlinks(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise ContractError(f"symlink is not allowed: {component}")
    return candidate.resolve()
