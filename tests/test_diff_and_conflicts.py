from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def make_registry_skill(registry: Path, name: str, body: str, description: str = "Demo") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: {description}\n",
        encoding="utf-8",
    )
    return skill


def test_skills_list_duplicates_and_diff_cli(fake_home):
    registry = fake_home / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# registry")
    make_registry_skill(registry, "other-skill", "# registry", description="Demo")

    hermes_target = fake_home / ".hermes" / "skills" / "custom" / "demo-skill"
    hermes_target.mkdir(parents=True)
    (hermes_target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\n\n# target changed\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    duplicates = runner.invoke(app, ["skills", "list", "--registry", str(registry), "--duplicates"])
    assert duplicates.exit_code == 0, duplicates.output
    assert "Demo" in duplicates.output
    assert "demo-skill" in duplicates.output
    assert "other-skill" in duplicates.output

    diff = runner.invoke(
        app,
        ["skills", "diff", "demo-skill", "--registry", str(registry), "--target", "hermes"],
    )
    assert diff.exit_code == 0, diff.output
    assert "level 2" in diff.output
    assert "CONTENT_CHANGED" in diff.output

    conflicts = runner.invoke(
        app,
        [
            "skills",
            "conflicts",
            "--registry",
            str(registry),
            "--target",
            "hermes",
            "--json",
        ],
    )
    assert conflicts.exit_code == 0, conflicts.output
    assert "agentmesh.skills-conflicts/v1" in conflicts.output
    assert "demo-skill" in conflicts.output
    assert "CONTENT_CHANGED" in conflicts.output


def test_skills_diff_unknown_target_reports_clean_error_without_traceback(tmp_path):
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# registry")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "skills",
            "diff",
            "demo-skill",
            "--registry",
            str(registry),
            "--target",
            "unknown-agent",
        ],
    )

    assert result.exit_code != 0
    assert "暂不支持目标 agent：unknown-agent" in result.output
    assert "Traceback" not in result.output



def test_skills_diff_requires_explicit_target(tmp_path):
    """不传 --target 时应明确报错并引导用户，而不是默认用 hermes。"""
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# body")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "diff", "demo-skill", "--registry", str(registry)],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "--target" in result.output
    assert "agents list" in result.output


def test_skills_diff_requires_explicit_target_json(tmp_path):
    """JSON 输出路径也应返回结构化错误，而不是 traceback。"""
    registry = tmp_path / "agentmesh"
    make_registry_skill(registry, "demo-skill", "# body")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "diff", "demo-skill", "--registry", str(registry), "--json"],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert '"status": "error"' in result.output
    assert "--target" in result.output
