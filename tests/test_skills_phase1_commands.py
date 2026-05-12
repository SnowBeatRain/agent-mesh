"""Phase 1 command unification tests.

Covers:
- `skills target <name> --enable/--disable/--show` unified command.
- `skills import --from agent:<name>` / `--from package:<path>` unified syntax.
- Deprecation warnings on legacy entry points (enable/disable/status,
  import positional, import-package, --dry-run flags).

The legacy commands stay functional so existing scripts keep working for
one more minor release; we only assert the new command semantics here plus
the deprecation-note presence/absence in --json vs TTY mode.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentmesh.cli.main import app


def _seed_registry_skill(registry: Path, name: str, body: str = "# body") -> Path:
    skill = registry / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.asset.yaml").write_text(
        f"schema: agentmesh.asset/v1\nkind: skill\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    (skill / "agentmesh.skill.yaml").write_text(
        f"schema: agentmesh.skill/v1\nname: {name}\ndescription: Demo\n",
        encoding="utf-8",
    )
    (skill / "provenance.yaml").write_text(
        f"source_agent: hermes\nhash: abc123\nsource_path: /tmp/{name}\n",
        encoding="utf-8",
    )
    return skill


# ---------------------------------------------------------------------------
# `skills target` — unified enable / disable / show
# ---------------------------------------------------------------------------


def test_target_enable_then_show_roundtrip(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    enable = runner.invoke(
        app,
        [
            "skills",
            "target",
            "demo-skill",
            "--enable",
            "--target",
            "openclaw",
            "--registry",
            str(registry),
        ],
    )
    assert enable.exit_code == 0, enable.output
    assert "已启用" in enable.output

    # --show without a name → whole state
    show_all = runner.invoke(
        app,
        ["skills", "target", "--show", "--registry", str(registry), "--json"],
    )
    assert show_all.exit_code == 0, show_all.output
    payload = json.loads(show_all.output)
    assert payload["status"] == "ok"
    state_skills = payload["data"]["state"]["skills"]
    assert "demo-skill" in state_skills
    assert state_skills["demo-skill"]["targets"]["openclaw"]["enabled"] is True

    # --show with a name → scoped payload
    show_one = runner.invoke(
        app,
        [
            "skills",
            "target",
            "demo-skill",
            "--show",
            "--registry",
            str(registry),
            "--json",
        ],
    )
    assert show_one.exit_code == 0, show_one.output
    scoped = json.loads(show_one.output)
    assert scoped["data"]["state"]["skill"] == "demo-skill"
    assert scoped["data"]["state"]["targets"]["openclaw"]["enabled"] is True


def test_target_disable_flips_enabled(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--enable", "--target", "openclaw",
         "--registry", str(registry)],
    )
    disable = runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--disable", "--target", "openclaw",
         "--registry", str(registry)],
    )
    assert disable.exit_code == 0, disable.output
    assert "已禁用" in disable.output

    show = runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--show", "--registry", str(registry),
         "--json"],
    )
    payload = json.loads(show.output)
    assert payload["data"]["state"]["targets"]["openclaw"]["enabled"] is False


def test_target_requires_exactly_one_mode(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    # No mode → error
    no_mode = runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--registry", str(registry)],
    )
    assert no_mode.exit_code != 0
    assert "--enable / --disable / --show" in no_mode.output

    # Two modes → error
    two_modes = runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--enable", "--show", "--target", "openclaw",
         "--registry", str(registry)],
    )
    assert two_modes.exit_code != 0


def test_target_enable_requires_name_and_target(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner()

    missing_name = runner.invoke(
        app, ["skills", "target", "--enable", "--target", "openclaw",
              "--registry", str(registry)],
    )
    assert missing_name.exit_code != 0
    assert "skill 名" in missing_name.output

    missing_target = runner.invoke(
        app, ["skills", "target", "demo-skill", "--enable", "--registry", str(registry)],
    )
    assert missing_target.exit_code != 0
    assert "--target" in missing_target.output


# ---------------------------------------------------------------------------
# Legacy enable / disable / status shims
# ---------------------------------------------------------------------------


def test_legacy_enable_still_works_with_deprecation_note(fake_home):
    """Legacy `skills enable` should write state identically to `target --enable`
    but print a [DEPRECATED] note on stderr (non-JSON)."""
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    # CliRunner with mix_stderr=False so we can inspect stderr separately.
    runner = CliRunner(mix_stderr=False)

    enable = runner.invoke(
        app,
        ["skills", "enable", "demo-skill", "--target", "openclaw",
         "--registry", str(registry)],
    )
    assert enable.exit_code == 0, enable.stdout
    assert "已启用" in enable.stdout
    assert "[DEPRECATED]" in enable.stderr
    assert "skills target" in enable.stderr

    # State still updated
    show = runner.invoke(
        app,
        ["skills", "target", "demo-skill", "--show", "--registry", str(registry),
         "--json"],
    )
    payload = json.loads(show.stdout)
    assert payload["data"]["state"]["targets"]["openclaw"]["enabled"] is True


def test_legacy_enable_json_mode_suppresses_deprecation_on_stdout(fake_home):
    """In --json mode the stdout must stay pure JSON; the deprecation line
    is suppressed entirely (not moved into the envelope, not on stdout)."""
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner(mix_stderr=False)

    enable = runner.invoke(
        app,
        ["skills", "enable", "demo-skill", "--target", "openclaw",
         "--registry", str(registry), "--json"],
    )
    assert enable.exit_code == 0, enable.stdout + enable.stderr
    # Should be parseable JSON (the envelope), with no deprecation text on stdout
    json.loads(enable.stdout)  # does not raise
    assert "[DEPRECATED]" not in enable.stdout
    assert "[DEPRECATED]" not in enable.stderr  # json mode: fully silent


def test_legacy_status_still_works(fake_home):
    registry = fake_home / "agentmesh"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner(mix_stderr=False)

    status = runner.invoke(
        app, ["skills", "status", "--registry", str(registry), "--json"],
    )
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    # Legacy schema retained for payload shape
    assert payload["schema"] == "agentmesh.skills-status/v1"


# ---------------------------------------------------------------------------
# `skills import --from <source>` — unified syntax
# ---------------------------------------------------------------------------


def _seed_hermes_source(fake_home: Path) -> None:
    skill = fake_home / ".hermes" / "skills" / "custom" / "demo-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\n\n# Demo\n",
        encoding="utf-8",
    )


def test_import_from_agent_writes_registry(fake_home):
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app,
        ["skills", "import", "--from", "agent:hermes", "--apply",
         "--registry", str(registry)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (registry / "skills" / "demo-skill" / "SKILL.md").exists()
    # New syntax must NOT emit the deprecation note
    assert "[DEPRECATED]" not in result.stderr


def test_import_from_all_agents_writes_registry(fake_home):
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["skills", "import", "--from", "agent:all", "--apply",
         "--registry", str(registry)],
    )

    assert result.exit_code == 0, result.output
    assert (registry / "skills" / "demo-skill" / "SKILL.md").exists()


def test_import_from_agent_dry_run_by_default(fake_home):
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app,
        ["skills", "import", "--from", "agent:hermes",
         "--registry", str(registry)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "DRY-RUN" in result.stdout
    # Nothing written
    assert not (registry / "skills" / "demo-skill").exists()


def test_import_from_package_json_envelope_uses_new_schema(fake_home, tmp_path):
    """`skills import --from package:<zip>` uses the new `agentmesh.skills-import/v1`
    schema (legacy `import-package` keeps the old schema)."""
    # Build a minimal AgentMesh package by exporting an empty registry first.
    registry = fake_home / "agentmesh-home"
    registry.mkdir(parents=True)
    _seed_registry_skill(registry, "demo-skill")

    out_zip = tmp_path / "demo.agentmesh.zip"
    runner = CliRunner(mix_stderr=False)

    export = runner.invoke(
        app,
        ["skills", "export", "agentmesh", "--out", str(out_zip),
         "--registry", str(registry)],
    )
    assert export.exit_code == 0, export.stdout + export.stderr
    assert out_zip.exists()

    # Fresh registry for the import
    dest = fake_home / "import-dest"
    dest.mkdir()

    import_result = runner.invoke(
        app,
        ["skills", "import", "--from", f"package:{out_zip}",
         "--registry", str(dest), "--json"],
    )
    assert import_result.exit_code == 0, import_result.stdout + import_result.stderr
    payload = json.loads(import_result.stdout)
    assert payload["schema"] == "agentmesh.skills-import/v1"
    assert payload["data"]["source"]["type"] == "package"


def test_import_from_rejects_bad_syntax(fake_home):
    registry = fake_home / "agentmesh-home"
    runner = CliRunner(mix_stderr=False)

    no_colon = runner.invoke(
        app, ["skills", "import", "--from", "hermes", "--registry", str(registry)],
    )
    assert no_colon.exit_code != 0
    assert "agent:<name>" in no_colon.stdout or "agent:<name>" in no_colon.stderr

    bad_kind = runner.invoke(
        app,
        ["skills", "import", "--from", "runtime:hermes", "--registry", str(registry)],
    )
    assert bad_kind.exit_code != 0
    combined = bad_kind.stdout + bad_kind.stderr
    assert "不支持的来源类型" in combined or "runtime" in combined

    empty_value = runner.invoke(
        app, ["skills", "import", "--from", "agent:", "--registry", str(registry)],
    )
    assert empty_value.exit_code != 0


def test_import_from_conflict_with_positional_arg(fake_home):
    """Passing both --from and the legacy positional agent is a user error."""
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app,
        ["skills", "import", "hermes", "--from", "agent:hermes",
         "--registry", str(registry)],
    )
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "--from" in combined and "位置参数" in combined


# ---------------------------------------------------------------------------
# Legacy import positional + import-package shims
# ---------------------------------------------------------------------------


def test_legacy_positional_import_keeps_write_semantics(fake_home):
    """`skills import hermes` (positional) must still write by default — the
    deprecation warning does not change its semantics."""
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app, ["skills", "import", "hermes", "--registry", str(registry)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (registry / "skills" / "demo-skill" / "SKILL.md").exists()
    assert "[DEPRECATED]" in result.stderr


def test_legacy_agent_option_import_still_works_with_deprecation_note(fake_home):
    """`skills import --agent hermes` is an old UI-emitted form.

    Keep it as a deprecated alias so workstation buttons generated before the
    command unification do not fail at Click/Typer option parsing.
    """
    _seed_hermes_source(fake_home)
    registry = fake_home / "agentmesh-home"
    runner = CliRunner()

    result = runner.invoke(
        app, ["skills", "import", "--agent", "hermes", "--registry", str(registry)]
    )
    assert result.exit_code == 0, result.output
    assert (registry / "skills" / "demo-skill" / "SKILL.md").exists()
    assert "[DEPRECATED]" in result.output
    assert "skills import --from agent:<agent>" in result.output


def test_legacy_import_package_keeps_old_schema(fake_home, tmp_path):
    """`skills import-package` is a shim for backward compat: its JSON
    envelope still uses the legacy `agentmesh.skills-import-package/v1` schema."""
    registry = fake_home / "agentmesh-home"
    registry.mkdir(parents=True)
    _seed_registry_skill(registry, "demo-skill")
    out_zip = tmp_path / "demo.agentmesh.zip"
    runner = CliRunner(mix_stderr=False)

    export = runner.invoke(
        app,
        ["skills", "export", "agentmesh", "--out", str(out_zip),
         "--registry", str(registry)],
    )
    assert export.exit_code == 0, export.stdout + export.stderr

    dest = fake_home / "import-dest"
    dest.mkdir()
    import_result = runner.invoke(
        app,
        ["skills", "import-package", str(out_zip), "--registry", str(dest),
         "--json"],
    )
    assert import_result.exit_code == 0, import_result.stdout + import_result.stderr
    payload = json.loads(import_result.stdout)
    assert payload["schema"] == "agentmesh.skills-import-package/v1"


# ---------------------------------------------------------------------------
# `--dry-run` deprecation warning
# ---------------------------------------------------------------------------


def test_dry_run_on_sync_emits_deprecation(fake_home):
    """`skills sync --dry-run` still works but prints a deprecation note."""
    registry = fake_home / "agentmesh-home"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app,
        ["skills", "sync", "--dry-run", "--to", "openclaw", "--registry", str(registry)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "[DEPRECATED]" in result.stderr
    assert "DRY-RUN" in result.stdout


def test_dry_run_on_sync_suppressed_in_json_mode(fake_home):
    registry = fake_home / "agentmesh-home"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app,
        ["skills", "sync", "--dry-run", "--to", "openclaw", "--registry", str(registry),
         "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    json.loads(result.stdout)  # pure JSON on stdout
    assert "[DEPRECATED]" not in result.stderr


def test_sync_without_dry_run_stays_silent(fake_home):
    """Default sync (neither --dry-run nor --apply) is dry-run and prints no
    deprecation (the deprecation is for the flag, not the behavior)."""
    registry = fake_home / "agentmesh-home"
    _seed_registry_skill(registry, "demo-skill")
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(
        app, ["skills", "sync", "--to", "openclaw", "--registry", str(registry)],
    )
    assert result.exit_code == 0
    assert "[DEPRECATED]" not in result.stderr
    assert "DRY-RUN" in result.stdout
