# AgentMesh Rollback Contract

> 目的：定义 A2 / M2 / M3 的 rollback 契约。本文只设计 `rollback plan` 与 `rollback apply` 共享的 plan builder、backup 引用解析、target state、recoverability 到 rollback decision 的映射、安全阻断与 symlink 特殊语义；不实现 CLI，不修改现有 state，不执行恢复。

## 1. 背景与边界

A0 已确认当前实现事实：

```text
<agentmesh_home>/state/sync-history.jsonl
<agentmesh_home>/backups/<timestamp>/<target>/<skill>/
copy target sidecar lock: <target>/<skill>/.agentmesh-lock.yaml
symlink parent sidecar lock: <target_parent>/.<skill>.agentmesh-link.yaml
```

A1 已定义：

```text
SyncHistoryEntry -> BackupRecord
backup_id = "bkp-" + sha256(history_id + "\0" + backup_path)[0:12]
recoverability = restorable | partial | metadata_missing | missing_path | empty_backup | unsafe_path | unknown
```

A2 的核心结论：

```text
rollback plan 与 rollback apply 必须共用同一个 plan builder。
M2 只读，只输出计划。
M3 apply 前必须重新 build plan，并且只执行刚刚重新验证过的 safe plan。
```

A2 不是：

```text
backup metadata 实现
细粒度 action-level rollback
central lock 迁移
并发事务系统
backup retention / cleanup
prompt backup rollback
runtime bootstrap rollback
```

## 2. 命令范围

后续 M2 / M3 建议命令：

```bash
am rollback plan <backup-ref> --registry <agentmesh_home>
am rollback plan <backup-ref> --registry <agentmesh_home> --json
am rollback apply <backup-ref> --registry <agentmesh_home> --confirm
am rollback apply <backup-ref> --registry <agentmesh_home> --confirm --json
```

其中 `<backup-ref>` 可为：

```text
backup_id     # 例如 bkp-a1b2c3d4e5f6
history_id    # 例如 sync-2026-04-30T12:00:00.123456+00:00
backup_path   # 例如 /home/now/.agentmesh/backups/20260430-120000-123456
```

`rollback apply` 不应接受“来自旧 plan 输出的完整 JSON”作为执行依据。用户可以传同一个 `<backup-ref>`，但 M3 必须重新构建 rollback plan。

## 3. 共享 plan builder

### 3.1 单一事实入口

M2 与 M3 必须调用同一个 builder，例如：

```python
def build_rollback_plan(
    agentmesh_home: Path,
    backup_ref: str,
    *,
    home: Path | None = None,
) -> dict:
    ...
```

M2：

```text
resolve backup_ref
  -> build_rollback_plan(...)
  -> render human/json
  -> 不写任何文件
```

M3：

```text
resolve backup_ref
  -> build_rollback_plan(...)
  -> 如果 plan.status != executable: block
  -> 如果存在 hard block: block
  -> 如果未传 --confirm: block
  -> apply actions
  -> 记录 rollback history（M3 设计）
```

### 3.2 builder 必须重新读取当前现实

builder 每次调用都必须重新读取：

- `<agentmesh_home>/state/sync-history.jsonl`
- `<agentmesh_home>/backups/` 内与 `<backup-ref>` 对应的 backup path
- 当前 live target path 的存在性、类型、lock 与 drift 状态

builder 不能复用以下内容作为当前事实：

- 上一次 `rollback plan` 输出的 JSON
- 缓存的 BackupRecord
- 用户提交的旧 `target_state`
- 用户提交的旧 `decision`

原因：M2 与 M3 之间 target 可能已被用户或其他 Agent 修改。M3 只有重新 build 才能发现 drift / unmanaged / missing / symlink 状态变化。

### 3.3 只读阶段与写入阶段分离

`build_rollback_plan()` 必须只读，不得：

- 创建、修改、删除 target 文件
- 创建、修改、删除 backup 文件
- 写 lock
- 写 history
- 修复 metadata
- 访问网络
- 扫描不相关 runtime home
- 读取 token / secret 配置

真正写入只能发生在 M3 apply executor 中，且 executor 只能执行 builder 输出的 `decision in {restore_tree, restore_managed_symlink_to_tree}` 且无 hard block 的 action；其中 `restore_managed_symlink_to_tree` 必须进入第 9 节定义的 symlink 专用 executor。

## 4. backup_ref 解析规则

### 4.1 解析输入类型

解析顺序建议：

```text
if backup_ref starts with "bkp-":
  resolve as backup_id
elif backup_ref starts with "sync-":
  resolve as history_id
else:
  resolve as backup_path candidate
```

实现可以同时支持显式前缀：

```text
backup_id:bkp-a1b2c3d4e5f6
history_id:sync-...
path:/home/now/.agentmesh/backups/...
```

但默认 CLI 不要求用户写前缀。

### 4.2 backup_id 解析

`backup_id` 解析必须基于 A1 规则现场重算：

```text
for each eligible BackupRecord:
  candidate_id = "bkp-" + sha256(history_id + "\0" + backup_path)[0:12]
  if candidate_id == backup_ref:
    match
```

如果匹配 0 条：返回 `backup_not_found` error。

如果匹配 1 条：继续 plan。

如果匹配多条：返回 `ambiguous_backup` error，并提示用户改用 `history_id` 或完整 `backup_path`。不能默认取第一条。

### 4.3 history_id 解析

`history_id` 只匹配 `SyncHistoryEntry.id`。

有效 entry 必须满足：

```text
operation == "skills sync"
status == "applied"
backup is a string
```

如果 history id 存在但 entry 不满足以上条件，返回 `not_rollback_eligible`，不能尝试从 actions 或 target path 猜测 backup。

如果多条 history 使用同一个 id，返回 `ambiguous_history`。虽然当前实现不会生成重复 id，但损坏 history 必须保守处理。

### 4.4 backup_path 解析

`backup_path` 可为绝对路径或相对路径。解析时必须：

```text
backups_root = (<agentmesh_home>/backups).resolve()
if backup_ref is relative:
  candidate = (backups_root / backup_ref).resolve()
else:
  candidate = Path(backup_ref).expanduser().resolve()
candidate must be inside backups_root
```

所有 backup path 必须限制在：

```text
<agentmesh_home>/backups/
```

路径限制优先于 existence check。也就是说：

```text
if candidate outside backups_root:
  unsafe_path hard block
  do not stat/list/read candidate
```

如果 `backup_path` 在 backups root 内但没有对应 history entry，M2 可输出 `metadata_missing` + `history_unmatched` 的只读诊断，但默认 M3 必须 hard block，因为无法确认 targets/actions/operation 来源。

### 4.5 backup path 禁止策略

任何以下 path 都不能作为 rollback backup：

```text
~/.hermes/...
~/.openclaw/...
~/.codex/...
~/.claude/...
/tmp/...
../ escaped path
symlink escaped path
URL 字符串必须直接拒绝；网络挂载不作为 A2 的可移植检测目标，A2 只要求 `resolve()` 后仍位于 `backups_root` 内。
```

实现层面不要依赖字符串前缀判断，应使用 `Path.resolve()` 后的 containment check。

## 5. RollbackPlan schema

### 5.1 逻辑模型

```yaml
RollbackPlan:
  schema: agentmesh.rollback-plan/v1
  command: rollback plan | rollback apply
  status: executable | blocked | error
  mode: PLAN | APPLY
  backup:
    backup_ref: string
    backup_id: string | null
    history_id: string | null
    backup_path: string | null
    sync_mode: copy | symlink | unknown
    recoverability: string
  summary:
    actions: integer
    executable: integer
    blocked: integer
    warnings: integer
    hard_blocks: integer
  actions:
    - action_id: string
      target: string
      skill: string
      target_path: string
      backup_skill_path: string | null
      target_state: TargetState
      current_target_state: TargetState | null
      recoverability: string
      decision: RollbackDecision
      hard_block: boolean
      reasons: string[]
      warnings: string[]
  warnings: string[]
  errors: string[]
  next_steps: string[]
```

### 5.2 action_id

`action_id` 应稳定且不泄露路径，可使用：

```text
action_id = "rb-" + sha256(history_id + "\0" + target + "\0" + skill)[0:12]
```

当没有 history_id 时，M2 可基于 backup_path 派生诊断 action id；M3 对缺 history 的 path 默认 hard block。

### 5.3 action 来源

action 优先来源：

1. history entry 的 `actions[]` 中 `decision=allow` 的 skill/target。
   当前实现里 target 字段来自 `action["to"]`，不是 `action["target"]`；`target_path` 只用于展示和定位当前 live target，不能绕过 target adapter / PathGuard。
2. 如果未来 metadata 存在且 schema 受支持，可由 metadata 覆盖或增强。
3. 如果只有 backup tree、没有 history actions，M2 只能做诊断展示；M3 默认 block。

A2 不允许 M3 从 `<backup_path>` 全量目录扫描后直接恢复所有子目录，除非有受支持 metadata 明确声明这些目录属于同一次 sync。旧 tree-only backup 的恢复范围必须受 history actions 约束。

## 6. TargetState

A2 定义以下 target state。builder 必须为每个 action 给出且只能给出其中之一：

```text
managed_clean
managed_drift
unmanaged
missing
backup_missing
metadata_missing
managed_symlink
unsafe_path
```

### 6.1 状态定义

| target_state | 定义 | 默认 rollback decision |
| --- | --- | --- |
| `managed_clean` | 当前 target 是普通目录，存在 `.agentmesh-lock.yaml`，lock schema/skill/target 匹配，当前 tree hash 与 lock hash 匹配。 | `restore_tree` |
| `managed_drift` | 当前 target 是普通目录，存在匹配 lock，但当前 tree hash 与 lock hash 不匹配。 | `block_drift` hard block |
| `unmanaged` | 当前 target 存在，但没有匹配 AgentMesh lock；或是文件；或是非 AgentMesh symlink。 | `block_unmanaged` hard block |
| `missing` | 当前 target 不存在，且不是 symlink。 | `restore_tree` 或 `noop_missing`，取决于 backup/metadata 语义 |
| `backup_missing` | 对应 `<backup_path>/<target>/<skill>/` 不存在或不可读。 | `block_backup_missing` hard block |
| `metadata_missing` | backup path 存在且 action 可从 history 推导，但缺少受支持 metadata；只能 tree-level restore。 | `restore_tree` with warning 或按 recoverability block |
| `managed_symlink` | 当前 target 是 AgentMesh 管理的 symlink，且 parent sidecar link lock 匹配。 | 进入 symlink rollback 语义，不走普通 tree restore |
| `unsafe_path` | backup path、backup skill path 或 target path resolve 后不在允许范围，或 target path 不满足 PathGuard。 | `block_unsafe_path` hard block |

### 6.2 状态判定顺序

状态判定必须遵循安全优先顺序：

```text
1. backup path confinement check
2. target path PathGuard check
3. backup skill path confinement check
4. backup skill path exists/readable check
5. target exists/type check
6. managed symlink lock check
7. ordinary sidecar lock check
8. drift hash check
9. metadata presence check
```

不能先读取或遍历 unsafe path。

### 6.3 managed_clean

判定条件：

```text
target exists
target is directory
target is not symlink
target/.agentmesh-lock.yaml exists
lock.schema == agentmesh.lock/v1
lock.skill == action.skill
lock.target == action.target
_tree_hash(target) == lock.hash
```

`managed_clean` 表示 live target 仍是上次 AgentMesh 托管的干净状态。它是 copy rollback 的主要可执行前提。

### 6.4 managed_drift

判定条件：

```text
lock exists and matches skill/target
_tree_hash(target) != lock.hash
```

`managed_drift` 是 hard block，不能通过 `--allow-conflicts`、`--force` 或 `--confirm` 绕过。原因：用户或 Agent 已经在 apply 后修改了 target，rollback 可能覆盖人工变更。

M3 后续若要支持 drift override，必须新增独立设计，例如 `rollback resolve-drift` 或生成人工 diff 审批；A2 不允许。

### 6.5 unmanaged

以下任一情况为 `unmanaged`：

- target 是普通目录但没有 `.agentmesh-lock.yaml`。
- target 有 lock 但 schema/skill/target 不匹配。
- target 是普通文件。
- target 是 symlink 但没有匹配 `agentmesh.link-lock/v1` parent lock。
- target parent link lock 指向其他 skill/target/source。

`unmanaged` 是 hard block。rollback 不能把非 AgentMesh 托管内容当作可覆盖对象。

### 6.6 missing

`missing` 表示 target 当前不存在。这不是错误，因为用户可能已删除当前 AgentMesh 生成物。

决策：

- 如果 backup 存在且 action 来源可信：可 `restore_tree`，恢复备份目录到 target。
- 如果 metadata 未来明确表示“sync 前 target 原本不存在”：应 `noop_missing` 或 `delete_generated`，不能恢复不存在的旧目录。
- 当前旧 backup 缺 metadata，若 backup skill path 存在，M2 可计划 tree restore 并 warning；M3 可执行但必须在 plan 中明确 `metadata_missing`。

### 6.7 backup_missing

`backup_missing` 表示 action 对应的备份目录不存在：

```text
<backup_path>/<target>/<skill>/ missing
```

它是 hard block。即使当前 target 是 managed_clean，也不能删除 target 来“回滚到缺失”。当前旧实现无法证明 sync 前 target 原本不存在，因此 A2 不允许把 backup_missing 当作删除信号。

未来只有受支持 metadata 明确记录 `before.exists=false` 时，才能把 backup_missing 映射为删除当前 AgentMesh 生成物。

### 6.8 metadata_missing

`metadata_missing` 表示缺少 `backup.yaml` / `restore.yaml` / `plan.yaml` 等受支持 metadata。它不是单独的 live target 类型，而是 backup 事实对 action 的降级状态；A2 将其放入 `target_state` 枚举，是为了让 CLI/JSON 能对旧 backup 给出明确状态。

当同时存在 live target 状态与 metadata 缺失时，推荐：

```yaml
target_state: metadata_missing
current_target_state: managed_clean | missing | managed_symlink
```

如果实现初版只能返回一个 state，则按以下优先级：

```text
unsafe_path > backup_missing > managed_drift > unmanaged > managed_symlink > metadata_missing > managed_clean > missing
```

### 6.9 managed_symlink

`managed_symlink` 表示：

```text
target.is_symlink()
parent lock exists
lock.schema == agentmesh.link-lock/v1
lock.mode == symlink
lock.skill == action.skill
lock.target == action.target
```

它不能用普通 tree restore 简化处理。symlink rollback 见第 9 节。

### 6.10 unsafe_path

`unsafe_path` 包括：

- backup root 不在 `<agentmesh_home>/backups/`。
- backup skill path resolve 后逃逸出 backup root。
- target path 不在该 target agent 允许写入目录。
- symlink resolve 导致写入/读取不安全。

`unsafe_path` 是最高优先级 hard block。

## 7. Recoverability -> rollback decision 映射

A1 的 recoverability 是 backup 级判断；A2 的 rollback decision 是 action 级判断。builder 必须同时考虑：

```text
backup recoverability
+ action backup availability
+ current target state
+ sync_mode
+ metadata support
```

### 7.1 Recoverability 映射表

| recoverability | M2 plan 行为 | M3 apply 行为 |
| --- | --- | --- |
| `restorable` | 可生成可执行计划；仍需检查 target state。 | target state 安全时可执行。 |
| `metadata_missing` | 可生成保守 tree-level plan；必须 warning。 | 只允许 `managed_clean` / `missing` 的 copy tree restore；symlink 走单独语义。 |
| `partial` | 默认 blocked；可列出可诊断 action，但不执行。 | hard block。 |
| `missing_path` | blocked。 | hard block。 |
| `empty_backup` | blocked，除非未来 metadata 明确表示 no-op。 | hard block。 |
| `unsafe_path` | blocked；不得读取路径。 | hard block。 |
| `unknown` | blocked。 | hard block。 |

### 7.2 RollbackDecision 枚举

A2 定义以下 action decision：

```text
restore_tree
restore_managed_symlink_to_tree
noop_missing
block_drift
block_unmanaged
block_backup_missing
block_metadata_missing
block_partial
block_missing_path
block_empty_backup
block_unknown
block_unsafe_path
block_symlink
manual_review
```

说明：

| decision | 含义 | hard_block |
| --- | --- | --- |
| `restore_tree` | 将 backup skill directory 恢复到 target path。 | false |
| `restore_managed_symlink_to_tree` | 仅用于第 9.1 的可安全 symlink rollback：移除 AgentMesh managed symlink 与 link lock，再把 backup tree 恢复为普通目录。 | false |
| `noop_missing` | 什么都不写；仅当 metadata 明确证明 no-op 安全。 | false |
| `block_drift` | 当前 managed target 已 drift。 | true |
| `block_unmanaged` | 当前 target 不受 AgentMesh 管理。 | true |
| `block_backup_missing` | 缺少 action 对应 backup。 | true |
| `block_metadata_missing` | metadata 缺失且该 action 无法安全 tree restore。 | true |
| `block_partial` | backup/action 不完整。 | true |
| `block_missing_path` | backup root 不存在。 | true |
| `block_empty_backup` | backup root 为空且没有 metadata 证明 no-op。 | true |
| `block_unknown` | 信息不足，无法安全判断。 | true |
| `block_unsafe_path` | 任一路径不安全。 | true |
| `block_symlink` | symlink rollback 缺少必要 metadata 或当前不支持。 | true |
| `manual_review` | M2 可显示人工审查建议；M3 不执行。 | true |

### 7.3 action 决策算法

保守算法：

```text
if any path unsafe:
  decision = block_unsafe_path
elif backup recoverability == missing_path:
  decision = block_missing_path
elif backup recoverability == empty_backup:
  decision = block_empty_backup
elif backup recoverability == unknown:
  decision = block_unknown
elif backup recoverability == partial:
  decision = block_partial
elif target_state == backup_missing:
  decision = block_backup_missing
elif target_state == managed_drift:
  decision = block_drift
elif target_state == unmanaged:
  decision = block_unmanaged
elif target_state == managed_symlink:
  if sync_mode == symlink and backup skill path exists and recoverability in {restorable, metadata_missing}:
    decision = restore_managed_symlink_to_tree
  else:
    decision = block_symlink
elif recoverability == metadata_missing:
  if target_state in {managed_clean, missing, metadata_missing} and backup skill path exists:
    decision = restore_tree with warning
  else:
    decision = block_metadata_missing
elif target_state in {managed_clean, missing}:
  decision = restore_tree
else:
  decision = manual_review
```

### 7.4 不可绕过规则

以下 block 不可被任何常规 flag 绕过：

```text
drift
unmanaged
unsafe_path
security hard block
backup_missing
partial
unsupported symlink rollback
```

特别是：

- `--allow-conflicts` 只属于 `skills sync --apply` 的非安全类冲突绕过，不适用于 rollback。
- `--confirm` 只确认执行已安全计划，不改变 action decision。
- A2 不定义 `--force`。如果未来引入 `--force`，也不能绕过 `unsafe_path`、security、unmanaged symlink 或 drift。

## 8. Copy rollback 语义

### 8.1 tree-level restore

当前旧 backup 只支持 tree-level restore：

```text
remove current ordinary target directory only if it is managed_clean, or create target if it is missing
copytree(<backup_path>/<target>/<skill>, <target_path>)
write restored lock according to restored backup content
```

普通 copy executor 不能删除 symlink 或普通文件；symlink rollback 只允许由第 9 节的 `restore_managed_symlink_to_tree` 专用 executor 处理，普通文件属于 `unmanaged` hard block。

- 如果 backup tree 内已有 `.agentmesh-lock.yaml`，恢复后保留它。
- 如果 backup tree 内没有 lock，M3 不应凭空写一个“看似真实”的 old lock；可以在结果中 warning。
- 恢复后可重新计算 target hash 并验证与 restored lock 是否一致；不一致则输出 warning 或失败，具体由 M3 实现设计。

### 8.2 删除当前生成物的限制

当前没有 metadata 证明 sync 前 target 是否不存在。因此 A2 不允许：

```text
backup_missing -> delete current managed target
empty_backup -> delete current managed target
```

未来 metadata 若明确：

```yaml
before:
  exists: false
```

才可生成 `delete_generated` 类 decision。A2 不引入该 decision。

### 8.3 apply 原子性要求

M3 最低要求：

```text
1. 在同一 filesystem 下创建 temp restore dir。
2. copy backup tree 到 temp dir。
3. 验证 temp dir 可读且基本结构存在。
4. 将 current target 移到 temporary holding path。
5. rename temp dir 到 target path。
6. 成功后清理 holding path。
7. 失败时尽量 restore holding path。
```

不要直接：

```text
rm -rf target
copytree backup target
```

除非实现同时具备异常恢复保护。A2 的核心是设计约束，M3 实现可分阶段达成，但必须在文档/测试里承认原子性成熟度。

## 9. Symlink rollback 单独语义

symlink rollback 不能套用 copy tree restore，因为当前 symlink apply 的 backup 行为不同：

```text
if target was normal directory:
  backup directory exists
  symlink apply replaced it with managed symlink
if target was managed symlink:
  previous link is only held in memory during apply failure recovery
  old link target is not written to backup metadata
if target did not exist:
  backup directory missing
```

### 9.1 当前可安全支持的 symlink rollback

A2 初版只允许一种 symlink rollback 可执行场景：

```text
sync_mode == symlink
current target_state == managed_symlink
backup skill path exists as normal directory
backup recoverability in {restorable, metadata_missing}
```

决策：

```text
decision = restore_managed_symlink_to_tree
remove managed symlink
remove parent .<skill>.agentmesh-link.yaml
copy backup skill directory to target path
restore as ordinary directory
```

这表示“回到 symlink apply 前的普通目录”。它不是恢复 previous symlink。该 decision 必须由 symlink rollback executor 单独处理，不能复用普通 `restore_tree` 的“删除目录再 copy”逻辑。

### 9.2 当前必须 block 的 symlink 场景

以下必须 `block_symlink`：

- 当前 target 是 symlink，但没有匹配 link lock。
- 当前 target 是 managed symlink，但 backup skill path 不存在。
- history `sync_mode=symlink` 且 backup path 空。
- 需要恢复 previous symlink，但 metadata 不存在 previous link target。
- link lock 指向 source_path 但 source_path 已变化或不在 agentmesh_home skills root 内。
- target 不是 symlink，但 link lock 仍存在且与 target 不一致。

### 9.3 为什么不恢复 previous symlink

当前 `_apply_symlink_action()` 只在同一次 apply 失败恢复中持有：

```python
previous_link = target.readlink() if target.is_symlink() else None
```

成功 apply 后，history/backup 中没有 previous link。因此 rollback 不能知道旧 link target 是什么。猜测 previous link 会带来路径逃逸和误恢复风险。

未来若要支持 previous symlink rollback，必须在 backup metadata 中记录：

```yaml
before:
  type: symlink
  link_target: ...
  link_target_resolved: ...
  link_lock: ...
```

并经过 path confinement 与 source trust 检查。

## 10. JSON envelope: `agentmesh.rollback-plan/v1`

### 10.1 blocked 示例：metadata missing + managed drift

```json
{
  "schema": "agentmesh.rollback-plan/v1",
  "command": "rollback plan",
  "status": "blocked",
  "mode": "PLAN",
  "backup": {
    "backup_ref": "bkp-a1b2c3d4e5f6",
    "backup_id": "bkp-a1b2c3d4e5f6",
    "history_id": "sync-2026-04-30T12:00:00.123456+00:00",
    "backup_path": "/home/now/.agentmesh/backups/20260430-120000-123456",
    "sync_mode": "copy",
    "recoverability": "metadata_missing"
  },
  "summary": {
    "actions": 1,
    "executable": 0,
    "blocked": 1,
    "warnings": 1,
    "hard_blocks": 1
  },
  "actions": [
    {
      "action_id": "rb-112233445566",
      "target": "openclaw",
      "skill": "demo-skill",
      "target_path": "/home/now/.openclaw/workspace/skills/demo-skill",
      "backup_skill_path": "/home/now/.agentmesh/backups/20260430-120000-123456/openclaw/demo-skill",
      "target_state": "managed_drift",
      "recoverability": "metadata_missing",
      "decision": "block_drift",
      "hard_block": true,
      "reasons": ["target hash differs from AgentMesh lock"],
      "warnings": ["backup metadata is missing; only tree-level rollback could be planned if target were clean"]
    }
  ],
  "warnings": ["1 backup has no metadata."],
  "errors": [],
  "next_steps": ["Inspect target changes before attempting rollback again."]
}
```

### 10.2 executable 示例：旧 backup tree-level restore

```json
{
  "schema": "agentmesh.rollback-plan/v1",
  "command": "rollback plan",
  "status": "executable",
  "mode": "PLAN",
  "backup": {
    "backup_ref": "bkp-a1b2c3d4e5f6",
    "backup_id": "bkp-a1b2c3d4e5f6",
    "history_id": "sync-2026-04-30T12:00:00.123456+00:00",
    "backup_path": "/home/now/.agentmesh/backups/20260430-120000-123456",
    "sync_mode": "copy",
    "recoverability": "metadata_missing"
  },
  "summary": {
    "actions": 1,
    "executable": 1,
    "blocked": 0,
    "warnings": 1,
    "hard_blocks": 0
  },
  "actions": [
    {
      "action_id": "rb-112233445566",
      "target": "openclaw",
      "skill": "demo-skill",
      "target_path": "/home/now/.openclaw/workspace/skills/demo-skill",
      "backup_skill_path": "/home/now/.agentmesh/backups/20260430-120000-123456/openclaw/demo-skill",
      "target_state": "metadata_missing",
      "current_target_state": "managed_clean",
      "recoverability": "metadata_missing",
      "decision": "restore_tree",
      "hard_block": false,
      "reasons": ["target is managed clean", "backup skill tree exists"],
      "warnings": ["backup metadata is missing; rollback will restore the whole backup directory tree"]
    }
  ],
  "warnings": ["This is a conservative tree-level rollback plan."],
  "errors": [],
  "next_steps": ["Review this read-only plan, then run `rollback apply <backup-ref> --confirm` to execute after M3 rebuilds the plan."]
}
```

### 10.3 unsafe path 示例

```json
{
  "schema": "agentmesh.rollback-plan/v1",
  "command": "rollback plan",
  "status": "blocked",
  "mode": "PLAN",
  "backup": {
    "backup_ref": "/home/now/.openclaw/workspace/skills/demo-skill",
    "backup_id": null,
    "history_id": null,
    "backup_path": null,
    "sync_mode": "unknown",
    "recoverability": "unsafe_path"
  },
  "summary": {"actions": 0, "executable": 0, "blocked": 0, "warnings": 0, "hard_blocks": 1},
  "actions": [],
  "warnings": [],
  "errors": ["backup path is outside <agentmesh_home>/backups/ and was not inspected"],
  "next_steps": ["Use a backup id from `am backup list`."]
}
```

## 11. Human output contract

默认人类输出应先回答“能不能执行”：

```text
Rollback plan: BLOCKED
Backup: bkp-a1b2c3d4e5f6 (metadata_missing)

Actions
Target    Skill       State           Decision       Reason
openclaw  demo-skill  managed_drift   block_drift    target changed since lock

Hard blocks
- drift cannot be bypassed; inspect target changes first
```

可执行计划示例：

```text
Rollback plan: EXECUTABLE
Backup: bkp-a1b2c3d4e5f6 (metadata_missing)

Actions
Target    Skill       State              Decision
openclaw  demo-skill  metadata_missing   restore_tree

Warnings
- backup metadata is missing; this is tree-level restore only

Next
Review this plan. Run `rollback apply <backup-ref> --confirm` only after accepting that M3 will rebuild the plan and execute the freshly validated safe actions.
```

人类输出不能把 `metadata_missing` 美化成 `restorable`，也不能隐藏 hard block。

## 12. M2 只读要求

M2 `rollback plan` 必须满足：

| 约束 | 要求 |
| --- | --- |
| 不写 state | 不创建、不修改 `state/*`。 |
| 不写 backup | 不创建、不修复、不删除 `backups/*`。 |
| 不写 runtime | 不移动、不删除、不恢复 target。 |
| 不写 lock | 不创建、不更新 sidecar lock。 |
| 不联网 | 不访问 remote source。 |
| 不读 secret | 不读取模型配置、token、API key。 |
| 不绕过 path guard | unsafe path 不读取、不遍历。 |

M2 可以读取 live target 的 lock 与非 secret 文件内容用于 hash/drift 判定。这是 rollback 安全计划所必需的，但读取范围必须限制在 action 对应 target path 内。

## 13. M3 apply 要求

M3 `rollback apply` 必须：

1. 使用与 M2 相同的 `build_rollback_plan()`。
2. 在 apply 前重新 build plan。
3. 如果 plan.status 不是 `executable`，立即停止。
4. 如果任一 action `hard_block=true`，立即停止。
5. 要求显式 `--confirm`。
6. 只执行 `decision in {restore_tree, restore_managed_symlink_to_tree}` 且 `hard_block=false` 的 action；其中 `restore_managed_symlink_to_tree` 必须进入第 9 节定义的 symlink 专用 executor。
7. 写入 rollback history（M3 另行细化 schema）。
8. 输出 apply result JSON，不复用 plan JSON 假装已执行。
9. 在删除或替换 live target 前保存当前 target snapshot；如果 restore、lock 写入或 history 写入失败，必须尽力从 snapshot 恢复 current target，并以 blocked/error 结果暴露失败。

M3 不能：

- 执行旧 plan 文件。
- 在遇到 drift/unmanaged/unsafe_path 时继续执行其他 action，除非未来设计支持显式 partial apply；A2 默认 all-or-nothing。
- 因为用户传了 `--confirm` 就改变 decision。
- 读取或写入 backups root 外的路径。

## 14. 错误与 warning 策略

| 情况 | plan status | action decision / error |
| --- | --- | --- |
| backup_ref 无匹配 | `error` | `backup_not_found` |
| backup_id 多匹配 | `error` | `ambiguous_backup` |
| history_id 多匹配 | `error` | `ambiguous_history` |
| history 缺 backup | `error` | `not_rollback_eligible` |
| backup path 越界 | `blocked` | `block_unsafe_path` |
| backup path missing | `blocked` | `block_missing_path` |
| backup metadata missing | `executable` 或 `blocked` | 取决于 target state 与 backup tree 是否足够支持 tree restore |
| backup root empty | `blocked` | `block_empty_backup` |
| recoverability unknown | `blocked` | `block_unknown` |
| target managed drift | `blocked` | `block_drift` |
| target unmanaged | `blocked` | `block_unmanaged` |
| target missing | `executable` 或 `blocked` | 取决于 backup tree / metadata |
| managed symlink | `executable` 或 `blocked` | 只按第 9 节语义处理 |

## 15. 与 A1 Backup History 的接口

A2 复用 A1：

```text
backup_id
history_id
backup_path
recoverability
action_refs
sync_mode
```

但 A2 必须重新验证：

- `backup_path` 是否仍在 `<agentmesh_home>/backups/`。
- `backup_path` 是否仍存在。
- 每个 action 的 backup skill path 是否存在。
- 当前 target 是否 `managed_clean` / `managed_drift` / `unmanaged` / `missing` / `managed_symlink`。
- `sync_mode` 是否与 symlink/copy 语义一致。

A1 的 `recoverability` 不是执行许可；它只是 A2 builder 的输入之一。

## 16. 非目标

A2 不做：

- 不实现 `am rollback plan`。
- 不实现 `am rollback apply`。
- 不新增 `rollback_service.py`。
- 不迁移 existing backup layout。
- 不生成 `backup.yaml` / `restore.yaml` / `plan.yaml`。
- 不迁移 central lock。
- 不实现 force override。
- 不实现 prompt/runtime rollback。
- 不改变 `sync_service.py`。
- 不改变现有测试预期。

## 16.1 当前 M3 实现范围

当前 M3 已实现：

- `am rollback apply <backup-ref> --confirm [--json]`。
- apply 前重新调用共享 `build_rollback_plan()`。
- 只执行 `restore_tree` / `restore_managed_symlink_to_tree`。
- 在 apply 前 snapshot current target 到 `<agentmesh_home>/backups/rollback-current/...`。
- restore / lock / rollback history 写入失败时尽力恢复 snapshot，并返回 `apply_failed_recovered` 或 `apply_failed_recovery_failed`。
- 追加写入 `<agentmesh_home>/state/rollback-history.jsonl`。

当前 M3 仍不做：

- force override。
- partial apply。
- previous symlink target rollback。
- backup layout 迁移或 central lock 迁移。

## 17. M2 / M3 实现建议

M2/M3 后续实现建议新增：

```text
src/agentmesh/services/backup_service.py      # 若 M1 尚未实现，可先承载 BackupRecord projection
src/agentmesh/services/rollback_service.py
src/agentmesh/cli/main.py                    # rollback app / commands
tests/test_rollback_cli.py
tests/test_rollback_service.py
```

建议实现顺序：

1. 从 A1 BackupRecord projection 开始，解析 `backup_ref`。
2. 实现 path confinement，先测 `unsafe_path`。
3. 实现 target state classifier。
4. 实现 recoverability -> decision mapper。
5. 实现 `rollback plan --json` envelope。
6. 实现人类输出。
7. 实现 M2 只读副作用测试。
8. 实现 M3 apply 前重新 build plan 测试。
9. 实现 tree-level restore executor。
10. 实现 symlink rollback 可执行/阻断测试。

## 18. A2 验收清单

- [x] 定义 rollback plan / rollback apply 共享 plan builder。
- [x] 定义 `backup_id` / `history_id` / `backup_path` 解析规则。
- [x] 明确所有 backup path 必须限制在 `<agentmesh_home>/backups/`。
- [x] 定义 target state：`managed_clean`、`managed_drift`、`unmanaged`、`missing`、`backup_missing`、`metadata_missing`、`managed_symlink`、`unsafe_path`。
- [x] 定义 recoverability -> rollback decision 映射。
- [x] 定义 symlink rollback 单独语义。
- [x] 明确 M2 只读。
- [x] 明确 M3 apply 前重新 build plan。
- [x] 明确 drift / unmanaged / hard block 不可绕过。
- [x] 包含 JSON 示例与 human output contract。
- [x] 明确非目标，不把 A2 文档误写成实现完成。

## 19. 参考

- `docs/design/state-reality-and-migration.md`
- `docs/design/backup-history.md`
- `src/agentmesh/services/sync_service.py`
- `tests/test_safe_apply.py`
- `tests/test_history_cli.py`
