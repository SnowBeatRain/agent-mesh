"""彩色 diff 渲染器：用于 `skills diff` 命令的 Rich 输出。

使用 `rich.console.Console` 和 `rich.text.Text` 渲染：
- 文件级别差异（新增 / 删除 / 修改），红色/绿色高亮
- SKILL.md 内容行级 diff，类似 git diff
- metadata（frontmatter）字段变化
"""

from __future__ import annotations

import difflib
from pathlib import Path

from rich.console import Console
from rich.text import Text

from agentmesh.engine.conflict_resolver import ConflictResult
from agentmesh.utils.frontmatter import read_skill_document


# ── 状态标签 ──────────────────────────────────────────────

_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "source-only": ("green", "新增"),
    "target-only": ("red", "删除"),
    "changed": ("yellow", "修改"),
    "missing-target": ("red", "缺失"),
    "blocked": ("red", "安全阻止"),
}


def _status_label(status: str) -> Text:
    style, label = _STATUS_STYLE.get(status, ("white", status))
    return Text(f"[{label}]", style=f"bold {style}")


# ── 文件级差异 ─────────────────────────────────────────────

def render_file_changes(
    changes: list[dict],
    *,
    console: Console,
) -> None:
    """渲染文件级别的差异列表。"""
    if not changes:
        console.print("  （无文件差异）", style="dim")
        return
    for change in changes:
        path = change.get("path", "")
        status = change.get("status", "changed")
        label = _status_label(status)
        kind = change.get("kind", "")
        kind_text = Text(f" ({kind})", style="dim") if kind else Text("")
        line = Text("  ")
        line.append_text(label)
        line.append(f" {path}")
        line.append_text(kind_text)
        console.print(line)


# ── 行级 diff ─────────────────────────────────────────────

def _line_diff(
    old_text: str,
    new_text: str,
    old_label: str,
    new_label: str,
) -> list[str]:
    """生成 unified diff 文本行。"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    return list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_label,
            tofile=new_label,
            lineterm="",
        )
    )


def _render_diff_lines(lines: list[str], *, console: Console) -> None:
    """将 unified diff 行以红/绿着色输出。"""
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            console.print(Text(line, style="bold"))
        elif line.startswith("@@"):
            console.print(Text(line, style="cyan"))
        elif line.startswith("+"):
            console.print(Text(line, style="green"))
        elif line.startswith("-"):
            console.print(Text(line, style="red"))
        else:
            console.print(line)


def _is_binary_content(data: bytes) -> bool:
    """检测内容是否为二进制（包含 null 字节或非 UTF-8）。"""
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def render_content_diff(
    source_path: Path,
    target_path: Path,
    rel: str,
    *,
    console: Console,
) -> None:
    """对单个文件渲染行级 unified diff。"""
    if not source_path.exists() or not target_path.exists():
        return
    try:
        src_data = source_path.read_bytes()
        tgt_data = target_path.read_bytes()
    except OSError:
        return
    if _is_binary_content(src_data) or _is_binary_content(tgt_data):
        return
    old_text = tgt_data.decode("utf-8")
    new_text = src_data.decode("utf-8")
    lines = _line_diff(
        old_text,
        new_text,
        old_label=f"a/{rel}",
        new_label=f"b/{rel}",
    )
    if lines:
        _render_diff_lines(lines, console=console)


# ── metadata 差异 ──────────────────────────────────────────

def _format_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return str(value)
    return str(value) if value is not None else "(无)"


def render_metadata_diff(
    source_path: Path,
    target_path: Path,
    *,
    console: Console,
) -> bool:
    """比较两个 SKILL.md 的 frontmatter 字段，以红/绿输出差异。

    Returns:
        True 行渲染了差异，False 无差异或无法解析。
    """
    if not source_path.exists() or not target_path.exists():
        return False
    try:
        src_doc = read_skill_document(source_path)
        tgt_doc = read_skill_document(target_path)
    except Exception:
        return False
    src_meta = src_doc.metadata
    tgt_meta = tgt_doc.metadata
    all_keys = sorted(set(src_meta) | set(tgt_meta))
    has_diff = False
    for key in all_keys:
        src_val = src_meta.get(key)
        tgt_val = tgt_meta.get(key)
        if src_val == tgt_val:
            continue
        has_diff = True
        if tgt_val is None:
            text = Text("  ")
            text.append(f"+ {key}: ", style="bold green")
            text.append(_format_value(src_val), style="green")
            console.print(text)
        elif src_val is None:
            text = Text("  ")
            text.append(f"- {key}: ", style="bold red")
            text.append(_format_value(tgt_val), style="red")
            console.print(text)
        else:
            text_del = Text("  ")
            text_del.append(f"- {key}: ", style="bold red")
            text_del.append(_format_value(tgt_val), style="red")
            console.print(text_del)
            text_add = Text("  ")
            text_add.append(f"+ {key}: ", style="bold green")
            text_add.append(_format_value(src_val), style="green")
            console.print(text_add)
    return has_diff


# ── 顶层渲染入口 ────────────────────────────────────────────

def render_diff(
    result: ConflictResult,
    source: Path,
    target: Path,
    *,
    console: Console,
) -> None:
    """渲染完整的 skill diff 输出（彩色）。"""
    level = int(result.level)
    level_style = "green" if level == 0 else ("yellow" if level <= 2 else "red")
    header = Text()
    header.append("level ", style="bold")
    header.append(str(level), style=f"bold {level_style}")
    header.append(f" {result.name}: ", style="bold")
    header.append(result.summary, style=level_style)
    console.print(header)

    changes = result.changes or []
    if not changes:
        return

    # ── 文件级别差异概览 ──
    console.print()
    console.print("文件差异:", style="bold underline")
    render_file_changes(changes, console=console)

    # ── metadata 差异 ──
    meta_changes = [c for c in changes if c.get("kind") == "metadata"]
    if meta_changes:
        console.print()
        console.print("Metadata 差异:", style="bold underline")
        for change in meta_changes:
            rel = change["path"]
            src_file = source / rel
            tgt_file = target / rel
            console.print(f"  {rel}:", style="bold")
            rendered = render_metadata_diff(src_file, tgt_file, console=console)
            if not rendered:
                console.print("  （无法解析 metadata 差异）", style="dim")

    # ── 内容行级 diff（SKILL.md 和其他变更文件）──
    content_changes = [
        c for c in changes if c.get("kind") in ("entrypoint", "file-tree")
    ]
    if content_changes:
        console.print()
        console.print("内容差异:", style="bold underline")
        for change in content_changes:
            rel = change["path"]
            src_file = source / rel
            tgt_file = target / rel
            status = change.get("status", "")
            if status == "source-only":
                console.print(f"  {rel}: 新增文件", style="green")
                if src_file.exists():
                    try:
                        text = src_file.read_text(encoding="utf-8")
                        for line in text.splitlines():
                            console.print(Text(f"+{line}", style="green"))
                    except (UnicodeDecodeError, OSError):
                        pass
            elif status == "target-only":
                console.print(f"  {rel}: 删除文件", style="red")
                if tgt_file.exists():
                    try:
                        text = tgt_file.read_text(encoding="utf-8")
                        for line in text.splitlines():
                            console.print(Text(f"-{line}", style="red"))
                    except (UnicodeDecodeError, OSError):
                        pass
            else:
                console.print(f"  {rel}:", style="bold")
                render_content_diff(src_file, tgt_file, rel, console=console)
