from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.cli.confirm import show_plan_and_confirm
from agentmesh.services.rollback_service import (
    RollbackApplyBlocked,
    apply_rollback,
    build_rollback_plan,
)

app = typer.Typer(help="Rollback 计划与执行命令。")
console = Console()


def _emit_rollback_payload(payload: dict, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def _rollback_plan_envelope(plan: dict) -> dict:
    return {
        "schema": "agentmesh.rollback-plan-response/v1",
        "command": "rollback plan",
        "status": plan.get("status", "unknown"),
        "data": {"plan": plan},
        "summary": plan.get("summary", {}),
        "warnings": plan.get("warnings", []),
        "errors": plan.get("errors", []),
        "next_steps": plan.get("next_steps", []),
    }


def _rollback_apply_blocked_envelope(plan: dict) -> dict:
    return {
        "schema": "agentmesh.rollback-apply/v1",
        "command": "rollback apply",
        "status": "blocked",
        "data": {"plan": plan},
        "summary": plan.get("summary", {}),
        "warnings": plan.get("warnings", []),
        "errors": plan.get("errors", []),
        "next_steps": plan.get("next_steps", []),
    }


@app.command("plan")
def rollback_plan(
    backup_ref: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    plan = build_rollback_plan(home, backup_ref)
    output = _rollback_plan_envelope(plan) if json_output else plan
    _emit_rollback_payload(output, json_output)
    if plan["status"] == "error":
        raise typer.Exit(code=1)


@app.command("apply")
def rollback_apply(
    backup_ref: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    confirm: Annotated[bool, typer.Option("--confirm", help="确认执行 rollback 写入。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    # 非 JSON 模式下先展示回滚计划
    if not json_output:
        plan = build_rollback_plan(home, backup_ref)
        summary = plan.get("summary", {})
        files = plan.get("files", [])
        show_plan_and_confirm(
            title="⏪ 回滚计划",
            summary={
                "备份引用": backup_ref,
                "状态": plan.get("status", "unknown"),
                **{k: v for k, v in summary.items()},
            },
            columns=["文件", "操作", "状态"] if files else None,
            rows=[
                [f.get("path", "?"), f.get("action", "?"), f.get("status", "?")]
                for f in files
            ] if files else None,
            extra_lines=plan.get("warnings", []),
            yes=yes,
            dry_run=False,
        )
    try:
        result = apply_rollback(home, backup_ref, confirm=confirm)
    except RollbackApplyBlocked as exc:
        plan = build_rollback_plan(home, backup_ref)
        plan["command"] = "rollback apply"
        plan["mode"] = "APPLY"
        plan["status"] = "blocked"
        plan["errors"] = [str(exc)]
        plan["next_steps"] = ["Resolve hard blocks, pass --confirm, then rerun rollback apply."]
        output = _rollback_apply_blocked_envelope(plan) if json_output else plan
        _emit_rollback_payload(output, json_output)
        raise typer.Exit(code=1) from exc
    _emit_rollback_payload(result, json_output)
