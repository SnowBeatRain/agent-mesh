from pathlib import Path


class PathViolation(ValueError):
    pass


class PathGuard:
    def __init__(self, registry_root: Path):
        self.registry_root = registry_root.expanduser().resolve()

    def ensure_inside(self, root: Path, candidate: Path) -> Path:
        resolved_root = root.expanduser().resolve()
        resolved_candidate = candidate.expanduser().resolve()
        if resolved_root != resolved_candidate and resolved_root not in resolved_candidate.parents:
            raise PathViolation(f"路径越界：{resolved_candidate} 不在 {resolved_root} 内")
        return resolved_candidate

    def ensure_writable_target(self, target: Path) -> Path:
        expanded = target.expanduser()
        resolved = expanded.resolve()
        parts = set(expanded.parts) | set(resolved.parts)
        if ".system" in parts and ".codex" in parts:
            raise PathViolation("禁止写入 Codex .system 目录")
        if "bundled" in parts or "official" in parts:
            raise PathViolation("禁止覆盖系统或官方资产目录")
        return resolved
