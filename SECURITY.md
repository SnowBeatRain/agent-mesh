# 安全政策

## 报告漏洞

**请勿在公开的 GitHub Issue 中报告安全漏洞。**

如果你发现 AgentMesh 中的安全漏洞,请通过以下渠道之一私下报告:

- **邮件**:[SnowBeatRain@users.noreply.github.com](mailto:SnowBeatRain@users.noreply.github.com)
- **GitHub Security Advisories**:[私下报告](https://github.com/SnowBeatRain/agent-mesh/security/advisories/new)

## 我们承诺

收到漏洞报告后,我们会:

| 时间 | 行动 |
|------|------|
| **48 小时内** | 确认收到报告 |
| **7 天内** | 完成初步评估,告知严重程度和修复计划 |
| **30 天内** | 修复确认的高危漏洞,或说明延期原因 |
| **修复发布后** | 致谢报告者(除非你希望保持匿名) |

## 范围

以下属于本项目的安全范围:

- **CLI 工具本身**(`src/agentmesh/`):路径逃逸、权限提升、secrets 泄露等。
- **Local API HTTP Server**:本地 endpoint 的越权、SSRF、注入。
- **Audit Engine**:漏报关键 secrets 模式、绕过 hard block。
- **Sync Engine**:静默覆盖、备份失效、rollback 损坏。

以下**不属于**安全漏洞:

- 用户运行不可信的 skills 导致的问题(用户责任)。
- 第三方 Agent runtime 的漏洞(应向对应项目报告)。
- 用户配置错误导致的安全问题。

## 受支持的版本

我们仅对最新的 minor 版本提供安全更新:

| 版本 | 是否支持 |
|------|----------|
| 0.1.x | ✅ 支持 |
| < 0.1 | ❌ 不再支持 |

## 安全最佳实践

使用 AgentMesh 时:

- **始终先 `--dry-run`**,确认计划后再 `--apply`。
- **审查导入的 skills**:执行 `am audit all` 后再决定是否同步。
- **不要在 registry 中存储 secrets**:任何 `*.env`、`credentials.json` 都应排除。
- **使用最小权限**:不要以 root/admin 身份运行 AgentMesh。
- **保护 Codex `.system`**:AgentMesh 默认保护,请勿绕过 PathGuard。

## 已知限制

详见 [威胁模型文档](docs/security/local-api-dashboard-threat-model.md)。

## 致谢

感谢以下报告者帮助改善 AgentMesh 的安全:

<!-- 已修复的漏洞致谢列表 -->

_暂无_
