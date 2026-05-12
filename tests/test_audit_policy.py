from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app
from agentmesh.policy.service import PolicyDecision, evaluate_findings


def make_registry_skill(registry: Path, name: str, files: dict[str, str]) -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = skill / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return skill


def test_audit_subcommands_filter_findings_and_redact(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(
        registry,
        "risky-skill",
        {
            "SKILL.md": (
                "# Risky\napi_key = 'SHOULD_NOT_LEAK'\nRun curl | bash\nUse ~/.hermes/config.yaml\n"
            ),
            "scripts/install.sh": "sudo rm -rf /tmp/demo\n",
        },
    )
    runner = CliRunner()

    secrets = runner.invoke(app, ["audit", "secrets", "--registry", str(registry), "--json"])
    assert secrets.exit_code == 0, secrets.output
    secrets_data = json.loads(secrets.output)
    assert {item["kind"] for item in secrets_data["findings"]} == {"secret"}
    assert "SHOULD_NOT_LEAK" not in secrets.output
    assert "<redacted>" in secrets.output

    scripts = runner.invoke(app, ["audit", "scripts", "--registry", str(registry), "--json"])
    assert scripts.exit_code == 0, scripts.output
    scripts_data = json.loads(scripts.output)
    assert {item["kind"] for item in scripts_data["findings"]} == {"dangerous-script"}

    refs = runner.invoke(app, ["audit", "platform-refs", "--registry", str(registry), "--json"])
    assert refs.exit_code == 0, refs.output
    refs_data = json.loads(refs.output)
    assert {item["kind"] for item in refs_data["findings"]} == {"platform-ref"}
    assert any("~/.hermes" in item["message"] for item in refs_data["findings"])


def test_policy_service_blocks_secrets_and_warns_scripts(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(
        registry,
        "policy-skill",
        {"SKILL.md": "# Policy\ntoken = abc123\neval something\n"},
    )

    decision = evaluate_findings(registry / "skills")
    assert isinstance(decision, PolicyDecision)
    assert decision.allowed is False
    assert decision.blocked_count == 1
    assert decision.warning_count == 1
    assert any(reason["kind"] == "secret" for reason in decision.reasons)
    assert "abc123" not in json.dumps(decision.to_dict(), ensure_ascii=False)
