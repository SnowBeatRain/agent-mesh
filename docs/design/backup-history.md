# AgentMesh Backup History Contract

> 目的：定义 M1 `am backup list` 的只读数据契约。本文只设计 `SyncHistoryEntry -> BackupRecord` 投影、`backup_id` 规则、recoverability 判定和 JSON envelope；不实现 CLI，不修改现有 history，不扫描 runtime，不执行 rollback。

## 1. 背景与边界

A0 `state-reality-and-migration.md` 已确认当前现实：

```text
state/sync-history.jsonl
backups/<timestamp>/<target>/<skill>/
```

当前 `skills sync --apply` 成功后会写一条 history entry，其中：

```json
{
  "schema": "agentmesh.sync-history-entry/v1",
  "id": "sync-<iso timestamp>",
  "timestamp": "<iso timestamp>",
  "operation": "skills sync",
  "status": "applied",
  "targets": ["openclaw"],
  "sync_mode": "copy",
  "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
  "backup": "<agentmesh_home>/backups/<timestamp>",
  "actions": []
}
```

这条记录足以回答“曾经有一次 apply，它声明了一个 backup root”，但还不足以证明 backup 一定完整、可恢复、含 metadata。

因此 M1 `am backup list` 的本质是：

```text
读取 sync-history.jsonl
  → 过滤成功 apply 且带 backup 字段的 entry
  → 对每条 entry 构造 BackupRecord
  → 检查 backup path 的最小可恢复性
  → 输出只读列表
```

它不是：

```text
history list 改名
runtime 目录扫描
rollback dry-run
backup 校验/清理/保留策略
```

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| `SyncHistoryEntry` | `state/sync-history.jsonl` 中的一行 JSON。当前只记录 successful apply。 |
| `backup_path` | history entry 的 `backup` 字段，指向 `backups/<timestamp>`。 |
| `backup_id` | M1/M2/M3 使用的稳定引用 ID，由 A1 定义。 |
| `BackupRecord` | 从 SyncHistoryEntry 投影出的用户级 backup 列表项。 |
| `recoverability` | 对 backup path 当前是否可用于后续 rollback plan 的保守判断。 |
| `metadata` | 未来可能存在的 `backup.yaml` / `restore.yaml` / `plan.yaml`；当前不存在。 |

## 3. 数据源

M1 只允许读取：

```text
<agentmesh_home>/state/sync-history.jsonl
<backup_path>/
```

其中 `<backup_path>` 来自 history entry 的 `backup` 字段。

### 3.1 backup path confinement

`backup_path` 虽然来自 AgentMesh 自己写入的 history，但 M1 仍必须把 history 当作不可信输入处理。实现时必须：

```text
backups_root = (<agentmesh_home>/backups).resolve()
candidate = Path(backup_path).expanduser().resolve()
candidate must be inside backups_root
```

如果 `candidate` 不在 `<agentmesh_home>/backups/` 内，M1 必须：

- 不读取该路径。
- 不遍历该路径。
- 不把它当作有效 backup。
- 输出 record-level `recoverability.status = unsafe_path`。
- 在 warnings 中说明该 path 因隐私与路径安全原因未被检查。

这条规则优先级高于 `missing_path`、`empty_backup` 和 metadata 探测。也就是说，路径越界时不能先检查“是否存在”。

M1 禁止读取或扫描：

```text
~/.hermes/...
~/.openclaw/...
~/.codex/...
~/.claude/...
任何 runtime live target
任何网络地址
任何 token / secret 配置
```

M1 也不应读取 `state/skills.yaml`、`state/prompts.yaml` 或 `state/runtime-load-plans/*` 来推断 backup。这些是相邻能力，不是 backup list 的事实源。

## 4. SyncHistoryEntry 兼容输入

### 4.1 当前标准 entry

当前标准 entry 必须尽量包含：

| 字段 | 类型 | 当前来源 | M1 用途 |
| --- | --- | --- | --- |
| `schema` | string | `_append_sync_history()` | 识别版本 |
| `id` | string | `sync-<iso timestamp>` | `history_id` |
| `timestamp` | string | ISO timestamp | `created_at` |
| `operation` | string | `skills sync` | 过滤 sync apply |
| `status` | string | `applied` | 过滤成功 apply |
| `targets` | string[] | CLI targets | record targets |
| `sync_mode` | string | `copy` / `symlink` | recoverability hints |
| `summary` | object | rendered plan summary | action counts |
| `backup` | string/null | backup root path | backup path |
| `actions` | object[] | rendered actions | target/skill projection hints |

### 4.2 旧 entry / 不完整 entry

M1 必须容忍旧 entry 或手工损坏 entry：

| 情况 | 处理 |
| --- | --- |
| 空行 | 跳过 |
| JSON parse failure | 记录 warning，跳过该行 |
| 缺 `id` | 用行号与 timestamp 生成 legacy history id |
| 缺 `timestamp` | `created_at` 为 null，加入 warning |
| 缺 `backup` | 不生成 BackupRecord，计入 `skipped.unbacked_history_entries`，并在 warnings 中说明；未来可用 `--include-unbacked` 显示 |
| `backup` 不是字符串 | 跳过并 warning |
| `backup` 指向 `<agentmesh_home>/backups/` 外 | 不读取该路径，输出 `unsafe_path` record 或跳过并 warning；推荐输出 record 以便用户看见损坏 history |
| `status != applied` | M1 默认跳过 |
| `operation != skills sync` | M1 默认跳过 |

M1 不修改旧 entry，也不回填 metadata。

## 5. BackupRecord schema

### 5.1 逻辑模型

```yaml
BackupRecord:
  backup_id: string
  history_id: string
  created_at: string | null
  operation: string
  status: string
  sync_mode: copy | symlink | unknown
  backup_path: string
  targets: string[]
  summary:
    actions: integer
    allowed: integer
    blocked: integer
    warnings: integer
  action_refs:
    - target: string
      skill: string
      target_path: string | null
      decision: string | null
  recoverability:
    status: restorable | partial | metadata_missing | missing_path | empty_backup | unsafe_path | unknown
    reasons: string[]
    warnings: string[]
  metadata:
    present: boolean
    schema: string | null
    path: string | null
```

### 5.2 字段说明

| 字段 | 说明 |
| --- | --- |
| `backup_id` | 用户后续传给 `am rollback plan <backup>` 的默认 ID。 |
| `history_id` | 原始 sync history id。 |
| `created_at` | 优先使用 history `timestamp`。 |
| `operation` | 当前应为 `skills sync`。 |
| `status` | 当前应为 `applied`。 |
| `sync_mode` | 当前为 `copy` 或 `symlink`；缺失时为 `unknown`。 |
| `backup_path` | 原始 backup root path，输出时可以保留绝对路径；未来 UI 可做 path redaction。 |
| `targets` | history `targets`。 |
| `summary` | history summary 的安全子集。 |
| `action_refs` | 从 history actions 提取 target/skill 等引用，不能作为完整 restore plan。 |
| `recoverability` | M1 的核心用户价值：告诉用户这条 backup 当前有多可信。 |
| `metadata` | 未来 metadata 探测结果。当前通常 `present=false`。 |

## 6. backup_id 规则

### 6.1 设计目标

`backup_id` 必须：

1. 对同一个 history entry 稳定。
2. 对用户短而可读。
3. 能在 M2/M3 中解析。
4. 不依赖 backup path 永远存在。
5. 能兼容旧 history。

### 6.2 规则

推荐规则：

```text
backup_id = "bkp-" + short_hash(history_id + "\0" + backup_path)
```

其中：

```text
short_hash = sha256(...)[0:12]
```

示例：

```text
history_id = sync-2026-04-30T12:00:00.123456+00:00
backup_path = /home/now/.agentmesh/backups/20260430-120000-123456
backup_id = bkp-a1b2c3d4e5f6
```

### 6.3 为什么不用 history id 直接作为 backup id

当前 history id 与 backup directory timestamp 不是同一个值：

```text
history id = sync-<iso timestamp>
backup path = backups/<YYYYMMDD-HHMMSS-ffffff>
```

直接使用 history id 会让用户误以为它就是 backup directory 名；直接使用 directory name 又不能处理多个 history 指向同一路径或路径移动的情况。因此 A1 用派生 ID。

### 6.4 M2 解析策略预留

后续 `am rollback plan <backup>` 应接受：

```text
bkp-a1b2c3d4e5f6              # backup_id
sync-2026-...                 # history_id，可作为兼容输入
/path/to/.agentmesh/backups/... # backup path
```

M1 只定义 ID，不实现解析。

### 6.5 冲突处理

`backup_id` 使用 12 位 hex short hash，实际冲突概率很低，但契约仍必须定义冲突行为：

- M1 如果发现同一次 list 输出中存在重复 `backup_id`，必须把重复项标记为 ambiguous。
- CLI 人类输出应提示用户改用完整 `history_id` 或 `backup_path`。
- M2/M3 解析 `backup_id` 时，如果匹配多条记录，必须返回 ambiguous error，不能默认取第一条。
- 实现可以在冲突时临时显示更长 hash，但不能改变已经输出给用户的旧 `backup_id` 解析语义。

## 7. recoverability

### 7.1 状态枚举

| 状态 | 含义 | M2 默认行为 |
| --- | --- | --- |
| `restorable` | backup path 存在，含至少一个可候选恢复的 target/skill 目录，且 metadata 存在并可读。 | 可进入 rollback plan。 |
| `metadata_missing` | backup path 存在且有内容，但缺少标准 backup metadata。当前旧 backup 通常是这个状态。 | 可进入保守 tree-level plan，但必须 warning。 |
| `partial` | backup path 存在，但 action refs 与实际 backup 内容不完全匹配，或部分 target/skill 缺失。 | M2 应 warn 或 block，取决于缺失程度。 |
| `missing_path` | history 声明了 backup path，但路径不存在。 | M2 block。 |
| `empty_backup` | backup path 存在但没有任何可候选恢复内容。 | M2 block 或仅显示不可恢复。 |
| `unsafe_path` | history 声明的 backup path 不在 `<agentmesh_home>/backups/` 内；M1 未读取该路径。 | M2 hard block。 |
| `unknown` | history 信息不足，无法判断。 | M2 block，除非用户显式 path ref 且 plan 能重新验证且 path 仍在允许 root 内。 |

> 说明：A 阶段计划要求至少定义 `restorable`、`partial`、`metadata_missing`、`missing_path`。A1 额外定义 `empty_backup` 和 `unknown`，用于更清楚表达旧状态。

### 7.2 当前版本的判定算法

M1 初版判定应保守：

```text
if backup_path is outside <agentmesh_home>/backups after resolve:
  status = unsafe_path
elif backup_path missing on disk:
  status = missing_path
elif backup_path exists but has no child entries:
  status = empty_backup
elif metadata exists and readable and at least one candidate target/skill exists:
  status = restorable
elif backup_path exists and has at least one child entry but no metadata:
  if actions can be mapped to existing target/skill backup dirs:
    status = metadata_missing
  else:
    status = partial
else:
  status = unknown
```

实际实现时，`unsafe_path` 判断必须发生在任何 filesystem existence/listing 检查之前。

### 7.3 metadata 探测

未来标准 metadata 文件名暂定：

```text
backup.yaml
restore.yaml
plan.yaml
```

M1 只探测 presence，不定义完整 metadata schema。A1 不要求创建这些文件。

当前旧 backup 通常没有 metadata，因此应输出：

```json
"recoverability": {
  "status": "metadata_missing",
  "reasons": ["backup metadata is not present; tree-level rollback only"],
  "warnings": ["This backup was created by a pre-manifest sync flow."]
}
```

## 8. copy 与 symlink backup 差异

### 8.1 copy mode

copy apply 当前行为：

```text
if target exists and is not symlink:
  copytree(target, backups/<timestamp>/<target>/<skill>/)
```

因此 copy backup 可能包含旧 target 的目录树，包括旧 `.agentmesh-lock.yaml`。

M1 判断：

- 若目录存在且非空：通常 `metadata_missing`。
- 若 action refs 指向多个 skill，但只找到部分目录：`partial`。
- 若 target 原本不存在：可能没有对应目录；这不一定代表失败，但当前没有 metadata 证明“原本不存在”。M1 应记录 warning。

### 8.2 symlink mode

symlink apply 当前行为：

```text
if target exists and is not symlink:
  copytree(target, backups/<timestamp>/<target>/<skill>/)
if target is symlink:
  previous_link = target.readlink()
  # 不把 symlink 本身写入 backup directory
```

因此 symlink backup 有特殊风险：

- 如果 symlink 替换的是普通目录，backup 目录存在。
- 如果 symlink 替换的是已有 managed symlink，backup 目录可能不存在。
- 当前没有 metadata 保存 previous link；只有 apply 失败恢复时在内存变量中使用。

M1 判断：

- `sync_mode=symlink` 且 backup path 有内容：最多 `metadata_missing`，并 warning symlink restore needs A2 contract。
- `sync_mode=symlink` 且 backup path 空：`empty_backup` 或 `partial`，并说明 symlink target may not have directory backup。
- M1 不承诺 symlink rollback 可恢复原 link。

## 9. action_refs 投影规则

从 `history.actions` 中提取安全引用：

| action 字段 | BackupRecord 字段 | 说明 |
| --- | --- | --- |
| `skill` | `action_refs[].skill` | 用于定位 `<backup_path>/<target>/<skill>` 候选目录。 |
| `to` | `action_refs[].target` | 当前 sync target 名。 |
| `target_path` | `action_refs[].target_path` | 仅展示；M1 不读取该路径。 |
| `decision` | `action_refs[].decision` | 当前成功 apply 通常应为 allow。 |

M1 不应信任 action refs 作为完整恢复计划，因为：

- actions 是 rendered plan 的 JSON-safe 复制，不是 restore manifest。
- 它描述 apply 意图，不描述 backup 内容。
- 它没有记录原 target 是否存在、是否 symlink、lock before/after。

## 10. JSON envelope: `agentmesh.backup-list/v1`

### 10.1 通用结构

```json
{
  "schema": "agentmesh.backup-list/v1",
  "command": "backup list",
  "status": "ok",
  "data": {
    "backups": []
  },
  "summary": {
    "total": 0,
    "restorable": 0,
    "partial": 0,
    "metadata_missing": 0,
    "missing_path": 0,
    "empty_backup": 0,
    "unsafe_path": 0,
    "unknown": 0,
    "skipped": {
      "invalid_json_lines": 0,
      "unbacked_history_entries": 0,
      "non_applied_entries": 0,
      "non_sync_entries": 0
    }
  },
  "warnings": [],
  "errors": [],
  "next_steps": []
}
```

### 10.2 空列表示例

```json
{
  "schema": "agentmesh.backup-list/v1",
  "command": "backup list",
  "status": "ok",
  "data": {"backups": []},
  "summary": {
    "total": 0,
    "restorable": 0,
    "partial": 0,
    "metadata_missing": 0,
    "missing_path": 0,
    "empty_backup": 0,
    "unsafe_path": 0,
    "unknown": 0,
    "skipped": {
      "invalid_json_lines": 0,
      "unbacked_history_entries": 0,
      "non_applied_entries": 0,
      "non_sync_entries": 0
    }
  },
  "warnings": [],
  "errors": [],
  "next_steps": ["Run `am skills sync --apply` to create backups before listing them."]
}
```

### 10.3 正常旧 backup 示例

当前没有 metadata 的旧 backup 应这样表达，而不是假装 fully restorable：

```json
{
  "schema": "agentmesh.backup-list/v1",
  "command": "backup list",
  "status": "ok",
  "data": {
    "backups": [
      {
        "backup_id": "bkp-a1b2c3d4e5f6",
        "history_id": "sync-2026-04-30T12:00:00.123456+00:00",
        "created_at": "2026-04-30T12:00:00.123456+00:00",
        "operation": "skills sync",
        "status": "applied",
        "sync_mode": "copy",
        "backup_path": "/home/now/.agentmesh/backups/20260430-120000-123456",
        "targets": ["openclaw"],
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "action_refs": [
          {
            "target": "openclaw",
            "skill": "demo-skill",
            "target_path": "/home/now/.openclaw/workspace/skills/demo-skill",
            "decision": "allow"
          }
        ],
        "recoverability": {
          "status": "metadata_missing",
          "reasons": ["backup metadata is not present"],
          "warnings": ["Only conservative tree-level rollback can be planned from this backup."]
        },
        "metadata": {"present": false, "schema": null, "path": null}
      }
    ]
  },
  "summary": {
    "total": 1,
    "restorable": 0,
    "partial": 0,
    "metadata_missing": 1,
    "missing_path": 0,
    "empty_backup": 0,
    "unsafe_path": 0,
    "unknown": 0,
    "skipped": {
      "invalid_json_lines": 0,
      "unbacked_history_entries": 0,
      "non_applied_entries": 0,
      "non_sync_entries": 0
    }
  },
  "warnings": [],
  "errors": [],
  "next_steps": ["Run `am rollback plan bkp-a1b2c3d4e5f6` after rollback planning is implemented."]
}
```

### 10.4 missing backup path 示例

```json
{
  "schema": "agentmesh.backup-list/v1",
  "command": "backup list",
  "status": "ok",
  "data": {
    "backups": [
      {
        "backup_id": "bkp-deadbeef0001",
        "history_id": "sync-2026-04-30T12:00:00.123456+00:00",
        "created_at": "2026-04-30T12:00:00.123456+00:00",
        "operation": "skills sync",
        "status": "applied",
        "sync_mode": "copy",
        "backup_path": "/home/now/.agentmesh/backups/20260430-120000-123456",
        "targets": ["openclaw"],
        "summary": {"actions": 1, "allowed": 1, "blocked": 0, "warnings": 0},
        "action_refs": [],
        "recoverability": {
          "status": "missing_path",
          "reasons": ["backup path does not exist on disk"],
          "warnings": ["Rollback must be blocked for this backup unless a valid backup path is provided explicitly."]
        },
        "metadata": {"present": false, "schema": null, "path": null}
      }
    ]
  },
  "summary": {
    "total": 1,
    "restorable": 0,
    "partial": 0,
    "metadata_missing": 0,
    "missing_path": 1,
    "empty_backup": 0,
    "unsafe_path": 0,
    "unknown": 0,
    "skipped": {
      "invalid_json_lines": 0,
      "unbacked_history_entries": 0,
      "non_applied_entries": 0,
      "non_sync_entries": 0
    }
  },
  "warnings": ["1 backup record points to a missing path."],
  "errors": [],
  "next_steps": ["Check whether the backup directory was moved or deleted."]
}
```

## 11. Human output contract

默认人类输出应短、可扫读：

```text
Backups

ID             Created at                    Mode    Recoverability     Targets
bkp-a1b2c3...  2026-04-30T12:00:00+00:00     copy    metadata_missing   openclaw
bkp-deadbee... 2026-04-30T13:00:00+00:00     copy    missing_path       codex

Warnings:
- 1 backup has no metadata; rollback will be conservative.
- 1 backup path is missing; rollback will be blocked.
```

人类输出不应隐藏 `metadata_missing`，避免用户误以为 backup 已完全可恢复。

## 12. 只读与安全约束

M1 必须满足：

| 约束 | 要求 |
| --- | --- |
| 不写 state | 不创建、不修改 `state/*`。 |
| 不写 backup | 不创建、不修复、不删除 `backups/*`。 |
| 不读 runtime | 不扫描 `~/.hermes` / `~/.openclaw` / `~/.codex` / `~/.claude`。 |
| 不联网 | 不访问 remote source。 |
| 不读 secret | 不读取模型配置、token、API key。 |
| 不 rollback | 不移动、不删除、不恢复任何 target。 |
| 不 retention | 不做 backup 清理策略。 |

## 13. 错误与 warning 策略

| 情况 | status | warnings/errors |
| --- | --- | --- |
| history 文件不存在 | `ok` | next_steps 提示暂无 backup。 |
| history 文件为空 | `ok` | next_steps 提示暂无 backup。 |
| 部分行 JSON 损坏 | `ok` | warnings 记录跳过行数。 |
| 全部行损坏 | `ok` 或 `error` | 建议 M1 返回 `ok` + warnings + 空列表，除非无法读取文件。 |
| history 文件权限不可读 | `error` | errors 包含 path 与原因。 |
| backup path missing | `ok` | record recoverability = `missing_path`。 |
| backup path outside `<agentmesh_home>/backups/` | `ok` | record recoverability = `unsafe_path`；不得读取该路径。 |
| metadata 缺失 | `ok` | record recoverability = `metadata_missing`。 |

M1 的用户价值是“可见性”，所以尽量以 record-level recoverability 表达问题，而不是整体失败。

## 14. 与 A2 Rollback Contract 的接口

A1 向 A2 提供三类输入：

```text
backup_id
history_id
backup_path
```

A2 必须重新验证：

- backup path 是否仍在 `<agentmesh_home>/backups/` 内；
- backup path 是否存在；
- current target 是否 managed；
- current target 是否 drift；
- backup 内容是否能构造 tree-level restore；
- symlink mode 是否应 block 或特殊处理。

A1 不替 A2 作出 restore action decision。

## 15. 非目标

A1 不做：

- 不实现 `am backup list`。
- 不新增 `backup_service.py`。
- 不实现 rollback。
- 不生成 backup metadata。
- 不迁移旧 history。
- 不清理旧 backup。
- 不改变 `sync_service.py`。
- 不改变现有测试预期。

## 16. M1 实现建议

M1 后续实现时建议新增：

```text
src/agentmesh/services/backup_service.py
tests/test_backup_cli.py
```

核心函数可为：

```python
def list_backup_records(agentmesh_home: Path) -> dict:
    ...
```

实现顺序建议：

1. 读取 history。
2. 过滤 successful sync entries with backup。
3. 生成 stable `backup_id`。
4. 提取 `action_refs`。
5. 判定 `recoverability`。
6. 输出 `agentmesh.backup-list/v1` envelope。
7. CLI 人类输出。
8. 测试只读副作用。

## 17. A1 验收清单

- [x] 定义 `SyncHistoryEntry -> BackupRecord` projection。
- [x] 定义 `backup_id` 规则。
- [x] 定义 backup path 存在/缺失/空目录/metadata 缺失/路径越界时的 `recoverability`。
- [x] 定义 copy/symlink backup 差异。
- [x] 定义旧 history 兼容策略。
- [x] 定义 `agentmesh.backup-list/v1` JSON envelope。
- [x] 至少定义 4 种 recoverability。
- [x] JSON 示例覆盖空列表、正常 backup、missing backup path。
- [x] 明确 M1 只读，不扫描 home，不读写 runtime，不做 retention。

## 18. 参考

- `docs/design/state-reality-and-migration.md`
- `brainstorm/task/agentmesh-architecture-led-delivery-plan.md`
- `src/agentmesh/services/sync_service.py`
- `tests/test_history_cli.py`
- `tests/test_safe_apply.py`
