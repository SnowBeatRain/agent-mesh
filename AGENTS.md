# AGENTS.md

> 本文件为 AI 代理(Claude Code、Cursor、Codex 等)和人类贡献者在本仓库中工作时提供指导。

## 项目概述

AgentMesh 是一个本地优先的 AI Agent 资产互通层,支持在不同 Agent 运行时(Hermes、OpenClaw、Claude Code、Codex 等)之间共享 skills、prompts、memory、tools、MCP servers 和 model configs。

MVP 模块为 **SkillMesh** — 统一的 skill 管理与安全同步。

## 核心原则

### 中文优先
- 所有文档、代码注释、提交信息和 PR 描述使用中文。
- 英文术语仅在无标准中文翻译时使用,并附中文解释。

### 规范驱动
- 功能开发从规范(spec)开始。

### 测试优先
- 遵循 TDD:先编写失败的测试,再用最小实现通过,最后重构。
- 不在没有自动化测试的情况下提交代码。

### 简单优先
- 在满足需求前提下选择最易理解的实现。
- 避免过度工程化和不必要的抽象。

### 最小化更改
- 只修改完成当前需求所必需的部分。
- 避免大范围格式化或"顺手优化"。

### 安全边界
- **禁止读取/同步/发布 secrets**;疑似密钥必须 redacted。
- **永不扫描或写入 Codex `.system` 目录**。
- **Claude Code 定位为 `export-only`**,不会自动安装插件。

## 代码结构

```
src/agentmesh/
├── __init__.py
├── __main__.py              # 入口
├── cli/main.py              # Typer CLI 应用
├── adapters/                # 7 大 runtime 适配器
├── models/                  # Pydantic 数据模型
├── services/                # 核心业务逻辑
├── engine/                  # diff, conflict resolver
├── audit/                   # 审计引擎
├── policy/                  # 策略评估
├── paths/                   # PathGuard
├── exporters/               # Claude Code plugin 导出
├── validation/              # Native 验证
├── config/                  # Registry 初始化
├── local_api/               # HTTP server + Dashboard
└── utils/                   # frontmatter, hashing, naming, yaml

tests/                       # pytest 测试套件
docs/                        # 用户文档
```

## 技术栈

```
Python >= 3.10
CLI:        Typer >= 0.12
数据模型:    Pydantic >= 2.0
终端 UI:    Rich >= 13.0
YAML:       ruamel.yaml >= 0.18
测试:       pytest >= 8.0, pytest-cov >= 5.0
代码检查:    ruff >= 0.4
构建:       Hatchling
```

## 开发命令

### 安装

```bash
# 虚拟环境
python -m venv .venv && source .venv/bin/activate    # Linux/Mac
python -m venv .venv && .\.venv\Scripts\Activate.ps1 # Windows
pip install -e ".[dev]"
```

### 测试与质量门

```bash
# 完整测试
python -m pytest tests/ -v --cov=agentmesh

# 单文件
python -m pytest tests/test_golden_cli.py -v

# 关键词筛选
python -m pytest tests/ -v -k "diff or conflict"

# 代码检查
ruff check src/ tests/
ruff format src/ tests/
```

### 开发工作流

日常开发采用分层验证:

```bash
# 聚焦测试
python -m pytest --basetemp=.tmp-pytest-001 tests/test_safe_apply.py -q -x --tb=short

# CLI 契约测试
python -m pytest tests/test_golden_cli.py tests/test_cli_smoke.py -q -x

# 只重跑失败的测试
python -m pytest --lf -q -x --tb=short
```

**Windows 注意**:沙箱环境下使用仓库内 `.tmp-*` 目录作为 `--basetemp`,避免权限问题。

### CLI 验证

```bash
am --version
am doctor --registry .tmp-agentmesh
am overview --registry .tmp-agentmesh --json
```

## 架构

```
CLI (Typer) → Services → Engine → Models
                       → Adapters → Models
                       → Audit → Models
```

**关键约束**:**Adapter 禁止直接写文件**。所有写入通过 SyncExecutor 执行,统一保障 dry-run、备份、diff 和审计。

### 核心组件
- **Adapters** — 按 Agent runtime 实现 detect/scan/import/export/validate。
- **Registry** — `~/.agentmesh/registry/assets/skills/<name>/`。
- **SyncService** — 生成同步计划,带备份执行。
- **AuditEngine** — 静态检查:secrets、危险脚本、平台引用、license。
- **LockManager** — 记录 hash 检测 target drift,防止静默覆盖。
- **PathGuard** — 防止路径逃逸和写入 Codex `.system` / bundled 目录。

## JSON 合约标准

所有 `--json` 输出使用统一信封结构:

```json
{
  "schema": "agentmesh.<command>/v1",
  "command": "skills scan",
  "status": "ok|error|planned|blocked",
  "data": {},
  "warnings": [],
  "errors": [],
  "next_steps": []
}
```

## 关键架构约束

### 适配器模式
- Adapter 不得直接写文件,所有写入通过 SyncExecutor。
- PathGuard、审计、备份、rollback 在 SyncExecutor 层统一处理。
- Adapter 负责检测和扫描,Service 负责业务逻辑,Engine 负责核心算法。

### 写入操作
- 所有写入默认为 dry-run,显式 `--apply` 才执行。
- 写入前必须 timestamp 备份,失败时自动 rollback。
- lock hash 检测 target drift,防止静默覆盖。

### 数据流
- 当前为 registry 到 runtime 的单向同步。
- 生成文件(`agents/openai.yaml`、`plugin.json` 等)禁止回流到 registry。
- 所有资产必须包含 frontmatter manifest。

## Schema 标准

两种 manifest 格式共存:
- `agentmesh.asset/v1` — 通用资产 manifest(kind: skill|prompt|memory|tool|...)
- `agentmesh.skill/v1` — skill 专用 manifest(兼容子集)

skill 名称必须匹配:`^[a-z0-9][a-z0-9_-]{0,63}$`

## 测试模式

### 测试隔离
- 所有测试使用 `tmp_path` fixture 隔离。
- 常用 `make_registry_skill()` 辅助函数创建临时 registry 结构。
- 通过 `monkeypatch.setenv("HOME", str(tmp_path))` 重定向路径。

### JSON 合约测试
- 验证信封结构(schema/command/status/data/warnings/errors/next_steps)。
- 错误路径测试确认输出无 traceback。
- 所有疑似秘密在输出中 redacted。

## 调试与排查

### 常见问题
| 现象 | 可能原因 | 诊断 |
|------|----------|------|
| `am` 命令找不到 | 虚拟环境未激活 | `am --help`, `python -m pip show agentmesh` |
| `agents list` 无 runtime | 未安装或路径不符 | `am agents list --json` |
| `scan` 无结果 | runtime 无用户 skills | `am skills scan --agent all --json` |
| `sync --apply` 阻断 | 审计/路径/lock drift | `am audit all --json` |

## 提交约定

使用 Conventional Commits 格式(中文描述):
- `feat:` 新功能
- `fix:` 缺陷修复
- `docs:` 文档变更
- `chore:` 构建/配置/工具变更

## PR 检查清单

- [ ] 所有测试通过 (`python -m pytest tests/ -q`)
- [ ] ruff 检查通过 (`ruff check src/ tests/`)
- [ ] ruff 格式通过 (`ruff format --check src/ tests/`)
- [ ] 包含必要的测试覆盖
- [ ] 签署 [CLA](CLA.md)
- [ ] commit message 遵循 Conventional Commits
