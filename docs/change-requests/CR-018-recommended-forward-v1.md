# CR-018-R1：recommended-forward-v1 核心链路前向闭合

状态：`APPROVED / SYNCHRONIZATION AUTHORIZED`

日期：2026-08-14

对应差异：`GAP-001`、`GAP-008`、`GAP-020`、`GAP-064`、`GAP-065`、`GAP-066`、`GAP-068`

## 1. 原因与授权

供应商、Markdown/分块、检索、审核和正式报告已经属于 P0，但活跃规格缺少若干会改变持久化、状态、权限或验收阈值的唯一结论。BOSS YHBX 在当前 Codex task 中明确回复：

> 批准 recommended-forward-v1，并授权同步 Request 后继续实施

该授权允许原子同步四份活跃 `Request/`、创建前向 migration、实现本地代码，以及在隔离合成环境运行 PostgreSQL、Redis、MinIO、Qdrant 和浏览器验证。它不授权真实业务数据、外部 AI Provider、远程仓库写入、部署或 production 放行。

## 2. 已批准决定

### RFV1-D-001：供应商统一身份与状态

- 所有 Supplier DTO 的公开 `tax_number` 为 `COALESCE(unified_social_credit_code, tax_number)`；双列同时非空时必须逐字相同，否则失败关闭。
- 合同乙方和发票销售方的 generic tax 只写 `suppliers.tax_number`；不得按长度或字符形状推断并写 USCC，AI 不得确认、激活或决定复用。
- P0 只允许 `unconfirmed/candidate`、`confirmed/active`、`rejected/inactive` 三种状态组合。
- 只有同组织、未删除、`confirmed/active` 且统一税务身份逐字相同的供应商可被复用；名称不参与硬身份。
- 锁序固定为组织 → 来源合同/发票 → 按 UUID 排序的候选与活动供应商；所有更新使用 `row_version` CAS。
- 每次成功人工处理只写一条 `supplier_field` 聚合纠错，保留原因、前后逻辑值、操作者和 Trace；操作日志只保存脱敏摘要。
- 稳定冲突码为 `SUPPLIER_STATE_CONFLICT`、`SUPPLIER_TAX_IDENTITY_CONFLICT`、`SUPPLIER_TAX_NUMBER_CONFLICT`，均为 HTTP 409；旧版本仍使用 `RESOURCE_VERSION_CONFLICT`。

### RFV1-D-002：文档块、Markdown 与复杂表格

- 结构块查询与转换包含 `quote`，不得静默丢弃。
- `document_blocks.bbox_json` 与 `bbox_unavailable_reason` 互斥且完备：有坐标时 reason 必须为空；无坐标时 reason 必须为 `source_not_paginated` 或 `extractor_not_available`。
- P0 Markdown Profile 为 CommonMark core 加 GFM pipe-table 扩展；raw HTML 禁用，渲染不得执行脚本、事件属性、外部资源或不可信 URL。
- 无法安全表达为 pipe table 的复杂表格保存为版本化 `table_asset_v1` JSON 制品和 PostgreSQL 身份，Markdown AST 只引用 opaque asset UUID，不内嵌 HTML、data URI、对象键或外部 URL。
- 分块只读取质量通过且活动的 Markdown 版本；P0 使用单一版本化应用分块 Profile，并把 profile version/hash 固化到 ChunkSet，不提供在线配置编辑或 A/B。
- 单文件多业务文档自动检测/拆分继续不属于本次 P0 实现，不阻断正常单文档链。

### RFV1-D-003：知识权限、Collection 与检索顺序

- P0 不新增知识库 ACL 表。允许集由 Backend 依据 `organization_id`、有效 `knowledge.use`、知识库 active、制度 published、基准日有效期、活动索引成员和未软删除事实生成。
- 一个 Qdrant Collection 对应一个“环境 + Embedding 模型身份 + 向量维度”组合；实际名称必须由配置显式注入并视为不可变身份，应用不得枚举或自动猜测名称。
- 检索顺序固定为：PostgreSQL 生成允许 Point ID 集 → Qdrant `must` 过滤召回 → PostgreSQL 逐项终审并重读可引用正文。任一步不一致都拒绝采用，不允许 Qdrant 扩大权限。
- Qdrant 仅保存可重建向量和最小过滤投影；活动索引、成员、权限、有效期和内容摘要仍由 PostgreSQL 管理。

### RFV1-D-004：评测分级

- 5 条 `smoke` 只证明功能路径可运行。
- 不少于 50 条已审批用例构成 MVP/UAT 最低检索集。
- 不少于 100 条已审批用例构成正式发布门禁；100 条集合可以包含前述 50 条，但正式运行必须保存独立 evaluation run。
- 三档都必须保存数据集、索引、模型/确定性生成器、参数、逐题结果和未命中原因；smoke 不得冒充 MVP/UAT 或正式门禁。

### RFV1-D-005：15 条内置规则目录

- P0 只发布 `RULE-001`～`RULE-015` 的应用内静态目录；禁止在线 DSL、动态 import、用户代码和启动时自动补种。
- 每条规则保存版本、七类 category、输入 Schema、默认风险、解释模板、citation 标志、静态 implementation key/hash 和发布 release/manifest hash。
- 显式离线 publisher 一次发布完整 15 行；数据库为 0 行时原子插入，精确相同集合时 no-op，部分集合、未知版本或漂移时整批失败。已发布行不可 UPDATE/DELETE/TRUNCATE。
- 当前版本按每个 rule code 的最大 version 派生；审核快照绑定具体 rule version ID，不随 current 变化。

### RFV1-D-006：审核执行与高风险门禁

执行状态闭集为：`draft`、`validating`、`queued`、`running`、`pending_finance_review`、`pending_audit_review`、`returned_for_correction`、`completed`、`failed`、`cancelled`、`outdated`。

允许转换：

| 当前状态 | 允许下一状态 |
|---|---|
| `draft` | `validating`、`cancelled` |
| `validating` | `queued`、`failed`、`cancelled`、`outdated` |
| `queued` | `running`、`failed`、`cancelled`、`outdated` |
| `running` | `pending_finance_review`、`failed`、`cancelled`、`outdated` |
| `pending_finance_review` | `completed`、`pending_audit_review`、`returned_for_correction`、`cancelled`、`outdated` |
| `pending_audit_review` | `completed`、`returned_for_correction`、`cancelled`、`outdated` |
| `failed` | `queued`、`outdated` |
| `completed` | `outdated` |
| `returned_for_correction`、`cancelled`、`outdated` | 无 |

- 取消直接持久化为 `cancelled`；`cancel_requested` 不是执行状态。Worker 只能用 CAS 写后续结果，取消后迟到结果不得采用。
- `failed → queued` 只重试同一不可变快照和同一执行版本；事实已变化时必须把旧执行设为 `outdated` 并创建新执行。
- 快照、规则执行和风险绑定同一组织、任务与执行；数据库必须防止跨父对象或跨组织引用。
- 原始风险等级不可改写；人工调整只改有效等级并保存原因和操作者。
- 财务可处理非 high 风险；任何有效等级为 high 且仍为 `pending` 的风险都会阻止完成。只有具备 `risks.review_high` 的审计复核人员可确认、驳回或调整 high，且不能是同一执行的财务初审 actor。
- `returned_for_correction`、`cancelled` 和 `outdated` 不得继续完成；修正后重审必须创建新执行版本。

### RFV1-D-007：正式报告、MinIO 与下载

- 报告状态闭集为 `queued`、`generating`、`ready`、`failed`、`outdated`、`archived`。
- 允许 `queued → generating|failed`、`generating → ready|failed`、`failed → queued`（仅相同执行与 payload hash 的技术重试）、`ready → outdated|archived`、`outdated → archived`；`archived` 无后继。
- 每个报告版本绑定一个 completed 执行、不可变 payload hash、PDF/XLSX artifact 身份、SHA-256、字节数、MIME 和生成器版本。ready 后不得覆盖对象或元数据；新生成创建新版本。
- MinIO 对象键只由服务端生成并保存在 PostgreSQL，永不返回客户端。PDF 预览/下载要求 `reports.read`，XLSX 风险明细下载要求 `reports.export`，均由 Backend 鉴权后流式返回；PDF 使用 inline，XLSX 使用 attachment。
- 执行过期时所有 ready 报告同事务标记 outdated，但历史制品继续可授权读取并明确显示过期。

### RFV1-D-008：迁移与降级

- 新 Schema 使用连续前向 Alembic revision，不自动导入、合并或清理真实业务数据。
- 同一 revision 的 downgrade 先按固定字典序锁定本 revision 拥有的表；存在业务行、下游 FK 或活动制品时以 SQLSTATE `55000` 失败关闭，不使用 `CASCADE`。
- 审核簇的锁顺序固定为 task → execution → snapshot → rule execution → risk → report；业务事务和 downgrade 都不得反序。

## 3. 兼容性与非目标

- 供应商、知识/RAG、审核执行和正式报告 Router 当前尚未发布，因此本次直接采用新合同，不增加旧字段兼容层。
- 不改变固定五角色和现有权限 code；只落实已经存在的 `suppliers.correct`、`knowledge.*`、`audits.*`、`risks.*`、`reports.*` 权限。
- 不新增动态规则中心、知识库级 ACL、混合检索、Reranker、语义分块、多文档拆分、供应商合并/拆分或外部企业查询。
- 外部 AI Provider、生产 Scanner、目标环境容量、部署、备份恢复和 production 仍需独立授权与运行证据。

## 4. 同步与验证要求

本批准生效后必须在同一工作窗口：

1. 同步四份活跃 `Request/`、`docs/baseline-gaps.md` 和 `docs/request-manifest.md`。
2. 为每个新增状态、权限和数据库不变量写先失败后通过的测试。
3. 分别报告离线、PostgreSQL、Redis、MinIO、Qdrant、浏览器和正式 AC 证据；未运行层级保持 `NOT_RUN`。
4. 不提交、不推送、不部署，不读取真实 `.env` 或凭据。

