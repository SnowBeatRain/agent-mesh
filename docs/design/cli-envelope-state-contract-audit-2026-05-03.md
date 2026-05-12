# CLI Envelope 与 State Contract 审计（2026-05-03）

> 范围：当前 worktree `agentmesh-next-20260503` 的 live CLI JSON 输出、状态命令和 read-only contract。
> 前置文档：`docs/reviews/2026-05-03-agentmesh-reality-check.md`。
> 目标：在进入 M1-M5 之前，明确哪些命令已经符合标准 envelope，哪些仍是 legacy/raw payload，哪些状态合同会阻塞 Web UI / Local API / Runtime 后续演进。

## 1. 标准 envelope

推荐所有用户可消费 JSON 输出遵守：

```json
{
  "schema": "agentmesh.<domain>/v1",
  "command": "...",
  "status": "ok|planned|blocked|failed|error|not-installed",
  "data": {},
  "summary": {},
  "warnings": [],
  "errors": [],
  "next_steps": []
}
```

说明：

- `summary` 已在多数命令中存在，建议作为标准 envelope 的推荐字段保留。
- `dry_run` 可作为写计划类命令的额外顶层字段。
- 领域对象也可以有自己的 schema，但应放在 `data` 内，而不是替代 CLI envelope。
- 错误路径也必须返回 envelope，避免 traceback 或 Typer usage 文本污染机器输出。

## 2. Live JSON 审计结果

使用临时 registry 调用各命令后，得到以下结果：

| 命令 | JSON 状态 | schema | 问题 / 备注 |
|---|---|---|---|
| `doctor --json` | 符合 | `agentmesh.doctor/v1` | 含 envelope 与 summary |
| `overview --json` | 符合 | `agentmesh.overview/v1` | `data.schema=agentmesh.local-overview/v1`，适合作为 UI 聚合源 |
| `agents list --json` | 符合 | `agentmesh.agents-list/v1` | 包含 capabilities matrix |
| `agents contract --json` | 符合 | `agentmesh.agents-contract/v1` | M3 继续固化 slots 与 safety values |
| `skills list --json` | 符合 | `agentmesh.skills-list/v1` | 正常 |
| `skills show missing --json` | 符合 | `agentmesh.skills-show/v1` | 错误路径也有 envelope |
| `skills conflicts --json` | 符合 | `agentmesh.skills-conflicts/v1` | 正常 |
| `skills status --json` | 已修复 | `agentmesh.skills-status/v1` | state 位于 `data.state` |
| `skills validate --json` | 已修复 | `agentmesh.skills-validate/v1` | validate report 位于 `data.report` |
| `skills export --json` | 已修复 | `agentmesh.skills-export/v1` | export result 位于 `data` |
| `skills sync --dry-run --json` | 符合 | `agentmesh.skills-sync/v1` | 含 `dry_run` |
| `history list --json` | 符合 | `agentmesh.history-list/v1` | M1 需核对 sync id / backup path / status 字段完整性 |
| `backup list --json` | 符合 | `agentmesh.backup-list/v1` | M1 需核对 unsafe path no-read 与 recoverability |
| `rollback plan --json` | 已修复 | `agentmesh.rollback-plan-response/v1` | 实际 rollback plan 位于 `data.plan`，domain schema 为 `agentmesh.rollback-plan/v1` |
| `package inspect missing --json` | 符合 | `agentmesh.package-inspect/v1` | 错误路径有 envelope |
| `package verify missing --json` | 符合 | `agentmesh.package-verify/v1` | 错误路径有 envelope |
| `runtime load-plan --json` | 已修复 | `agentmesh.runtime-load-plan-response/v1` | 实际 LoadPlan 位于 `data.plan`，包含 `plan_id/generated_at/load_plan_path` 并持久化 |
| `runtime exec-plan missing --json` | 符合 | `agentmesh.runtime-exec-plan/v1` | 错误路径有 envelope |
| `runtime status --json` | 符合 | `agentmesh.runtime-status/v1` | status 可为 `not-installed` |
| `runtime bootstrap --dry-run --json` | 符合 | `agentmesh.runtime-bootstrap/v1` | 含 `dry_run` |
| `local status --json` | 符合 | `agentmesh.local-status/v1` | `data.schema=agentmesh.local-overview/v1` |

## 3. A1 结论

当前 JSON 合同已完成本轮优先缺口修复；原先 3 个重点问题的处理结果：

1. **`skills status --json` 已迁移。**
   - 当前使用 `agentmesh.skills-status/v1` envelope。
   - 原 state payload 放入 `data.state`。

2. **`runtime load-plan --json` 已拆分 CLI envelope 与 domain object。**
   - CLI response 使用 `agentmesh.runtime-load-plan-response/v1`。
   - 实际 LoadPlan 放入 `data.plan`，domain schema 保持 `agentmesh.runtime-load-plan/v1`。

3. **`rollback plan --json` 已迁移为 CLI envelope。**
   - CLI response 使用 `agentmesh.rollback-plan-response/v1`。
   - 实际 rollback plan 放入 `data.plan`。

## 4. State contract 重点风险

### 4.1 History / Backup / Rollback

M1 不应只看命令存在，还要检查状态链：

```text
sync apply
  -> state/sync-history.jsonl
  -> backups/<timestamp>/...
  -> backup list projection
  -> rollback plan
  -> rollback apply
  -> state/rollback-history.jsonl
```

必须保证：

- history entry 有稳定 `id` / `schema` / `status` / `backup_path` / `actions`。
- backup projection 不读取 `<registry>/backups/` 外路径。
- rollback plan 是只读。
- rollback apply 写入前重新 build plan。
- hard block 不被 `--confirm` 绕过。
- rollback apply 失败时有当前状态快照和恢复路径。

### 4.2 Registry state

M2 前置核对：

- live `skills` 命令现已包含 `reindex`。
- `registry_service.py` 已有 `RegistryImportConflict` 和 excluded import noise 逻辑。
- 需要确认同名不同内容是否完全阻断、原始 registry 是否保持不变。
- 已新增 index 文件合同：`registry/index/skills.json`，schema 为 `agentmesh.registry-skills-index/v1`。

### 4.3 Adapter contract

M3 重点不是新增 adapter，而是让 contract 可被下游消费：

- 每个 contract 应有 `agentmesh.adapter-contract/v1`。
- slots 必须明确 implemented/unsupported。
- `write_operations_enabled=false` 应描述 contract surface，不得误导为 sync 永久不可写。
- Codex / Claude Code 的 safety values 需要 value-level tests。

### 4.4 Local API

本轮扩展后 `local_api` 模块包含 HTTP server + Dashboard：

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

`am local serve --port 9090` 启动 localhost-only HTTP server，浏览器访问 `http://127.0.0.1:9090/` 查看 Dashboard UI。安全约束：

- 默认绑定 `127.0.0.1`，deny remote bind。
- 非 GET blocked。
- unknown route error envelope。
- 不 import mutating services。

**✅ HTTP server + Dashboard 已实现：**

- `local_api/server.py` 封装 HTTP server，默认端口 `9090`。
- `local_api/dashboard.html` 提供 Dashboard UI，在根路径 `/` 和 `/dashboard` 自动加载。
- path redaction 已实现（`_redact_path` 和 `_redact_paths_in_value`）。
- 非 GET 参数化测试已补齐（PUT/PATCH/DELETE/OPTIONS/HEAD）。

### 4.5 Runtime LoadPlan（含 RuntimeRenderer）

M5 必须区分两层 schema：

- CLI response envelope。
- LoadPlan domain object：`agentmesh.runtime-load-plan/v1`。

已完成：

- `plan_id`
- `generated_at`
- `load_plan_path`
- 持久化到 `state/runtime-load-plans/<target>.json`
- blocked skills 保留在 plan 中
- shim/exec-plan 只证明定位与解析，不宣称真实 runtime session injection
- 动态 `next_steps`

**✅ RuntimeRenderer 已集成到 bootstrap：**

- `runtime/renderer.py` 提供 target-specific renderers，将 registry skills 渲染为目标 Agent 原生格式：
  - Hermes / OpenClaw → 合并 SKILL.md
  - Cursor → `.mdc` 规则文件
  - Windsurf → `.md` 规则文件
  - Aider → `conventions.md`
- bootstrap `--apply` 时自动调用 Renderer 写入渲染产物。

## 5. 推荐 TDD 切片顺序

### A1-fix-1：统一 `skills status --json`

- 先加 CLI golden test：断言顶层含 `schema/command/status/data/warnings/errors/next_steps`。
- 最小实现：把现有 raw payload 包进 envelope。
- 文档：CLI reference 更新。

### A1-fix-2：统一 `runtime load-plan --json`

- 先加测试：`data.plan.schema == agentmesh.runtime-load-plan/v1`。
- 保留 human 输出不破坏。
- 明确是否保留 legacy raw 输出；若不保留，更新 tests/docs。

### A1-fix-3：统一 `rollback plan --json`

- 先加测试：`data.plan.schema == agentmesh.rollback-plan/v1`。
- `rollback apply --json` 同步检查。
- 注意不要破坏 rollback service 的 domain plan builder；只调整 CLI envelope。

### M1-fix：Backup-History-Rollback 证明

- 优先补 read-only plan snapshot test。
- 再补 apply 前重建 plan test。
- 再补 unsafe/hard block 不能 confirm bypass。
- 再补 rollback history failure 恢复测试。

### M2-fix：Registry reindex 与 import conflict

- 先加 `skills reindex --json` help/golden test，若命令不存在应失败。
- 再实现 service + CLI。
- 再补 conflict idempotent / different content blocked / original unchanged。

### M3-fix：Adapter contract

- 先补 `agents contract --json` value-level tests。
- 再补 docs。

### M4-fix：Local API 扩展

- 先补 handler tests：`GET /overview`、`GET /skills`、`GET /history`、`GET /backups`。
- 不加 server。

### M5-fix：Runtime alpha

- 先补 LoadPlan persisted contract tests。
- 再补 `plan_id/generated_at/load_plan_path`。
- 再补 shim/env/exec-plan 一致性。

## 6. 不进入本轮的事项

- 远程同步 / DeepLink apply。
- 目标 Agent 原生 session-init 注入。
- 绕过 hard block 的宽泛 force flag。
