"""Recipes: opinionated multi-step workflows for the Web 工作台.

A :class:`Recipe` is a small, hand-curated sequence of ``agentmesh`` commands
with Chinese descriptions, aimed at teaching or automating a typical flow
(first-time setup, daily sync, migration, etc.).

Each ``RecipeStep`` references a registered :class:`CommandSchema` by id plus
the default parameter values for that step. The workstation can:

1. List recipes via ``GET /recipes`` (summary payload).
2. Fetch one via ``GET /recipes/<id>`` (full steps with defaults).
3. Preview via ``POST /recipes/<id>/preview`` with user-supplied value
   overrides, which returns the fully-assembled CLI string for each step.

Like schemas, recipes are declarative and pure; nothing is executed at
import time. Execution lives in the front-end (step-by-step) or via the
regular ``/commands/execute`` endpoint per step.
"""

from __future__ import annotations

from agentmesh.local_api.recipes.registry import (
    get_recipe,
    list_recipes,
    preview_recipe,
    register_recipe,
)
from agentmesh.local_api.recipes.types import (
    Recipe,
    RecipeStep,
    RecipeValidationError,
)

__all__ = [
    "Recipe",
    "RecipeStep",
    "RecipeValidationError",
    "get_recipe",
    "list_recipes",
    "preview_recipe",
    "register_recipe",
]
