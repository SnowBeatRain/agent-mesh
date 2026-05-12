from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.cli.confirm import show_plan_and_confirm
from agentmesh.cli.diff_renderer import render_diff
from agentmesh.cli.envelope import build_envelope
from agentmesh.cli.progress import progress_bar, spinner
from agentmesh.config import loader
from agentmesh.config.loader import (
    ensure_layout,
    registry_skills_root,
    resolve_agentmesh_home,
)
from agentmesh.engine.diff_engine import diff_skill
from agentmesh.exporters.claude_code import export_claude_code_package
from agentmesh.services.agent_service import scan_skills
from agentmesh.services.package_service import (
    PackageError,
    export_agentmesh_package,
    import_agentmesh_package,
)
from agentmesh.services.registry_service import (
    RegistryImportConflict,
    RegistrySkillExists,
    RegistrySkillNotFound,
    delete_registry_skill,
    describe_registry_skill,
    find_duplicate_candidates,
    import_skill,
    list_registry_skills,
    list_registry_skills_detailed,
    purge_target_skill_copies,
    reindex_registry_skills,
    rename_registry_skill,
)
from agentmesh.services.skill_state_service import (
    SkillStateError,
    enabled_sync_pairs,
    get_skill_status,
    remove_skill_state,
    rename_skill_state,
    set_skill_targets,
)
from agentmesh.services.sync_service import (
    SyncBlocked,
    UnsupportedSyncMode,
    UnsupportedSyncTarget,
    sync,
)
from agentmesh.services.update_check_service import build_update_check
from agentmesh.validation.native import validate_native_runtime
from agentmesh.validation.skills import validate_registry_skills

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="SkillMesh 命令。")


# ---------------------------------------------------------------------------
# Phase 1 deprecation helper
# ---------------------------------------------------------------------------
# Several CLI surface changes are landing behind an alias-with-warning policy
# so existing scripts keep working for one more minor release:
#
#   - `skills enable` / `skills disable` / `skills status` → `skills target`
#   - `skills import-package <zip>` → `skills import --from package:<zip>`
#   - `skills import <agent>` (positional) → `skills import --from agent:<name>`
#   - `skills sync --dry-run` / `skills import-package --dry-run` → default,
#     the flag now emits a deprecation note because it is redundant with
#     "no --apply means dry-run".
#
# Each legacy entry point prints exactly one DeprecationWarning-style line
# to stderr via ``_emit_deprecation`` so it shows up alongside normal output
# without polluting JSON envelopes (stderr is not captured by the envelope).
_DEPRECATION_PREFIX = "[DEPRECATED] "


def _deprecation_message(old: str, new: str, *, extra: str | None = None) -> str:
    suffix = f" {extra}" if extra else ""
    return (
        f"{_DEPRECATION_PREFIX}`{old}` will be removed in 0.3.0; "
        f"use `{new}` instead.{suffix}"
    )


def _emit_deprecation(old: str, new: str, *, json_output: bool, extra: str | None = None) -> None:
    """Write a single-line DeprecationWarning to stderr.

    Suppressed in ``--json`` mode because scripted clients consume stdout as a
    pure JSON envelope; the warning propagates through envelope ``warnings``
    there instead (callers are responsible for injecting it).

    In interactive/text mode we use ``typer.echo(err=True)`` (not a raw
    ``print``) so the output is routed through Click's error stream. This
    plays nicely with ``CliRunner(mix_stderr=False)`` in tests and with
    tools that redirect ``2>`` in real shells.
    """
    if json_output:
        return
    typer.echo(_deprecation_message(old, new, extra=extra), err=True)


def _emit_dry_run_deprecation(command: str, *, json_output: bool) -> None:
    _emit_deprecation(
        f"{command} --dry-run",
        command,
        json_output=json_output,
        extra=(
            "dry-run is already the default; pass --apply to execute. "
            "The --dry-run flag will be removed in 0.3.0."
        ),
    )


@app.command("scan")
def skills_scan(
    agent: Annotated[str, typer.Option(help="hermes|openclaw|codex|claude-code|all")] = "all",
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
) -> None:
    _ = registry  # scan reads from agent home dirs, not registry
    user_home = loader.user_home()
    if agent == "all":
        from agentmesh.services.agent_service import ADAPTERS

        agent_names = list(ADAPTERS)
        all_skills = []
        with progress_bar("扫描 Agent skills", len(agent_names)) as advance:
            for name in agent_names:
                all_skills.extend(scan_skills(user_home, name))
                advance()
        skills = all_skills
    else:
        with spinner(f"扫描 {agent} skills"):
            skills = scan_skills(user_home, agent)
    data = [
        {
            "name": s.name,
            "description": s.description,
            "agent": s.agent,
            "source_path": str(s.source_path),
            "hash": s.digest,
            "warnings": list(s.warnings),
        }
        for s in skills
    ]
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-scan/v1",
                    command="skills scan",
                    status="ok",
                    data={"skills": data},
                    next_steps=["Run `agentmesh skills import --from agent:<agent>` to import."],
                ),
                ensure_ascii=False,
            )
        )
        return
    for item in data:
        suffix = ""
        if item["warnings"]:
            suffix = f" warnings={len(item['warnings'])}"
        console.print(f"{item['agent']}:{item['name']} {item['source_path']}{suffix}")


# ---------------------------------------------------------------------------
# Import — unified `--from <source:value>` with legacy aliases
# ---------------------------------------------------------------------------
# `skills import --from agent:hermes`   — scan and import from a runtime
# `skills import --from package:a.zip`  — load an AgentMesh ZIP package
# Legacy forms still work but print a deprecation note:
#   * `skills import hermes` (positional agent)
#   * `skills import-package <zip>` (separate command)


def _import_from_agent(
    home: Path,
    agent: str,
    *,
    dry_run: bool,
) -> None:
    from agentmesh.services.agent_service import ADAPTERS, get_adapters

    if agent != "all" and agent not in ADAPTERS:
        console.print(
            f"暂不支持 agent：{agent}；支持列表：{', '.join(sorted(ADAPTERS))}"
        )
        raise typer.Exit(code=1)
    ensure_layout(home)
    skill_dir = None
    skill_dir_exists = True
    if agent != "all":
        adapter = get_adapters(loader.user_home(), agent)[0]
        skill_dir = getattr(adapter, "skill_dir", None)
        skill_dir_exists = bool(skill_dir and Path(skill_dir).exists())
    count = 0
    try:
        for skill in scan_skills(loader.user_home(), agent):
            if dry_run:
                preview = import_skill(home, skill, dry_run=True)
                console.print(
                    f"[DRY-RUN] {preview['skill']}: "
                    f"would_write={preview['would_write']} conflict={preview['conflict']}"
                )
            else:
                import_skill(home, skill)
            count += 1
    except RegistryImportConflict as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if count == 0 and not skill_dir_exists and skill_dir is not None:
        console.print(
            f"{agent} 未检测到 skill 目录：{skill_dir}（该 agent 可能未安装，"
            "或未在该目录下创建 skill）。"
        )
    if dry_run:
        console.print(f"[DRY-RUN] 共 {count} 个 skill 待导入到 {registry_skills_root(home)}")
    else:
        console.print(f"已导入 {count} 个 skill 到 {registry_skills_root(home)}")


def _import_from_package(
    home: Path,
    package: Path,
    *,
    apply: bool,
    json_output: bool,
    schema: str = "agentmesh.skills-import/v1",
    command_label: str = "skills import",
) -> None:
    ensure_layout(home)
    try:
        plan = import_agentmesh_package(home, package, apply=apply)
    except PackageError as exc:
        response = _cli_response(
            schema=schema,
            command=command_label,
            status="blocked" if apply else "error",
            data={"package": str(package)},
            errors=[str(exc)],
            next_steps=[
                "Run `agentmesh skills import --from package:<zip>` "
                "(without --apply) to inspect the package first."
            ],
        )
        response["dry_run"] = not apply
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    status = "applied" if apply else ("planned" if plan["allowed"] else "blocked")
    response = _cli_response(
        schema=schema,
        command=command_label,
        status=status,
        data={"plan": plan, "source": {"type": "package", "path": str(package)}},
        warnings=[] if plan["allowed"] else ["Package import is blocked by audit or conflicts."],
        next_steps=["Run with --apply to import this package."]
        if not apply and plan["allowed"]
        else [],
    )
    response["dry_run"] = not apply
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        typer.echo(json.dumps(plan, ensure_ascii=False, indent=2))


def _parse_from_spec(spec: str) -> tuple[str, str]:
    """Parse the ``--from <type>:<value>`` argument into (type, value).

    Supported types: ``agent``, ``package``. Raises ``typer.BadParameter``
    for anything else so the error message lists what is allowed.
    """
    if ":" not in spec:
        raise typer.BadParameter(
            "--from 必须是 agent:<name> 或 package:<path>"
        )
    kind, _, value = spec.partition(":")
    kind = kind.strip().lower()
    value = value.strip()
    if kind not in {"agent", "package"}:
        raise typer.BadParameter(
            f"--from 不支持的来源类型：{kind!r}；支持：agent, package"
        )
    if not value:
        raise typer.BadParameter(f"--from {kind}: 缺少值（例如 --from {kind}:<x>）")
    return kind, value


@app.command("import")
def skills_import(
    agent: Annotated[
        str | None,
        typer.Argument(
            help=(
                "[DEPRECATED] 位置参数形式 `skills import <agent>`；"
                "请改用 `--from agent:<name>`。"
            ),
        ),
    ] = None,
    agent_option: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="[DEPRECATED] Use `--from agent:<name>` instead.",
        ),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option(
            "--from",
            help=(
                "统一来源语法：`agent:<name>` 扫描并导入某 agent；"
                "`package:<path>` 从 AgentMesh ZIP 加载。"
            ),
        ),
    ] = None,
    registry: Annotated[
        str | None, typer.Option(help="AgentMesh home/registry 根目录。")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="[DEPRECATED] 默认就是 dry-run。")
    ] = False,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="实际写入 registry。包 import 场景下必填，agent import 场景下视为写入。",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """Import skills into the registry.

    Use ``--from agent:<name>`` or ``--from package:<path>``. Legacy forms
    (``skills import <agent>`` positional, ``skills import-package <zip>``)
    still work but emit a deprecation note.
    """
    if agent is not None and agent_option is not None:
        raise typer.BadParameter("pass either legacy <agent> or --agent, not both")
    if dry_run and apply:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if dry_run:
        _emit_dry_run_deprecation("skills import", json_output=json_output)
    home = resolve_agentmesh_home(registry)
    legacy_agent = agent_option or agent
    if source is None and legacy_agent is None:
        raise typer.BadParameter(
            "必须指定 --from agent:<name> 或 --from package:<path>；"
            "旧语法 `skills import <agent>` 仍可用但已弃用。"
        )
    if source is not None:
        if legacy_agent is not None:
            raise typer.BadParameter(
                "同时传入了位置参数 <agent> 和 --from；请只使用其中一个。"
            )
        kind, value = _parse_from_spec(source)
        if kind == "agent":
            _import_from_agent(home, value, dry_run=not apply)
        else:
            _import_from_package(home, Path(value), apply=apply, json_output=json_output)
        return
    # Legacy: positional agent name. Kept behaviorally identical to the old
    # command — default is "write, not dry-run" — so existing scripts do not
    # flip semantics when the deprecation period begins.
    _emit_deprecation(
        "skills import --agent <agent>" if agent_option is not None else "skills import <agent>",
        "skills import --from agent:<agent>",
        json_output=json_output,
    )
    _import_from_agent(home, legacy_agent, dry_run=dry_run)


@app.command("import-package")
def skills_import_package(
    package: Path,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="[DEPRECATED] 默认就是 dry-run。")
    ] = False,
    apply: Annotated[bool, typer.Option("--apply", help="导入 package 到 registry。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """[DEPRECATED] Use `skills import --from package:<zip>` instead.

    Kept as an alias for one minor release so existing scripts keep working.
    """
    _emit_deprecation(
        "skills import-package <zip>",
        "skills import --from package:<zip>",
        json_output=json_output,
    )
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if dry_run:
        _emit_dry_run_deprecation("skills import", json_output=json_output)
    home = resolve_agentmesh_home(registry)
    # Preserve the legacy envelope schema so existing JSON consumers keep
    # seeing `agentmesh.skills-import-package/v1` until the command is
    # removed in 0.3.0.
    _import_from_package(
        home,
        package,
        apply=apply,
        json_output=json_output,
        schema="agentmesh.skills-import-package/v1",
        command_label="skills import-package",
    )


def _collect_skill_conflicts(home: Path, target: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for path in list_registry_skills(home):
        result = diff_skill(home, path.name, target)
        if int(result.level) == 0:
            continue
        items.append(
            {
                "skill": path.name,
                "target": target,
                "level": int(result.level),
                "name": result.name,
                "summary": result.summary,
                "changes": result.changes or [],
            }
        )
    return items


def _print_skill_conflicts(
    home: Path,
    target: str,
    json_output: bool,
    *,
    schema: str,
    command: str,
    extra_data: dict[str, object] | None = None,
) -> None:
    """Render target-vs-registry conflict findings as text or envelope JSON.

    ``extra_data`` lets callers merge command-specific keys into the envelope
    ``data`` payload — ``skills list --conflicts`` uses this to keep
    ``skills``/``duplicates`` stubs alongside ``conflicts``.
    """
    try:
        items = _collect_skill_conflicts(home, target)
    except ValueError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema=schema,
                        command=command,
                        status="error",
                        data={"target": target},
                        errors=[str(exc)],
                        next_steps=["Use `agentmesh agents list` to inspect supported targets."],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if json_output:
        data: dict[str, object] = {"target": target, "conflicts": items}
        if extra_data:
            data = {**extra_data, **data}
        typer.echo(
            json.dumps(
                _cli_response(
                    schema=schema,
                    command=command,
                    status="ok",
                    data=data,
                    next_steps=[
                        "Run `agentmesh skills diff <name>` for a focused conflict summary."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    for item in items:
        console.print(
            f"{item['skill']} -> {item['target']}: level {item['level']} "
            f"{item['name']}: {item['summary']}"
        )


@app.command("list")
def skills_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    duplicates: Annotated[bool, typer.Option("--duplicates", help="显示疑似重复 skill。")] = False,
    conflicts: Annotated[
        bool, typer.Option("--conflicts", help="输出 registry 与目标 runtime 的冲突列表。")
    ] = False,
    target: Annotated[str, typer.Option("--target", help="冲突检查目标 agent。")] = "hermes",
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    detailed: Annotated[
        bool,
        typer.Option(
            "--detailed",
            help=(
                "返回每个 skill 的完整详情（file_count / total_bytes / enabled_targets / "
                "risk_summary / source_agent / imported_at / last_diff）。"
                "配合 --json 使用最佳；不加 --json 时以表格输出核心列。"
            ),
        ),
    ] = False,
    diff_targets: Annotated[
        str | None,
        typer.Option(
            "--diff-targets",
            help=(
                "逗号分隔的目标 agent 列表，配合 --detailed 同时返回每个 skill 对各目标的 "
                "last_diff 等级名称。省略时 last_diff 为 {}。"
            ),
        ),
    ] = None,
) -> None:
    home = resolve_agentmesh_home(registry)
    if duplicates:
        groups = find_duplicate_candidates(home)
        for description, names in groups.items():
            console.print(f"{description}: {', '.join(names)}")
        return
    if conflicts:
        _print_skill_conflicts(
            home,
            target,
            json_output,
            schema="agentmesh.skills-list/v1",
            command="skills list",
            extra_data={"skills": [], "duplicates": {}},
        )
        return
    # 详细列表分支：返回每个 skill 的丰富元数据，便于工作台/自动化消费。
    if detailed:
        targets_list: list[str] | None = None
        if diff_targets:
            targets_list = [t.strip() for t in diff_targets.split(",") if t.strip()]
        items = list_registry_skills_detailed(home, with_diff_targets=targets_list)
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-list/v1",
                        command="skills list",
                        status="ok",
                        data={
                            "skills": items,
                            "duplicates": {},
                            "conflicts": [],
                            "detailed": True,
                            "diff_targets": targets_list or [],
                        },
                        next_steps=[
                            "Use `agentmesh skills show <name>` for a full manifest dump, "
                            "or `agentmesh skills diff <name> --target <agent>` for a "
                            "focused conflict summary."
                        ],
                    ),
                    ensure_ascii=False,
                )
            )
            return
        for item in items:
            skill = item["skill"]
            risk = item["risk_summary"]
            enabled = ",".join(item["enabled_targets"]) or "-"
            console.print(
                f"{skill['name']} "
                f"files={skill['file_count']} "
                f"bytes={skill['total_bytes']} "
                f"source={skill.get('source_agent') or '-'} "
                f"enabled={enabled} "
                f"findings={risk['findings']}"
            )
        return
    skills = [path.name for path in list_registry_skills(home)]
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-list/v1",
                    command="skills list",
                    status="ok",
                    data={"skills": skills, "duplicates": {}, "conflicts": []},
                    next_steps=[
                        "Run with `--duplicates` or `--conflicts --target <agent>` for diagnostics."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    for name in skills:
        console.print(name)


@app.command("reindex")
def skills_reindex(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    index = reindex_registry_skills(home)
    index_path = home / "registry" / "index" / "skills.json"
    response = _cli_response(
        schema="agentmesh.skills-reindex/v1",
        command="skills reindex",
        status="ok",
        data={"index": index, "index_path": str(index_path)},
        summary=index["summary"],
        next_steps=["Use `agentmesh skills list --json` or inspect the generated index file."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    console.print(f"已重建 registry skill index：{index_path}")
    console.print(f"skills: {index['summary']['skills']}")


@app.command("show")
def skills_show(
    name: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        detail = describe_registry_skill(home, name)
    except FileNotFoundError as exc:
        response = _cli_response(
            schema="agentmesh.skills-show/v1",
            command="skills show",
            status="error",
            data={"skill": name},
            errors=[str(exc)],
            next_steps=["Run `agentmesh skills list` to see available registry skills."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.skills-show/v1",
        command="skills show",
        status="ok",
        data=detail,
        summary={
            "files": detail["skill"]["files"]["total"],
            "findings": detail["risk_summary"]["findings"],
        },
        next_steps=["Run `agentmesh skills diff <name> --target <agent>` to compare projections."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    skill = detail["skill"]
    console.print(f"Skill: {skill['name']}")
    console.print(f"Description: {skill['description']}")
    console.print(f"Path: {skill['path']}")
    console.print(f"Files: {skill['files']['total']}")
    console.print(f"Risk findings: {detail['risk_summary']['findings']}")


@app.command("update-check")
def skills_update_check(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    report = build_update_check(home)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.update-check/v1",
                    command="skills update-check",
                    status="ok",
                    data=report,
                    next_steps=[
                        "No network requests were made; future update apply remains out of scope."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    summary = report["summary"]
    console.print(
        f"Update check: {summary['candidate']} candidate, {summary['unknown']} unknown, "
        f"{summary['skipped']} skipped (network disabled)"
    )
    for item in report["skills"]:
        console.print(f"{item['name']}: {item['status']} ({item['reason']})")


@app.command("diff")
def skills_diff(
    name: str,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="目标 agent（必填）。使用 `agentmesh agents list` 查看支持的 agent。",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="禁用彩色输出。")] = False,
) -> None:
    # --target 由默认 "hermes" 改为必填：新用户常常并未安装 hermes，
    # 默认值会导致 diff 永远返回 "STRUCTURE_CHANGED: 目标 skill 不存在"。
    if not target:
        message = "必须显式指定 --target <agent>；使用 `agentmesh agents list` 查看支持的 agent。"
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-diff/v1",
                        command="skills diff",
                        status="error",
                        data={"skill": name, "target": None},
                        errors=[message],
                        next_steps=["Run `agentmesh agents list` to pick a target."],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(message)
        raise typer.Exit(code=2)
    home = resolve_agentmesh_home(registry)
    try:
        result = diff_skill(home, name, target)
    except ValueError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-diff/v1",
                        command="skills diff",
                        status="error",
                        data={"skill": name, "target": target},
                        errors=[str(exc)],
                        next_steps=["Use `agentmesh agents list` to inspect supported targets."],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    data = {
        "skill": name,
        "target": target,
        "level": int(result.level),
        "name": result.name,
        "summary": result.summary,
        "changes": result.changes or [],
    }
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-diff/v1",
                    command="skills diff",
                    status="ok",
                    data=data,
                    next_steps=[]
                    if int(result.level) == 0
                    else [
                        "Review conflict details before running `agentmesh skills sync --apply`."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    # 彩色 / 无色 diff 渲染
    from agentmesh.engine.diff_engine import target_skill_path
    from agentmesh.services.registry_service import resolve_skill_registry_dir

    source = resolve_skill_registry_dir(home, name)
    target_path = target_skill_path(name, target)
    diff_console = Console(no_color=no_color)
    render_diff(result, source, target_path, console=diff_console)


@app.command("conflicts")
def skills_conflicts(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    target: Annotated[str, typer.Option("--target", help="冲突检查目标 agent。")] = "hermes",
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    _print_skill_conflicts(
        home,
        target,
        json_output,
        schema="agentmesh.skills-conflicts/v1",
        command="skills conflicts",
    )


@app.command("validate")
def skills_validate(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    target: Annotated[
        str | None, typer.Option("--target", help="目标 runtime；当前主要验证 registry 结构。")
    ] = None,
    native: Annotated[
        bool, typer.Option("--native", help="同时调用目标 runtime 原生验证器；找不到命令则跳过。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    report = validate_registry_skills(home, target)
    if native and target:
        native_path = home
        if target == "claude-code":
            native_path = home / "exports" / "claude-code"
        report["native_validation"] = validate_native_runtime(target, native_path)
        if report["native_validation"]["status"] == "failed":
            report["ok"] = False
    if json_output:
        status = "ok" if report["ok"] else "error"
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-validate/v1",
                    command="skills validate",
                    status=status,
                    data={"report": report},
                    errors=[] if report["ok"] else ["skill validation failed"],
                    next_steps=[]
                    if report["ok"]
                    else ["Review findings and fix invalid skills before syncing."],
                ),
                ensure_ascii=False,
            )
        )
    else:
        console.print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Target — unified state matrix CRUD (enable / disable / show)
# ---------------------------------------------------------------------------
# The legacy trio (enable/disable/status) has been merged into a single
# `skills target <name>` command with --enable/--disable/--show modes.
# The old commands still work via a shim that prints a deprecation note.


def _handle_target_write(
    home: Path,
    name: str,
    target: str,
    *,
    enable: bool,
    json_output: bool,
    command_label: str,
) -> None:
    try:
        status = set_skill_targets(home, name, target, enabled=enable)
    except SkillStateError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-state/v1",
                        command=command_label,
                        status="error",
                        data={"skill": name, "target": target},
                        errors=[str(exc)],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(status, ensure_ascii=False))
    else:
        verb = "已启用" if enable else "已禁用"
        console.print(f"{verb} {name} -> {target}")


def _handle_target_show(
    home: Path,
    name: str | None,
    json_output: bool,
    *,
    command_label: str,
) -> None:
    status = get_skill_status(home, name)
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-status/v1",
                    command=command_label,
                    status="ok",
                    data={"state": status},
                ),
                ensure_ascii=False,
            )
        )
    else:
        console.print(json.dumps(status, ensure_ascii=False, indent=2))


@app.command("target")
def skills_target(
    name: Annotated[
        str | None,
        typer.Argument(help="skill 名。--enable/--disable 必填；--show 下可省略列出全部。"),
    ] = None,
    enable: Annotated[bool, typer.Option("--enable", help="启用指定 target。")] = False,
    disable: Annotated[bool, typer.Option("--disable", help="禁用指定 target。")] = False,
    show: Annotated[
        bool,
        typer.Option(
            "--show",
            help="打印 state 中的 skill/target 启用矩阵；省略 <name> 时列出全部。",
        ),
    ] = False,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="目标 agent，逗号分隔。--enable / --disable 必填。",
        ),
    ] = None,
    registry: Annotated[
        str | None, typer.Option(help="AgentMesh home/registry 根目录。")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """Unified enable / disable / show for the skills state matrix.

    Replaces ``skills enable`` / ``skills disable`` / ``skills status``. Exactly
    one of ``--enable`` / ``--disable`` / ``--show`` must be given.
    """
    modes = [m for m in (enable, disable, show) if m]
    if len(modes) != 1:
        raise typer.BadParameter(
            "必须指定 --enable / --disable / --show 中恰好一个"
        )
    home = resolve_agentmesh_home(registry)
    if show:
        _handle_target_show(home, name, json_output, command_label="skills target --show")
        return
    if name is None:
        raise typer.BadParameter("使用 --enable / --disable 时必须提供 skill 名。")
    if not target:
        raise typer.BadParameter("使用 --enable / --disable 时必须提供 --target <agent>")
    _handle_target_write(
        home,
        name,
        target,
        enable=enable,
        json_output=json_output,
        command_label="skills target",
    )


@app.command("enable")
def skills_enable(
    name: str,
    target: Annotated[str, typer.Option("--target", help="目标 agent，逗号分隔。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """[DEPRECATED] Use `skills target <name> --enable --target <agent>` instead."""
    _emit_deprecation(
        "skills enable",
        "skills target <name> --enable --target <agent>",
        json_output=json_output,
    )
    home = resolve_agentmesh_home(registry)
    _handle_target_write(
        home, name, target, enable=True, json_output=json_output, command_label="skills enable"
    )


@app.command("disable")
def skills_disable(
    name: str,
    target: Annotated[str, typer.Option("--target", help="目标 agent，逗号分隔。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """[DEPRECATED] Use `skills target <name> --disable --target <agent>` instead."""
    _emit_deprecation(
        "skills disable",
        "skills target <name> --disable --target <agent>",
        json_output=json_output,
    )
    home = resolve_agentmesh_home(registry)
    _handle_target_write(
        home, name, target, enable=False, json_output=json_output, command_label="skills disable"
    )


@app.command("status")
def skills_status(
    name: Annotated[
        str | None, typer.Argument(help="可选 skill 名称。省略时输出全部状态。")
    ] = None,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """[DEPRECATED] Use `skills target [<name>] --show` instead."""
    _emit_deprecation(
        "skills status",
        "skills target [<name>] --show",
        json_output=json_output,
    )
    home = resolve_agentmesh_home(registry)
    _handle_target_show(home, name, json_output, command_label="skills status")


@app.command("export")
def skills_export(
    target: str,
    out: Annotated[Path, typer.Option("--out", help="导出目录或 AgentMesh ZIP 文件。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    home = resolve_agentmesh_home(registry)
    try:
        if target == "claude-code":
            result = export_claude_code_package(home, out)
        elif target == "agentmesh":
            result = export_agentmesh_package(home, out)
        else:
            raise typer.BadParameter("当前仅支持导出目标：claude-code、agentmesh")
    except PackageError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-export/v1",
                        command="skills export",
                        status="error",
                        data={"target": target, "out": str(out)},
                        errors=[str(exc)],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-export/v1",
                    command="skills export",
                    status="ok",
                    data=result,
                    next_steps=[
                        "Validate the exported package before installing it into a target runtime."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    if target == "claude-code":
        console.print(f"已导出 Claude Code package：{out}")
    else:
        console.print(f"已导出 AgentMesh package：{out}")


@app.command("sync")
def skills_sync(
    to: Annotated[
        str | None, typer.Option(help="目标 agent，逗号分隔。使用 --enabled 时可省略。")
    ] = None,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="[DEPRECATED] 默认就是 dry-run。")
    ] = False,
    apply: Annotated[bool, typer.Option("--apply", help="执行真实写入。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
    allow_conflicts: Annotated[
        bool,
        typer.Option(
            "--allow-conflicts",
            help="允许覆盖非安全类 level 2/4 冲突；安全审计 block 和 drift 仍会阻止写入。",
        ),
    ] = False,
    mode: Annotated[str, typer.Option("--mode", help="同步模式：copy 或 symlink。")] = "copy",
    confirm: Annotated[bool, typer.Option("--confirm", help="确认执行高风险同步模式。")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
    enabled: Annotated[
        bool, typer.Option("--enabled", help="使用 state 中已启用的 skill/target。")
    ] = False,
) -> None:
    if apply and dry_run:
        raise typer.BadParameter("--dry-run 与 --apply 不能同时使用")
    if dry_run:
        _emit_dry_run_deprecation("skills sync", json_output=json_output)
    if not apply:
        dry_run = True
    home = resolve_agentmesh_home(registry)
    pairs = enabled_sync_pairs(home) if enabled else None
    if pairs is not None:
        targets = sorted({item["target"] for item in pairs})
    else:
        if not to:
            raise typer.BadParameter("必须指定 --to，或使用 --enabled 读取 state")
        targets = [x.strip() for x in to.split(",") if x.strip()]
    try:
        # symlink 模式需要显式 --confirm，提前校验避免进入交互式确认流程
        if mode == "symlink" and apply and not confirm:
            raise UnsupportedSyncMode("symlink 模式需要显式 --confirm 才能 apply")
        # apply 模式且非 JSON 时，先 dry-run 展示计划再确认
        if apply and not json_output:
            plan = sync(
                home,
                targets,
                apply=False,
                allow_conflicts=allow_conflicts,
                mode=mode,
                confirm=confirm,
                pairs=pairs,
            )
            actions = plan.get("actions", [])
            plan_summary = plan.get("summary", {})
            show_plan_and_confirm(
                title="🔄 Skill 同步计划",
                summary={
                    "目标": ", ".join(targets),
                    "同步模式": plan.get("sync_mode", "copy"),
                    "总操作数": plan_summary.get("actions", len(actions)),
                    "允许": plan_summary.get("allowed", 0),
                    "阻止": plan_summary.get("blocked", 0),
                    "警告": plan_summary.get("warnings", 0),
                },
                columns=["Skill", "决策", "差异级别", "摘要"] if actions else None,
                rows=[
                    [
                        a.get("skill", "?"),
                        a.get("decision", "?"),
                        a.get("diff", {}).get("name", "?"),
                        a.get("diff", {}).get("summary", ""),
                    ]
                    for a in actions
                ]
                if actions
                else None,
                yes=yes or confirm,
                dry_run=False,
            )
        result = sync(
            home,
            targets,
            apply=apply,
            allow_conflicts=allow_conflicts,
            mode=mode,
            confirm=confirm,
            pairs=pairs,
        )
    except SyncBlocked as exc:
        status = "error" if isinstance(exc, UnsupportedSyncTarget) else "blocked"
        response = _cli_response(
            schema="agentmesh.skills-sync/v1",
            command="skills sync",
            status=status,
            data={"targets": targets},
            errors=[str(exc)],
            next_steps=["Use `agentmesh agents list` to inspect supported targets."]
            if isinstance(exc, UnsupportedSyncTarget)
            else ["Review blocked reasons, then rerun with --dry-run before applying."],
        )
        response["dry_run"] = not apply
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(
                str(exc) if isinstance(exc, UnsupportedSyncTarget) else f"同步被阻止：{exc}"
            )
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.skills-sync/v1",
        command="skills sync",
        status="applied" if apply else "planned",
        data={"plan": result},
        next_steps=["Inspect target runtime skill directories and sync history."]
        if apply
        else ["Run with --apply to execute this sync plan."],
    )
    response["dry_run"] = not apply
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        # apply 成功后把 backup 位置和操作统计单独再打一行，便于用户之后快速
        # 定位 rollback 入口（JSON 输出本身已经包含这些字段，所以只补 TTY 路径）。
        if apply:
            summary = result.get("summary", {})
            backup = result.get("backup")
            applied_count = summary.get("actions", 0) - summary.get("blocked", 0)
            console.print(
                f"[green]✓ sync 完成[/green]  "
                f"applied={applied_count} skipped={summary.get('skipped', 0)} "
                f"blocked={summary.get('blocked', 0)}"
            )
            if backup:
                console.print(f"  backup: {backup}")
                console.print(
                    "  如需回滚，使用 `agentmesh rollback plan --backup <backup>` "
                    "或查看 `state/sync-history.jsonl`"
                )


@app.command("rename")
def skills_rename(
    old_name: str = typer.Argument(..., help="当前 skill 名"),
    new_name: str = typer.Argument(..., help="新 skill 名"),
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """Rename a skill in the registry, also updating state/skills.yaml."""
    home = resolve_agentmesh_home(registry)
    try:
        new_path = rename_registry_skill(home, old_name, new_name)
        rename_skill_state(home, old_name, new_name)
    except (RegistrySkillNotFound, RegistrySkillExists, SkillStateError, ValueError) as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-rename/v1",
                        command="skills rename",
                        status="error",
                        data={"old_name": old_name, "new_name": new_name},
                        errors=[str(exc)],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    data = {
        "old_name": old_name,
        "new_name": new_name,
        "path": str(new_path),
    }
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-rename/v1",
                    command="skills rename",
                    status="ok",
                    data=data,
                    next_steps=[
                        "Target-side synced copies still use the old name. "
                        "Run `agentmesh skills sync --to <agent>` to re-project, "
                        "or `agentmesh skills delete <old> --purge-targets` if you need a cleanup."
                    ],
                ),
                ensure_ascii=False,
            )
        )
        return
    console.print(f"已重命名 {old_name} → {new_name}（{new_path}）")
    console.print(
        "提示：target 上已同步的副本仍使用旧名字；如需同步过去，"
        "请运行 `agentmesh skills sync --to <agent>`。"
    )


@app.command("delete")
def skills_delete(
    name: str = typer.Argument(..., help="要删除的 skill 名"),
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    purge_targets: Annotated[
        bool,
        typer.Option(
            "--purge-targets",
            help=(
                "同时删除所有 target runtime 上由 AgentMesh 同步过来的副本"
                "（仅删除带 AgentMesh lockfile 的目录 / 符号链接）。"
            ),
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """Remove a skill from the registry. Optionally cascade to target copies."""
    home = resolve_agentmesh_home(registry)
    if not yes and not json_output:
        scope = "registry + 所有 target 上的 AgentMesh 副本" if purge_targets else "仅 registry"
        console.print(
            f"[yellow]即将删除 skill[/yellow] `{name}`（{scope}）。"
        )
        console.print("如不确定，请使用 --yes / -y 确认，或先 `agentmesh skills show <name>`。")
        raise typer.Exit(code=2)
    try:
        removed_path = delete_registry_skill(home, name)
    except RegistrySkillNotFound as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.skills-delete/v1",
                        command="skills delete",
                        status="error",
                        data={"skill": name},
                        errors=[str(exc)],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    remove_skill_state(home, name)
    purge_results: list[dict[str, str]] = []
    if purge_targets:
        purge_results = purge_target_skill_copies(home, name)
    data = {
        "skill": name,
        "removed_path": str(removed_path),
        "purge_targets": purge_targets,
        "purge_results": purge_results,
    }
    if json_output:
        typer.echo(
            json.dumps(
                _cli_response(
                    schema="agentmesh.skills-delete/v1",
                    command="skills delete",
                    status="ok",
                    data=data,
                    summary={
                        "removed": 1,
                        "targets_touched": len(
                            [r for r in purge_results if r["action"].startswith("removed_")]
                        ),
                    },
                ),
                ensure_ascii=False,
            )
        )
        return
    console.print(f"[green]已删除[/green] registry skill：{removed_path}")
    if purge_targets:
        for record in purge_results:
            prefix = "✓" if record["action"].startswith("removed_") else "·"
            console.print(f"  {prefix} {record['target']}: {record['action']} → {record['path']}")
