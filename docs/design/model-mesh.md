# ModelMesh 设计文档：模型配置互通

## 概述

ModelMesh 是 AgentMesh 的模型配置互通层。目标是扫描各 AI Agent 的模型配置，提供统一的 schema 表示和跨 Agent 差异比较。

## 各 Agent 模型配置格式差异

| Agent | 配置文件路径 | 格式 | 关键字段 |
|-------|-------------|------|---------|
| Hermes | `~/.hermes/config.yaml` | YAML | `model.default`, `model.provider`, `model.base_url`, `model.context_length` |
| OpenClaw | `~/.openclaw/openclaw.json` | JSON | `models.providers.{name}.models[].id`（多 provider，每个含多个 model） |
| Codex | `~/.codex/config.json` | JSON | `model`（字符串） |
| Claude Code | `~/.claude/settings.json` | JSON | `model`（字符串） |

### 格式差异分析

- **Hermes** 最完整：包含 default model、provider、base_url、context_length
- **OpenClaw** 最复杂：多 provider 架构，每个 provider 下有多个模型定义（含 context window、cost 等）
- **Codex / Claude Code** 最简单：仅一个 model 字符串

## 统一 Schema：`agentmesh.model-config/v1`

```python
@dataclass(frozen=True)
class ModelConfig:
    agent: str                    # Agent 名称
    default_model: str            # 默认模型 ID
    provider: str = ""            # Provider 名称
    base_url: str = ""            # API 端点
    context_length: int | None = None  # 上下文窗口大小
    available_models: tuple[str, ...] = ()  # 可用模型列表
    schema: str = "agentmesh.model-config/v1"
```

### 设计取舍

1. **扁平化**：各 Agent 差异很大，选择提取公共字段到扁平结构
2. **只读探索**：当前阶段仅 scan/diff，不涉及写入
3. **available_models**：主要为 OpenClaw 的多模型场景设计

## 实现模块

| 模块 | 职责 |
|------|------|
| `models/model_config.py` | `ModelConfig` 和 `ModelDiff` 数据类 |
| `services/model_service.py` | `scan_config()`, `scan_all()`, `diff_configs()` |
| `cli/model.py` | `am model scan/diff/list` CLI 命令 |

## CLI 命令

```bash
am model scan [--json] [--registry PATH]   # 扫描各 Agent 模型配置
am model diff [--json] [--registry PATH]   # 比较模型配置差异
am model list [--json] [--registry PATH]   # 列出模型配置概览
```

## 后续方向

- [ ] 模型能力映射（reasoning、vision、context window 对比）
- [ ] 模型推荐：基于任务类型推荐最优模型
- [ ] 模型配置同步：跨 Agent 推送模型偏好
- [ ] 成本分析：基于 provider 定价估算使用成本
