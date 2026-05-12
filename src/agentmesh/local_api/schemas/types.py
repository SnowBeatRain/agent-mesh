"""Command schema dataclasses and the ``assemble_command`` helper.

These are the dumb-data primitives used by the registry, the HTTP endpoints,
and the tests. They never touch the file system and never import the CLI.

A :class:`CommandSchema` is a plain description of one ``agentmesh`` command.
The workstation renders it as a form; when the user submits values, the
front-end (or the server, via ``POST /commands/plan``) calls
:func:`assemble_command` to turn the values into a runnable CLI string.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

# Parameter types supported by the workstation form renderer.
# Front-end chooses a widget based on this; server uses it to validate.
ParamType = Literal[
    "string",  # single-line text input
    "text",  # multi-line textarea (rare; used by prompts content)
    "boolean",  # toggle / checkbox
    "integer",  # numeric input (non-negative)
    "select",  # single choice from options list
    "multi-select",  # multiple choices, joined by cli_value_join (default ',')
    "path",  # filesystem path hint (validated only as string)
]


class SchemaValidationError(ValueError):
    """Raised when user-supplied values fail schema validation."""


@dataclass(frozen=True)
class CommandOption:
    """A single allowed option for ``select`` / ``multi-select`` params."""

    value: str
    label: str = ""

    def __post_init__(self) -> None:
        # Convenience: fall back to `value` when the caller did not supply a
        # display label. Frozen dataclasses need object.__setattr__.
        if not self.label:
            object.__setattr__(self, "label", self.value)

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class CommandParam:
    """One parameter the workstation asks the user to fill in.

    Fields summary:

    - ``name``: form field key + JSON key for values payload
    - ``label``: Chinese-friendly display label
    - ``type``: widget type (see :data:`ParamType`)
    - ``default``: default value (None means "omit unless user provides")
    - ``required``: whether the user must supply a value
    - ``help``: short description for form tooltip
    - ``options``: allowed values for ``select`` / ``multi-select``
    - ``options_endpoint``: alternative to ``options`` — a Local API path
      (e.g. ``/agents``) whose response ``data`` supplies options dynamically
    - ``cli_flag``: long flag to emit, e.g. ``--target``; ``None`` means a
      positional argument
    - ``cli_value_join``: separator for ``multi-select`` values (default ",")
    - ``cli_flag_when_true`` / ``cli_flag_when_false``: for ``boolean`` params
      where the flag name differs by truthiness (e.g. ``--dry-run`` vs ``--apply``)
    - ``visible_when``: expression string describing when the UI should show
      this field (server does not evaluate it; front-end is authoritative)
    - ``validate_regex``: optional regex the string value must match; enforced
      by :func:`validate_values`
    """

    name: str
    label: str
    type: ParamType
    default: Any = None
    required: bool = False
    help: str | None = None
    options: tuple[CommandOption, ...] = ()
    options_endpoint: str | None = None
    cli_flag: str | None = None
    cli_value_join: str = ","
    cli_flag_when_true: str | None = None
    cli_flag_when_false: str | None = None
    visible_when: str | None = None
    validate_regex: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
        }
        if self.default is not None:
            data["default"] = self.default
        if self.help is not None:
            data["help"] = self.help
        if self.options:
            data["options"] = [opt.to_dict() for opt in self.options]
        if self.options_endpoint is not None:
            data["options_endpoint"] = self.options_endpoint
        if self.cli_flag is not None:
            data["cli_flag"] = self.cli_flag
        if self.cli_value_join != ",":
            data["cli_value_join"] = self.cli_value_join
        if self.cli_flag_when_true is not None:
            data["cli_flag_when_true"] = self.cli_flag_when_true
        if self.cli_flag_when_false is not None:
            data["cli_flag_when_false"] = self.cli_flag_when_false
        if self.visible_when is not None:
            data["visible_when"] = self.visible_when
        if self.validate_regex is not None:
            data["validate_regex"] = self.validate_regex
        return data


@dataclass(frozen=True)
class CommandSchema:
    """Describes a single high-frequency ``agentmesh`` command.

    The schema is identified by a dotted ``id`` (e.g. ``"skills.sync"``) that
    is stable across versions; ``command`` is the matching CLI prefix without
    any flags.
    """

    id: str
    title: str
    command: str  # e.g. "am skills sync"
    description: str
    params: tuple[CommandParam, ...] = ()
    category: str = "general"  # "skills" | "agents" | "audit" | ...
    destructive: bool = False  # whether apply/write is possible
    confirmation_required: bool = False  # UI should show a confirm modal
    tags: tuple[str, ...] = ()
    schema_version: str = "agentmesh.command-schema/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_version,
            "id": self.id,
            "title": self.title,
            "command": self.command,
            "description": self.description,
            "category": self.category,
            "destructive": self.destructive,
            "confirmation_required": self.confirmation_required,
            "tags": list(self.tags),
            "params": [p.to_dict() for p in self.params],
        }


# ─────────────────────────────────────────────────────────────────────────
# Command assembly
# ─────────────────────────────────────────────────────────────────────────


def _coerce_bool(raw: Any) -> bool:
    """Accept the usual "truthy" JSON shapes (bool / int / "true"/"false"/"")."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off", ""}:
            return False
    raise SchemaValidationError(f"expected boolean, got {raw!r}")


def _coerce_int(raw: Any) -> int:
    if isinstance(raw, bool):  # bool is a subclass of int; reject it here
        raise SchemaValidationError(f"expected integer, got bool {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    raise SchemaValidationError(f"expected integer, got {raw!r}")


def _coerce_string(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float, bool)):
        return str(raw)
    raise SchemaValidationError(f"expected string, got {raw!r}")


def _coerce_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, Iterable):
        return [str(item) for item in raw]
    raise SchemaValidationError(f"expected list or comma-separated string, got {raw!r}")


def validate_values(schema: CommandSchema, values: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors.

    Empty list means the values are acceptable for :func:`assemble_command`.

    The validator is intentionally lenient: it checks only what the CLI will
    also check (required-ness, select membership, basic types). Regex and
    ``validate_regex`` are enforced here so typos don't reach the subprocess.
    """
    import re

    errors: list[str] = []
    for param in schema.params:
        supplied = values.get(param.name, None)

        if param.required:
            missing = supplied is None or (
                isinstance(supplied, (str, list, tuple)) and len(supplied) == 0
            )
            if missing:
                errors.append(f"missing required parameter: {param.name}")
                continue

        if supplied is None:
            continue

        try:
            if param.type == "boolean":
                _coerce_bool(supplied)
            elif param.type == "integer":
                _coerce_int(supplied)
            elif param.type in {"string", "text", "path"}:
                _coerce_string(supplied)
            elif param.type == "select":
                text = _coerce_string(supplied)
                if param.options:
                    allowed = {opt.value for opt in param.options}
                    if text not in allowed:
                        errors.append(
                            f"invalid value for {param.name!r}: {text!r} not in {sorted(allowed)}"
                        )
                        continue
            elif param.type == "multi-select":
                parts = _coerce_list(supplied)
                if param.options:
                    allowed = {opt.value for opt in param.options}
                    bad = [p for p in parts if p not in allowed]
                    if bad:
                        errors.append(
                            f"invalid value(s) for {param.name!r}: {bad} not in {sorted(allowed)}"
                        )
                        continue
        except SchemaValidationError as exc:
            errors.append(f"{param.name}: {exc}")
            continue

        if param.validate_regex and isinstance(supplied, str):
            if not re.fullmatch(param.validate_regex, supplied):
                errors.append(
                    f"{param.name!r} must match /{param.validate_regex}/ (got {supplied!r})"
                )

    return errors


def assemble_command(schema: CommandSchema, values: dict[str, Any]) -> str:
    """Assemble a runnable CLI command string from user-supplied values.

    Raises :class:`SchemaValidationError` if validation fails.

    Contract:
    - Output always starts with ``schema.command`` (e.g. ``"am skills sync"``).
    - Boolean params emit ``cli_flag_when_true`` / ``cli_flag_when_false`` or
      ``cli_flag`` depending on the truthiness.
    - Multi-select params emit a single flag with comma-joined values.
    - Positional params (``cli_flag=None``) are appended in declaration order
      after all flags.
    - Values supplied but not in schema are silently ignored (front-end may
      sometimes carry UI-only state).
    - All values are shell-escaped via :func:`shlex.quote`.
    """
    errors = validate_values(schema, values)
    if errors:
        raise SchemaValidationError("; ".join(errors))

    flag_tokens: list[str] = []
    positional_tokens: list[str] = []

    for param in schema.params:
        supplied = values.get(param.name, None)
        # Allow default to satisfy required / provide CLI value.
        if supplied is None:
            supplied = param.default

        if param.type == "boolean":
            # Boolean resolved even when supplied is None and default is None:
            # treat as False (flag not emitted).
            truthy = False if supplied is None else _coerce_bool(supplied)
            if truthy:
                flag = param.cli_flag_when_true or param.cli_flag
                if flag:
                    flag_tokens.append(flag)
            else:
                flag = param.cli_flag_when_false
                if flag:
                    flag_tokens.append(flag)
            continue

        if supplied is None:
            continue  # nothing to emit

        if param.type == "multi-select":
            parts = _coerce_list(supplied)
            if not parts:
                continue
            joined = param.cli_value_join.join(parts)
            if param.cli_flag:
                flag_tokens.append(param.cli_flag)
                flag_tokens.append(shlex.quote(joined))
            else:
                positional_tokens.append(shlex.quote(joined))
            continue

        if param.type == "integer":
            text = str(_coerce_int(supplied))
        else:
            text = _coerce_string(supplied)

        if text == "" and not param.required:
            continue

        if param.cli_flag:
            flag_tokens.append(param.cli_flag)
            flag_tokens.append(shlex.quote(text))
        else:
            positional_tokens.append(shlex.quote(text))

    parts = [schema.command, *positional_tokens, *flag_tokens]
    return " ".join(part for part in parts if part)


def param(**kwargs: Any) -> CommandParam:
    """Tiny helper to keep schema registration readable."""
    return CommandParam(**kwargs)


def option(value: str, label: str | None = None) -> CommandOption:
    """Shorthand for a select/multi-select option."""
    return CommandOption(value=value, label=label or value)


# Re-export the common builders so authoring modules don't need two imports.
__all__ = [
    "CommandOption",
    "CommandParam",
    "CommandSchema",
    "SchemaValidationError",
    "assemble_command",
    "option",
    "param",
    "validate_values",
]
