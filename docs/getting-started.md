# 快速开始

> 5 分钟上手 AgentMesh，体验跨 Agent 资产互通。

---

## 前置条件

- Python 3.10+
- 本机至少安装了一个 Agent runtime（Hermes / OpenClaw / Codex / Claude Code 等）

## 安装

```bash
git clone https://github.com/SnowBeatRain/AgentMesh.git
cd AgentMesh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

验证安装：

```bash
am --version
```

## 第一步：初始化

```bash
am init
```

创建 AgentMesh registry 目录结构（默认 `~/.agentmesh/`）。

## 第二步：健康检查

```bash
am doctor
```

检测本机已安装的 Agent runtime 和配置完整性。

## 第三步：扫描 Skills

```bash
# 扫描所有已检测的 runtime
am skills scan --agent all

# 只扫描 Hermes
am skills scan --agent hermes
```

## 第四步：导入到 Registry

```bash
# 预览导入（dry-run）
am skills import hermes --dry-run

# 确认后执行导入
am skills import hermes
```

## 第五步：查看与比较

```bash
# 列出 registry 中所有已导入 skills
am skills list

# 查看单个 skill 详情
am skills show <skill-name>

# 比较 registry 与 runtime 版本差异
am skills diff hermes
```

## 第六步：同步到其他 Agent

```bash
# 预览同步计划
am skills sync --to openclaw --dry-run

# 执行同步（需要确认）
am skills sync --to openclaw --apply
```

## 更多功能

### 跨 Agent 资产互通

```bash
# 记忆资产
am memory scan --agent all
am memory import hermes
am memory diff hermes openclaw
am memory sync --to openclaw --apply

# 模型配置
am model scan
am model diff
am model sync --to hermes --apply

# 工具配置
am tool scan
am tool diff
am tool sync --to hermes --apply
```

### Package 管理

```bash
# 从本地发布
am package publish my-skill 1.0.0
am package install my-skill

# 从远端安装
am package install https://github.com/user/skill --yes
```

### Prompt 管理

```bash
am prompts add my-prompt --content "You are a helpful assistant."
am prompts list
am prompts versions my-prompt
```

### 安全与审计

```bash
am audit all          # 全量安全审计
am audit secrets      # 敏感信息检测
am history list       # 同步历史
am backup list        # 备份记录
am rollback plan      # 生成回滚计划
```

### Runtime 管理

```bash
am runtime status     # 查看 runtime 状态
am runtime bootstrap  # 初始化 runtime 目录
am runtime update --target hermes --apply  # 更新 LoadPlan
```

## 下一步

- [使用指南](usage-guide.md) — 完整功能详解
- [CLI 参考](cli-reference.md) — 所有命令和参数速查
- [架构设计](design/index.md) — 了解内部实现
- [贡献指南](contributing.md) — 参与开发
