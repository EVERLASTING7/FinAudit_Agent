# CR-019：真实 AI 运行链与内部指标边界

状态：`APPROVED BY CURRENT TASK / SYNCHRONIZED`

日期：2026-08-16

对应差异：`GAP-002`、`GAP-005`、`OQ-11`、`PROD-VS-03`、`DEP-006`

## 1. 原因与授权

BOSS YHBX 在当前 `/goal` 中明确要求继续完成真实 LLM/Embedding Provider、模型 Adapter、Provider → EventSink → 业务事实原子采用、合同/发票真实 AI 提取、解释/报告草稿、OPS-005、正式验收、生产门禁和监控接口，并随后明确说明本地 `.env` 已配置完成且允许读取。

本 CR 记录当前任务直接授权的最小前向决定：允许在 `local/test` 使用一份固定 MiniMax-M3 LLM Profile，接入既有持久审计和业务采用边界，并暴露受独立凭据保护的内部指标。授权不包含生产部署、真实业务数据、远程仓库写入、生产 Secret/CA/OCR/Scanner、真实 Embedding Provider 或正式 AC/UAT 放行。

## 2. 已批准决定

### CR019-D-001：`minimax-m3-local-v1` 真实 LLM Profile

- 真实 LLM 仅允许 `local/test` 使用 `https://api.minimaxi.com/v1`、`MiniMax-M3` 和 `LLM_API_KEY` secret slot；production 继续失败关闭。
- 固定 OpenAI-compatible Chat Completions Adapter、HTTPS、域名 allowlist、DNS/IP 拒绝规则、peer 复核、无系统代理、无重定向、有界 Header/Body、deadline、重试、Token 和费用预算。
- 固定 `thinking=disabled`、`temperature=0`、`top_p=0.95`、`service_tier=standard` 和 `max_completion_tokens`。模型 ID、Policy 原始字节和 canonical hash 启动时重验。
- MiniMax 当前批准资料未提供本项目可采用的 Embedding API；知识索引继续使用 `deterministic-hash-v1`。启用真实 LLM 时如配置 Embedding URL、密钥或其他模型名，Backend/Worker 必须启动失败，禁止把 Hash 向量误标为真实模型输出。

### CR019-D-002：持久审计与原子采用

- 所有真实调用经 `AiGateway`、注册 Adapter 和 `AuditedLlmInvoker`；业务 Service 不直连 Provider。
- Provider 发送前必须先持久 reserve 并获得一次性 `SendPermit`；完成事件必须与采用它的合同、发票、RAG Query、风险解释或报告草稿事实处于同一 PostgreSQL 事务。
- 业务输入在 Provider 调用后、采用前必须重新锁定和校验；发生状态、权限、引用、内容或 payload hash 漂移时，完成事件记为 rejected，模型输出不得成为业务事实。
- 审计失败、预算拒绝、未知完成、迟到完成和结构校验失败均不得产生伪成功。合同/发票提取 Job 失败；RAG 受控拒答；风险解释与报告草稿降级，但确定性规则和正式报告基础事实继续保留。

### CR019-D-003：AI 业务输出

- 合同和发票输出必须包含冻结的 13 个核心字段、严格 JSON/Pydantic 结构和本次输入证据；无证据为 `null`，不得由模型确认、审批、判重或覆盖规则。
- 未确认发票允许 `currency = null`，并移除无证据的 `CNY` 默认；发票进入 `confirmed` 时数据库仍强制 currency 非空。
- RAG 仅接收 PostgreSQL 允许集、Qdrant must-filter 和 PostgreSQL 终审后的候选；引用必须逐项属于本次候选，失败时拒答。
- 风险解释不能改变规则 ID、实际值、预期值或风险等级；报告草稿明确标记为未审批内容，不能改变执行、风险、引用或报告状态。
- 风险解释和报告草稿保存 `disabled|succeeded|degraded`、严格 JSON 和 SHA-256；成功三元组和空降级三元组由数据库约束，ready/outdated 报告制品仍不可变。

### CR019-D-004：OPS-005

- 新增 `GET /api/v1/ai-call-logs?business_operation_id=<uuid>`。
- 仅允许当前组织且具备 `operations.read` 的 Actor 查询；响应按 Provider attempt 连续排序，仅包含模型身份、状态、预算/实际 Token、费用、稳定错误码、Trace 和时间等批准字段。
- 不返回 Prompt、响应正文、Header、密钥、Provider URL 或跨组织存在性信息；响应使用 `private, no-store`。

### CR019-D-005：内部 `/metrics`

- `/metrics` 位于 `/api/v1` 之外，只在 `METRICS_ENABLED=true` 时注册，并使用独立 `METRICS_INTERNAL_TOKEN` Bearer 凭据；不得复用用户 JWT，不接受 query token。
- 输出仅含 build、uptime、in-flight、HTTP 请求计数和固定桶耗时；标签只允许固定 `method/request_group/status_class`，不得包含路径参数、组织、用户、Trace、业务 ID、Prompt 或正文。
- Nginx 只精确代理 `location = /metrics` 并透传 Authorization；是否对生产网络暴露、采集端身份、告警规则、SLO 和保留期仍由 production Profile 决定。

### CR019-D-006：质量阈值计算器

- 合同 85%、发票 95% 按冻结 13 个核心字段的已归一化值做逐字段精确匹配；结构合法率按所有收到结构化响应的 Provider attempt 计算，修复响应同样进入分母。
- 结构无效且未形成严格输出的业务样本，其全部核心字段按未命中计；不得删除失败样本或只统计最终成功响应。
- `scripts/evaluate_ai_extraction.py` 只复算阈值并固定输出 `formal_acceptance_status=NOT_DETERMINED`。`representative=true` 和 `approval_ref` 是追踪输入，不构成审批真实性证明；正式验收仍须独立审批数据集、UAT 和发布签署。

## 3. 数据库与兼容性

- accepted head 前进为 `20260816_023`，仍为 57 张核心表。
- `022` 允许未确认发票 currency 为空并增加“confirmed 必须有 currency”的数据库约束；该变更避免无证据默认值，不增加兼容层。
- `023` 为 `audit_risks` 和 `audit_reports` 增加 AI 状态/JSON/hash，并只放行受控的同状态 AI 采用转换；原报告状态机和 ready 制品不可变规则保持有效。
- OPS-005 和 `/metrics` 是新增只读端点，不改变既有响应字段。Frontend 新增 AI 状态/草稿显示时继续严格解码，AI 不可用时展示明确降级。

## 4. 验证与证据边界

- 离线单元、Ruff、mypy、隔离 PostgreSQL AI/Audit/Retrieval scopes 和 Frontend 聚焦测试用于验证结构、权限、迁移、原子采用、拒答与降级。
- 受显式 gate 保护的真实 MiniMax 冒烟覆盖合同、发票、RAG、风险解释和报告草稿；每次 Provider attempt 都必须有对应持久审计记录。该 smoke 只证明链路，不证明字段准确率、99% 合法率、代表性性能或正式 AC。
- 正式验收仍缺代表性合同/发票标准答案集、已审批 50/100 条检索集、正式 UAT、发布与回滚决定；production 环境、安全、容量、监控告警和恢复证据继续 `BLOCKED/NOT_RUN`。

## 5. 回滚

- 运行时首选设置 `AI_PROVIDER_CALLS_ENABLED=false`：业务恢复确定性提取/生成器或受控降级，既有 AI 审计与已采用事实继续保留追溯。
- `/metrics` 可通过 `METRICS_ENABLED=false` 停止注册；不得通过删除鉴权或公开 query token 规避采集配置。
- 数据库 downgrade 只允许在确认不存在依赖新增 AI 列的业务事实后执行；`022` downgrade 会把遗留空币种回填为 CNY，因此不作为无审计的数据修复手段。
- production canary、模型/价格/端点变化、真实 Embedding Provider 和外部监控暴露必须另立环境 Profile 或后续 CR。
