# 贡献指南

感谢你对 AgentMesh 的兴趣！本指南帮助你快速上手开发环境和贡献流程。

## 开发环境

### 克隆与安装

```bash
git clone https://github.com/agentmesh/agentmesh.git
cd agentmesh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

### 验证环境

```bash
python3 -m pytest tests -q
ruff check src/ tests/
```

## 开发工作流

### TDD 优先

1. 先编写失败的 pytest 测试用例
2. 实现最小代码使测试通过
3. 提交前运行完整测试套件

### 常用命令

```bash
# 运行测试
python3 -m pytest tests -q

# 带覆盖率
python3 -m pytest tests -q --cov=agentmesh

# Lint 检查
ruff check src/ tests/

# 自动格式化
ruff format src/ tests/
```

## 代码风格

- **Python** >= 3.10，使用 type hints
- **行宽**：100 字符
- **Lint 规则**：E, F, I, UP, B
- **文档语言**：中文为主，技术标识符用英文

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 前缀：

| 前缀 | 用途 |
|------|------|
| `feat:` | 新功能 |
| `fix:` | Bug 修复 |
| `docs:` | 文档变更 |
| `refactor:` | 代码重构 |
| `test:` | 测试相关 |
| `chore:` | 构建/工具变更 |

示例：

```
feat: 添加 MemoryMesh prompt 导出功能
fix: 修复 Codex adapter 路径解析问题
docs: 更新 CLI 参考文档
```

## Pull Request

- 说明 PR 的目的和变更范围
- 列出已变更的文档或规格
- 描述已执行的验证步骤
- 保持 PR 范围小而专注

## 安全规则

!!! danger "绝对禁止"
    - 不要提交 secrets、API key、token 或本地凭据
    - 不要覆盖系统 skills 或受保护的运行时资产
    - 不要绕过 dry-run 保护机制

## 文档贡献

- 文档放在 `docs/` 目录下
- 保持中文为主
- 使用 MkDocs Material 语法
- 本地预览：

```bash
pip install mkdocs-material
mkdocs serve
```

## 问题反馈

通过 GitHub Issues 报告 bug 或提出功能请求。请包含：

- 问题描述
- 复现步骤
- 期望行为
- 实际行为
- 环境信息（OS、Python 版本）
