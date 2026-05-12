"""ModelMesh 探索：模型配置 scan / diff / list 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.models.model_config import ModelConfig, ModelDiff
from agentmesh.services.model_service import diff_configs, scan_all, scan_config

runner = CliRunner()


# ── helpers ──────────────────────────────────────────────────────────────


def _setup_hermes(home: Path, *, default: str = "mimo-v2.5-pro", provider: str = "custom") -> None:
    cfg_dir = home / ".hermes"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        f"model:\n  default: {default}\n  provider: {provider}\n"
        "  base_url: https://example.com/v1\n  context_length: 128000\n",
        encoding="utf-8",
    )


def _setup_openclaw(home: Path, *, models: list[str] | None = None) -> None:
    cfg_dir = home / ".openclaw"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    models = models or ["gpt-5.5", "glm-5.1"]
    providers: dict = {}
    for m in models:
        prov_models = providers.setdefault("sub2api", {"models": []})["models"]
        prov_models.append({"id": m, "name": m.upper()})
    data = {"models": {"providers": providers}}
    (cfg_dir / "openclaw.json").write_text(json.dumps(data), encoding="utf-8")


def _setup_claude_code(home: Path, *, model: str = "opus[1m]") -> None:
    cfg_dir = home / ".claude"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.json").write_text(json.dumps({"model": model}), encoding="utf-8")


def _setup_codex(home: Path, *, model: str = "o3-mini") -> None:
    cfg_dir = home / ".codex"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps({"model": model}), encoding="utf-8")


# ── ModelConfig dataclass ───────────────────────────────────────────────


def test_model_config_schema_fields():
    cfg = ModelConfig(
        agent="hermes",
        default_model="mimo-v2.5-pro",
        provider="custom",
        base_url="https://example.com/v1",
        context_length=128000,
    )
    assert cfg.agent == "hermes"
    assert cfg.default_model == "mimo-v2.5-pro"
    assert cfg.provider == "custom"
    assert cfg.schema == "agentmesh.model-config/v1"


def test_model_config_to_dict():
    cfg = ModelConfig(agent="hermes", default_model="mimo-v2.5-pro")
    d = cfg.to_dict()
    assert d["schema"] == "agentmesh.model-config/v1"
    assert d["agent"] == "hermes"
    assert d["default_model"] == "mimo-v2.5-pro"
    assert isinstance(d["available_models"], list)


def test_model_config_available_models_default_empty():
    cfg = ModelConfig(agent="test", default_model="x")
    assert cfg.available_models == ()


# ── scan ─────────────────────────────────────────────────────────────────


def test_scan_hermes_config(tmp_path: Path):
    _setup_hermes(tmp_path)
    cfg = scan_config(tmp_path, "hermes")
    assert cfg is not None
    assert cfg.agent == "hermes"
    assert cfg.default_model == "mimo-v2.5-pro"
    assert cfg.provider == "custom"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.context_length == 128000


def test_scan_openclaw_config(tmp_path: Path):
    _setup_openclaw(tmp_path, models=["gpt-5.5", "glm-5.1"])
    cfg = scan_config(tmp_path, "openclaw")
    assert cfg is not None
    assert cfg.agent == "openclaw"
    assert "gpt-5.5" in cfg.available_models
    assert "glm-5.1" in cfg.available_models


def test_scan_claude_code_config(tmp_path: Path):
    _setup_claude_code(tmp_path, model="opus[1m]")
    cfg = scan_config(tmp_path, "claude-code")
    assert cfg is not None
    assert cfg.agent == "claude-code"
    assert cfg.default_model == "opus[1m]"


def test_scan_codex_config(tmp_path: Path):
    _setup_codex(tmp_path, model="o3-mini")
    cfg = scan_config(tmp_path, "codex")
    assert cfg is not None
    assert cfg.agent == "codex"
    assert cfg.default_model == "o3-mini"


def test_scan_missing_config_returns_none(tmp_path: Path):
    cfg = scan_config(tmp_path, "hermes")
    assert cfg is None


def test_scan_all_returns_installed_configs(tmp_path: Path):
    _setup_hermes(tmp_path)
    _setup_claude_code(tmp_path)
    results = scan_all(tmp_path)
    names = {c.agent for c in results}
    assert "hermes" in names
    assert "claude-code" in names
    assert "openclaw" not in names  # not installed


# ── diff ─────────────────────────────────────────────────────────────────


def test_diff_same_model(tmp_path: Path):
    _setup_hermes(tmp_path, default="gpt-5.5")
    _setup_claude_code(tmp_path, model="gpt-5.5")
    diffs = diff_configs(tmp_path)
    # same model → no diff for default_model
    default_diffs = [d for d in diffs if d.field == "default_model"]
    assert len(default_diffs) == 0


def test_diff_different_models(tmp_path: Path):
    _setup_hermes(tmp_path, default="mimo-v2.5-pro")
    _setup_claude_code(tmp_path, model="opus[1m]")
    diffs = diff_configs(tmp_path)
    default_diffs = [d for d in diffs if d.field == "default_model"]
    assert len(default_diffs) > 0
    # should contain a diff between hermes and claude-code
    agents_pairs = {(d.agent_a, d.agent_b) for d in default_diffs}
    assert ("claude-code", "hermes") in agents_pairs or ("hermes", "claude-code") in agents_pairs


def test_diff_only_installed_agents(tmp_path: Path):
    _setup_hermes(tmp_path)
    diffs = diff_configs(tmp_path)
    assert len(diffs) == 0  # only 1 agent → no pairs


def test_model_diff_dataclass():
    d = ModelDiff(
        field="default_model",
        agent_a="hermes",
        value_a="mimo",
        agent_b="codex",
        value_b="o3",
    )
    assert d.field == "default_model"
    d2 = d.to_dict()
    assert d2["agent_a"] == "hermes"
    assert d2["value_a"] == "mimo"


# ── CLI: am model scan ──────────────────────────────────────────────────


def test_model_scan_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    _setup_claude_code(tmp_path)
    result = runner.invoke(app, ["model", "scan", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.model-scan/v1"
    assert payload["command"] == "model scan"
    assert payload["status"] == "ok"
    configs = payload["data"]["configs"]
    names = {c["agent"] for c in configs}
    assert "hermes" in names
    assert "claude-code" in names


def test_model_scan_human_readable(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    result = runner.invoke(app, ["model", "scan", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "hermes" in result.output


# ── CLI: am model diff ──────────────────────────────────────────────────


def test_model_diff_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path, default="mimo-v2.5-pro")
    _setup_claude_code(tmp_path, model="opus[1m]")
    result = runner.invoke(app, ["model", "diff", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.model-diff/v1"
    assert payload["command"] == "model diff"
    diffs = payload["data"]["diffs"]
    assert len(diffs) > 0


def test_model_diff_no_configs(tmp_path: Path, monkeypatch):
    result = runner.invoke(app, ["model", "diff", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["data"]["diffs"] == []


# ── CLI: am model list ──────────────────────────────────────────────────


def test_model_list_json(tmp_path: Path, monkeypatch):
    _setup_hermes(tmp_path)
    _setup_openclaw(tmp_path)
    result = runner.invoke(app, ["model", "list", "--json", "--registry", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentmesh.model-list/v1"
    agents = payload["data"]["agents"]
    assert len(agents) == 2
