from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.cli.envelope import build_envelope
from agentmesh.cli.confirm import show_plan_and_confirm
from agentmesh.services.package_registry import (
    PackageRegistryError,
    install_package,
    list_available_packages,
    publish_skill,
    uninstall_package,
)
from agentmesh.services.package_service import (
    PackageError,
    inspect_agentmesh_package,
    verify_agentmesh_package,
)

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="AgentMesh package 命令。")


@app.command("inspect")
def package_inspect(
    package: Path,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    try:
        report = inspect_agentmesh_package(package)
    except PackageError as exc:
        response = _cli_response(
            schema="agentmesh.package-inspect/v1",
            command="package inspect",
            status="error",
            data={"package": str(package)},
            errors=[str(exc)],
            next_steps=[
                "Use `agentmesh package inspect <zip>` before import; "
                "inspect does not verify checksums."
            ],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.package-inspect/v1",
        command="package inspect",
        status="ok",
        data=report,
        warnings=report["warnings"],
        next_steps=[
            "Run `agentmesh skills import-package <zip> --dry-run` for audit/conflict planning."
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"Package: {report['package']}")
        console.print(f"Schema: {report['package_schema']}")
        console.print(f"Skills: {report['summary']['skill_count']}")
        console.print(f"Files: {report['summary']['file_count']}")
        for skill in report["skills"]:
            console.print(f"- {skill['name']} ({skill['path']})")
        console.print("注意：inspect 只查看内容，不等于 verify/audit。")


@app.command("verify")
def package_verify(
    package: Path,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    try:
        report = verify_agentmesh_package(package)
    except PackageError as exc:
        response = _cli_response(
            schema="agentmesh.package-verify/v1",
            command="package verify",
            status="error",
            data={"package": str(package)},
            errors=[str(exc)],
            next_steps=["Run `agentmesh package inspect <zip>` to inspect package structure."],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.package-verify/v1",
        command="package verify",
        status="ok" if report["valid"] else "error",
        data=report,
        warnings=report["warnings"],
        errors=[f"{error['kind']}: {error['path']}" for error in report["errors"]],
        next_steps=[
            "Run `agentmesh skills import-package <zip> --dry-run` for audit/policy checks."
        ]
        if report["valid"]
        else ["Re-export the package from a trusted registry source, then verify again."],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"Package verify: {'valid' if report['valid'] else 'invalid'}")
        console.print(f"Package: {report['package']}")
        console.print(f"Declared files: {report['summary']['declared_files']}")
        console.print(f"Verified files: {report['summary']['verified_files']}")
        if report["errors"]:
            for error in report["errors"]:
                console.print(f"- {error['kind']}: {error['path']}")
        console.print("注意：verify 只校验清单和 checksum，不等于 audit/policy。")
    if not report["valid"]:
        raise typer.Exit(code=1)


@app.command("publish")
def package_publish(
    skill_name: Annotated[str, typer.Argument(help="要发布的 skill 名称。")],
    version: Annotated[str, typer.Argument(help="版本号（semver 格式）。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    force: Annotated[bool, typer.Option("--force", help="覆盖已存在的版本。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    from agentmesh.config.loader import resolve_agentmesh_home

    home = resolve_agentmesh_home(registry)
    try:
        result = publish_skill(home, skill_name, version, force=force)
    except PackageRegistryError as exc:
        response = _cli_response(
            schema="agentmesh.package-publish/v1",
            command="package publish",
            status="error",
            data={"skill": skill_name, "version": version},
            errors=[str(exc)],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.package-publish/v1",
        command="package publish",
        status="ok",
        data=result,
        next_steps=[
            f"Run `agentmesh package install {skill_name}` to install into registry.",
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"已发布 {skill_name}@{version} 到 {result['path']}")


def _is_url(name: str) -> bool:
    """检测是否为 URL。"""
    return name.startswith(("http://", "https://", "github.com/"))


@app.command("install")
def package_install(
    skill_name: Annotated[str, typer.Argument(help="要安装的 package 名称或 URL。")],
    version: Annotated[str | None, typer.Argument(help="版本号（默认最新）。")] = None,
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    branch: Annotated[str | None, typer.Option(help="Git 分支（仅 URL 安装）。")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="覆盖 registry 中已有的同名 skill。")
    ] = False,
    resolve_deps: Annotated[
        bool, typer.Option("--resolve-deps", help="自动解析并安装依赖。")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过交互确认。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    import tempfile

    from agentmesh.config.loader import resolve_agentmesh_home
    from agentmesh.services.remote_fetcher import fetch_from_url

    home = resolve_agentmesh_home(registry)
    source = skill_name
    tmp_dir = None

    # URL 安装：先下载到临时目录
    if _is_url(skill_name):
        url = skill_name
        if not url.startswith("http"):
            url = "https://" + url
        tmp_dir = tempfile.mkdtemp(prefix="agentmesh-remote-")
        try:
            fetch_from_url(url, tmp_dir, branch=branch)
        except Exception as exc:
            console.print(f"[red]下载失败：{exc}[/red]")
            raise typer.Exit(code=1) from exc
        # 从临时目录找到 skill 名称
        from pathlib import Path

        tmp_path = Path(tmp_dir)
        skill_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        if len(skill_dirs) == 1:
            source = str(skill_dirs[0])
            skill_name = skill_dirs[0].name
        else:
            source = tmp_dir
            skill_name = url.split("/")[-1].replace(".git", "")

    # 非 JSON 模式下展示安装信息供确认
    if not json_output:
        show_plan_and_confirm(
            title="📦 安装 Skill Package",
            summary={
                "Package": skill_name,
                "来源": source if _is_url(skill_name) else "本地",
                "版本": version or "最新",
                "覆盖已有": "是" if force else "否",
                "解析依赖": "是" if resolve_deps else "否",
            },
            yes=yes,
            dry_run=False,
            prompt=f"确认安装 {skill_name}？",
        )
    try:
        if _is_url(skill_name):
            # URL 安装：从临时目录导入
            from agentmesh.services.registry_service import import_skill

            result = import_skill(
                home,
                skill_name,
                source_dir=Path(source),
                force=force,
            )
        else:
            result = install_package(
                home,
                skill_name,
                version=version,
                resolve_deps=resolve_deps,
                force=force,
            )
    except PackageRegistryError as exc:
        response = _cli_response(
            schema="agentmesh.package-install/v1",
            command="package install",
            status="error",
            data={"skill": skill_name},
            errors=[str(exc)],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.package-install/v1",
        command="package install",
        status="ok" if result.get("action") != "skip" else "ok",
        data=result,
        next_steps=[
            "Run `agentmesh agents list` to verify skill availability.",
        ],
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        action = result.get("action", "installed")
        if action == "skip":
            console.print(f"{skill_name}@{result['version']} 已安装，内容相同，跳过。")
        else:
            deps_msg = ""
            if result.get("resolved_deps"):
                deps_msg = f"（已解析依赖：{', '.join(result['resolved_deps'])}）"
            console.print(f"已安装 {skill_name}@{result['version']} {deps_msg}")


@app.command("uninstall")
def package_uninstall(
    skill_name: Annotated[str, typer.Argument(help="要卸载的 skill 名称。")],
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    from agentmesh.config.loader import resolve_agentmesh_home

    home = resolve_agentmesh_home(registry)
    try:
        result = uninstall_package(home, skill_name)
    except PackageRegistryError as exc:
        response = _cli_response(
            schema="agentmesh.package-uninstall/v1",
            command="package uninstall",
            status="error",
            data={"skill": skill_name},
            errors=[str(exc)],
        )
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False))
        else:
            console.print(str(exc))
        raise typer.Exit(code=1) from exc
    response = _cli_response(
        schema="agentmesh.package-uninstall/v1",
        command="package uninstall",
        status="ok",
        data=result,
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        console.print(f"已卸载 {skill_name}")


@app.command("list")
def package_list(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    from agentmesh.config.loader import resolve_agentmesh_home

    home = resolve_agentmesh_home(registry)
    packages = list_available_packages(home)
    response = _cli_response(
        schema="agentmesh.package-list/v1",
        command="package list",
        status="ok",
        data={"packages": packages, "total": len(packages)},
    )
    if json_output:
        typer.echo(json.dumps(response, ensure_ascii=False))
    else:
        if not packages:
            console.print("暂无已发布的 package。")
        else:
            for pkg in packages:
                console.print(
                    f"  {pkg['name']}  latest={pkg['latest']}  versions={','.join(pkg['versions'])}"
                )
