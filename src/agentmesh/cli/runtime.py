from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.cli.envelope import build_envelope
from agentmesh.cli.confirm import show_plan_and_confirm
from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.runtime_service import (
    RuntimeBootstrapBlocked,
    RuntimeLoadPlanError,
    apply_bootstrap,
    bootstrap_status,
    build_bootstrap_plan,
    build_runtime_env,
    build_runtime_response,
    check_stale,
    disable_bootstrap,
    load_runtime_exec_plan,
    persist_runtime_load_plan,
    validate_runtime,
)

app = typer.Typer(help="Runtime 直接加载与验证命令。")
console = Console()

_cli_response = build_envelope


@app.command("load-plan")
def runtime_load_plan(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    result = persist_runtime_load_plan(home, target)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.runtime-load-plan-response/v1",
                    command="runtime load-plan",
                    status="ok",
                    data={"plan": result},
                    next_steps=[
                        "This is Runtime Auto-Load alpha groundwork; "
                        "target agents do not natively consume it yet."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("exec-plan")
def runtime_exec_plan(
    load_plan: Annotated[Path, typer.Option("--load-plan", help="LoadPlan JSON 路径。")],
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    try:
        result = load_runtime_exec_plan(load_plan)
    except (RuntimeLoadPlanError, OSError, json.JSONDecodeError) as exc:
        response = build_runtime_response(
            "agentmesh.runtime-exec-plan/v1",
            "runtime exec-plan",
            "error",
            {"load_plan": str(load_plan)},
            errors=[str(exc)],
            next_steps=["Provide a valid agentmesh.runtime-load-plan/v1 JSON file."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(json.dumps(response, ensure_ascii=False, indent=2))
        raise typer.Exit(code=1) from exc
    response = build_runtime_response(
        "agentmesh.runtime-exec-plan/v1",
        "runtime exec-plan",
        "planned",
        result,
        next_steps=[
            (
                f"This is a dry-run LoadPlan reader entrypoint for "
                f"target '{result.get('target', 'unknown')}'; "
                "native runtime execution is still experimental."
            ),
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    console.print(json.dumps(response, ensure_ascii=False, indent=2))


@app.command("env")
def runtime_env(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    home = resolve_agentmesh_home(registry)
    typer.echo(build_runtime_env(home, target))


@app.command("validate")
def runtime_validate(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    result = validate_runtime(home, target)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False))
    else:
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("bootstrap")
def runtime_bootstrap(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只生成计划，不写入。")] = False,
    apply: Annotated[bool, typer.Option("--apply", help="写入 bootstrap shim。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if not apply:
        dry_run = True
    home = resolve_agentmesh_home(registry)
    # apply 模式下先展示计划供确认
    if apply and not json_output:
        plan = build_bootstrap_plan(home, target)
        show_plan_and_confirm(
            title="🚀 Runtime Bootstrap 计划",
            summary={
                "目标": target,
                "Loader 路径": plan.get("loader_path", "N/A"),
                "Registry": plan.get("registry", "N/A"),
                "允许加载": plan.get("summary", {}).get("allowed", 0),
                "阻止的 Skill": plan.get("summary", {}).get("blocked", 0),
            },
            extra_lines=["写入文件: " + str(plan.get("loader_path", ""))],
            yes=yes,
            dry_run=False,
        )
    try:
        result = apply_bootstrap(home, target) if apply else build_bootstrap_plan(home, target)
    except RuntimeBootstrapBlocked as exc:
        response = build_runtime_response(
            "agentmesh.runtime-bootstrap/v1",
            "runtime bootstrap",
            "blocked",
            {"target": target},
            dry_run=False,
            errors=[str(exc)],
            next_steps=["Move or review the existing loader directory, then rerun with --dry-run."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(f"Bootstrap 被阻止：{exc}")
            console.print(
                "Next: move or review the existing loader directory, then rerun with --dry-run."
            )
        raise typer.Exit(code=1) from exc
    response = build_runtime_response(
        "agentmesh.runtime-bootstrap/v1",
        "runtime bootstrap",
        "applied" if apply else "planned",
        result,
        dry_run=not apply,
        next_steps=[
            f"Run `agentmesh runtime status --target {target}` to inspect it."
            if apply
            else "Run with --apply to enable the bootstrap shim."
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    if apply:
        console.print(f"Bootstrap shim enabled for {target}")
        console.print(f"Loader: {result['loader_path']}")
        console.print(f"Registry: {result['registry']}")
        console.print(f"Next: agentmesh runtime status --target {target}")
    else:
        console.print(f"Bootstrap plan for {target}")
        console.print(f"Will create: {result['loader_path']}")
        console.print(f"Will reference: {result['registry']}")
        console.print(f"Will load: {result['summary']['allowed']} allowed skills")
        console.print(f"Blocked: {result['summary']['blocked']} risky skills require review")
        console.print("No files were changed. Run with --apply to enable.")


@app.command("status")
def runtime_status(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    result, status_warnings = bootstrap_status(home, target)
    response = build_runtime_response(
        "agentmesh.runtime-status/v1",
        "runtime status",
        "installed" if result["installed"] else "not-installed",
        result,
        warnings=status_warnings,
        next_steps=[]
        if result["installed"]
        else [f"Run `agentmesh runtime bootstrap --target {target} --dry-run` to preview setup."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    console.print(f"Runtime bootstrap status for {target}")
    console.print(f"Installed: {result['installed']}")
    console.print(f"Managed by AgentMesh: {result['managed']}")
    console.print(f"Loader: {result['loader_path']}")
    if result.get("plan_stale"):
        console.print("[yellow]⚠ LoadPlan is stale — registry has changed since last plan[/yellow]")
        console.print(f"  Run [bold]agentmesh runtime update --target {target}[/bold] to refresh")


@app.command("disable")
def runtime_disable(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只生成计划，不写入。")] = False,
    apply: Annotated[bool, typer.Option("--apply", help="禁用 bootstrap shim。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if not apply:
        dry_run = True
    home = resolve_agentmesh_home(registry)
    try:
        result = disable_bootstrap(home, target, apply=apply)
    except RuntimeBootstrapBlocked as exc:
        response = build_runtime_response(
            "agentmesh.runtime-disable/v1",
            "runtime disable",
            "blocked",
            {"target": target},
            dry_run=False,
            errors=[str(exc)],
            next_steps=["Only AgentMesh-managed bootstrap shims can be disabled automatically."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(f"Bootstrap 禁用被阻止：{exc}")
            console.print("Next: review the existing loader directory manually.")
        raise typer.Exit(code=1) from exc
    response = build_runtime_response(
        "agentmesh.runtime-disable/v1",
        "runtime disable",
        "disabled" if apply and result["managed"] else "planned",
        result,
        dry_run=not apply,
        next_steps=[] if apply else ["Run with --apply to disable the bootstrap shim."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    if apply:
        console.print(f"Bootstrap shim disabled for {target}")
        if result.get("backup"):
            console.print(f"Backup: {result['backup']}")
    else:
        console.print(f"Disable plan for {target}")
        console.print(f"Loader: {result['loader_path']}")
        console.print("No files were changed. Run with --apply to disable.")


@app.command("update")
def runtime_update(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="执行更新。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """重新生成 LoadPlan 并重新渲染 skills 到目标 runtime 原生格式。"""
    from agentmesh.services.runtime_service import apply_bootstrap

    home = resolve_agentmesh_home(registry)
    if not apply:
        response = build_runtime_response(
            "agentmesh.runtime-update/v1",
            "runtime update",
            "planned",
            {"target": target},
            dry_run=True,
            next_steps=["Run with --apply to regenerate and re-render the LoadPlan."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
            return
        console.print(f"Runtime update plan for {target}")
        console.print("No files were changed. Run with --apply to regenerate.")
        return

    result = apply_bootstrap(home, target)
    response = build_runtime_response(
        "agentmesh.runtime-update/v1",
        "runtime update",
        "updated",
        result,
        next_steps=[f"Run `agentmesh runtime status --target {target}` to verify."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    console.print(f"Runtime updated for {target}")
    console.print(f"Rendered skills: {result.get('rendered_skills', 0)}")
    console.print(f"LoadPlan: {result.get('load_plan_path', 'N/A')}")


@app.command("check-stale")
def runtime_check_stale(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """轻量级 LoadPlan 过期检测，供 auto-load hook 脚本调用。"""
    home = resolve_agentmesh_home(registry)
    result = check_stale(home, target)
    response = build_runtime_response(
        "agentmesh.runtime-check-stale/v1",
        "runtime check-stale",
        "stale" if result["stale"] else "fresh",
        result,
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    if result["stale"]:
        console.print(f"[yellow]⚠ LoadPlan is stale for {target}[/yellow]")
        if result["skills_added"]:
            console.print(f"  Added: {', '.join(result['skills_added'])}")
        if result["skills_removed"]:
            console.print(f"  Removed: {', '.join(result['skills_removed'])}")
        if result["content_changed"]:
            console.print(f"  Modified: {', '.join(result['content_changed'])}")
        console.print(
            f"  Run [bold]agentmesh runtime update --target {target} --apply[/bold]"
            " to refresh."
        )
    else:
        console.print(f"[green]✓ LoadPlan is fresh for {target}[/green]")
