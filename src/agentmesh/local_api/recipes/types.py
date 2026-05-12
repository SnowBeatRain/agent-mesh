"""Recipe dataclasses plus ``preview_recipe``.

Recipes intentionally stay dumb — they describe an ordered list of
``CommandSchema`` ids plus default parameter values. The Phase B4
``assemble_command`` does the heavy lifting for each step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Difficulty = Literal["beginner", "intermediate", "advanced"]


class RecipeValidationError(ValueError):
    """Raised when a recipe references an unknown command id or fails at preview."""


@dataclass(frozen=True)
class RecipeStep:
    """One step in a Recipe.

    ``params_defaults`` supplies the default param values for the step's
    :class:`CommandSchema`. The workstation UI may override any of them
    before previewing / executing.
    """

    id: int
    title: str
    command_id: str
    description: str = ""
    params_defaults: dict[str, Any] = field(default_factory=dict)
    requires_confirm: bool = False
    expected_duration_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "command_id": self.command_id,
            "description": self.description,
            "params_defaults": dict(self.params_defaults),
            "requires_confirm": self.requires_confirm,
        }
        if self.expected_duration_seconds is not None:
            data["expected_duration_seconds"] = self.expected_duration_seconds
        return data


@dataclass(frozen=True)
class Recipe:
    """A short, opinionated workflow bundling several CLI commands.

    Recipes are meant to be *runnable by humans with light review*, not
    silent automations. Destructive steps set ``requires_confirm=True`` so
    the front-end inserts an explicit confirmation gate.
    """

    id: str
    title: str
    description: str
    difficulty: Difficulty = "beginner"
    est_minutes: int = 5
    prerequisites: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    steps: tuple[RecipeStep, ...] = ()
    schema_version: str = "agentmesh.recipe/v1"

    def to_dict(self, *, include_steps: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema": self.schema_version,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "difficulty": self.difficulty,
            "est_minutes": self.est_minutes,
            "prerequisites": list(self.prerequisites),
            "tags": list(self.tags),
            "step_count": len(self.steps),
        }
        if include_steps:
            data["steps"] = [step.to_dict() for step in self.steps]
        return data
