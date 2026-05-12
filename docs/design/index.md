# 架构设计

AgentMesh 的设计文档集中在此目录下，记录了内部架构决策、数据流和实现细节。

## 核心设计

| 文档 | 说明 |
|------|------|
| [Runtime Renderer](runtime-renderer.md) | Runtime 渲染引擎设计 |
| [CLI Envelope Contract](cli-envelope-contract.md) | CLI JSON envelope 标准化约定 |
| [CLI Envelope 审计](cli-envelope-state-contract-audit-2026-05-03.md) | Envelope 与 state contract 的审计记录 |
| [Update 流程](update-flow.md) | Runtime 更新流程设计 |
| [Rollback](rollback.md) | 回滚机制设计 |

## 状态与数据

| 文档 | 说明 |
|------|------|
| [Backup History](backup-history.md) | 备份历史机制 |
| [Package Verify](package-verify.md) | Package 验证流程 |
| [Prompt Target State](prompt-target-state.md) | Prompt 目标状态设计 |
| [State Reality & Migration](state-reality-and-migration.md) | 状态真实性与迁移策略 |
| [Model Mesh](model-mesh.md) | ModelMesh 跨 Agent 模型对比设计 |

## 规划与审计

| 文档 | 说明 |
|------|------|
| [Refactor Roadmap](refactor-roadmap.md) | 重构路线图 |
| [Codebase Roadmap 审计](codebase-roadmap-alignment-audit.md) | 代码库与路线图对齐审计 |
| [CC Switch 架构](ccswitch-milestone-architecture.md) | CC Switch 里程碑架构设计 |

## 设计原则

- **本地优先**：所有数据存储在本地，不依赖云服务。
- **Dry-run 优先**：任何写操作前先预览，显式 `--apply` 才执行。
- **审计可追溯**：所有变更记录 history / backup，支持回滚。
- **安全边界**：默认保护 Codex `.system` 等受保护资源。
