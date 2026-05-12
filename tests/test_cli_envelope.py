from __future__ import annotations

import pytest

from agentmesh.cli.envelope import build_envelope


def test_build_envelope_fills_required_fields_and_defaults():
    payload = build_envelope(
        "agentmesh.example/v1",
        "example command",
        "ok",
        {"items": []},
        {"total": 0},
    )

    assert payload == {
        "schema": "agentmesh.example/v1",
        "command": "example command",
        "status": "ok",
        "data": {"items": []},
        "summary": {"total": 0},
        "warnings": [],
        "errors": [],
        "next_steps": [],
    }


def test_build_envelope_rejects_unknown_status():
    with pytest.raises(ValueError, match="invalid envelope status"):
        build_envelope("agentmesh.example/v1", "example", "weird", {}, {})


def test_build_envelope_copies_mutable_lists():
    warnings = ["careful"]
    payload = build_envelope(
        "agentmesh.example/v1",
        "example",
        "blocked",
        {},
        {},
        warnings=warnings,
        errors=["blocked"],
        next_steps=["fix it"],
    )
    warnings.append("mutated")

    assert payload["warnings"] == ["careful"]
    assert payload["errors"] == ["blocked"]
    assert payload["next_steps"] == ["fix it"]
