import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.adapters.aider import AiderAdapter
from agentmesh.adapters.claude_code import ClaudeCodeAdapter
from agentmesh.adapters.codex import CodexAdapter
from agentmesh.adapters.cursor import CursorAdapter
from agentmesh.adapters.hermes import HermesAdapter
from agentmesh.adapters.openclaw import OpenClawAdapter
from agentmesh.adapters.windsurf import WindsurfAdapter
from agentmesh.cli.main import app
from agentmesh.config.loader import AGENT_TARGETS, EXPORT_ONLY_TARGETS
from agentmesh.models.runtime import (
    ADAPTER_CONTRACT_V1_SLOTS,
    CONTRACT_SCHEMA,
    AdapterContract,
)
from agentmesh.services.agent_service import adapter_capabilities_matrix, adapter_contract_matrix
from agentmesh.services.runtime_service import RUNTIME_TARGETS
from agentmesh.validation.native import NATIVE_VALIDATORS

ALL_ADAPTER_CLASSES = [
    HermesAdapter,
    OpenClawAdapter,
    CodexAdapter,
    ClaudeCodeAdapter,
    CursorAdapter,
    WindsurfAdapter,
    AiderAdapter,
]

EXPECTED_SLOTS = dict(ADAPTER_CONTRACT_V1_SLOTS)


def test_adapter_capabilities_match_implemented_target_registries(tmp_path: Path):
    matrix = {item["name"]: item for item in adapter_capabilities_matrix(tmp_path)}

    native_targets = set(NATIVE_VALIDATORS)
    matrix_native_targets = {
        name for name, item in matrix.items() if "native_validation" in item["capabilities"]
    }
    assert matrix_native_targets == native_targets

    runtime_targets = set(RUNTIME_TARGETS)
    matrix_runtime_targets = {
        name for name, item in matrix.items() if "runtime_load_plan" in item["capabilities"]
    }
    assert matrix_runtime_targets == runtime_targets

    sync_targets = set(AGENT_TARGETS) - set(EXPORT_ONLY_TARGETS)
    matrix_apply_targets = {
        name for name, item in matrix.items() if "apply_sync" in item["capabilities"]
    }
    assert matrix_apply_targets == sync_targets

    for name, item in matrix.items():
        if item["writable"] is False:
            assert "apply_sync" not in item["capabilities"], name


def test_adapter_capabilities_matrix_declares_runtime_safety_contract(tmp_path: Path):
    home = tmp_path / "home"
    matrix = adapter_capabilities_matrix(home)

    names = {item["name"] for item in matrix}
    assert names == {"hermes", "openclaw", "codex", "claude-code", "cursor", "windsurf", "aider"}

    by_name = {item["name"]: item for item in matrix}
    assert by_name["hermes"]["mode"] == "read-write"
    assert "native_validation" in by_name["hermes"]["capabilities"]
    assert "runtime_load_plan" in by_name["hermes"]["capabilities"]

    assert by_name["openclaw"]["mode"] == "read-write"
    assert "runtime_load_plan" in by_name["openclaw"]["capabilities"]

    assert by_name["codex"]["mode"] == "read-write"
    assert "native_validation" in by_name["codex"]["capabilities"]
    assert "runtime_load_plan" in by_name["codex"]["capabilities"]
    assert ".system" in by_name["codex"]["protected_paths"]
    assert "exclude_system_skills" in by_name["codex"]["safety_guards"]

    assert by_name["claude-code"]["mode"] == "export-only"
    assert by_name["claude-code"]["writable"] is False
    assert "export_package" in by_name["claude-code"]["capabilities"]
    assert "no_auto_install" in by_name["claude-code"]["safety_guards"]

    assert by_name["cursor"]["mode"] == "read-write"
    assert by_name["cursor"]["writable"] is True
    assert "native_validation" in by_name["cursor"]["capabilities"]
    assert "dry_run_sync" in by_name["cursor"]["capabilities"]
    assert "path_guard" in by_name["cursor"]["safety_guards"]

    assert by_name["windsurf"]["mode"] == "read-write"
    assert by_name["windsurf"]["writable"] is True
    assert "native_validation" in by_name["windsurf"]["capabilities"]
    assert "dry_run_sync" in by_name["windsurf"]["capabilities"]
    assert "path_guard" in by_name["windsurf"]["safety_guards"]

    assert by_name["aider"]["mode"] == "read-write"
    assert by_name["aider"]["writable"] is True
    assert "native_validation" in by_name["aider"]["capabilities"]
    assert "apply_sync" in by_name["aider"]["capabilities"]
    assert "dry_run_sync" in by_name["aider"]["capabilities"]
    assert "path_guard" in by_name["aider"]["safety_guards"]

    for item in matrix:
        assert item["schema"] == "agentmesh.adapter-capabilities/v1"
        assert item["skill_dir"].startswith(str(home))
        assert isinstance(item["capabilities"], list)
        assert isinstance(item["safety_guards"], list)
        assert isinstance(item["protected_paths"], list)


def test_agents_list_json_includes_capabilities_matrix(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.agents-list/v1"
    agents = payload["data"]["agents"]
    assert {agent["name"] for agent in agents} == {
        "hermes",
        "openclaw",
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "aider",
    }
    codex = next(agent for agent in agents if agent["name"] == "codex")
    assert ".system" in codex["protected_paths"]
    assert "exclude_system_skills" in codex["safety_guards"]


def test_agents_contract_json_exposes_adapter_contract_v1_without_writes(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "contract", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.agents-contract/v1"
    assert payload["command"] == "agents contract"
    assert payload["status"] == "ok"
    contracts = payload["data"]["contracts"]
    assert {item["name"] for item in contracts} == {
        "hermes",
        "openclaw",
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "aider",
    }
    for item in contracts:
        assert item["schema"] == "agentmesh.adapter-contract/v1"
        assert item["write_operations_enabled"] is False
        assert item["network_required"] is False
        assert item["slots"]["classify"] == "unsupported"
        assert item["slots"]["render_plan"] == "unsupported"
    by_name = {item["name"]: item for item in contracts}
    assert by_name["codex"]["protected_paths"] == [".system"]
    assert "exclude_system_skills" in by_name["codex"]["safety_guards"]
    assert by_name["claude-code"]["mode"] == "export-only"
    assert by_name["claude-code"]["writable"] is False
    assert "no_auto_install" in by_name["claude-code"]["safety_guards"]
    assert payload["next_steps"] == [
        "This is a read-only contract declaration; use explicit CLI --apply for writes."
    ]


def test_each_adapter_exposes_capabilities_method(tmp_path: Path):
    for adapter_cls in [
        HermesAdapter,
        OpenClawAdapter,
        CodexAdapter,
        ClaudeCodeAdapter,
        CursorAdapter,
        WindsurfAdapter,
        AiderAdapter,
    ]:
        capabilities = adapter_cls(home=tmp_path).capabilities()
        assert capabilities.schema == "agentmesh.adapter-capabilities/v1"
        assert capabilities.name == adapter_cls.name
        assert capabilities.skill_dir.is_absolute()


def test_adapter_contract_matrix_declares_v1_slots_without_enabling_writes(tmp_path: Path):
    matrix = adapter_contract_matrix(tmp_path)

    assert {item["name"] for item in matrix} == {
        "hermes",
        "openclaw",
        "codex",
        "claude-code",
        "cursor",
        "windsurf",
        "aider",
    }
    for item in matrix:
        assert item["schema"] == "agentmesh.adapter-contract/v1"
        assert item["contract_version"] == "v1"
        assert item["slots"] == {
            "detect": "implemented",
            "scan": "implemented",
            "capabilities": "implemented",
            "classify": "unsupported",
            "render_plan": "unsupported",
            "validate_projection": "unsupported",
            "audit_hints": "unsupported",
        }
        assert item["write_operations_enabled"] is False
        assert item["network_required"] is False
        assert item["unsupported_reason"] == "adapter contract v1 slot declared but not implemented"

    by_name = {item["name"]: item for item in matrix}
    assert by_name["codex"]["protected_paths"] == [".system"]
    assert "exclude_system_skills" in by_name["codex"]["safety_guards"]
    assert by_name["claude-code"]["mode"] == "export-only"
    assert by_name["claude-code"]["writable"] is False
    assert "no_auto_install" in by_name["claude-code"]["safety_guards"]


# ── AdapterContract dataclass & schema tests ──────────────────────────────


def test_adapter_contract_returns_adapter_contract_dataclass(tmp_path: Path):
    """Each adapter's contract() returns an AdapterContract instance."""
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract()
        assert isinstance(contract, AdapterContract), adapter_cls.name


def test_adapter_contract_schema_is_v1(tmp_path: Path):
    """Every contract dict uses the agentmesh.adapter-contract/v1 schema."""
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract().to_dict()
        assert contract["schema"] == CONTRACT_SCHEMA, adapter_cls.name
        assert contract["contract_version"] == "v1", adapter_cls.name


def test_adapter_contract_slots_completeness(tmp_path: Path):
    """Every contract declares all 7 slots exactly matching ADAPTER_CONTRACT_V1_SLOTS."""
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract().to_dict()
        assert contract["slots"] == EXPECTED_SLOTS, adapter_cls.name


def test_adapter_contract_unsupported_slots_explicitly_marked(tmp_path: Path):
    """classify, render_plan, validate_projection, audit_hints are explicitly 'unsupported'."""
    unsupported_slots = {"classify", "render_plan", "validate_projection", "audit_hints"}
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract().to_dict()
        for slot in unsupported_slots:
            assert contract["slots"][slot] == "unsupported", f"{adapter_cls.name}.{slot}"


def test_adapter_contract_write_operations_disabled(tmp_path: Path):
    """No adapter enables write operations in contract v1."""
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract().to_dict()
        assert contract["write_operations_enabled"] is False, adapter_cls.name
        assert contract["network_required"] is False, adapter_cls.name


def test_adapter_contract_preserves_capabilities_fields(tmp_path: Path):
    """Contract dict includes all AdapterCapabilities fields."""
    required_keys = {
        "name",
        "skill_dir",
        "mode",
        "writable",
        "capabilities",
        "safety_guards",
        "protected_paths",
    }
    for adapter_cls in ALL_ADAPTER_CLASSES:
        contract = adapter_cls(home=tmp_path).contract().to_dict()
        assert required_keys <= contract.keys(), adapter_cls.name


def test_adapter_contract_specific_adapter_properties(tmp_path: Path):
    """Verify adapter-specific contract properties."""
    codex = CodexAdapter(home=tmp_path).contract().to_dict()
    assert codex["protected_paths"] == [".system"]
    assert "exclude_system_skills" in codex["safety_guards"]

    cc = ClaudeCodeAdapter(home=tmp_path).contract().to_dict()
    assert cc["mode"] == "export-only"
    assert cc["writable"] is False
    assert "no_auto_install" in cc["safety_guards"]

    hermes = HermesAdapter(home=tmp_path).contract().to_dict()
    assert hermes["mode"] == "read-write"
    assert hermes["writable"] is True
    assert "apply_sync" in hermes["capabilities"]


def test_agents_contract_json_envelope_structure(tmp_path: Path, monkeypatch):
    """CLI agents contract --json produces a valid envelope."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "contract", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    for key in (
        "schema",
        "command",
        "status",
        "data",
        "summary",
        "warnings",
        "errors",
        "next_steps",
    ):
        assert key in payload, f"missing envelope key: {key}"

    assert payload["schema"] == "agentmesh.agents-contract/v1"
    assert payload["command"] == "agents contract"
    assert payload["status"] == "ok"
    assert isinstance(payload["data"]["contracts"], list)
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["errors"], list)
    assert isinstance(payload["next_steps"], list)


def test_agents_contract_json_each_contract_has_all_slots(tmp_path: Path, monkeypatch):
    """CLI contract --json: every contract in data.contracts has all 7 slots."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    runner = CliRunner()

    result = runner.invoke(app, ["agents", "contract", "--json"])
    payload = json.loads(result.output)

    for contract in payload["data"]["contracts"]:
        assert contract["slots"] == EXPECTED_SLOTS, contract["name"]
        assert contract["schema"] == CONTRACT_SCHEMA
        assert contract["write_operations_enabled"] is False
        assert contract["network_required"] is False
