from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentmesh.cli.envelope import build_envelope
from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.sync_service import list_sync_history

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="同步历史查看命令；恢复命令仍在规划中。")


@app.command("list")
def history_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    entries = list_sync_history(home)
    response = _cli_response(
        schema="agentmesh.history-list/v1",
        command="history list",
        status="ok",
        data={"entries": entries},
        next_steps=["Use backup paths from history for future rollback planning."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    if not entries:
        console.print("暂无同步历史。")
        return
    table = Table(title="AgentMesh sync history")
    for col in ["id", "timestamp", "status", "targets", "actions"]:
        table.add_column(col)
    for entry in entries:
        table.add_row(
            str(entry["id"]),
            str(entry["timestamp"]),
            str(entry["status"]),
            ",".join(entry["targets"]),
            str(entry["summary"]["actions"]),
        )
    console.print(table)
