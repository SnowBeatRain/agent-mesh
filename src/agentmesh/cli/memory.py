"""MemoryMesh CLI：`agentmesh memory scan/import/list/diff`。"""
from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.cli.confirm import show_plan_and_confirm
from agentmesh.cli.envelope import build_envelope
from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.memory_service import (
    MemoryImportConflict,
    diff_memory,
    import_memory,
    list_imported_memories,
    scan_memory_files,
    sync_memory,
)

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="MemoryMesh：跨 Agent 记忆资产互通。")


@app.command("scan")
def memory_scan(
    agent: Annotated[str, typer.Option(help="hermes|openclaw|codex|claude-code|all")] = "all",
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    _ = registry  # scan reads from agent home dirs, not registry
    try:
        assets = scan_memory_files(
            __import__("agentmesh.config.loader", fromlist=["user_home"]).user_home(),
            agent,
        )
    except ValueError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.memory-scan/v1",
                        command="memory scan",
                        status="error",
                        data={"agent": agent},
                        errors=[str(exc)],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc

    data = [
        {
            "agent": a.agent,
            "name": a.name,
            "source_path": str(a.source_path),
            "digest": a.digest,
            "format": a.format,
            "size": a.size,
            "warnings": list(a.warnings),
        }
        for a in assets
    ]
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.memory-scan/v1",
                    command="memory scan",
                    status="ok",
                    data={"memories": data},
                    next_steps=["Run `agentmesh memory import <agent>` to import into registry."],
                ),
                ensure_ascii=False,
            )
        )
        return
    for item in data:
        console.print(
            f"{item['agent']}:{item['name']} [{item['format']}] "
            f"size={item['size']} path={item['source_path']}"
        )


@app.command("import")
def memory_import(
    agent: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="预览导入结果而不实际写入。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    from agentmesh.config.loader import ensure_layout

    ensure_layout(home)
    # 先扫描以获取导入概览
    scanned = list(scan_memory_files(
        __import__("agentmesh.config.loader", fromlist=["user_home"]).user_home(),
        agent,
    ))
    if not scanned:
        console.print("未发现可导入的记忆资产。")
        return
    if not dry_run:
        show_plan_and_confirm(
            title="🧠 记忆资产导入计划",
            summary={
                "来源 Agent": agent,
                "资产数量": len(scanned),
            },
            columns=["名称", "格式", "大小", "路径"] if scanned else None,
            rows=[
                [a.name, a.format, str(a.size), str(a.source_path)]
                for a in scanned
            ] if scanned else None,
            yes=yes,
            dry_run=False,
            prompt=f"确认导入 {len(scanned)} 个记忆资产？",
        )
    count = 0
    try:
        for asset in scanned:
            if dry_run:
                preview = import_memory(home, asset, dry_run=True)
                console.print(
                    f"[DRY-RUN] {preview['agent']}/{preview['name']}: "
                    f"would_write={preview['would_write']} conflict={preview['conflict']}"
                )
            else:
                import_memory(home, asset)
            count += 1
    except MemoryImportConflict as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if dry_run:
        console.print(f"[DRY-RUN] 共 {count} 个记忆资产待导入")
    else:
        console.print(f"已导入 {count} 个记忆资产到 {home / 'memories'}")


@app.command("list")
def memory_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    memories = list_imported_memories(home)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.memory-list/v1",
                    command="memory list",
                    status="ok",
                    data={"memories": memories},
                    next_steps=[],
                ),
                ensure_ascii=False,
            )
        )
        return
    if not memories:
        console.print("暂无已导入的记忆资产。")
        return
    for m in memories:
        console.print(f"{m['agent']}:{m['name']} [{m['format']}] size={m['size']} path={m['path']}")


@app.command("diff")
def memory_diff(
    agent_a: str,
    agent_b: str,
    name: Annotated[str | None, typer.Option("--name", help="比较特定记忆文件名。")] = None,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    result = diff_memory(home, agent_a, agent_b, name)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.memory-diff/v1",
                    command="memory diff",
                    status="ok",
                    data=result,
                    next_steps=[],
                ),
                ensure_ascii=False,
            )
        )
        return
    if name:
        level = result.get("level", 0)
        res = result.get("result", "")
        console.print(f"{agent_a} vs {agent_b} [{name}]: level={level} {res}")
        console.print(f"  {result.get('detail', '')}")
    else:
        summary = result.get("summary", {})
        console.print(f"{agent_a} vs {agent_b}:")
        console.print(f"  only_in_{agent_a}: {result.get('only_in_a', [])}")
        console.print(f"  only_in_{agent_b}: {result.get('only_in_b', [])}")
        console.print(f"  different: {result.get('different', [])}")
        console.print(f"  identical: {result.get('identical', [])}")
        console.print(f"  summary: {summary}")


@app.command("sync")
def memory_sync(
    to: Annotated[str, typer.Option(help="目标 agent。")] = "",
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="执行真实写入。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
) -> None:
    """将 registry 中已导入的记忆同步到目标 Agent。"""
    if not to:
        raise typer.BadParameter("必须指定 --to")
    home = resolve_agentmesh_home(registry)
    dry_run = not apply

    if apply and not json_output:
        # 先展示计划再确认
        preview = sync_memory(home, to, dry_run=True)
        show_plan_and_confirm(
            title="🧠 记忆同步计划",
            summary={
                "目标": to,
                "动作数": len(preview.get("actions", [])),
            },
            columns=["名称", "目标路径", "状态"] if preview.get("actions") else None,
            rows=[
                [a.get("name", ""), a.get("target_path", ""), a.get("status", "")]
                for a in preview.get("actions", [])
            ] if preview.get("actions") else None,
            yes=yes,
            dry_run=False,
            prompt=f"确认同步记忆到 {to}？",
        )

    result = sync_memory(home, to, dry_run=dry_run)

    response = _cli_response(
        schema="agentmesh.memory-sync/v1",
        command="memory sync",
        status="applied" if apply else "planned",
        data={"plan": result},
        next_steps=["Inspect target agent memory files."]
        if apply
        else ["Run with --apply to execute this sync plan."],
    )
    response["dry_run"] = dry_run
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(json.dumps(result, ensure_ascii=False, indent=2))
