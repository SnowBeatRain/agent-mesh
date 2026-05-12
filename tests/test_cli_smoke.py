from typer.testing import CliRunner

from agentmesh.cli.main import app


def test_cli_help_and_version():
    runner = CliRunner()
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "AgentMesh" in help_result.output

    version_result = runner.invoke(app, ["--version"])
    assert version_result.exit_code == 0
    assert "0.1.0" in version_result.output


def test_init_creates_registry_skills_at_agentmesh_root(tmp_path):
    registry = tmp_path / "agentmesh-home"
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--registry", str(registry)])

    assert result.exit_code == 0, result.output
    assert (registry / "registry").is_dir()
    assert (registry / "skills").is_dir()
    assert not (registry / "registry" / "assets" / "skills").exists()
