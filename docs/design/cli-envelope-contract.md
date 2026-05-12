# CLI Envelope Contract

## 范围

定义 AgentMesh 所有 `--json` 输出的统一信封规范，避免各命令自行发明字段名和状态语义。

本文是 A3 架构校准里程碑的输出，只约束 JSON envelope 格式，不改变已有命令的输入参数或人类输出格式。

## 当前现实

截至 `c7ac229 docs: sync AgentMesh milestone status`，`src/agentmesh/cli/main.py` 有 1616 行，包含 23 个 `--json` 输出 schema。envelope 字段分散在 `cli/main.py` 和各 `services/*.py` 中构造，没有统一的 helper 函数或类型定义。

当前 23 个 schema：

```text
agentmesh.agents-contract/v1
agentmesh.agents-list/v1
agentmesh.audit-all/v1
agentmesh.backup-list/v1
agentmesh.doctor/v1
agentmesh.history-list/v1
agentmesh.local-status/v1
agentmesh.overview/v1
agentmesh.package-inspect/v1
agentmesh.package-verify/v1
agentmesh.prompts-disable/v1
agentmesh.prompts-enable/v1
agentmesh.prompts-list/v1
agentmesh.prompts-status/v1
agentmesh.prompts/v1
agentmesh.skills-conflicts/v1
agentmesh.skills-diff/v1
agentmesh.skills-export/v1
agentmesh.skills-import-package/v1
agentmesh.skills-list/v1
agentmesh.skills-scan/v1
agentmesh.skills-state/v1
agentmesh.skills-sync/v1
agentmesh.update-check/v1
```

## 统一 Envelope 规范

### 顶级字段

每个 `--json` 输出必须包含以下字段，不可省略：

```json
{
  "schema": "agentmesh.<command>/v1",
  "command": "<group> <subcommand>",
  "status": "<status-value>",
  "data": { ... },
  "summary": { ... },
  "warnings": [],
  "errors": [],
  "next_steps": []
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema` | string | 唯一标识此命令的 JSON schema，格式 `agentmesh.<command>/v1` |
| `command` | string | 用户执行的命令文本，如 `backup list`、`skills sync` |
| `status` | string | 命令级别的执行状态，取值见下方状态枚举 |
| `data` | object | 命令的核心输出数据，结构因命令而异 |
| `summary` | object | 人类可读的摘要计数，字段因命令而异 |
| `warnings` | string[] | 不阻止执行但需要用户注意的信息 |
| `errors` | string[] | 阻止执行或导致失败的原因 |
| `next_steps` | string[] | 建议用户接下来做什么 |

部分命令有额外顶级字段（如 rollback 的 `mode`、`backup`、`actions`），这些是命令特有数据，不属于通用 envelope，但应放在 `data` 内或与 `data` 平级且有明确语义。

### 状态枚举

命令级 `status` 只允许以下值：

| status | 语义 | 典型场景 |
| --- | --- | --- |
| `ok` | 命令成功完成 | 只读查询、dry-run 预览、apply 成功 |
| `planned` | 生成了计划但未执行 | `sync --dry-run`、`rollback plan` |
| `applied` | 写入操作已执行 | `sync --apply`、`rollback apply` 成功 |
| `blocked` | 有 hard block 阻止执行 | drift unmanaged、policy blocked |
| `error` | 输入错误或运行时异常 | 参数缺失、文件不存在、备份找不到 |

注意：`status` 只描述命令执行结果，不描述子资源状态。子资源状态（如 backup 的 `recoverability`、skill 的 update check 状态）放在 `data` 内，使用各自的语义字段。

当前代码中已有的子资源状态值（不作为命令级 status）：

- `restorable` / `partial` / `metadata_missing` / `missing_path` / `empty_backup` / `unsafe_path` — backup recoverability
- `passed` / `skipped` / `unknown` / `candidate` / `unsupported` — update check / verify
- `executable` — rollback plan 内部状态

这些保持不变，但命令级 `status` 必须映射到上表的 5 个值之一。

### 已有偏差与修正

| 当前 | 问题 | 修正 |
| --- | --- | --- |
| rollback plan 成功时 status=`executable` | 不在枚举内 | 改为 `ok`，executable 放 `data.summary` |
| rollback plan 有 hard block 时 status=`blocked` | ✅ 符合 | 保持 |
| rollback apply 有 hard block 时 status=`blocked` | ✅ 符合 | 保持 |
| 部分 schema 命名不一致（`agentmesh.prompts/v1` vs `agentmesh.prompts-list/v1`） | 命名风格不统一 | 统一为 `<group>-<subcommand>/v1` |
| 部分 envelope 缺少 `command` 字段 | 不可追溯 | 补齐 |
| 部分 envelope 缺少 `next_steps` | 用户不知道下一步 | 补齐 |

### data 与 summary 的边界

- `data` 放结构化业务数据：记录列表、动作列表、plan、verify 结果等
- `summary` 放计数和人类摘要：total、allowed、blocked、passed 等
- `warnings` / `errors` / `next_steps` 放字符串，不放结构化数据

### 嵌套动作的 envelope

sync / rollback 等包含多个 action 的命令，每个 action 应包含：

```json
{
  "action": "copy|symlink|restore_tree|...",
  "skill": "<name>",
  "to": "<target>",
  "target_path": "<abs-path>",
  "decision": "allow|block|warn",
  "hard_block": false,
  "reasons": [],
  "warnings": []
}
```

当前 rollback service 和 sync service 已基本遵循此结构。

## 实现策略

### 不做的事

- **不一次性重写所有 23 个 schema。** 现有 envelope 虽然有偏差，但功能正确。
- **不改 `--json` 以外的人类输出格式。**
- **不改 CLI 入参。**

### 渐进修正

1. 新增 `src/agentmesh/cli/envelope.py`，提供 `build_envelope(schema, command, status, data, summary, *, warnings=None, errors=None, next_steps=None)` helper。
2. 新命令和修改已有命令时，逐步迁移到 helper。
3. 不做批量重写 PR；在日常开发中逐步统一。

### helper 函数签名

```python
def build_envelope(
    schema: str,
    command: str,
    status: Literal["ok", "planned", "applied", "blocked", "error"],
    data: dict,
    summary: dict,
    *,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> dict:
    ...
```

未来可加 JSON schema 校验、字段缺失检查等，但初版只做统一构造。

## Schema 命名规范

格式：`agentmesh.<group>-<subcommand>/v1`

| 命令 | schema |
| --- | --- |
| `am overview` | `agentmesh.overview/v1` |
| `am agents list` | `agentmesh.agents-list/v1` |
| `am agents contract` | `agentmesh.agents-contract/v1` |
| `am skills scan` | `agentmesh.skills-scan/v1` |
| `am skills list` | `agentmesh.skills-list/v1` |
| `am skills sync --dry-run` | `agentmesh.skills-sync/v1` |
| `am skills sync --apply` | `agentmesh.skills-sync/v1` |
| `am skills diff` | `agentmesh.skills-diff/v1` |
| `am skills conflicts` | `agentmesh.skills-conflicts/v1` |
| `am skills export` | `agentmesh.skills-export/v1` |
| `am skills import-package` | `agentmesh.skills-import-package/v1` |
| `am skills update-check` | `agentmesh.update-check/v1` |
| `am skills enable` | `agentmesh.skills-state/v1` |
| `am skills disable` | `agentmesh.skills-state/v1` |
| `am skills status` | `agentmesh.skills-state/v1` |
| `am skills validate` | `agentmesh.skills-validate/v1` |
| `am prompts list` | `agentmesh.prompts-list/v1` |
| `am prompts enable` | `agentmesh.prompts-enable/v1` |
| `am prompts status` | `agentmesh.prompts-status/v1` |
| `am prompts disable` | `agentmesh.prompts-disable/v1` |
| `am package inspect` | `agentmesh.package-inspect/v1` |
| `am package verify` | `agentmesh.package-verify/v1` |
| `am backup list` | `agentmesh.backup-list/v1` |
| `am rollback plan` | `agentmesh.rollback-plan/v1` |
| `am rollback apply` | `agentmesh.rollback-apply/v1` |
| `am history list` | `agentmesh.history-list/v1` |
| `am audit` | `agentmesh.audit-all/v1` |
| `am doctor` | `agentmesh.doctor/v1` |
| `am local status` | `agentmesh.local-status/v1` |

同一命令的不同模式（dry-run vs apply）使用同一 schema，通过 `status` 字段区分 `planned` / `applied`。

rollback plan 使用 `agentmesh.rollback-plan/v1`，rollback apply 使用 `agentmesh.rollback-apply/v1`。二者复用同一个 plan builder 保持恢复语义一致，但 JSON schema 分别表达只读计划与写入执行结果。

## Exit Code 规范

当前所有错误场景统一 exit 1，成功统一 exit 0。未来可扩展：

| exit code | 含义 |
| --- | --- |
| 0 | 成功（`ok` / `planned` / `applied`） |
| 1 | 错误（`error`） |
| 2 | 阻塞（`blocked`） |
| 3 | 有 warning 但完成了 |

暂不实现，等 `--quiet` / `--verbose` 一起做。当前保持 exit 0 / 1。

## 非目标

- 不定义 JSON Schema Draft 校验文件。envelope 规范以本文为准。
- 不要求所有命令都输出 `--json`。只读命令和写入命令必须有；辅助命令（`init`、`--version`）可选。
- 不改变 runtime alpha 命令的现有输出格式。
- 不做 API 版本协商。所有 schema 都是 `v1`，v2 时再设计迁移。
