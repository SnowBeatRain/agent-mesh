# AgentMesh State Reality and Migration

> 目的：校准 AgentMesh 当前代码真实使用的 state / backup / lock 布局，并明确它与历史架构设计之间的差异。本文只描述现实、风险和未来迁移触发条件；不要求立即改代码、不迁移已有 state、不改变 lock 格式。

## 1. 核心结论

当前 AgentMesh 的状态系统已经能支撑最小安全 apply，但还不是完整的状态账本。

一句话概括：

```text
当前实现 = sidecar lock + timestamp backup directory + sync-history.jsonl
历史目标 = central lock + backup metadata + restore plan + richer state store
```

这两者都合理，但属于不同成熟度阶段。当前阶段最重要的是：**不要把历史目标误当成当前事实，也不要让 rollback 建立在不存在的 backup metadata 上。**

## 2. 当前实现事实

当前事实基于以下代码：

- `src/agentmesh/config/loader.py`
- `src/agentmesh/services/sync_service.py`
- `tests/test_safe_apply.py`
- `tests/test_history_cli.py`

## 2.1 AgentMesh home layout

`ensure_layout(home)` 当前创建：

```text
<agentmesh_home>/
  config.yaml
  registry/
  skills/
  generated/
  backups/
  logs/
  locks/
  state/
```

其中：

| 路径 | 当前用途 | 当前成熟度 |
| --- | --- | --- |
| `skills/` | registry skill 事实源 | 已实际使用 |
| `registry/` | legacy / registry root 辅助路径 | 部分历史兼容 |
| `generated/` | 生成区 | 已创建，部分 runtime 使用 |
| `backups/` | sync apply 前的 target 备份 | 已实际使用，但 metadata 不完整 |
| `logs/` | 日志预留 | 目前不是核心状态账本 |
| `locks/` | central lock 预留 | 已创建，但 copy/symlink 当前不用它作为主 lock |
| `state/` | JSON/YAML/JSONL 状态 | 已用于 sync history、skills/prompt/runtime state |

当前已经落地的关键 state 文件包括：

```text
state/sync-history.jsonl
state/skills.yaml
state/prompts.yaml
state/runtime-load-plans/<target>.json
```

此外，PromptMesh 启用 live prompt 前会保存 prompt 专用备份：

```text
backups/prompts/<timestamp>/<live-prompt-filename>
```

这些 prompt/runtime 状态与 skill sync backup/rollback 是相邻能力，但不是 A1/M1 `backup list` 的直接数据源。A1 应优先围绕 `state/sync-history.jsonl` 与 `backups/<timestamp>/<target>/<skill>/` 定义契约。

## 2.2 当前 skill target layout

`AGENT_TARGETS` 当前定义：

```python
AGENT_TARGETS = {
    "hermes": (".hermes", "skills", "custom"),
    "openclaw": (".openclaw", "workspace", "skills"),
    "codex": (".codex", "skills"),
}
```

这意味着 copy/symlink sync 的目标路径形如：

```text
~/.hermes/skills/custom/<skill>/
~/.openclaw/workspace/skills/<skill>/
~/.codex/skills/<skill>/
```

注意：Claude Code 当前是 export-only，不参与 `skills sync --apply` 目标。

## 2.3 当前 copy mode lock

copy apply 成功后，当前在 target skill 目录内写入：

```text
<target>/<skill>/.agentmesh-lock.yaml
```

内容形如：

```yaml
schema: agentmesh.lock/v1
skill: demo-skill
target: openclaw
hash: <target tree hash>
updated_at: "2026-..."
```

这个 lock 当前用于 drift 检测：

```text
读取 target/.agentmesh-lock.yaml
  → 取出 hash
  → 重新计算 target tree hash
  → 不一致则阻止 apply
```

关键事实：

- 当前 copy lock 是 **target sidecar lock**。
- 当前没有使用 `state/locks/<agent>/<asset>.yaml` 作为主 lock。
- 当前 `_tree_hash()` 会排除 `.agentmesh-lock.yaml` 本身。

## 2.4 当前 symlink mode lock

symlink apply 成功后，target skill 是目录级 symlink：

```text
<target>/<skill> -> <agentmesh_home>/skills/<skill>
```

sidecar link lock 写在目标父目录：

```text
<target_parent>/.<skill>.agentmesh-link.yaml
```

内容形如：

```yaml
schema: agentmesh.link-lock/v1
skill: demo-skill
target: openclaw
mode: symlink
source_path: <registry skill path>
source_hash: <registry tree hash>
updated_at: "2026-..."
```

关键事实：

- symlink lock 不写入 registry 源目录，避免污染事实源。
- 目标已有非 AgentMesh 托管 symlink 时会阻断。
- symlink apply 需要显式 `--confirm`。

## 2.5 当前 backup layout

每次 `skills sync --apply` 会创建：

```text
<agentmesh_home>/backups/<timestamp>/
```

其中每个已有 target skill 被备份到：

```text
<agentmesh_home>/backups/<timestamp>/<target>/<skill>/
```

示例：

```text
.agentmesh/backups/20260430-120000-123456/openclaw/demo-skill/SKILL.md
```

关键事实：

- backup root 使用 `timestamp()`，格式类似 `YYYYMMDD-HHMMSS-ffffff`。
- 当前 backup 只复制已有普通目录 target。
- 如果 target 不存在，通常不会生成该 skill 的 backup 目录。
- 如果 target 是 symlink，当前保存 `previous_link` 用于失败恢复，但不会把 symlink 本身作为目录备份。
- 当前 backup 目录内没有标准 `backup.yaml`、`restore.yaml`、`plan.yaml`。

## 2.6 当前 sync history

成功 apply 后写入：

```text
<agentmesh_home>/state/sync-history.jsonl
```

每行是一个 JSON entry：

```json
{
  "schema": "agentmesh.sync-history-entry/v1",
  "id": "sync-<iso timestamp>",
  "timestamp": "<iso timestamp>",
  "operation": "skills sync",
  "status": "applied",
  "targets": ["openclaw"],
  "sync_mode": "copy",
  "summary": {
    "actions": 1,
    "allowed": 1,
    "blocked": 0,
    "warnings": 0
  },
  "backup": "<agentmesh_home>/backups/<timestamp>",
  "actions": []
}
```

关键事实：

- 当前只记录成功 apply。
- dry-run 不写 history。
- policy/security/drift block 不写 history。
- 失败 apply 目前依赖内部异常恢复，不写结构化 failed history entry。
- `history list` 当前只是查看 raw sync history，不是 backup list，也不是 rollback plan。

## 3. 当前状态流

## 3.1 Dry-run

```text
build_sync_plan
  → render_sync_plan
  → diff/policy check
  → return rendered plan
  → 不写 backup
  → 不写 lock
  → 不写 history
```

## 3.2 Copy apply

```text
render_sync_plan(APPLY)
  → PathGuard check source/target
  → security check
  → file/symlink target check
  → drift check via target/.agentmesh-lock.yaml
  → diff conflict check
  → backup existing target directory to backups/<timestamp>/<target>/<skill>/
  → remove target
  → copy registry skill to target
  → write target/.agentmesh-lock.yaml
  → remove symlink sidecar lock if any
  → append state/sync-history.jsonl
```

失败恢复：

```text
if previous target was symlink:
  restore symlink
elif previous target existed:
  restore copied backup directory
elif partial target exists:
  remove partial target
raise original error
```

## 3.3 Symlink apply

```text
render_sync_plan(APPLY)
  → PathGuard check source/target
  → security check
  → target file/symlink/drift/conflict checks
  → backup existing non-symlink target directory if present
  → remove target
  → create directory symlink to registry skill
  → write <target_parent>/.<skill>.agentmesh-link.yaml
  → append state/sync-history.jsonl
```

失败恢复类似 copy apply，但 symlink 失败会包装为 `SyncBlocked("symlink failed: ...")`。

## 4. 历史设计目标

历史架构文档中设计过更完整的状态系统：

```text
state/
  agent-detect.json
  hashes.json
  provenance.json
  sync-history.jsonl
  audit-reports/
  plans/
  locks/<agent>/<asset>.yaml
backups/<sync-id>/
  files/
  backup.yaml
  plan.yaml
  restore.yaml
  lock-before.yaml
  lock-after.yaml
```

这些目标仍然有价值，但当前并未完整实现。

## 4.1 Central lock 目标

历史设计建议：

```text
<agentmesh_home>/state/locks/<agent>/<asset>.yaml
```

优点：

- 不污染 Agent runtime 目录。
- 更容易集中查询和管理。
- 更适合未来 Local API / Web UI。

缺点：

- state 丢失后 target 目录不可自描述。
- 迁移成本高，需要同时调整 sync、diff、rollback、status、tests。

## 4.2 Backup metadata 目标

历史设计建议每个 backup 包含：

```text
backup.yaml
plan.yaml
restore.yaml
lock-before.yaml
lock-after.yaml
```

这样 rollback 可以回答：

- 备份来自哪次 sync？
- 原 target 是什么路径？
- 哪些文件原本存在？
- 哪些文件是 sync 新增？
- rollback 应恢复哪些文件、删除哪些生成物？
- lock 应恢复成什么状态？

当前实现没有这些 metadata。

## 4.3 Rich history 目标

历史设计希望 history 能记录：

- success
- blocked
- failed
- partial write
- validation result
- recovery hint
- rollback event

当前 history 只记录 successful apply。

## 5. 差异矩阵

| 领域 | 历史设计目标 | 当前实现事实 | 当前风险 | 近期处理 |
| --- | --- | --- | --- | --- |
| Lock 存储 | central lock in `state/locks` | copy target sidecar lock；symlink parent sidecar lock | 文档与现实不一致，未来实现可能误判 | A0 明确现实；近期不迁移 |
| Backup ID | sync-id 驱动 | backup path 是 timestamp；history id 是 ISO timestamp | M1/M2 如果不统一会返工 | A1 定义 backup_id |
| Backup metadata | backup/restore/plan/lock before-after | 只有目录内容 | rollback 只能 tree-level 推断 | A1/A2 明确初版边界 |
| History event | success/blocked/failed/rollback | 仅成功 apply | 无法审计失败写入 | M3 前定义 rollback history；failed history 后置 |
| Apply 原子性 | temp + rename + action log | copytree + exception restore | 可恢复但动作级解释不足 | 近期不重写；rollback 文档承认限制 |
| State lock | 全局/target 写锁 | 未实现通用 state lock | 并发命令可能竞争 | 后置，SQLite/多进程前再做 |
| Package integrity | checksums/provenance | ZIP 无 file checksum | verify 不可做完整证明 | M5 引入 file manifest |
| Prompt state | lifecycle 明确 | only enabled state | disable/status 语义不完整 | M6 前补 prompt-target-state |

## 6. 为什么近期不迁移 central lock

当前不迁移 central lock，理由如下：

1. **当前 sidecar lock 已有测试覆盖。** 例如 drift block、copy apply、symlink apply 等测试基于现状。
2. **central lock 会扩大影响面。** 需要同时改 sync、diff、rollback、status、runtime、tests。
3. **M1/M2/M3 的真正阻塞不是 lock 位置，而是 backup/rollback 契约。** 先迁移 lock 会绕开核心问题。
4. **sidecar lock 有现实优点。** 即使 state 丢失，target 仍能自描述“曾由 AgentMesh 管理”。
5. **当前还没有 Web UI / 多进程 state 查询压力。** central lock 的收益尚未超过迁移成本。

因此近期决策：

```text
v0.1 继续承认 sidecar lock 是现实实现。
central lock 保留为未来演进目标，不作为 A 阶段或 M1-M3 前置条件。
```

## 7. 为什么当前 backup 只能支撑 tree-level rollback

当前 backup 保存的是旧 target 目录树，而不是 action log。

因此它能比较可靠地支持：

```text
把某个 target skill 目录恢复成备份目录的内容
```

但它不能可靠回答：

```text
哪些文件是 sync 新增的？
哪些文件应该删除？
原 target 是否不存在？
原 target 是否是 symlink？
原 lock before/after 是什么？
```

所以 M2/M3 初版 rollback 必须声明：

- 初版只做 tree-level restore。
- 如果 backup metadata 缺失，计划中标记 `metadata_missing` 或 `partial`。
- 对 drift/unmanaged target 默认 blocked。
- 更细粒度 action-level rollback 需要先引入 backup manifest。

## 8. 当前事实对后续里程碑的影响

## 8.1 对 A1 / M1 的影响

`am backup list` 必须是：

```text
sync-history entry -> backup record projection
```

而不是：

```text
history list alias
```

BackupRecord 至少要表达：

```yaml
id: sync-...
history_id: sync-...
created_at: ...
backup_path: ...
sync_mode: copy|symlink
targets: []
action_count: 0
recoverability:
  status: restorable|partial|metadata_missing|missing_path
  reasons: []
```

## 8.2 对 A2 / M2 / M3 的影响

rollback plan 必须能处理：

```text
backup exists but metadata missing
backup path missing
current target managed clean
current target managed drift
current target unmanaged
current target missing
```

M2 不写文件。M3 apply 前必须重新 build plan。

## 8.3 对 A3 的影响

M1-M7 都会新增 JSON schema。当前 CLI envelope 不完全统一，因此 A3 必须先定义最小通用 envelope，避免继续扩散。

## 9. 迁移路线

## 9.1 当前阶段：承认现实

范围：A0-A3 + M1-M3。

策略：

- 不迁移 lock。
- 不迁移 state backend。
- 不改变现有 sync apply 行为。
- 新功能围绕现有 history/backup/lock 现实建立只读投影和保守恢复。

## 9.2 中期阶段：补 metadata

触发条件：

- M1 backup list 已可见。
- M2 rollback plan 已能从 history 推导 tree-level restore。
- M3 rollback apply 已可用，但用户需要更精细恢复。

可引入：

```text
backups/<sync-id>/backup.yaml
backups/<sync-id>/restore.yaml
backups/<sync-id>/plan.json
```

注意：引入 metadata 时要兼容旧 backup。

## 9.3 后期阶段：central lock / SQLite

触发条件至少满足其中两项：

- 需要 Web UI 大量查询 target state。
- 出现多进程并发写 state 问题。
- sidecar lock 被某些 runtime 误读或污染用户体验。
- rollback/status 需要跨 target 聚合 lock。
- state 查询性能明显不足。

迁移原则：

- central lock 不应破坏已有 sidecar lock。
- 可以先双写，再切读路径。
- 提供 `state migrate --dry-run` 类命令时才进入实现阶段。

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 文档继续把 central lock 当当前事实 | 后续实现读错位置 | 本文明确 sidecar lock 是当前事实 |
| rollback 误以为有 restore metadata | 误恢复/误删除 | A1/A2 明确 metadata_missing 与 tree-level restore |
| backup path 丢失 | backup list/rollback 崩溃 | M1 输出 `missing_path`，M2 blocked |
| symlink rollback 语义不清 | 恢复错误对象 | A2 必须单独定义 symlink target state |
| failed apply 无 history | 用户无法查询失败记录 | 近期承认限制；后续 failed history 单独设计 |
| state 并发写冲突 | history/prompt state 损坏 | 后置 state lock；当前命令保持短事务 |

## 11. A0 验收清单

- [x] 至少列出 4 类当前状态文件/目录。
- [x] 至少列出 5 个历史设计 vs 当前实现差异。
- [x] 至少给出 3 条迁移触发条件。
- [x] 明确“不做”：不改代码、不迁移 state、不改 lock 格式。
- [x] 包含状态流 text diagram。
- [x] 包含 YAML/JSON 示例。
- [x] 包含风险/缓解表。

## 12. 非目标

A0 不做：

- 不实现 `am backup list`。
- 不实现 rollback。
- 不迁移 central lock。
- 不新增 SQLite。
- 不改变 `sync_service.py`。
- 不改变现有测试预期。

## 13. 后续文档入口

完成 A0 后，下一步是 A1：

```text
docs/design/backup-history.md
```

A1 应基于本文的现实约束，定义 `BackupRecord`、`backup_id`、`recoverability` 和 `agentmesh.backup-list/v1`。
