from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

NATIVE_VALIDATORS = {
    "hermes": {
        "binary": "hermes",
        "command": ["hermes", "skills", "check"],
    },
    "openclaw": {
        "binary": "openclaw",
        "command": ["openclaw", "skills", "check"],
    },
    "claude-code": {
        "binary": "claude",
        "command": ["claude", "plugins", "validate", "{path}"],
    },
    "codex": {
        "binary": "codex",
        "command": ["codex", "skills", "validate"],
    },
    "cursor": {
        "binary": "cursor",
        "command": ["cursor", "--version"],
    },
    "windsurf": {
        "binary": "windsurf",
        "command": ["windsurf", "--version"],
    },
    "aider": {
        "binary": "aider",
        "command": ["aider", "--version"],
    },
}


def validate_native_runtime(
    target: str,
    path: Path,
    *,
    which: Callable[[str], str | None] | None = None,
    runner: Callable[..., CompletedProcess[str]] | None = None,
) -> dict:
    spec = NATIVE_VALIDATORS.get(target)
    if spec is None:
        return {
            "target": target,
            "status": "unsupported",
            "command": [],
            "exit_code": None,
            "message": f"unsupported native validator target: {target}",
        }

    which_fn = which or shutil.which
    binary = spec["binary"]
    command = [part.format(path=str(path)) for part in spec["command"]]
    if which_fn(binary) is None:
        return {
            "target": target,
            "status": "skipped",
            "command": command,
            "exit_code": None,
            "message": f"native validator not found: {binary}",
        }

    run = runner or subprocess.run
    completed = run(command, capture_output=True, text=True, timeout=60)
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    message = (
        stdout or stderr or ("ok" if completed.returncode == 0 else "native validation failed")
    )
    return {
        "target": target,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "exit_code": completed.returncode,
        "message": message,
    }
