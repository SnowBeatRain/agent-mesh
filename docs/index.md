# AgentMesh / SkillMesh

> 本地优先的 AI Agent 资产互通层。

---

**AgentMesh** 把 Hermes、OpenClaw、Codex、Claude Code、Cursor、Windsurf、Aider 等本机 Agent runtime 的 skills 收敛到中立 registry，再通过审计、diff、dry-run、apply、backup、rollback 和 package 导入导出，实现更安全的共享与迁移。

## 核心能力

<div class="grid cards" markdown>

- :material-shield-lock:{ .lg .middle } **安全优先**

    ---

    默认 dry-run 预览，显式 `--apply` 才执行写入；secrets 自动脱敏。

- :material-sync:{ .lg .middle } **资产互通**

    ---

    扫描并同步 Skills、Prompts、Memory、Models、Tools 等跨 Agent 资产。

- :material-package-variant:{ .lg .middle } **Package 管理**

    ---

    本地 skill 发布、版本化安装、ZIP 导出导入，基于 semver。

- :material-history:{ .lg .middle } **备份与回滚**

    ---

    自动 backup history，支持 rollback plan / rollback apply。

</div>

## 检测的 Agent Runtime

| Runtime | Skills | Memory | Models | Tools |
|---------|:------:|:------:|:------:|:-----:|
| Hermes  | ✅     | ✅     | ✅     | ✅    |
| OpenClaw | ✅    | ✅     | —      | —     |
| Codex   | ✅     | ✅     | —      | —     |
| Claude Code | ✅ | ✅     | —      | —     |
| Cursor  | ✅     | —      | —      | —     |
| Windsurf | ✅    | —      | —      | —     |
| Aider   | ✅     | —      | —      | —     |

## 快速安装

```bash
cd AgentMesh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
am --help
```

## 快速体验

```bash
# 扫描本机 skills
am skills scan

# dry-run 预览同步
am skills sync --dry-run

# 显式 apply
am skills sync --apply

# 查看 skill 审计
am skills audit
```

## 环境要求

- Python >= 3.10
- Linux / macOS / WSL / Windows PowerShell

## 文档导航

### 用户文档
- [快速开始](getting-started.md) — 安装到首次使用的完整流程
- [使用指南](usage-guide.md) — 全功能详解
- [CLI 参考](cli-reference.md) — 每个命令的参数与示例
- [高级工作台指南](advanced-dashboard-guide.md) — Web命令工作台使用指南

### 项目文档
- [路线图](roadmap-version-plan.md) — 未来规划
- [开源策略](opensource-strategy.md) — 开源范围分析与推荐
- [贡献指南](contributing.md) — 如何参与项目开发

### 开发文档
- [开发指南](../DEVELOPMENT_GUIDE.md) — 仓库结构与开发约定
- [项目指导](../CLAUDE.md) — AI Agent 工作指南
