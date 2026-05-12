"""Remote Fetcher：从远端 URL 下载并解压 package。

支持：
  - GitHub 仓库 URL（自动转换为 archive URL）
  - 直接 ZIP / tar.gz 归档 URL
  - 下载到临时目录后解压到目标目录
"""

from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse


class RemoteFetchError(RuntimeError):
    """远端 package 获取失败时抛出。"""


# GitHub patterns:
#   https://github.com/owner/repo
#   https://github.com/owner/repo/tree/branch
#   https://github.com/owner/repo/tree/branch/subdir
_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
    r"(/tree/(?P<branch>[^/]+)(/(?P<subdir>.+))?)?/?$"
)


def _is_archive_url(url: str) -> bool:
    """判断 URL 是否指向 ZIP 或 tar.gz 归档。"""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return (
        path.endswith(".zip")
        or path.endswith(".tar.gz")
        or path.endswith(".tgz")
        or path.endswith(".tar.bz2")
    )


def _convert_github_url(url: str) -> str | None:
    """尝试将 GitHub 仓库 URL 转换为 archive 下载 URL。

    返回转换后的 URL，若非 GitHub 仓库 URL 则返回 None。
    """
    m = _GITHUB_REPO_RE.match(url.rstrip("/"))
    if m is None:
        return None
    owner = m.group("owner")
    repo = m.group("repo")
    branch = m.group("branch") or "main"
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"


def _download_file(url: str, dest: Path) -> None:
    """下载文件到指定路径。"""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlretrieve(url, str(dest))
    except urllib.error.URLError as exc:
        raise RemoteFetchError(f"下载失败：{url}（{exc}）") from exc


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    """解压 ZIP 或 tar.gz 到目标目录。"""
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        _extract_zip(archive_path, dest_dir)
    elif name.endswith(".tar.gz") or name.endswith(".tgz"):
        _extract_tar(archive_path, dest_dir)
    elif name.endswith(".tar.bz2"):
        _extract_tar(archive_path, dest_dir)
    else:
        raise RemoteFetchError(f"不支持的归档格式：{archive_path.name}")


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    """解压 ZIP 归档。自动剥离顶层单一目录。"""
    try:
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            _check_zip_safety(names)
            prefix = _detect_single_top_dir(names)
            for info in zf.infolist():
                rel = info.filename
                if prefix:
                    if rel == prefix.rstrip("/") or rel.startswith(prefix):
                        rel = rel[len(prefix) :]
                    else:
                        continue
                if not rel:
                    continue
                target = dest_dir / rel
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as exc:
        raise RemoteFetchError(f"无效的 ZIP 文件：{archive_path.name}") from exc


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    """解压 tar.gz/tar.bz2 归档。自动剥离顶层单一目录。"""
    try:
        with tarfile.open(archive_path) as tf:
            names = tf.getnames()
            prefix = _detect_single_top_dir(names)
            for member in tf.getmembers():
                rel = member.name
                if prefix:
                    if rel == prefix.rstrip("/") or rel.startswith(prefix):
                        rel = rel[len(prefix) :]
                    else:
                        continue
                if not rel:
                    continue
                target = dest_dir / rel
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src is None:
                        continue
                    with src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    except (tarfile.TarError, EOFError) as exc:
        raise RemoteFetchError(f"无效的 tar 归档：{archive_path.name}") from exc


def _detect_single_top_dir(names: list[str]) -> str:
    """检测是否有单一顶层目录（GitHub 归档常见）。

    如果所有非空路径都以同一个顶层目录开头，则返回该前缀，否则返回空字符串。
    """
    if not names:
        return ""
    top_names: set[str] = set()
    for name in names:
        parts = name.split("/")
        if len(parts) > 1 and parts[0]:
            top_names.add(parts[0])
    if len(top_names) == 1:
        top = top_names.pop()
        prefix = top + "/"
        # 验证所有条目都在这个顶层目录下
        if all(name.startswith(prefix) or name == prefix.rstrip("/") for name in names):
            return prefix
    return ""


def _check_zip_safety(names: list[str]) -> None:
    """检查 ZIP 条目是否包含路径穿越。"""
    windows_drive_re = re.compile(r"^[A-Za-z]:")
    for name in names:
        clean = name.replace("\\", "/")
        if clean.startswith("/") or windows_drive_re.match(clean):
            raise RemoteFetchError(f"unsafe zip path: {name}")
        parts = clean.split("/")
        if any(part in {".."} for part in parts):
            raise RemoteFetchError(f"unsafe zip path: {name}")


def fetch_from_url(url: str, dest_dir: Path) -> Path:
    """从远端 URL 下载 package 到目标目录。

    参数：
        url: 远端资源 URL，支持：
             - GitHub 仓库 URL（https://github.com/owner/repo）
             - 直接归档 URL（.zip / .tar.gz / .tgz）
        dest_dir: 解压目标目录

    返回：
        dest_dir 的 Path 对象

    抛出：
        RemoteFetchError: URL 无效、下载失败、或解压失败时
    """
    if not url or not url.strip():
        raise RemoteFetchError("URL 不能为空")

    url = url.strip()

    # 判断下载 URL
    if _is_archive_url(url):
        download_url = url
    else:
        converted = _convert_github_url(url)
        if converted is not None:
            download_url = converted
        else:
            raise RemoteFetchError(
                f"不支持的 URL 格式：{url}\n支持的格式：GitHub 仓库 URL 或直接 .zip/.tar.gz URL"
            )

    # 确定归档文件扩展名
    parsed = urlparse(download_url)
    path_lower = parsed.path.lower()
    if path_lower.endswith(".tar.gz"):
        suffix = ".tar.gz"
    elif path_lower.endswith(".tgz"):
        suffix = ".tgz"
    elif path_lower.endswith(".tar.bz2"):
        suffix = ".tar.bz2"
    elif path_lower.endswith(".zip"):
        suffix = ".zip"
    else:
        suffix = ".zip"  # fallback

    # 下载到临时目录
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"archive{suffix}"
        _download_file(download_url, tmp_path)

        # 解压到目标目录
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        _extract_archive(tmp_path, dest_dir)

    return dest_dir
