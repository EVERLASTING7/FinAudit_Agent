# CR-022：AI 费用审计货币中立化

状态：`APPROVED / SYNCHRONIZED / IMPLEMENTED / VERIFIED LOCAL`

日期：2026-08-17

对应范围：`AI-001`、`AI-005`、`TEST-005`、`PROD-VS-03`、OPS-005

## 1. 问题

当前 `AiCallEventV1`、AI 预算、`ai_call_logs` 和 OPS-005 都把金额固定为 `micro_usd`。`CR-021` 批准的百炼 Embedding 以 CNY 计费，因此现有字段不能承载其价格、预留或实际费用，也不能通过隐式汇率转换伪装为 USD。

本 CR 只冻结货币中立费用审计的前向合同。BOSS 于 2026-08-17 另行明确授权复用现有百炼密钥并执行一次受限付费 Embedding smoke；该次授权本身不扩展到第二次调用、生产部署、代表性数据验收或 AC/UAT 签署。其后另一次完整知识库 E2E 授权与实跑事实见第 9 节。

## 2. 备选方案

### A. 版本化 currency-neutral 合同（推荐）

- 保留 Event v1 和历史 `micro_usd` 语义用于回放。
- 新增 Event v2，以“计费币种 + 该币种百万分之一单位整数”记录预留与实际费用。
- 初始只允许 `USD`、`CNY` 和内部不计费三种情况，不做汇率换算，不支持跨币种汇总。

### B. 为 CNY 增加平行专用字段（不推荐）

会把预算、事件、数据库和 API 分裂成 USD/CNY 两套分支；增加重复逻辑，并使后续币种继续扩列。

### C. 运行时换算为 USD（拒绝）

缺少批准的汇率来源、时间点、精度和审计证据；会把估算值写成确定事实。

## 3. 推荐合同

### CR022-D-001：金额单位

- `cost_currency` 仅允许 `USD | CNY | null`；`null` 只表示 `internal_unmetered`。
- `microunits` 固定表示对应币种的 `10^-6`，全部金额使用非负整数和向上取整公式，禁止二进制浮点。
- `external_usd` 必须对应 `USD`，`external_cny` 必须对应 `CNY`，`internal_unmetered` 必须对应 `null` 和零价格。
- 禁止汇率转换、不同币种相加、把未知费用记为零或用币种缺失表示免费。

### CR022-D-002：Policy 与预算 v2

- v2 价格字段为 `input_price_microunits_per_million`、`output_price_microunits_per_million` 和 `cost_currency`。
- v2 业务预算字段为 `max_cost_microunits`；同一业务操作的所有外部计费 attempt 必须使用同一 `cost_currency`，否则在 Provider 发送前失败关闭。
- 单次预留仍按完整输入估算与最大输出 Token 使用现有向上取整公式；失败、unknown、retry、fallback 和 repair 不释放最坏预留。
- Provider 成功时按权威 usage 计算 `actual_cost_microunits`；usage 或价格身份未知时输出不可采用。

### CR022-D-003：Event v2

- `ai.call.started` v2 用 `cost_currency` 和 `reserved_cost_microunits` 取代 `reserved_cost_micro_usd`。
- `ai.call.completed` v2 增加 `actual_cost_microunits`：外部计费成功必须非空，内部不计费成功固定为 `0`；没有权威 usage 的失败可以为 `null`，不得伪造为零。
- `ai.call.late_completion` v2 使用相同币种与实际费用语义。
- v1 bytes、JCS hash、重放键和解析保持不变；v2 使用独立 Schema/版本。消费者必须显式分派 v1/v2，禁止把 v2 payload 交给 v1 模型宽松解析。

### CR022-D-004：PostgreSQL

- `ai_call_logs.event_version` 允许 `1|2`。
- 保留可空的 legacy `reserved_cost_micro_usd`，新增 `cost_currency`、`reserved_cost_microunits` 和 `actual_cost_microunits`。
- v1 行必须保留 legacy USD 字段，v2 行必须使用 generic 字段；两套字段不能同时非空。
- v2 外部计费行要求 `USD|CNY`，v2 内部不计费行要求 `cost_currency IS NULL` 且预留/实际费用为零。
- 升级前必须确认没有 pending AI 调用或未投影 AI Outbox；不猜测既有 v1 行的通用币种或实际费用。终态 v1 行继续按 v1 查询和回放。
- downgrade 只有在不存在任何 v2 Event、v2 日志和依赖事实时才允许；不得把 CNY 行转换为 USD。

### CR022-D-005：OPS-005

- attempt 新增 `cost_currency`、`reserved_cost_microunits`、`actual_cost_microunits`，legacy `reserved_cost_micro_usd` 改为可空并只服务 v1。
- summary 只能汇总同一 currency-neutral 业务操作；实际费用只在所有相关 attempt 都有权威金额时返回总数，否则为 `null`。
- 不返回价格密钥、Provider 原始 usage、汇率、Prompt、正文或跨组织事实；继续使用 `private, no-store`。
- 该响应是 `/api/v1` 的兼容性变化：严格客户端必须接受 legacy 字段可空和新增字段。批准本 CR 即表示接受该前向变化；否则保持现状并继续禁用 Embedding 持久费用审计。

### CR022-D-006：Embedding 采用

- 百炼 Embedding 每次物理请求必须在发送前完成 v2 durable reserve，并继续先通过 Redis 门禁。
- Provider 成功后的 completion、向量身份/hash 和采用该向量的 PostgreSQL 事实必须遵守既有原子采用边界；审计或实际费用对账失败时不得采用向量。
- Worker 重试仍是新的物理 attempt，不复用费用或发送许可；Backend 查询与 Worker 构建共享同一事件、预算和脱敏规则。

## 4. 明确非目标

- 不新增汇率服务、会计总账、税务处理、阶梯价、缓存价或账单对账平台。
- 不修改发票业务字段 `currency`；本 CR 只处理 Provider 调用费用。
- 每次真实网络调用都必须有独立、受限授权；本 CR 记录的首次 smoke 与第 9 节完整 E2E 授权均已消耗，不批准其他币种、其他百炼模型、production Profile 或 quota/canary。
- 不把本地测试、合成数据或 Provider smoke 视为正式费用、质量、AC 或 UAT 验收。

## 5. 实施与验证门禁

批准后按以下最小顺序实施：

1. 新增 Event/Policy v2 Schema 与 v1/v2 双读测试；保持 v1 bytes/hash 不变。
2. 增加线性迁移、ORM、Repository 预算和 OPS-005 投影；用非空 v1 历史、pending/Outbox 负例和 v2 CNY 行验证升级/降级边界。
3. 将 Chat 切到 v2 USD、Embedding 切到 v2 CNY；验证同币种并发预算、实际 usage 对账、unknown/late、Redis 拒绝和事务回滚。
4. 运行完整离线门禁、PostgreSQL current-head 双轮和零网络 Provider 门禁。
5. 已在“复用现有百炼密钥 + 单次付费调用”明确授权下运行一次有界真实 Embedding smoke；无自动重试，授权已消耗。

通过标准：

- v1 历史事件逐字节兼容且可继续投影/查询。
- v2 USD/CNY 费用计算只使用整数，边界与并发预留不能超支。
- 混币种、未知价格、未知 usage、字段混用、pending 升级和含 v2 数据 downgrade 全部失败关闭。
- OPS-005 不进行跨币种求和，且不泄露敏感内容。
- 本次 local/test 百炼 Provider smoke 可记为 `VERIFIED LOCAL`；production、代表性质量与正式 AC 在没有独立证据时继续为 `NOT_RUN`。

## 6. 回滚

- 首选把 `AI_PROVIDER_CALLS_ENABLED=false`，停止新的外部请求并保留审计事实。
- 代码必须继续读取 v1；已产生 v2 事件或日志后不得降级为只支持 v1 的版本。
- 数据库 downgrade 仅允许空 v2 状态；任何 CNY 事实存在时失败关闭。

## 7. 批准决定

BOSS 于 2026-08-17 批准：`CR-022 / option-A / event-policy-v2 / USD-CNY-only / no-fx`。

同次决定另明确授权复用现有百炼密钥并执行一次受限付费 Embedding smoke。该一次性授权已执行成功，不得据此继续调用或扩展为 production。

## 8. 实施与验证记录

- Event v1 保持原解析、JCS bytes/hash 和投影；Event v2 由 `backend/app/ai/events.py` 的封闭 Pydantic 模型与显式 v1/v2 dispatcher 作为机器 Schema。
- `live-ai-policy-v2.json` 固定 Chat/USD 与 Embedding/CNY 的整数 microunit 价格、预算、endpoint、模型、批次和单次调用边界；Policy 原始字节和 canonical hash 继续双重校验。
- Alembic `20260817_024` 保留 legacy v1 字段，增加 generic currency/cost 字段，并对 pending 升级、字段混用和含 v2 数据 downgrade 失败关闭。
- Chat 已迁移到 Event v2/USD；Backend RAG、Worker 索引与评测的真实 Embedding 已迁移到 Event v2/CNY，Provider 成功结果只有在 completion 与业务事实同一 PostgreSQL 事务提交时才可采用。
- OPS-005 对 v1 返回 legacy USD，对 v2 返回 `cost_currency`、预留与权威实际 microunits；不跨币种汇总。
- 2026-08-17 当前 checkout：完整离线门禁为 Backend `3027 passed / 141 skipped`、Frontend `527 passed`，Ruff/format/Mypy/typecheck/build 均通过；PostgreSQL 16.14 current-head 全目录连续两轮通过；真实 Redis/Celery 与 AI runtime-control 共 `4 passed`。
- 唯一一次百炼 smoke 成功：固定 2 条短合成输入，`43` input tokens，2 个 `1024` 维向量，Event v2 审计终态 `succeeded`，币种 `CNY`，权威实际费用 `22` microunits。输出未包含密钥、输入原文或向量；一次性 PostgreSQL 容器已销毁。
- 上述均为 local/test 工程证据，不构成代表性检索质量、正式费用账单、production、UAT 或任何 AC 的正式签署。

## 9. 单独再授权的完整知识库 E2E

BOSS 于 2026-08-17 另行批准复用现有百炼密钥，在一次性 local/test PostgreSQL + Qdrant 环境重新执行同范围完整 E2E，并明确保持以下硬边界：最多 20 次 Provider 请求、最多 50000 input tokens、CNY 总费用不超过 1 元、单次运行、不自动扩大范围、no-fx、no-production、不绕过至少 100 条 `formal_release` 门禁，且不得输出密钥、文档原文、向量或敏感数据。

受保护运行器 `scripts/smoke_live_bailian_knowledge_e2e.py` 的实际结果为 `PASS`：知识库构建 → Worker 索引 → Qdrant collection green → Top-5 → 5 条 smoke 评测完整执行；7 次 Provider 请求、3231 个权威 input tokens（运行前 UTF-8 上界 13905）、CNY 1616 microunits，15 个索引成员、1024 维、Top-5 返回 5 条、5/5 smoke 通过，7 个 completed attempt 投影 14 个 Event v2 事件。激活调用按设计返回 `formal_evaluation_required`，索引保持 `ready`；未伪造或绕过正式评测事实。唯一 Collection 与专用 PostgreSQL/Qdrant 容器已删除，脚本输出未包含密钥、原文或向量。本次授权已经消耗；该结果仍不构成经审批 50/100 条代表性检索质量、production、UAT 或正式 AC 签署。
