# 更新日志

## Unreleased

### Added
- `skills target <name> --enable/--disable/--show` 统一 state 矩阵命令，
  取代分散的 `skills enable` / `skills disable` / `skills status`。
- `skills import --from <source>` 统一导入语法：
  - `--from agent:<name>` 从 agent runtime 扫描并导入（取代位置参数 `skills import <agent>`）
  - `--from package:<path>` 从 AgentMesh ZIP 导入（取代 `skills import-package`）

### Deprecated
- `skills enable` / `skills disable` / `skills status`：请改用 `skills target`。
  旧命令仍可用，调用时会在 stderr 打印 `[DEPRECATED]` 提示。
- `skills import <agent>` 位置参数形式：请改用 `skills import --from agent:<name>`。
- `skills import-package <zip>`：请改用 `skills import --from package:<zip>`。
  legacy 命令的 JSON envelope schema 维持 `agentmesh.skills-import-package/v1`
  不变，直到 0.3.0 删除。
- `skills sync --dry-run` / `skills import --dry-run` / `skills import-package --dry-run`：
  dry-run 已是默认行为（不传 `--apply` 即为 dry-run），`--dry-run` 标志冗余。

弃用策略：上述命令/标志在本版本仍然工作，调用时在 stderr 打印 `[DEPRECATED]`
提示。`--json` 输出模式下不打印弃用提示，保证 stdout 是纯净的 JSON envelope。
计划在 **0.3.0** 正式移除。

## 0.1.0

首个可运行 SkillMesh MVP 骨架：

- 提供 `agentmesh` CLI、`--help` 与 `--version`。
- 支持 `init` 创建本地 registry 布局。
- 支持 `doctor` 与 `agents list` 检测 Hermes、OpenClaw、Codex、Claude Code 的 skill 路径状态。
- 支持扫描 Hermes/OpenClaw/Codex/Claude Code skills，并默认排除 Codex `.system`。
- 支持将 skill 导入中立 registry，生成 `agentmesh.asset.yaml`、`agentmesh.skill.yaml` 与 provenance。
- 支持基础 secrets / dangerous scripts 审计，敏感内容只输出 `<redacted>`。
- 支持 `skills sync --dry-run` 生成同步计划；真实写入必须显式 `--apply`。
- 支持 `package inspect` 只读检查 AgentMesh ZIP package，输出 schema、skill/file 数量、manifest 摘要，并阻断 unsafe ZIP path；inspect 不等于 verify/audit。
- 支持 `package verify` 校验 AgentMesh package 文件清单与 checksum，发现缺失、额外文件或内容篡改。
- 支持 `backup list`、`rollback plan` 与 `rollback apply --confirm`，形成基础恢复闭环。
- 支持 `prompts status` / `prompts disable`，查看并解除 target prompt 管理关系，disable 不删除 live 文件。
- 支持 `skills update-check` 本地只读预检，M7 不联网、不下载、不读取 token。

暂不包含：云同步、在线 marketplace、GUI、Claude Code 自动安装、复杂冲突自动合并。
