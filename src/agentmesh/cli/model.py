"""CLI: am model scan / diff / list（ModelMesh 探索）。"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentmesh.cli.envelope import build_envelope
from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.model_service import diff_configs, scan_all, sync_model

console = Console()
app = typer.Typer(help="ModelMesh：模型配置互通。")


@app.command("scan")
def model_scan(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """扫描各 Agent 的模型配置。"""
    home = resolve_agentmesh_home(registry)
    configs = scan_all(home)
    if json_output:
        typer.echo(
            json.dumps(
                build_envelope(
                    schema="agentmesh.model-scan/v1",
                    command="model scan",
                    status="ok",
                    data={"configs": [c.to_dict() for c in configs]},
                    next_steps=["Run `am model diff` to compare model configs across agents."],
                ),
                ensure_ascii=False,
            )
        )
        return
    if not configs:
        console.print("[dim]未扫描到任何 Agent 模型配置。[/dim]")
        return
    table = Table(title="Model Scan")
    for col in ("agent", "default_model", "provider", "context_length"):
        table.add_column(col)
    for c in configs:
        table.add_row(
            c.agent,
            c.default_model or "-",
            c.provider or "-",
            str(c.context_length) if c.context_length else "-",
        )
    console.print(table)


@app.command("diff")
def model_diff(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """比较不同 Agent 的模型配置差异。"""
    home = resolve_agentmesh_home(registry)
    diffs = diff_configs(home)
    if json_output:
        typer.echo(
            json.dumps(
                build_envelope(
                    schema="agentmesh.model-diff/v1",
                    command="model diff",
                    status="ok",
                    data={"diffs": [d.to_dict() for d in diffs]},
                    next_steps=["Run `am model scan` to see full model config per agent."],
                ),
                ensure_ascii=False,
            )
        )
        return
    if not diffs:
        console.print("[dim]无差异或不足两个 Agent。[/dim]")
        return
    table = Table(title="Model Diff")
    for col in ("field", "agent_a", "value_a", "agent_b", "value_b"):
        table.add_column(col)
    for d in diffs:
        table.add_row(d.field, d.agent_a, str(d.value_a), d.agent_b, str(d.value_b))
    console.print(table)


@app.command("list")
def model_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """列出各 Agent 的模型配置概览。"""
    home = resolve_agentmesh_home(registry)
    configs = scan_all(home)
    if json_output:
        typer.echo(
            json.dumps(
                build_envelope(
                    schema="agentmesh.model-list/v1",
                    command="model list",
                    status="ok",
                    data={
                        "agents": [c.to_dict() for c in configs],
                        "total": len(configs),
                    },
                ),
                ensure_ascii=False,
            )
        )
        return
    if not configs:
        console.print("[dim]未扫描到任何 Agent 模型配置。[/dim]")
        return
    for c in configs:
        models_str = ", ".join(c.available_models) if c.available_models else c.default_model
        console.print(f"  [bold]{c.agent}[/bold]: {models_str}")


@app.command("sync")
def model_sync(
    to: Annotated[str, typer.Option(help="目标 agent。")] = "",
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="执行真实写入。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
) -> None:
    """同步模型配置到目标 Agent。"""
    if not to:
        raise typer.BadParameter("必须指定 --to")
    home = resolve_agentmesh_home(registry)
    dry_run = not apply

    if apply and not json_output:
        from agentmesh.cli.confirm import show_plan_and_confirm
        preview = sync_model(home, to, dry_run=True)
        show_plan_and_confirm(
            title="🔧 模型配置同步计划",
            summary={
                "目标": to,
                "动作数": len(preview.get("actions", [])),
            },
            columns=["目标路径", "状态"] if preview.get("actions") else None,
            rows=[
                [a.get("target_path", ""), a.get("status", "")]
                for a in preview.get("actions", [])
            ] if preview.get("actions") else None,
            yes=yes,
            dry_run=False,
            prompt=f"确认同步模型配置到 {to}？",
        )

    result = sync_model(home, to, dry_run=dry_run)

    response = build_envelope(
        schema="agentmesh.model-sync/v1",
        command="model sync",
        status="applied" if apply else "planned",
        data={"plan": result},
        next_steps=["Inspect target agent config files."]
        if apply
        else ["Run with --apply to execute this sync plan."],
    )
    response["dry_run"] = dry_run
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
