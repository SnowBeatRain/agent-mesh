"""测试 Remote Fetcher：远端 package 下载与解压。"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agentmesh.services.remote_fetcher import (
    RemoteFetchError,
    _check_zip_safety,
    _convert_github_url,
    _detect_single_top_dir,
    _extract_archive,
    _extract_tar,
    _extract_zip,
    _is_archive_url,
    fetch_from_url,
)

# ── URL 检测 ─────────────────────────────────────────────────────────


def test_is_archive_url_zip():
    assert _is_archive_url("https://example.com/pkg.zip") is True


def test_is_archive_url_tar_gz():
    assert _is_archive_url("https://example.com/pkg.tar.gz") is True


def test_is_archive_url_tgz():
    assert _is_archive_url("https://example.com/pkg.tgz") is True


def test_is_archive_url_tar_bz2():
    assert _is_archive_url("https://example.com/pkg.tar.bz2") is True


def test_is_archive_url_not_archive():
    assert _is_archive_url("https://github.com/owner/repo") is False


def test_is_archive_url_html():
    assert _is_archive_url("https://example.com/page.html") is False


# ── GitHub URL 转换 ──────────────────────────────────────────────────


def test_convert_github_repo_url():
    result = _convert_github_url("https://github.com/owner/repo")
    assert result == "https://github.com/owner/repo/archive/refs/heads/main.zip"


def test_convert_github_repo_url_with_branch():
    result = _convert_github_url("https://github.com/owner/repo/tree/dev")
    assert result == "https://github.com/owner/repo/archive/refs/heads/dev.zip"


def test_convert_github_repo_url_with_subdir():
    result = _convert_github_url("https://github.com/owner/repo/tree/main/packages")
    assert result == "https://github.com/owner/repo/archive/refs/heads/main.zip"


def test_convert_github_url_trailing_slash():
    result = _convert_github_url("https://github.com/owner/repo/")
    assert result == "https://github.com/owner/repo/archive/refs/heads/main.zip"


def test_convert_non_github_url_returns_none():
    assert _convert_github_url("https://example.com/pkg.zip") is None


def test_convert_github_url_http():
    result = _convert_github_url("http://github.com/owner/repo")
    assert result == "https://github.com/owner/repo/archive/refs/heads/main.zip"


# ── 顶层目录检测 ─────────────────────────────────────────────────────


def test_detect_single_top_dir():
    names = ["repo-main/", "repo-main/file.txt", "repo-main/sub/file2.txt"]
    assert _detect_single_top_dir(names) == "repo-main/"


def test_detect_single_top_dir_none():
    names = ["file1.txt", "file2.txt", "sub/file3.txt"]
    assert _detect_single_top_dir(names) == ""


def test_detect_single_top_dir_multiple():
    names = ["a/file.txt", "b/file.txt"]
    assert _detect_single_top_dir(names) == ""


def test_detect_single_top_dir_empty():
    assert _detect_single_top_dir([]) == ""


# ── ZIP 安全检查 ─────────────────────────────────────────────────────


def test_check_zip_safety_normal():
    # 不应抛出
    _check_zip_safety(["file.txt", "sub/dir/file.txt"])


def test_check_zip_safety_rejects_dotdot():
    with pytest.raises(RemoteFetchError, match="unsafe zip path"):
        _check_zip_safety(["../escape.txt"])


def test_check_zip_safety_rejects_absolute():
    with pytest.raises(RemoteFetchError, match="unsafe zip path"):
        _check_zip_safety(["/etc/passwd"])


# ── ZIP 解压 ─────────────────────────────────────────────────────────


def _make_zip(files: dict[str, bytes]) -> Path:
    """创建一个临时 ZIP 文件，返回其 Path。"""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return Path(tmp.name)


def test_extract_zip_basic(tmp_path):
    archive = _make_zip(
        {
            "file1.txt": b"hello",
            "sub/file2.txt": b"world",
        }
    )
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_zip(archive, dest)
    assert (dest / "file1.txt").read_text() == "hello"
    assert (dest / "sub" / "file2.txt").read_text() == "world"


def test_extract_zip_strips_single_top_dir(tmp_path):
    archive = _make_zip(
        {
            "repo-main/file1.txt": b"hello",
            "repo-main/sub/file2.txt": b"world",
        }
    )
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_zip(archive, dest)
    assert (dest / "file1.txt").read_text() == "hello"
    assert (dest / "sub" / "file2.txt").read_text() == "world"


def test_extract_zip_invalid(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"not a zip")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(RemoteFetchError, match="无效的 ZIP"):
        _extract_zip(bad_zip, dest)


# ── tar.gz 解压 ──────────────────────────────────────────────────────


def _make_tar_gz(files: dict[str, bytes]) -> Path:
    """创建一个临时 tar.gz 文件，返回其 Path。"""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    with tarfile.open(tmp.name, "w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return Path(tmp.name)


def test_extract_tar_basic(tmp_path):
    archive = _make_tar_gz(
        {
            "file1.txt": b"hello",
            "sub/file2.txt": b"world",
        }
    )
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_tar(archive, dest)
    assert (dest / "file1.txt").read_text() == "hello"
    assert (dest / "sub" / "file2.txt").read_text() == "world"


def test_extract_tar_strips_single_top_dir(tmp_path):
    archive = _make_tar_gz(
        {
            "repo-main/file1.txt": b"hello",
            "repo-main/sub/file2.txt": b"world",
        }
    )
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_tar(archive, dest)
    assert (dest / "file1.txt").read_text() == "hello"
    assert (dest / "sub" / "file2.txt").read_text() == "world"


def test_extract_tar_invalid(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tar.gz")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(RemoteFetchError, match="无效的 tar"):
        _extract_tar(bad, dest)


# ── extract_archive 路由 ─────────────────────────────────────────────


def test_extract_archive_routes_to_zip(tmp_path):
    archive = _make_zip({"file.txt": b"zip"})
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_archive(archive, dest)
    assert (dest / "file.txt").read_text() == "zip"


def test_extract_archive_routes_to_tar(tmp_path):
    archive = _make_tar_gz({"file.txt": b"tar"})
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_archive(archive, dest)
    assert (dest / "file.txt").read_text() == "tar"


def test_extract_archive_rejects_unsupported(tmp_path):
    unknown = tmp_path / "archive.xyz"
    unknown.write_bytes(b"data")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(RemoteFetchError, match="不支持的归档格式"):
        _extract_archive(unknown, dest)


# ── fetch_from_url 集成 ─────────────────────────────────────────────


def test_fetch_from_url_rejects_empty():
    with pytest.raises(RemoteFetchError, match="URL 不能为空"):
        fetch_from_url("", Path("/tmp/out"))


def test_fetch_from_url_rejects_whitespace():
    with pytest.raises(RemoteFetchError, match="URL 不能为空"):
        fetch_from_url("   ", Path("/tmp/out"))


def test_fetch_from_url_rejects_unsupported():
    with pytest.raises(RemoteFetchError, match="不支持的 URL 格式"):
        fetch_from_url("https://example.com/not-a-repo", Path("/tmp/out"))


def test_fetch_from_url_github(tmp_path):
    """测试 GitHub URL 集成：mock 下载，验证解压。"""
    # 构造一个模拟 GitHub archive ZIP
    archive = _make_zip(
        {
            "repo-main/SKILL.md": b"# Test",
            "repo-main/agentmesh.asset.yaml": b"name: test\nkind: skill\n",
        }
    )

    dest = tmp_path / "out"

    with patch("agentmesh.services.remote_fetcher._download_file") as mock_dl:
        # mock 下载行为：将 archive 复制到 mock 下载目标
        def fake_download(url: str, target: Path) -> None:
            import shutil

            shutil.copy(archive, target)

        mock_dl.side_effect = fake_download

        result = fetch_from_url("https://github.com/owner/repo", dest)

    assert result == dest
    assert (dest / "SKILL.md").read_text() == "# Test"
    assert (dest / "agentmesh.asset.yaml").exists()


def test_fetch_from_url_direct_zip(tmp_path):
    """测试直接 ZIP URL 集成。"""
    archive = _make_zip(
        {
            "pkg/file.txt": b"content",
        }
    )

    dest = tmp_path / "out"

    with patch("agentmesh.services.remote_fetcher._download_file") as mock_dl:

        def fake_download(url: str, target: Path) -> None:
            import shutil

            shutil.copy(archive, target)

        mock_dl.side_effect = fake_download

        result = fetch_from_url("https://example.com/pkg.zip", dest)

    assert result == dest
    assert (dest / "file.txt").read_text() == "content"


def test_fetch_from_url_direct_tar_gz(tmp_path):
    """测试直接 tar.gz URL 集成。"""
    archive = _make_tar_gz(
        {
            "pkg/file.txt": b"tar-content",
        }
    )

    dest = tmp_path / "out"

    with patch("agentmesh.services.remote_fetcher._download_file") as mock_dl:

        def fake_download(url: str, target: Path) -> None:
            import shutil

            shutil.copy(archive, target)

        mock_dl.side_effect = fake_download

        result = fetch_from_url("https://example.com/pkg.tar.gz", dest)

    assert result == dest
    assert (dest / "file.txt").read_text() == "tar-content"


def test_fetch_from_url_creates_dest_dir(tmp_path):
    """目标目录不存在时应自动创建。"""
    archive = _make_zip({"file.txt": b"data"})
    dest = tmp_path / "new" / "nested" / "dir"

    with patch("agentmesh.services.remote_fetcher._download_file") as mock_dl:

        def fake_download(url: str, target: Path) -> None:
            import shutil

            shutil.copy(archive, target)

        mock_dl.side_effect = fake_download

        fetch_from_url("https://example.com/pkg.zip", dest)

    assert dest.is_dir()
    assert (dest / "file.txt").read_text() == "data"


def test_fetch_from_url_github_with_branch(tmp_path):
    """测试带分支的 GitHub URL。"""
    archive = _make_zip({"repo-dev/README.md": b"# Dev"})

    dest = tmp_path / "out"

    with patch("agentmesh.services.remote_fetcher._download_file") as mock_dl:

        def fake_download(url: str, target: Path) -> None:
            import shutil

            shutil.copy(archive, target)
            # 验证转换后的 URL 包含 dev 分支
            assert "dev.zip" in url

        mock_dl.side_effect = fake_download

        fetch_from_url("https://github.com/owner/repo/tree/dev", dest)

    assert (dest / "README.md").read_text() == "# Dev"
