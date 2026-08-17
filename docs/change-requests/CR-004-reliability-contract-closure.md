# CR-004-R1：Job 与 Outbox 可靠性合同闭合

文档类型：合同候选；可变生命周期状态只记录在第 6 节。

日期：2026-08-07

## 1. 变更原因

`CR-001-R2` 已批准可恢复 Job、追加写步骤和最小 Broker 消息，`CR-002-R4` 已批准 AI 调用 reserve/complete、顺序投影和 `outcome_unknown/late_completion` 原则。准备创建 Job、Step 与 Outbox 迁移时，仍有三个无法由当前 Request 唯一实现的缺口：

1. `GAP-040`：架构仍要求 `async_jobs.retryable/idempotency_key`，数据库却只定义 `idempotency_record_id`，存在重复事实风险。
2. `GAP-041`：`async_job_steps.status` 没有枚举，`running` 步骤如何且只能一次进入终态、哪些字段可随之更新均未冻结。
3. `GAP-042`：Broker 与 Outbox 的版本映射、Job 消息载荷、AI 迟到完成事件、Outbox 投递更新白名单和含数据降级策略均未冻结。

本 CR 推荐在不增加 P0 物理表、不扩大 Provider 权限且不修改已批准 CR-001/002 业务边界的前提下关闭这些缺口。在首次 snapshot 与全部必需签署完成前，不能据此修改 Request、创建迁移或实现运行时代码。

## 2. 推荐决策

### REL-D-001：Job 不保存重复的可重试与幂等事实

- 不在 `async_jobs` 新增 `retryable` 或 `idempotency_key` 列。
- 幂等键的唯一事实来源保持为 `idempotency_records.idempotency_key`；Job 只通过现有 `idempotency_record_id` 外键关联。内部系统 Job 不需要 API 幂等记录时，该外键可空。
- 对外展示或重试入口使用的 `retryable` 是只读派生值，固定为同时满足：`status='failed'`、`attempt_no < max_attempts`、`next_retry_at IS NOT NULL AND next_retry_at <= database_now`、`job_type + input_schema_version` 存在于 Job 冻结 version/hash 对应的只读 Worker Handler Registry、`error_code` 非空且属于下述固定白名单、`retry_policy_version/hash` 是当前实现支持的精确配对。空值、未知错误码、未注册 Handler、未知 Policy、错误 hash 或非小写 64 位十六进制 hash 一律派生为 `false`。OPS-001 响应和页面 Job 模型必须显式增加该只读字段，不得由前端根据错误文案推断。
- 首版唯一错误码字典标识为 `job-retry-policy-v1`，其 RFC 8785 规范化 JSON 固定为 `{"retryable_error_codes":["DATABASE_TRANSIENT","DEPENDENCY_TIMEOUT","DEPENDENCY_UNAVAILABLE","RATE_LIMITED","STORAGE_TRANSIENT","WORKER_LOST"],"version":"job-retry-policy-v1"}`，SHA-256 固定为 `9cdb2a30bba1e39155adcb3bcb55fe6465811b63290d249ccbfac4f976cdbba7`。所有已注册 P0 Handler 使用同一闭合集合；不适用的代码不会由该 Handler 产生，未知代码失败关闭。`LEASE_EXPIRED` 只进入下述 Lease 恢复路径，不属于失败 Job 的用户重试码。`async_jobs` 新增 `retry_policy_version VARCHAR(50) NOT NULL` 和 `retry_policy_hash CHAR(64) NOT NULL` 两列，在创建时冻结；业务 `input_json/input_hash` 不含这两个技术字段，策略升级不会改变活动 Job 唯一键或产生第二个业务 Job。不得通过环境变量、自由文本或 Handler 私有映射临时扩展。
- Worker Handler Registry 是 Job 类型、输入 Schema 和阶段顺序的唯一上游门禁，而不是 Worker 内部常量。Registry 机器制品的顶层必须且只能包含 `registry_version/handlers`；`handlers` 必须为非空数组，每个 handler 必须且只能包含 `job_type/input_schema_version/input_schema_id/input_schema_sha256/handler_code_version/steps`；`steps` 是非空数组，每项必须且只能包含 `step_code`。`input_schema_id` 是 1～160 位 ASCII 不可变制品标识并匹配 `^[a-z][a-z0-9._-]*$`，`input_schema_sha256` 是该 Job 输入 JSON Schema 原始无 BOM UTF-8 bytes 的 SHA-256 小写 64 位十六进制。机器 Registry JSON Schema 必须对每层设置 `additionalProperties=false`，Registry Loader 必须在任何 Schema 校验前拒绝 JSON 重复键；`input_schema_version` 必须为正整数；`registry_version/handler_code_version` 必须为 1～80 位 ASCII 且匹配 `^[a-z0-9][a-z0-9._-]*$`，`job_type` 必须为 1～60 位 ASCII 且匹配 `^[a-z][a-z0-9_]*$`，`step_code` 必须为 1～80 位 ASCII 且匹配同一规则。`handlers` 按 `job_type` 的 UTF-8 bytes 升序、再按 `input_schema_version` 数值升序，且 `(job_type,input_schema_version)` 全局唯一；同一 `input_schema_id` 只能对应一个 hash；`steps` 的数组顺序就是执行顺序，同一 handler 内 `step_code` 唯一，不得另外排序。Registry 实例通过 Registry Schema 后对 RFC 8785 规范化 bytes 计算 SHA-256 小写十六进制 hash；同一 `registry_version` 只允许对应一个 hash，二者共同识别不可变快照。Registry Schema 自身也必须作为不可变机器制品独立记录 `registry_schema_version + registry_schema_sha256`，其 hash 对原始无 BOM UTF-8 bytes 计算。批准包必须一次性绑定 Registry version/hash、Registry Schema version/hash，以及每个 handler 引用的输入 Schema ID/hash 与原始 bytes；缺少、hash 不匹配、未知或额外输入 Schema 均失败关闭，不允许使用私有映射或“当前版”。
- `async_jobs` 增加 `handler_registry_version VARCHAR(80) NOT NULL` 与 `handler_registry_hash CHAR(64) NOT NULL`，创建时冻结。API Job 创建、输入校验、`retryable` 派生、重试、Worker claim、阶段推进和 Worker 审计动作生成必须经过同一个只读 Registry Loader，精确加载 Job 冻结的 Registry version/hash、其批准包绑定的 Registry Schema version/hash，以及命中 handler 的输入 Schema ID/hash；随后只用该获批输入 Schema 校验精确 `input_json`，禁止从环境变量、路由表、私有字典或“当前默认版”绕过。已发布的 Registry、Registry Schema、输入 Schema 与绑定记录只能追加，只要任一 Job/Step/Outbox 或法定审计保留证据仍引用该 version/hash，就不得删除或原地覆盖。本 CR 只冻结 Registry 元合同，不猜测任何具体 Handler 值；首个 Registry 实例、Registry Schema、每个输入 Schema 的原始 bytes、各自身份/hash 与绑定记录仍待单独产出并批准。在该制品批准前，任何需写入、读取或校验 Handler 的 migration 与 runtime 均硬阻塞。
- Job Lease 使用唯一 Profile `job-lease-v1`，其 RFC 8785 规范化 JSON 固定为 `{"heartbeat_interval_seconds":15,"lease_ttl_seconds":60,"recovery_grace_seconds":15,"version":"job-lease-v1"}`，SHA-256 固定为 `50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00`；任何参数变化发布新版本。`async_jobs` 相应新增 `lease_policy_version VARCHAR(50) NOT NULL` 与 `lease_policy_hash CHAR(64) NOT NULL`，创建时冻结，且与 retry Policy 一样不进入业务 `input_json/input_hash`。`status IN ('running','cancel_requested')` 时 `worker_id/lease_owner/lease_expires_at/heartbeat_at/started_at` 必须全部非空，且 `started_at <= heartbeat_at < lease_expires_at`；其他状态的四个 worker/lease 字段必须全部为空。`lease_owner` 是每次 claim 生成的不可复用随机 token，不是可复用 worker 名称；未知版本/hash 的 Job 不允许 claim、heartbeat 或恢复。
- 普通 Job 状态闭集固定为 `queued/running/cancel_requested/succeeded/failed/cancelled`。初始插入只能为 `queued`，且 `attempt_no=0`、`max_attempts>=1`、`row_version=1`，`stage/next_retry_at/worker_id/started_at/finished_at/error_code/error_message/lease_owner/lease_expires_at/heartbeat_at` 全部为空，同时冻结 input、Handler Registry、retry Policy 和 lease Policy 的 version/hash。普通 Job 的唯一允许转换是 `queued -> running`、`queued -> cancelled`、下述仅由 dispatch dead-letter finalizer 执行的 `queued -> failed`、`running -> succeeded|failed|cancel_requested`、`cancel_requested -> cancelled` 与符合重试门禁的 `failed -> queued`。`running -> running` 只表示 heartbeat、同 attempt 阶段推进或下述 Lease recovery，`cancel_requested -> cancel_requested` 只允许 heartbeat；二者都是受 CAS 保护的同状态更新，不是额外转换边。未显式列出的边全部禁止，尤其禁止普通业务或 Worker 直接执行 `queued -> succeeded|failed`、`running -> queued|cancelled`、`cancel_requested -> running|succeeded|failed`、任何终态回到 `running`、`failed -> succeeded|cancelled` 以及 `succeeded/cancelled` 的任何后续变更。

| Job 状态 | `started_at` | `finished_at` | `stage` | `error_code` | `error_message` | `next_retry_at` | Worker/Lease 四字段 |
|---|---|---|---|---|---|---|---|
| `queued` | 空 | 空 | 空 | 空 | 空 | 空 | 全空 |
| `running` | 非空 | 空 | 非空，等于当前 running Step | 空 | 空 | 空 | 全部非空 |
| `cancel_requested` | 非空 | 空 | 非空，等于当前 running Step | 空 | 空 | 空 | 全部非空 |
| `succeeded` | 非空 | 非空且不早于开始 | 保留最后 Step 代码 | 空 | 空 | 空 | 全空 |
| `failed` | pre-claim dispatch 失败时为空；执行失败时非空 | 非空；执行失败时不早于开始 | pre-claim dispatch 失败时为空；否则保留失败 Step 代码 | 非空稳定安全码；pre-claim 只允许 `JOB_DISPATCH_FAILED/JOB_DISPATCH_OUTCOME_UNKNOWN` | 可空；非空时只能是脱敏安全摘要 | 仅执行错误可重试且次数未耗尽时等于 `finished_at`，否则为空 | 全空 |
| `cancelled` | 从 queued 直接取消时为空；执行中取消时非空 | 非空，执行中取消时不早于开始 | 从 queued 直接取消时为空；否则保留取消 Step 代码 | `JOB_CANCELLED` | 空 | 空 | 全空 |

- `async_jobs` 增加 `row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0)`。任何可变写入必须为单条条件 UPDATE：至少 CAS `id + 当前 status + expected row_version`，Worker/Dispatcher 路径还必须同时 CAS 对应 fencing tuple，成功时恰好执行 `row_version=row_version+1`。对外取消与重试请求必须携带当前 `row_version`；claim 返回的 fencing tuple 扩展为 `(job_id,attempt_no,lease_owner,lease_expires_at,row_version)`，heartbeat 和阶段更新返回递增后的新版本。0 行更新必须重读权威状态，不得覆盖、降级为无条件 UPDATE 或重放已经可能发生外部副作用的操作。
- 受影响的外部合同精确限定为 `AUDIT-007/AUDIT-008/OPS-001`，接口数量不变。`AUDIT-007` 请求 Body 在既有 `retry_scope/reason` 外新增必填正整数 `row_version`；成功响应删除会误称已递增的 `attempt_no`，改为返回当前尚未递增的 `attempt_no`、`scheduled_attempt_no=attempt_no+1` 与事务提交后的新 `row_version`，并保留既有 `job_id/execution_id/status/preserved_results`。`AUDIT-008` 请求 Body 在既有 `reason` 外新增必填正整数 `row_version`；成功响应增加 `job_id` 与事务提交后的新 `row_version`，保留 `execution_id/status/cancelled_at`。两接口 CAS 0 行且非幂等重放时统一返回 409 `JOB_VERSION_CONFLICT`；同一 `Idempotency-Key` 与相同请求 hash 必须在可变状态门禁前返回首次保存的完整响应，不同 hash 仍返回 `IDEMPOTENCY_CONFLICT`。`OPS-001` Job 模型增加权威 `row_version` 与只读派生 `retryable`，前端据此发起动作；不得从 `audit_task_execution` 的版本或页面缓存代替 Job 版本。
- 在 queued 流程中，Worker claim 是 `attempt_no` 的唯一递增点：单条条件 UPDATE 要求 `status='queued' AND attempt_no < max_attempts`，同时执行 `status='running'`、`attempt_no=attempt_no+1`，把 `stage` 写为 Handler Registry 固定的首个 `step_code`，写入 `worker_id/lease_owner/started_at/heartbeat_at=数据库当前时间` 与 `lease_expires_at=当前时间+60s`，并在同一事务追加与该 stage/attempt 对应的唯一 running Step。初始 Job 从 0 变 1；失败 Job 的用户重试事务只执行 `failed -> queued`，保持 `attempt_no`，清空 `stage/started_at/finished_at/next_retry_at/error_code/error_message/worker_id/lease_owner/lease_expires_at/heartbeat_at`，并以当前值 `+1` 创建下一条 Outbox。Job、Outbox、幂等结果必须同事务提交；重试 API 返回 `scheduled_attempt_no=attempt_no+1`，不得再声称当前值已递增。下述 Lease recovery CAS 是唯一另一类获准的技术递增点，它不属于 queued claim 或用户重试。
- 每次 claim 返回 fencing tuple `(job_id, attempt_no, lease_owner, lease_expires_at, row_version)`。heartbeat 必须 CAS 当前 tuple，再写新的 `heartbeat_at/lease_expires_at/row_version`；Step 终结、Job 终结、业务结果和后续 Outbox 的事务也必须匹配最新 tuple，0 行更新统一视为 stale worker，旧 Worker 不得提交任何业务或审计终态。
- Lease 恢复只在数据库当前时间 `>= lease_expires_at + 15s` 时发生。若 `attempt_no < max_attempts`，恢复事务用旧 fencing tuple 做 CAS，先把旧 running Step 固定更新为 `status='failed'`、`error_code='LEASE_EXPIRED'`、`finished_at=数据库当前时间`，再执行 `attempt_no=attempt_no+1`，生成新的不可复用 `lease_owner`，写入新的 `worker_id`，把 `started_at/heartbeat_at` 同时重置为数据库当前时间、把 `lease_expires_at` 重置为当前时间加 60 秒，把 `stage` 重置为冻结 Handler Registry 的首个 `step_code`，并追加与新 attempt 对应的该 running Step；不经过 failed/queued 用户重试路径。若 `attempt_no = max_attempts`，同一 CAS 事务把旧 Step 固定终结为 `status='failed'`、`finished_at=数据库当前时间`、`error_code='WORKER_LOST'`，并把 Job 置为 `failed`、写入相同 `finished_at/error_code`、`next_retry_at=NULL`，清空所有 Lease 字段，不再派发。Lease 恢复不得被伪装成用户重试。
- 同一业务 Job 的所有重试/恢复继续沿用原 `job_id`；不得因缺少重复列而创建第二个 Job，也不得从自由文本错误消息推断可重试性。
- 取消语义固定为：queued Job 在当前计划 attempt 尚未 claim、没有当前 attempt Step/Lease 时可由取消事务直接 `queued -> cancelled`；可以保留以前 attempt 的终态 Step，但必须写 `finished_at`、`error_code='JOB_CANCELLED'`且不创建新 Step。running Job 只能用当前行版本执行 `running -> cancel_requested`，必须保留原 fencing tuple、Lease、stage 和唯一 running Step。`cancel_requested` 允许同一 Worker 继续 heartbeat，但禁止开始下一阶段、写新的业务结果或 Outbox；Worker 在安全检查点用当前 fencing tuple 同事务把 Step `running -> cancelled`、`error_code='JOB_CANCELLED'`、`finished_at=database_now`，把 Job `cancel_requested -> cancelled`、写 `finished_at/error_code='JOB_CANCELLED'` 并清空 worker/Lease 字段。若 cancel_requested 的 Lease 在 grace 后过期，回收器用旧 tuple 执行同一取消终态，不递增 attempt、不恢复业务执行、不创建新 Step。终态提交与取消请求并发时只有匹配当前 status 与 fencing 的一个 CAS 能成功，失败方读取权威终态，不覆盖结果。

### REL-D-002：Step 只允许一次 `running` 到终态转换

- `async_job_steps.status` 枚举固定为 `running/succeeded/failed/cancelled/skipped`。
- 新记录只能以 `running` 插入，`started_at` 必填，`finished_at/error_code` 为空。允许的唯一状态变化为一次 `running -> succeeded|failed|cancelled|skipped`；终态记录禁止再次 UPDATE，所有记录禁止 DELETE。
- 终态转换必须在一个语句内设置 `finished_at`，且 `finished_at >= started_at`。`failed` 必须写非空的稳定安全 `error_code`；`succeeded` 必须保持 `error_code` 为空；`cancelled` 固定写 `JOB_CANCELLED`，`skipped` 固定写 `STEP_SKIPPED`，不允许自由文本原因。
- 该唯一终态 UPDATE 的字段白名单固定为 `status/finished_at/summary_json/error_code`。`id/job_id/step_seq/step_code/attempt_no/started_at/trace_id` 及其他身份字段全部不可变；`summary_json` 仍只允许脱敏、Schema 校验后的结构化摘要。
- 触发器使用白名单比较实际变化字段；不能通过“除某些字段外均可修改”的黑名单或空 UPDATE 绕过。崩溃恢复必须先把旧 `running` 步骤安全终结，再为下一次尝试追加新记录，禁止覆盖旧尝试。
- P0 Handler 阶段严格串行：建立 `UNIQUE(job_id, attempt_no) WHERE status='running'` 部分唯一索引。可延迟约束触发器在事务提交时要求每个 `async_jobs.status IN ('running','cancel_requested')` 的当前 attempt 恰有一条 running Step 且 `async_jobs.stage = async_job_steps.step_code`，其他 Job 状态不得留有 running Step。正常阶段推进必须在匹配 Job fencing tuple 的同一事务中终结当前 Step、追加下一 Step 并更新 `Job.stage`；最终阶段必须在同一事务终结 Step 和 Job；cancel_requested 只允许上条取消终结。不得出现两个并行 running Step，或“旧 Step 已终结而下一 Step/Job 终态尚未提交”的可见间隙，Lease recovery/取消回收因而总能唯一定位旧 running Step。
- 每个 attempt 的 Step 必须与 Job 冻结 Handler Registry 完全一致：`step_seq` 是该 handler `steps` 数组的 1-based 位置，`step_code` 逐字等于该位置的值，禁止未注册、跳序或重复阶段。阶段推进时当前 Step 只能终结为 `succeeded|skipped`并追加下一个 running Step；最后一个 Step `running -> succeeded` 必须与 Job `running -> succeeded`同事务，两者共用同一 `finished_at`且均无错误码。任何 Step `running -> failed` 必须与 Job `running -> failed`同事务，两者共用同一 `finished_at/error_code`，Job 仅可额外保存脱敏 `error_message`；若错误可重试且次数未耗尽，同时写 `next_retry_at=finished_at`，否则写空。从执行中取消时，当前 Step 与 Job 也必须在同一事务终结为 `cancelled`。
- 提交时一致性矩阵固定为：`queued` 不得有当前 attempt Step；`running/cancel_requested` 恰有一条当前 attempt running Step；`succeeded` 没有 running Step 且最后 Step 为 `succeeded`；执行中形成的 `failed` 没有 running Step且当前 attempt 最后 Step 为 `failed` 并与 Job 错误码一致；dispatch finalizer 在首次或重试 claim 前形成的 `failed` 不得为尚未发生的计划 attempt 伪造 Step，且只允许对应的 pre-claim 错误码；从执行中进入的 `cancelled` 没有 running Step 且最后 Step 为 `cancelled`；从尚未 claim 的 queued（包括初始排队和用户重试排队）直接取消时不得为当前计划 attempt 伪造 Step。历史 attempt 只能保留终态 Step，Job `stage` 在运行时指向唯一 running Step；终态且当次存在 Step 时保留当次最后 Step 代码，否则为空。

### REL-D-003：Outbox 版本是 Broker Schema 版本的唯一来源

- P0 Job 投递事件固定为 `aggregate_type='async_job'`、`aggregate_id=job_id`、`event_type='job.dispatch.requested'`、`event_version=1`。`event_id` 在创建 Outbox 行时生成并保持不变；同一 Outbox 行的发送重试复用该 ID。
- `payload_json` 固定只保存 `{ "job_id": "<uuid>" }`。Dispatcher 发送的 Broker JSON 固定只包含 `{ "job_id": "<uuid>", "event_schema_version": <outbox_events.event_version> }`；不在 `payload_json` 再保存第二份版本，也不携带 Job 输入、正文、凭据、尝试状态或业务结果。
- 每条 `job.dispatch.requested` 的 `event_sequence` 等于计划尝试号。初始 queued Job 的 `attempt_no=0`，故首次事件为 1；用户重试事务保持当前 `attempt_no=n` 并创建 sequence `n+1`；Worker claim 随后把 Job 递增到同一个 `n+1`。Lease 内部恢复不回到 Broker 队列、不创建 dispatch 事件，由恢复事务直接换 Lease 并递增 attempt。Broker 重发复用原 Outbox 行，不增加 sequence，也不增加 Job attempt；数据库唯一约束保持基线的 `(aggregate_type, aggregate_id, event_sequence)`，`event_type` 不进入该键，因此同一 aggregate 不可能用不同事件类型重复占用同一 sequence。`(event_id, event_type)` 继续承担事件身份去重，不替代 aggregate 全局顺序。
- Dispatcher 不得转换、猜测或默认版本；发送前发现序列化值不等于当前 Outbox 行的 `event_version` 时必须停止发送并进入失败/死信流程。Worker 收到缺失、非正整数或本进程不支持的 `event_schema_version` 时，不得修改 Job 业务状态；事件进入隔离/死信并写安全操作日志。

### REL-D-004：AI 迟到完成只追加 sequence 3 证据

- `ai.call.started` 继续使用 sequence 1；正常完成或 reconciler 判定的 `outcome_unknown` 均使用 `ai.call.completed`、sequence 2。一个物理请求只能有一个 sequence 2 事实。
- 仅当同一物理请求的权威 sequence 2 状态已是 `outcome_unknown`，之后才可追加迟到事件：`event_type='ai.call.late_completion'`、`aggregate_type='ai_call'`、`aggregate_id=<原物理请求 event_id>`、`event_id=<原物理请求 event_id>`、`event_version=1`、`event_sequence=3`。
- sequence 3 的 `payload_json` 只允许以下键：`organization_id/business_operation_id/job_id/request_id/trace_id/policy_version/policy_hash/observed_status/provider_completed_at/duration_ms/output_hash/input_tokens/output_tokens/vector_count/http_status/error_category/safe_error_code`。`policy_version/policy_hash` 必填且必须与同一物理请求 sequence 1 冻结值逐字一致；其中 `observed_status` 只允许 `succeeded/failed/degraded/rejected`，按调用类型不适用的其他可选字段必须为 `null` 或省略。
- 载荷禁止完整输入/输出、Prompt、制度 Chunk、Provider 原始响应或异常、凭据及自由文本错误。正常 sequence 2 已存在时再写 late completion、未知版本、相同身份不同载荷或错误顺序，均须隔离告警。
- 相同 sequence 3 身份与相同规范化载荷的重放为 no-op。该事件不得把 `ai_call_logs.status='outcome_unknown'` 改为成功或触发业务结果采用，只作为关联审计证据和告警事实。
- REL-D-004 只冻结可审批的 sequence 3 语义和与 Outbox 的兼容边界；具体 `AiCallEventV1` Schema、机器向量、`AiCallEventSink` 状态机、持久化投影与 runtime 都硬依赖已批准且已同步 Request 的 CR-011。CR-011 未批准、未同步或快照不兼容时，上述实现全部阻塞；不得把本节文本当作可执行 Schema 或 Sink 证据。若未来批准的 CR-011 与本节存在差异，必须先提升 CR-004 revision 并重新审批，不得由运行时自行选择。
- 批准 REL-D-004 不等于批准 AI-005，不授权创建 `ai_call_logs`、AI Outbox/投影、Worker/Sink，也不授权 Provider 网络调用或业务结果采用。

### REL-D-005：Outbox 只更新投递状态，含数据降级 fail-closed

- `aggregate_type/aggregate_id/event_id/event_type/event_version/event_sequence/payload_json/trace_id/created_at` 一经插入全部不可变。唯一允许 UPDATE 的投递字段为 `status/attempt_count/next_attempt_at/published_at/last_error`，任何其他字段变化均由数据库拒绝。
- 投递状态机固定为：`pending -> processing`；`processing -> published|failed|dead_letter`；`failed -> processing|dead_letter`。`published/dead_letter` 为终态。未显式列出的边全部禁止，终态禁止 UPDATE，所有 Outbox 记录禁止 DELETE。创建时必须为 `pending`、`attempt_count=0`、`next_attempt_at/published_at/last_error` 为空。`failed -> processing` 只在 `next_attempt_at <= database_now` 且 `attempt_count < 8` 时允许；第八次已经开始或完成的记录不得再次 claim。

| Outbox 状态 | `attempt_count` | `next_attempt_at` | `published_at` | `last_error` |
|---|---:|---|---|---|
| `pending` | `0` | 空 | 空 | 空 |
| `processing` | `1..8` | 非空，表示当前处理租约截止时间 | 空 | 空 |
| `failed` | `1..7` | 非空，表示下次可 claim 时间 | 空 | 下述可恢复安全错误码之一 |
| `published` | `1..8` | 空 | 非空 | 空 |
| `dead_letter` | `1..8` | 空 | 空 | 下述永久、耗尽或未知安全错误码之一 |

- 每次合法的 `pending|failed -> processing` 原子执行 `attempt_count = attempt_count + 1`，把 `next_attempt_at` 设置为本次处理租约截止时间，并清空 `last_error`；claim 条件必须同时包含 `attempt_count < 8`，对 `failed` 还必须包含 `next_attempt_at <= database_now`。claim 必须返回冻结的 Outbox fencing tuple `(id, attempt_count, next_attempt_at)`。`processing -> published|failed|dead_letter` 都必须 CAS `status='processing'` 及该 tuple，0 行更新表示迟到 Dispatcher，不得覆盖较新的处理尝试。成功时写 `published_at=database_now` 并清空 `next_attempt_at/last_error`；第 1～7 次可恢复发送失败写下一次允许尝试时间和固定安全错误码；永久错误、未知版本、未知错误或第 8 次失败直接进入 `dead_letter`，保持 `published_at` 为空并清空 `next_attempt_at`。
- `failed -> dead_letter` 只能由 Dispatcher 或处理租约回收器通过唯一的 Outbox dead-letter finalizer 仓储入口调用，管理员、业务 API 与普通 Worker 无权调用。该边仅用于失败关闭异常快照：必须 CAS `(id,status='failed',attempt_count,next_attempt_at)`，且同时满足下列之一：不可变事件版本已无法由受支持的 Schema 解释；不可变载荷无法按批准 Schema 校验或无法序列化为 Broker 消息；`last_error` 为空或不属于可恢复白名单；或来自旧版本的异常行已记录 `attempt_count=8`。更新不改变 `attempt_count`，清空 `next_attempt_at`，保持 `published_at` 为空，并将原因规范化为 `UNSUPPORTED_EVENT_VERSION`、`SERIALIZATION_FAILED`、`DELIVERY_ATTEMPTS_EXHAUSTED` 或稳定的未知值 `UNKNOWN_DELIVERY_ERROR`；禁止保存原始未知码。合法新写入仍应从 `processing` 直接进入 `dead_letter`，该狭窄边不是日常重试分支。
- 对 `job.dispatch.requested`，任何 `processing|failed -> dead_letter` 都必须走同一个 Job-aware finalizer，不能只终结 Outbox。发送尝试事务结束后，finalizer 在独立事务中固定先锁 `async_jobs`、再锁 `outbox_events`，并 CAS 当前 Outbox fencing tuple；若 Job 已被 Worker claim 或已终结，只终结 Outbox 并写安全告警，不反向覆盖 Job。若 Job 仍为与 `event_sequence=attempt_no+1` 对应的 `queued`、没有当前 attempt Step/Lease，则同一事务把 Outbox 终结为 `dead_letter`，并把 Job 以当前 `row_version` CAS 为 `failed`、写同一 `finished_at`、清空 `next_retry_at`。能证明未发送的 `UNSUPPORTED_EVENT_VERSION/SERIALIZATION_FAILED/BROKER_UNAVAILABLE` 映射为 `JOB_DISPATCH_FAILED`；`BROKER_TIMEOUT/PUBLISH_CONFIRM_UNKNOWN/PROCESSING_LEASE_EXPIRED/UNKNOWN_DELIVERY_ERROR/DELIVERY_ATTEMPTS_EXHAUSTED` 等无法证明未发送的路径映射为 `JOB_DISPATCH_OUTCOME_UNKNOWN`。后者不采用业务结果：若消息随后到达，Worker 因 Job 已非 queued 而拒绝 claim；若消息已先 claim，finalizer 的 Job CAS 为 0 行并保留权威运行状态。两类 pre-claim 失败都不伪造 Step、`started_at` 或 stage，且不属于首版 retryable 白名单；新业务请求可在新的幂等键下创建新 Job，原幂等键仍返回首次保存的 Job 身份/响应，调用方通过 OPS-001 读取其权威 failed 状态。该规则保证 dead-letter 不留下永久 queued Job，也不把不确定投递误标为成功。
- 首版 Outbox 投递参数固定为：`max_attempts=8`、处理租约 `60s`、失败后的基础延迟序列 `1/2/4/8/16/32/60s`；第 `n` 次处理失败且 `n=1..7` 时使用序列第 `n` 项。每次延迟再加 `0..999ms` 的确定性抖动，输入 bytes 固定为 `UTF8(lower(outbox_events.id) + ':' + decimal(attempt_count))`，其中 UUID 带连字符、十进制无前导零；取 `SHA-256(input)` 前 8 bytes 按无符号大端整数对 1000 取模。第 8 次处理仍失败时直接进入 `dead_letter`，不得创建第 9 次处理。租约和延迟使用数据库 UTC 时间，重启不得重置 `attempt_count`。
- 处理租约回收器也只能 CAS 当前过期 tuple：数据库时间超过 `next_attempt_at` 且 `attempt_count < 8` 时，将该次 processing 变为 `failed`、写 `PROCESSING_LEASE_EXPIRED`，并把 `next_attempt_at` 设置为 `database_now + delay[attempt_count] + deterministic_jitter`；`attempt_count=8` 的超时必须直接 CAS 为 `dead_letter`、写 `DELIVERY_ATTEMPTS_EXHAUSTED` 并清空 `next_attempt_at`，不得回到 `failed`。如果其后已有新 claim，旧 tuple 更新 0 行并立即停止。`last_error` 虽为文本列，也只能写固定安全错误码：可恢复 `BROKER_UNAVAILABLE/BROKER_TIMEOUT/PUBLISH_CONFIRM_UNKNOWN/PROCESSING_LEASE_EXPIRED`，永久 `UNSUPPORTED_EVENT_VERSION/SERIALIZATION_FAILED`，耗尽 `DELIVERY_ATTEMPTS_EXHAUSTED`，未知失败关闭 `UNKNOWN_DELIVERY_ERROR`；任何未知码都必须规范化为 `UNKNOWN_DELIVERY_ERROR` 并直接隔离为 `dead_letter`，不保存原码、Provider/Broker 自由文本或堆栈。Dispatcher 采用至少一次投递；重复发送由稳定 `event_id` 和消费者幂等处理，`PUBLISH_CONFIRM_UNKNOWN` 必须以同一 Outbox 行重试，不得直接标成 `published`。
- revision ownership 固定为：在当前 head 不存在这三表的前提下，CR-004 获批后的首个 reliability revision 是 `async_jobs/async_job_steps/outbox_events` 完整三表的唯一创建者；upgrade 按 `async_jobs -> async_job_steps -> outbox_events` 创建基线与 CR-001/CR-002/本 CR 已批准的全部列、约束、触发器和索引，不允许另一个前置 revision 先创建“简化表”再由本 revision 增量修改。该 revision 拥有且只创建四个独立 trigger function：`enforce_async_jobs_state_v1()`、`enforce_async_job_steps_state_v1()`、`enforce_job_step_consistency_v1()`、`enforce_outbox_events_state_v1()`；状态/字段不可变、跨 Job/Step 延迟一致性和 Outbox 状态分别只经这些函数实现，禁止生成未登记 helper function。该 ownership 不增加第 58 张核心表，只实现 57 张正式基线中的三张。
- downgrade 前的部署门禁必须先停止生产者、用兼容消费者排空可处理事件，并确认外部 Broker 没有无法解释的在途证据；这是跨系统运维前置条件，不伪装成数据库事务能原子检查的事实。随后该 reliability revision 的 downgrade 在单一事务开始时执行 `SET LOCAL lock_timeout='5s'`，按 `async_jobs -> async_job_steps -> outbox_events` 的固定顺序取得 `ACCESS EXCLUSIVE` 锁；锁等待超时保持 PostgreSQL 稳定 SQLSTATE `55P03`，不得重试为无界等待。取得全部锁后重复检查三表均为空，任一非空以稳定 SQLSTATE `55000` 在任何 DDL 前原子失败。全部门禁通过后，使用显式、无 `CASCADE` 的 `DROP TABLE outbox_events`、`DROP TABLE async_job_steps`、`DROP TABLE async_jobs` 依次删除本 revision 拥有的完整三表；再依次执行无 `CASCADE` 的 `DROP FUNCTION enforce_job_step_consistency_v1()`、`DROP FUNCTION enforce_outbox_events_state_v1()`、`DROP FUNCTION enforce_async_job_steps_state_v1()`、`DROP FUNCTION enforce_async_jobs_state_v1()`，不得把独立函数误称为随表自动删除。不存在另一套“只删 CR-004 列/对象”的增量 downgrade、动态发现、自动 `TRUNCATE`、删除业务行、归档、改写版本或绕过检查；任一语句失败则整个事务回滚，未知/不兼容事件保持停用并前向修复。任何后续引用这三表或四个函数的 revision 必须先按 Alembic 逆序降级，不能跨越依赖直接执行本 downgrade。

## 3. 实施影响

本推荐不改变 P0 的 57 张核心表总数，不新增 `async_jobs` 重复业务列；增加独立的 Handler Registry/retry/lease 版本与 hash，以及 `row_version`。CR-004 批准并同步 Request 只关闭本文的元合同；首个 Handler Registry 制品仍须单独批准，且 AI sequence 3 实现仍须 CR-011 批准并同步。所有上游门禁均满足后，一个后续线性 Alembic revision 才可按上文 ownership 一次创建完整 `async_jobs/async_job_steps/outbox_events` 三表及相应列、CHECK、唯一约束和不可变/CAS 边界；本 CR 不预占 revision 编号，也不允许拆出含义不同的简化表前置 revision。

需要同步的事实来源至少包括：需求规格、系统架构、数据库设计、API 设计、页面与交互设计、AI/RAG/Prompt 设计、测试方案、部署运维、实施计划和追踪材料。同步时必须删除架构中的陈旧 `retryable/idempotency_key` 持久列要求，冻结 Job/Step 状态与字段矩阵，在 OPS-001 与页面模型增加只读派生 `retryable` 和 `row_version`，并保持 Handler Registry、Broker 消息与数据库列的单一版本事实。

## 4. 必须验收

- Schema 证明 `async_jobs` 不存在 `retryable/idempotency_key`，但精确包含 `handler_registry_version/hash`、`retry_policy_version/hash`、`lease_policy_version/hash` 与 `row_version`；契约测试固定两个 Policy Profile 的规范化哈希，并证明策略升级不改变 `input_hash`、不绕过活动 Job 唯一键，且 retryable 派生在错误/未知版本或 hash、未注册组合、未知码、次数边界及 Lease 恢复场景均 fail closed。
- Handler Registry 机器制品验收必须证明 Registry Schema 拒绝未知键/空值/非正整数，Loader 拒绝重复键，handlers 排序和复合唯一性不可绕过，steps 顺序及 handler 内唯一性精确；每个条目的 `input_schema_id/input_schema_sha256` 必须命中同一批准包内唯一、原始 bytes hash 可复现的 Job 输入 Schema，缺失、替换、额外 Schema 或私有映射均被拒绝。Registry JCS/hash、Registry Schema 原始 bytes hash、全部输入 Schema 原始 bytes hash与绑定关系都可重现且不可拆分，历史 version/hash 不可覆盖，Job 创建、输入校验、重试、claim、阶段推进和审计动作只经由唯一 Loader。具体制品未批准前，该项只能为 pending，不得以手写测试字典代替。
- Job 并发测试证明初始值、全部允许边、全部禁止边和各状态字段矩阵；用户 failed→queued 重试和 Lease 恢复都只有 claim/recovery CAS 递增一次 `attempt_no`，API 的 `scheduled_attempt_no`、Outbox sequence、running Step attempt 与实际 Job attempt 一致。真实约束证明 running/cancel_requested Job 在提交时恰有一个与 stage 对应的 running Step，阶段推进无空窗，running→succeeded|failed 与最后 Step 同事务且字段一致，同 attempt 第二个 running Step 被拒绝。覆盖 queued 直接取消、running 请求取消并继续 heartbeat、安全检查点取消、取消 Lease 超时回收以及终态/取消并发；取消不得产生新 attempt、Step 或业务结果。用暂停旧 Worker 的双连接测试证明 heartbeat、Step/Job 终结、业务结果和 Outbox 全部受包含 `row_version` 的 fencing tuple 保护，所有成功写入恰好递增一次版本，过期且次数耗尽稳定进入 failed。
- PostgreSQL 16 真实约束测试证明 Step 只能从 `running` 一次进入终态，字段白名单、终态不可变、禁止删除、时间关系和并发终结均不能绕过。
- 序列化契约测试逐字验证 Job Outbox payload 与 Broker 两字段消息，并证明 `event_schema_version == outbox_events.event_version`；缺失、错版、未知版和重复消息不污染 Job 状态。
- AI 事件测试覆盖 started、正常 completed、outcome_unknown、合法 late completion、重复、乱序、相同身份冲突和未知版本；late completion 永不反向改写未知终态或采用业务结果。该项必须使用已批准且已同步的 CR-011 Schema/Sink 合同；在此之前保持 pending，不得将 CR-004 语义测试宣称为 AI-005 验收。
- Outbox 测试覆盖所有允许/禁止状态转换、字段矩阵、实际变化字段白名单、每次 claim 的 fencing tuple、迟到 Dispatcher/reaper 0 行 CAS、固定八次上限、60 秒租约、精确退避/确定性抖动、发送结果未知、处理租约超时、至少一次重复投递、死信和完整安全错误码集合。必须单独证明 `failed -> dead_letter` 只能由限定 finalizer 在限定条件下 CAS，未知码稳定归一为 `UNKNOWN_DELIVERY_ERROR` 且原码不泄露。
- 部署前置门禁与数据库 downgrade 分开验收；验证当前前置 head 无三表和上述四个函数、单一 revision upgrade 后三表及四函数完整、没有简化表前置 revision或额外 helper function。双连接用例必须证明 5 秒锁超时稳定返回 `55P03` 且不执行 DDL，非空门禁稳定返回 `55000`，空表 downgrade 按 `outbox_events -> async_job_steps -> async_jobs` 完整删表、随后按固定顺序删除四函数，全部无 `CASCADE` 且不遗留 revision-owned 对象，并可重复 upgrade/downgrade；按固定顺序加锁后只要存在一条 Job、Step 或 Outbox 就必须在任何 DDL 前原子失败且数据保持不变。仅离线 SQL、ORM 元数据或 Mock 不算 PostgreSQL 16 完整验收。

## 5. 审批边界

在第 6 节记录首次 snapshot 且全部必需签署完成前，本文件不授权：

- 修改或同步任何 `Request/` 文档；
- 创建或修改 migration、Worker、Dispatcher、AI 投影或其他运行时代码；
- 调用 `fixed_test_provider`、内部 vLLM 或任何真实 Provider 网络接口；
- production 放行、canary、部署、提交、推送或创建 PR。

批准必须覆盖以下角色矩阵；一人具备多个角色权限时可以合并一条记录，但必须逐项列出所代表角色与对应决策。任一必需角色拒绝、留空或给出相互冲突的条件，整体都保持 `NOT APPROVED`。

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | REL-D-001～005 范围、用户可见 retry/cancel 语义与 Request 同步清单 |
| 架构 | Job/Step/Outbox 边界、Handler Registry 上游门禁和 CR-011 依赖 |
| 数据/数据库 | 列、CHECK、状态机、不可变、CAS/延迟约束与 downgrade |
| 后端/API | Job 创建、重试、取消、Worker/Dispatcher 仓储边界与 OPS-001 响应 |
| AI | REL-D-004 语义、CR-011 兼容性及“不授权 AI-005”边界 |
| 测试/质量 | 第 4 节的全部契约、并发、PostgreSQL 16 与降级验收 |
| 运维/可靠性 | Registry 历史保留、Lease/Outbox 运行边界、Broker 前置门禁与回滚条件 |
| 安全 | 载荷最小化、安全错误码、未知值 fail-closed、凭据/网络/生产边界 |

每条审批记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_decisions=REL-D-001..005 / cr_revision=CR-004-R1 / decision_snapshot_sha256 / environment_scope=contract / handler_registry_scope=meta_contract_only|approved_artifact / handler_registry_version / handler_registry_sha256 / handler_registry_schema_version / handler_registry_schema_sha256 / input_schema_bundle_status / CR-011_dependency_status / 日期 / 证据链接 / 备注`。本轮未包含具体 Handler Registry 制品时，相应 scope 必须记为 `meta_contract_only`，Registry、Registry Schema 与输入 Schema bundle 的身份/hash 必须全部记为 `PENDING`，不得伪造值或由实现代填。`CR-011_dependency_status` 必须明确区分“语义可审批”与“Schema/Sink/投影/runtime 仍阻塞”。

`decision_snapshot_sha256` 计算规则：将全文行尾规范化为 LF，定位内容完全等于第 6 节标题的行，该标记必须恰好出现一次；取该行之前的全部行，末尾保留恰好一个 LF，对无 BOM 的 UTF-8 bytes 计算 SHA-256 小写十六进制。标记缺失或重复、规范化失败或 hash 非小写 64 位十六进制时一律不可签署。

首次生成 decision snapshot 只建立可签署对象，不等于批准。首次生成后，第 1～5 节的任何规范性修改都必须提升 CR revision、重新生成 hash 并重置所有签署。在 snapshot 与相应批准完成前，Job/Outbox migration 与依赖这些合同的 Dispatcher、AI-005 持久投影继续保持阻塞，而不是选择任一隐含解释。

## 6. 当前状态

状态：`DRAFT / PROPOSED / NOT APPROVED`

| 项目 | 状态 |
|---|---|
| GAP-040～GAP-042 / REL-D-001～005 | `PROPOSED / NOT APPROVED` |
| Job/Step 状态机、字段矩阵与 `row_version` CAS | `PROPOSED / NOT APPROVED` |
| Handler Registry 元合同 | `PROPOSED / NOT APPROVED` |
| Handler Registry 具体 Schema/实例/version/hash | `PENDING / NOT GENERATED / NOT APPROVED；Handler-dependent migration/runtime BLOCKED` |
| CR-011 依赖 | `DRAFT / NOT APPROVED / Request NOT SYNCHRONIZED；AI sequence-3 Schema/Sink/投影/runtime BLOCKED` |
| AI-005 | `NOT AUTHORIZED BY CR-004` |
| Request 同步 | `NOT AUTHORIZED` |
| decision snapshot | `GENERATED FOR REVIEW；decision_snapshot_sha256=387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6；NOT APPROVED` |
| migration/runtime | `NOT AUTHORIZED` |
| `fixed_test_provider` / 内部 vLLM / 真实 Provider 网络 | `NOT AUTHORIZED` |
| production/canary/部署 | `NOT AUTHORIZED` |
