# FinAudit Agent 技术规格

## 1. 文档定位

本文是面向开发的最小实现指南，描述当前可执行事实、稳定架构边界和可观察契约。

本文不复制完整 DTO、数据库字段表、迁移实现、测试用例或历史决策；`archive/legacy-v1/` 中的旧文档只供追溯，不能覆盖第 3 节的机器事实。

未形成唯一事实来源的设计统一标记为 `BLOCKED`；实现者不得猜字段、状态、错误码、权限或默认值。

本项目当前是增量交付状态。文档存在、代码存在、测试通过和正式验收必须分别判断。

## 2. 开发目标与非目标

### 2.1 P0 开发目标

- 单组织内完成财务文件、合同、补充协议、发票、制度知识库、审核任务、风险和报告的可追溯闭环。
- Backend 强制认证、授权、职责分离、状态迁移、并发控制和审计。
- 长任务可恢复，失败、重试、取消和投递过程可追踪。
- PostgreSQL 保存业务事实，文件制品与派生索引可以从权威事实恢复。
- AI 只提供提取、解释、检索辅助和草稿，不决定审批或确定性财务结论。

### 2.2 非目标

- 多租户、自定义角色和动态权限中心。
- GraphRAG、多 Agent 或动态规则中心。
- 将 Redis、Qdrant、前端状态或模型输出作为业务事实。
- 在未冻结合同前通过占位 DTO、默认 ID 或 Mock 数据补齐业务链路。
- 用静态页面、离线单测或存活探针证明真实业务运行或验收通过。

## 3. 单一事实来源（SSOT）

| 事实类型 | 唯一来源 | 其他材料的角色 |
|---|---|---|
| 产品范围、业务目标、验收标准 | `PRODUCT_REQUIREMENTS.md` | 技术文档不得降低门槛 |
| 当前已实现 HTTP 路径、方法、Schema、状态码 | FastAPI 运行时生成的 OpenAPI | Markdown 只解释通用规则 |
| 当前成功与错误包络 | Backend Pydantic Schema 与异常处理器 | 前端按运行时合同解析 |
| 当前物理数据库 | `backend/alembic/versions/` 的 accepted 线性 head | ORM 是应用映射，不是迁移历史 |
| 当前 ORM 映射 | `backend/app/models/` | 必须与 accepted head 一致 |
| Backend/Worker 配置 | `infra/env/.env.example`、`Settings`、本地 AI Policy 的交集 | 部署文档只说明注入方式 |
| 当前前端页面与角色导航 | `frontend/src/router/index.ts` | 页面文档只说明体验目标 |
| 当前前端 HTTP 行为 | `frontend/src/services/api.ts` | 页面不得另建请求约定 |
| 当前 AI 离线行为 | `backend/app/ai/` 的类型、校验器和本地 Policy | 不代表真实 Provider 可用 |
| 阶段阻断 | 本文第 15 节和仍可复现的基线差异 | 候选方案不能自动解除阻断 |

SSOT 使用规则：

1. 已实现接口以运行时 OpenAPI 为准；OpenAPI 中不存在的业务接口视为未实现。
2. 新接口先形成可评审的 Pydantic/Router 合同，再生成 OpenAPI，不在 Markdown 预写完整 DTO。
3. 数据库当前形状以 accepted Alembic head 为准；目标表清单不等于当前数据库。
4. 业务枚举在 Backend domain/Schema 中定义一次，并通过测试校验 OpenAPI、ORM 和数据库约束投影。
5. 错误码在 Backend 可执行注册或异常映射中定义一次，不维护第二份手工全局目录。
6. 统计值从代码生成，不把接口、表、函数或文件总数写成永久合同。

## 4. 总体架构边界

`Browser -> /api/v1 -> Router -> Service -> Repository/Port -> PostgreSQL/Adapter`；长任务由 Service 在 PostgreSQL 事务中写 Job 与 Outbox，再由 Worker 重读权威输入。

强制边界：

- Frontend 只能访问 Backend，不得直连 PostgreSQL、Redis、MinIO、Qdrant 或模型服务。
- Router 只处理 HTTP、认证、参数校验、依赖注入和错误映射，不直接访问数据库或外部模型。
- Service 负责权限、业务不变量、事务边界、幂等和状态迁移。
- Repository 负责持久化查询和锁，不返回未经权限裁剪的跨组织数据。
- Adapter 封装对象存储、检索、OCR、模型和消息系统，不把第三方异常原文透传给客户端。
- 长耗时工作由 Job/Worker 执行；同步 API 只完成短事务和任务受理。
- PostgreSQL 是业务事实唯一来源。
- MinIO 保存文件和报告制品；数据库保存身份、归属、摘要、版本和状态。
- Redis/Broker 只负责唤醒和传输，不保存权威 Job 输入或完成事实。
- Qdrant 只保存可重建向量和过滤投影，不反向覆盖 PostgreSQL。
- 已激活、已发布或已完成版本不得原地覆盖；变更创建新版本并保留追溯关系。

## 5. 模块责任

### 5.1 Backend

- `app/api/`：HTTP Router、依赖、异常处理和 OpenAPI 投影。
- `app/schemas/`、`app/services/`：外部合同，以及业务用例、权限、状态迁移和事务编排。
- `app/repositories/`、`app/models/`：SQLAlchemy 查询、锁、持久化边界和当前 ORM 投影。
- `app/workers/`：Celery 应用、最小消息合同和后续 Job handler。
- `app/ai/`：Provider-neutral 合同、Policy、路由、预算、输出校验和网络边界。
- 文档处理、检索、审核、规则和报告模块：负责确定性处理、授权复核、风险聚合和安全制品生成。

### 5.2 Frontend

- `router/` 与 `stores/`：页面入口、导航和会话视图状态；不得充当后端权限来源。
- `services/api.ts`：唯一 HTTP 客户端与响应净化边界。
- `views/` 与 `components/`：页面编排、用户操作及加载、空、错误、状态和 Trace 反馈。

## 6. 当前 HTTP 与 OpenAPI 合同

### 6.1 当前实现事实

- FastAPI 应用先校验 `Settings` 和本地 AI Policy，再构造应用对象。
- 当前运行时 OpenAPI 只代表代码中真实注册的 Router。
- 当前已注册 `/health`；它只证明 Backend 进程存活。
- 当前 `/api/v1` 已注册 Auth、用户管理、Break-glass、操作日志、单文件上传/读取、合同/补充协议、发票、合同发票关系、供应商、制度/知识索引与评测、RAG/反馈、审核执行和正式报告 Router；其严格方法、Schema 和状态码以运行时 OpenAPI 为准。工作台摘要、依赖健康和未注册路径仍不能由旧接口目录或静态页面推断为已实现。
- `prod` 环境关闭 OpenAPI、Swagger UI 和 ReDoc。

### 6.2 路径与传输

- 业务 API 固定使用同源 `/api/v1`。
- `/health` 是前缀外存活探针，不探测外部依赖。
- JSON 请求使用 `application/json`；上传使用浏览器生成 boundary 的 multipart。
- 文件流和明确的 HTTP 204 可以不使用成功包络。
- UUID 使用标准小写文本，时间使用 UTC RFC 3339。
- 金额、税额和税率在 JSON 中使用十进制字符串，禁止用浮点数做财务计算。

### 6.3 成功包络

普通成功响应以 Pydantic `SuccessResponse` 为唯一字段来源；`data` 必须是接口自己的严格 Schema，成功码和消息保持稳定，Trace 与时间由 Backend 生成。本文不复制字段表。

### 6.4 错误包络

错误响应以 Pydantic `ErrorResponse` 和异常处理器为唯一字段来源；机器错误码稳定可分类，消息可安全展示，详情结构化且脱敏，响应体 Trace 与 `X-Trace-ID` 一致。本文不维护第二份字段表。

错误处理必须满足：

- Pydantic 422 统一映射为 `VALIDATION_ERROR`。
- 校验详情只暴露安全字段位置和固定原因，不返回原始输入。
- 不可见资源统一按 404 处理，避免资源枚举。
- 未处理异常统一返回 500 `INTERNAL_ERROR`，不得返回堆栈、SQL、路径或 secret。
- HTTP 405 使用稳定的通用错误，不泄露内部 Router 细节。
- 新业务错误必须先进入可执行异常映射和 OpenAPI 测试，不能只写 Markdown。

### 6.5 Trace

- Middleware 为每个请求生成 `trace_id`。
- 合法 W3C `traceparent` 可以提供 Trace ID；非法值安全降级为新 UUID。
- 响应体和 `X-Trace-ID` 必须使用同一值。
- 日志只记录 Trace ID、错误分类和必要上下文，不记录 secret 或完整业务正文。

### 6.6 幂等与并发

- 关键创建和异步动作使用 `Idempotency-Key`。
- 幂等记录与业务写入或 Job 创建必须位于同一 PostgreSQL 事务。
- 相同调用者、路径、Key 和请求摘要的重放返回既有结果，不重复副作用。
- 相同 Key 对应不同请求时返回稳定冲突错误。
- 可变资源使用 `row_version` 做 CAS；影响行数不符合预期时不得静默覆盖。
- 具体请求字段和冲突错误码必须来自该接口 OpenAPI；未出现时按 `BLOCKED` 处理。

### 6.7 `invoice-detail-read-v1`

- `GET /api/v1/invoices/{invoice_id}` 是当前已实现的财务详情 Router；`invoice_id` 只接受 canonical lowercase UUID。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`；Repository 只能使用 `Actor.organization_id + invoice_id + deleted_at IS NULL` 查询，跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。
- 成功返回 `SuccessResponse[InvoiceDetailData]`；严格字段以 `app/schemas/invoices.py` 和运行时 OpenAPI 为唯一机器事实源。金额、税额、税率、数量和单价使用非指数十进制字符串或 `null`，明细按 `line_no + id` 稳定排序。
- 响应只投影 accepted `invoices/invoice_items` 当前字段，不返回 `organization_id`、供应商标识、证据 JSON、关键事实哈希、确认 Actor 或其他内部字段；成功响应固定 `Cache-Control: private, no-store`。
- 本接口只读且无副作用，不接受 `Idempotency-Key` 或 `row_version` 请求；响应中的 `row_version` 使用正整数十进制字符串以保持 PostgreSQL BIGINT 精度，仅供显示和后续尚未冻结的写合同使用。证据定位、重复处置、合同关系、供应商、修改历史及所有写操作不属于本接口。

### 6.8 `invoice-list-read-v1`

- `GET /api/v1/invoices` 提供真实发票列表到既有详情的最小只读入口；请求必须先得到数据库重验后的 Actor，再要求 `financial.read`，Repository 只能读取 `Actor.organization_id + deleted_at IS NULL` 范围。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422，当前版本不支持页码、关键字、状态、重复状态、日期或客户端排序筛选。
- 排序固定为 `invoice_date DESC NULLS LAST, id DESC`；Repository 使用 keyset 条件读取 `page_size + 1` 条，不执行 OFFSET 或 total count。`cursor` 是无 padding 的 canonical base64url UTF-8 JSON，解码后精确为 `{v:1, invoice_date: YYYY-MM-DD|null, id: canonical-lowercase-UUID}`；长度上限 256，非法编码、非 canonical 表示、未知键或非法字段固定 422。Cursor 只是不可信位置输入，不包含机密、不授予权限且不替代 Actor 组织边界。
- 非空日期 cursor 的后继条件为更早日期、同日更小 UUID 或 `invoice_date IS NULL`；空日期 cursor 只允许 `invoice_date IS NULL AND id < cursor.id`。成功返回 `SuccessResponse[InvoiceListData]`，其中 `data` 精确为 `{items, page_size, next_cursor}`；只有读取到额外一条时才基于本页最后一项生成 `next_cursor`，因此 `next_cursor` 非空时 `items` 必须恰有 `page_size` 项，末页为 `null`。列表项只含 `id`、`invoice_code`、`invoice_number`、`invoice_date`、`seller_name`、`total_amount`、`currency`、`confirmation_status`、`duplicate_status`、`status`；金额仍使用非指数十进制字符串或 `null`。
- 响应不返回组织、税号、供应商、明细、证据、关键哈希、Actor、`row_version`、主合同、更新时间或聚合指标；成功响应固定 `Cache-Control: private, no-store`。本接口无副作用、不接受 `Idempotency-Key`，运行时 OpenAPI 与 `app/schemas/invoices.py` 是机器事实源。

### 6.9 `contract-detail-read-v1`

- `GET /api/v1/contracts/{contract_id}` 提供 accepted `contracts` 当前持久化行的只读详情；`contract_id` 只接受 canonical lowercase UUID。它不是按审核基准日期应用补充协议后的有效字段投影。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`；Repository 只能使用 `Actor.organization_id + contract_id + deleted_at IS NULL` 查询，跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。
- 成功返回 `SuccessResponse[ContractDetailData]`，字段精确为 `id`、`contract_no`、`name`、`party_a_name`、`party_a_tax_no`、`party_b_name`、`party_b_tax_no`、`amount`、`currency`、`signed_date`、`effective_date`、`expiry_date`、`payment_method`、`payment_terms`、`confirmation_status`、`status`、`row_version`。`name` 必须是字符串；`contract_no`、双方名称与税号、`payment_method`、`payment_terms` 均为字符串或 `null`。金额使用非指数十进制字符串或 `null`，币种使用三个大写 ASCII 字母或 `null`，日期使用 `YYYY-MM-DD` 或 `null`，`row_version` 使用正整数十进制字符串。`confirmation_status` 精确为 `unconfirmed|confirmed|rejected`，`status` 精确为 `draft|active|expired|terminated|archived`。
- 响应不返回 `organization_id`、`supplier_id`、证据、关键事实哈希、确认/创建/更新 Actor、时间戳、补充协议、附件、关联、解析版本或历史；成功响应固定 `Cache-Control: private, no-store`。本接口只读且无副作用，不接受 `Idempotency-Key` 或 `row_version` 请求；运行时 OpenAPI 与 `app/schemas/contracts.py` 是机器事实源。

### 6.10 `contract-list-read-v1`

- `GET /api/v1/contracts` 提供真实合同列表到合同详情的最小只读入口；请求必须先得到数据库重验后的 Actor，再要求 `financial.read`，Repository 只能读取 `Actor.organization_id + deleted_at IS NULL` 范围。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422，当前版本不支持页码、关键字、状态、确认状态、供应商、日期或客户端排序筛选。
- 排序固定为 `effective_date DESC NULLS LAST, id DESC`；Repository 使用 keyset 条件读取 `page_size + 1` 条，不执行 OFFSET 或 total count。`cursor` 是无 padding的 canonical base64url UTF-8 JSON，解码后精确为 `{v:1, effective_date: YYYY-MM-DD|null, id: canonical-lowercase-UUID}`；长度上限 256，非法编码、非 canonical 表示、未知键或非法字段固定 422。Cursor 只是不可信位置输入，不包含机密、不授予权限且不替代 Actor 组织边界。
- 非空日期 cursor 的后继条件为更早日期、同日更小 UUID 或 `effective_date IS NULL`；空日期 cursor 只允许 `effective_date IS NULL AND id < cursor.id`。成功返回 `SuccessResponse[ContractListData]`，其中 `data` 精确为 `{items, page_size, next_cursor}`；只有读取到额外一条时才基于本页最后一项生成 `next_cursor`，因此 `next_cursor` 非空时 `items` 必须恰有 `page_size` 项，末页为 `null`。
- 列表项精确为 `id`、`contract_no`、`name`、`party_b_name`、`amount`、`currency`、`effective_date`、`expiry_date`、`confirmation_status`、`status`；`name` 与两个状态字段非空，`contract_no` 与 `party_b_name` 为字符串或 `null`，金额、币种、日期及两个状态闭集沿用详情合同。响应不返回组织、供应商标识、税号、付款文本、`row_version`、时间戳、补充协议、附件、关联或聚合指标；成功响应固定 `Cache-Control: private, no-store`。本接口无副作用、不接受 `Idempotency-Key`，运行时 OpenAPI 与 `app/schemas/contracts.py` 是机器事实源。

### 6.11 `invoice-primary-contract-read-v1`

- `GET /api/v1/invoices/{invoice_id}/primary-contract` 提供一张可见发票当前唯一已确认主合同的只读投影；它不返回候选列表、不重新计算匹配依据、不解释任意形状的 `match_reasons_json`，也不声明合同字段已经按审核基准日期应用补充协议。`invoice_id` 只接受 canonical lowercase UUID，接口不接受 Query 参数，未知参数固定 422。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`。Repository 必须先以 `Actor.organization_id + invoice_id + deleted_at IS NULL` 验证目标发票；跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。主合同查询必须以 `invoice_id + status = confirmed_primary + deleted_at IS NULL` 命中 accepted 009 的条件唯一索引，并同时联查合同和发票，要求关系、合同、发票均未软删除且合同、发票均属于 Actor 组织；不可见合同对应的关系不得泄露。
- 成功返回 `SuccessResponse[InvoicePrimaryContractData]`，其中 `data` 精确为 `{primary_contract}`。`primary_contract` 为 `null` 或复用第 6.10 节十个字段与严格约束的 `ContractListItemData`；可见发票没有已确认主合同时返回 200 与 `null`，不使用 404。若持久化状态违反唯一性或公开 Schema，必须失败关闭并由通用异常边界返回脱敏 500。
- 响应不返回关系 ID、其他关系状态、`suggested_by`、`organization_id`、`invoice_id`、`match_reasons_json`、税号、供应商、关系或合同 `row_version`、确认/取消/创建 Actor、时间戳、取消原因、证据、哈希、分数或冗余 `is_primary`。成功响应固定 `Cache-Control: private, no-store`。本接口只读且无副作用，不接受 `Idempotency-Key`；主合同匹配候选查询、建议、确认、替换、取消和历史读取合同仍未冻结，Frontend 必须保持不可用。

### 6.12 `supplementary-agreement-header-list-read-v1`

- `GET /api/v1/contracts/{contract_id}/supplementary-agreements` 只读取一个可见合同下 accepted 009 的当前、未软删除补充协议 header；`contract_id` 只接受 canonical lowercase UUID。它不返回字段级 change，不计算 `is_effective`、`is_applicable` 或有效合同字段，也不表示协议已进入任何审核快照。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`。Repository 必须先以 `Actor.organization_id + contract_id + deleted_at IS NULL` 验证父合同；跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。子查询必须同时约束协议的 `organization_id`、`contract_id` 与 `deleted_at IS NULL`，并联查父合同再次强制同组织且未软删除；可见合同没有补充协议时返回 200 空页。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422。排序固定为 `effective_date DESC, id DESC`，Repository 使用 keyset 条件读取 `page_size + 1` 条，不执行 OFFSET 或 total count。`cursor` 是长度不超过 256 的无 padding canonical base64url UTF-8 JSON，解码后精确为 `{v:1, effective_date:YYYY-MM-DD, id:canonical-lowercase-UUID}`；非法编码、非 canonical 表示、未知键或非法字段固定 422。后继条件为更早生效日期，或同日更小 UUID。Cursor 不包含机密、不授予权限且不替代父子组织边界。
- 成功返回 `SuccessResponse[SupplementaryAgreementHeaderListData]`，其中 `data` 精确为 `{items, page_size, next_cursor}`。列表项精确为 `id`、`agreement_no`、`name`、`signed_date`、`effective_date`、`status`、`confirmation_status`；`agreement_no` 与 `signed_date` 可为 `null`，`name` 是数据库非空的原样字符串，`effective_date` 非空。`status` 精确为 `draft|pending_confirmation|confirmed|rejected|archived`，`confirmation_status` 精确为 `unconfirmed|confirmed|rejected`；两个状态独立原样展示，不从组合推导生效资格。只有读取到额外一条时才基于本页最后一项生成 `next_cursor`，因此 `next_cursor` 非空时本页必须恰有 `page_size` 项，末页为 `null`。
- 响应不返回 `organization_id`、路径中已有的 `contract_id`、`row_version`、确认原因、关键事实哈希、任何 Actor 或时间戳、删除事实、证据、附件、字段变更或有效字段投影。成功响应固定 `Cache-Control: private, no-store`；本接口无副作用、不接受 `Idempotency-Key`。当前 accepted 索引只支持已知 `contract_id` 的父范围读取，本合同不得扩张为组织级补充协议列表；隔离 PostgreSQL current-head Gate 已覆盖同日 UUID tie-break、软删除和分页路径，但不构成高基数容量或性能证明。

### 6.13 `contract-primary-invoice-list-read-v1`

- `GET /api/v1/contracts/{contract_id}/primary-invoices` 只读取当前以一个可见合同为 `confirmed_primary` 主合同的发票摘要；`contract_id` 只接受 canonical lowercase UUID。它不返回候选、建议、取消历史、关系 ID、匹配依据或任何关联写能力。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`。Repository 必须先以 `Actor.organization_id + contract_id + deleted_at IS NULL` 验证父合同，跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。分页查询必须联查关系、合同和发票，固定约束 `ContractInvoice.contract_id`、`status = confirmed_primary`、关系未软删除、合同与发票均属于 Actor 组织且均未软删除；可见合同没有当前主合同发票时返回 200 空页。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422。排序固定为关系中的 `invoice_id ASC`，Repository 使用 accepted 009 的 `(contract_id, invoice_id)` active-pair 条件唯一索引执行 keyset 条件与 `LIMIT page_size + 1`，不执行 OFFSET、total count、全量物化或 Python 排序。`cursor` 是长度不超过 256 的无 padding canonical base64url UTF-8 JSON，解码后精确为 `{v:1,id:canonical-lowercase-UUID}`；非法编码、非 canonical 表示、未知键或非法字段固定 422。后继条件为 `invoice_id > cursor.id`；Cursor 不包含机密、不授予权限且不替代父子组织边界。
- 成功返回 `SuccessResponse[ContractPrimaryInvoiceListData]`，其中 `data` 精确为 `{items, page_size, next_cursor}`，`items` 复用第 6.8 节严格字段与约束的 `InvoiceListItemData`。只有读取到额外一条时才基于本页最后一个 `invoice_id` 生成 `next_cursor`，因此 `next_cursor` 非空时本页必须恰有 `page_size` 项，末页为 `null`；页内 ID 必须严格升序且不得重复。
- 响应不返回 `organization_id`、关系 ID、关系状态冗余字段、`match_reasons_json`、`suggested_by`、确认/取消/创建 Actor 或时间戳、取消原因、关系 `row_version`、候选分数、证据、哈希或历史。成功响应固定 `Cache-Control: private, no-store`；本接口无副作用、不接受 `Idempotency-Key`。UUID 顺序只提供与现有索引一致的稳定有界遍历，不声明时间排序；若未来要求按发票日期或其他业务字段排序，必须先冻结匹配索引与新 cursor 合同。

### 6.14 `invoice-exact-duplicate-candidates-read-v1`

- `GET /api/v1/invoices/{invoice_id}/duplicate-candidates` 只读取一张可见发票基于当前持久化三元组 `invoice_code + invoice_number + seller_tax_no` 的精确重复候选；`invoice_id` 只接受 canonical lowercase UUID。它不执行 trim、大小写折叠、模糊匹配、供应商归一化、税务真伪校验或历史版本回放，也不写入 `duplicate_status`、风险、审核任务或 operation-log。
- 请求必须先得到数据库重验后的 Actor，再要求 `financial.read`。Repository 必须先以 `Actor.organization_id + invoice_id + deleted_at IS NULL` 读取源发票锚点；跨组织、不存在和软删除统一返回 404 `RESOURCE_NOT_FOUND`。若源发票 `status = voided`，`basis_status = source_voided`；否则三元组任一字段为数据库 `NULL` 时 `basis_status = incomplete_identity`；其余情况为 `ready`。状态判定优先级固定为 `source_voided` 高于 `incomplete_identity`，字符串值不做隐式清理或转换。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422。`cursor` 是长度不超过 256 的无 padding canonical base64url UTF-8 JSON，解码后精确为 `{v:1,id:canonical-lowercase-UUID}`；非法编码、非 canonical 表示、未知键或非法字段固定 422。即使当前 `basis_status` 不是 `ready`，传入 cursor 也必须先完成同一严格校验，不能形成宽松旁路。
- 只有 `basis_status = ready` 才执行候选查询。候选必须同时满足：与源发票属于同一 Actor 组织、不是源发票自身、未软删除、`status <> voided`，且三元组逐字段使用数据库等值比较；`archived` 候选保留。排序固定为 `id ASC`，后继条件为 `id > cursor.id`，Repository 使用 `LIMIT page_size + 1`，不执行 OFFSET、total count、全组织物化或 Python 排序。该条件复用 accepted `idx_invoices_duplicate_lookup` 的组织与三元组前缀；UUID tie-break 未声明为容量或性能证明。
- 成功返回 `SuccessResponse[InvoiceDuplicateCandidateListData]`，其中 `data` 精确为 `{basis_status, items, page_size, next_cursor}`。`basis_status` 精确为 `ready|incomplete_identity|source_voided`；`items` 复用第 6.8 节严格字段与约束的 `InvoiceListItemData`，页内 ID 必须严格升序且不得重复。只有读取到额外一条时才基于本页最后一个候选 ID 生成 `next_cursor`，因此 `next_cursor` 非空时本页必须恰有 `page_size` 项；`basis_status` 不是 `ready` 时必须固定返回空 `items` 与 `next_cursor = null`。
- 响应不返回源发票三元组、`seller_tax_no`、`organization_id`、供应商、证据、关键事实哈希、Actor、`row_version`、匹配分数、自由文本原因或写能力；成功响应固定 `Cache-Control: private, no-store`。`ready + 空页` 只表示本次数据库读取未发现精确候选，不等同于税务唯一性、外部真伪或人工确认结论。当前普通 `READ COMMITTED` Session 的源锚点与候选查询不声明单一 MVCC 快照；跨页也不提供冻结快照。重复确认、例外批准、重新检测、状态写入和高风险落库仍受公开写合同、CAS/幂等与 `BLOCKED-OPERATION-LOG` 约束，Frontend 必须保持不可用。

### 6.15 `invoice-exact-duplicate-pair-read-v1`

- `GET /api/v1/invoices/{invoice_id}/duplicate-candidates/{candidate_id}` 只核对两个已知发票 UUID 在同一条数据库语句中是否仍构成第 6.14 节的精确候选；两个路径参数分别只接受 canonical lowercase UUID，非法格式固定 422。两个 UUID 相等不属于路径格式错误，不返回 422，而是按下一条的自比较规则统一返回 404。Query 必须为空，未知参数固定 422。请求先得到数据库重验后的 Actor，再要求 `financial.read`。
- Repository 必须使用一条以两个主键为边界的自连接点查语句，同时要求 source 与 candidate 都属于 `Actor.organization_id`、未软删除、`status <> voided`，source 三元组 `invoice_code + invoice_number + seller_tax_no` 均非数据库 `NULL`，并与 candidate 三元组逐字段数据库等值；不执行 trim、大小写折叠、供应商归一化、模糊匹配、组织级扫描、count 或 Python 搜索。`archived` 两端均允许。任一对象不存在、不可见、软删除、voided、身份不完整、自比较或已不再精确匹配，统一返回 404 `RESOURCE_NOT_FOUND`，不得泄露哪一项失败。
- 成功返回 `SuccessResponse[InvoiceExactDuplicatePairData]`，其中 `data` 精确为 `{source, candidate, exact_identity}`。`source` 与 `candidate` 各自复用第 6.8 节的严格 `InvoiceListItemData`，且 ID 必须分别等于两个路径参数、互不相同、状态不得为 `voided`；`exact_identity` 精确为三个数据库非 `NULL` 的原样字符串 `invoice_code`、`invoice_number`、`seller_tax_no`，允许空字符串或纯空白且不得隐式清理，并必须与两项摘要中的 `invoice_code/invoice_number` 一致。响应不返回明细、组织、供应商、证据、哈希、Actor、`row_version`、候选数量或写能力。
- 成功响应固定 `Cache-Control: private, no-store`。200 只证明该单条数据库语句快照中这两个对象仍满足当前持久化三元组逐字段等值，不表示税务真伪、唯一性、高风险已落库、人工确认或 `duplicate_status` 已更新。该只读 API 不接受 Idempotency-Key，不写风险、审核任务、状态或 operation-log；重复确认、例外批准和重新检测继续不可用。

### 6.16 `contract-effective-fields-read-v1`

- `contract_fields` 保存原合同的可扩展候选、确认值和逐字段证据；`supplementary_agreement_changes` 保存一个补充协议对字段的当前变更集合。`field_code` 固定使用 `^[a-z][a-z0-9_.]{0,79}$`，`value_type` 精确为 `string|number|date|json`，同一合同的 `field_code` 唯一，同一补充协议的 `field_code` 唯一；P0 不引入 `change_seq`。草稿变更集合的整组替换由 `user_corrections` 保存 before/after 和原因，已确认或已拒绝协议及其变更不得原地覆盖。
- 合同核心字段固定为 `contract_no`、`name`、`party_a_name`、`party_a_tax_no`、`party_b_name`、`party_b_tax_no`、`amount`、`currency`、`signed_date`、`effective_date`、`expiry_date`、`payment_method`、`payment_terms`；扩展字段必须先存在于同一合同的 `contract_fields`。金额和日期在公开 JSON 中分别使用十进制字符串和 `YYYY-MM-DD` 字符串，不使用二进制浮点。扩展字段只有 `confirmation_status=confirmed` 且 `confirmed_value_json` 非空时才进入有效投影；extracted 候选只在字段详情中展示，不能抬升为有效财务事实。补充协议不得通过未知 `field_code` 隐式创建合同字段。
- `GET /api/v1/contracts/{contract_id}/effective-fields?baseline_date=YYYY-MM-DD` 读取一个可见合同在显式基准日期的有效字段投影；`baseline_date` 必填且 Query 不接受其他字段。请求必须先得到数据库重验后的 Actor，再要求 `financial.read`；跨组织、不存在或软删除统一返回 404 `RESOURCE_NOT_FOUND`。
- 只有协议 `status=confirmed`、协议 `confirmation_status=confirmed`、全部变更 `confirmation_status=confirmed` 且 `effective_date <= baseline_date` 时，该协议才整体参与投影。任一变更未确认时整个协议不应用；同一字段同一生效日存在两个可应用协议时返回 409 `EFFECTIVE_FIELD_CONFLICT`，不得按数据库读取顺序任选。不同生效日按日期升序重放，同日无冲突字段可共同应用。
- 成功返回 `SuccessResponse[EffectiveContractData]`；`data` 精确为 `{id,baseline_date,confirmation_status,fields,applied_agreement_ids,row_version}`。`fields` 按 `field_code ASC`，每项精确为 `{field_code,value_type,original_value,effective_value,source_agreement_id,source_effective_date}`；原合同来源的两个 source 字段均为 `null`，补充协议来源则同时非空。响应不返回组织、证据正文、内部哈希、Actor 或删除事实，固定 `Cache-Control: private, no-store`，且不接受 `Idempotency-Key`。

### 6.17 `supplementary-agreement-changes-write-v1`

- `GET /api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}` 返回一个可见协议及按 `field_code ASC` 排序的字段变更；父合同、协议和变更必须在同一组织，跨组织、不存在或软删除统一 404。读取要求 `financial.read`，不接受 `Idempotency-Key`。
- `PUT /api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}/changes` 只允许 `contracts.manage`，请求体精确为 `{row_version,reason,changes}`。`changes` 为 1～100 个互不重复字段的完整替换集合，每项精确为 `{field_code,value_type,new_value,evidence_block_id,page_no,quote_text,bbox}`；`old_value` 必须由服务端按协议生效日、排除本协议后计算并持久化，不接受客户端声明。未知合同字段、非有限 number、非法 date、证据跨组织或证据链不一致固定 422/409 安全失败。动作只允许协议处于 `draft|pending_confirmation`，以协议 `row_version` 执行 CAS；成功把全部变更重建为 `unconfirmed`、协议置为 `pending_confirmation`、协议版本加一，并追加一条脱敏 operation log 和一条包含完整 before/after 的受控 `user_corrections`。
- `POST /api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}/decision` 只允许 `contracts.manage`，请求体精确为 `{row_version,decision,reason}`，其中 `decision=confirmed|rejected`。决定只允许协议处于 `pending_confirmation`；确认要求至少一项变更且所有当前变更都有完整原文证据，拒绝允许证据为空。成功在同一事务把协议和全部变更同时设为 confirmed 或 rejected，写同一 Actor/时间，协议版本加一。其他状态、旧版本或重复决定均返回 409，不产生部分写入。
- 两个写接口都要求 `Idempotency-Key`，幂等范围为组织、Actor、HTTP method、canonical path、请求体和 24 小时有效期；相同键相同请求重放首次脱敏响应，不重复写 correction/log，不同请求复用同一键返回 409 `IDEMPOTENCY_KEY_REUSED`。成功响应固定 `Cache-Control: private, no-store` 和 `Idempotency-Replayed: true|false`。

### 6.18 `contract-invoice-link-write-v1`

- `GET /api/v1/invoices/{invoice_id}/contract-candidates` 要求 `financial.read`，读取同组织、未软删除且 `confirmation_status=confirmed`、`status<>draft` 的合同，以发票日期作为补充协议投影基准；发票日期为空时只使用合同原始确认事实，不推测基准日。已过期、终止或归档合同仍可作为历史发票候选，不能只按当前 active 状态过滤。每个候选只返回合同摘要及税号、名称、日期三个独立的 `matched|mismatched|unavailable` 状态和稳定原因 code，不生成总分、不自动确认、不写关系。结果按三个状态优先级及合同 UUID 稳定排序，并返回当前 `invoice_row_version`；当前 P0 返回组织内全部符合条件的候选，不声明高基数容量或性能保证。
- `POST /api/v1/invoices/{invoice_id}/contract-link-suggestions` 只允许 `links.suggest`，请求体精确为 `{contract_id,invoice_row_version,reason}`。服务端锁定发票后重新读取目标合同并重新计算匹配依据，客户端不能提交或覆盖理由；目标必须与发票同组织、两端未软删除，且合同仍为 `confirmation_status=confirmed`、`status<>draft`。成功创建新的 `suggested` 关系，`suggested_by=user`，推进发票版本并追加操作日志。相同合同和发票已有未取消关系时返回 409 `CONTRACT_INVOICE_RELATION_EXISTS`；已取消历史不阻止创建新关系。
- `PUT /api/v1/invoices/{invoice_id}/primary-contract` 只允许 `links.manage_primary`，请求体精确为 `{suggestion_id,invoice_row_version,relation_row_version,reason}`。目标关系必须是同票、同组织、未软删除的 `suggested` 行且版本匹配，目标合同在确认时仍须满足已确认、非草稿和可见条件；第一次确认把该行推进为 `confirmed_primary`。若已有另一主合同，则同一事务先把旧关系推进为 `cancelled` 并保存替换原因，再确认新关系；不得覆盖或删除旧行。`contract_admin` 没有该权限，系统管理员和只读 deny-overrides 也不能绕过。发票行锁和条件唯一索引共同保证同票并发确认最多一个成功，输家固定为 409 `ROW_VERSION_CONFLICT` 或 `PRIMARY_CONTRACT_CONFLICT`。
- `POST /api/v1/invoices/{invoice_id}/primary-contract/cancel` 只允许 `links.manage_primary`，请求体精确为 `{invoice_row_version,relation_row_version,reason}`。当前主关系必须存在、版本匹配且仍为 `confirmed_primary`；成功把它推进为 `cancelled`，保存取消 Actor、数据库时间和非空原因，并推进发票版本。没有主关系为 409 `PRIMARY_CONTRACT_NOT_SET`，旧版本为 409 `ROW_VERSION_CONFLICT`，不得物理删除或软删除历史。
- `GET /api/v1/invoices/{invoice_id}/contract-link-history` 要求 `financial.read`，返回该票全部未软删除关系，按 `created_at ASC,id ASC`；每项只公开关系/合同 ID、状态、三个匹配理由、建议/确认/取消时间、取消原因和关系版本，不公开内部组织、Actor ID、哈希或删除事实。跨组织、不存在或软删除发票统一 404；空历史返回空数组。
- 三个写接口都要求调用者级 24 小时 `Idempotency-Key`，以 method、canonical path 和规范请求体摘要重放；冲突返回 `IDEMPOTENCY_KEY_REUSED`。建议关系只追加关系历史和 operation-log；主合同确认/替换/取消还必须追加 `correction_type=contract_invoice` 的 before/after 事实。发票、关系、必要的 `user_corrections`、operation-log 和幂等记录必须在同一 PostgreSQL 事务提交；所有响应固定 `Cache-Control: private, no-store`，写响应额外返回 `Idempotency-Replayed: true|false`。

### 6.19 `invoice-facts-write-v1`

- `file_process` 的既有 `scan → parse` Registry 身份保持不变。发票文件解析事务成功后，必须在同一 PostgreSQL 事务派生一个独立 `invoice_extract` Job 与 Outbox；输入只包含 canonical `file_id + parse_version_id`，处理队列固定为 `extraction`。提取 Job 只读取已持久化且属于同一文件的解析块，不重复读取或 OCR 原文件；重试、租约恢复和终结继续使用通用 Job fencing。非发票文件、`scan_only` 文件或失败解析不得创建提取 Job。
- `invoice_extract` 只生成未确认候选：创建一条新的 `invoices` 当前投影、基础 `invoice_items` 和唯一 `file_primary_business_objects` 绑定，绝不覆盖历史发票。每个非空候选必须引用同一文件解析版本中的真实 `block_id/page_no/quote/bbox/confidence`；缺失、模糊或低置信字段保留为空或候选状态，`confirmation_status` 固定为 `unconfirmed`、`status` 固定为 `draft`。确定性三元组 `invoice_code + invoice_number + seller_tax_no` 完整时，同一事务精确查询同组织、未软删除且非 `voided` 的历史发票，并把 `duplicate_status` 写为 `suspected|unique`；三元组不完整时保持 `not_checked`。该状态不表示税务真伪或人工重复结论。
- `GET /api/v1/invoices/{invoice_id}/evidence` 要求 `financial.read`，返回字段和明细当前证据、解析版本身份及 `row_version`；只能读取该发票唯一绑定文件内的解析块。`GET /api/v1/invoices/{invoice_id}/history` 要求 `financial.read`，按 `created_at,id` 返回 `invoice_field` 人工修正历史的 before/after、原因、角色、操作者和 trace；系统提取候选不是人工修正，只进入脱敏 operation-log。
- `PUT /api/v1/invoices/{invoice_id}/facts` 只允许 `invoices.manage`，请求体精确为 `{row_version,reason,facts,field_evidence,items}`。`facts` 是发票当前核心字段完整替换，`items` 是 0～1000 条按 `line_no` 唯一的完整替换，所有金额、税率、数量和单价使用有界非指数十进制字符串；`field_evidence` 的 field code 唯一。证据引用必须逐项在数据库重新校验为该发票绑定文件的同一真实块，且页码、原文和坐标完全一致。只允许未确认的 `draft` 或已拒绝的 `draft` 发票；成功重建明细、重算关键事实哈希、重置为 `unconfirmed + draft`、推进发票版本，并追加一条完整 before/after `UserCorrection` 和脱敏操作日志。已确认、`voided`、`archived` 或旧版本固定 409，不原地修改历史确认事实。
- `POST /api/v1/invoices/{invoice_id}/decision` 只允许 `invoices.manage`，请求体精确为 `{row_version,decision,reason}`，`decision=confirmed|rejected`。仅 `draft + unconfirmed` 可决定；确认要求代码、号码、日期、买卖方税务身份、不含税金额、税额、总额及其同文件证据全部存在，且不含税金额加税额与总额按两位十进制精确相等。成功写决定 Actor/数据库时间、推进版本并追加修正历史和日志；确认后 `status=confirmed`，拒绝后保持 `status=draft`。模型或 OCR 不能调用该权限替代人工确认。
- `POST /api/v1/invoices/{invoice_id}/duplicate-check` 只允许 `invoices.manage`，请求体精确为 `{row_version,reason}`。服务端在锁定源票后以同一事务重新执行三元组精确匹配，只有当前非终局重复状态才能写 `not_checked|unique|suspected`；结果未变化固定 409。`POST /api/v1/invoices/{invoice_id}/duplicate-decision` 同样只允许 `invoices.manage`，请求体精确为 `{row_version,candidate_id,decision,reason}`，其中 `decision=confirmed_duplicate|exception_approved`；必须锁定并重新验证两票仍同组织、可见、非作废且三元组精确相等，人工决定可替换先前人工决定但不得删除历史票。两个动作都推进版本并追加 `UserCorrection` 与脱敏日志；`confirmed_duplicate` 只是业务重复处置，不是发票真伪法律结论。
- 四个写接口都要求调用者级 24 小时 `Idempotency-Key`，请求摘要绑定 method、canonical path 和严格请求体；相同键相同请求重放首次脱敏响应，不重复写发票、明细、修正或日志，不同请求复用固定 409 `IDEMPOTENCY_KEY_REUSED`。发票/明细、文件绑定、幂等、修正、operation-log、Job/Step/Outbox 的对应一次业务转移必须各自在单一 PostgreSQL 事务中原子提交。字段或重复事实变化只把后续已冻结执行标为过期；审核表尚未交付前 `caused_outdated` 保持 false，不得伪造传播完成。

### 6.20 `supplier-runtime-v1`

- Supplier 的公开 `tax_number` 统一为 `COALESCE(unified_social_credit_code, tax_number)`；双列同时存在时必须逐字相同。generic 合同乙方/发票销售方税号只写物理 `tax_number`，不得猜测为 USCC；名称不参与唯一性或自动复用。
- 状态组合只允许 `unconfirmed/candidate`、`confirmed/active`、`rejected/inactive`。活动或失活供应商不能通过候选接口重新修改或激活；P0 不提供别名、拆分或复杂合并。
- 候选 resolver 只复用同组织、未删除、`confirmed/active` 且统一身份逐字相同的唯一供应商。已存在待处理候选时，合同/发票动作不得静默改写或退役它；人工确认可把候选激活，或把候选退役并把来源回填到唯一既有活动供应商。
- 所有 resolver 与人工处理事务固定锁序：组织行 → 来源合同/发票 → 按 UUID 升序的路径候选、来源已引用供应商和精确匹配供应商。路径候选与来源都使用 `row_version` CAS；被复用的活动供应商不得 UPDATE。
- 每个成功人工处理恰好追加一条 `correction_type=supplier_field` 的聚合纠错，before/after 只保存本次变化的 `standard_name/tax_number/confirmation_status/status/source_supplier_id` 逻辑事实；同事务写脱敏 `supplier.update` 操作日志。错误、日志和 Trace 不得回显完整税务身份或用户 reason。
- 稳定冲突为 HTTP 409 `SUPPLIER_STATE_CONFLICT`、`SUPPLIER_TAX_IDENTITY_CONFLICT`、`SUPPLIER_TAX_NUMBER_CONFLICT`；旧版本为 409 `RESOURCE_VERSION_CONFLICT`。Repository 只可按 SQLSTATE 和精确 constraint name 映射唯一冲突，不得 stringify driver exception。
- 读取要求 `financial.read` 并按组织/对象范围裁剪；人工处理要求 `suppliers.correct`。`finance_reviewer` 与 `contract_admin` 可以处理候选，`audit_reviewer` 只读，`system_admin` 不因技术角色获得业务正文或修改权。
- 当前运行时已注册 `GET /api/v1/suppliers`、`GET /api/v1/suppliers/{supplier_id}`、`POST /api/v1/suppliers/source-candidates` 与 `PATCH /api/v1/suppliers/{supplier_id}`。两个写入口都要求调用者级 `Idempotency-Key`，严格请求体、来源/候选 `row_version` CAS，并在一个 PostgreSQL 事务内写来源回填、供应商状态、幂等结果、聚合纠错与脱敏操作日志；精确 DTO 和错误响应以运行时 OpenAPI 与 `app/schemas/suppliers.py` 为机器事实。

### 6.21 `contract-facts-write-v1`

- `file_process` 对 `business_type=contract` 且 `processing_mode=auto_process` 的文件完成解析后，必须在同一 PostgreSQL 事务派生独立 `contract_extract` Job 与 Outbox；输入只包含 canonical `file_id + parse_version_id`，处理队列固定为 `extraction`。提取 Job 只读取同一文件已持久化的解析块，不重新读取或 OCR 原文件。非合同、`scan_only` 或失败解析不得创建该 Job。
- `contract_extract` 只生成未确认候选：创建新的 `contracts` 当前投影、对应 `contract_fields` 候选行和唯一 `file_primary_business_objects` 绑定，绝不覆盖已有合同。每个非空候选必须引用同一解析版本的真实 `block_id/page_no/quote/bbox/confidence`；无证据、冲突或无法确定的字段保持 `null`，数据库非空的 `contracts.name` 使用空字符串表达“尚无候选”，不得伪造占位名称。合同固定为 `confirmation_status=unconfirmed + status=draft`，不得由 OCR、规则或模型直接确认。
- `GET /api/v1/contracts/{contract_id}/evidence` 要求 `financial.read`，按第 6.16 节固定顺序返回全部 13 个核心字段的候选、确认状态与当前证据；没有候选的字段显式返回 `candidate_value=null + evidence=null`。证据必须在读取时重验为该合同唯一绑定文件中的真实解析块。`GET /api/v1/contracts/{contract_id}/history` 要求 `financial.read`，按 `created_at,id` 返回 `contract_field` 人工修正的 before/after、原因、角色、操作者和 trace；系统提取只写脱敏 operation-log，不伪装成人工修正。
- `PUT /api/v1/contracts/{contract_id}/facts` 只允许 `contracts.manage`，请求体精确为 `{row_version,reason,facts,field_evidence}`。`facts` 是 13 个核心字段的完整替换，金额使用有界非指数十进制字符串、币种使用三位大写代码、日期使用 `YYYY-MM-DD`；`field_evidence` 的字段码唯一，且每个非空事实必须恰有一条证据。服务端逐项重验 block、解析版本、页码、原文和坐标与绑定文件一致。只允许 `draft + unconfirmed|rejected`；成功逐字段 upsert 核心 `contract_fields`，数据库禁止删除的旧候选若不再出现则保留原文并标记 `rejected`，同时同步合同当前行、重置为 `unconfirmed + draft`、清除合同决定 Actor/时间、重算关键事实哈希、推进版本，并在同一事务追加完整 before/after `UserCorrection` 与脱敏 operation-log。已确认、非草稿或旧版本固定 409，不原地覆盖历史确认事实。
- `POST /api/v1/contracts/{contract_id}/decision` 只允许 `contracts.manage`，请求体精确为 `{row_version,decision,reason}`，其中 `decision=confirmed|rejected`。仅 `draft + unconfirmed` 可决定。确认至少要求 `contract_no`、`name`、甲乙双方名称和税号、`amount`、`currency`、`effective_date` 均为非空候选并有同文件证据；任何其他非空核心字段也必须有证据。成功在同一事务把合同及当前非空字段设为 confirmed 或 rejected、写决定 Actor/数据库时间、推进合同版本并追加修正历史和日志；确认后 `status=active`，拒绝后保持 `status=draft`。模型或 Worker 不得调用该权限替代人工决定。
- 两个写接口都要求调用者级 24 小时 `Idempotency-Key`，摘要绑定 method、canonical path 和严格请求体；相同键相同请求重放首次脱敏响应且不重复写合同、字段、纠错或日志，不同请求复用固定 409 `IDEMPOTENCY_KEY_REUSED`。合同/字段、文件绑定、幂等、纠错、operation-log、Job/Step/Outbox 的对应一次业务转移必须各自在单一 PostgreSQL 事务中原子提交。当前切片不新增数据库结构；回滚为停用新 Router/Worker 路由，已生成候选仍保持未确认且不进入有效合同投影。

### 6.22 `knowledge-base-catalog-read-v1`

- `GET /api/v1/knowledge-bases` 与 `GET /api/v1/knowledge-bases/{knowledge_base_id}` 为知识库浏览器入口提供组织范围内的真实目录；请求必须先得到数据库重验后的 Actor，再要求 `knowledge.use`。Repository 只读取 `Actor.organization_id` 下未删除知识库，跨组织、不存在或不可见统一返回 404 `RESOURCE_NOT_FOUND`，不得通过 Frontend 从制度列表反推或猜测知识库。
- 列表 Query 只允许可选 `cursor` 与 `page_size`；`page_size` 默认 20、范围 1～100。cursor 使用无 padding canonical base64url UTF-8 JSON `{v:1,id:canonical-lowercase-UUID}`；结果按 `id ASC`、后继条件 `id > cursor.id`、`LIMIT page_size + 1` 分页，不返回 total count。详情 Query 必须为空。
- 单项精确返回 `id`、`code`、`name`、`description`、`status`、`default_top_k`、`row_version`；`status` 只允许 `active|archived`，`default_top_k` 固定为 5，`row_version` 为正整数十进制字符串。列表精确返回 `{items,page_size,next_cursor}`。不返回组织、创建/更新 Actor、时间戳、删除字段、向量 Collection、Provider 配置或权限映射；成功响应固定 `Cache-Control: private, no-store`。
- `GET /api/v1/policy-documents` 增加可选 canonical `knowledge_base_id` Query；存在时仍先执行 `knowledge.use` 和组织裁剪，只返回该组织内该知识库的制度并保持既有 UUID keyset 分页。该扩展不改变未传参数的现有行为，也不增加制度写能力。
- 本合同只读、无副作用、不接受 `Idempotency-Key`。新增读取可通过删除新增 Router/Service/Frontend 接线回滚，不改变物理表或既有客户端语义。

### 6.23 `dashboard-summary-read-v1`

- `GET /api/v1/dashboard` 是登录后工作台的唯一摘要入口；只要求数据库重验后的有效 Actor，不授予任何新的业务权限。Query 精确为可选 `item_limit`，默认 5、范围 1～20；未知参数固定 422。成功返回 `{item_limit,audit_tasks,files,failed_jobs}`，每个 section 要么为 `null`，要么为对应权限允许的真实 PostgreSQL 投影。
- `audit_tasks` 仅在 Actor 当前权限包含 `audits.read` 时返回，精确为 `{open_count,pending_review_count,items}`；items 最多 `item_limit` 条，字段为 `id/task_no/name/status/current_execution_id/updated_at`，只读取同组织、未删除且非归档任务，按 `updated_at DESC,id DESC` 排序。`open_count` 只计 `status=open`；`pending_review_count` 只计当前执行处于 `pending_finance_review|pending_audit_review` 的任务。
- `files` 仅在 Actor 当前权限包含 `files.read` 时返回，精确为 `{active_processing_count,failed_processing_count,items}`；每个文件只关联 `file_scan|file_process` 中按既有优先规则选出的一个权威 Job，items 最多 `item_limit` 条并按文件 `created_at DESC,id DESC` 排序，字段只含 `file_id/original_name/status/security_scan_status/intended_business_type/job_id/job_status/created_at`。活动计数只计 Job `queued|running|cancel_requested`，失败计数只计 Job `failed` 或文件 `rejected`。
- `failed_jobs` 仅在 Actor 当前权限包含 `jobs.recover` 时返回，精确为 `{failed_count,items}`；items 最多 `item_limit` 条，只读取同组织 `status=failed` Job，按 `created_at DESC,id DESC` 排序，字段为 `id/job_type/resource_type/resource_id/status/stage/attempt_no/max_attempts/error_code/next_retry_at/created_at/row_version`。不得返回 `input_json`、input hash、错误正文、Worker/lease、对象存储位置或任何 secret。
- section 是否存在只能由 Backend 基于当前 Actor 权限决定，Frontend 不能请求扩大范围；跨组织对象永不进入 count 或 items。各 section 使用有界独立 SQL 读取，不承诺跨 section 单一 MVCC 快照；摘要只用于导航，不替代资源详情或正式验收统计。成功响应固定 `Cache-Control: private, no-store`，无副作用、不接受 `Idempotency-Key`。

## 7. 认证、授权与职责分离

- Backend 鉴权是唯一安全边界；前端 Router meta 只改善导航体验。
- 当前 accepted 数据库已具备组织、用户、固定角色、会话和临时授权的存储约束。
- 当前 Backend 已注册五个 Auth API、统一 Actor/permission 依赖、用户创建/启停/密码重置/角色替换、Break-glass、操作日志读取、单文件上传/读取，以及第 6、10、11 节已冻结的财务、供应商、知识/RAG、审核与正式报告 Router；所有写动作在 Service 与 Repository 再校验组织、权限、对象状态、row-version 和幂等。Frontend 权限 UX 仍不是安全边界，未注册的工作台/依赖健康等路径也不能由既有权限字典外推。
- Access Token、Refresh Token、一次性换密 Token 和密码不得写入日志、URL或普通持久化状态。
- Refresh Token 只保存不可逆摘要；会话撤销和用户禁用必须在后端生效。
- 临时授权必须限时、双人控制、禁止自批，并在动作发生时重新校验资格。
- 长期职责分离由后端和数据库共同强制，不能由 UI 隐藏按钮代替。
- 资源授权必须同时校验组织、角色、资源范围和对象状态。

### 7.0 `first-org-admin-bootstrap-v1`

- 首次初始化只允许受信任操作者运行一次性离线 CLI `finaudit-bootstrap-admin`；不得提供匿名 HTTP 初始化接口，也不得在镜像、迁移、仓库或日志中预置公开账号和密码。
- CLI 不接受命令行参数。企业名称、统一社会信用代码、税号、管理员 username/display_name 由显式环境变量注入；初始密码只从绝对路径 `BOOTSTRAP_ADMIN_PASSWORD_FILE` 读取，目标必须是有界、不可写、非 symlink/reparse 的常规 UTF-8 文件，并继续执行 `auth-password-v2` 门禁。输出只含固定 PASS/FAIL 与脱敏原因码，不回显配置、路径、标识符或凭据。
- CLI 在 PostgreSQL 单事务内取得固定 advisory transaction lock；仅当 organizations/users 为空且迁移已提供 enabled `system_admin` 时，创建唯一 active 企业、active 首管理员、`force_change_on_login=true` 的 Argon2id 密码事实、`assignment_source=bootstrap` 角色历史和 `system.bootstrap.completed` 操作日志。任一步失败必须整体回滚。
- 精确相同的企业和管理员 Profile 已存在且仍有未撤销的 bootstrap `system_admin` 分配时，重放只返回 `ALREADY_INITIALIZED` 且不得重置密码、角色或 row-version；其他既有、部分或冲突状态全部失败关闭。首管理员仍必须按 7.2 完成受限换密并重新登录后，才能取得普通业务会话。

### 7.1 `auth-mvp-v1` 密码与登录锁定

- `username` 只接受 ASCII lowercase，grammar 固定为 `^[a-z0-9][a-z0-9._-]{0,99}$`；服务端不做大小写折叠。
- `password` 必须先按 JSON string 严格解码，拒绝 NUL，再做 Unicode NFC；不得 trim、casefold、折叠空白或进行其他隐式转换。
- `auth-password-v2` 在所有环境统一生效：NFC 后密码长度必须为 6～128 个 code point，UTF-8 长度不超过 512 bytes；允许空格和 Unicode，不要求大写、小写、数字或符号组合；`123456`、`letmein`、`qwerty` 等版本化弱密码继续失败关闭。
- 创建用户和管理员重置密码都必须校验本地、版本化、可哈希追踪的弱密码 blocklist；blocklist 不联网获取，更新按独立版本审查，不静默改变既有 Profile。
- 密码哈希固定为 Argon2id v19：`m=65536 KiB`、`t=3`、`p=1`、16-byte 随机 salt、32-byte hash，按 PHC string 持久化。成功校验发现旧参数时可在同一受控事务按需 rehash；不得手写密码学实现。
- 对 unknown 或 deleted 用户执行同一 Argon2id dummy verify；disabled、manual locked、timed locked、unknown 和密码错误对匿名调用者均返回同一通用 401，不暴露账号是否存在。
- active 用户的连续错误计数在数据库中按用户行原子更新；第 5 次错误在同一事务写 `status=locked`、`locked_until=db_now+15 minutes`。成功登录原子清零计数；`locked_until` 到期后原子恢复 active 并清零；`locked_until IS NULL` 的 locked 用户是人工锁定，只能由授权管理动作解除。

### 7.2 Access、Refresh 与强制换密 Token

- Access Token 使用 EdDSA/Ed25519，TTL 900 秒；JOSE header 必须包含 `typ=at+jwt` 和 allowlist 中的显式 `kid`，拒绝未知 `kid`、`jku` 和 `x5u`。
- Access claims 固定为 `sub`、`sid`、`jti`、`purpose=access`、`iat`、`nbf`、`exp`、`iss=finaudit-agent`、`aud=finaudit-api`、`auth_epoch_us`；时间校验只允许正负 30 秒 skew。`auth_epoch_us` 是签发时用户 `token_invalid_before` 的 UTC epoch microseconds 投影。
- JWT key 只从环境注入或 secret mount 加载；一个 active signer 加多个 verify-only key。旧 verify key 至少保留最长已签发 JWT TTL 加 30 秒，回滚只能切换 active signer，不接受客户端提供的 key URL。
- 每次受保护请求都用 `sub/sid/auth_epoch_us` 回 PostgreSQL 校验用户、组织、TokenSession、当前有效角色与撤销/禁用/锁定状态；JWT 内不携带可作为最终授权事实的 permissions。
- Refresh Token 是 256-bit opaque secret，不是 JWT；wire format 固定为 `<session_uuid>.<base64url_32_byte_secret>`，base64url 部分无 padding。数据库只保存完整 wire token 的 SHA-256 摘要。
- 一个 `token_sessions.id` 就是一个会话族。`remember_me=false` 的绝对 TTL 为 7 天，`true` 为 30 天；服务端锁定该 TokenSession 后原子验证并旋转摘要，但保持原 `expires_at`，不得滑动延长。
- wire 中 session ID 存在但摘要不匹配时视为该族 Refresh 重放，原子撤销该 TokenSession 且不签发新 Token。Frontend 必须对刷新 single-flight；跨进程并发输家仍按重放 fail closed。
- 强制换密 Token 使用 EdDSA/Ed25519，header `typ=pwd+jwt`，claim `purpose=password:change`，TTL 300 秒，不含可作为普通会话的 `sid`。使用时必须同时校验用户仍为 `force_change_on_login=true` 且 `auth_epoch_us` 未变化。
- 完成换密必须在单一事务消费受限 Token、写新密码哈希、清除强制换密标志、推进 `token_invalid_before` 并撤销该用户全部旧 TokenSession；成功后不建立普通会话，用户必须重新登录。

### 7.3 Refresh Cookie 与五个 Auth API

- Refresh Cookie 名为 `finaudit_refresh`，固定 `HttpOnly`、`SameSite=Strict`、`Path=/api/v1/auth`、无 `Domain`；`Secure` 严格由规范化后的 `AUTH_PUBLIC_ORIGIN` scheme 决定，HTTP 为 false、HTTPS 为 true。`Max-Age` 使用当前会话剩余绝对 TTL。
- 登录、刷新、退出及任何写入或清除该 Cookie 的浏览器动作都必须验证 `Origin` 与 Backend 对外同源；production 必须显式配置无路径的 HTTPS `AUTH_PUBLIC_ORIGIN`，不信任 `Forwarded` 或 `X-Forwarded-*`。local/test 未配置时才使用 ASGI 直连 origin。不接受 Cookie 且缺少 Origin 的浏览器式请求。无 Origin 的非浏览器测试只允许走显式 test transport，必须无 Cookie，不能形成 production HTTP 旁路。
- `POST /api/v1/auth/login` 的 JSON body 固定为 `username`、`password`、`remember_me`。成功返回 200 `SuccessResponse[SessionDTO]` 并写 Refresh Cookie；命中强制换密返回 403 `AUTH_PASSWORD_CHANGE_REQUIRED`，安全 `data` 仅含 `password_change_token` 与 `expires_in=300`，不创建 TokenSession。
- `POST /api/v1/auth/refresh` 从 Refresh Cookie 读取 credential；成功返回 200 `SuccessResponse[SessionDTO]` 并旋转 Cookie。
- `POST /api/v1/auth/logout` 幂等返回 204，撤销可识别会话并按固定属性清除 Cookie；无会话也不得暴露差异。
- `GET /api/v1/auth/me` 返回 200 `SuccessResponse[CurrentUser]`。
- `POST /api/v1/auth/password/change` 的 JSON body 只含 `new_password`，`Authorization: Bearer <pwd token>`；成功返回 204、撤销旧会话并清除同路径 Refresh Cookie。
- `SessionDTO = {access_token, token_type: "Bearer", expires_in: 900, user}`，其中 `user` 使用同一 `CurrentUser` 投影；`CurrentUser = {id, display_name, roles[], permissions[]}`，两个数组都只含有效 code 并稳定去重排序。`permissions[]` 只返回 `PRODUCT_REQUIREMENTS.md` 的 `p0-permissions-v1` deny-overrides 后 code；对象级授权仍按每次请求的组织、资源范围和状态计算。
- 任何响应 body 或安全错误 `data` 只要携带 Access Token 或强制换密 Token，都必须同时返回 `Cache-Control: no-store` 与 `Pragma: no-cache`，且不得返回可复用的 `ETag` 或 `Last-Modified`。

### 7.4 `p0-permissions-v1` 强制顺序

- 唯一 26-code 字典、五固定角色直接映射和业务范围以 `PRODUCT_REQUIREMENTS.md` 3.1.1 为语义 SSOT；Backend 使用精确 code，不支持通配符、继承别名或客户端自报权限。
- 授权顺序固定为：加载同组织 active 用户 → 加载当前有效固定/临时角色 → 取直接映射并集 → 应用 deny-overrides → 校验 permission code → 校验组织、资源类型/范围、对象状态 → 校验同人职责分离。
- 有效角色含 `system_admin` 时先把候选集合收敛为其七项技术权限；随后若含 `read_only`，只保留候选集合中属于 `operations.read/files.read/financial.read/knowledge.use/audits.read/reports.read` 的读取 code。`read_only` 自身只直接授予 `audits.read/reports.read`；Break-glass 不得绕过任一 deny。
- 同一 actor 不得提交并批准同一制度或评测对象；执行财务初审的 actor 不得以审计角色复核同一 high 风险。技术管理员不能修改业务事实、执行业务审批或复核，财务不能最终处理 high 风险，合同管理员不能确认主合同，只读不能导出。
- 决策兼容现有 008 storage schema：Refresh 旋转复用同一 TokenSession 行，当前不要求迁移。若实现发现必须改变公开 DTO、Cookie、持久化语义或 deny 集，必须先更新本节与产品 SSOT；回滚只能回滚未发布实现，不能静默退回 Mock、宽松密码学或旧权限示例。

### 7.5 `user-list-read-v1`

- `GET /api/v1/users` 提供用户管理页的最小真实只读入口。请求必须先得到数据库重验后的 Actor，再要求 `users.manage`；Repository 只能读取 `Actor.organization_id + deleted_at IS NULL` 范围，并同时要求所属组织未软删除且处于 `active`。其他组织的用户不得进入结果，也不得通过总数或错误差异泄露。
- Query 只允许可选 `cursor` 与 `page_size`：`page_size` 默认 20、范围 1～100；其他参数固定 422。排序固定为 `username ASC, id ASC`，其中 `username` 使用 PostgreSQL `CITEXT` 的数据库比较语义；Repository 使用 keyset 条件读取 `page_size + 1` 条，不执行 OFFSET 或 total count。现版本不支持关键字、状态、角色或客户端排序筛选。
- `cursor` 是长度不超过 256 的无 padding canonical base64url UTF-8 JSON，解码后精确为 `{v:1, username:<当前用户名>, id:<canonical-lowercase-UUID>}`；非法编码、非 canonical 表示、未知键、非法用户名或字段类型固定 422。后继条件为更大的用户名，或同用户名下更大的 UUID。Cursor 不包含凭据、不授予权限且不替代 Actor 组织边界，但其内容可逆并携带用户名；原始 query/cursor 不得写入应用日志、错误详情、Trace 展示或长期遥测。
- 成功返回 `SuccessResponse[UserListData]`，其中 `data` 精确为 `{items, page_size, next_cursor}`；只有读取到额外一条时才基于本页最后一项生成 `next_cursor`，因此 `next_cursor` 非空时 `items` 必须恰有 `page_size` 项，末页为 `null`。列表项精确为 `id`、`username`、`display_name`、`status`、`fixed_roles`、`row_version`；`username` 沿用第 7.3 节登录合同的 1～100 字符小写 ASCII 格式，`display_name` 为字符串，`status` 精确为 `active|disabled|locked`。`fixed_roles` 只包含数据库当前时刻已经生效、尚未撤销且角色仍启用的 `bootstrap|user` 长期分配，不含 break-glass，并按五个 `RoleCode` code 的 ASCII 升序稳定去重；`row_version` 使用正整数十进制字符串以保持 PostgreSQL BIGINT 精度。
- 当前 Repository 在一个普通 Session 中依次读取有界用户页、数据库时钟和该页固定角色；PostgreSQL 默认 `READ COMMITTED` 下各语句不构成同一 MVCC 快照。`row_version` 只投影用户行版本，不证明 `fixed_roles` 与用户页属于同一快照；需要跨行原子目录快照时必须另行冻结事务隔离或单语句投影合同。
- 响应不得返回 `organization_id`、email、密码哈希、登录失败次数、`locked_until`、强制换密标记、Token/session、break-glass、分配原因、Actor、时间戳、软删除事实或任何有效权限推导；成功响应固定 `Cache-Control: private, no-store`。本接口只读且无副作用，不接受 `Idempotency-Key` 或 `row_version` 请求；用户写入使用第 7.6 节合同，break-glass 写入仍须先冻结独立 HTTP 合同，Frontend 在对应链路完成前保持不可用。

### 7.6 `user-management-write-v1`

- P0 用户写接口固定为：`POST /api/v1/users` 创建，`PATCH /api/v1/users/{user_id}/status` 启用或停用，`POST /api/v1/users/{user_id}/password/reset` 管理员重置密码，`PUT /api/v1/users/{user_id}/roles` 原子替换长期固定角色。四个接口都必须先得到数据库重验后的 Actor、要求 `users.manage`，并且只允许 Actor 当前 active 组织内未软删除的目标；跨组织、不存在或软删除统一返回 404 `RESOURCE_NOT_FOUND`。`user_id` 只接受 canonical lowercase UUID，未知 body/query 字段固定 422。
- 创建 body 精确为 `{username, display_name, initial_password, fixed_roles}`：username 沿用 7.3 的小写 ASCII 格式，display_name 为 1～100 字符且首尾不得是空白，initial_password 沿用 `auth-mvp-v1` 新密码门禁，fixed_roles 为 1～5 个已启用固定 RoleCode 的 ASCII 升序无重复数组。成功 201。新用户固定为 active、`force_change_on_login=true`，密码只保存 Argon2id PHC，长期角色来源为 `user`；响应不得回显密码。
- 状态 body 精确为 `{status: active|disabled, row_version}`；密码重置 body 精确为 `{new_password, row_version}`；角色替换 body 精确为 `{fixed_roles, row_version}`。`row_version` 是正整数十进制字符串并对 users 行执行 CAS；成功均返回 200，重复提交相同业务状态但使用新 Key 固定为 409 `USER_STATE_UNCHANGED`，版本不匹配固定为 409 `ROW_VERSION_CONFLICT`。停用必须同时推进 `token_invalid_before` 并撤销全部未撤销会话；重新启用清除登录锁与失败次数。密码重置必须执行新密码门禁、只保存哈希、设置 `force_change_on_login=true`、推进 token epoch、撤销旧会话并清除已到期或当前锁定状态，但不得隐式启用已 disabled 用户。
- 角色替换只处理 `bootstrap|user` 长期分配，不修改 break-glass 历史；删除语义是以同一数据库时间撤销旧分配，新增语义是创建 `assignment_source=user` 的新历史，且必须推进 users `row_version`。`system_admin` 不得与 `finance_reviewer|audit_reviewer` 形成长期组合，固定返回 409 `ROLE_SEPARATION_CONFLICT`。停用最后一个 active 长期 system admin，或从该用户移除最后一个 active 长期 system admin，固定返回 409 `LAST_SYSTEM_ADMIN_REQUIRED`。所有用户管理写按组织级事务锁串行，避免并发绕过最后管理员和长期角色职责分离。
- 四个接口都要求 `Idempotency-Key`：8～128 个可打印 ASCII `A-Z/a-z/0-9/._~-`，同一 organization + actor 的 Key 在所有用户写路径共享命名空间，保留 24 小时。服务在业务写前取得组织级事务锁及 Key 事务锁；相同 method/path/规范请求摘要重放已提交 `data`，返回相同业务状态码并设置 `Idempotency-Replayed: true`，首次为 `false`；同 Key 不同 method/path/body 固定 409 `IDEMPOTENCY_KEY_REUSED`。幂等记录、用户/角色/会话写和必要 operation-log 必须同一 PostgreSQL 事务提交；密码明文及请求正文不得写入幂等响应、日志或 operation-log。
- 四个成功响应的 `data` 都严格复用第 7.5 节 `UserListItemData` 六字段，固定 `Cache-Control: private, no-store`。数据库 username 唯一冲突为 409 `USERNAME_CONFLICT`；无效或停用角色为 409 `ROLE_SET_UNAVAILABLE`。所有成功操作分别写 `users.created|users.status_changed|users.password_reset|users.roles_replaced`，只记录目标 UUID、前后状态/角色和结果 row_version；操作日志插入失败时业务事务必须回滚。

### 7.7 `break-glass-write-v1`

- 临时角色公开写接口固定为：`POST /api/v1/break-glass-requests` 创建申请，要求 `temporary_roles.request`；`POST /api/v1/break-glass-requests/{request_id}/decision` 批准或驳回，及 `POST /api/v1/break-glass-requests/{request_id}/revoke` 提前撤销，均要求 `temporary_roles.decide`。所有接口只允许 Actor 当前 active 组织，路径 UUID 必须 canonical lowercase，未知 query/body 字段固定 422，并沿用第 7.6 节同一调用者级 24 小时 `Idempotency-Key` 命名空间、摘要重放、冲突和 `Idempotency-Replayed` 头。
- 创建 body 精确为 `{target_user_id, target_role_code, requested_duration_seconds, reason}`：目标必须是同组织 active 用户；目标角色只允许 `system_admin|finance_reviewer|audit_reviewer|contract_admin` 且当前启用；时长 1～14400 秒；reason 是去除首尾空白后 1～500 字符的业务事实。申请者必须持有 active 长期 system_admin，且目标在申请时不得已经有效持有同角色。成功 201，状态固定 pending、row_version=1，不允许预约或预批准。
- 决策 body 精确为 `{decision: approved|rejected, reason, row_version}`，撤销 body 精确为 `{reason, row_version}`；reason 同样为 1～500 字符业务事实，操作日志不得复制。决策者必须是另一名 active 长期 system_admin，不得是申请者或目标。批准时必须重新校验申请者、目标、角色及目标未持有同角色；在同一事务内把申请推进为 approved，并创建唯一 `assignment_source=break_glass` 的 `user_roles` 行，生效时刻由数据库决定，到期时刻严格等于生效时刻加申请秒数。驳回不得创建角色。撤销仅允许未到期 approved，必须在同一事务推进请求和对应角色撤销事实；不允许延期、续期、重复决定、重复撤销或覆盖历史。
- `row_version` 必须匹配锁定后的请求行，否则 409 `ROW_VERSION_CONFLICT`；状态不允许为 409 `BREAK_GLASS_STATE_CONFLICT`，资格或双人控制不满足为 409 `BREAK_GLASS_NOT_ELIGIBLE`，目标/申请不可见统一 404 `RESOURCE_NOT_FOUND`。数据库约束仍是最后防线，约束拒绝必须回滚全部申请、角色、幂等和日志写入。
- 成功 `data` 精确为 `{id,target_user_id,target_role_code,requested_duration_seconds,status,effective_from,expires_at,row_version}`；时间为 UTC ISO-8601 或 null，不返回组织、申请/决定/撤销 actor、任何 reason、trace 或用户详情。三类动作分别写 `break_glass.requested|approved|rejected|revoked`，日志只保存目标 role、结果 status、row_version 及创建时长；响应固定 `Cache-Control: private, no-store`。

## 8. 异步 Job 可观察契约

### 8.1 权威状态

- PostgreSQL 的 `async_jobs` 是 Job 身份、输入版本、状态、尝试、Lease 和结果的权威来源。
- Job 状态闭集为 `queued`、`running`、`cancel_requested`、`succeeded`、`failed`、`cancelled`。
- `async_job_steps` 保存每次 attempt 的追加式绝对步骤历史。
- Step 从 `running` 进入 `succeeded`、`failed`、`cancelled` 或 `skipped` 后不可改写。
- 同一 Job attempt 最多存在一个 running Step。
- `outbox_events` 保存可靠投递状态和不可重复事件身份。
- Outbox 状态按 `pending`、`processing`、`failed`、`published`、`dead_letter` 的受控边推进。

### 8.2 创建、执行与恢复

- 创建 Job、写业务对象和写 Outbox 必须在同一事务完成。
- Broker 消息只携带 `job_id` 与消息 Schema 版本。
- Worker 收到消息后从 PostgreSQL重读权威输入、状态和处理配置。
- Broker 重复投递不得产生重复业务结果。
- Worker claim、heartbeat、阶段完成和终态提交必须受 Lease 与数据库时间保护。
- Job 和当前 Step 的状态推进必须保持事务一致。
- 失败只使用受控错误码；第三方自由文本必须脱敏或丢弃。
- 重试沿用原 Job 并保留历史 attempt；具体 HTTP fencing 合同仍受第 15 节约束。
- 取消请求只在安全检查点终结，不删除已产生的可追溯结果。

### 8.3 当前实现边界

- accepted Alembic/ORM 已实现 Job、Step、Outbox 的存储约束；`JobRuntimeRepository`、Dispatcher、租约续期、恢复扫描和失败回写使用 CAS/fencing 保护权威事实。
- Worker 启动入口、七队列隔离和 `job_id + event_schema_version=1` 消息 Schema 已接真实 Celery task。Dispatcher 从 PostgreSQL Outbox 认领后向 Redis Broker 发布；未注册 task 或未安装 Handler 失败关闭。
- `handler_registry.py` 继续提供严格、无远程 retrieval 的通用 meta Loader；文件、发票提取、知识索引/评测、审核和报告各有版本化 Registry/Input/Summary bundle 与静态 callable 映射，Job 在创建和执行时都重验版本与哈希。
- 文件 scan/parse、发票提取、知识 index/eval、审核和报告 Executor 均写入现有 Job/Step/Outbox 闭环；Dispatcher、Handler、Broker 和恢复路径已有单元/数据库证据，显式 loopback Redis/Celery transport Gate 已通过且测试容器残留为 0。
- 以上通用证据不自动证明 production Broker、强杀/断电、容量、监控或完整 Compose；显式 local Compose 门禁已分别验证 `file_process` 在 scan 中 SIGKILL、同容器受管重启、attempt-2 `scan → parse → markdown` 恢复及下游合同提取，以及 `contract_extract`、`invoice_extract` 本体在 attempt 1 `extract` 中 SIGKILL、零业务事实回滚、`LEASE_EXPIRED` 和 Maintenance attempt 2 唯一事实收敛。发票门禁还核对 13 个字段证据、1 条明细证据、原件 SHA-256/ETag 与唯一发票/明细/绑定/日志；`audit_execute` 门禁在 attempt 1 `evaluate` 中强杀 Worker，精确终止唯一孤儿等待后端并核对零规则/风险/执行日志回滚，再由 attempt 2 收敛为 15 条规则、2 条风险和唯一日志。`report_generate` 门禁在 PDF/XLSX 已写 MinIO、数据库制品事实未提交时强杀并核对孤儿对象保留、attempt-2 相同字节和唯一 ready 报告；`knowledge_index_build` 门禁在 Qdrant 点与 PostgreSQL 成员 Hash 已提交、ready 事务未提交时强杀并核对相同 Point ID 幂等重放、跨恢复不变摘要和唯一 ready 索引。production、Docker 自动重启与主机断电仍须独立运行。

## 9. 数据库与存储契约

### 9.1 当前物理数据库

- 当前 accepted Alembic head 为 `20260817_024`，ORM 与运行时 catalog 覆盖 57/57 张核心物理表。
- `20260815_021` 不新增表；它在升级时检查既有活动索引、已批准评测集和已结束评测运行的完整性，并用 PostgreSQL `BEFORE INSERT` 触发器强制索引、评测集和评测运行分别从 `building`、`draft`、`running` 创建，防止绕过正式评测与发布状态机。
- `20260816_022` 允许未确认发票的 currency 为空、移除无证据 CNY 默认，并由数据库继续强制 confirmed 发票 currency 非空。
- `20260816_023` 为风险解释和报告草稿增加 `disabled|succeeded|degraded`、严格 JSON 与 SHA-256 事实，并只放行受控 AI 采用转换；既有报告状态机与 ready 制品不可变规则保持有效。
- `20260817_024` 保留 Event v1 与非空 legacy USD 历史，增加 Event v2 的 USD/CNY 通用 microunit 费用列和版本/货币一致性约束；pending 审计事实阻断升级，任何 v2 事实阻断 downgrade，禁止隐式 FX。
- accepted 线性迁移是当前物理 Schema 的唯一来源。
- 当前 head 覆盖扩展、身份、幂等、财务主数据与关系、可靠性、特权授权、追加式操作日志、文件/文档处理、Markdown/分块、知识检索/评测、审核执行和正式报告。
- 旧数据库设计与历史迁移候选仍不参与解释当前 Schema；物理事实只来自 accepted 线性 head 和 PostgreSQL catalog 验证。
- ORM 必须精确映射当前 accepted head；发现漂移时先修正迁移或模型，不在 Service 绕过。

### 9.2 迁移规则

- 所有 Schema 变化通过新的线性 Alembic revision 完成。
- Migration 只从进程环境读取 `DATABASE_URL`，并使用与应用一致的安全解析器。
- PostgreSQL 会话统一使用 UTC 和 UTF-8。
- 迁移不得打开或打印本地 `.env`、连接串或凭据。
- 升级和降级必须保持事务原子性；安全失败优先于部分修改。
- 删除表、列或约束前必须证明兼容窗口、数据保留和回滚路径。
- 数据库验证使用隔离的 PostgreSQL 测试库，禁止回退到开发或生产数据。

### 9.3 数据所有权

- PostgreSQL 保存组织、身份、业务对象、版本、状态、关系、审计和任务事实。
- MinIO 保存隔离的原件、隔离区、资产、预览、报告、导出和临时制品。
- Qdrant 保存可重建的向量与最小过滤元数据。
- Redis 保存队列和可恢复运行状态，不作为完成事实。
- JSONB 只用于快照、配置和低频结构，不替代核心关联、唯一性或权限字段。

### 9.4 `operation-log-v1`

- P0 使用一张不分区的 PostgreSQL `operation_logs` 追加写表；当前保留周期仍为环境 TBD，因此不得实现自动清理、按月分区或归档删除。该最小选择避免在容量数据不存在时预建分区体系；以后改变保留或分区策略必须使用新迁移并保留现有记录身份。
- 每条记录固定包含数据库生成的 UUID、可空组织、`anonymous|user|system` actor kind、可空 actor UUID、版本化 action code、`succeeded|denied|failed` outcome、可空资源类型/UUID、Trace UUID、有界脱敏 `change_summary_json` 和数据库时间。`user` actor 必须同时存在组织和 actor UUID；`anonymous/system` 不得伪造 actor UUID。未知用户名、密码错误和其他匿名认证失败只使用 `anonymous`，不得保存用户名、密码、Token、Cookie、Header、IP 原文或请求正文。
- 当前 action 字典已覆盖认证、身份、Break-glass、文件、补充协议、合同发票、发票、供应商、制度/知识、审核和报告运行时所需动作。`backend/app/models/operations.py::OPERATION_LOG_ACTION_CODES` 是字典 SSOT，`OperationLogRepository` 对每个动作实施精确脱敏摘要白名单；不得为未实现模块预建 action。
- `change_summary_json` 只能包含 action 注册表为该 action 明确允许的非敏感键，序列化后最多 16 KiB；不得保存认证 credential、完整业务正文、原文件名、税号、自由文本原因或第三方异常。reason 等业务事实保存在其权威业务表，操作日志只保存动作身份、状态变化和必要版本摘要。
- 数据库触发器从插入起禁止 `UPDATE`、`DELETE` 与 `TRUNCATE`；非空表 downgrade 必须失败关闭。P0 不增加伪造的周期封账或哈希链：当前封账语义就是数据库追加写约束、最小权限和不可原地修改，备份/WORM/长期保留仍由后续环境 Profile 验证。
- 必须在同一业务事务内写必要操作日志；日志插入失败时对应敏感业务写不得提交。读取由 `operations.read` 保护，按组织与无组织匿名记录裁剪，并使用稳定 keyset；读取 API 在用户管理写链完成前另行冻结，不由本存储切片猜测。

### 9.5 `operation-log-read-v1`

- `GET /api/v1/operation-logs` 是追加式操作日志的最小读取入口；请求必须先得到数据库重验后的 Actor，再要求 `operations.read`。当前产品为单组织：Repository 只允许 `organization_id = Actor.organization_id` 的记录，以及 actor_kind=anonymous 且 organization_id 为 null 的全局匿名认证记录；其他组织和 system 无组织记录不得返回。接口不解析、关联或返回用户名、显示名、IP、Header、请求正文、密码、Token、Cookie或业务 reason。
- Query 只允许可选 `cursor` 与 `page_size`，默认 20、范围 1～100，未知参数固定 422。排序固定为 `created_at DESC, id DESC`，keyset 后继为更早 created_at 或同一时间更小 UUID；Repository 使用 `LIMIT page_size + 1`，不执行 OFFSET 或 total count。Cursor 是长度不超过 256 的 canonical 无 padding base64url UTF-8 JSON，精确为 `{v:1,created_at:<UTC ISO-8601>,id:<canonical UUID>}`，非法编码、重复/未知键、非 UTC/非 canonical 时间或 UUID 固定 422。
- 成功 `data` 精确为 `{items,page_size,next_cursor}`；item 精确为 `{id,actor_kind,actor_id,action_code,outcome,resource_type,resource_id,trace_id,change_summary,created_at}`。`change_summary` 只来自第 9.4 节注册表写入的脱敏对象；anonymous item 的 actor_id 必须为 null，user item 必须非 null。响应固定 `Cache-Control: private, no-store`，本接口只读、不接受 Idempotency-Key，不提供删除、导出、任意筛选或全文搜索。

## 10. 文件与文档处理

### 10.1 上传安全边界

- 上传输入是不可信数据。
- 当前纯服务合同支持 PDF、DOCX、PNG 和 JPEG 的扩展名、声明 MIME 与文件头联合校验。
- DOCX 必须通过有界 ZIP 目录、核心部件和 XML 结构校验，拒绝加密或异常压缩内容。
- 上传流单次遍历计算字节大小和 SHA-256 内容摘要；空文件和超限文件失败关闭。
- 批量数量上限从 `Settings` 注入，不在 Service 固化环境默认值。
- 只有经过 Pydantic 校验得到的 `clean` 扫描状态可以进入解析。
- 原文件、解析、Markdown、分块和索引各自版本化；活动版本切换不得覆盖历史。
- 外部文档文本、Markdown、表格和模型输出都不得成为指令来源。
- 当前已实现单文件与批量 Router、quarantine 写入、PostgreSQL 去重/幂等事务、文件/Job/Step/Outbox/操作日志持久化、真实 Celery/Redis 投递与恢复、Scanner、基础 PDF/DOCX/OCR 解析及 originals 固化。默认离线门禁不运行这些外部依赖；显式真实 MinIO、Redis/Celery、PostgreSQL 和浏览器证据必须分别表述。`local-performance-baseline-v2` 已在真实 local 链路验证默认最大 20 件批量受理、同键重放、207 部分失败、第 21 件 413，以及每个 run 精确 61 组文件/Job/attempt-1 scan step/published Outbox 与超限零副作用；该小型合成结果不是正式参考环境完整容量。local `file_process` 另有 scan 中 SIGKILL、同容器受管重启、attempt-2 parse/markdown 和下游合同提取证据；`contract_extract`、`invoice_extract`、`audit_execute`、`report_generate` 与 `knowledge_index_build` 本体也分别通过 attempt-1 强杀、恢复前事务或跨系统边界核验、attempt-2 成功与唯一事实收敛。production Scanner、Docker 自动重启、主机断电和正式 AC 仍无证据。

### 10.2 `archived-reupload=conflict-v1`

- 去重身份固定为同一 `organization_id` 下相同的文件内容 SHA-256 与精确 `size_bytes`；archived 且未软删除的文件继续参与该去重判断，跨组织结果不得泄露或复用。
- 单文件上传命中该身份且既有文件为 archived 时，固定返回 HTTP 409 `FILE_ARCHIVED_DUPLICATE`，响应只使用统一脱敏错误包络和 `trace_id`，不得回显旧文件 ID、分类、知识库或对象元数据。
- 该分支不得返回 `reused=true`，不得恢复或修改 archived 行，不得创建第二个文件事实、Job、业务对象、Outbox 业务事件、quarantine/originals 对象或其他 MinIO 副本，也不得执行自动处理意图提升。
- 批量上传中的同类项目同样必须保留 `code=FILE_ARCHIVED_DUPLICATE` 与项目级 `http_status=409` 且零业务/存储副作用；批量接口的整体 HTTP 包络仍由其最小 Router 合同冻结，不属于 MVP-VS-07。
- 归档恢复不是上传的隐式分支；未来如需恢复，必须另行冻结权限、状态迁移、引用影响、幂等和审计合同。

### 10.3 `file-upload-intake-v1`

- `POST /api/v1/files` 是 P0 单文件受理入口，要求数据库重验 Actor、`files.upload`、业务类型角色范围和 8～128 字符 canonical `Idempotency-Key`。请求固定为 `multipart/form-data`，精确包含一个 `file`、`intended_business_type=contract|supplementary_agreement|invoice|policy`、`auto_process_requested=true|false`，仅 policy 额外且必须包含 canonical `target_knowledge_base_id`；重复、未知或缺失 part 固定 422。文件名拒绝路径分隔符、控制字符、空值和超过 500 字符，不把客户端路径静默转换为文件名。
- API 在进入数据库前完成单文件上限、空内容、扩展名、声明 MIME、Magic Bytes/DOCX 有界结构和 SHA-256 校验。合法内容写入 MinIO quarantine；对象键只由服务端组织 UUID 与文件 UUID 生成，不使用原文件名。MinIO 明确失败或结果未知分别返回 503 `FILE_STORAGE_UNAVAILABLE` / `FILE_STORAGE_OUTCOME_UNKNOWN`，不得返回 202；数据库提交失败会尝试精确补偿删除，补偿失败使用 503 `FILE_STORAGE_CLEANUP_REQUIRED`，只向内部错误对象保留定位信息。
- 去重身份固定为同组织 SHA-256+字节大小，并在 PostgreSQL 事务级 advisory lock 与条件唯一索引双重裁决。命中未归档、未拒绝且分类、目标知识库一致的文件时返回 `reused=true`，不写第二份文件或 MinIO 对象；分类或目标不一致返回 409 `FILE_CLASSIFICATION_CONFLICT`，archived/rejected 分别返回 409 `FILE_ARCHIVED_DUPLICATE` / `FILE_REJECTED_DUPLICATE`。跨组织永不复用或泄露。
- 每个新文件在同一 PostgreSQL 事务写 `files`、`async_jobs`、`outbox_events`、幂等结果和脱敏操作日志。`auto_process_requested=true` 创建 `file_process/full` Job，false 创建 `file_scan/scan_only` Job；两者首个步骤均为强制 `scan`，queued Job 的权威 `stage` 按第 8 节保持 null，响应另以 `next_stage='scan'` 表示计划步骤。关闭自动处理从不跳过扫描，也不创建解析、Markdown、分块、索引或业务对象。
- 相同幂等键在同组织+Actor 的 24 小时命名空间内跨路径唯一：同请求返回首次完整 202 数据且不新增日志、对象、Job 或 Outbox；不同 method/path/hash 返回 409 `IDEMPOTENCY_KEY_REUSED`。请求 hash 只包含规范化意图、消毒后的文件名、MIME、字节大小和 SHA-256，不保存上传正文。
- policy 目标知识库必须同组织、active 且未软删除；不存在、跨组织或不可见统一 404 `RESOURCE_NOT_FOUND`，已归档返回 409 `KNOWLEDGE_BASE_NOT_ACTIVE`。其他类型必须不带目标知识库。
- 成功 HTTP 202 的 `data` 精确为 `{file_id,original_name,status,security_scan_status,reused,intended_business_type,target_knowledge_base_id,auto_process_requested,job_id,job_status,job_scope,next_stage,row_version}`；新文件为 `uploaded/pending`、Job 为 `queued`，所有 bigint 版本使用正整数字符串。响应固定 `Cache-Control: private, no-store` 与 `Idempotency-Replayed`。

### 10.4 `file-read-v1`

- `GET /api/v1/files` 与 `GET /api/v1/files/{file_id}` 要求 `files.read`，只返回 Actor 同组织且未软删除的文件。列表只接受 `cursor/page_size`，按 `created_at DESC,id DESC` 做 canonical opaque keyset，不提供 total；详情对跨组织与不存在统一 404。
- 列表 item 与详情精确返回上传响应中的文件字段，并增加 `size_bytes,created_at,job_id,job_status,job_scope,next_stage`；`size_bytes` 与 `row_version` 都使用字符串。关联 Job 固定选择 full 优先、否则 scan-only，不能用 Broker 状态覆盖 PostgreSQL Job 事实。列表和详情固定 `private, no-store`。

### 10.4.1 `file-batch-upload-v1`

- `POST /api/v1/files/batch` 要求 `files.upload` 与 canonical `Idempotency-Key`，使用严格 `multipart/form-data`：同一批次包含 1～`Settings.max_batch_file_count` 个重复 `files` part，并共享一个 `intended_business_type`、一个 `auto_process_requested`，仅 policy 批次额外且必须包含一个 `target_knowledge_base_id`；未知 part、重复元数据 part、空批次和混合业务意图固定失败关闭。
- 批次仅编排既有 `file-upload-intake-v1`，每个文件使用由批次键和零基索引确定性派生的子幂等键，并分别进入独立存储与 PostgreSQL 事务；一个项目的合法拒绝不得回滚或伪造其他项目结果。批次重放保持项目顺序、文件身份与单项结果稳定；同一批次键换序或换内容时，对受影响项目返回 `IDEMPOTENCY_KEY_REUSED`。
- 整体固定返回 HTTP 207 与 `SuccessResponse[FileBatchUploadData]`。`data` 精确为 `{items,accepted_count,rejected_count}`；每项精确为 `{index,original_name,outcome,http_status,replayed,data,error}`，其中 accepted 项只含现有 `FileUploadData`，rejected 项只含脱敏 `{code,message}`。不得在项目错误中返回对象键、摘要、文件内容、异常原文或跨组织事实。

### 10.4.2 `file-preview-v1`

- `GET /api/v1/files/{file_id}/preview` 要求 `files.read`，只读取 Actor 同组织、`stored|archived + clean` 且 originals locator 完整的文件。API 存储身份只获得 originals 的受限 `GetObject`；Adapter 只接受数据库提供的固定 originals locator，并在返回前按权威字节数与 SHA-256 完整复验，不列举、不签名、不接受用户路径。
- 读取完成后在同一组织事务中重新锁定文件并核对状态、locator、大小和摘要；任一事实变化返回 409，存储或完整性失败返回脱敏 503。成功使用权威 MIME、`private, no-store`、`nosniff`、SHA-256 ETag 与安全 `Content-Disposition: inline`，不得泄露 MinIO bucket/object key；成功预览追加脱敏操作日志。
- `GET /api/v1/files/{file_id}/text-preview` 同样要求 `files.read`，只返回该文件当前 active Markdown 的有界只读文本，不渲染或执行 raw HTML、URL、脚本或模型指令。响应精确为 `{file_id,markdown_version_id,content_sha256,markdown_text,char_count,truncated}`；查询 `max_chars` 只能为 1000～200000，缺少 active Markdown 返回 409 `FILE_TEXT_PREVIEW_NOT_READY`。

### 10.4.3 `file-management-v1`

- `POST /api/v1/files/{file_id}/archive` 要求 `files.manage`、canonical `Idempotency-Key` 与 JSON `{row_version,reason}`。只允许同组织 `stored+clean` 文件按乐观版本转为 `archived`，保留 originals、解析、业务对象和历史引用，写入 `archived_at/updated_by/row_version` 与操作日志；归档不可逆，重复上传继续遵循 `FILE_ARCHIVED_DUPLICATE`。
- `POST /api/v1/files/{file_id}/retry` 要求 `files.manage`、canonical `Idempotency-Key` 与 JSON `{row_version,job_id,reason}`。只允许该文件当前权威 `file_scan|file_process` Job 在 `failed`、未耗尽尝试且失败阶段属于当前 Handler retry scope 时由用户显式立即重排队；复用原 Job，清除脱敏运行失败状态并追加下一 attempt 的唯一 Outbox，不创建第二个文件、Job、解析事实或业务对象。合同/发票提取及其他 Job 的技术恢复不由该端点越权处理。
- 两个写动作均对不存在与跨组织统一 404，对旧版本、旧 Job、非法状态、不可重试或幂等冲突返回稳定 409；成功返回更新后的 `FileListItemData`，固定 `private, no-store` 与 `Idempotency-Replayed`，并在权威事务内追加脱敏操作日志。

### 10.5 `file-schema-v1`

- `knowledge_bases` 首次落表包含组织、code/name/description、`active|archived`、固定 Top-5/NULL 阈值和完整 M1 列；同组织 active 且未软删除 code 条件唯一，P0 归档不可逆。`files` 包含不可变上传身份、不可变 quarantine 定位、clean 后一次写入且不可改写的 originals 定位、双状态、分类/目标、自动处理意图、扫描/拒绝事实、归档时间和完整 M1 列。`uploaded/validating/rejected` 的 originals 定位必须为空，`stored/archived` 必须非空；扫描只读 quarantine，解析、预览与下载只读 originals。
- 文件双状态初始为 `uploaded+pending`；Worker claim 后为 `validating+pending`；clean 后为 `stored+clean`；infected/unsupported 为 `rejected`；scan_failed/not_configured 保持 validating 并禁止解析；只有 `stored+clean` 可转 archived。数据库 CHECK/trigger 拒绝混合状态、身份漂移、true→false 意图回退、软删除、DELETE/TRUNCATE 和跨组织/非活动 policy 目标。
- 同一文件终身最多一个 `file_scan` 和一个 `file_process` Job；技术重试复用原 Job。文件 Job 必须同组织、`resource_type=file`、resource UUID 与 input 中 file UUID 相同。非空文件或历史 file Job 存在时，迁移 downgrade 以 SQLSTATE 55000 原子失败。

### 10.6 `markdown-chunk-profile-v1`

- `document_blocks.block_type` 的可查询与可转换闭集包含 `quote`。`bbox_json` 与 `bbox_unavailable_reason` 满足异或：坐标存在时 reason 为 null；坐标为空时 reason 精确为 `source_not_paginated|extractor_not_available`。未知原因或两者同时为空/非空失败关闭。
- Markdown 由活动解析版本的结构块确定性生成，Profile 为 CommonMark core 加 GFM pipe table；raw HTML 禁用。只读渲染必须使用文本/AST 输出编码，禁止脚本、事件属性、data URI、外部资源自动加载和不可信 URL 执行。
- 简单表格写为 pipe table。超出边界或含复杂合并单元格的表格写入 `table_asset_v1` JSON 制品；PostgreSQL 保存 opaque asset UUID、来源块、版本、摘要、对象身份和状态，Markdown AST 只引用 UUID，不保存或返回 MinIO 对象键。
- Markdown、source map、质量结果与 ChunkSet 都是不可变版本。只有解析率、来源映射率和有效内容覆盖率均达到产品阈值的候选版本可原子切为 active；失败保留旧 active。
- P0 分块只使用应用内 `chunk-profile-v1`。ChunkSet 固化 profile version/hash 和实际参数；不提供在线编辑、A/B、语义分块或自动多业务文档拆分。
- 每个 Chunk 必须非空、有界，并可经 Markdown source map 追溯到一个或多个真实 document block；分块只读取同文件当前 active 且质量通过的 Markdown。

## 11. 检索、引用与审核

- PostgreSQL 保存知识库成员、制度状态、有效期、活动索引和权限事实。
- Qdrant 只做候选召回；命中必须回到 PostgreSQL 复核权限、状态、有效期、成员和内容摘要。
- 当前 Qdrant 1.10 Adapter 不枚举或自动创建 Collection，使用配置显式注入的环境+Adapter+模型+维度身份，校验健康、维度和 distance，并提供 waited upsert/delete 与 `has_id` must-filter 查询。知识运行时已实现 PostgreSQL 成员/活动版本、索引构建/激活/重建、5 条 smoke 评测、PG 终审、RAG 引用白名单/拒答和反馈 API；calls-disabled 使用确定性 Hash，`minimax-m3-bailian-qwen37-local-v2` 启用时由 Backend/Worker 通过 Gateway 使用 1024 维百炼 `qwen3.7-text-embedding`，旧 Hash 索引因身份不匹配不能查询或原地覆盖。真实 Embedding 先以 Event v2/CNY durable reserve，completion 与 Query、索引批次或评测结果在同一 PostgreSQL 事务采用。授权的 `local/test` Profile 还可在终审后调用真实 MiniMax-M3 生成受引用约束的答案。单元、隔离 PostgreSQL、真实 Qdrant round trip、Nginx/HTTP 提示注入双路径拒答、受限真实 LLM smoke 和唯一一次受限付费百炼 smoke 已通过。安全专用 100 条 `no_answer` 合成集不等于代表性 50/100 条业务审批集；完整百炼索引重建、正式容量、production 与 AC-008～011/016 仍未运行。
- RAG 引用只能来自本次授权检索结果。
- 引用必须能追溯到制度版本、Markdown、分块、页面和索引版本。
- 无足够依据时返回无答案或降级结果，禁止模型补造制度依据。
- 确定性金额、日期和重复规则由普通代码执行，不交给模型判断。
- 审核任务与执行版本是不同对象；快照、规则结果、风险和报告绑定执行版本。
- 已完成执行依赖的事实改变时，旧结果必须标记过期，不得静默沿用。
- high 风险的最终处置必须由获授权角色完成并留痕。

### 11.1 `report-xlsx-writer-v1` 内部 Profile

- 依赖精确锁定为 `XlsxWriter==3.2.9`；入口只接受当前冻结的精确 `ReportPayload`，只生成内存 XLSX 字节，不访问数据库、对象存储、网络或系统字体。
- 工作簿固定且仅含三个可见工作表：`Summary`、`Rules`、`Risks`。规则必须为有序 `RULE-001`～`RULE-015`，风险最多 15 条，并重新校验 hit rule、risk、pending review 与 summary 的一致性；UUID、枚举、引用顺序、UTC 时间和 AI-disabled 降级事实失败关闭。
- 单元格只允许显式字符串、布尔、安全整数和空值；关闭字符串到公式、URL 和数字的自动转换，所有字符串先经过七类公式前缀保护并拒绝非法 XML 字符。OOXML 不得包含公式、超链接、External 关系、宏、媒体或绘图。
- 每个文本单元格最多 4096 code point，全簿文本最多 262144 code point，引用 ID 最多 110 个，降级原因最多 1024 个，输出最多 2 MiB；超过边界、库写入非零返回或负载内部事实不一致时失败关闭。
- 固定输入的字节相等只承诺同一 Python、XlsxWriter、操作系统和运行环境；跨镜像字节复现必须另行运行，不能由单环境测试推断。
- 该 Profile 本身仍只是 `REP-003` 的内部 Writer 边界；正式报告运行时通过 §11.7 的冻结 payload、数据库版本、MinIO 和鉴权读取组合使用它。仅运行 Writer 测试不能替代 §11.7、浏览器、production 或 AC-014 证据。

### 11.2 `report-pdf-writer-v1` 内部 Profile

- 依赖精确锁定为 `ReportLab==5.0.0`；入口只接受当前冻结的精确 `ReportPayload`，只生成内存 PDF 字节，不访问数据库、对象存储、网络或系统字体，并复用 §11.1 的负载重验边界。
- 页面固定为 A4，最多 128 页、8 MiB；每页必须显示“内部离线预览（非正式审核报告）”、页码、过期/降级状态、降级原因数量和引用仅为未解析 ID 的说明。正文按固定顺序展示 Summary、15 条 Rules 与最多 15 条 Risks。
- 所有负载字符串通过 JSON 字面量与可见控制符转义展示；TAB、CR、LF、C0/C1、双向控制符、格式控制符和行/段分隔符不得产生新的视觉字段或控制阅读方向。缺失字形、超限、负载事实不一致或字体校验失败时失败关闭。
- 只允许使用随包分发的 AOSP `android-15.0.0_r25` `DroidSansMono.ttf` 与 `DroidSansFallback.ttf`；渲染前按固定 SHA-256 校验，并以带 `/ToUnicode` 与 `/FontFile2` 的内嵌 TrueType 字体输出。原始 `NOTICE`、`README.txt` 与记录精确 tag、URL、字节和哈希的 `SOURCE.txt` 必须随字体入包；不得回退到 Helvetica、系统字体、CID 运行时映射或运行时下载。
- PDF 不得包含 JavaScript、Action、URI、Launch、附件、嵌入文件、表单、富媒体、主动 Metadata XML 或 XObject；固定输入的字节相等只承诺同一 Python、ReportLab、操作系统和运行环境，跨镜像字节复现必须另行运行。
- 当前离线 Writer 证据包括字体/许可证/来源入包、上游 exact hash、Poppler 全页渲染、pypdf/pdfplumber 提取和主动内容检查。`formal_report_pdf_bytes` 使用同一安全渲染器但切换为正式标题与冻结执行元数据；Profile 单测仍不能单独证明数据库、MinIO、鉴权、浏览器、跨镜像、production 或 AC-014。

### 11.3 `knowledge-retrieval-v1`

- P0 不建立知识库 ACL 表。允许集由 Repository 按 `Actor.organization_id`、`knowledge.use`、知识库 active、制度 published、未软删除、基准日有效期、活动索引成员和内容摘要共同生成；每个谓词必须在 PostgreSQL 可执行查询中重验。
- 一个 Qdrant Collection 对应一个环境、一个 Embedding 模型身份和一个向量维度。名称从安全配置显式注入并作为不可变身份；应用不得列举、自动创建或按知识库猜测 Collection。distance 和维度仍由 Adapter 在使用前校验。
- 查询固定三阶段：PG 生成有界允许 Point ID 集；Qdrant 使用 `has_id` must-filter 召回；PG 按返回 ID 重读并终审组织、权限、制度状态、有效期、活动成员、Chunk/Markdown/原文摘要。服务端返回越权、缺失或漂移 ID 时整次失败关闭。
- Qdrant payload 只保存重建需要的无敏感最小投影；PostgreSQL 保存索引版本、成员、向量摘要、活动状态和评测事实。向量摘要按 Qdrant 实际持久化的 IEEE-754 float32 字节规范化，避免写入前 Python float64 与读取后 float32 的正常精度差异被误判为成员漂移；非有限值和 float32 溢出仍失败关闭。候选索引完整写入、成员一致性与门禁通过后才可事务激活，失败时旧 active 不变。
- RAG 生成器只接收终审后的本次候选。引用逐项绑定制度版本、Markdown、Chunk、document block、页码、索引版本和冻结正文；引用验证失败、无答案、越权、提示注入或依赖降级时返回受控拒答，不采用模型补造内容。

### 11.4 `retrieval-evaluation-v1`

- evaluation tier 精确为 `smoke|mvp_uat|formal_release`，最小已审批用例数分别为 5、50、100。100 条集合可包含 50 条，但每一档运行都有独立 run ID 和不可变输入身份。
- 公共 JSON API 在信任边界把 tier/label 字符串和 cases/ID 数组显式规范化为严格内部类型；未知枚举、非数组或不规范日期/UUID 仍返回 422，不能要求浏览器构造 Python Enum 或 tuple。
- 每个 run 保存组织、tier、数据集版本/摘要、索引版本、Embedding/确定性生成器身份、参数、逐题实际排名、授权过滤结果、未命中原因和聚合指标。相同输入可重跑但不能覆盖旧 run。
- smoke 只允许验证链路；只有 mvp_uat/formal_release 可分别作为 MVP/UAT 与正式激活/发布证据。权限泄露或成员不一致在任何 tier 都立即失败。

### 11.5 `builtin-audit-rule-catalog-v1`

- P0 规则目录只含应用静态 `RULE-001`～`RULE-015`。每行保存正整数 version、七类 category、严格输入 Schema、默认风险、固定中文解释、citation 标志、静态 implementation key/hash，以及 application release 和 catalog manifest hash；数据库字符串不得用于 dynamic import、反射或表达式执行。
- 显式离线 publisher 在单事务和固定 advisory/table lock 下发布完整 15 行：0 行时一次插入，精确相同 15 行时 no-op，部分集合、额外 code/version、混合版本或任一 semantic/hash 漂移都整批失败。应用启动、migration、HTTP 和 Worker 不自动补种。
- 已发布行不可 UPDATE、DELETE 或 TRUNCATE。变化发布 15 条 lockstep 新版本；每个 code 的最大 version 派生 current，历史审核快照仍引用原 rule version ID。
- 规则执行器只通过静态 allowlist 调用普通代码谓词。没有已确认主合同时只执行独立规则，其余保存 `not_applicable`；规则结果先于检索和 AI，外部能力失败不得改写确定性结果。

### 11.6 `audit-execution-v1`

- 执行状态闭集为 `draft|validating|queued|running|pending_finance_review|pending_audit_review|returned_for_correction|completed|failed|cancelled|outdated`。允许边以 `CR-018-R1/RFV1-D-006` 为唯一产品决定，并由 Backend domain map 与数据库 trigger 双重校验。
- 取消直接 CAS 为 `cancelled`，不存在持久 `cancel_requested`。`failed→queued` 只允许同一不可变快照的技术重试；事实已变化时旧执行转为 outdated 并创建新执行。returned/cancelled/outdated 无后继，completed 只可转 outdated。
- Task、item、execution、snapshot、rule execution、risk、report 必须具有一致组织和父对象；使用复合唯一/FK 或约束 trigger 在数据库拒绝跨 task、跨 execution 和跨组织引用。快照及终态结果不可 UPDATE。
- 风险 `original_level` 永不修改；人工复核只写 `effective_level/review_status/reason/reviewer/time`。财务只处理非 high；存在 `effective_level=high AND review_status=pending` 时禁止完成。处理 high 必须具有 `risks.review_high`，且 reviewer actor 不得等于本执行 finance reviewer。
- 状态转换、复核、重审和过期传播都使用 row-version CAS，并与必要 operation-log、correction/decision history、Job/Outbox 同一 PostgreSQL 事务。迟到 Worker 结果不能越过取消、过期或新 fencing token。
- 审核簇锁序固定为 audit task → execution → snapshot → rule execution → risk → report；业务写和 downgrade 不得反序。

### 11.7 `formal-report-runtime-v1`

- 报告状态为 `queued|generating|ready|failed|outdated|archived`。允许 `queued→generating|failed`、`generating→ready|failed`、`failed→queued`（同 execution 与 payload hash 的技术重试）、`ready→outdated|archived`、`outdated→archived`；archived 无后继。
- 报告只从 completed execution 的冻结快照生成。每个版本保存 execution、payload hash、PDF/XLSX 对象身份、SHA-256、字节数、MIME、生成器版本和状态；ready 后对象及元数据不可覆盖，新生成创建新版本。
- MinIO key 只由 Backend 生成并保存在数据库。客户端只能通过 Backend 下载：PDF 要求 `reports.read` 并以 `Content-Disposition: inline` 返回；XLSX 要求 `reports.export` 并以 attachment 返回。响应不得包含 bucket、object key、内部 endpoint 或预签名直链。
- execution 转 outdated 时，其 ready 报告在同一事务转 outdated；历史制品继续保留，并在读取/预览响应中明确 `is_outdated=true`。对象上传成功但数据库提交失败必须精确补偿；结果未知使用受控恢复状态，不能返回 ready。
- 当前 `ReportQueueService`、`ReportJobExecutor`、`ReportRuntimeRepository`、`MinioReportStorageAdapter` 和 Report Router 已实现 completed execution 自动排队、版本化 payload、PDF/XLSX 生成、双对象持久化、哈希/字节/MIME 核验、失败恢复及鉴权流式读取。API/Worker 使用分离的 MinIO 最小权限，客户端响应不暴露 Bucket、对象键、内部 endpoint 或预签名 URL。
- 显式真实 MinIO Gate 已覆盖 Worker 写入、API 身份读取、权限拒绝和篡改失败；本地同源浏览器已验证真实登录后的报告元数据、PDF blob iframe 预览、XLSX 下载动作审计和零 console error。固定合成正式报告又在宿主与当前本地 Backend 镜像中通过 PDF 语义/字节一致、XLSX 规范化内容一致和 Poppler 渲染，并由 Microsoft Excel 以禁用宏、只读方式实际打开两份 XLSX；LibreOffice、production、UAT 和正式 AC-014 仍为 `NOT_RUN`。

## 12. AI 合同与安全边界

### 12.1 当前可用能力

- Backend 和 Worker 在对象构造前加载并校验本地 AI Policy。
- `Settings` 与 Policy 的版本、模型、端点、deadline、retry、预算和限流投影必须一致。
- `AI_PROVIDER_CALLS_ENABLED=false` 仍是默认值；`local/test` 可显式启用 `minimax-m3-bailian-qwen37-local-v2`，production 继续启动失败。环境值、Policy 原始字节与 canonical hash 任一漂移都失败关闭。
- OpenAI-compatible Chat/Embedding Adapter 与 `AiGateway` 已接线。Chat 的 `AuditedLlmInvoker`、结构清理/修复、共享预算和持久 EventSink 接入合同/发票提取、RAG 回答、风险解释与报告草稿；Embedding 接入 Backend RAG 查询、Worker 索引构建和检索评测。
- `RedisAiRuntimeControl` 已接入所有真实 Chat/Embedding 调用，使用 Redis server time 与 Lua 原子维护 `rag/async_generation/embedding` 三个独立并发、RPM、TPM、burst 池，以及按 Adapter+模型不可逆哈希隔离的滚动失败窗口、open deadline 和单 half-open probe；Redis 不可用时真实 Provider 调用失败关闭。
- Provider 调用发生在数据库事务外；采用前重新锁定和校验业务输入，完成事件再与业务事实同事务提交。结构、权限、引用、状态或 payload hash 漂移时拒绝采用。
- `GET /api/v1/ai-call-logs` 已按 `operations.read`、当前组织和 `private, no-store` 暴露 OPS-005 安全摘要；不返回 Prompt、响应正文、Header、密钥或 Provider URL。
- `CR-021` 固定百炼北京共享 OpenAI-compatible endpoint、`qwen3.7-text-embedding`、1024 维、20 条批次、30 秒 deadline、`EMBEDDING_API_KEY` 和 CNY 价格快照；`CR-022 / option-A / event-policy-v2 / USD-CNY-only / no-fx` 继续固定币种中立事件、预算、数据库与 OPS-005 合同。Settings 与 Policy 不一致时启动失败；模型/维度切换必须新建索引版本。
- Event v1 和 legacy `reserved_cost_micro_usd` 继续用于历史回放。Event v2 使用 `cost_currency=USD|CNY|null`、`reserved_cost_microunits` 和 `actual_cost_microunits`；`null` 仅表示内部不计费且金额为零。禁止汇率换算、跨币种相加、把未知实际费用记为零或在 v2 同时填写 legacy 字段。

### 12.2 调用规则

- 调用必须通过 Provider-neutral Gateway 和注册 Adapter，业务代码不得直接请求模型 URL。
- 每次调用必须携带显式目标和 Trace；Chat 还必须携带 purpose 与共享预算上下文。
- Chat 的 retry、fallback 和结构修复共用总请求、Token、费用和 deadline 门禁；Embedding 固定单次 Adapter 调用、批次/deadline/字节限制，transient failure 只进入既有 Worker Job recovery。
- Chat 与 Embedding 都在发送前按最坏情况预留预算；失败后不释放预留以避免重放超支。Chat 固定 `USD`，百炼 Embedding 固定 `CNY`，只使用对应币种的整数 microunit，不进行 FX。
- 运行门禁顺序固定为：纯预算/deadline preflight → Redis 并发/速率/熔断许可 → durable Event v2 reserve → 最终 monotonic deadline → 单次 HTTP → Redis 完成 → durable complete/业务采用。Redis 拒绝不写 started、不消耗 `SendPermit`；Provider 成功但 Redis 完成失败时必须写安全失败 completion，输出不可采用。Embedding 使用 UTF-8 字节数作为不低估 Provider token 的保守上界，权威 usage 对账失败或 completion 不能与业务事实同事务提交时不得采用向量。
- 结构化输出先做本地确定性 JSON 与 Pydantic 校验。
- 重复键、非有限数字、多对象歧义和超出 Schema 的不可信结构失败关闭。
- 修复请求只携带安全 JSON Pointer 和错误类别，不携带原始敏感值。
- 引用与风险解释必须通过独立业务校验器，模型返回不能替换严格解析对象。
- AI 不得批准制度、激活索引、改变审核状态或覆盖确定性规则结果。

### 12.3 出站网络

- secret 只通过 Policy 引用的环境变量槽位注入，不进入 Policy 正文。
- 外部 Provider 必须使用 HTTPS、域名 allowlist、DNS/IP 校验、peer 复核、超时和响应大小限制。
- 禁止继承系统代理、自动重定向、任意 URL、内网探测和任意工具调用。
- Provider 错误只映射为受控类别，不向用户暴露响应正文或 Header。
- `local/test` Chat 的真实 HTTP、DNS、TLS、peer、持久事件和业务采用已有受限 smoke；Redis 运行门禁已在两个独立客户端上以锁定 Redis 7.4.9 digest 验证共享并发、RPM/TPM、滚动熔断、并发旧成功不误关新熔断和单 half-open 恢复。百炼 Embedding 的唯一一次受限付费 smoke 也已验证真实 HTTPS/peer、43 input tokens、2×1024 维输出和 Event v2/CNY `22` microunits 持久审计；该授权已消耗，不代表代表性检索、生产 Policy、生产网络、Secret Manager、quota/canary 或正式 AC。

### 12.4 `ai-call-audit-runtime-v1-v2`

- `AiCallAuditRepository.reserve_attempt()` 在 `(organization_id,business_operation_id,policy_version)` 的 PostgreSQL transaction advisory lock 下汇总已提交 `ai.call.started`，同时守住事件版本、同一币种、物理尝试数、单请求输入/输出 Token、业务总 Token、最坏费用和 monotonic deadline；相同 `event_id`/内容重放，内容漂移或同一业务操作混币种冲突，提交结果不可确认时 Service 只返回 `unknown`。
- `append_completion()` 先验证已提交的同 ID reserve；`TransactionalAiAdoption` 只允许调用方在当前业务事务中写 completion，并与合同、发票、RAG Query、风险解释或报告草稿事实原子提交。回滚时二者都不可见。
- `backend/app/services/ai_call_event_sink.py` 把持久状态映射为一次性 `SendPermit`/`AdoptPermit`：只有 `reserved_new` 或同一调用域安全恢复可发送；新实例 replay、外来 scope、冲突、预算/deadline 耗尽、`outcome_unknown` 和 `late_completion` 均无采用许可。
- `AuditedLlmInvoker` 以 Event v2/USD 通过共享 writer/UoW 消费许可；合同/发票 Executor、RAG Service、风险解释和报告草稿均在采用前重验输入并在同一 Session 落完成审计。`EmbeddingRuntime` 对真实百炼调用以 Event v2/CNY 先 reserve，Backend RAG、Worker 索引批次与评测 case 再把 completion 和采用事实同事务提交；离线 Hash Runtime 不产生付费审计。聚焦单元、隔离 PostgreSQL scopes、真实 MiniMax 与唯一一次百炼 smoke 覆盖成功、拒绝、回滚与降级；production 仍未运行。
- Redis 许可先于 durable reserve；许可中的 `breaker_state=closed|half_open` 写入 started。调用前审计预留失败或 deadline 耗尽时只中性释放 Redis 租约；仅规范化 transient Provider 失败计入熔断，永久/配置/业务输出失败不误伤目标。正常 closed 调用成功不会清除另一个并发调用刚打开的熔断，只有当前 half-open owner 的成功或中性结果可以关闭 open 状态。
- Maintenance 在所有既有 Job 恢复工作空闲后消费 `ai.call.*` Outbox。claim、`ai_call_logs` 投影和 published 标记在同一 PostgreSQL 事务；sequence 2 先到时等待 sequence 1。消费者显式分派 v1/v2；未知版本、混版本、冲突或坏载荷进入 dead-letter，`late_completion`、dead-letter、`outcome_unknown` 和补偿阻塞只记录不含 ID/载荷的 WARNING。
- Reconciler 在对应调用 deadline 加 30 秒后持有同一 aggregate 锁，先检查权威 completion；确实不存在时才追加并投影 `outcome_unknown`。终态后的真实结果只能作为 sequence 3 `late_completion` 证据，不能把未知终态改写为成功。
- `get_operation_summary()` 只返回业务操作、尝试顺序、模型身份、预留预算、实际 Token、安全错误码、Trace 和时间等已批准安全字段；v1 只返回 legacy USD，v2 只返回 `cost_currency`、generic 预留和权威实际费用，不能跨币种汇总。OPS-005 Router 使用 `operations.read` 和 Actor organization 强制范围，跨组织不存在性不泄露。
- Alembic `20260817_024` 保留非空 v1 历史字节/行，增加 v2 generic 费用列；pending AI log 或未发布 AI Outbox 阻断升级，含任意 v2 Event/log 时阻断 downgrade。隔离 PostgreSQL 16.14 AI 门禁覆盖 v1 保留、字段混用、CNY v2 投影与 OPS 汇总、同 ID 重放/冲突、事务回滚、提交结果未知映射、并发预算、各 Token/费用/deadline 边界、乱序、消费者中断恢复、未知版本/坏载荷隔离和 `outcome_unknown/late_completion`；完整数据库目录又连续两轮通过。
- 独立 `local-ai-audit-crash-recovery-v1` local Compose 门禁已在 Provider 关闭时播种同一调用的 started/completed Outbox，以 `ai_call_logs` 排他锁确认 Maintenance 进入真实投影事务，再对精确容器执行 SIGKILL 并确认退出码 137。门禁释放本次专用锁后等待唯一数据库会话消失，核对两条 Outbox 仍为 pending/attempt 0 且无审计日志，再启动同一容器并确认两条事件各投影一次、唯一 succeeded 日志、脱敏结构化日志、零测试事实残留和依赖恢复 ready。Redis/Celery 与 runtime-control 的当前隔离门禁共 4 项通过；真实百炼 smoke 已有一次 local/test 证据，但 Docker 自动重启、主机断电、production 或正式 AC 仍保持 `NOT_RUN/BLOCKED`。

### 12.5 `ai-extraction-prompt-v1`

- `backend/app/ai/extraction_prompts.py` 是 AI-003 当前内部机器事实源。合同与发票分别固定为 `contract_field_extraction / contract-field-extraction / v1 / d79afad7a5654d72091a34f4c0d0e5a7123d95dde4eb24503d6634fa1ac2698a` 和 `invoice_field_extraction / invoice-field-extraction / v1 / 09f1c58c930c0e49d912f7052243c00e377fea11260de010cf1cb090cb91d3de`；Hash 只覆盖精确 UTF-8 system instruction，文档内容另由调用事件的 input hash 管理。
- 输入块必须使用 UUID 类型的 `block_id/parse_version_id`、正页码、非负 block index、1～4000 字符原文、可选有限 `0..1` Decimal confidence 和 string→integer bbox。一次请求只能包含一个解析版本，block ID 和页内位置都必须唯一；渲染器按 `page_no,block_index,block_id` 排序并编码为 `extraction-input-v1` canonical JSON，不插值到 system instruction。
- 两份 Prompt 都把 `blocks[*].text` 定义为不可信数据，只允许逐字证据，不使用常识补全；无证据或冲突字段返回 `null`，证据必须逐字回指本次输入，禁止模型确认合同/发票、决定重复/真伪、审批、激活、输出风险或付款结论。合同固定 13 个核心字段；发票固定 13 个头字段与有序基础明细，且明确禁止因本地默认值伪造币种证据。
- 合同/发票严格输出 DTO、证据白名单、同目标结构修复、Gateway/EventSink、真实 Provider 与 Executor 业务采用已经接线。`022` 已把未确认发票 currency 改为可空并移除无证据 CNY 默认，confirmed 边界仍要求非空。正式代表性准确率和 99% 结构合法率尚无审批数据集与运行结果，因此 AI-003 仍为 `partial` 而非 `accepted`。

## 13. Frontend 与 UI 合同

### 13.1 当前页面事实

- 当前 Router 提供登录、工作台、文件、合同、发票、合同发票关系、供应商、知识库、问答、审核、报告和用户管理入口。
- 页面路径和角色导航以 `frontend/src/router/index.ts` 为准。
- 登录/会话、用户、Break-glass、操作日志、文件、合同/补充协议/发票、合同发票关系、供应商、知识库/问答、审核、正式报告和工作台页面均已接同源真实 API。报告页严格解码元数据并通过 Backend 获取 PDF blob 预览与 XLSX attachment；文件页支持批量独立结果、原件/文本预览、归档和失败 Job 重试。
- 合同详情的补充协议 Header 操作必须读取 `GET /contracts/{contract_id}/supplementary-agreements/{agreement_id}` 的字段级详情；`financial.read` 只能查看，只有 `contracts.manage` 且详情返回的当前状态允许时，才可调用整组 `PUT .../changes` 或 `POST .../decision`。Frontend 必须保留服务端 `row_version`、证据与同一逻辑提交的幂等键，冲突后不得静默覆盖；确认前每项变更必须有完整证据。基准日期区直接调用 `GET /contracts/{contract_id}/effective-fields?baseline_date=...` 并并列显示原始值、有效值和来源协议，不在客户端推导旧值。独立 `scripts/verify-supplementary-agreement-browser-gate.ps1` 在全新 PostgreSQL 中要求真实浏览器完成完整变更集提交、证据绑定、人工确认和基准日生效查询，并且只在受保护 manifest 核对行版本、日志和幂等结果后接受本次运行。当前未提供补充协议附件上传或合同版本替换入口。
- Access Token 和换密 Token 只保留在内存，Refresh Token 只由 HttpOnly Cookie 承载。显式隔离浏览器 Gate 已实际完成合同与发票 multipart 上传、文件 Worker、合同/发票提取、人工确认、主合同关联、审核执行/复核和 PDF/XLSX 报告，并在刷新后从服务端恢复事实；它使用合成业务数据、确定性 AI 与隔离依赖，不是 production 或正式 AC。
- `DashboardService` 只返回当前 Actor 有权读取的摘要、待办和最近失败 Job，不要求 Frontend 全量抓取业务事实；五角色权限裁剪、严格响应 decoder、空/错/刷新状态已有聚焦测试。页面不得回退到静态 fixture 或 Mock DTO 冒充真实状态。

### 13.2 API Client

- 唯一 Base URL 为同源 `/api/v1`。
- 客户端拒绝绝对 URL、双斜杠、反斜杠、fragment、百分号路径和逃出前缀的路径。
- 请求使用 `credentials: same-origin`。
- JSON 请求可统一注入 `row_version`；FormData 由调用方显式写入并让浏览器生成 boundary。
- HTTP 204 只在调用方声明 `expectNoContent` 时接受。
- 普通成功响应必须是合法 `OK` 包络，并由调用方 decoder 校验业务数据。
- 非法成功体、非法 204 或 decoder 失败统一映射为 `API_RESPONSE_INVALID`。
- 网络失败统一映射为脱敏 `NETWORK_ERROR`。
- 认证失效错误触发统一会话清理回调，不由页面分别处理。
- 强制换密 Token 只允许从精确登录路径的 403 错误中读取，不进入可枚举错误字段或持久化 Store。

### 13.3 权限与体验

- Router 守卫只控制页面入口；Backend 必须再次鉴权。
- 页面必须实现 Loading、Empty、Error、Forbidden 和 Not Found 状态。
- 错误页显示可复制 Trace ID，但不得显示 Token、路径、SQL 或原始异常。
- 状态展示使用正式状态码到简体中文和 ARIA 文案的集中映射。
- “带入助手”只预填输入，不自动发送。
- 桌面和窄屏布局都要检查溢出、重叠、键盘操作和可访问名称。

## 14. 配置与运行安全

### 14.1 配置事实

- `infra/env/.env.example` 是变量名和注入顺序模板，不是可直接运行的配置。
- `Settings` 是 Backend/Worker 的运行时配置 Schema。
- 从源码仓库在主机直接运行时，`Settings` 默认加载由 `config.py` 绝对定位的 `infra/env/.env`，不依赖当前工作目录；空值继续忽略。
- 配置优先级固定为显式初始化参数 → 进程环境变量 → 运行时 Secret 文件 → 仓库 `.env` → 字段默认值。仓库布局无法验证时不启用该 dotenv 来源；Docker 镜像排除 `.env`，Compose/production 继续由启动器、环境变量或 Secret Manager 注入。
- 本地 AI Policy 是 AI 相关值的第二重门禁；只修改环境变量不能绕过 Policy。
- 配置校验错误必须隐藏原始输入和 secret。

#### 14.1.1 `local-minio-v1`

- 仅用于 local/test 的镜像引用固定为 `minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`；这是多架构 manifest digest，Compose 必须同时使用 tag 与 digest，禁止 `latest` 或仅 tag 漂移。
- Compose 内的 Backend/Worker 只通过内部网络访问 `http://minio:9000`，`MINIO_SECURE=false`；主机侧 bootstrap 只访问 loopback `127.0.0.1:9000`。Frontend 不得直连，9000/Console 不得成为产品公网入口；该明文边界不得复制到 test/prod 外部网络或 production。
- 七个 Bucket 逐字固定为 `quarantine`、`originals`、`assets`、`previews`、`reports`、`exports`、`temp`，必须分别创建且组内唯一，不得合并职责。
- `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` 只用于容器启动与最小 bootstrap；应用使用 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`。四个值均由 local 启动器或 Compose 在运行时生成/注入，`.env.example` 只保留占位符，仓库、命令行、日志和测试证据不得保存真实值。
- 当前 `MinioQuarantineAdapter` 只暴露 quarantine put/delete；对象键固定由服务端生成 `organizations/{organization_id.hex}/files/{file_id.hex}/source`，不使用用户文件名。上传 SDK 实际读取时必须校验精确长度与 SHA-256 并写入摘要 metadata。PUT 未正常返回时必须尝试删除同一独占键，但无论该次删除是否返回成功，都必须以脱敏 cleanup-required 内部错误携带只读 locator；一次删除不能证明迟到 PUT 不会随后落盘。PUT 已正常返回后的摘要或长度不一致也必须补偿删除，只有删除失败时才升级为 cleanup-required，不能伪装成已清理。
- `MinioReportStorageAdapter` 以 `api|worker` credential scope 分离读取与写入；报告对象键固定由服务端生成并只持久化在 PostgreSQL，API 只能读取数据库授权且摘要/长度/MIME 一致的对象。
- 本 Profile 已有分离应用身份/Bucket bootstrap、离线配置/Adapter 测试，以及 quarantine、冷重启持久性、正式报告和完整 local Compose 中的显式 real MinIO Gate。报告 Gate 已覆盖 Worker PDF/XLSX 写入、API 读取、越权拒绝与篡改失败；完整本地恢复还校验 MinIO 整卷摘要、文件数与字节数。上述证据仍不证明通用迟到 timeout reconcile、强杀/断电、容量、异地备份、production 或 AC-002/014/016。production 必须另有 TLS、网络、权限、保留、备份和恢复 Profile。

### 14.2 Fail-closed 规则

- secret 为空、过短或仍为占位符时启动失败。
- 数据库只接受 `postgresql+psycopg` URL。
- Redis/Celery 只接受 `redis` 或 `rediss` URL。
- HTTP 服务 URL 禁止 userinfo、query、fragment、控制字符和歧义主机；MinIO endpoint 还必须是无 path 的 HTTP(S) origin，`MINIO_SECURE` 与 scheme 一致，production 强制 HTTPS。
- Qdrant 向量维度必须等于 Embedding 维度。
- 当前 live Profile 只允许百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`、`qwen3.7-text-embedding`、1024 维、批次 20 和独立 `EMBEDDING_API_KEY`；calls-disabled 则使用确定性 Hash。两种 Adapter 身份不得混写同一索引。
- Celery 软超时必须小于硬超时。
- Celery 队列名组内唯一；MinIO Bucket 必须同时满足 S3 兼容命名规则并组内唯一。
- OCR 引擎仍是产品选型 TBD；当前可执行 Profile 仅为 `not_configured` 或 `tesseract_cli`。`tesseract_cli` 必须同时固定 executable 和 version，使用无 shell、有超时的 TSV Adapter；未配置时图片/扫描 PDF 失败关闭，不得产生空文本成功版本。`OCR_BASE_URL/OCR_API_KEY` 暂不构成已安装 HTTP Provider 协议。
- 启用本地 vLLM 前必须提供完整运行 Profile。
- 组织级分块配置不得由旧 `CHUNK_*` 环境变量定义。
- Qdrant Collection 身份已由 `recommended-forward-v1` 固定为环境+Embedding 模型+向量维度，名称必须显式注入且占位符失败关闭；应用不得枚举、创建或猜测名称。

### 14.3 Secret 规则

- 除 `Settings` 上述固定的本机源码仓库入口外，不读取真实 `.env`；不得提交、回显或记录 `.env`、Token、密码、API Key 或私钥。
- 不在 CLI 参数、URL、测试 fixture、日志、报告或前端持久化中保存 secret。
- 文档只记录变量名、来源和安全注入方式。
- 数据库 Engine 隐藏 SQL 参数；配置对象对敏感字段使用 `SecretStr`。

### 14.4 `dependency-health-v1`

- `GET /health` 仍只证明 Backend 进程存活；`GET /health/dependencies` 独立探测固定顺序 `postgresql|redis|minio|qdrant|worker|scanner|ai_provider`。响应中的每项精确为 `{name,required,status}`，其中 status 只允许 `ok|unavailable|disabled`；不得返回地址、端口、凭据、底层异常、耗时、节点名或 Worker hostname。
- PostgreSQL、Redis、MinIO、Qdrant 和至少一个响应 Celery ping 的 Worker 始终是必需依赖。Scanner 在 `not_configured` 的 local/test Profile、AI 在 `AI_PROVIDER_CALLS_ENABLED=false` 时分别返回 `required=false,status=disabled`，不影响就绪；一旦对应 Profile 启用即为必需依赖并执行有界 Provider 探针。production 仍禁止启用未批准 Profile。
- 所有必需依赖为 `ok` 时聚合 status 为 `ok` 并返回 200 `code=OK`；任一必需依赖失败、超时或响应非法时聚合为 `unavailable` 并返回 503 `code=DEPENDENCY_UNAVAILABLE`。两种响应都使用同一脱敏 `SuccessResponse[DependencyHealthData]` 投影并包含 Trace ID；disabled 不得伪装为 ok。
- 每个运行探针必须设置有界连接/读取等待。`/health/dependencies` 只是实时就绪证据，不替代迁移、业务 smoke、容量、告警、production Scanner/Provider 或恢复验收。

### 14.5 `internal-metrics-v1`

- `/metrics` 位于业务 `/api/v1` 之外，只在 `METRICS_ENABLED=true` 时注册，并要求独立 `METRICS_INTERNAL_TOKEN` Bearer 凭据；用户 JWT、Cookie 和 query token 均不构成授权。
- 指标仅包含 build、uptime、in-flight、HTTP 请求计数和固定桶耗时；标签限制为固定 method、request group 与 status class，不包含原始 URL、组织、Actor、Trace、业务 ID、Prompt、正文或错误内容。
- Nginx 仅以精确 `location = /metrics` 代理并透传 Authorization。当前单元与静态 Nginx 合同已通过；生产网络暴露、采集器身份、Prometheus/告警/SLO、保留期和容量仍为 `NOT_RUN/BLOCKED`。

### 14.6 `local-compose-v1`

- `infra/compose/compose.local.yml`、Backend/Frontend Dockerfile、`infra/env/.env.example` 与 `docs/runbooks/local-stack.md` 共同构成本地完整栈运行事实源。栈包含 PostgreSQL、Redis、MinIO、Qdrant、ClamAV、迁移、Bucket/Collection/admin 初始化、Backend、Worker、Dispatcher、Maintenance、Frontend/Nginx；AI Provider 固定关闭，OCR 固定为 `not_configured`。
- PostgreSQL、Redis、MinIO、Qdrant、ClamAV、Python、Node 和 Nginx 基础镜像都必须使用 tag+manifest digest；不得使用 `latest`。Qdrant local 继续固定 `1.10.0`：现有 1.10 派生卷直接启动 1.18 已实际因 segment 格式不兼容失败，因此升级必须采用显式快照或从 PostgreSQL 事实重建，不得静默删除卷。
- 只有 Nginx HTTP 入口映射到主机 `127.0.0.1:${FINAUDIT_HTTP_PORT}`；Backend、数据库、缓存、对象存储、向量库和 Scanner 不发布主机端口。业务容器使用只读根文件系统和 `no-new-privileges`；Backend、Worker、Dispatcher、Maintenance 丢弃全部 capabilities，Frontend/Nginx 也先 `cap_drop: ALL`，只补回官方镜像启动所需的 `CHOWN/SETGID/SETUID`。`app`/`data` 网络为 internal；仅 ClamAV 同时加入 `scanner_updates` 网络以更新本地病毒库。该宽出口只允许 local，production 必须使用域名出口控制、代理、告警和定义版本审计。
- `scripts/start-local-stack.ps1` 在 `%LOCALAPPDATA%/FinAuditAgent/runtime/<project>` 创建带归属标记的运行时 Secret 与 Ed25519 keyring，并通过只读 Secret mount 注入容器；`CR-024` 后不再生成或挂载 TLS 证书/私钥，也不创建或读取仓库 `.env`。启动器执行当前 accepted head `20260817_024` 迁移、七 Bucket、Qdrant Collection 和 first-org/admin 幂等 bootstrap，初始密码只输出文件路径且首次登录强制换密。
- `scripts/verify-local-stack.ps1` 分开验证依赖、HTTP/Nginx 文件链、六类 Worker 崩溃恢复、性能和安全基线。文件 smoke 使用独立 `finance_reviewer` 并等待 ClamAV → Celery Worker → PostgreSQL `stored/clean/succeeded`，最后核对 MinIO 原件；各恢复门禁继续核对 `LEASE_EXPIRED`、attempt 2、唯一事实、日志/Outbox 与依赖恢复。安全门禁核对 HTTP/CSRF/锁定/防枚举/授权拒绝/Trace/审计回滚/日志不可变、容器权限和 loopback 暴露；浏览器直接访问门禁输出的 HTTP origin 完成登录、问答与拒答后，再由 PostgreSQL 终审 Query、Hash、Trace 和操作日志。HTTP 结果不提供传输加密证据。
- 性能门禁只允许专用 `finaudit-perf-*` 项目；每个 run 连续三轮测量审核列表、单文件受理、默认最大 20 件批量及其同键重放，并运行 207 部分失败和 21 件超限 413，最后按 run-scoped 文件名核对 61 组文件/Job/attempt-1 scan step/published Outbox 与超限零副作用。该门禁可在同一隔离栈以新 run 重复执行，但小型合成 PDF 和 local 硬件结果不得外推为正式参考环境完整容量。
- `scripts/backup-local-stack.ps1` 先静默业务写入，再生成 PostgreSQL custom dump 与 MinIO 停机一致整卷归档；manifest 保存 SHA-256、核心表行数和 MinIO 内容摘要，不包含 Secret。`scripts/restore-local-stack.ps1` 只允许新项目隔离恢复，逐表/逐摘要核对后重建 Redis/Qdrant/ClamAV 派生状态并等待 dependency-ready；恢复仍需要源 Secret 或等价受控注入。
- `scripts/stop-local-stack.ps1` 默认保留卷与 Secret；只有显式 `-Purge` 且归属标记、项目名和受管绝对路径全部匹配时才删除。`CR-024` 前的本地启动、文件、恢复、性能和安全证据保留为历史；HTTP Profile 必须重新验证入口、Cookie、文件和浏览器链。跨组织 IDOR、传输加密、完整审计链、正式 DAST、Secret Manager、正式 Scanner/OCR、正式参考环境完整容量性能、异地备份、RPO/RTO、UAT 和 AC 仍为 `NOT_RUN`。

## 15. BLOCKED：不得猜测的合同

以下阻断只限制对应最小切片，不得扩张为全项目停工：

- `BLOCKED-JOB-HTTP`：重试/取消动作的 `row_version` 来源、响应投影和冲突错误必须由新 OpenAPI 统一，不能拼接旧文档结论。
- `BLOCKED-DOCUMENT-CORRECTION`：纠错结果版本回填与追加写不可变要求冲突。
- `BLOCKED-SCANNER`：local Profile 已使用官方 ClamAV INSTREAM 并有真实 clean-path 证据，但不能冒充 production Scanner；生产产品、病毒库更新/回滚、出口、资源、告警和验证载体仍未闭合。
- `BLOCKED-AI-PROVIDER`：local Chat/Embedding 的端点、模型、网络 allowlist、Event/Policy v2 USD/CNY/no-FX 审计、持久 reserve/complete、Redis 运行门禁和业务采用已验证；完整百炼索引重建、代表性质量，以及 production Profile/Secret/quota/canary 仍未授权或未运行。

`CR-018-R1/recommended-forward-v1` 已关闭供应商、正常单文档 Markdown/asset、P0 知识权限、Qdrant Collection、检索顺序、评测分级、规则目录、审核执行/high gate 和正式报告状态的实现歧义；对应 Schema、Router 和本地运行时现已实现。该实现仍不表示外部 Provider、完整部署、production 或任何 AC 已完成。

解除阻断必须产生：

1. 唯一的可观察决定。
2. 对应 SSOT 的最小更新。
3. 能先失败后通过的契约或集成测试。
4. 对兼容性、数据迁移和回滚的明确结论。

## 16. 开发与验证流程

### 16.1 实现顺序

1. 确认目标不命中第 15 节阻断。
2. 写清用户可观察结果、权限、正常路径和关键失败路径。
3. API 先定义 Router/Pydantic；数据库先定义 Alembic/ORM；两者不得互相猜字段。
4. 先写最小失败测试，再实现 Service、Repository 或 Adapter。
5. 长任务先完成 Job/Outbox 事务，再接 Dispatcher 和 Worker。
6. Backend OpenAPI 稳定后再生成或编写前端 decoder 和页面调用。
7. 只修改当前用例涉及的文件，不顺带实现相邻模块。

### 16.2 完成定义

一个工作包只有同时满足以下条件才可标记完成：

- 代码实现了目标正常路径和关键失败路径。
- OpenAPI、Pydantic、ORM、Alembic 与前端 decoder 没有重复且冲突的定义。
- 权限、幂等、并发、状态迁移、Trace 和脱敏已验证。
- 相关单测、类型检查、lint 和构建实际通过。
- 需要外部依赖时，已在隔离环境完成代表性运行验证。
- UI 任务已完成桌面、窄屏、空、错、加载和权限状态检查。
- 未运行的 Docker、浏览器、Provider、性能、安全、备份恢复或 UAT 明确记为 `NOT_RUN`。

### 16.3 证据表达

证据等级依次为 `STATIC_PASS`、`TEST_PASS`、`RUNTIME_PASS` 和 `AC_PASS`，只证明各自范围；未执行记为 `NOT_RUN`，合同或环境缺失且不能安全猜测记为 `BLOCKED`。

## 17. 变更原则

- 修改产品范围或 AC：先更新需求规格说明书。
- 修改已实现 HTTP：改 Router/Pydantic，生成 OpenAPI，并更新契约测试和前端 decoder。
- 修改物理数据库：新增 Alembic revision，同步 ORM，并在隔离 PostgreSQL 验证升级与安全回退。
- 修改配置：同步 `.env.example`、`Settings` 和相关 Policy 校验。
- 修改 AI 行为：保持预算、deadline、网络和输出校验的失败关闭边界。
- 修改前端路由：同步 Router meta、导航、权限拒绝和页面状态测试。
- 破坏性变化必须提供明确迁移或版本策略；不得静默改变现有客户端或数据语义。
- 历史说明只归档，不作为现行 SSOT 的覆盖层。
