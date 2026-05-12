from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import json
from pathlib import Path
from typing import Any
from datetime import datetime
import os

LOCAL_API_SCHEMA = "agentmesh.local-api-response/v1"

# Command history storage file
COMMAND_HISTORY_FILE = Path.home() / ".agentmesh" / "command_history.json"
# Favorites storage file
FAVORITES_FILE = Path.home() / ".agentmesh" / "command_favorites.json"


def _resolve_cli_executable() -> list[str]:
    """Resolve the AgentMesh CLI executable.

    Strategy (in order):
    1. If ``am`` is on PATH, use it directly.
    2. If ``agentmesh`` is on PATH, use it directly.
    3. Fall back to ``sys.executable -m agentmesh.cli.main`` which always
       works when the package is importable in the current Python environment.
    """
    if shutil.which("am"):
        return ["am"]
    if shutil.which("agentmesh"):
        return ["agentmesh"]
    # Fallback: run via the current Python interpreter as a module.
    return [sys.executable, "-m", "agentmesh.cli.main"]


# Cache the resolved CLI prefix so we don't stat the filesystem on every call.
_CLI_PREFIX: list[str] | None = None


def _get_cli_prefix() -> list[str]:
    global _CLI_PREFIX
    if _CLI_PREFIX is None:
        _CLI_PREFIX = _resolve_cli_executable()
    return _CLI_PREFIX


def _resolve_default_registry() -> Path:
    """Return the default AgentMesh home directory, creating it if needed."""
    home = Path.home() / ".agentmesh"
    home.mkdir(parents=True, exist_ok=True)
    return home


class CommandExecutionError(Exception):
    """Custom exception for command execution errors."""
    def __init__(self, message: str, exit_code: int | None = None):
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class CommandExecutor:
    """Safe command executor with timeout and output capture."""
    def __init__(self, timeout: int = 30, registry: str | Path | None = None):
        self.timeout = timeout
        # Always resolve a registry path — use default ~/.agentmesh if not given.
        if registry:
            self.registry = Path(registry).expanduser().resolve()
        else:
            self.registry = _resolve_default_registry()

    def execute_sync(self, command: str) -> dict[str, Any]:
        """Execute command synchronously with timeout."""
        try:
            args = shlex.split(command)
            if not args:
                raise CommandExecutionError("Empty command")

            # 安全验证：只允许 am 和 agentmesh 命令
            if args[0] not in ("am", "agentmesh"):
                raise CommandExecutionError(
                    f"Only 'am' and 'agentmesh' commands are allowed, got: {args[0]!r}"
                )

            # Replace the command name (am/agentmesh) with the resolved CLI
            # prefix. This handles the case where 'am' isn't on PATH but the
            # package is importable via `python -m`.
            cli_prefix = _get_cli_prefix()
            args = cli_prefix + args[1:]

            # 智能添加 registry 参数
            needs_registry = self._needs_registry_parameter(args)
            if self.registry and needs_registry and "--registry" not in args:
                args.extend(["--registry", str(self.registry)])

            # 执行命令
            env = os.environ.copy()
            # Ensure the current Python's Scripts/bin is on PATH so that
            # entry-point scripts can be found.
            python_bin_dir = str(Path(sys.executable).parent)
            if python_bin_dir not in env.get("PATH", ""):
                env["PATH"] = python_bin_dir + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,  # Return the original user-facing command
                "error": result.stderr.strip() if result.stderr and result.returncode != 0 else None
            }

        except CommandExecutionError:
            raise
        except subprocess.TimeoutExpired:
            raise CommandExecutionError(
                f"Command timed out after {self.timeout} seconds", exit_code=-1
            )
        except FileNotFoundError as e:
            raise CommandExecutionError(
                f"CLI executable not found: {e}. "
                f"Ensure AgentMesh is installed (`pip install -e .` or `pip install agentmesh`)."
            )
        except OSError as e:
            raise CommandExecutionError(f"OS error executing command: {e}")
        except Exception as e:
            raise CommandExecutionError(f"Command execution failed: {e}")

    def _needs_registry_parameter(self, args: list[str]) -> bool:
        """判断命令是否需要 registry 参数。

        Args:
            args: 已替换 CLI 前缀后的命令参数列表

        Returns:
            True 如果命令需要 registry 参数，否则 False
        """
        # 如果已经包含 --registry 参数，不需要再次添加
        if "--registry" in args:
            return False

        # 检查是否是全局选项（不需要 registry）
        global_options = {"--help", "--version", "-h", "-v"}
        for opt in global_options:
            if opt in args:
                return False

        # 需要 registry 的命令列表
        registry_commands = {
            "skills", "agents", "sync", "import", "export", "scan",
            "init", "doctor", "overview", "history", "backup", "rollback",
            "runtime", "memory", "model", "tool", "audit"
        }

        # Find the first positional argument after the CLI prefix.
        # The CLI prefix is _get_cli_prefix() which could be ["am"] or
        # ["/path/python", "-m", "agentmesh.cli.main"]. We look for the
        # first arg that doesn't start with "-" and isn't part of the
        # interpreter invocation.
        cli_prefix_len = len(_get_cli_prefix())
        remaining = args[cli_prefix_len:]
        for token in remaining:
            if token.startswith("-"):
                continue
            # First positional token after prefix is the sub-command
            return token in registry_commands

        # 默认不添加 registry
        return False

    def execute_command(self, command: str, dry_run: bool = False) -> dict[str, Any]:
        """Execute a command with optional dry-run mode.

        Args:
            command: Command string to execute
            dry_run: If True, add --dry-run flag to command

        Returns:
            Dictionary with execution result and status field
        """
        # Add dry-run flag if requested
        actual_command = command
        if dry_run and '--dry-run' not in command:
            actual_command = f"{command} --dry-run"

        result = self.execute_sync(actual_command)

        # status field is consumed by HTTP server response builder
        status = "success" if result.get("success") else "error"
        result["status"] = status
        result["dry_run"] = dry_run

        return result

    def load_command_history(self) -> list[dict[str, Any]]:
        """Load command history from storage.

        Returns:
            List of command history entries
        """
        try:
            if COMMAND_HISTORY_FILE.exists():
                with open(COMMAND_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    return history[-100:]  # Return last 100 commands
            return []
        except Exception:
            return []

    def load_favorites(self) -> list[dict[str, Any]]:
        """Load favorite commands from storage.

        Returns:
            List of favorite command entries
        """
        try:
            if FAVORITES_FILE.exists():
                with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception:
            return []

    def add_favorite(self, command_id: str, category: str = "general") -> dict[str, Any]:
        """Add a command to favorites.

        Args:
            command_id: Command identifier or string
            category: Category for the favorite

        Returns:
            Result dictionary
        """
        try:
            favorites = self.load_favorites()

            # Check if already exists
            for fav in favorites:
                if fav.get("command") == command_id:
                    return {"success": False, "error": "Command already in favorites"}

            # Add new favorite
            new_favorite = {
                "id": len(favorites) + 1,
                "command": command_id,
                "category": category,
                "created_at": datetime.now().isoformat()
            }
            favorites.append(new_favorite)

            # Save to file
            FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
                json.dump(favorites, f, indent=2, ensure_ascii=False)

            return {"success": True, "favorite": new_favorite}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_favorite(self, favorite_id: int) -> dict[str, Any]:
        """Remove a command from favorites.

        Args:
            favorite_id: ID of the favorite to remove

        Returns:
            Result dictionary
        """
        try:
            favorites = self.load_favorites()

            # Find and remove the favorite
            favorites = [fav for fav in favorites if fav.get("id") != favorite_id]

            # Save to file
            FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
                json.dump(favorites, f, indent=2, ensure_ascii=False)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_commands(self, query: str) -> list[dict[str, Any]]:
        """Search for commands by query string.

        Args:
            query: Search query string

        Returns:
            List of matching command entries
        """
        try:
            # Search in command history
            history = self.load_command_history()
            results = []

            for entry in history:
                command = entry.get("command", "")
                if query.lower() in command.lower():
                    results.append(entry)

            # Search in favorites
            favorites = self.load_favorites()
            for fav in favorites:
                command = fav.get("command", "")
                if query.lower() in command.lower():
                    results.append({
                        "id": fav.get("id"),
                        "command": command,
                        "category": fav.get("category", "favorite"),
                        "source": "favorites"
                    })

            return results
        except Exception:
            return []

    def get_command_categories(self) -> list[dict[str, Any]]:
        """Get available command categories.

        Returns:
            List of category information
        """
        try:
            favorites = self.load_favorites()
            categories = set()

            for fav in favorites:
                categories.add(fav.get("category", "general"))

            # Add default categories
            categories.update(["skills", "agents", "sync", "export", "general"])

            return [
                {"name": cat, "count": sum(1 for f in favorites if f.get("category") == cat)}
                for cat in sorted(categories)
            ]
        except Exception:
            return [{"name": "general", "count": 0}]

    def get_batch_execution_plan(self, commands: list[str], targets: list[str]) -> dict[str, Any]:
        """Get a plan for batch command execution.

        Args:
            commands: List of commands to execute
            targets: List of target agents for sync commands

        Returns:
            Execution plan dictionary
        """
        try:
            plan = {
                "total_commands": len(commands),
                "commands": [],
                "estimated_time": len(commands) * 2,  # Estimate 2 seconds per command
                "targets": targets
            }

            for i, cmd in enumerate(commands):
                plan["commands"].append({
                    "id": i + 1,
                    "command": cmd,
                    "status": "pending",
                    "requires_confirmation": "sync" in cmd or "apply" in cmd
                })

            return {"success": True, "plan": plan}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_batch_commands(self, commands: list[str], targets: list[str], dry_run: bool = False) -> dict[str, Any]:
        """Execute multiple commands in batch.

        Args:
            commands: List of commands to execute
            targets: List of target agents for sync commands
            dry_run: If True, add --dry-run flag to commands

        Returns:
            Batch execution results
        """
        try:
            results = {
                "total": len(commands),
                "successful": 0,
                "failed": 0,
                "results": []
            }

            for cmd in commands:
                try:
                    # Execute the command
                    result = self.execute_command(cmd, dry_run=dry_run)

                    if result.get("success"):
                        results["successful"] += 1
                    else:
                        results["failed"] += 1

                    results["results"].append({
                        "command": cmd,
                        "success": result.get("success", False),
                        "output": result.get("stdout", ""),
                        "error": result.get("error")
                    })

                    # Add to command history
                    self._add_to_history(cmd, result.get("success", False))

                except Exception as e:
                    results["failed"] += 1
                    results["results"].append({
                        "command": cmd,
                        "success": False,
                        "error": str(e)
                    })

            return {"success": True, "results": results}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _add_to_history(self, command: str, success: bool) -> None:
        """Add command to history storage.

        Args:
            command: Command string
            success: Whether the command was successful
        """
        try:
            history = self.load_command_history()

            history.append({
                "command": command,
                "success": success,
                "timestamp": datetime.now().isoformat()
            })

            # Keep only last 1000 commands
            if len(history) > 1000:
                history = history[-1000:]

            # Save to file
            COMMAND_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(COMMAND_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Silently fail for history recording


def get_command_service(timeout: int = 30, registry: str | Path | None = None) -> CommandExecutor:
    """Get or create the global command executor instance."""
    return CommandExecutor(timeout=timeout, registry=registry)


def execute_command(command: str, dry_run: bool = False, timeout: int = 30, registry: str | Path | None = None) -> dict[str, Any]:
    """Execute an AgentMesh command safely.

    Args:
        command: Command string to execute
        dry_run: If True, add --dry-run flag to command
        timeout: Execution timeout in seconds
        registry: Registry path to use

    Returns:
        Dictionary with execution result and status field
    """
    executor = CommandExecutor(timeout=timeout, registry=registry)

    # Add dry-run flag if requested
    actual_command = command
    if dry_run and '--dry-run' not in command:
        actual_command = f"{command} --dry-run"

    result = executor.execute_sync(actual_command)

    # status field is consumed by HTTP server response builder
    status = "success" if result.get("success") else "error"
    result["status"] = status
    result["dry_run"] = dry_run

    return result


def build_command_response(command: str, result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    """Build a standardized Local API response for command execution."""
    if error:
        return {
            "schema": LOCAL_API_SCHEMA,
            "command": f"local-api command execute: {command}",
            "status": "error",
            "data": {"command": command, "executed": False},
            "warnings": [],
            "errors": [error],
            "next_steps": ["Check command syntax and try again"]
        }
    
    if result is None:
        return {
            "schema": LOCAL_API_SCHEMA,
            "command": f"local-api command execute: {command}",
            "status": "ok",
            "data": {"command": command, "executed": False, "message": "Command queued"},
            "warnings": [],
            "errors": [],
            "next_steps": []
        }
    
    return {
        "schema": LOCAL_API_SCHEMA,
        "command": f"local-api command execute: {command}",
        "status": "ok" if result.get("success") else "error",
        "data": {
            "command": result.get("command", command),
            "executed": True,
            "success": result.get("success", False),
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error")
        },
        "warnings": [] if result.get("success") else ["Command execution failed"],
        "errors": [] if result.get("success") else [result.get("error", "Unknown error")],
        "next_steps": [] if result.get("success") else ["Check command output"]
    }
