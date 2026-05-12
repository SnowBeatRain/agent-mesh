from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.backup_service import list_backup_records

app = typer.Typer(help="备份记录查看命令。")
console = Console()


@app.command("list")
def backup_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    response = list_backup_records(home)
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    backups = response["data"]["backups"]
    if not backups:
        console.print("暂无可回滚 backup 记录。")
        return
    table = Table(title="AgentMesh backups")
    for col in ["backup_id", "history_id", "created_at", "recoverability", "backup_path"]:
        table.add_column(col)
    for item in backups:
        table.add_row(
            str(item["backup_id"]),
            str(item["history_id"]),
            str(item["created_at"]),
            str(item["recoverability"]["status"]),
            str(item["backup_path"]),
        )
    console.print(table)
