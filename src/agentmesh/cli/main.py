from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentmesh import __version__
from agentmesh.cli.agents import _agent_info_data
from agentmesh.cli.agents import app as agents_app
from agentmesh.cli.audit import app as audit_app
from agentmesh.cli.backup import app as backup_app
from agentmesh.cli.envelope import build_envelope
from agentmesh.cli.history import app as history_app
from agentmesh.cli.memory import app as memory_app
from agentmesh.cli.model import app as model_app
from agentmesh.cli.package import app as package_app
from agentmesh.cli.prompts import app as prompts_app
from agentmesh.cli.rollback import app as rollback_app
from agentmesh.cli.runtime import app as runtime_app
from agentmesh.cli.skills import app as skills_app
from agentmesh.cli.tool import app as tool_app
from agentmesh.config.loader import (
    ensure_layout,
    resolve_agentmesh_home,
)
from agentmesh.services.overview_service import build_local_overview

console = Console()
app = typer.Typer(help="AgentMesh：本地优先的 AI Agent 资产互通层。")
local_app = typer.Typer(help="本机轻量状态命令。")
app.add_typer(agents_app, name="agents")
app.add_typer(skills_app, name="skills")
app.add_typer(prompts_app, name="prompts")
app.add_typer(audit_app, name="audit")
app.add_typer(history_app, name="history")
app.add_typer(backup_app, name="backup")
app.add_typer(rollback_app, name="rollback")
app.add_typer(package_app, name="package")
app.add_typer(runtime_app, name="runtime")
app.add_typer(memory_app, name="memory")
app.add_typer(model_app, name="model")
app.add_typer(tool_app, name="tool")
app.add_typer(local_app, name="local")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"AgentMesh {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="显示版本号。"),
    ] = False,
) -> None:
    _ = version


_cli_response = build_envelope


def _overview_next_steps() -> list[str]:
    return [
        "Run `agentmesh agents list` for runtime details.",
        "Run `agentmesh runtime load-plan --target <agent> --json` "
        "to inspect LoadPlan alpha state.",
    ]


def _print_overview(data: dict[str, object]) -> None:
    console.print("AgentMesh Local Overview")
    console.print(f"Version: {data['version']}")
    console.print(f"Registry: {data['registry']}")
    console.print(f"Local-first: {'yes' if data['local_first'] else 'no'}")
    console.print(f"Default dry-run: {'yes' if data['default_dry_run'] else 'no'}")
    console.print("")
    network = data["network"]
    console.print(f"HTTP server: {network['http_server']}")
    console.print(f"Dashboard UI: {network['dashboard_ui']}")
    console.print(f"Default bind: {network['default_bind']}")
    runtime = data["runtime"]
    console.print(f"Runtime LoadPlan schema: {runtime['load_plan_schema']}")
    console.print(f"Runtime Auto-Load: {runtime['auto_load']}")
    console.print(f"Native LoadPlan consumption: {runtime['native_load_plan_consumption']}")
    safety = data["safety"]
    console.print(f"Codex .system protected: {'yes' if safety['codex_system_protected'] else 'no'}")
    console.print(
        f"Claude Code auto-install: {'yes' if safety['claude_code_auto_install'] else 'no'}"
    )
    console.print("")
    table = Table(title="Local agents")
    for column in ["name", "installed", "mode", "writable", "protected"]:
        table.add_column(column)
    for agent in data["agents"]:
        table.add_row(
            str(agent["name"]),
            "yes" if agent["installed"] else "no",
            str(agent["mode"]),
            "yes" if agent["writable"] else "no",
            ",".join(agent["protected_paths"]) or "-",
        )
    console.print(table)


def _emit_overview(
    *,
    registry: str | None,
    json_output: bool,
    schema: str,
    command: str,
) -> None:
    home = resolve_agentmesh_home(registry)
    data = build_local_overview(home)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema=schema,
                    command=command,
                    status="ok",
                    data=data,
                    next_steps=_overview_next_steps(),
                ),
                ensure_ascii=False,
            )
        )
        return
    _print_overview(data)


@app.command()
def overview(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _emit_overview(
        registry=registry,
        json_output=json_output,
        schema="agentmesh.overview/v1",
        command="overview",
    )


@local_app.command("status")
def local_status(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _emit_overview(
        registry=registry,
        json_output=json_output,
        schema="agentmesh.local-status/v1",
        command="local status",
    )


@local_app.command("serve")
def local_serve(
    host: Annotated[str, typer.Option(help="绑定地址。")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="端口。")] = 9090,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    advanced: Annotated[
        bool,
        typer.Option(
            "--advanced",
            help=(
                "[已弃用] Phase A 之后 server 已合并为单一实现，--advanced 等价于默认行为。"
                "保留该参数仅为兼容性，将在后续版本移除。"
            ),
            hidden=True,
        ),
    ] = False,
) -> None:
    """启动 Local API HTTP server（统一只读 API + 命令执行 + 历史 + 收藏 + 批量）。"""
    home = resolve_agentmesh_home(registry)
    from agentmesh.local_api.server import serve

    if advanced:
        console.print(
            "[yellow]警告：`--advanced` 已被弃用。"
            "server.py 与 server_advanced.py 已在 Phase A 合并，"
            "默认行为即为完整功能，请移除该参数。[/yellow]"
        )

    console.print("Starting AgentMesh Local API Server...")
    console.print(f"Address: http://{host}:{port}")
    console.print(f"Registry: {home}")
    console.print(
        "Features: Read-only API, command execution, history, favorites, batch operations"
    )
    console.print("")
    serve(host=host, port=port, registry=str(home))


@app.command()
def init(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    home = resolve_agentmesh_home(registry)
    ensure_layout(home)
    console.print(f"已初始化 AgentMesh：{home}")


@app.command()
def doctor(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    ensure_layout(home)
    agents = _agent_info_data()

    # Runtime health checks for each known target
    from agentmesh.services.runtime_service import (
        RUNTIME_TARGETS,
        bootstrap_status,
    )

    runtime_checks: list[dict] = []
    doctor_warnings: list[str] = []
    for target in RUNTIME_TARGETS:
        status, status_warnings = bootstrap_status(home, target)
        check: dict = {
            "target": target,
            "installed": status["installed"],
            "managed": status.get("managed", False),
            "plan_stale": status.get("plan_stale"),
            "rendered_file_exists": status.get("rendered_file_exists"),
            "rendered_file_path": status.get("rendered_file_path"),
            "warnings": status_warnings,
        }
        runtime_checks.append(check)
        if status.get("installed") and status.get("managed"):
            doctor_warnings.extend(status_warnings)

    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.doctor/v1",
                    command="doctor",
                    status="ok",
                    data={
                        "home": str(home),
                        "agents": agents,
                        "runtime_checks": runtime_checks,
                    },
                    warnings=doctor_warnings,
                    next_steps=["Run `agentmesh agents list` for a focused runtime summary."],
                ),
                ensure_ascii=False,
            )
        )
        return
    typer.echo(f"AgentMesh home: {home}")
    for info in agents:
        agent_status = "installed" if info["installed"] else "missing"
        typer.echo(
            f"- {info['name']}: {agent_status}, mode={info['mode']}, path={info['skill_dir']}"
        )
    typer.echo("")
    typer.echo("Runtime health checks:")
    for check in runtime_checks:
        if not check["installed"]:
            typer.echo(f"  - {check['target']}: not installed")
            continue
        parts = [f"  - {check['target']}: installed"]
        if check["managed"]:
            parts.append("managed")
        if check.get("plan_stale"):
            parts.append("[STALE]")
        if check.get("rendered_file_exists") is False:
            parts.append("[RENDERED FILE MISSING]")
        elif check.get("rendered_file_exists"):
            parts.append("rendered OK")
        typer.echo(", ".join(parts))
        for w in check.get("warnings", []):
            typer.echo(f"    ⚠ {w}")
    if not doctor_warnings:
        typer.echo("\n✓ All runtime checks passed.")


def main() -> None:
    app()
