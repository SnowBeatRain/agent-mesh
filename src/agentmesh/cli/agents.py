from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentmesh.cli.envelope import build_envelope
from agentmesh.config import loader
from agentmesh.services.agent_service import (
    adapter_capabilities_matrix,
    adapter_contract_matrix,
    detect_agents,
)

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="Agent 运行时命令。")


def _agent_info_data() -> list[dict[str, object]]:
    runtime_by_name = {info.name: info for info in detect_agents(loader.user_home())}
    agents = []
    for capability in adapter_capabilities_matrix(loader.user_home()):
        info = runtime_by_name[str(capability["name"])]
        agents.append(
            {
                **capability,
                "installed": info.installed,
                "warnings": list(info.warnings),
            }
        )
    return agents


@app.command("list")
def agents_list(
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    _ = registry
    infos = _agent_info_data()
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.agents-list/v1",
                    command="agents list",
                    status="ok",
                    data={"agents": infos},
                    next_steps=["Run `agentmesh doctor` for registry and runtime diagnostics."],
                ),
                ensure_ascii=False,
            )
        )
        return
    table = Table(title="Agent runtimes")
    for col in ["name", "installed", "mode", "writable", "skill_dir"]:
        table.add_column(col)
    for info in infos:
        table.add_row(
            str(info["name"]),
            str(info["installed"]),
            str(info["mode"]),
            str(info["writable"]),
            str(info["skill_dir"]),
        )
    console.print(table)


@app.command("contract")
def agents_contract(
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    _ = registry
    contracts = adapter_contract_matrix(loader.user_home())
    response = _cli_response(
        schema="agentmesh.agents-contract/v1",
        command="agents contract",
        status="ok",
        data={"contracts": contracts},
        next_steps=[
            "This is a read-only contract declaration; use explicit CLI --apply for writes."
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    table = Table(title="Agent adapter contract v1")
    for col in ["name", "mode", "writable", "classify", "render_plan"]:
        table.add_column(col)
    for item in contracts:
        slots = item["slots"]
        table.add_row(
            str(item["name"]),
            str(item["mode"]),
            str(item["writable"]),
            str(slots["classify"]),
            str(slots["render_plan"]),
        )
    console.print(table)
    console.print("Read-only contract declaration. Use explicit CLI --apply for writes.")
