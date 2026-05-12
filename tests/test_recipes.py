"""Phase B5: Recipe registry + HTTP endpoints.

Recipes are the "operation cookbooks" the workstation presents. Each recipe
references command ids in the schema registry; these tests ensure:

- 6 built-in recipes are registered.
- Every step references an actual CommandSchema id.
- ``preview_recipe`` expands defaults + overrides into assembled commands.
- GET /recipes returns summaries (no steps).
- GET /recipes/<id> returns full steps.
- POST /recipes/<id>/preview returns per-step commands, respects overrides,
  and surfaces validation errors per-step without aborting the whole plan.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentmesh.local_api.recipes import (
    Recipe,
    RecipeStep,
    RecipeValidationError,
    get_recipe,
    list_recipes,
    preview_recipe,
    register_recipe,
)
from agentmesh.local_api.schemas import get_schema
from agentmesh.local_api.server import create_server

# ── Registry-level invariants ────────────────────────────────────────────


def test_registry_has_six_builtin_recipes():
    recipes = list_recipes()
    assert len(recipes) >= 6
    expected = {
        "first-time-setup",
        "daily-sync",
        "migrate-hermes-to-openclaw",
        "recover-from-bad-sync",
        "share-via-package",
        "claude-code-plugin",
    }
    assert expected <= {r.id for r in recipes}


def test_every_recipe_step_command_id_is_registered():
    """Guard against typos between recipe and schema registries."""
    for recipe in list_recipes():
        for step in recipe.steps:
            assert get_schema(step.command_id) is not None, (
                f"{recipe.id} step {step.id} references unknown command id {step.command_id!r}"
            )


def test_every_recipe_step_id_is_unique_within_recipe():
    for recipe in list_recipes():
        ids = [step.id for step in recipe.steps]
        assert len(ids) == len(set(ids)), f"duplicate step ids in {recipe.id}"


def test_recipe_envelope_schema_is_v1():
    for recipe in list_recipes():
        assert recipe.schema_version == "agentmesh.recipe/v1"


def test_recipe_to_dict_omits_steps_by_default_in_summary_mode():
    recipe = get_recipe("first-time-setup")
    summary = recipe.to_dict(include_steps=False)
    assert "steps" not in summary
    assert summary["step_count"] == len(recipe.steps)

    detail = recipe.to_dict(include_steps=True)
    assert isinstance(detail["steps"], list)
    assert len(detail["steps"]) == len(recipe.steps)


# ── preview_recipe (pure) ────────────────────────────────────────────────


def test_preview_recipe_expands_first_time_setup_with_defaults():
    plan = preview_recipe("first-time-setup")
    assert plan["ok"] is True
    assert plan["recipe"]["id"] == "first-time-setup"
    assert len(plan["steps"]) >= 3
    for step in plan["steps"]:
        assert step["command"], step
        assert step["errors"] == [], step


def test_preview_recipe_override_merges_on_top_of_defaults():
    plan = preview_recipe(
        "first-time-setup",
        overrides={4: {"dry_run": False}},  # step 4 is skills.import
    )
    step4 = next(s for s in plan["steps"] if s["id"] == 4)
    # dry_run override means the import schema emits the write flag.
    assert "--dry-run" not in step4["command"]
    assert "--apply" in step4["command"]
    # Other values from step 4's defaults remain present.
    assert "--from agent:hermes" in step4["command"]


def test_preview_recipe_accepts_string_keys_in_overrides():
    # The HTTP layer sends integer step ids as JSON object keys (which become strings).
    plan = preview_recipe(
        "share-via-package",
        overrides={"1": {"out": "/tmp/custom.zip"}},
    )
    step1 = next(s for s in plan["steps"] if s["id"] == 1)
    assert "/tmp/custom.zip" in step1["command"]


def test_preview_recipe_unknown_recipe_raises():
    with pytest.raises(RecipeValidationError):
        preview_recipe("does-not-exist")


def test_preview_recipe_invalid_override_key_raises():
    with pytest.raises(RecipeValidationError):
        preview_recipe("first-time-setup", overrides={"not-an-int": {}})


def test_preview_recipe_missing_required_value_reports_step_error():
    """Recovery recipe has a rollback.apply step whose backup_ref defaults to '';
    preview should report a per-step validation error (but not raise)."""
    plan = preview_recipe("recover-from-bad-sync")
    step3 = next(s for s in plan["steps"] if s["id"] == 3)  # rollback.apply
    assert step3["errors"], step3
    assert plan["ok"] is False


def test_preview_recipe_override_fixes_step_error():
    plan = preview_recipe(
        "recover-from-bad-sync",
        overrides={3: {"backup_ref": "2026-05-01-123456", "confirm": True}},
    )
    step3 = next(s for s in plan["steps"] if s["id"] == 3)
    assert step3["errors"] == []
    assert "2026-05-01-123456" in step3["command"]
    assert "--confirm" in step3["command"]


def test_destructive_step_propagates_requires_confirm():
    plan = preview_recipe("daily-sync")
    apply_step = next(s for s in plan["steps"] if s["id"] == 4)
    assert apply_step["requires_confirm"] is True


def test_register_recipe_replaces_existing_by_id():
    """register_recipe is idempotent: same id overwrites."""
    original = get_recipe("first-time-setup")
    dummy = Recipe(
        id="first-time-setup",
        title="Overridden in test",
        description="",
        steps=(RecipeStep(id=1, title="noop", command_id="doctor"),),
    )
    try:
        register_recipe(dummy)
        assert get_recipe("first-time-setup").title == "Overridden in test"
    finally:
        # Restore so other tests still see the real recipe.
        register_recipe(original)
    assert get_recipe("first-time-setup") is original


# ── HTTP endpoints ───────────────────────────────────────────────────────


@pytest.fixture
def api_server(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = create_server(host="127.0.0.1", port=port, registry=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_recipes_list_endpoint(api_server):
    resp = _get_json(f"{api_server}/recipes")
    assert resp["command"] == "local-api recipes list"
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["total"] >= 6
    ids = {r["id"] for r in data["recipes"]}
    assert "first-time-setup" in ids
    # Summaries must not include the full steps array (HTTP payload keeps small).
    for recipe in data["recipes"]:
        assert "steps" not in recipe
        assert "step_count" in recipe
    assert "beginner" in data["difficulties"]


def test_recipes_detail_endpoint_returns_full_steps(api_server):
    resp = _get_json(f"{api_server}/recipes/first-time-setup")
    assert resp["status"] == "ok"
    data = resp["data"]
    assert data["id"] == "first-time-setup"
    assert data["schema"] == "agentmesh.recipe/v1"
    assert isinstance(data["steps"], list)
    assert data["steps"][0]["command_id"] == "init"


def test_recipes_detail_unknown_returns_error(api_server):
    resp = _get_json(f"{api_server}/recipes/nope")
    assert resp["status"] == "error"
    assert any("unknown recipe" in e for e in resp["errors"])


def test_recipes_preview_endpoint_no_overrides(api_server):
    resp = _post_json(f"{api_server}/recipes/first-time-setup/preview")
    assert resp["command"] == "local-api recipes preview"
    assert resp["status"] == "ok"
    plan = resp["data"]
    assert plan["recipe"]["id"] == "first-time-setup"
    for step in plan["steps"]:
        assert step["command"]


def test_recipes_preview_endpoint_with_overrides(api_server):
    resp = _post_json(
        f"{api_server}/recipes/share-via-package/preview",
        {"overrides": {"1": {"out": "/tmp/override.zip"}}},
    )
    assert resp["status"] == "ok"
    step1 = next(s for s in resp["data"]["steps"] if s["id"] == 1)
    assert "/tmp/override.zip" in step1["command"]


def test_recipes_preview_empty_body_uses_defaults(api_server):
    """Empty POST body is acceptable for /recipes/<id>/preview (defaults only)."""
    req = urllib.request.Request(
        f"{api_server}/recipes/first-time-setup/preview",
        data=b"",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["status"] == "ok"
    assert payload["data"]["ok"] is True


def test_recipes_preview_unknown_returns_404(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post_json(f"{api_server}/recipes/nope/preview", {"overrides": {}})
    assert exc_info.value.code == 404


def test_recipes_preview_reports_step_errors_without_aborting(api_server):
    resp = _post_json(
        f"{api_server}/recipes/recover-from-bad-sync/preview",
        {"overrides": {}},
    )
    # Endpoint returns 200; per-step error is visible in step["errors"].
    assert resp["status"] == "error"
    step3 = next(s for s in resp["data"]["steps"] if s["id"] == 3)
    assert step3["errors"]


def test_recipes_preview_bad_overrides_type_returns_400(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post_json(
            f"{api_server}/recipes/first-time-setup/preview",
            {"overrides": "not-a-dict"},
        )
    assert exc_info.value.code == 400


def test_recipes_preview_requires_confirm_flag_propagates(api_server):
    """daily-sync step 4 is apply and should set requires_confirm."""
    resp = _post_json(f"{api_server}/recipes/daily-sync/preview")
    step4 = next(s for s in resp["data"]["steps"] if s["id"] == 4)
    assert step4["requires_confirm"] is True
