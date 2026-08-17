# FinAudit Agent

企业财务文档智能审核与风险分析平台。系统定位为审核辅助工具，不替代有权限的人员作出付款、税务或合规决定。

## 当前状态

说明：下文保留的 `57 表 / 122 API / 86 工作包` 是旧 V1.3 基线的历史盘点口径，用于理解当前进度，不再作为不可变产品数量合同；后续数量由 Alembic、OpenAPI 和追踪矩阵自动生成，只有业务语义变化才需要 CR。

`BASE-001` 本地治理已补齐项目分支模型与 Git 原生 ref 双重校验、`RootPath`/`.git` 绑定，以及 raw/effective remote URL 失败关闭校验；另以纯标准库严格解析器验证项目工作流的 synthetic/offline 分支保护 fixture，固定覆盖 `main/develop`、禁止 Force Push、PR、独立 Review 和 static/test 类别。两类门禁都不执行 fetch/push 或托管平台查询；fixture 也不是 Request-exact 或远程证据。远程分支保护仍未配置和演练，因此 `BASE-001` 继续保持 `partial`。

当前已完成第一批基础工程切片：`BASE-001` 的本地仓库治理（含幂等初始化、Commit hook 和版本标签校验）、`BASE-002` FastAPI 骨架、`BASE-003` Vue 3 路由与布局骨架，以及 `BASE-004` 环境配置 Schema。`BASE-001` 因远程分支保护尚未配置和演练，整体状态仍为 `partial`。`CR-001-R2`、`CR-003-R3`、`CR-004-R2`、`CR-011-R4/R5/R6` 与 `CR-012-R3` 的合同均已批准并原子同步至九份 `Request/`，正式基线仍为 57 张核心物理表、122 个 API 与 86 个 P0 工作包。当前追踪矩阵为 2 个 `implemented`、31 个 `partial`、53 个 `planned`。`BASE-005` 当前为 **18/57**：`20260807_009` 在既有 15 表上按 Request 已冻结表合同增加空的 `supplementary_agreements/invoice_items/contract_invoices`，尚缺 39 表。当前 PostgreSQL 16.14（`server_version_num=160014`）Gate 已对唯一 head `20260807_009` 连续两轮运行 71/71 项并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，专用标签容器最终 0 残留，测试连接与确认环境变量已恢复。默认 `verify-local-offline.ps1` 仍不自动运行该显式 Gate。没有默认组织、管理员、密码、真实规则或业务数据种子；`BASE-005`、`AUTH-005` 仍为 `partial`，Repository/Service/API/Worker、真实 ACL/认证业务链、真实数据、Provider、浏览器 E2E、Compose、最小权限生产演练与所有 AC 仍未授权、未运行或未实现。

`BASE-002` production route config regression 已固定 `AppEnvironment.PROD` 下 `/health` 返回 200，而 `/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc` 全部返回 404；`test_app.py` 聚焦 20 项通过，独立审查为 `GO`。该结果只证明配置 seam，真实 production Policy、runtime 与 deploy 仍为 `NOT_RUN`。

`CR-003-R3` 是当前特权授权 active-baseline successor：九角色审批为 9/9，Gate A、十一文件原子同步、Gate B 与 008 storage-schema Gate C 均为 `PASS`。其前身 R1/R2 只保留为历史绑定。Gate C 的证据严格限定于可丢弃 PostgreSQL 16.14 上的 008 catalog、约束/触发器行为、并发、降级和往返；它不证明认证 Repository/Service/API/Worker、真实 ACL/调用者绑定、业务 runtime、真实数据或 AC。`CR-011-R4/R5/R6` 组成另一条当前批准链；R6 startup Gate C 仍 `BLOCKED BEFORE RUN / NOT RUN`，不得与已经通过的 CR-003-R3 storage-schema Gate C 混淆。`CR-004-R2` 和 `CR-012-R3` 的有限授权分别覆盖 007 与 006 空表 DDL/ORM 及其既有合成验证，不授权业务运行时、Provider、部署或 production。`CR-005-R1`、`CR-015-R2` 与 `CR-016-R1` 仍为 `NOT APPROVED`。`CR-014-R3` governance contract 已通过 BOSS direct approval `item-572`，绑定 `11956 bytes / e5c00e6e47081d0e7418b48957d7895fe5a4705a1d5008256a7bb291d15b7cd9`；本地回执仅是 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份为 `1801 bytes / 7421b7913ed31b12ba37da52f2a74d3ac28d7eab01bfeea0efc5bcde2c9bd08b`。随后生成的 `CR-006-R4` source snapshot 为 `8945 bytes / 159dd1588d9366c85e8aa1ffc5f9b910ea9319732a491785ce2fdf10d8096e8c`，`CR-013-R3` source snapshot 为 `9496 bytes / 6cecc269e6517bb5b30d535350cdcb7e9aa2a00cf827199c2c2cb3789eae3d1a`；`CR006_R4_SOURCE_A1` 已 `RECEIVED / VALID`，其 create-only 本地 receipt 仅为 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份 `1807 bytes / d98c2556a07deb73b6683fdc8c325498a19815acb0034cbf2ac3f7905f2aab1c`，`source_message_text_sha256=69886a5974497a981f8649f8071f476487319fe2f0abdfc9636b3618ef331695`；`CR013_R3_SOURCE_A1` 已通过 platform event `item-684` `RECEIVED / VALID`，其 create-only 本地 receipt 仅为 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份 `2607 bytes / 1454233d212979663e26e2699b924689cb081e893b456daa30530e81a778b9c8`，`source_message_text_sha256=572c102327f313c2a6e82ad582c4369f827e62c613c74ab14aecfe6b8971a37b`；两份 A1 source approvals 已闭合。CR-013-R3 blocklist A2 仍为 `NOT GENERATED / NOT RECEIVED`，原因是获准本地目录未找到合同精确 source/license bytes；resolver 可内嵌于 A1 已冻结的两条隔离单文件脚本并由 implementation-manifest → 十键 payload 传递绑定，无需新 resolver CR，现有两份 A1 保持有效；expected-post/inverse bundle 仍为 `NOT GENERATED`，joint authorization 仍为 `NOT RECEIVED`。临时 transport successor `CR-014-R4/CR-006-R5/CR-013-R4` 已撤回且不可批准。候选 lineage 仍是当前 009 → operation-log 010 → auth 011；010/011 migration 仍为 `NOT GENERATED / NOT AUTHORIZED / NOT RUN`，runtime 与 AC 仍为 `NOT AUTHORIZED / NOT RUN`，20/58 仍只是后续全部门禁成立时的候选结果。

`BASE-003` 的全局 `StatusTag` 已补齐 Request 页面出现的 62 个去重正式状态码，全部提供简体中文与 `aria-label`，未知 code 保持原样；`TraceIdCopy` 只复制当前 Trace ID，提供可访问的成功/失败反馈，并在属性切换时复位及忽略旧异步结果，避免把旧 Trace ID 标为当前已复制。这不新增或完成任何 FE 业务页面；真实浏览器剪贴板权限、屏幕阅读器和截图验收尚未执行。

`BASE-003` 的 `ApiClient` 已收紧请求与响应边界：FormData 请求会删除调用方提供的 `Content-Type`，由浏览器生成含正确 boundary 的 multipart Header；`AUTH_PASSWORD_CHANGE_REQUIRED` 在所有路径都使用固定中文消息并丢弃不可信 `details`，只有精确 `POST /api/v1/auth/login`、HTTP 403 且 `data` 合法时，才把受限 Token 保留在不可枚举的错误 `data` 中。成功响应 body 与错误响应 body/header 的 `trace_id` 只接受标准小写 UUID；不可信候选不会透传，错误路径只会降级到另一个安全候选或空字符串，且不得采用与受限 Token 相同的 UUID 形态值。聚焦 API 测试 28 项、前端全量 230 项、typecheck 与无落盘 build 均通过，独立审查未发现 Critical/High/Medium 问题；这仍是请求层离线证据，不代表真实认证 API、浏览器业务链或 AC 通过。

`FE-002` 仍为 `partial`，且新增 `GAP-067` 跟踪 UI-002 数据来源缺口：页面要求五角色工作台、最近任务和当前用户失败 Job，并禁止前端全量拉取模拟，但 AUDIT-001 排除 `system_admin` 且未冻结五角色摘要，OPS-001 只能查询已知 `job_id`，正式 API 没有权限裁剪的 Job/工作台摘要发现入口。合同裁决前不得枚举 Job ID、编造 Mock DTO 或用孤立状态组件冒充工作台完成。

`BASE-004` 的 P0 追踪状态仍为 `partial`：严格 Settings、`provider_calls_enabled=false` 的 Policy、固定本地资源 loader、approval pin 与 Settings/Policy cross-binding 已接入 Backend/Worker 的 pre-construction 路径；合成 Settings → 本地 Policy/resources → loader/pin/cross-binding → FastAPI/Celery object → 进程内 `/health` 的最小启动链已有局部离线运行证据。`CR-011-R5/R6` 已 9/9 批准并完成 Gate B 同步，但 R6 Gate C 的 exact locked-subject evidence 仍 `BLOCKED BEFORE RUN / NOT RUN`。上述局部证据不等于 R6 Gate C、真实依赖健康、生产启动、Provider、Worker 消费、业务 API 或 AC 通过。

`BASE-006` 已完成不依赖业务表的首个离线切片：严格的 `job_id + event_schema_version` 消息、七个精确到 `execute_job` 的确定性 Celery 队列路由、未知 task 失败关闭、`task_publish_retry=false`、JSON/UTC、late ack、Worker 丢失重投和禁用 Result Backend 事实语义。应用层新增延迟连接的 PostgreSQL Engine/Session 工厂，复用 Settings 的 DSN 校验、连接池参数、隐藏 SQL 参数和 10 秒连接超时，并保留由 Application Service 显式控制事务；这只是通用运行时基础，尚未接入 Repository 或业务服务。Job/Step/Outbox 空表 DDL/ORM 已由 `BASE-005` 交付，但当前授权不包含 Repository、Task、Dispatcher、Lease、Redis/Broker/Worker 集成、真实 Job 或崩溃恢复运行时，因此 `BASE-006` 仍为 `partial`。

`CON-003` 新增补充协议有效字段的纯领域投影：先校验同一协议的状态、确认状态和生效日一致，只有协议内全部变更均已确认且在 `baseline_date` 已生效时才整组按日期确定性回放，避免单个协议被部分应用。原合同字段与有效字段保持分离，嵌套字段值递归冻结，并返回逐字段来源及实际采用的协议 ID；输出边界可生成与内部事实隔离且可由 Pydantic 序列化的新 `dict/list`。输入顺序不影响结果；同协议重复字段违反现有唯一约束时失败关闭，同字段同日跨协议因没有冻结赢家规则也失败关闭。字段值在顶层或嵌套容器中出现 `Decimal("NaN")`、`Decimal("sNaN")`、`Decimal("Infinity")` 或 `Decimal("-Infinity")` 时均失败关闭；有限 Decimal 保持原值并可安全物化。当前 `contract_effectivity` 聚焦测试为 52 项。该切片不访问数据库或 API，不实现确认状态机、过期传播、审核快照或页面链路，因此 `CON-003`、AC-004 和所有 runtime 状态仍为 `partial / NOT_RUN`。

`FILE-001` 当前完成 `PARTIAL / S1-S4`：除四种上传意图 Schema 外，已离线验证文件精确字节大小/SHA-256、批量数量、扩展名/声明 MIME/检测 MIME/Magic Bytes 一致性，以及 DOCX EOCD、中央目录、核心 OOXML 与解压资源边界。`measure_upload_stream` 对无 chunk、单个空 chunk 和多个空 chunk 均复用 400 `FILE_SIGNATURE_MISMATCH` 失败关闭，落实 `files.size_bytes > 0`；FILE 六文件聚焦套件 135 项通过。知识库存在性/组织/active 状态、multipart Form/API、持久化去重与行锁、Scanner/MinIO、Job/Worker 和运行时链路仍未实现；严格布尔字段的 multipart 文本解析留待获批 Form Router 边界处理。

`FILE-002` 当前仅完成 `PARTIAL / S1`：后端提供精确六态安全扫描 Enum，并以纯函数保证只有经过校验的 `clean` 枚举实例允许进入解析；旧 `error`、未知值、裸字符串和错误类型失败关闭。Scanner、状态转换、错误码映射、数据库、Job/Worker、网络与 production 扫描均未实现。

`AUD-003` 当前完成 `PARTIAL / S1-S9`：RULE-001～RULE-015 的 15 条纯谓词均已有严格类型、缺失事实、适用性和关键边界单测；其中重复身份、主体完整性、检索结果、名称/税务身份等输入仍是调用方预计算或规范化事实。GAP-066 已确认规则输入 Schema、实现键/代码哈希、整批发布和 RULE-001 多版本投影在 Request 中不唯一；未批准的 CR-016-R1 已形成可评审推荐，但不能替代 Request 同步或 `BASE-005、AUD-002` 前置。registry/publisher、执行器、聚合、持久化、风险生成和 AC-007 运行链路均未实现，因此不能把纯谓词覆盖或 CR 快照表述为 `AUD-003`/AC 已完成。

`AUD-005` 的纯风险汇总输入已与 Request 的 UUID 合同对齐：`risk_id` 只接受精确 `UUID`，非 UUID 与 UUID 子类均失败关闭；`REP-003` 的文本单元格保护覆盖 `= + - @` 以及 TAB/CR/LF 七类公式前缀并保持幂等。风险汇总与表格安全聚焦套件合计 54 项通过；数据库、风险生成、真实 XLSX writer、下载链、浏览器与 AC 仍为 `NOT_RUN`。

`TEST-001` 当前仅完成 `PARTIAL / S1-S9`：测试策略、86 个 P0 任务的精确追踪矩阵、39 条合成 JSON fixture、14 个确定性 PDF/DOCX/PNG/JPEG fixture、生成器及离线正/负向资产校验。当前矩阵计数为 `2 implemented / 31 partial / 53 planned`。S9 已对当前 `20260807_009` / 18/57 表在一次性 PostgreSQL 16.14 容器连续两轮取得 71/71，输出 `POSTGRESQL_CURRENT_HEAD=PASS` 且最终 0 残留；历史 007/13 与 008/15 表只保留为旧 head 证据。该结果只升级 009 storage-schema Gate，不升级 `TEST-001`、`BASE-005`、`AUTH-005` 或业务 runtime。Docker/Compose 全栈、Repository/Service/API/Worker、真实 ACL/数据、浏览器 E2E、Provider、远程分支保护、部署、production 与业务 AC 仍为 `NOT_RUN` 或 `NOT_AUTHORIZED`。

`AI-001` 当前仅完成 `PARTIAL / S1-S10`：provider-neutral 的 LLM/Embedding Adapter Protocol、不可变调用契约、调用方注入的无默认值 Transport Policy、按显式 `ModelTarget` 精确调用一次注入式 Adapter 的 Gateway、六类 P0 调用到主/备候选的只读纯配置映射，以及版本化 `PricingProfile` 的纯整数 `micro_usd` 单请求计费。S8 增加无默认值的不可变 `BudgetProfile`、下一物理请求的最坏 Token/费用预检和 Provider usage/价格版本对账；预留只计算结果，不修改或释放共享预算。S9 增加 `provider_calls_enabled=false` 的严格不可变 pre-hash Policy payload、CR-002 初始 Profile/operation/retry/breaker/rate/outbound 值校验和 `.env.example` 映射；校验错误不回显原始输入，Policy JSON 拒绝重复 key 与布尔/整数混用，外部计费 Profile 强制 HTTPS。S10 以纯函数把 RAG 映射到 `rag`、合同/发票/风险/报告映射到 `async_generation`、Embedding 映射到 `embedding` 三个独立限流池，裸字符串或未知类型失败关闭；它不实现 Redis 计数或运行时限流。preflight 已显式保留未来 model-repair 请求格数，错误合同补齐 `invalid_response/content_rejected/provider_configuration_error/output_truncated` 及批准的 5xx retry 语义。LLM 请求把必填 `system_instruction` 与 `user_content` 分离；Embedding 请求和结果使用有序、不可变的非空批次，Gateway 校验返回向量数与输入数一致。合同、发票、风险解释和 RAG 缺失显式备用模型时配置失败；报告草稿是否携带备用候选必须显式配置，Embedding 始终只有一个候选。Gateway 会校验 Outcome、Trace ID、成功目标、结果字段类型和有序有限数值序列，并把 Embedding 向量复制为不可变 tuple；未知 Adapter、网关契约错误及未规范化 Adapter 异常均替换为只含固定消息与 `trace_id`、不保留原始异常链或查找上下文的脱敏错误。外部 USD 费用按每个物理请求分别向上取整，内部不计费目标必须显式使用零价；预算、计费和限流池选择函数不执行数据库、Redis、网络或睡眠。`CR-002-R4` 与 `CR-011-R4` 的 contract 均已批准并同步；Fake Sink 在 completed/late_completion 记录或签发 permit 前复用完整事件链校验，跨事件字段不一致返回 `CONFLICT`，且不记录冲突事件、不签发 permit。当前 events 47 项与 sink 22 项合计 69 项；Gate B Stage1 已以 275/275、negative runner `PASS`、zero-socket attempts=0 验证严格 parser/companion/resolver、retry、response boundary、network policy、`AiCallEventV1` DTO/JCS/hash/replay 与 Fake Sink 行为，完整 Gate B 又以 Node selftest `PASS`、27/27、negative vectors 25/25、Schema calls 20+20、engines=2/2、zero-socket attempts=0 与 anti-forgery 11/11 通过。该证据仍不包含 durable reserve、数据库/Outbox、并发锁、真实 deadline/HTTP Adapter、Provider 或 Gate C persistent runtime，因此 `AI-001` 与 GAP-057～062 均保持 `partial/open`。当前固定 `AI_PROVIDER_CALLS_ENABLED=false`，只允许不打开 socket 的离线 Mock；`fixed_test_provider` 与 `production` 仍为 `PENDING`，不得发起 Provider 网络调用或 production 放行。

`AI-002` 当前为 `partial`，新增结构化输出离线 repair orchestration：本地清理与严格 Pydantic 校验失败后，最多对同一实际目标修复两次；repair 请求只携带安全 JSON Pointer/类别，不携带失败值或 Provider 原文，并共享 attempts、Token、费用和 hard deadline。候选结果必须通过完整业务/权限/引用 validator；validator 只接收 `deep=True` 的 `model_copy`，既不能原地篡改最终采用对象，其返回值也被忽略。coroutine、同步 generator 或 async-generator validator 在 initial/repaired 两条采用路径都失败关闭，validator 主体不执行，固定映射为 `INTERNAL_ERROR` 且不保留 cause/context。仅精确的 `CitationValidationError/RiskExplanationValidationError` 原样透传；其他未知 validator 异常同样固定映射为 `INTERNAL_ERROR`，repair 调用异常固定映射为 `MODEL_UNAVAILABLE`。structured output 46 项与 structured repair 56 项合计 102 项通过；四个 AI 测试文件合计 241 项（46 + 56 + 25 + 114），这是另一个汇总口径。Provider、数据库、Redis、持久化 EventSink、业务 Schema/Service/API、真实网络和 AC 仍为 `NOT_RUN`，因此这不是实际提取或业务链路完成证据。

2026-08-12 最近一次完整 `verify-local-offline` accepted-source 质量 checkpoint 为 Backend `1816 passed / 54 skipped`（另有 1 条 Starlette 弃用警告）、Ruff check/format 对精确范围 `app + alembic/versions + tests` 通过（140 files）、mypy 77 sources 与 pip check 通过，以及 Frontend typecheck、6 files/230 Vitest、Vite 8.2.0 write-false build（119 modules）通过。该全量运行已纳入当前 52 项 `CON-003` 聚焦套件、54 项 risk/spreadsheet 聚焦套件、28 项 ApiClient 聚焦套件和 FILE 六文件 135 项聚焦套件的新增边界。离线编排器固定只调用上述三个 Ruff accepted-source scope；`backend/alembic/recovery` 匹配 0 个 accepted files，明确为 `NOT_APPLICABLE`。其 9000-byte verifier 身份固定为 SHA-256 `455ba2ea80534d594dabce6869bc8bf441892ac3f36414783d1c47df90a94f43`，负向自测封堵动态 scope 增宽、额外 Ruff 调用和伪造失败原因。本轮另行显式在 PostgreSQL 16.14（`server_version_num=160014`）对唯一 head `20260807_009` 连续两轮通过 71/71，并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，专用标签容器最终 0 残留；这是独立历史证据，默认离线门禁本身仍未运行 PostgreSQL current-head，Docker/Compose、浏览器 E2E、Provider、远程、production 与所有 AC 也均为 `NOT_RUN`。真实业务 API/Worker/ACL/数据仍未运行。本轮还加固了 Pydantic 校验脱敏边界：固定 `FinAuditValidation` title/type/message，只保留代码 allowlist 的顶层 field location，丢弃 input/ctx/动态 location，并清除 cause/context；ValueError、自定义 PydanticCustomError、恶意 title 与动态 extra key 回归覆盖，聚焦 144 项及独立终审均 PASS。

旧实施计划把 P0 拆成 86 个工作包并估算约 561 人日；这些数字只作历史规划参考，不再冻结任务形态。当前实施顺序以最短可运行纵向链路和实际依赖为准，P1/P2 不得成为 P0 验收前置条件。

## 规格入口

[Request 开发规格入口](Request/README.md) 是日常开发起点。[产品需求](Request/PRODUCT_REQUIREMENTS.md)、[技术规格](Request/TECHNICAL_SPEC.md) 和[实施计划](Request/IMPLEMENTATION_PLAN.md) 分别回答“做什么”“按什么边界做”和“下一步做哪一刀”。旧版九份文档已移入 `Request/archive/legacy-v1/`，仅供追溯。

日常开发只核对当前切片、相关产品结果、当前模块的机器事实来源和对应验收。已识别的问题和迁移依据保留在[规格体系审计与简化方案](docs/specification-simplification.md)，不作为实现前置。

只有改变范围、外部兼容性、持久化语义、状态/权限/安全边界或验收阈值时才需要简短 CR。未批准 CR/DEP 不因自身声明成为开发前置；它指出的问题必须能从当前活跃基线独立复现，并只阻断受影响的最小切片。

## 目录

```text
backend/   FastAPI 模块化单体与 Celery Worker
frontend/  Vue 3 + TypeScript 前端
infra/     Docker Compose、Nginx 与数据服务配置
docs/      开发流程、基线清单和长期工程文档
scripts/   可重复执行的开发、验证和运维脚本
Request/   四份活跃开发规格；旧版九份文档只在 archive 中追溯
Demo/      静态 UI 原型，仅作视觉与信息结构参考
```

基线 secret 门禁覆盖 `.env.example`、`Request/`、`Demo/` 以及常见 `.pem/.key` 私钥文件；隔离负例只输出命中文件路径，不回显匹配内容。

## 开发前置

- Git 2.55+
- Python 3.10（项目基线；不要使用系统 Python 3.14 生成锁定结果）
- Node.js 20.19+（或 Vite 8 支持的更高 LTS 版本）
- Docker Desktop 与 Docker Compose

首次使用仓库时运行一次本地治理初始化；该命令可重复执行，也可在尚未执行 `git init` 的项目副本中使用：

```powershell
.\scripts\setup-git-governance.ps1
```

仓库基线验证：

```powershell
git status --short --branch
git config --local --get commit.template
git config --local --get core.hooksPath
.\scripts\verify-baseline.ps1
.\scripts\test-verify-git-governance.ps1
.\scripts\verify-baseline.ps1
.\scripts\test-verify-baseline.ps1
```

Backend 质量门禁（目标版本 Python 3.10）：

```powershell
Set-Location .\backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check app alembic/versions tests
.\.venv\Scripts\python.exe -m ruff format --check app alembic/versions tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

数据库迁移只读取当前进程的 `DATABASE_URL`，不会自动加载 `.env`，也不会随应用启动自动执行。由受信任的发布环境注入 DSN 后，可执行：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
```

当前首个 revision 只启用 `pgcrypto`、`btree_gist` 和 `citext`，降级会回退 revision 但保留可能由同库其他对象共享的扩展。完整范围、安全门控、测试目标限制和停止边界见 [数据库迁移运行手册](docs/database-migrations.md)。

`TEST-001-S1-S9` 测试资产、本地离线质量编排和显式 PostgreSQL 16 current-head 门禁的边界、数据目录及追踪矩阵见 [测试策略](docs/testing/test-strategy.md)、[测试数据目录](docs/testing/test-data-catalog.md) 与 [P0 追踪矩阵](docs/testing/p0-traceability-matrix.csv)。生成器的 `python` 必须为 `scripts/requirements-test-assets.txt` 记录的 Python 3.12.13；默认离线校验命令：

```powershell
python scripts/generate_test_documents.py --check
.\scripts\verify-test-assets.ps1
.\scripts\test-verify-test-assets.ps1
.\scripts\test-verify-local-offline.ps1
.\scripts\verify-local-offline.ps1
```

已由操作者启动 Docker 且本机预先缓存 `postgres:16-alpine` 时，显式 S9 门禁为：

```powershell
.\scripts\test-verify-postgresql-current-head.ps1
.\scripts\verify-postgresql-current-head.ps1
```

默认离线命令成功只证明固定资产可逐字节复现，且结构、P0 任务集合、AC 覆盖、fixture 路径/大小/哈希、最低文件包络和 JSON 敏感内容门禁自洽，不替代 PDF/DOCX 业务解析、OCR、数据库、API、Worker、浏览器、模型或环境重建验证。显式 S9 已通过当前 `20260807_009` / 18 表 PostgreSQL 16 storage-schema Gate；它不证明剩余 39 表、Compose、业务 Repository/Service/API/Worker、真实 ACL/数据、Provider、浏览器、部署、production 或 AC。

`AI-001-S1-S10` 的离线契约、Gateway、纯路由/限流池映射、整数计费、预算预检和 pre-hash Policy 测试不访问网络或真实模型：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests\unit\test_ai_gateway_contract.py tests\unit\test_ai_gateway.py tests\unit\test_ai_routing.py tests\unit\test_ai_pricing.py tests\unit\test_ai_policy.py -q
.\.venv\Scripts\python.exe -m pytest tests\unit\test_ai_structured_output.py tests\unit\test_ai_structured_repair.py -q
```

该测试只验证 Adapter 可替换性、显式单次分派、Trace ID/目标传播、错误分类、脱敏边界、六类 P0 调用的候选/限流池纯映射、整数计费、预算纯计算和 Provider 默认关闭的 pre-hash Policy。已批准 CR-011 的独立 contract/offline 门禁为：

```powershell
.\scripts\test-verify-cr011-gate-b-stage1.ps1
.\scripts\verify-cr011-gate-b-stage1.ps1
```

Stage1 命令仍只证明 275/275 项纯 parser/companion/resolver/retry/response/network/Event/Fake Sink 行为（含完整事件链冲突失败关闭）、zero-socket attempts=0 和 runner 负向防伪；其 scoped BLOCKED marker 防止 Stage1 自身冒充完整 Gate。完整 Gate B 使用 test-only 精确锁与隔离物化依赖，必须显式运行，不纳入默认 `verify-local-offline.ps1`：

```powershell
.\scripts\materialize-cr011-gate-b-dependencies.ps1
.\scripts\test-verify-cr011-gate-b.ps1
.\scripts\verify-cr011-gate-b.ps1
```

2026-08-10 的完整 Gate B 证据为 Node selftest `PASS`、27/27（2 个正向 + 25 个负向）、negative vectors 25/25、Python/Node Schema calls 20+20、engines=2/2、zero-socket guard `PASS`/attempts=0 和 anti-forgery 11/11。依赖获取不属于 Gate；正式 Gate 只消费已锁定、已隔离物化的测试依赖。该 PASS 仍不证明真实 Provider 可达/鉴权/生成、持久预算预留、自动 fallback、数据库、Outbox、Worker 或生产降级可用。

[`infra/env/.env.example`](infra/env/.env.example) 是 Backend/Worker 与基础设施的变量清单，包含故意不可运行的安全占位符。运行服务前必须通过进程环境或 Secret 机制注入实际配置；不得把本地 `.env` 提交到仓库。`GAP-008` 关闭前，Qdrant Collection 名称必须显式提供，代码不会替冲突中的设计作默认裁决。

Frontend 质量门禁与本地预览：

```powershell
Set-Location .\frontend
npm ci
Copy-Item .env.example .env.local
npm run typecheck
npm test -- --run
npm run build
npm run dev
```

Frontend 当前使用 Mock 登录与专用静态演示页，仅用于验证路由、角色拦截、通用布局和请求层契约；不代表业务 API 已实现。

基础请求层固定访问同源 `/api/v1`，既接受客户端相对路径，也接受 Backend 返回的完整 `/api/v1/...` 站内路径，并拒绝外部基址、路径遍历和编码路径分隔符；仅精确 `POST /api/v1/auth/login` 的 403 强制换密错误会校验并以不可枚举属性保留受限 `data`，供唯一允许的换密流程使用。匿名登录的普通 401 不会误触发已有会话清理，HTTP 204 仅由显式 no-content 调用接受。Backend 的 422 运行时响应与 OpenAPI 均使用统一 `ErrorResponse`，`/health` 提供中文 OpenAPI 摘要和合成响应示例，`APP_ENV=prod` 时关闭 OpenAPI 与交互文档入口。PostgreSQL 配置拒绝可覆盖连接目标的 libpq query 参数，分块重叠必须小于最大长度。

## 安全边界

- 真实密钥、Token、密码、私钥和业务敏感数据不得进入 Git、日志、前端构建产物或测试夹具。
- 仅提交 `.env.example` 中的变量名和安全占位符。
- PostgreSQL 是业务事实唯一来源；Redis、Qdrant 和 Markdown/Chunk/Embedding 均不得成为唯一事实来源。
- AI 输出必须可追溯、可拒答、可人工复核；不得直接决定审批、付款或确定性规则是否命中。

## 分支与提交

`.\scripts\verify-baseline.ps1` 只证明本地分支、项目根、Git 配置和基线文件门禁；即使通过也仍输出 `BASELINE_TASK_STATUS=PARTIAL`，不能替代远程保护证据。

采用 `main`、`develop`、`feature/*`、`release/*`、`hotfix/*` 模型；远程分支保护需在仓库托管平台创建后配置。提交使用 Conventional Commits，`setup-git-governance.ps1` 会设置 `.gitmessage` 和 `.githooks/commit-msg`；Git 自动生成的 merge、revert、fixup、squash 和 amend 主题保持可用。发布标签使用 `vMAJOR.MINOR.PATCH`，创建前运行 `.\scripts\verify-git-governance.ps1 -VersionTag 'v0.1.0'`。详见 [开发工作流](docs/development-workflow.md)。
