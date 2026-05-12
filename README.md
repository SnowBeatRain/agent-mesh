# AgentMesh

> 本地优先的 AI Agent 资产互通层。当前 `0.1.0` 聚焦 **SkillMesh**:把 Hermes、OpenClaw、Codex、Claude Code、Cursor、Windsurf、Aider 等本机 Agent runtime 的 skills 收敛到中立 registry,再通过审计、diff、dry-run、apply、backup、rollback 和 package 导入导出,实现更安全的共享与迁移。

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)

## 核心能力

- **多 runtime 检测**:Hermes / OpenClaw / Codex / Claude Code / Cursor / Windsurf / Aider 七大 Agent runtime。
- **安全扫描与导入**:扫描用户 skills 到中立 registry,默认保护 Codex `.system` 永不写入。
- **审计与脱敏**:secrets、危险脚本、平台引用静态检查,疑似敏感内容自动 `<redacted>`。
- **dry-run 优先**:默认预览,显式 `--apply` 才执行写入;每次写入前 timestamp 备份。
- **回滚保护**:`rollback plan` / `rollback apply` 形成完整恢复闭环,含 hard block 安全保护。
- **多资产互通**:Skills、Prompts、Memory、Model、Tool 五大资产类型的 scan/diff/list。
- **本地 Dashboard**:`am local serve` 启动浏览器工作台,提供命令执行、定时任务、批量操作、收藏夹等。
- **Package 导入导出**:ZIP 包离线迁移,含 inspect / verify / dry-run 三层保护。

## 环境要求

```text
Python >= 3.10
```

## 安装

### 推荐:项目内虚拟环境

**Linux / macOS / WSL**:

```bash
git clone https://github.com/SnowBeatRain/agent-mesh.git
cd agent-mesh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
am --help
```

**Windows PowerShell**:

```powershell
git clone https://github.com/SnowBeatRain/agent-mesh.git
cd agent-mesh
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
am --help
```

安装后会生成两个等价命令:`am` 和 `agentmesh`。

## 15 分钟快速开始

建议先用临时 registry 体验完整链路,避免直接写入真实 runtime:

```bash
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

这条流程只写临时 registry,不写目标 runtime。真正同步前请先审计和 dry-run。

## 基础使用

### 管理 skills

```bash
am skills scan --registry .tmp-agentmesh --agent all --json
am skills import hermes --registry .tmp-agentmesh
am skills list --registry .tmp-agentmesh
am skills show demo-skill --registry .tmp-agentmesh --json
am skills rename old-name new-name --json
am skills delete unwanted-skill --yes --json
```

### 审计、diff 与同步

```bash
am audit all --registry .tmp-agentmesh
am skills diff demo-skill --registry .tmp-agentmesh --target hermes
am skills sync --registry .tmp-agentmesh --to hermes --dry-run
am skills sync --registry .tmp-agentmesh --to hermes --apply
```

> **注意**:`skills diff` 的 `--target` 为必填参数,需显式指定目标 Agent。

### 回滚

```bash
am history list --registry .tmp-agentmesh --json
am backup list --registry .tmp-agentmesh --json
am rollback plan <backup-ref> --registry .tmp-agentmesh --json
am rollback apply <backup-ref> --registry .tmp-agentmesh --confirm --json
```

### Package 导入导出

```bash
am skills export agentmesh --registry .tmp-agentmesh --out ./agentmesh-package.zip --json
am package inspect ./agentmesh-package.zip --json
am package verify ./agentmesh-package.zip --json
am skills import-package ./agentmesh-package.zip --registry .tmp-agentmesh-2 --dry-run --json
```

### Local Dashboard

```bash
am local serve --port 9090
# 浏览器访问 http://127.0.0.1:9090/
```

默认绑定 `127.0.0.1:9090`,localhost-only,不允许远程连接。

## 安全原则

- 默认 `--dry-run`,显式 `--apply` 才执行写入。
- Codex `.system` 永远受保护,不扫描、不导入、不写入。
- Claude Code 当前为 `export-only`,不会自动安装插件。
- 审计、diff、show 中的疑似 secrets 自动脱敏为 `<redacted>`。
- `--allow-conflicts` 不能绕过 secret/security/drift/unsafe path 的 hard block。
- Package verify 仅校验清单和 checksum,不等于安全审计;导入前请先 `--dry-run`。

## 文档入口

- [快速开始](docs/getting-started.md)
- [完整使用指南](docs/usage-guide.md)
- [CLI 参考](docs/cli-reference.md)
- [架构设计](docs/design/index.md)
- [Adapter Contract v1](docs/specs/adapter-contract-v1.md)
- [安全模型](docs/security/local-api-dashboard-threat-model.md)

## 贡献

我们欢迎 PR 和 Issue。提交贡献前请阅读:

- [贡献指南](CONTRIBUTING.md)
- [行为准则](CODE_OF_CONDUCT.md)
- [贡献者许可协议(CLA)](CLA.md)

发现安全问题请通过 [SECURITY.md](SECURITY.md) 中的渠道私下报告。

## 开发质量门

```bash
python3 -m pytest tests -q
ruff check src/ tests/
ruff format --check src/ tests/
```

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
