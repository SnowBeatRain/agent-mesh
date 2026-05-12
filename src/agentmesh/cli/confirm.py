"""AgentMesh CLI 确认交互工具模块。

为危险操作提供统一的交互式确认体验：
- 使用 Rich Panel 显示操作摘要
- 使用 Rich Table 显示变更列表
- 支持 --yes/-y 跳过确认
- 支持 --dry-run 只显示计划不执行
"""
from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def build_change_table(
    title: str,
    columns: list[str],
    rows: list[list[str]],
    *,
    show_lines: bool = False,
) -> Table:
    """构建变更列表表格。"""
    table = Table(title=title, show_lines=show_lines, expand=True)
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*row)
    return table


def build_plan_panel(
    title: str,
    summary: dict[str, Any],
    *,
    extra_lines: list[str] | None = None,
) -> Panel:
    """构建操作计划面板。"""
    lines: list[str] = []
    for key, value in summary.items():
        lines.append(f"[bold]{key}[/bold]: {value}")
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    body = "\n".join(lines) if lines else "（无摘要信息）"
    return Panel(body, title=title, border_style="yellow")


def confirm_or_exit(
    *,
    yes: bool = False,
    dry_run: bool = False,
    prompt: str = "确认执行以上操作？",
) -> None:
    """交互确认：--yes 自动通过，--dry-run 时提示退出。

    Parameters
    ----------
    yes:
        为 True 时直接跳过确认。
    dry_run:
        为 True 时只显示计划并退出，不执行。
    prompt:
        确认提示文字。
    """
    if dry_run:
        console.print("\n[dim]（dry-run 模式，未执行任何写入操作）[/dim]")
        raise typer.Exit(code=0)
    if yes:
        return
    try:
        answer = input(f"\n{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        console.print("[dim]已取消。[/dim]")
        raise typer.Exit(code=0)


def show_plan_and_confirm(
    *,
    title: str,
    summary: dict[str, Any],
    columns: list[str] | None = None,
    rows: list[list[str]] | None = None,
    extra_lines: list[str] | None = None,
    yes: bool = False,
    dry_run: bool = False,
    prompt: str = "确认执行以上操作？",
) -> None:
    """一站式显示计划面板 + 变更表格 + 交互确认。

    典型用法::

        show_plan_and_confirm(
            title="Skill 同步计划",
            summary={"目标": "hermes", "变更数": 3},
            columns=["Skill", "操作", "状态"],
            rows=[["demo", "覆盖", "CONTENT_CHANGED"]],
            yes=yes, dry_run=dry_run,
        )
        # 如果用户拒绝或 dry-run，此处不会返回（直接 exit）
    """
    panel = build_plan_panel(title, summary, extra_lines=extra_lines)
    console.print(panel)
    if columns and rows:
        table = build_change_table("变更详情", columns, rows, show_lines=True)
        console.print(table)
    confirm_or_exit(yes=yes, dry_run=dry_run, prompt=prompt)
