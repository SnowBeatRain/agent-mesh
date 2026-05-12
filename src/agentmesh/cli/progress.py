"""CLI 进度指示器工具。

提供两种进度指示模式：
- ``progress_bar``: 已知总数时使用，显示进度条和百分比。
- ``spinner``: 未知总数时使用，显示旋转动画。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, Iterator

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_console = Console()


def _build_bar(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def _build_status(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


@contextmanager
def progress_bar(
    description: str,
    total: int,
    *,
    console: Console | None = None,
) -> Iterator[Callable[[], None]]:
    """已知总数时的进度条上下文管理器。

    Yields:
        advance: 每完成一个步骤后调用的函数。

    Usage::

        with progress_bar("扫描", total=5) as advance:
            for item in items:
                process(item)
                advance()
    """
    con = console or _console
    prog = _build_bar(con)
    with prog:
        prog.add_task(description, total=total)

        def advance() -> None:
            prog.advance(prog.task_ids[0])

        yield advance


@contextmanager
def spinner(
    description: str,
    *,
    console: Console | None = None,
) -> Iterator[None]:
    """未知总数时的旋转动画上下文管理器。

    Usage::

        with spinner("扫描模型配置"):
            do_work()
    """
    con = console or _console
    prog = _build_status(con)
    with prog:
        prog.add_task(description)
        yield


def scan_with_progress(
    items: Sequence,
    process: Callable,
    description: str,
    *,
    console: Console | None = None,
) -> list:
    """扫描一组项目并显示进度条。

    Args:
        items: 待扫描的项目列表。
        process: 处理单个项目的函数，返回结果。
        description: 进度条描述文本。
        console: 可选 Rich Console 实例。

    Returns:
        处理结果列表（不含 None 结果）。
    """
    results = []
    with progress_bar(description, len(items), console=console) as advance:
        for item in items:
            result = process(item)
            if result is not None:
                results.append(result)
            advance()
    return results
