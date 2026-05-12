"""AgentMesh Local API HTTP server.

This module provides the unified HTTP server for the AgentMesh Local API and
Dashboard. It combines the previously-separate basic (`server.py`) and advanced
(`server_advanced.py`) servers into a single entrypoint.

Endpoints:
- ``GET /``                — Dashboard HTML (Rich UI)
- ``GET /dashboard``       — Alias for dashboard HTML
- ``GET /<readonly path>`` — Read-only JSON endpoints (see ``service.py``)
- ``POST /commands/execute``     — Execute an ``am`` CLI command
- ``POST /commands/history``     — Return saved command history
- ``POST /commands/favorites``   — Favorites CRUD (action: get|add|delete)
- ``DELETE /commands/favorites`` — Remove a favorite (alt path)
- ``POST /commands/search``      — Text search in history + favorites
- ``POST /commands/categories``  — Get favorite categories
- ``POST /commands/batch/plan``  — Preview a batch execution
- ``POST /commands/batch/execute`` — Execute a batch synchronously
- ``POST /export/history``       — Download history (json|csv|txt)

Security constraints (from threat model):
- Binds to 127.0.0.1 only (no remote access).
- No CORS headers are emitted.
- No authentication is required (localhost-only).
- Server must be started explicitly; it is never auto-started.
- Only ``am`` / ``agentmesh`` commands are permitted by ``command_service``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from agentmesh.local_api.command_service import (
    CommandExecutionError,
    build_command_response,
    execute_command,
    get_command_service,
)
from agentmesh.local_api.service import handle_readonly_request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090

# Canonical dashboard served at ``/`` and ``/dashboard``.
# Legacy root-level HTML snapshots are kept only as historical references and
# are not part of the server fallback path.
_DASHBOARD_CANDIDATES: tuple[str, ...] = (
    "static/dashboard.html",
)

_STATIC_DIR_NAME = "static"
_STATIC_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {".html", ".css", ".js", ".mjs", ".map", ".svg", ".png", ".ico", ".txt"}
)
_STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class _LocalAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler that exposes the Local API read-only endpoints plus
    command execution / history / favorites / batch endpoints."""

    registry: str | Path | None = None

    # ── GET ────────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "" or self.path == "/dashboard":
            self._serve_dashboard()
            return

        if self.path.startswith("/static/"):
            self._serve_static(self.path[len("/static/"):])
            return

        try:
            response = handle_readonly_request("GET", self.path, registry=self.registry)
            self._send_json_response(response)
        except Exception as exc:  # pragma: no cover - defensive
            self._send_error_response(f"Server error: {exc}", status=500)

    # ── POST ───────────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        route = self.path.rstrip("/")

        # Phase B5: /recipes/<id>/preview is parameterized; dispatch it
        # before the fixed route table lookup.
        if route.startswith("/recipes/") and route.endswith("/preview"):
            recipe_id = route[len("/recipes/") : -len("/preview")].strip("/")
            try:
                data = self._read_json_body_optional()
            except ValueError as exc:
                self._send_error_response(str(exc), status=400)
                return
            except json.JSONDecodeError as exc:
                self._send_error_response(f"Invalid JSON: {exc}", status=400)
                return
            try:
                self._handle_recipe_preview(recipe_id, data)
            except Exception as exc:  # pragma: no cover - defensive
                self._send_error_response(f"Server error: {exc}", status=500)
            return

        handler = self._post_routes().get(route)
        if handler is None:
            # 501: method is recognised but this path does not accept POST.
            self._send_error_response(
                f"POST not implemented for {self.path}",
                status=501,
            )
            return
        try:
            data = self._read_json_body()
        except ValueError as exc:
            self._send_error_response(str(exc), status=400)
            return
        except json.JSONDecodeError as exc:
            self._send_error_response(f"Invalid JSON: {exc}", status=400)
            return
        try:
            handler(data)
        except Exception as exc:  # pragma: no cover - defensive
            self._send_error_response(f"Server error: {exc}", status=500)

    # ── DELETE ─────────────────────────────────────────────────────────────

    def do_DELETE(self) -> None:
        """Handle DELETE requests (currently only ``/commands/favorites``)."""
        route = self.path.rstrip("/")
        if route != "/commands/favorites":
            self._send_error_response(
                f"DELETE not implemented for {self.path}",
                status=501,
            )
            return
        try:
            data = self._read_json_body()
        except ValueError as exc:
            self._send_error_response(str(exc), status=400)
            return
        except json.JSONDecodeError as exc:
            self._send_error_response(f"Invalid JSON: {exc}", status=400)
            return
        data = {**data, "action": "delete"}
        self._handle_favorites(data)

    # ── Route table ───────────────────────────────────────────────────────

    def _post_routes(self) -> dict[str, Any]:
        return {
            "/commands/execute": self._handle_command_execute,
            "/commands/history": lambda _data: self._handle_command_history(),
            "/commands/favorites": self._handle_favorites,
            "/commands/search": self._handle_command_search,
            "/commands/categories": lambda _data: self._handle_get_categories(),
            "/commands/batch/plan": self._handle_batch_plan,
            "/commands/batch/execute": self._handle_batch_execute,
            # Phase B4: assemble a CLI command string from a schema + values
            # without running it. The front-end also has a local assembler,
            # but this endpoint is the canonical validator.
            "/commands/plan": self._handle_command_plan,
            "/export/history": self._handle_export_history,
        }

    # ── Handlers ──────────────────────────────────────────────────────────

    def _handle_command_execute(self, data: dict) -> None:
        command = (data.get("command") or "").strip()
        if not command:
            self._send_error_response("Missing 'command' field in request", status=400)
            return
        timeout = int(data.get("timeout") or 30)
        dry_run = bool(data.get("dry_run", False))
        try:
            result = execute_command(
                command,
                dry_run=dry_run,
                timeout=timeout,
                registry=self.registry,
            )
            response = build_command_response(command, result=result)
        except CommandExecutionError as exc:
            response = build_command_response(command, error=exc.message)
        self._send_json_response(response)

    def _handle_command_plan(self, data: dict) -> None:
        """Assemble and validate a CLI command string *without* executing it.

        Request payload::

            {
                "command_id": "skills.sync",
                "values": {"to": ["hermes"], "dry_run": true, ...}
            }

        Response ``data``::

            {
                "command_id": "skills.sync",
                "command": "am skills sync --to hermes --dry-run ...",
                "schema": { ...schema.to_dict()... },
                "values": { ...echoed back for inspection... }
            }

        On validation errors the status is "error" and ``errors`` lists the
        specific problems. The front-end uses this for the live command
        preview pane; the CLI is the sole source of truth for execution.
        """
        # Lazy imports keep server startup cheap.
        from agentmesh.local_api.schemas import (
            SchemaValidationError,
            assemble_command,
            get_schema,
        )

        command_id = (data.get("command_id") or "").strip()
        values = data.get("values") or {}
        if not command_id:
            self._send_error_response(
                "Missing 'command_id' field in request",
                status=400,
            )
            return
        if not isinstance(values, dict):
            self._send_error_response(
                "'values' must be a JSON object",
                status=400,
            )
            return

        schema = get_schema(command_id)
        if schema is None:
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api command plan",
                    "status": "error",
                    "data": {"command_id": command_id, "values": values},
                    "warnings": [],
                    "errors": [f"unknown command schema: {command_id}"],
                    "next_steps": [
                        "GET /commands/schemas to list available command ids.",
                    ],
                },
                status=404,
            )
            return

        try:
            command = assemble_command(schema, values)
        except SchemaValidationError as exc:
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api command plan",
                    "status": "error",
                    "data": {
                        "command_id": command_id,
                        "values": values,
                        "schema": schema.to_dict(),
                    },
                    "warnings": [],
                    "errors": [str(exc)],
                    "next_steps": [
                        "Adjust the form values and retry; schema metadata is "
                        "included in data for debugging.",
                    ],
                },
                status=200,
            )
            return

        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api command plan",
                "status": "ok",
                "data": {
                    "command_id": command_id,
                    "command": command,
                    "schema": schema.to_dict(),
                    "values": values,
                    "destructive": schema.destructive,
                    "confirmation_required": schema.confirmation_required,
                },
                "warnings": (
                    ["This command is destructive; require user confirmation."]
                    if schema.destructive
                    else []
                ),
                "errors": [],
                "next_steps": [
                    'POST /commands/execute with {"command": "..."} to run it.',
                ],
            }
        )

    def _handle_command_history(self) -> None:
        svc = get_command_service(registry=self.registry)
        history = svc.load_command_history()
        response = {
            "schema": "agentmesh.local-api-response/v1",
            "command": "local-api command history",
            "status": "ok",
            "data": {"history": history, "total": len(history)},
            "warnings": [],
            "errors": [],
            "next_steps": [],
        }
        self._send_json_response(response)

    def _handle_favorites(self, data: dict) -> None:
        svc = get_command_service(registry=self.registry)
        action = (data.get("action") or "get").lower()
        if action == "get":
            favorites = svc.load_favorites()
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api favorites get",
                    "status": "ok",
                    "data": {"favorites": favorites, "total": len(favorites)},
                    "warnings": [],
                    "errors": [],
                    "next_steps": [],
                }
            )
            return
        if action == "add":
            command_id = data.get("command_id") or data.get("command")
            category = data.get("category") or "general"
            if not command_id:
                self._send_error_response("Missing 'command_id' for add", status=400)
                return
            result = svc.add_favorite(command_id, category)
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api favorites add",
                    "status": "ok" if result.get("success") else "error",
                    "data": result,
                    "warnings": [],
                    "errors": [] if result.get("success") else [result.get("error", "")],
                    "next_steps": [],
                }
            )
            return
        if action == "delete":
            fav_id = data.get("favorite_id") or data.get("id")
            if fav_id is None:
                self._send_error_response("Missing 'favorite_id' for delete", status=400)
                return
            try:
                fav_int = int(fav_id)
            except (TypeError, ValueError):
                self._send_error_response("'favorite_id' must be an integer", status=400)
                return
            result = svc.remove_favorite(fav_int)
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api favorites delete",
                    "status": "ok" if result.get("success") else "error",
                    "data": result,
                    "warnings": [],
                    "errors": [] if result.get("success") else [result.get("error", "")],
                    "next_steps": [],
                }
            )
            return
        self._send_error_response(f"Unsupported favorites action: {action}", status=400)

    def _handle_command_search(self, data: dict) -> None:
        query = (data.get("query") or "").strip()
        if not query:
            self._send_error_response("Missing 'query' field", status=400)
            return
        svc = get_command_service(registry=self.registry)
        results = svc.search_commands(query)
        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api command search",
                "status": "ok",
                "data": {"query": query, "results": results, "total": len(results)},
                "warnings": [],
                "errors": [],
                "next_steps": [],
            }
        )

    def _handle_get_categories(self) -> None:
        svc = get_command_service(registry=self.registry)
        categories = svc.get_command_categories()
        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api command categories",
                "status": "ok",
                "data": {"categories": categories},
                "warnings": [],
                "errors": [],
                "next_steps": [],
            }
        )

    def _handle_batch_plan(self, data: dict) -> None:
        commands = data.get("commands") or []
        targets = data.get("targets") or []
        if not commands:
            self._send_error_response("Missing 'commands' list", status=400)
            return
        svc = get_command_service(registry=self.registry)
        plan = svc.get_batch_execution_plan(commands, targets)
        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api batch plan",
                "status": "ok" if plan.get("success", True) else "error",
                "data": plan,
                "warnings": [],
                "errors": [] if plan.get("success", True) else [plan.get("error", "")],
                "next_steps": ["Use POST /commands/batch/execute to execute this plan."],
            }
        )

    def _handle_batch_execute(self, data: dict) -> None:
        """Execute a list of commands sequentially (synchronous)."""
        commands = data.get("commands") or []
        dry_run = bool(data.get("dry_run", False))
        timeout = int(data.get("timeout") or 30)
        if not commands:
            self._send_error_response("Missing 'commands' list", status=400)
            return
        results: list[dict[str, Any]] = []
        successful = 0
        failed = 0
        for cmd in commands:
            try:
                result = execute_command(
                    cmd,
                    dry_run=dry_run,
                    timeout=timeout,
                    registry=self.registry,
                )
                if result.get("success"):
                    successful += 1
                else:
                    failed += 1
                results.append(
                    {
                        "command": cmd,
                        "success": result.get("success", False),
                        "exit_code": result.get("exit_code"),
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "error": result.get("error"),
                    }
                )
            except CommandExecutionError as exc:
                failed += 1
                results.append({"command": cmd, "success": False, "error": exc.message})
        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api batch execute",
                "status": "ok",
                "data": {
                    "total": len(commands),
                    "successful": successful,
                    "failed": failed,
                    "results": results,
                },
                "warnings": [],
                "errors": [],
                "next_steps": [],
            }
        )

    def _handle_export_history(self, data: dict) -> None:
        """Download command history as json / csv / txt."""
        fmt = (data.get("format") or "json").lower()
        try:
            limit = int(data.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        svc = get_command_service(registry=self.registry)
        history = svc.load_command_history()
        if len(history) > limit:
            history = history[-limit:]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["command", "success", "timestamp"])
            for item in history:
                writer.writerow(
                    [
                        item.get("command", ""),
                        item.get("success", False),
                        item.get("timestamp", ""),
                    ]
                )
            content = buffer.getvalue()
            content_type = "text/csv; charset=utf-8"
            filename = f"agentmesh_history_{ts}.csv"
        elif fmt == "txt":
            lines = [
                "AgentMesh Command History Export",
                f"Exported: {datetime.now().isoformat()}",
                f"Total: {len(history)}",
                "-" * 40,
            ]
            for item in history:
                lines.append(
                    f"[{item.get('timestamp', '')}] "
                    f"{'OK ' if item.get('success') else 'ERR'} "
                    f"{item.get('command', '')}"
                )
            content = "\n".join(lines) + "\n"
            content_type = "text/plain; charset=utf-8"
            filename = f"agentmesh_history_{ts}.txt"
        else:
            content = json.dumps(
                {
                    "schema": "agentmesh.history-export/v1",
                    "exported_at": datetime.now().isoformat(),
                    "total": len(history),
                    "history": history,
                },
                ensure_ascii=False,
                indent=2,
            )
            content_type = "application/json; charset=utf-8"
            filename = f"agentmesh_history_{ts}.json"

        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    # ── Dashboard ─────────────────────────────────────────────────────────

    def _handle_recipe_preview(self, recipe_id: str, data: dict) -> None:
        """Assemble every step of a Recipe into CLI strings without running.

        Request body::

            { "overrides": { "1": {...}, "2": {...} } }

        Overrides are keyed by integer step id (strings accepted for JSON
        friendliness). Recipes preview independently of the registry, but we
        still pass ``registry`` through in the response so the UI can surface
        which AgentMesh home the recipe assumes.
        """
        from agentmesh.local_api.recipes import (
            RecipeValidationError,
            preview_recipe,
        )

        overrides = data.get("overrides") or {}
        if not isinstance(overrides, dict):
            self._send_error_response(
                "'overrides' must be a JSON object keyed by step id",
                status=400,
            )
            return

        try:
            plan = preview_recipe(recipe_id, overrides=overrides)
        except RecipeValidationError as exc:
            self._send_json_response(
                {
                    "schema": "agentmesh.local-api-response/v1",
                    "command": "local-api recipes preview",
                    "status": "error",
                    "data": {"recipe_id": recipe_id},
                    "warnings": [],
                    "errors": [str(exc)],
                    "next_steps": [
                        "GET /recipes to list available recipes and their step ids.",
                    ],
                },
                status=404,
            )
            return

        any_errors = any(step["errors"] for step in plan["steps"])
        self._send_json_response(
            {
                "schema": "agentmesh.local-api-response/v1",
                "command": "local-api recipes preview",
                "status": "ok" if plan["ok"] else "error",
                "data": plan,
                "warnings": (
                    ["One or more steps failed schema validation; see per-step errors."]
                    if any_errors
                    else []
                ),
                "errors": [],
                "next_steps": [
                    "POST /commands/execute per step, or use the front-end runner.",
                ],
            }
        )

    def _serve_static(self, relative: str) -> None:
        """Serve a file from ``local_api/static/`` with extension allowlist."""
        request_path = relative.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        if not request_path:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write(b"static asset not found")
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        static_root = (Path(__file__).parent / _STATIC_DIR_NAME).resolve()
        try:
            candidate = (static_root / request_path).resolve()
        except (OSError, RuntimeError):
            candidate = None

        if (
            candidate is None
            or not candidate.is_file()
            or static_root not in candidate.parents
            or candidate.suffix.lower() not in _STATIC_ALLOWED_SUFFIXES
        ):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write(b"static asset not found")
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        try:
            content = candidate.read_bytes()
        except OSError:
            self.send_response(500)
            self.end_headers()
            return

        content_type = _STATIC_CONTENT_TYPES.get(
            candidate.suffix.lower(), "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _serve_dashboard(self) -> None:
        dashboard_path = None
        for name in _DASHBOARD_CANDIDATES:
            candidate = Path(__file__).parent / name
            if candidate.exists():
                dashboard_path = candidate
                break

        if dashboard_path is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write(b"Dashboard not found.")
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        try:
            content = dashboard_path.read_bytes()
        except OSError as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write(f"Error loading dashboard: {exc}".encode())
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    # ── Helpers ───────────────────────────────────────────────────────────

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("Empty request body")
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _read_json_body_optional(self) -> dict:
        """Read a JSON body but treat empty body as ``{}``.

        Used by endpoints whose defaults make sense when the caller sends
        no overrides (e.g. ``POST /recipes/<id>/preview`` with no body
        should expand the recipe using its built-in defaults).
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _send_json_response(self, response: dict, status: int = 200) -> None:
        body = json.dumps(response, ensure_ascii=False, indent=2) + "\n"
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _send_error_response(self, message: str, *, status: int = 500) -> None:
        response = {
            "schema": "agentmesh.local-api-response/v1",
            "command": "error",
            "status": "error",
            "data": {},
            "warnings": [],
            "errors": [message],
            "next_steps": [],
        }
        self._send_json_response(response, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default stderr logging; rely on JSON responses.
        pass


# ── Module-level server API ──────────────────────────────────────────────


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    registry: str | Path | None = None,
) -> HTTPServer:
    """Create a localhost-only HTTP server exposing the unified Local API.

    Security constraints (from threat model):
    - Binds to ``127.0.0.1`` only (no remote access).
    - Only ``GET``, ``POST``, ``DELETE`` are handled; other methods return 501.
    - No CORS headers are emitted.
    - No authentication is required (localhost-only).
    - Server must be started explicitly; it is never auto-started.
    """
    # Pin the registry on the handler class so all requests share the same value.
    _LocalAPIHandler.registry = registry
    server = HTTPServer((host, port), _LocalAPIHandler)
    return server


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    registry: str | Path | None = None,
) -> None:
    """Start the unified Local API HTTP server (blocking).

    Use ``Ctrl+C`` to stop.
    """
    server = create_server(host, port, registry)
    print(f"AgentMesh Local API listening on http://{host}:{port}")
    print(f"Dashboard: http://{host}:{port}/")
    print(f"Registry: {registry or '(default)'}")
    print("Features: Read-only API, command execution, history, favorites, batch operations")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
