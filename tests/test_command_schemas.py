"""Phase B1+B2: Command schema registry + ``assemble_command`` contract.

Key behaviours covered:

- 15+ schemas are registered at import time (B1 coverage target).
- Each registered schema uses the ``agentmesh.command-schema/v1`` envelope
  and ``am ...`` as the command prefix.
- Validation catches required-but-missing params, bad select values, regex
  mismatches, and type coercion errors.
- Boolean params with ``cli_flag_when_true`` / ``cli_flag_when_false`` emit
  the right flag for each branch; no flag is emitted when value is False and
  only ``cli_flag_when_true`` is set.
- Multi-select values get comma-joined and shell-escaped.
- Positional args come after flags regardless of declaration order.
- ``validate_values`` is pure (does not raise) and lists all errors at once.
- Individual schemas (``skills.sync``, ``skills.enable``, ``rollback.apply``)
  assemble to the expected CLI strings.
"""

from __future__ import annotations

import pytest

from agentmesh.local_api.schemas import (
    CommandParam,
    CommandSchema,
    SchemaValidationError,
    assemble_command,
    get_schema,
    list_schemas,
    validate_values,
)
from agentmesh.local_api.schemas.types import CommandOption

# ── Registry coverage ────────────────────────────────────────────────────


def test_registry_contains_minimum_15_schemas():
    schemas = list_schemas()
    assert len(schemas) >= 15, (
        f"Phase B1 targets ≥ 15 schemas, got {len(schemas)}: {[s.id for s in schemas]}"
    )


def test_registry_ids_are_unique():
    ids = [s.id for s in list_schemas()]
    assert len(ids) == len(set(ids))


def test_every_schema_uses_v1_envelope_and_am_prefix():
    for schema in list_schemas():
        assert schema.schema_version == "agentmesh.command-schema/v1", schema.id
        assert schema.command.startswith("am "), schema.id
        assert schema.id.strip() == schema.id


def test_every_schema_to_dict_is_json_serialisable():
    import json

    for schema in list_schemas():
        json.dumps(schema.to_dict())  # raises if not serialisable


def test_destructive_commands_require_confirmation():
    """Every destructive schema sets confirmation_required so UI knows to prompt."""
    for schema in list_schemas():
        if schema.destructive:
            assert schema.confirmation_required, (
                f"destructive {schema.id} must set confirmation_required=True"
            )


def test_required_params_never_have_visible_when():
    """A required param that is hidden by a visible_when condition is a UX trap."""
    for schema in list_schemas():
        for p in schema.params:
            if p.required and p.visible_when is not None:
                raise AssertionError(f"{schema.id}.{p.name} is required but conditionally visible")


def test_lookup_by_known_id_and_unknown_id():
    assert get_schema("skills.sync") is not None
    assert get_schema("skills.sync").command == "am skills sync"
    assert get_schema("does.not.exist") is None


# ── validate_values pure behaviour ───────────────────────────────────────


def _build_trivial_schema() -> CommandSchema:
    return CommandSchema(
        id="tests.trivial",
        title="Trivial",
        command="am tests trivial",
        description="Only used in unit tests.",
        params=(
            CommandParam(name="name", label="Name", type="string", required=True),
            CommandParam(
                name="flag",
                label="Flag",
                type="boolean",
                default=False,
                cli_flag_when_true="--flag",
            ),
        ),
    )


def test_validate_values_reports_missing_required():
    schema = _build_trivial_schema()
    errors = validate_values(schema, {})
    assert any("missing required parameter: name" in e for e in errors)


def test_validate_values_accepts_complete_payload():
    schema = _build_trivial_schema()
    assert validate_values(schema, {"name": "demo"}) == []


def test_validate_values_rejects_bad_select_member():
    schema = CommandSchema(
        id="tests.select",
        title="Select",
        command="am tests select",
        description="",
        params=(
            CommandParam(
                name="choice",
                label="Choice",
                type="select",
                required=True,
                options=(CommandOption("a", "A"), CommandOption("b", "B")),
            ),
        ),
    )
    errors = validate_values(schema, {"choice": "nope"})
    assert any("invalid value" in e for e in errors)


def test_validate_values_rejects_bad_multi_select_member():
    schema = CommandSchema(
        id="tests.multi",
        title="Multi",
        command="am tests multi",
        description="",
        params=(
            CommandParam(
                name="items",
                label="Items",
                type="multi-select",
                options=(CommandOption("a"), CommandOption("b")),
                cli_flag="--items",
            ),
        ),
    )
    errors = validate_values(schema, {"items": ["a", "zz"]})
    assert any("invalid value(s)" in e for e in errors)


def test_validate_values_accepts_multi_select_comma_string():
    """UIs often send multi-select as comma strings; validator should accept both."""
    schema = CommandSchema(
        id="tests.multi2",
        title="Multi2",
        command="am tests multi2",
        description="",
        params=(
            CommandParam(
                name="items",
                label="Items",
                type="multi-select",
                options=(CommandOption("a"), CommandOption("b")),
                cli_flag="--items",
            ),
        ),
    )
    assert validate_values(schema, {"items": "a,b"}) == []


def test_validate_values_regex_enforced():
    schema = CommandSchema(
        id="tests.regex",
        title="Regex",
        command="am tests regex",
        description="",
        params=(
            CommandParam(
                name="name",
                label="name",
                type="string",
                required=True,
                validate_regex=r"^[a-z][a-z0-9_-]{0,10}$",
            ),
        ),
    )
    assert validate_values(schema, {"name": "GoodName!"}) != []
    assert validate_values(schema, {"name": "good-name"}) == []


def test_validate_values_does_not_raise_on_bad_type():
    """validate_values is expected to aggregate errors, never raise."""
    schema = _build_trivial_schema()
    errors = validate_values(schema, {"name": 123, "flag": "not-a-bool"})
    # name=123 is acceptable (coerced via str()); flag is the problem.
    assert any("flag" in e for e in errors)


# ── assemble_command mechanics ───────────────────────────────────────────


def test_assemble_fails_fast_on_validation_errors():
    schema = _build_trivial_schema()
    with pytest.raises(SchemaValidationError):
        assemble_command(schema, {})  # missing required


def test_assemble_boolean_true_emits_positive_flag():
    schema = _build_trivial_schema()
    out = assemble_command(schema, {"name": "demo", "flag": True})
    assert out == "am tests trivial demo --flag"


def test_assemble_boolean_false_omits_flag_when_only_true_form_set():
    schema = _build_trivial_schema()
    out = assemble_command(schema, {"name": "demo", "flag": False})
    assert out == "am tests trivial demo"


def test_assemble_boolean_false_emits_negative_flag_when_both_forms_set():
    schema = CommandSchema(
        id="tests.dual",
        title="Dual",
        command="am tests dual",
        description="",
        params=(
            CommandParam(
                name="dry_run",
                label="dry run",
                type="boolean",
                default=True,
                cli_flag_when_true="--dry-run",
                cli_flag_when_false="--apply",
            ),
        ),
    )
    assert assemble_command(schema, {"dry_run": True}) == "am tests dual --dry-run"
    assert assemble_command(schema, {"dry_run": False}) == "am tests dual --apply"


def test_assemble_multi_select_joins_and_quotes():
    schema = CommandSchema(
        id="tests.multi3",
        title="Multi3",
        command="am tests multi3",
        description="",
        params=(
            CommandParam(
                name="to",
                label="to",
                type="multi-select",
                options=(CommandOption("a"), CommandOption("b")),
                cli_flag="--to",
            ),
        ),
    )
    out = assemble_command(schema, {"to": ["a", "b"]})
    assert out == "am tests multi3 --to a,b"


def test_assemble_multi_select_skips_when_empty():
    schema = CommandSchema(
        id="tests.multi4",
        title="Multi4",
        command="am tests multi4",
        description="",
        params=(
            CommandParam(
                name="to",
                label="to",
                type="multi-select",
                options=(CommandOption("a"),),
                cli_flag="--to",
            ),
        ),
    )
    assert assemble_command(schema, {"to": []}) == "am tests multi4"


def test_assemble_positional_goes_before_flags():
    schema = CommandSchema(
        id="tests.positional",
        title="Positional",
        command="am tests positional",
        description="",
        params=(
            CommandParam(name="name", label="name", type="string", required=True),
            CommandParam(
                name="json_output",
                label="json",
                type="boolean",
                default=False,
                cli_flag_when_true="--json",
            ),
        ),
    )
    out = assemble_command(schema, {"name": "demo", "json_output": True})
    assert out == "am tests positional demo --json"


def test_assemble_shell_quotes_special_characters():
    schema = CommandSchema(
        id="tests.quote",
        title="Quote",
        command="am tests quote",
        description="",
        params=(
            CommandParam(
                name="path",
                label="path",
                type="path",
                required=True,
                cli_flag="--path",
            ),
        ),
    )
    out = assemble_command(schema, {"path": "/tmp/with space"})
    assert "--path '/tmp/with space'" in out


def test_assemble_ignores_values_not_in_schema():
    schema = _build_trivial_schema()
    out = assemble_command(schema, {"name": "demo", "flag": True, "stray": "x"})
    assert out == "am tests trivial demo --flag"


# ── End-to-end: real registered schemas assemble correctly ──────────────


def test_skills_sync_dry_run_minimal_emits_dry_run():
    schema = get_schema("skills.sync")
    assert schema is not None
    out = assemble_command(
        schema,
        {
            "to": ["hermes", "openclaw"],
            "dry_run": True,
            "mode": "copy",
            "json_output": True,
            "yes": True,
        },
    )
    assert out.startswith("am skills sync")
    assert "--to hermes,openclaw" in out
    assert "--dry-run" in out
    assert "--apply" not in out
    assert "--mode copy" in out
    assert "--json" in out


def test_skills_sync_apply_emits_apply_flag():
    schema = get_schema("skills.sync")
    out = assemble_command(
        schema,
        {
            "to": ["hermes"],
            "dry_run": False,
            "mode": "copy",
            "allow_conflicts": True,
            "json_output": True,
            "yes": True,
        },
    )
    assert "--apply" in out
    assert "--dry-run" not in out
    assert "--allow-conflicts" in out
    assert "--yes" in out


def test_skills_sync_symlink_requires_confirm_from_caller():
    """Schema doesn't enforce symlink+confirm at validate time; CLI does.
    The workstation reflects this by hiding/showing --confirm via visible_when.
    But if user supplies it, assemble emits it regardless."""
    schema = get_schema("skills.sync")
    out = assemble_command(
        schema,
        {
            "to": ["hermes"],
            "dry_run": False,
            "mode": "symlink",
            "confirm": True,
            "json_output": True,
            "yes": True,
        },
    )
    assert "--mode symlink" in out
    assert "--confirm" in out


def test_skills_sync_rejects_bad_mode():
    schema = get_schema("skills.sync")
    with pytest.raises(SchemaValidationError):
        assemble_command(schema, {"mode": "rsync"})


def test_skills_enable_multi_select_target():
    schema = get_schema("skills.enable")
    out = assemble_command(
        schema,
        {"name": "demo", "target": ["hermes", "openclaw"]},
    )
    assert out == "am skills enable demo --target hermes,openclaw"


def test_skills_show_regex_rejects_uppercase():
    schema = get_schema("skills.show")
    with pytest.raises(SchemaValidationError):
        assemble_command(schema, {"name": "BadSkill"})


def test_rollback_apply_without_confirm_fails_validation():
    schema = get_schema("rollback.apply")
    # confirm is required=True; omitting it should raise.
    with pytest.raises(SchemaValidationError):
        assemble_command(schema, {"backup_ref": "2026-05-09"})


def test_rollback_apply_with_confirm_builds_command():
    schema = get_schema("rollback.apply")
    out = assemble_command(
        schema,
        {"backup_ref": "2026-05-09", "confirm": True, "json_output": True},
    )
    assert out.startswith("am rollback apply")
    assert "2026-05-09" in out
    assert "--confirm" in out


def test_audit_all_multi_select_kinds():
    schema = get_schema("audit.all")
    out = assemble_command(schema, {"kinds": ["secrets", "scripts"]})
    assert "--kinds secrets,scripts" in out


# ── Categorical sanity checks ───────────────────────────────────────────


def test_skills_import_schema_uses_current_from_agent_syntax():
    schema = get_schema("skills.import")
    assert schema is not None

    out = assemble_command(schema, {"source": "agent:hermes", "dry_run": False})

    assert out == "am skills import --from agent:hermes --apply"
    assert "--agent" not in out


def test_each_category_has_schemas():
    """Every documented category in the plan shows up in the registry."""
    categories = {s.category for s in list_schemas()}
    expected = {"core", "skills", "audit", "runtime", "rollback", "package"}
    missing = expected - categories
    assert not missing, f"categories missing from registry: {missing}"


def test_tags_are_lowercase_strings():
    for schema in list_schemas():
        for tag in schema.tags:
            assert isinstance(tag, str) and tag == tag.lower(), (schema.id, tag)
