"""In-memory registry of built-in Recipes, plus ``preview_recipe``."""

from __future__ import annotations

from typing import Any

from agentmesh.local_api.recipes.types import (
    Recipe,
    RecipeValidationError,
)
from agentmesh.local_api.schemas import (
    SchemaValidationError,
    assemble_command,
    get_schema,
)

_REGISTRY: dict[str, Recipe] = {}


def register_recipe(recipe: Recipe) -> None:
    """Register a recipe; later registrations replace earlier ones by id."""
    _REGISTRY[recipe.id] = recipe


def get_recipe(recipe_id: str) -> Recipe | None:
    return _REGISTRY.get(recipe_id)


def list_recipes() -> list[Recipe]:
    return [_REGISTRY[key] for key in sorted(_REGISTRY)]


def clear_registry() -> None:
    """Used by tests only."""
    _REGISTRY.clear()


def preview_recipe(
    recipe_id: str,
    *,
    overrides: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand a recipe into its assembled command strings without executing.

    ``overrides`` is a per-step-id mapping of parameter overrides; each step's
    final values are ``params_defaults | overrides.get(step.id, {})``.

    Return payload::

        {
            "recipe": {...recipe.to_dict(include_steps=False)...},
            "steps": [
                {
                    "id": 1,
                    "title": "...",
                    "command_id": "init",
                    "values": {...},
                    "command": "am init --registry .tmp-agentmesh",
                    "errors": [],
                    "requires_confirm": False,
                    "schema": {...},
                },
                ...
            ],
            "ok": True,  # False if any step has validation errors
        }

    The function never raises for *per-step* validation issues — those are
    reported in each step's ``errors`` list so the UI can highlight them.
    A missing recipe id or a step referencing an unknown command, however,
    is a programmer error and does raise :class:`RecipeValidationError`.
    """
    recipe = get_recipe(recipe_id)
    if recipe is None:
        raise RecipeValidationError(f"unknown recipe: {recipe_id}")

    overrides = overrides or {}
    # Normalise override keys: accept int, numeric string, or "1"/"2" forms.
    normalised_overrides: dict[int, dict[str, Any]] = {}
    for key, value in overrides.items():
        try:
            normalised_overrides[int(key)] = value or {}
        except (TypeError, ValueError) as exc:
            raise RecipeValidationError(
                f"recipe preview override key must be an integer step id, got {key!r}"
            ) from exc

    out_steps: list[dict[str, Any]] = []
    ok = True

    for step in recipe.steps:
        schema = get_schema(step.command_id)
        if schema is None:
            raise RecipeValidationError(
                f"recipe {recipe_id!r} step {step.id} references unknown command id "
                f"{step.command_id!r}; fix the Recipe definition"
            )

        merged_values: dict[str, Any] = {
            **step.params_defaults,
            **normalised_overrides.get(step.id, {}),
        }

        errors: list[str] = []
        command = ""
        try:
            command = assemble_command(schema, merged_values)
        except SchemaValidationError as exc:
            errors.append(str(exc))
            ok = False

        out_steps.append(
            {
                "id": step.id,
                "title": step.title,
                "command_id": step.command_id,
                "description": step.description,
                "values": merged_values,
                "command": command,
                "errors": errors,
                "requires_confirm": step.requires_confirm or schema.destructive,
                "schema": schema.to_dict(),
            }
        )

    return {
        "recipe": recipe.to_dict(include_steps=False),
        "steps": out_steps,
        "ok": ok,
    }


# Import built-in recipe definitions so register_recipe fires on package load.
from agentmesh.local_api.recipes import builtin as _builtin  # noqa: E402,F401
