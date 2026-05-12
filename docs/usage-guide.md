# AgentMesh 使用教程

> 面向第一次使用和继续开发 AgentMesh 的完整上手指南。本文档以当前仓库实现为准，覆盖安装、初始化、扫描导入、审计、同步、回滚、Package Registry、MemoryMesh、ModelMesh、ToolMesh、PromptMesh（含版本管理与多 target）、Runtime Auto-Load hook、Local API contract 和常见排查。

## 1. AgentMesh 是什么

AgentMesh 是一个**本地优先的 AI Agent 资产互通层**。当前版本 `0.1.0` 的核心是 SkillMesh：把本机不同 Agent runtime 里的 skills 收敛到一个中立 registry，再通过审计、diff、dry-run、apply、backup、rollback 等机制，安全地同步或导出到目标 runtime。

当前重点支持的 runtime：

- Hermes
- OpenClaw
- Codex
- Claude Code

当前主要资产类型：

- Skills：最完整，支持扫描/导入/审计/同步/回滚。
- Prompts：PromptMesh，含版本管理、多 target、冲突解决策略。
- Memory：MemoryMesh，跨 Agent 记忆资产扫描/导入/diff。
- Model：ModelMesh，模型配置扫描/diff。
- Tool：ToolMesh，工具配置扫描/diff。
- Package Registry：本地 package 发布/安装/卸载。
- Runtime LoadPlan：含 auto-load hook 与 stale 检测。

## 2. 当前能力边界

### 已可用

- 检测本机 Agent runtime。
- 扫描 Hermes / OpenClaw / Codex / Claude Code skills。
- 默认排除 Codex `.system` 受保护目录。
- 将用户 skills 导入 AgentMesh registry。
- 对 registry skills 做基础审计。
- 查看 skill 列表、重复候选、冲突和目录级 diff。
- 重建 registry skill index。
- dry-run 同步计划。
- 显式 `--apply` 后执行受保护写入。
- backup / history / rollback plan / rollback apply。
- 导出 Claude Code package，但不会自动安装 Claude Code plugin。
- 导出 / 导入 AgentMesh ZIP package。
- Package Registry：本地 package 发布、安装、卸载和列表。
- MemoryMesh：扫描、导入、列表、跨 Agent diff 和同步。
- ModelMesh：扫描、diff、列表和同步。
- ToolMesh：扫描、diff、列表和同步。
- Package Registry：本地 package 发布、安装、卸载、列表，支持远端 URL 安装（GitHub/ZIP/tar.gz）。
- PromptMesh：add / list / import-live / enable / status / disable / update / versions，支持多 target、冲突解决策略。
- Runtime LoadPlan：生成、持久化、校验、dry-run exec-plan。
- Runtime Auto-Load hook：`runtime check-stale` 轻量过期检测。
- Runtime update：重新生成 LoadPlan 并重新渲染。
- Local API HTTP server（`am local serve`）与浏览器 Dashboard。

### 尚未完成

- 生产级 Runtime Auto-Load。
- 目标 Agent 在真实会话启动时原生消费 LoadPlan。
- 云同步、在线 marketplace。
- 远程 package registry（中心化包仓库）。

## 3. 安装

项目要求：

```text
Python >= 3.10
```

### 推荐：项目内虚拟环境

Linux / macOS / WSL：

```bash
cd /path/to/AgentMesh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
am --help
agentmesh --help
```

Windows PowerShell：

```powershell
cd "E:\path\to\AgentMesh"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
am --help
agentmesh --help
```

### 用户级安装

Linux / macOS / WSL：

```bash
cd /path/to/AgentMesh
python3 -m pip install --user -e ".[dev]"
export PATH="$HOME/.local/bin:$PATH"
am --help
```

Windows PowerShell：

```powershell
cd "E:\path\to\AgentMesh"
python -m pip install --user -e ".[dev]"
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))"
$env:Path = "$scripts;$env:Path"
am --help
```

### 确认命令来自当前仓库

如果你在多个 worktree 或多个 Python 版本之间切换，请确认 `am` 使用的是当前仓库代码：

```bash
python3 - <<'PY'
import agentmesh.cli.main as m
print(m.__file__)
PY
```

输出应指向当前项目的：

```text
.../AgentMesh/src/agentmesh/cli/main.py
```

如果 `am --help` 看不到新命令，通常是 console script 仍指向旧 Python 或旧 editable install。解决方式：

```bash
python3 -m pip install -e ".[dev]"
which am
head -n 1 "$(which am)"
```

必要时优先激活项目 `.venv` 后再运行 `am`。

## 4. 快速开始：安全试用流程

建议先用临时 registry 体验，不要直接写入真实 runtime：

```bash
cd /path/to/AgentMesh
. .venv/bin/activate

am init --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh
am doctor --registry .tmp-agentmesh
am agents list --json
am skills scan --registry .tmp-agentmesh --agent all --json
am skills import hermes --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh
am audit all --registry .tmp-agentmesh
am skills sync --registry .tmp-agentmesh --to hermes,openclaw,codex --dry-run
```

这条流程中只有两类写入：

- `am init`：写入 `.tmp-agentmesh` registry。
- `am skills import`：把扫描到的 skills 复制到 `.tmp-agentmesh` registry。

不会写入目标 runtime，因为同步使用了 `--dry-run`。

## 5. 核心概念

| 概念 | 示例 | 说明 |
| --- | --- | --- |
| registry | `.tmp-agentmesh`、`~/.agentmesh` | AgentMesh 的中立资产库。 |
| runtime | `hermes`、`openclaw`、`codex`、`claude-code` | 本机已有 Agent。 |
| skill | `SKILL.md` 目录 | 当前 MVP 的主要共享资产。 |
| memory | `.hermes/` 下的记忆文件 | MemoryMesh 的跨 Agent 记忆资产。 |
| model config | Agent 模型配置 | ModelMesh 的模型配置互通。 |
| tool config | Agent 工具配置 | ToolMesh 的工具配置互通。 |
| scan | `am skills scan` / `am memory scan` / `am model scan` / `am tool scan` | 只读扫描本机 runtime。 |
| import | `am skills import` / `am memory import` | 写入 registry，不写目标 runtime。 |
| audit | `am audit all` | 检查 secrets、危险脚本和平台路径引用。 |
| diff | `am skills diff` / `am memory diff` / `am model diff` / `am tool diff` | 比较 registry 与目标 runtime 中的同名资产。 |
| sync dry-run | `am skills sync --dry-run` | 只生成计划。 |
| sync apply | `am skills sync --apply` | 显式写入目标 runtime。 |
| package | `am skills export agentmesh` | 离线迁移或备份 skills。 |
| package registry | `am package publish` / `am package install` | 本地 package 版本管理。 |
| prompt version | `am prompts update` / `am prompts versions` | PromptMesh 版本管理。 |
| conflict strategy | `--conflict-strategy backup/skip/force` | PromptMesh 冲突解决策略。 |
| LoadPlan | `am runtime load-plan` | Runtime Auto-Load 的计划文件。 |
| check-stale | `am runtime check-stale` | 轻量级 LoadPlan 过期检测。 |

## 6. 初始化与诊断

```bash
am init --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh --json
am local status --registry .tmp-agentmesh --json
am doctor --registry .tmp-agentmesh
am doctor --registry .tmp-agentmesh --json
am agents list
am agents list --json
am agents contract --json
```

说明：

- `init` 创建 registry 布局。
- `overview` 给出本机轻量总览，包括 Local API contract、Runtime alpha 状态和安全边界。
- `local status` 是 `overview` 的 local 子命令视角。
- `doctor` 用于环境诊断。
- `agents list` 只检测本机 runtime，检测基于用户 home，不把 `--registry` 当成 runtime root。
- `agents contract` 输出 adapter contract 声明。

## 7. Skills：扫描、导入、查看

### 扫描

```bash
am skills scan --registry .tmp-agentmesh --agent all
am skills scan --registry .tmp-agentmesh --agent hermes --json
```

支持的 agent 参数：

```text
hermes
openclaw
codex
claude-code
all
```

扫描是只读操作，不写 registry，也不写目标 runtime。

### 导入

```bash
am skills import hermes --registry .tmp-agentmesh
am skills import openclaw --registry .tmp-agentmesh
am skills import codex --registry .tmp-agentmesh
am skills import all --registry .tmp-agentmesh
```

导入会写入：

```text
<registry>/registry/assets/skills/<name>/
```

典型文件：

```text
SKILL.md
agentmesh.asset.yaml
agentmesh.skill.yaml
provenance.yaml
references/
scripts/
templates/
assets/
```

Codex `.system` 受保护，不会被扫描、导入或写入。

### 查看列表

```bash
am skills list --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh --json
am skills list --registry .tmp-agentmesh --duplicates
am skills list --registry .tmp-agentmesh --conflicts --target hermes
```

### 查看详情

```bash
am skills show demo-skill --registry .tmp-agentmesh
am skills show demo-skill --registry .tmp-agentmesh --json
```

`skills show` 输出 provenance 和风险摘要时会做脱敏，不应泄露疑似密钥正文。

### 重建 index

```bash
am skills reindex --registry .tmp-agentmesh
am skills reindex --registry .tmp-agentmesh --json
```

输出文件：

```text
<registry>/registry/index/skills.json
```

CLI JSON envelope：

```text
agentmesh.skills-reindex/v1
```

内部 index schema：

```text
agentmesh.registry-skills-index/v1
```

## 8. Skills：验证、审计、diff

### 验证 registry skill 结构

```bash
am skills validate --registry .tmp-agentmesh
am skills validate --registry .tmp-agentmesh --json
am skills validate --registry .tmp-agentmesh --native --target hermes --json
```

说明：

- 普通 `validate` 检查 manifest、entrypoint、命名等基础规范。
- `--native` 会尝试调用目标 runtime 的原生验证器。
- 找不到原生命令时返回 `skipped`，不等于 AgentMesh 自身失败。

### 审计

```bash
am audit all --registry .tmp-agentmesh
am audit all --registry .tmp-agentmesh --json
am audit secrets --registry .tmp-agentmesh --json
am audit scripts --registry .tmp-agentmesh --json
am audit platform-refs --registry .tmp-agentmesh --json
```

审计关注：

- 疑似 secrets / token / key。
- 危险脚本模式。
- 平台特定路径引用。

审计和 diff 中的疑似密钥必须 redacted。

### Diff

```bash
am skills diff demo-skill --registry .tmp-agentmesh --target hermes
am skills diff demo-skill --registry .tmp-agentmesh --target codex --json
```

diff 等级：

| 等级 | 名称 | 含义 |
| --- | --- | --- |
| 0 | IDENTICAL | 内容一致。 |
| 1 | METADATA_ONLY | 仅 manifest 或 frontmatter 等元数据不同。 |
| 2 | CONTENT_CHANGED | `SKILL.md` 正文不同。 |
| 3 | STRUCTURE_CHANGED | 目标缺失或结构缺失。 |
| 4 | MANUAL_REVIEW | references/scripts/templates/assets 文件树变化。 |
| 5 | SECURITY_BLOCK | 存在安全阻断，需要人工处理。 |

## 9. Skills：同步到目标 runtime

### 永远先 dry-run

```bash
am skills sync --registry .tmp-agentmesh --to hermes --dry-run
am skills sync --registry .tmp-agentmesh --to hermes,openclaw,codex --dry-run
am skills sync --registry .tmp-agentmesh --to codex --dry-run --json
```

### 确认后再 apply

```bash
am skills sync --registry .tmp-agentmesh --to hermes --apply
```

`--apply` 会执行真实写入，并包含基础保护：

- PathGuard。
- backup。
- lock drift 检测。
- 失败 rollback。
- 安全审计阻断。

### 冲突处理

```bash
am skills sync --registry .tmp-agentmesh --to hermes --apply --allow-conflicts
```

注意：

- `--allow-conflicts` 只能绕过非安全类内容/文件树冲突。
- 不能绕过 secret/security hard block。
- 不能绕过 drift block。
- Claude Code 当前是 `export-only`，不作为 `skills sync --apply` 目标。

### Symlink 模式

```bash
am skills sync --registry .tmp-agentmesh --to codex --mode symlink --apply --confirm
```

symlink apply 必须显式 `--confirm`，并会写 sidecar lock。已有非托管 symlink、普通文件目标或内容冲突会阻断。

## 10. 启用矩阵：skills enable / disable / status

你可以把某个 skill 标记为长期启用到某些 runtime：

```bash
am skills enable demo-skill --registry .tmp-agentmesh --target hermes,codex
am skills status demo-skill --registry .tmp-agentmesh --json
am skills disable demo-skill --registry .tmp-agentmesh --target codex
am skills sync --registry .tmp-agentmesh --enabled --dry-run
```

这会写入 registry state，而不是立即写目标 runtime。真正投影仍由 `skills sync` 完成。

## 11. Backup、History 与 Rollback

### 查看历史和备份

```bash
am history list --registry .tmp-agentmesh
am history list --registry .tmp-agentmesh --json
am backup list --registry .tmp-agentmesh
am backup list --registry .tmp-agentmesh --json
```

### 生成 rollback plan

```bash
am rollback plan <backup-ref> --registry .tmp-agentmesh
am rollback plan <backup-ref> --registry .tmp-agentmesh --json
```

`backup-ref` 支持：

- `backup_id`
- `history_id`
- `<registry>/backups/` 内的 backup path

路径必须解析后仍位于 `<registry>/backups/` 内，否则会返回 unsafe path hard block。

### 执行 rollback

```bash
am rollback apply <backup-ref> --registry .tmp-agentmesh --confirm
am rollback apply <backup-ref> --registry .tmp-agentmesh --confirm --json
```

说明：

- `rollback plan` 只读，不写 target。
- `rollback apply` 必须显式 `--confirm`。
- `managed_drift`、`unmanaged`、`unsafe_path`、backup 缺失等 hard block 不能通过 CLI 参数绕过。
- symlink rollback 使用独立语义，不能悄悄覆盖 unmanaged symlink。

## 12. Package：离线导出、检查、导入

### 导出 AgentMesh package

```bash
am skills export agentmesh --registry .tmp-agentmesh --out ./agentmesh-package.zip --json
```

### 只读检查 package

```bash
am package inspect ./agentmesh-package.zip
am package inspect ./agentmesh-package.zip --json
am package verify ./agentmesh-package.zip
am package verify ./agentmesh-package.zip --json
```

说明：

- `package inspect` 只查看 ZIP 内容，不需要 registry。
- `package verify` 校验 manifest 文件清单与 checksum。
- verify 不等于 audit / policy 安全审查。

### 导入 package

```bash
am skills import-package ./agentmesh-package.zip --registry .tmp-agentmesh-2 --dry-run --json
am skills import-package ./agentmesh-package.zip --registry .tmp-agentmesh-2 --apply
```

导入会拒绝：

- `../` path traversal。
- 绝对路径。
- Windows drive path。
- symlink entry。
- 同名不同内容且未处理的冲突。
- audit/policy hard block。

## 13. Package Registry：本地 package 版本管理

Package Registry 提供本地 skill package 的发布、安装、卸载和列表功能，用于版本化管理。

### 发布 package

```bash
am package publish my-skill 1.0.0 --registry .tmp-agentmesh
am package publish my-skill 1.1.0 --registry .tmp-agentmesh --force --json
```

说明：

- 版本号使用 semver 格式。
- `--force` 覆盖已存在的同名版本。
- 发布后 package 存储在 `<registry>/packages/<name>/<version>/`。

### 安装 package

**从本地 registry 安装：**

```bash
am package install my-skill --registry .tmp-agentmesh
am package install my-skill 1.0.0 --registry .tmp-agentmesh --json
am package install my-skill --registry .tmp-agentmesh --resolve-deps
```

**从远端 URL 安装：**

```bash
# GitHub 仓库（自动转 clone 或 ZIP 下载）
am package install https://github.com/user/skill --registry .tmp-agentmesh --yes

# 指定分支
am package install https://github.com/user/skill --branch dev --registry .tmp-agentmesh --yes

# 直接 ZIP/tar.gz URL
am package install https://example.com/skill.zip --registry .tmp-agentmesh --yes

# 省略协议前缀
am package install github.com/user/skill --registry .tmp-agentmesh --yes
```

说明：

- 不指定版本时安装最新版。
- `--resolve-deps` 自动解析并安装依赖。
- `--force` 覆盖 registry 中已有的同名 skill。
- 内容相同时自动跳过，避免重复写入。
- **远端安装**：支持 GitHub URL（自动转换 clone/ZIP）、直接 ZIP/tar.gz URL。
- GitHub URL 会自动尝试 `git clone`（浅克隆），失败后降级为 ZIP 下载。
- `--branch` 指定 Git 分支（默认 `main`）。
- `--yes` 跳过交互确认，适用于脚本和自动化场景。
- 下载内容包含安全校验：路径穿越防护、zip bomb 检测。

### 卸载 package

```bash
am package uninstall my-skill --registry .tmp-agentmesh
am package uninstall my-skill --registry .tmp-agentmesh --json
```

### 列出已发布 package

```bash
am package list --registry .tmp-agentmesh
am package list --registry .tmp-agentmesh --json
```

输出包含 package 名称、最新版本和所有可用版本。

## 14. MemoryMesh：跨 Agent 记忆资产互通

MemoryMesh 支持扫描、导入、列表和跨 Agent 记忆文件比较。

### 扫描记忆

```bash
am memory scan --agent all
am memory scan --agent hermes --json
```

扫描是只读操作，读取本机 Agent 的记忆文件目录。

### 导入记忆

```bash
am memory import hermes --registry .tmp-agentmesh
am memory import all --registry .tmp-agentmesh --dry-run
```

说明：

- `--dry-run` 预览导入结果而不实际写入。
- 记忆资产导入到 `<registry>/memories/`。
- 同名不同内容会抛出 `MemoryImportConflict` 错误。

### 列出已导入记忆

```bash
am memory list --registry .tmp-agentmesh
am memory list --registry .tmp-agentmesh --json
```

### 跨 Agent diff

比较两个 Agent 的记忆文件差异：

```bash
am memory diff hermes openclaw --registry .tmp-agentmesh
am memory diff hermes openclaw --name shared-memory.md --registry .tmp-agentmesh --json
```

说明：

- 不指定 `--name` 时比较全部记忆文件，输出 only_in_a / only_in_b / different / identical 摘要。
- 指定 `--name` 时比较单个文件，输出 diff level 和详情。

### 同步记忆到目标 Agent

```bash
am memory sync --to hermes --registry .tmp-agentmesh
am memory sync --to hermes --registry .tmp-agentmesh --dry-run
am memory sync --to hermes --registry .tmp-agentmesh --apply --yes
```

说明：

- `--to` 指定目标 Agent（`hermes`、`openclaw`、`codex`、`claude-code`）。
- `--dry-run`（默认）预览同步操作，显示哪些文件将被写入/覆盖/跳过。
- `--apply` 实际执行写入。
- `--yes` 跳过交互确认（适用于脚本/自动化）。
- 只同步 registry 中已导入的记忆条目，不触发扫描。
- 内容相同的文件自动跳过（`skip`），避免无效写入。

## 15. ModelMesh：模型配置互通

ModelMesh 扫描各 Agent 的模型配置并比较差异。

### 扫描模型配置

```bash
am model scan --registry .tmp-agentmesh
am model scan --registry .tmp-agentmesh --json
```

输出包含 agent 名称、默认模型、provider 和 context_length。

### 比较模型配置差异

```bash
am model diff --registry .tmp-agentmesh
am model diff --registry .tmp-agentmesh --json
```

比较所有已扫描 Agent 的模型配置字段差异，输出逐字段对比表。

### 列出模型配置概览

```bash
am model list --registry .tmp-agentmesh
am model list --registry .tmp-agentmesh --json
```

### 同步模型配置到目标 Agent

```bash
am model sync --to hermes --registry .tmp-agentmesh
am model sync --to hermes --registry .tmp-agentmesh --dry-run
am model sync --to hermes --registry .tmp-agentmesh --apply --yes
```

说明：

- `--to` 指定目标 Agent（`hermes`、`openclaw`、`codex`、`claude-code`）。
- `--dry-run`（默认）预览同步操作。
- `--apply` 实际执行写入。
- `--yes` 跳过交互确认。
- 将扫描到的源 Agent 模型配置写入目标 Agent 的 config 文件。

## 16. ToolMesh：工具配置互通

ToolMesh 扫描各 Agent 的工具配置并比较差异。

### 扫描工具配置

```bash
am tool scan --registry .tmp-agentmesh
am tool scan --registry .tmp-agentmesh --json
```

输出包含 agent 名称、profile、已启用工具列表和已禁用工具列表。

### 比较工具配置差异

```bash
am tool diff --registry .tmp-agentmesh
am tool diff --registry .tmp-agentmesh --json
```

比较差异类型包括：`only_in_a`（仅 A 有）、`only_in_b`（仅 B 有）、`disabled_in_a`（A 中禁用）、`disabled_in_b`（B 中禁用）。

### 列出工具配置概览

```bash
am tool list --registry .tmp-agentmesh
am tool list --registry .tmp-agentmesh --json
```

### 同步工具配置到目标 Agent

```bash
am tool sync --to hermes --registry .tmp-agentmesh
am tool sync --to hermes --registry .tmp-agentmesh --dry-run
am tool sync --to hermes --registry .tmp-agentmesh --apply --yes
```

说明：

- `--to` 指定目标 Agent（`hermes`、`openclaw`、`codex`、`claude-code`）。
- `--dry-run`（默认）预览同步操作。
- `--apply` 实际执行写入。
- `--yes` 跳过交互确认。
- 将扫描到的源 Agent 工具配置写入目标 Agent 的 config 文件。

## 17. Claude Code 导出

Claude Code 当前是 `export-only`：

```bash
am skills export claude-code --registry .tmp-agentmesh --out .tmp-claude-package --json
```

AgentMesh 不会自动安装到 `~/.claude/plugins`，需要你在目标工具中按其原生方式处理导出的 package。

## 18. PromptMesh：版本管理、多 target 与冲突解决

### 添加 prompt

```bash
am prompts add review-prompt --registry .tmp-agentmesh --name "Review Prompt" --from ./review.md
am prompts list --registry .tmp-agentmesh
am prompts list --registry .tmp-agentmesh --json
```

### 从 live prompt 导入

```bash
am prompts import-live --registry .tmp-agentmesh --target codex --json
```

典型 live prompt 文件包括：

- Codex：`AGENTS.md`
- Claude Code：`CLAUDE.md`

### 版本管理

每次 `prompts update` 会自动创建新版本快照：

```bash
am prompts update review-prompt --registry .tmp-agentmesh --content-file ./review-v2.md
am prompts update review-prompt --registry .tmp-agentmesh --content-file ./review-v3.md --name "Review V3"
```

查看版本历史：

```bash
am prompts versions review-prompt --registry .tmp-agentmesh
am prompts versions review-prompt --registry .tmp-agentmesh --json
```

说明：

- 每次 update 递增版本号，保存到 `<registry>/prompts/<id>/versions/` 目录。
- 内容、名称和描述均未修改时会报错拒绝。
- 版本快照包含 content_hash 和时间戳。

### 启用 prompt（单 target）

```bash
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --dry-run
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --apply
```

### 启用 prompt（多 target）

```bash
am prompts enable review-prompt --registry .tmp-agentmesh --targets codex,hermes,openclaw --dry-run
am prompts enable review-prompt --registry .tmp-agentmesh --targets codex,hermes --apply
```

说明：

- `--targets` 接受逗号分隔的多个目标 runtime。
- 每个 target 独立处理冲突和快照。

### 冲突解决策略

```bash
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --apply --conflict-strategy backup
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --apply --conflict-strategy skip
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --apply --conflict-strategy force
```

策略说明：

| 策略 | 行为 |
| --- | --- |
| `backup` | 默认策略。存在冲突时先备份 live 文件，再覆盖写入。 |
| `skip` | 存在冲突时跳过写入，返回 `skipped: true`。 |
| `force` | 无条件覆盖写入，不做备份。 |

### 查看和禁用 target prompt 状态

```bash
am prompts status --target codex --registry .tmp-agentmesh
am prompts status --target codex --registry .tmp-agentmesh --json
am prompts disable --target codex --registry .tmp-agentmesh --dry-run
am prompts disable --target codex --registry .tmp-agentmesh --apply
am prompts disable --target codex --registry .tmp-agentmesh --apply --json
```

说明：

- `prompts disable --apply` 标记 target state 为 disabled，但不删除 live prompt 文件。
- 如果 live prompt 非空且和 state hash 不一致，会先回填当前 live 内容为 snapshot，避免手工修改丢失。

## 19. Runtime Bootstrap alpha

Runtime 命令用于验证未来“直接从 AgentMesh registry 加载共享资产”的方向。当前仍是 alpha，不代表目标 Agent 已经在真实会话启动时原生加载共享 skill。

### 生成并持久化 LoadPlan

```bash
am runtime load-plan --target openclaw --registry .tmp-agentmesh --json
```

该命令返回 CLI envelope：

```text
agentmesh.runtime-load-plan-response/v1
```

实际 LoadPlan 位于：

```text
data.plan
```

并写入：

```text
<registry>/state/runtime-load-plans/<target>.json
```

LoadPlan domain schema：

```text
agentmesh.runtime-load-plan/v1
```

### 查看环境变量

```bash
am runtime env --target openclaw --registry .tmp-agentmesh
```

### 验证 runtime 状态

```bash
am runtime validate --target openclaw --registry .tmp-agentmesh --json
```

### Bootstrap shim

先 dry-run：

```bash
am runtime bootstrap --target openclaw --registry .tmp-agentmesh --dry-run
```

确认后 apply：

```bash
am runtime bootstrap --target openclaw --registry .tmp-agentmesh --apply --json
```

`--apply` 会写入轻量 `agentmesh-loader` shim，并生成读取 LoadPlan 的入口，但仍不等于生产级 Runtime Auto-Load。

### Exec-plan dry-run reader

```bash
am runtime exec-plan --load-plan .tmp-agentmesh/state/runtime-load-plans/openclaw.json --json
```

它只读取并校验 LoadPlan，然后渲染 dry-run actions，不注入目标 runtime。

### 状态与禁用

```bash
am runtime status --target openclaw --registry .tmp-agentmesh --json
am runtime disable --target openclaw --registry .tmp-agentmesh --dry-run
am runtime disable --target openclaw --registry .tmp-agentmesh --apply --json
```

`runtime status` 会检测 LoadPlan 是否过期：当 registry 中 skills 文件的修改时间晚于 LoadPlan 的 `generated_at` 时，返回 `plan_stale: true` 并显示黄色警告，提示你需要运行 `runtime update --apply` 刷新计划。

`runtime disable --apply` 会标记 target state 为 disabled，移除已渲染的文件，并将操作记录写入 Runtime Audit 日志。

### Runtime update

```bash
am runtime update --target openclaw --registry .tmp-agentmesh --dry-run
am runtime update --target openclaw --registry .tmp-agentmesh --apply --json
```

`runtime update` 会重新生成 LoadPlan 并重新渲染 registry skills 为目标 Agent 原生格式。默认为 dry-run；必须显式 `--apply` 才执行写入。适用于以下场景：

- registry 中的 skills 发生了变更（新增、删除、内容修改）。
- `runtime status` 报告 `plan_stale: true`。
- 手动修改了 LoadPlan 或渲染输出后需要重建。

### Runtime Auto-Load hook：check-stale

`runtime check-stale` 提供轻量级 LoadPlan 过期检测，适合在 shell hook 或启动脚本中调用：

```bash
am runtime check-stale --target openclaw --registry .tmp-agentmesh
am runtime check-stale --target openclaw --registry .tmp-agentmesh --json
```

输出内容：

- `stale`：是否过期。
- `skills_added`：registry 中新增的 skills。
- `skills_removed`：registry 中移除的 skills。
- `content_changed`：内容变更的 skills。

建议用法：在 Agent 会话启动前调用 `check-stale`，若返回 `stale` 则提示用户运行 `runtime update --apply` 刷新。

### Runtime Audit

`runtime bootstrap --apply` 和 `runtime disable --apply` 操作会自动写入审计日志到：

```text
<registry>/state/runtime-audit/<timestamp>-<operation>.json
```

每条审计记录包含操作类型（`bootstrap` / `disable`）、target、LoadPlan 引用、渲染文件列表和时间戳。可用于追溯 runtime 操作历史。

## 20. Local API HTTP Server 与 Dashboard

当前 Local API 已实现完整的 HTTP server（`am local serve`），默认绑定 `127.0.0.1:9090`，localhost-only：

```bash
am local serve --port 9090 --registry .tmp-agentmesh
# 浏览器访问 http://127.0.0.1:9090/
```

底层 handler 仍通过 Python 函数 `agentmesh.local_api.service.handle_readonly_request(method, path)` 处理请求，`local_api/server.py` 封装为 HTTP server。

支持的只读 endpoint：

```text
GET /health
GET /doctor
GET /agents
GET /overview
GET /skills
GET /history
GET /backups
GET /runtime/status
```

返回 envelope：

```text
agentmesh.local-api-response/v1
```

Dashboard 自动在根路径 `/` 和 `/dashboard` 提供。非 GET 方法统一返回方法不允许错误。所有 handler 已应用 path redaction，响应值中的用户本地文件路径会被脱敏处理。

## 21. JSON 输出约定

面向自动化的命令通常支持 `--json`。常见 envelope 字段：

```json
{
  "schema": "agentmesh.<command>/v1",
  "command": "command name",
  "status": "ok",
  "data": {},
  "summary": {},
  "warnings": [],
  "errors": [],
  "next_steps": []
}
```

常用 JSON 命令：

```bash
am overview --registry .tmp-agentmesh --json
am local status --registry .tmp-agentmesh --json
am doctor --registry .tmp-agentmesh --json
am agents list --json
am agents contract --json
am skills scan --registry .tmp-agentmesh --agent all --json
am skills list --registry .tmp-agentmesh --json
am skills show demo-skill --registry .tmp-agentmesh --json
am skills reindex --registry .tmp-agentmesh --json
am audit all --registry .tmp-agentmesh --json
am skills sync --registry .tmp-agentmesh --to codex --dry-run --json
am memory scan --agent all --json
am memory list --registry .tmp-agentmesh --json
am memory diff hermes openclaw --registry .tmp-agentmesh --json
am model scan --registry .tmp-agentmesh --json
am model diff --registry .tmp-agentmesh --json
am tool scan --registry .tmp-agentmesh --json
am tool diff --registry .tmp-agentmesh --json
am package list --registry .tmp-agentmesh --json
am package publish my-skill 1.0.0 --registry .tmp-agentmesh --json
am prompts versions review-prompt --registry .tmp-agentmesh --json
am runtime load-plan --target openclaw --registry .tmp-agentmesh --json
am runtime check-stale --target openclaw --registry .tmp-agentmesh --json
```

注意：少数历史命令仍可能保留 raw JSON 输出，后续会逐步统一。写自动化脚本时请以当前命令实际 schema 为准。

## 22. 安全原则

1. **默认不写目标 runtime**：同步前先 `--dry-run`。
2. **真实写入必须显式 `--apply`**。
3. **Codex `.system` 受保护**：不扫描、不导入、不写入。
4. **Claude Code export-only**：不会自动安装 plugin。
5. **疑似 secrets 必须 redacted**。
6. **hard block 不可绕过**：secret/security/drift/unsafe path 等阻断不能靠 `--allow-conflicts` 跳过。
7. **Package 导入先 dry-run**：verify 只证明 checksum，不证明安全。
8. **Runtime bootstrap alpha 谨慎 apply**：优先 dry-run，确认 loader 目录受 AgentMesh 管理后再写。

## 23. 常见问题排查

### `am` 找不到

```bash
. .venv/bin/activate
am --help
```

或检查用户级脚本目录：

```bash
python3 -m pip show agentmesh
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

### `am` 看不到新命令

可能是 console script 指向旧 Python：

```bash
which am
head -n 1 "$(which am)"
python3 - <<'PY'
import agentmesh.cli.main as m
print(m.__file__)
PY
```

重新安装当前 worktree：

```bash
python3 -m pip install -e ".[dev]"
```

### `agents list` 没发现某个 runtime

```bash
am agents list --json
am doctor --registry .tmp-agentmesh --json
```

确认该 runtime 是否安装，以及其用户目录是否符合当前检测规则。

### `skills scan` 没结果

可能原因：

- runtime 中没有用户 skills。
- 只有被保护的系统 skills。
- runtime 路径未被检测到。

排查：

```bash
am agents list --json
am skills scan --registry .tmp-agentmesh --agent all --json
```

### `sync --apply` 被阻断

先看审计和 diff：

```bash
am audit all --registry .tmp-agentmesh --json
am skills list --registry .tmp-agentmesh --conflicts --target hermes --json
am skills diff demo-skill --registry .tmp-agentmesh --target hermes
```

### JSON 不适合人读

去掉 `--json`：

```bash
am doctor --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh
am audit all --registry .tmp-agentmesh
```

## 24. 开发与质量检查

### 日常局部测试

```bash
python3 -m pytest tests/test_local_api.py -q
python3 -m pytest tests/test_runtime_commands.py -q
python3 -m pytest tests/test_registry_reindex.py -q
ruff check src/ tests/
ruff format --check src/ tests/
```

### 阶段收尾完整质量门

```bash
python3 -m pytest tests -q
ruff check src/ tests/
ruff format --check src/ tests/
git diff --check
```

### 提交前检查状态

```bash
git status --short
git diff --stat
git diff --check
```

如果存在 `.hermes/`、`.tmp-*`、review 输出目录等临时文件，确认不要误提交。

## 25. 推荐新用户学习路径

1. 读本文档前 6 节，理解 AgentMesh / registry / runtime / dry-run。
2. 用 `.tmp-agentmesh` 跑通快速开始。
3. 用 `am audit all` 和 `am skills sync --dry-run` 理解安全边界。
4. 尝试 `am memory scan`、`am model scan`、`am tool scan` 了解新增资产互通能力。
5. 只在确认计划后，对单个目标 runtime 执行 `--apply`。
6. 学会 `history list`、`backup list`、`rollback plan`，再扩大同步范围。
7. 尝试 `am package publish` / `am package install` 体验本地 package 版本管理。
8. 用 `am prompts update` / `am prompts versions` 体验 PromptMesh 版本管理。
9. 对 Claude Code 优先使用 export package，不期待自动安装。
10. 对 Runtime Bootstrap 只按 alpha 功能试验，用 `am runtime check-stale` 做过期检测。

## 26. 一页命令速查

```bash
# 安装
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"

# 初始化与诊断
am init --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh
am doctor --registry .tmp-agentmesh
am agents list --json

# skills 核心链路
am skills scan --registry .tmp-agentmesh --agent all --json
am skills import hermes --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh
am skills show demo-skill --registry .tmp-agentmesh
am skills reindex --registry .tmp-agentmesh --json
am audit all --registry .tmp-agentmesh
am skills diff demo-skill --registry .tmp-agentmesh --target hermes
am skills sync --registry .tmp-agentmesh --to hermes --dry-run
am skills sync --registry .tmp-agentmesh --to hermes --apply

# 状态、历史、回滚
am skills enable demo-skill --registry .tmp-agentmesh --target hermes,codex
am skills status demo-skill --registry .tmp-agentmesh --json
am history list --registry .tmp-agentmesh --json
am backup list --registry .tmp-agentmesh --json
am rollback plan <backup-ref> --registry .tmp-agentmesh --json
am rollback apply <backup-ref> --registry .tmp-agentmesh --confirm --json

# package（离线导出/导入/检查）
am skills export agentmesh --registry .tmp-agentmesh --out ./agentmesh-package.zip --json
am package inspect ./agentmesh-package.zip --json
am package verify ./agentmesh-package.zip --json
am skills import-package ./agentmesh-package.zip --registry .tmp-agentmesh-2 --dry-run --json

# package registry（版本管理）
am package publish my-skill 1.0.0 --registry .tmp-agentmesh
am package install my-skill --registry .tmp-agentmesh
am package install my-skill 1.0.0 --registry .tmp-agentmesh --resolve-deps
am package uninstall my-skill --registry .tmp-agentmesh
am package list --registry .tmp-agentmesh --json

# memory mesh
am memory scan --agent all --json
am memory import hermes --registry .tmp-agentmesh --dry-run
am memory import hermes --registry .tmp-agentmesh
am memory list --registry .tmp-agentmesh --json
am memory diff hermes openclaw --registry .tmp-agentmesh --json

# model mesh
am model scan --registry .tmp-agentmesh --json
am model diff --registry .tmp-agentmesh --json
am model list --registry .tmp-agentmesh --json

# tool mesh
am tool scan --registry .tmp-agentmesh --json
am tool diff --registry .tmp-agentmesh --json
am tool list --registry .tmp-agentmesh --json

# prompts（含版本管理与多 target）
am prompts add review-prompt --registry .tmp-agentmesh --name "Review Prompt" --from ./review.md
am prompts import-live --registry .tmp-agentmesh --target codex --json
am prompts update review-prompt --registry .tmp-agentmesh --content-file ./review-v2.md
am prompts versions review-prompt --registry .tmp-agentmesh --json
am prompts enable review-prompt --registry .tmp-agentmesh --target codex --dry-run
am prompts enable review-prompt --registry .tmp-agentmesh --targets codex,hermes --apply --conflict-strategy backup
am prompts status --target codex --registry .tmp-agentmesh --json

# runtime alpha（含 auto-load hook）
am runtime load-plan --target openclaw --registry .tmp-agentmesh --json
am runtime env --target openclaw --registry .tmp-agentmesh
am runtime validate --target openclaw --registry .tmp-agentmesh --json
am runtime bootstrap --target openclaw --registry .tmp-agentmesh --dry-run
am runtime exec-plan --load-plan .tmp-agentmesh/state/runtime-load-plans/openclaw.json --json
am runtime status --target openclaw --registry .tmp-agentmesh --json
am runtime check-stale --target openclaw --registry .tmp-agentmesh --json
am runtime update --target openclaw --registry .tmp-agentmesh --apply --json
```
