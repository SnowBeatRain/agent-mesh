try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility path
    import tomli as tomllib
from pathlib import Path


def test_agentmesh_and_am_console_scripts_point_to_same_main():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["agentmesh"] == "agentmesh.cli.main:main"
    assert scripts["am"] == "agentmesh.cli.main:main"
