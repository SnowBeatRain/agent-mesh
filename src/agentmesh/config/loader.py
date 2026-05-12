from datetime import datetime, timezone
from pathlib import Path

# 各 Agent runtime 的 skill 目录路径片段（相对 home）
AGENT_TARGETS: dict[str, tuple[str, ...]] = {
    "hermes": (".hermes", "skills", "custom"),
    "openclaw": (".openclaw", "workspace", "skills"),
    "codex": (".codex", "skills"),
    "cursor": (".cursor", "rules"),
    "windsurf": (".windsurf", "rules"),
    # aider 原生只有单文件 .aider.conventions.md；此处新增一个 skills 目录约定，
    # 用户若选择启用 aider 作为 sync 目标，AgentMesh 会写入该目录，并由用户决定
    # 是否通过 `.aider.conf.yml` 中的 read 指令引入这些 skill 文档。
    "aider": (".aider", "skills"),
    # Claude Code 原生使用 plugin 机制；AgentMesh 保持 export-only：
    # AGENT_TARGETS 中登记其 plugin 路径仅用于 diff/enable 规划，
    # sync --apply 会被 EXPORT_ONLY_TARGETS 拦截并引导到 `skills export claude-code`。
    "claude-code": (".claude", "plugins"),
}

# Export-only 目标：出现在 AGENT_TARGETS 以便扫描/diff/enable 统一矩阵，
# 但 sync --apply 必须被拦截，由 `skills export <target>` 的 package 导出流程处理。
EXPORT_ONLY_TARGETS: frozenset[str] = frozenset({"claude-code"})


def user_home() -> Path:
    return Path.home()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def resolve_agentmesh_home(registry: str | None = None) -> Path:
    return Path(registry).expanduser().resolve() if registry else user_home() / ".agentmesh"


def registry_root(agentmesh_home: Path) -> Path:
    return agentmesh_home / "registry"


def registry_skills_root(agentmesh_home: Path) -> Path:
    return agentmesh_home / "skills"


def legacy_registry_skills_root(agentmesh_home: Path) -> Path:
    return registry_root(agentmesh_home) / "assets" / "skills"


def ensure_layout(home: Path) -> list[Path]:
    dirs = [
        home,
        registry_root(home),
        registry_skills_root(home),
        home / "generated",
        home / "backups",
        home / "logs",
        home / "locks",
        home / "state",
    ]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
    config = home / "config.yaml"
    if not config.exists():
        config.write_text("schema: agentmesh.config/v1\ndefault_mode: copy\n", encoding="utf-8")
    return dirs
