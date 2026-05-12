# AgentMesh Package Inspect / Verify

## 范围

本文记录 package inspect / verify 的产品边界。

M4 `package inspect` 是只读内容查看能力：读取 ZIP 中的 `package.yaml`、安全枚举文件路径，并输出 package schema、skill 数量、文件数量、manifest 摘要和 warnings。

M4 不做：

- 不写 registry。
- 不写 runtime。
- 不解包到目标目录。
- 不执行 audit / policy。
- 不校验 checksum。
- 不证明 package 未被篡改。

## 安全边界

inspect 必须复用 ZIP path safety：

- 阻止绝对路径。
- 阻止 Windows drive path。
- 阻止 `..` path traversal。
- 阻止 symlink entry。
- 损坏 ZIP、无效 `package.yaml`、缺少 `package.yaml` 返回 error envelope。

## 与 M5 verify 的区别

`package inspect` 只回答“包里声明和包含了什么”。即使 inspect 成功，也不能等价于完整性验证、安全审计或导入许可。

M5 `package verify` 已落地，用于回答“文件清单和 checksum 是否完整一致”。verify 仍然只证明 package manifest 中声明的文件完整性：

- 不建立签名信任体系。
- 不替代 audit / policy 安全审查。
- 不导入 registry。
- 不写 runtime。
- 不访问网络或读取 token。

verify 对 manifest 中缺失文件、额外文件、checksum mismatch 返回 error envelope；对旧 manifest 或不支持的清单语义不能假装完整性通过。
