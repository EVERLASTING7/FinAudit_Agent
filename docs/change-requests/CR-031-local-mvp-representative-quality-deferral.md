# CR-031：Local MVP 代表性业务质量范围延期

- 状态：`APPROVED`
- 批准人：BOSS（YHBX）
- 批准日期：2026-08-20
- 适用范围：当前 Local MVP Goal

## 决定

BOSS 明确将原 Goal 第 6 项“代表性业务准确率仍未证明”移出当前 Goal，并将其保留为 Local MVP 已知限制，状态固定为 `OUT_OF_SCOPE_KNOWN_LIMITATION`。

本决定只调整当前 Goal 的完成边界：

- 不修改 `PRODUCT_REQUIREMENTS.md` 中合同 85%、发票 95%、结构合法率 99%、确定性规则 100%/高风险漏报 0 等正式质量阈值。
- 不改写现有公开技术测量。`MEASURED_FAILED`、`NOT_COMPUTABLE`、`PARTIAL` 和低于阈值的结果继续有效。
- 不把公开跨域数据、合成数据、Agent 复核或本机模型 pilot 提升为客户业务代表性数据、人类 UAT、production 或正式 AC 证据。
- 不改变默认 Local MVP Profile：OCR 与 AI Provider 继续关闭，确定性规则和人工确认流程继续可用。
- 不修改代码、API、Schema、迁移、权限、安全边界、运行配置或正式验收状态。

## 修订后的当前 Goal

| 原项目 | 当前 Goal 结论 |
|---|---|
| 第 5 项：文档纠错与制度撤销浏览器闭环 | `PASS`；当前 Chrome Gate 已覆盖授权角色、失败路径、刷新恢复、console、PostgreSQL 终态和清理 |
| 第 6 项：代表性业务准确率 | `OUT_OF_SCOPE_KNOWN_LIMITATION`；失败证据与正式质量缺口继续保留 |
| 第 7 项：知识库真实质量门禁 | `PASS`；owner-delegated local/test v3 已完成 50/50 → 100/100 → 可丢弃索引激活 |
| 第 8 项：默认关闭 OCR 与 AI Provider | `RETAINED_LOCAL_PROFILE`；属于已批准 Local MVP 边界，不是启动缺陷 |

## 用户影响与后继条件

当前 Local MVP 仍不能保证图片/扫描 PDF 的真实 OCR 成功，也不能保证客户真实合同、发票、重复发票和风险规则达到正式业务质量阈值。它可继续依赖确定性解析、确定性规则和人工确认完成本地流程。

后续只有在取得业务批准的代表性数据、独立标准答案、必要的 OCR/模型 Profile 与单独运行授权后，才能新建目标执行合同 85%、发票 95%、重复识别、风险有效性和复杂多格式文档正式门禁。该后继工作不得复用本 CR 将 Local MVP Goal 收口的结论作为质量通过证据。
