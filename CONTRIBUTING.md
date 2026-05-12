# 贡献指南

感谢你对 AgentMesh 的关注!本文档说明如何向项目贡献代码、文档或反馈。

## 重要声明:这是一个发布镜像

> 本 GitHub 仓库是 AgentMesh 的**公开发布镜像**。
>
> 主要开发在私有仓库进行,代码每个 release 版本通过自动化流水线**同步**到这里。这意味着:
>
> - 公开仓库的 `main` 分支**仅由 release bot 推送**,不接受外部直接 push。
> - 你的 PR 在 GitHub 上被 review 通过后,维护者会在私有仓库**重写一份等价的 commit**(保留你的署名为 `Co-authored-by`),原 PR 会被关闭并链接到下个 release 的 commit。
> - 公开版本可能比私有版本滞后 1-2 个版本,部分新特性会在下个 release 中出现。

## 贡献流程

### 1. 提交前

- **查看现有 Issue 和 PR**:确认你的想法没有被讨论过。
- **大型变更先开 Issue 讨论**:避免投入精力后被 reject。
- **小修复直接提 PR**:typo、文档勘误、bug 修复欢迎直接 PR。

### 2. 开发环境

```bash
git clone https://github.com/SnowBeatRain/agent-mesh.git
cd agent-mesh
python3 -m venv .venv
. .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 3. 编码规范

- **中文优先**:文档、注释、commit message 使用中文。
- **TDD**:先写测试,再写实现。
- **简单优先**:最小化变更,不做无关重构。
- **不引入未声明依赖**:新依赖需在 PR 中说明必要性。

### 4. 测试

提交前必须通过:

```bash
python -m pytest tests/ -q
ruff check src/ tests/
ruff format --check src/ tests/
```

详细的开发命令见 [AGENTS.md](AGENTS.md)。

### 5. Commit Message

使用 Conventional Commits 格式(中文描述):

```
feat: 新增 skills export 支持 yaml 格式
fix: 修复 sync apply 时的 backup 路径竞态
docs: 补充 CLI reference 中 rollback 命令说明
chore: 升级 ruff 到 0.6
```

### 6. 提交 PR

- **标题**:遵循 Conventional Commits 格式。
- **描述**:说明动机、解决方案、影响范围、测试覆盖。
- **签署 CLA**:首次 PR 时 CLA Assistant 会自动评论要求签署,见 [CLA.md](CLA.md)。

### 7. Review 与合并

- 维护者通常在 7 天内回应。
- 修改后请 push 到原分支,不要新开 PR。
- PR 在公开仓库 review 通过后,**实际合入会在下一个 release 时通过私有仓库的 commit 完成**;原 PR 会被关闭并贴出 release commit 链接。

## 文档贡献

文档位于 `docs/` 目录。修改文档时:

- 保持中文为主,术语保留英文。
- 使用 Markdown,代码块标注语言。
- 大幅修改时附上 `docs:` 前缀的 commit。

## 报告 Bug

通过 [GitHub Issues](https://github.com/SnowBeatRain/agent-mesh/issues) 提交,使用 bug report 模板,包含:

- 操作系统和 Python 版本
- AgentMesh 版本(`am --version`)
- 重现步骤
- 期望行为 vs 实际行为
- `--json` 输出(如果适用)

## 报告安全漏洞

**请勿在公开 Issue 中报告安全问题。** 见 [SECURITY.md](SECURITY.md)。

## 功能建议

通过 [GitHub Discussions](https://github.com/SnowBeatRain/agent-mesh/discussions) 发起讨论,描述:

- 你试图解决的问题
- 期望的工作方式
- 现有方案为什么不够
- 是否愿意亲自实现

## 行为准则

参与本项目即表示同意遵守 [行为准则](CODE_OF_CONDUCT.md)。

## 许可证

提交的所有贡献都将以 [Apache License 2.0](LICENSE) 发布,并签署 [CLA](CLA.md) 授予项目方使用权。
