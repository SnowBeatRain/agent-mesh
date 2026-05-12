## 描述

<!-- 简要说明本 PR 做了什么 -->

## 动机

<!-- 为什么需要这个变更?解决了什么问题? -->

Closes #<!-- issue 编号,可选 -->

## 变更类型

- [ ] 🐛 Bug 修复(不破坏现有功能)
- [ ] ✨ 新功能(不破坏现有功能)
- [ ] 💥 破坏性变更(修改了现有 API/行为)
- [ ] 📝 文档更新
- [ ] 🔧 构建/工具/CI 变更
- [ ] ♻️ 重构(不改变功能)
- [ ] ⚡ 性能优化

## 测试

<!-- 如何验证这个变更?哪些测试被新增或修改? -->

```bash
# 运行的测试命令
python -m pytest tests/test_xxx.py -v
```

- [ ] 已添加/更新单元测试
- [ ] 所有现有测试仍然通过
- [ ] `ruff check src/ tests/` 通过
- [ ] `ruff format --check src/ tests/` 通过

## 影响范围

<!-- 这个变更影响哪些模块/命令/接口? -->

- 影响的 CLI 命令:
- 影响的 JSON envelope schema:
- 影响的 Adapter:
- 是否影响 `--apply` 写入行为:

## 安全检查

- [ ] 未引入 secrets 处理逻辑(或已使用 audit engine 脱敏)
- [ ] 未绕过 PathGuard / dry-run / backup
- [ ] 未引入新依赖(或在描述中说明了必要性)
- [ ] 未读取/写入 Codex `.system`

## 检查清单

- [ ] 已阅读 [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] commit message 遵循 Conventional Commits
- [ ] 已签署 [CLA](../CLA.md)
- [ ] 文档已更新(如适用)
- [ ] CHANGELOG.md 已更新(如适用)

## 备注

<!-- 维护者需要注意的其他事项 -->

> **关于合并流程**:本仓库为发布镜像,你的 PR review 通过后,实际合入会在下一个 release 时通过私有仓库的等价 commit 完成。原 PR 会被关闭并贴出 release commit 链接,你的署名会通过 `Co-authored-by` 保留。
