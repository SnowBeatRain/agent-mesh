from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.cli.envelope import build_envelope
from agentmesh.config import loader
from agentmesh.config.loader import resolve_agentmesh_home
from agentmesh.services.prompt_service import (
    PromptError,
    add_prompt,
    disable_prompt_target,
    enable_prompt,
    enable_prompt_multi,
    import_live_prompt,
    list_prompt_versions,
    list_prompts,
    prompt_target_status,
    update_prompt,
)

app = typer.Typer(help="PromptMesh 命令。")
console = Console()
_cli_response = build_envelope


def _prompt_error_response(command: str, error: Exception, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.prompts/v1",
                    command=command,
                    status="error",
                    data={},
                    errors=[str(error)],
                ),
                ensure_ascii=False,
            )
        )
    else:
        console.print(str(error))


@app.command("add")
def prompts_add(
    prompt_id: str,
    name: Annotated[str, typer.Option("--name", help="Prompt 显示名称。")],
    content_file: Annotated[Path, typer.Option("--from", help="Prompt 内容文件。")],
    description: Annotated[str, typer.Option("--description", help="Prompt 描述。")] = "",
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        content = content_file.read_text(encoding="utf-8")
        result = add_prompt(home, prompt_id, name, content, description)
    except (OSError, PromptError, ValueError) as exc:
        _prompt_error_response("prompts add", exc, json_output)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False))
    else:
        console.print(f"已添加 prompt：{result['id']}")


@app.command("list")
def prompts_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    prompts = list_prompts(home)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.prompts-list/v1",
                    command="prompts list",
                    status="ok",
                    data={"prompts": prompts},
                ),
                ensure_ascii=False,
            )
        )
        return
    for prompt in prompts:
        console.print(f"{prompt['id']}: {prompt['name']}")


@app.command("import-live")
def prompts_import_live(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        result = import_live_prompt(home, target, home=loader.user_home())
    except PromptError as exc:
        _prompt_error_response("prompts import-live", exc, json_output)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False))
    else:
        console.print(f"已导入 live prompt：{result['id']}")


@app.command("status")
def prompts_status(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        result = prompt_target_status(home, target, home=loader.user_home())
    except PromptError as exc:
        _prompt_error_response("prompts status", exc, json_output)
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.prompts-status/v1",
        command="prompts status",
        status="ok",
        data={"status": result},
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"Prompt target: {result['target']}")
        console.print(f"Live path: {result['live_path']}")
        console.print(f"Enabled: {'yes' if result['enabled'] else 'no'}")
        console.print(f"Managed: {'yes' if result['managed'] else 'no'}")
        console.print(f"Drift: {'yes' if result['drift'] else 'no'}")


@app.command("disable")
def prompts_disable(
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只生成计划，不写入。")] = False,
    apply: Annotated[
        bool, typer.Option("--apply", help="禁用 target prompt state；不删除 live 文件。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if not apply:
        dry_run = True
    home = resolve_agentmesh_home(registry)
    try:
        result = disable_prompt_target(home, target, apply=apply, home=loader.user_home())
    except PromptError as exc:
        _prompt_error_response("prompts disable", exc, json_output)
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.prompts-disable/v1",
        command="prompts disable",
        status="applied" if apply else "planned",
        data={"plan": result},
        next_steps=[]
        if apply
        else ["Run with --apply to disable prompt target state without deleting live content."],
    )
    response["dry_run"] = dry_run
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("enable")
def prompts_enable(
    prompt_id: str,
    target: Annotated[str, typer.Option("--target", help="目标 runtime。")] = "",
    targets: Annotated[str, typer.Option("--targets", help="逗号分隔的多个目标 runtime。")] = "",
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只生成计划，不写入。")] = False,
    apply: Annotated[bool, typer.Option("--apply", help="写入目标 live prompt 文件。")] = False,
    conflict_strategy: Annotated[
        str, typer.Option("--conflict-strategy", help="冲突策略：backup/skip/force。")
    ] = "backup",
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if not target and not targets:
        raise typer.BadParameter("至少指定 --target 或 --targets")
    home = resolve_agentmesh_home(registry)
    try:
        if targets:
            target_list = [t.strip() for t in targets.split(",") if t.strip()]
            plans = enable_prompt_multi(
                home,
                prompt_id,
                target_list,
                apply=apply,
                home=loader.user_home(),
                conflict_strategy=conflict_strategy,
            )
            response = _cli_response(
                schema="agentmesh.prompts-enable/v1",
                command="prompts enable",
                status="applied" if apply else "planned",
                data={"plans": plans},
            )
            response["dry_run"] = not apply
        else:
            result = enable_prompt(
                home,
                prompt_id,
                target,
                apply=apply,
                home=loader.user_home(),
                conflict_strategy=conflict_strategy,
            )
            response = _cli_response(
                schema="agentmesh.prompts-enable/v1",
                command="prompts enable",
                status="applied" if apply else "planned",
                data={"plan": result},
            )
            response["dry_run"] = not apply
    except PromptError as exc:
        _prompt_error_response("prompts enable", exc, json_output)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        typer.echo(json.dumps(response["data"], ensure_ascii=False, indent=2))


@app.command("update")
def prompts_update(
    prompt_id: str,
    content_file: Annotated[Path, typer.Option("--content-file", help="新内容文件。")],
    name: Annotated[str, typer.Option("--name", help="新显示名称。")] = "",
    description: Annotated[str, typer.Option("--description", help="新描述。")] = "",
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        content = content_file.read_text(encoding="utf-8")
        result = update_prompt(
            home,
            prompt_id,
            content=content,
            name=name or None,
            description=description or None,
        )
    except (OSError, PromptError, ValueError) as exc:
        _prompt_error_response("prompts update", exc, json_output)
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.prompts-update/v1",
        command="prompts update",
        status="ok",
        data=result,
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"已更新 prompt {result['id']} 到版本 {result['version']}")


@app.command("versions")
def prompts_versions(
    prompt_id: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        versions = list_prompt_versions(home, prompt_id)
    except PromptError as exc:
        _prompt_error_response("prompts versions", exc, json_output)
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.prompts-versions/v1",
        command="prompts versions",
        status="ok",
        data={"prompt_id": prompt_id, "versions": versions},
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        for v in versions:
            console.print(
                f"v{v['version']}: {v.get('content_hash', '')[:12]}  {v.get('created_at', '')}"
            )
