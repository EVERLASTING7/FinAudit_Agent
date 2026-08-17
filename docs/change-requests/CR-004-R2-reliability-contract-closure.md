# CR-004-R2：Job、Step 与 Outbox 可靠性合同 successor addendum

> 文档类型：`CR-004-R1` 的最小 successor addendum  
> 修订：`CR-004-R2`  
> 日期：2026-08-09  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 9 节  
> 非目标：不改写 R1 规范正文，不生成生产 Handler 制品，不同步 Request，不创建 migration/runtime，不授权网络或 production

## 1. 基座、范围与 effective contract

本 addendum 只在下列不可变 R1 决策快照上生效：

| 字段 | 固定值 |
|---|---|
| `base_document_path` | `docs/change-requests/CR-004-reliability-contract-closure.md` |
| `base_revision` | `CR-004-R1` |
| `base_raw_bytes` | `41523` |
| `base_decision_preimage_bytes` | `40544` |
| `base_decision_snapshot_sha256` | `387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6` |
| `successor_revision` | `CR-004-R2` |

`CR-004-R2 effective contract` 的唯一含义是“上述精确 R1 decision snapshot 加本文件第 1～8 节的 R2 addendum snapshot”。两份 snapshot 必须分别验证，不得拼接两份 bytes 后生成未定义的第三个 hash，也不得用 R1 动态状态区替代其决策快照。

R1 的 `REL-D-001`～`REL-D-005` 仍是唯一决策全集。本文件只覆盖 R1 中明确列出的矛盾、遗漏、依赖范围与授权分层；未被本文件覆盖的 R1 条款原样继承。发生冲突时，本 R2 addendum 优先。任何其他语义变化必须另升 revision。

本候选的目标是解除“空的可靠性三表必须等待首个生产 Handler Registry”这一循环依赖，同时保持真实 Job 创建、Dispatcher、Worker、重试、取消、Lease recovery、Outbox 投递和 AI 投影继续失败关闭。R2 获批本身不等于 `BASE-006` 完成。

## 2. 决策全集与累计 delta

R2 不新增 `REL-R2-*` alias。审批只能使用以下五项，顺序固定：

```text
REL-D-001
REL-D-002
REL-D-003
REL-D-004
REL-D-005
```

- `APPROVED` 时，`selected_decisions` 必须逐字等于上述五项，`rejected_decisions` 必须为空。
- `REJECTED` 时，两个数组必须无重复、互斥并精确分区五项全集，且 `rejected_decisions` 非空；数组保持上述声明顺序。
- `selected_decisions` 缺项、额外项、乱序、别名或相互冲突的条件均不构成有效批准。

累计 delta 固定如下：

| 项目 | 值 |
|---|---:|
| `api_path_delta` | `0` |
| `http_api_error_code_delta` | `+1`，只新增 `JOB_VERSION_CONFLICT` |
| `core_table_delta` | `0`，三表已在 57 张正式基线内 |
| `implemented_core_table_delta_after_authorized_007` | `+3`，仅表示实现既有三表 |
| `ui_page_route_delta` | `0` |
| `p0_work_item_delta` | `0` |
| `operation_log_action_delta` | `0` |
| `owned_alembic_revision_count` | `1` |
| API path 总数 | `122` |
| 核心表总数 | `57` |
| 页面范围 | `UI-001`～`UI-014` |
| P0 工作包总数 | `86` |

本 CR 不批准任何新的 operation action；后续 action registry 必须从本 effective contract 的全局状态机推导 transition，不得把 transition code 复制进 Handler Registry 形成第二事实来源。

## 3. R2 规范覆盖

### 3.1 Handler Registry、Schema 与已安装 Handler 门禁

Registry 顶层必须且只能包含：

```text
registry_version
handlers
```

每个 handler 必须且只能包含：

```text
job_type
input_schema_version
input_schema_id
input_schema_sha256
handler_code_version
logical_queue
max_attempts
retry_scopes
steps
```

每个 `retry_scopes` item 必须且只能包含：

```text
scope_code
start_step_code
```

每个 `steps` item 必须且只能包含：

```text
step_code
summary_schema_id
summary_schema_sha256
```

R1 对重复键、`additionalProperties=false`、排序、唯一性、标识符、raw bytes 与 JCS hash 的要求继续有效，并增加：

- `logical_queue` 只能为 `document/extraction/knowledge/evaluation/audit/report/maintenance`。
- `input_schema_version` 与 `max_attempts` 都必须是拒绝 JSON boolean、字符串和小数的严格 JSON integer，范围为 `1..2147483647`；Job 创建只能从命中的冻结 handler 复制 `max_attempts`，客户端、环境变量、AI Provider retry Policy 或私有常量不得覆盖。
- `retry_scopes` 必须是 JSON array，可为空；每项两个值都必须是严格 JSON string。`scope_code/start_step_code` 均为 1～80 位 ASCII 并匹配 `^[a-z][a-z0-9_]*$`。数组按 `scope_code` 的 UTF-8 bytes 升序，且在同一 handler 内唯一；不同 handler 可以复用相同 scope code。每个 `start_step_code` 必须逐字命中本 handler 的一个 `steps[].step_code`。具体生产 scope code 与映射值仍保持 PENDING，不得从 API enum 或代码命名猜测。
- `steps` 数组顺序是绝对执行顺序；`step_seq` 是该数组的 1-based 绝对位置。`summary_schema_id` 必须是 1～160 位 ASCII 且匹配 `^[a-z][a-z0-9._-]*$`；`summary_schema_sha256` 必须是对应 Summary Schema 原始无 BOM UTF-8 bytes 的 SHA-256 小写 64 位 hex。同一 `summary_schema_id` 只能对应一个 hash；后续 Summary Schema bundle 必须恰好包含 Registry 引用的全部唯一 ID/hash，不得缺失、替换或额外夹带 Schema。Worker 不得用私有字典验证 `summary_json`。
- Registry、Registry Schema、Input Schema 与 Summary Schema 均使用 JSON Schema Draft 2020-12；严格 UTF-8、无 BOM、重复键拒绝和 raw SHA-256 规则沿用 R1。
- Celery task name 不进入 Registry。唯一公式固定为 `app.workers.tasks.<logical_queue>.execute_job`；物理 queue 与 routing key 只由已验证 Settings 的七项逻辑队列映射产生。
- 运行时只能通过代码内封闭 allowlist 将 `(job_type, handler_code_version)` 解析为已安装 callable；禁止 `importlib` 动态导入、`eval`、数据库字符串模块路径或环境变量覆盖。后续 Handler artifact manifest 必须绑定该 allowlist 对应的应用 release、实现身份与 Registry/Input/Summary 全部 raw identity。

本 R2 只冻结 meta contract。具体 Registry Schema、Registry 实例、Input/Summary Schema bundle、Handler artifact manifest、version/hash 与生产 scope-to-step 值全部保持 `PENDING / NOT GENERATED / NOT APPROVED`；缺少其中任一项时，真实 Job 创建和 Handler-dependent runtime 必须失败关闭。

### 3.2 attempt 起点的唯一持久事实

`async_jobs` 新增且只新增下列当前 attempt 计划列：

```text
current_attempt_start_step_code VARCHAR(80) NOT NULL
```

唯一语义如下：

- 初始 Job 创建时，值等于冻结 Registry 的首个 `step_code`。
- `FILE-007.stage` 或 `AUDIT-007.retry_scope` 必须先命中冻结 Registry 的 `retry_scopes`，再在 `failed -> queued` 事务中把映射结果写入本列。
- queued claim 保留本列，不清空、不改写；claim 创建的新 running Step 使用该代码在 Registry 中的绝对 `step_seq`。
- Lease recovery 明确覆盖 R1 的“恢复到 Registry 首 step”：新 attempt 仍从本列记录的 scope 起点开始，不得退回已被本次 partial retry 明确保留的更早阶段。
- 已 claim attempt 的历史起点由该 attempt 中最小 `step_seq` 的第一条 Step 唯一重建；该值可以大于 1。前序已保留结果不伪造 `skipped` Step。
- 同一 attempt 的后续 Step 必须从该起点形成 Registry 顺序中的连续片段。未 claim 即取消或 dispatch 失败的 queued 计划不伪造 attempt Step 历史。
- 不新增 `retry_scope` JSON、第四张表或可变 `input_json`；`input_json/input_hash` 继续冻结。

### 3.3 三表列集、删除边界与触发器所有权

`async_jobs` 完整列集固定为：

```text
id
organization_id
job_type
resource_type
resource_id
status
stage
attempt_no
max_attempts
current_attempt_start_step_code
next_retry_at
worker_id
started_at
finished_at
error_code
error_message
input_hash
input_json
input_schema_version
idempotency_record_id
handler_registry_version
handler_registry_hash
retry_policy_version
retry_policy_hash
lease_policy_version
lease_policy_hash
lease_owner
lease_expires_at
heartbeat_at
row_version
trace_id
created_by
created_at
```

`async_job_steps` 完整列集固定为：

```text
id
job_id
step_seq
step_code
status
attempt_no
started_at
finished_at
summary_json
error_code
trace_id
```

`outbox_events` 完整列集固定为：

```text
id
aggregate_type
aggregate_id
event_id
event_type
event_version
event_sequence
payload_json
status
attempt_count
next_attempt_at
published_at
last_error
trace_id
created_at
```

R1 的字段矩阵、CHECK、索引、Job/Step 延迟一致性和四个 trigger function 所有权继续有效，并增加：

- `async_job_steps` 与 `outbox_events` 同时禁止 `DELETE` 和 `TRUNCATE`；statement-level `TRUNCATE` trigger 复用各自既有 trigger function，不得生成第五个 helper function。
- `async_job_steps.summary_json` 必须命中该 Step 冻结绑定的 Summary Schema；具体 Handler bundle 获批前，运行时不得写 Step。
- `current_attempt_start_step_code` 必须命中 Job 冻结 Registry 的该 handler；数据库格式约束与 Loader 语义校验共同失败关闭。
- 三表仍只允许 R1 登记的 `enforce_async_jobs_state_v1()`、`enforce_async_job_steps_state_v1()`、`enforce_job_step_consistency_v1()`、`enforce_outbox_events_state_v1()` 四个函数。

### 3.4 Celery protocol v2、最小 kwargs 与 wake-up identity

应用 kwargs 必须且只能是：

```json
{
  "job_id": "<canonical-lowercase-uuid>",
  "event_schema_version": 1
}
```

该对象不是完整 Celery wire body。真实消息使用 Celery protocol v2：body 必须精确为 `args=[]`、上述 exact kwargs，以及只含 `callbacks/errbacks/chain/chord` 四键且四值全部为 JSON null 的 embed object；任何非空 callback、errback、chain、chord 或额外 embed 键都失败关闭。标准 headers/properties 保留，但必须满足以下固定规则：

- `event_schema_version` 必须是严格 JSON integer `1`；拒绝 `true`、`1.0`、`"1"`、零、负数和未知版本。
- execution-control headers 必须固定为：`eta=null`、`expires=null`、`retries=0`、`timelimit=[null,null]`、`group=null`、`group_index=null`、`shadow=null`、`parent_id=null`、`root_id=id`、`replaced_task_nesting=0`、`stamped_headers=null`、`stamps={}`、`ignore_result=true`。禁止 per-message time limit、ETA、expiry、retry、stamp、group 或替换任务覆盖；AMQP properties 中 `expiration` 必须缺失。
- Dispatcher 只允许 `application/json`/UTF-8 serializer，Worker `accept_content` 只允许 JSON；未知 content type/encoding 在反序列化和 callable 前失败关闭。除 Celery 5.6 必需的观察性标准字段 `lang/origin/argsrepr/kwargsrepr` 与唯一允许的 `traceparent` 外，不得增加影响调度、执行或结果采用的 header；这些观察性字段不参与业务状态和排期。
- `task` header 必须逐字等于命中 Handler 的 `app.workers.tasks.<logical_queue>.execute_job`；`id` header 与 AMQP `correlation_id` 都固定为小写 `outbox_events.event_id`，且不得用不同 task alias。`event_id` 不进入第三个应用字段。自定义关联 Header 只允许已验证的 W3C `traceparent`，不得在 body 放 `trace_id`、正文、输入参数或 secret。
- Dispatcher 必须经同一冻结 Registry 取得 `logical_queue`，使用第 3.1 节 task-name 公式并显式设置物理 queue/routing key。
- Outbox publish 必须显式 `retry=False`，Celery 配置固定 `task_publish_retry=False`；一次 Outbox `attempt_count` 只能对应一次真实 publish 调用。Job task 禁止 `autoretry_for`、`self.retry()` 或其他 Celery 自重试。
- Broker 消息只是非权威 wake-up。`async_jobs.resource_type='audit_task_execution'` 是 audit-execution Job 的唯一机械分类谓词；其他值全部走通用路径。通用 Worker 按 `async_jobs -> outbox_events` 锁序；audit-execution Worker 必须先用不加锁读取取得不可变 `resource_type/resource_id`，再按第 4.2 节 `audit_task_executions -> async_jobs -> outbox_events` 加锁并重验二者，禁止先持有 Job 锁再反向取得 execution 锁。随后回查 `id` header 命中的 Outbox，并同时验证：`aggregate_type='async_job'`、`aggregate_id=job_id`、`event_type='job.dispatch.requested'`、`event_version=event_schema_version`、`event_sequence=async_jobs.attempt_no+1`、`payload_json` 精确为当前 `job_id`，Outbox 状态属于 `processing|failed|published`，Job 状态为 `queued`，且当前 attempt 尚无 Step/Lease。audit-execution claim 还必须要求 execution 为 `queued`，并在同一 `database_now` 事务中把 execution 与 Job 原子置为 `running`、追加 running Step；任一前像或 affected-row 不匹配都不得 claim。
- `pending/dead_letter` Outbox、旧 `event_sequence`、未知 task ID、错版、错 Job 或 terminal/running Job 均不得 claim。迟到或重复的旧 attempt 消息因此不能提前启动新计划；同一当前消息并发时只有一个 Job CAS 成功。
- task callable 在 claim 前还必须从 Job 冻结 Registry 重新得到 `logical_queue`，核对自身 task name 与 Celery `delivery_info.routing_key`（以及配置启用时的 exchange）命中已验证 Settings 映射；Celery 5.6 `delivery_info` 不提供实际 consuming queue，故物理 consumer queue 必须由 Worker 启动配置与 runtime integration Gate 证明，不得在 callable 中读取虚构字段。错 task、错 routing key/exchange 或非空 canvas embed 均不得进入业务 Handler。

### 3.5 PostgreSQL 时钟与 Lease 边界

- 每个状态转换必须在数据库内只捕获一次 `clock_timestamp()` 作为 `database_now`，并将该单值复用于该转换的全部 CAS 条件和时间字段。
- 禁止应用时钟、客户端时间、事务起点 `now()/CURRENT_TIMESTAMP/transaction_timestamp()` 或多次独立取时参与同一转换。多表转换必须使用同一 SQL statement/writable CTE 或同一数据库 transition function，不得在取时与提交之间执行外部 I/O。
- heartbeat、阶段推进、Step/Job 终结和业务结果提交只在 `database_now < lease_expires_at` 时允许。到达等值边界时旧 Worker 立即失去写权限。
- recovery 只在 `database_now >= lease_expires_at + interval '15 seconds'` 时允许；Lease 到期到 grace 结束之间既不允许旧 Worker 写，也不允许提前 recovery。
- Outbox `failed -> processing` 在 `next_attempt_at <= database_now` 时允许；processing reaper 在 `database_now >= next_attempt_at` 时允许，消除等值边界差异。
- `lease_owner` 只能由 PostgreSQL `gen_random_uuid()::text` 生成，与 `worker_id` 分离，并满足 canonical lowercase UUIDv4 CHECK：`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`。

### 3.6 Outbox 第八次失败与未知结果

- 第 1～7 次可恢复发送失败进入 `failed` 并按 R1 延迟计划下一次。
- 第 8 次任何可恢复发送失败直接进入 `dead_letter`，固定 `last_error='DELIVERY_ATTEMPTS_EXHAUSTED'`，不得保留当次底层码或产生第 9 次。
- 只有 `outbox_events.attempt_count=1` 且在任何 Broker publish 调用前，由本地确定性校验发现的 `UNSUPPORTED_EVENT_VERSION` 或 `SERIALIZATION_FAILED`，可以把仍 queued 的 Job 映射为 `JOB_DISPATCH_FAILED`。
- 任何 Broker 调用、confirm、timeout、processing lease、未知错误、历史不完整或尝试耗尽路径都保守映射 `JOB_DISPATCH_OUTCOME_UNKNOWN`，包括 `BROKER_UNAVAILABLE`。
- finalizer 不得根据已被后续 claim 清空的 `last_error` 推断“历史所有尝试均未发送”；本方案不增加重复的 `delivery_outcome_unknown` 列。
- `PUBLISH_CONFIRM_UNKNOWN` 继续复用同一 Outbox 行，不得直接标记 `published`。自由文本、堆栈、连接信息和未知 Broker code 必须归一为 R1 安全码，禁止进入表、日志、响应或测试报告。

### 3.7 CR-011 依赖只阻塞 AI late-event 范围

当前唯一候选绑定为：

```text
revision=CR-011-R3
decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be
artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c
status=NOT_APPROVED
request_sync_authorization=NOT_AUTHORIZED
request_sync_execution=NOT_EXECUTED
```

该依赖只阻塞 `AiCallEventV1` sequence 3 的具体 Schema、Sink、投影与 runtime，及 AI-005、Provider 调用和 AI 业务结果采用。它不阻塞：

- CR-004-R2 合同审批；
- 九份 Request、正式 baseline manifest 与 active-baseline pin 对本 R2 通用可靠性语义的 11 文件原子同步；
- `20260807_007` 三张空表 DDL/ORM；
- 不含 AI runtime 的离线与专用合成 PostgreSQL 16 约束验证。

批准 CR-004-R2 不批准 CR-011-R3。若 CR-011 后续获批内容与 R1 `REL-D-004` 或本 R2 不兼容，必须先提升 CR-004 revision。

### 3.8 旧下游 fact-set 与治理候选不得消费 R2

当前 `backend/app/approval_pre_meta.py` 及其测试、`DEP-005`/`DEP-005-R2`、`CR-014`、`CR-006`/`CR-006-R2`、`CR-008`/`CR-008-R2` 仍只绑定 `CR-004-R1`、旧八角色或旧 `cr004-handler-registry-approved-fact-set-v1`。它们不得把 R1-only binding 解释为已覆盖本 R2 effective contract，也不得按现状批准、生成 artifact、同步 Request 或被 runtime 消费。

后续若继续这些候选，必须各自提升 successor revision，并至少：

- 同时绑定第 1 节 R1 base tuple 与本 R2 decision snapshot，不得只替换一个 hash；
- 将 CR-004 approved fact set 扩展为绑定 Registry Schema/instance、Input Schema bundle、Summary Schema bundle、Handler manifest/静态 allowlist identity 及其共同 release；
- 使 CR-006/008 的依赖 Schema、companion、fixed vectors、pre-meta verifier 与审批角色集合消费相同 effective identity；
- 删除 CR-008 对“Handler Registry transition enum”的依赖，Worker transition 只能从 R1+R2 effective contract 的 Job/Step/Outbox 全局状态机推导，Registry exact keys 不得增加第二份 transition 事实。

上述 substantive successor 与 verifier 修订不由本 R2 授权，也不阻塞本 R2 合同审批、九份 Request 加正式 baseline manifest 的原子同步或 `20260807_007` 空表 DDL/ORM。唯一机械例外是第 6 节授权的 `approval_pre_meta.py::_BASELINE_IDENTITY` active-baseline re-pin：它只能把旧 manifest 的 byte length/hash 两个 literal 换为本次 post-sync manifest identity，不得修改 `_SCHEMA_IDENTITIES`、`_SNAPSHOT_IDENTITIES`、snapshot 数量、Schema/fact-set/角色、CLI 的 `OUT_OF_SCOPE_NOT_EVALUATED/NOT_AUTHORIZED` 输出或任何批准判断；该 re-pin 不使 legacy verifier 成为 R2 fact-set consumer。

## 4. API 与 UI 精确 delta

### 4.1 FILE-007 与 AUDIT-007

两个重试接口请求 Body 均增加必填正整数 `row_version`，其唯一语义为当前 Job 版本。重试事务必须：

1. 在幂等请求绑定门禁后锁定对应业务对象；`AUDIT-007` 固定锁序为 `audit_task_executions -> async_jobs -> outbox_events`，验证 execution 与 Job 都为 `failed`、`retryable=true`、当前 `row_version` 与权限/状态；FILE 路径不涉及 execution 时保持业务对象后 `async_jobs -> outbox_events`；
2. 通过 Job 冻结 Registry 将 `FILE-007.stage` 或 `AUDIT-007.retry_scope` 映射为 `current_attempt_start_step_code`；
3. 同一 `database_now` 事务执行 Job `failed -> queued`、保持 `attempt_no` 不变、递增一次 `row_version`，创建唯一 `event_sequence=attempt_no+1` Outbox 并保存幂等请求绑定；`AUDIT-007` 还必须把 execution `failed -> queued`，清空当前失败投影并检查 affected row 恰为 1，不得出现 Job queued 而 execution 仍 failed；不得创建 Step；
4. 返回当前 `attempt_no`、`scheduled_attempt_no=attempt_no+1` 和事务提交后的新 `row_version`。

`FILE-007` 响应字段固定为：

```text
job_id
attempt_no
scheduled_attempt_no
status                 # queued
stage                  # 已批准 scope 映射出的计划起始 step，不是 OPS-001 当前运行 stage
row_version
job_url
```

`AUDIT-007` 保留 `execution_id/status/preserved_results`，增加相同的 `scheduled_attempt_no/row_version`；响应 `status='queued'` 同时投影已提交的 execution 与 Job 状态，`preserved_results` 只能投影已提交的执行事实。两个接口都新增 409 `JOB_VERSION_CONFLICT`。删除“重试事务已经递增 attempt_no”的旧说明；只有 queued claim 或 Lease recovery 递增。

具体 FILE stage mapping、AUDIT scope mapping、Repository/Service/Router 与 operation log action 仍依赖各自生产 Handler artifact 和后续运行时前置，不由本 CR 候选直接实现。

### 4.2 audit execution 与 Job 原子状态投影

只有 `async_jobs.resource_type='audit_task_execution'` 且 `resource_id` 逐字命中 execution 主键时应用本节；分类、加锁后都必须重验不可变 identity。任何同时读取或修改 execution 与 Job 的 claim、阶段终结、取消、retry 或 Job-aware finalizer 都固定按 `audit_task_executions -> async_jobs -> outbox_events` 加锁，affected-row 必须恰为 1；通用 Job 路径不得反向取得 execution 锁。

- 初始或 retry 后的 claim 必须同时要求 execution 与 Job 都为 `queued`。同一 `database_now` 事务把 execution `queued -> running`、Job `queued -> running` 并追加唯一 running Step；execution.`started_at` 为空时写 `database_now`，retry 已有值时保留首次开始时间。
- Worker 正常完成最后一步时，同一事务把 Step 置为 `succeeded`、Job 置为 `succeeded`、execution `running -> pending_finance_review`；execution.`completed_at` 继续为空，只有后续人工状态机真正进入 `completed` 时写入。
- Worker 执行失败时，同一事务把 Step 与 Job 置为 `failed`、execution `running -> failed`，共享 `database_now` 与稳定安全错误码；execution 写 `failed_at/failure_code`，`failure_reason` 只能是脱敏安全摘要。
- pre-claim dispatch finalizer 只在 execution 与 Job 都为 `queued` 时把二者原子置为 `failed`，不写 `started_at` 或伪造 Step，并写同一 `failed_at/finished_at` 与安全 dispatch code。
- `AUDIT-007` 的 `failed -> queued` 同时清空 execution 当前 `failed_at/failure_code/failure_reason` 与 Job 当前失败投影，保留 execution.`started_at`、冻结快照和已提交确定性结果；历史失败仍由 append-only Job Step/operation evidence 保留。
- 以上行为属于第 6.2 节 runtime Gate，不是 007 空表 DDL/ORM 已实现证据。

### 4.3 AUDIT-008 条件式 Job CAS

`AUDIT-008` Body 在既有 `reason` 外增加必填但可空的 `row_version: positive integer|null`，其值只表示 Job 版本，不新增 `audit_task_executions.row_version`：

- `draft/validating` 必须尚无 Job，`row_version` 必须为 null。事务锁定 execution、复核状态并直接写 `cancelled/cancelled_at`；不伪造 Job、Step 或 Job 版本。
- `queued/running` 必须已有唯一活动 Job，`row_version` 必须非空且匹配当前 Job。
- queued 取消在同一事务把 Job 与 execution 直接置为 `cancelled`，不创建当前 attempt Step。
- running 取消在同一事务把 Job 置为 `cancel_requested`；execution 保持 `running`。Worker 在安全检查点用当前 fencing tuple 同事务把当前 Step、Job 与 execution 终结为 `cancelled`，共享同一 `database_now`。
- 本接口、Worker checkpoint 与 audit Job finalizer 必须遵守第 4.2 节分类、锁序、状态前像和 affected-row 门禁；AUDIT-007/008 的客户端 fencing 值只来自 Job `row_version`。
- 同一 `Idempotency-Key` 与相同请求 hash 的 replay 只复用首次请求绑定，不重复 mutation 或 operation log；它必须重读 execution/Job 并返回当前权威动作投影，因此首次 `cancel_requested` 后由 Worker 完成的 replay 返回 `cancelled`。不同请求 hash 仍返回 `IDEMPOTENCY_CONFLICT`，不得同时要求返回首次静态响应体。

响应固定包含 `execution_id/status/cancelled_at/job_id/row_version`；`status` 是取消动作投影 `cancel_requested|cancelled`。无 Job 路径的 `job_id/row_version` 均为 null；有 Job 路径均非空。状态与 nullability 不匹配或 Job CAS 0 行返回 409 `JOB_VERSION_CONFLICT`，不得用 execution 缓存代替 Job fencing。

### 4.4 OPS-001 与页面模型

- `OPS-001` Job item 增加权威 `row_version` 和只读派生 `retryable`。
- UI Job 模型同步两字段；重试/取消动作只能携带最近一次 OPS-001 或动作响应返回的 Job `row_version`。
- draft/validating 的 execution-only 取消必须显式发送 `row_version=null`，不得生成假 Job 版本。
- FILE/AUDIT 重试页面只使用后端固定 scope、状态和错误码，不从错误文案推断可重试性。
- 不新增 API path、页面、路由或前端自行维护的 retry 状态。

## 5. 空表 DDL/ORM 与分层授权

R2 获批并完成第 6 节定义的 11 文件原子 baseline 同步后，唯一允许的 reliability revision 固定为：

```text
revision=20260807_007
down_revision=20260807_006
file=backend/alembic/versions/20260807_007_create_reliability_core.py
```

该 revision 的授权范围只有：

- 同一 revision 按 `async_jobs -> async_job_steps -> outbox_events` 创建三张空表；
- 创建 R1+R2 effective contract 的完整列、CHECK、FK、唯一/部分索引、触发器及四个固定 trigger functions；
- 创建对应 SQLAlchemy ORM 模型与必要导出；
- 不播种 Job、Step、Outbox、Registry、Policy 或业务行；
- 允许离线 SQL/ORM 检查及本地或专用可丢弃合成 PostgreSQL 16 测试，测试数据只存在于可重建测试库；
- 空表 downgrade、锁超时、非空 fail-closed、约束与并发测试。

该授权不要求 CR-011-R3 或生产 Handler artifact 先获批，因为空表 migration 不读取 Registry、Schema、Broker 或 AI 制品。测试可使用 manifest 固定、测试目录专属的 synthetic Registry/Input/Summary Schema 证明通用 Loader/约束行为，但它们不得进入应用 Settings、发布包或任何非测试环境，也不构成生产 artifact 批准。

以下内容保持 `PENDING / NOT AUTHORIZED`：

- 生产 Registry、Registry Schema、Input/Summary Schema bundle 与 Handler manifest；
- 真实 Job/Step/Outbox 写入；
- Repository、Service、API Router、Handler Loader runtime、Worker task、Dispatcher、reaper、Scheduler；
- FILE-007、AUDIT-007、AUDIT-008、OPS-001 运行时；
- Redis/Broker socket、AI sequence 3、AI-005、operation log/action registry runtime；
- 真实数据、Provider 或其他网络、部署、canary、production migration。

实施并通过授权 Gate 后，只可记录 `BASE-005=13/57`；`BASE-006` 仍为 `partial`，P0 与全部 AC 状态不变。

## 6. 九份 Request、正式 baseline manifest 与 active-baseline pin 原子同步及验收

批准后的同步目标必须恰为：

1. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
2. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
5. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
7. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
8. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
9. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`

同步前正式 manifest 绑定固定为：

```text
path=docs/baseline-manifest.md
raw_bytes=1619
raw_sha256=c1058b63cc256f866dd28ef4662078ecedc26351b4f08e9e906acf6765b81ffe
```

唯一获准机械 re-pin 的源文件 pre identity 固定为：

```text
path=backend/app/approval_pre_meta.py
raw_bytes=22193
raw_sha256=db85d914ff13dca797e6e44bcb5d89cece7ec8720937e483f123e12171107524
allowed_change=_BASELINE_IDENTITY.byte_length|_BASELINE_IDENTITY.sha256
```

`backend/tests/unit/test_approval_pre_meta.py` 不修改；它必须在 re-pin 后用 post-sync manifest 实际通过。生成顺序固定为：在临时区生成九份 Request post bytes，计算九项 post identity，生成正式 manifest，计算 manifest identity，最后只替换上述两个 `_BASELINE_IDENTITY` literal；验证成功后再一次性替换 11 个目标文件。任何中间结果不得被 runtime 或其他任务读取。

其九项 pre-sync Request identity 固定如下；hash 使用小写列示，但比较 manifest 的显示值时必须先严格解码为 32 bytes，不以大小写字符串差异制造假冲突：

| Request path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 124040 | `4a4f431a421a89b72c9586b5eb0e4b154856713dbb38f83e42456e568bf5e308` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 85605 | `5965ac96480919a3d5ac46c4a20e3fbeda5fbdc39fc6fb36cab06359c27352dc` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 109489 | `4e3d540fc345ce2b155e84fd862d9a3d3d98f119c80180c693df4367efb1942d` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 324511 | `fa277147a8af6f5d5d0f96bd34170440f2b55be8450aa1f49a845b13e69ac4d0` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 80792 | `d5c53be941ce45652111f7a75dcca93426dbc5d915a64a14fbdd37f5c5d96e89` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 48655 | `f83e4e41ed1a3a51909a745f4726a16243295c3164879143b7ef0e04c9d270fe` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 46602 | `5471739020734eb1fad0c9c4e493d46ac5d4f6a372b23b1b46ae691342fa91c3` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 51144 | `c3526c75899dd136db1369a2b420972b5a2f70f8640b977ca22d9502c8193e2f` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 103607 | `7a032de9a6fefdb01877d865746715ccb8ef39c449b6d69b14cb403be2be8bae` |

领域投影固定为：

- SRS：Job/Step/Outbox、attempt 起点、派生 `retryable`、非权威 wake-up 与计数零变化。
- 架构：删除 `async_jobs.retryable/idempotency_key` 持久列要求；同步 Registry/queue/task 公式、严格 kwargs、Outbox identity 与 current attempt 起点。
- 数据库：同步三表完整列、状态矩阵、索引、四函数/trigger、DELETE+TRUNCATE 和 007 ownership。
- API：同步 FILE-007、AUDIT-007、AUDIT-008、OPS-001；新增且只新增 `JOB_VERSION_CONFLICT`；AUDIT-008 同 key/hash replay 返回当前取消投影，不返回陈旧首次响应体。
- 页面：同步 Job `row_version/retryable`、条件取消和后端 scope 门禁。
- AI：只同步 sequence 3 与 CR-011 的精确阻塞边界，不批准 CR-011 或 AI runtime。
- 测试：把 007 schema/PG16 Gate 与后续 production Handler/runtime Gate 分开。
- 部署：同步 publish `retry=False`、logical-to-physical queue、数据库时钟/Lease、downgrade；production 继续未授权。
- 计划：BASE-005 增加 007 三表空 DDL/ORM 切片；BASE-006 runtime 继续等待已批准 Handler artifact 与其他正式前置。

九份 Request、上述同一路径 `docs/baseline-manifest.md` 与 `backend/app/approval_pre_meta.py` 必须全有或全无地同步。每份 Request 内只保留一条 `CR-004-R2 / 2026-08-09 / approved contract scope` 修订记录，不得写入该文件自身的 post length/hash；九份 pre identity 由本节静态表固定，九份 post identity 只由更新后的正式 manifest 记录。manifest 必须仍恰好列出九份 Request并明确 CR-004-R2 已批准同步；manifest 自身及 re-pin 源文件的 post raw byte length/hash另写入 CR-004-R2 第 9 节动态状态和外部跟踪证据，不得自嵌。任一领域投影、Request/manifest/re-pin 写入失败、pre/post hash 不匹配、manifest 条目漂移、re-pin 超出两个 literal 或静态/全量测试失败，都必须回滚 11 个文件的整个同步集合，不得留下部分生效状态。

同步静态 Gate 必须证明 `approval_pre_meta.py` 的 diff 只含 `_BASELINE_IDENTITY` 两个 literal，`test_current_pre_meta_contract_passes` 对 post manifest 通过，14 个既有 snapshot/三类 Schema identity 与 CLI `APPROVAL/REGISTRY_PIN/SIGNATURES=OUT_OF_SCOPE_NOT_EVALUATED`、`REQUEST_SYNC/NETWORK/PRODUCTION=NOT_AUTHORIZED` 输出逐字不变；该 PASS 只表示独立静态 identity 均有效，不构成 R2 downstream fact-set 或 approval 验证。

### 6.1 007 schema Gate

- 开始时 Alembic 唯一 head 精确为 `20260807_006`，成功后唯一 head 为 `20260807_007`；核心表从已实现 10/57 变为 13/57。
- 三表、四函数、全部列/约束/索引/trigger 与 ORM 定义精确一致；无第四张表、额外 helper 或 seed。
- 在 PostgreSQL 16 上执行 `006 -> 007 -> 006 -> 007` 和既有 base/current-head 往返；空表 downgrade 按 R1 固定锁序、`lock_timeout='5s'`、`55P03` 与 `55000` 语义，无 `CASCADE`、无残留对象。
- 真实约束覆盖 Job 全状态/字段矩阵、每次写入 `row_version` 恰增一、`current_attempt_start_step_code` 格式、absolute `step_seq`、Job/Step 提交时一致性、Lease/时钟字段边界、Outbox 状态/八次上限/安全码字段组合、Step/Outbox UPDATE 白名单、终态不可变、DELETE 和 TRUNCATE。这里仅证明数据库可强制的不变量，不把直接 SQL probe 冒充 Repository/Worker 实现。
- 双连接只验证数据库唯一/锁约束：活动 Job 部分唯一、同 attempt running Step 唯一、Outbox aggregate sequence/event identity 唯一、并发终态不可变与 downgrade 锁超时。所有错误输出不得回显正文、连接串、凭据、Broker 自由文本或原始 DB exception。
- 聚焦与全量 backend pytest、Ruff、format、mypy、离线网络门禁和现有资产门禁全部通过。Redis/Broker/Provider socket 仍不得打开。

### 6.2 后续 runtime Gate

以下 Gate 继续 `NOT_RUN / PENDING`，不得用于宣称本 R2 或 007 已实现：

- production Registry/Schema/Input/Summary/Handler bundle 的生成、独立复核与批准；
- Loader 与已安装 Handler identity、Job 创建、FILE/AUDIT/OPS API，以及 execution/Job/Outbox 固定锁序；
- Repository 生成的 expected `row_version`/完整 fencing tuple CAS、stale Worker 0 行、并发终结/取消与实际幂等投影；
- Celery protocol v2 的 task/args/kwargs/embed/delivery-info decode、Worker 启动时 logical-to-physical consumer queue 配置与实际消费队列集成证明、真实 Dispatcher 单 claim、Worker claim、reaper、Job-aware finalizer、Broker 调用历史分类与 Redis 故障恢复；
- CR-011/AI sequence 3、AI-005、operation log/action registry；
- 业务 E2E、浏览器、真实数据、部署、canary 与 production。

## 7. 审批边界与记录格式

本 CR 必须由以下九角色共同批准；一人具备多角色权限时可合并一条记录，但必须逐项列明：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | REL-D-001～005、FILE/AUDIT/OPS 用户语义与九份 Request 同步 |
| 架构 | Job/Step/Outbox、Registry/queue/task、wake-up identity 与依赖分层 |
| 数据/DBA | 三表列/约束/触发器、时钟/Lease、CAS、007 与 downgrade |
| 后端/API | 重试/取消响应、Handler Loader 边界、Job/Outbox 仓储语义 |
| 前端/UI | Job `row_version/retryable`、条件取消和不推断状态 |
| AI/RAG | REL-D-004、CR-011 兼容性与 AI runtime 非授权边界 |
| 测试/质量 | Request 原子同步、007 PG16/并发/失败路径与证据边界 |
| 运维/可靠性 | queue、publish retry、Lease/reaper/dead-letter、回退和恢复 |
| 安全 | 最小载荷、严格类型、安全错误码、脱敏、网络/生产边界 |

审批记录必须包含：

```text
姓名
角色
decision=APPROVED|REJECTED
selected_decisions
rejected_decisions
cr_revision=CR-004-R2
base_revision=CR-004-R1
base_decision_snapshot_sha256=387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6
decision_snapshot_sha256
environment_scope=contract
handler_registry_scope=meta_contract_only
handler_registry_version=PENDING
handler_registry_sha256=PENDING
handler_registry_schema_version=PENDING
handler_registry_schema_sha256=PENDING
input_schema_bundle_status=PENDING
summary_schema_bundle_status=PENDING
CR-011_dependency_revision=CR-011-R3
CR-011_dependency_decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be
CR-011_dependency_artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c
CR-011_dependency_status=NOT_APPROVED|REQUEST_SYNC_NOT_AUTHORIZED|REQUEST_NOT_SYNCHRONIZED|AI_RUNTIME_BLOCKED
baseline_manifest_pre_raw_sha256=c1058b63cc256f866dd28ef4662078ecedc26351b4f08e9e906acf6765b81ffe
approval_pre_meta_pre_raw_sha256=db85d914ff13dca797e6e44bcb5d89cece7ec8720937e483f123e12171107524
approval_pre_meta_repin_scope=_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY
authorized_scope=exact_nine_request_plus_baseline_manifest_sync|approval_pre_meta_active_baseline_identity_repin_only|20260807_007_empty_ddl_orm|local_or_disposable_synthetic_pg16
日期
证据链接
备注
```

本轮不得出现 `handler_registry_scope=approved_artifact`，不得预填任何生产 Registry/Schema/Handler hash。任一角色留空、拒绝、范围互斥或使用不同 R1/R2 snapshot 时，整体保持 `NOT APPROVED`。

批准只可授权九份 Request、正式 `docs/baseline-manifest.md` 与 `approval_pre_meta.py::_BASELINE_IDENTITY` 两个 literal 的 11 文件原子同步、`20260807_007` 空表 DDL/ORM 与本地/专用可丢弃合成 PostgreSQL 16 Gate；不授权其他 verifier 逻辑、生产 Handler/Job runtime、Redis/Broker/Provider 网络、真实数据、部署或 production。CR-011-R3 仍须独立批准；第 3.8 节列出的旧下游候选必须先升版且不构成 007 空表 DDL 前置。

## 8. Snapshot 算法与静态验收

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次。
4. preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256 小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定第 1 节 R1 base tuple。在首条有效 approval record、Request sync authorization 或下游消费证据形成后，第 1～8 节任一 byte 变化必须提升 `CR-004-R3` 并使旧 R2 签署失效；在三者均为零的 review 阶段可以保留 R2 修订本文，但旧 unsigned review hash 必须显式撤回、重新生成 snapshot 并执行全量独立复审。第 9 节动态更新不改变 decision snapshot。
7. 生成前至少机械复核：R1 base tuple、五项 decision universe、九角色、九份 Request 路径、累计 delta、三表/四函数、Registry exact keys、七队列、strict integer、current attempt 起点、Celery task/outbox identity、CR-011 candidate identity、007/006 lineage和全部非授权边界。
8. 生成 snapshot 只建立可签署对象，不等于批准；在有效审批记录产生前，不得同步 Request 或创建 007。

## 9. 当前状态

全部九个必需角色已由 `APR-20260809-YHBX-CR004R2` 在 `environment_scope=contract` 范围明确批准。本节只位于 decision snapshot 之外的动态区；第 1～8 节及其 snapshot 未改写。

### 9.1 九角色决策矩阵

| 决策 | 需求/产品 | 架构 | 数据/DBA | 后端/API | 前端/UI | AI/RAG | 测试/质量 | 运维/可靠性 | 安全 |
|---|---|---|---|---|---|---|---|---|---|
| REL-D-001 | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] |
| REL-D-002 | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] |
| REL-D-003 | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] |
| REL-D-004 | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] |
| REL-D-005 | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] | APPROVED [APR-CR004R2] |

### 9.2 APR-20260809-YHBX-CR004R2

| 字段 | 批准记录 |
|---|---|
| 姓名 | YHBX（BOSS） |
| 角色 | 需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全 |
| decision | `APPROVED` |
| selected_decisions | `[REL-D-001,REL-D-002,REL-D-003,REL-D-004,REL-D-005]` |
| rejected_decisions | `[]` |
| cr_revision | `CR-004-R2` |
| base_revision | `CR-004-R1` |
| base_decision_snapshot_sha256 | `387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6` |
| decision_snapshot_sha256 | `77a8a2e63a4668a5e7e6a028b18cc04f34ddc824d04096db8bede7bce844241b` |
| environment_scope | `contract` |
| handler_registry_scope | `meta_contract_only` |
| handler_registry_version | `PENDING` |
| handler_registry_sha256 | `PENDING` |
| handler_registry_schema_version | `PENDING` |
| handler_registry_schema_sha256 | `PENDING` |
| input_schema_bundle_status | `PENDING` |
| summary_schema_bundle_status | `PENDING` |
| CR-011_dependency_revision | `CR-011-R3` |
| CR-011_dependency_decision_snapshot_sha256 | `b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` |
| CR-011_dependency_artifact_manifest_sha256 | `f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` |
| CR-011_dependency_status | `NOT_APPROVED\|REQUEST_SYNC_NOT_AUTHORIZED\|REQUEST_NOT_SYNCHRONIZED\|AI_RUNTIME_BLOCKED` |
| baseline_manifest_pre_raw_sha256 | `c1058b63cc256f866dd28ef4662078ecedc26351b4f08e9e906acf6765b81ffe` |
| approval_pre_meta_pre_raw_sha256 | `db85d914ff13dca797e6e44bcb5d89cece7ec8720937e483f123e12171107524` |
| approval_pre_meta_repin_scope | `_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY` |
| authorized_scope | `exact_nine_request_plus_baseline_manifest_sync\|approval_pre_meta_active_baseline_identity_repin_only\|20260807_007_empty_ddl_orm\|local_or_disposable_synthetic_pg16` |
| 日期 | 2026-08-09 |
| 证据链接 | 本 Codex task 的本条批准消息 |
| 备注 | 仅授权十一文件原子同步、`20260807_007` 空表 DDL/ORM，以及本地或专用可丢弃合成 PostgreSQL 16 验证；不授权生产 Handler/Job runtime、Redis/Broker、真实数据、Provider 网络、部署、canary 或 production。 |

### 9.3 十一文件同步证据

下表是 strict UTF-8、无 BOM、LF-only post raw identity。九份 Request 各有且仅有一条 `CR-004-R2 / 2026-08-09 / approved contract scope` 修订记录；正式 manifest 恰列九项并匹配全部 post bytes。

| Request 文档 | byte length | raw SHA-256 |
|---|---:|---|
| `FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 127311 | `28f71bde8257c99af4be8f6bee7414d3f147258949795348572422ae6715ab88` |
| `FinAudit_Agent_系统架构设计说明书_V1.0.md` | 88992 | `ff3a3a66dae560009e2ae35af677f6b6b71ff4f4c1a5359352d51b7886903214` |
| `FinAudit_Agent_数据库设计说明书_V1.0.md` | 114800 | `5b7783fe1230d9c1e3df3a5cd27ca325a4e79850d65c20b957aca902baeba56f` |
| `FinAudit_Agent_API接口设计说明书_V1.0.md` | 327158 | `1a00bf91e7c3c543685db815054dbbc9558b9277962b52fd61ac2609eab103b2` |
| `FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 82514 | `5964160ee0d4e814c2dc92c00ae1c8b48d70864504502c6dbb9b966e578ecc40` |
| `FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 50039 | `7e8dbdff494815e61f6d0fe48a7787bd9aa9046ce99f8b028cfbc59e5483ffb0` |
| `FinAudit_Agent_测试与验收方案_V1.0.md` | 48590 | `f0d1ce76986df85405984d2b3a6ce3fb99c6963b46c8c9bd7b9d92d51ef3466e` |
| `FinAudit_Agent_部署与运维说明书_V1.0.md` | 53183 | `0f223f98c8a674905a40650b394fd704828491d8b47c5957e385509d1cd91108` |
| `FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 105222 | `9bf8b51593260ddbabe9f7557fc9726fb11331d9feda250a4f52042ed73b00a0` |

| 同步配套文件 | post byte length | post raw SHA-256 |
|---|---:|---|
| `docs/baseline-manifest.md` | 1633 | `d833c568277fae4f3b74f520acb31dfd58d8caaafad67fdaee1b1d54740d08b7` |
| `backend/app/approval_pre_meta.py` | 22193 | `f76f5f59f99a95d088990820fdd1b50124e6caa24bcfaa12dfe0946a947a99fd` |

`approval_pre_meta.py` 的机械 diff 只把 `_BASELINE_IDENTITY.byte_length` 从 `1_619` 换为 `1_633`，并把 SHA-256 从 pre manifest 换为上表 post manifest；逆替换后精确重建 pre identity `22193/db85d914ff13dca797e6e44bcb5d89cece7ec8720937e483f123e12171107524`。`_SCHEMA_IDENTITIES`、`_SNAPSHOT_IDENTITIES`、数量、角色/fact-set 与 CLI 输出全部未改。

### 9.4 静态验收与生命周期

- `backend/tests/unit/test_approval_pre_meta.py::test_current_pre_meta_contract_passes` 与 CLI scope 测试：`2 passed`。
- pre-meta CLI：`APPROVAL_PRE_META_STATIC=PASS`，`SNAPSHOTS_VERIFIED=14`，`SCHEMAS_VERIFIED=3`，`BASELINE_VERIFIED=1`；`APPROVAL/REGISTRY_PIN/SIGNATURES=OUT_OF_SCOPE_NOT_EVALUATED`与 `REQUEST_SYNC/NETWORK/PRODUCTION=NOT_AUTHORIZED` 的 legacy 静态输出逐字不变。该 CLI 不评估本节的人工批准或同步事实。
- `scripts/verify-baseline.ps1`：`BASELINE_LOCAL_VERIFY=PASS`；remote branch protection 因无 remote 保持 `NOT_RUN`，不是本 contract sync 的失败。
- `20260807_007` 空 Job/Step/Outbox DDL/ORM 已在本批准的有限范围内实现。显式 `scripts/verify-postgresql-current-head.ps1` 在 PostgreSQL 16.14（`server_version_num=160014`）上连续两轮均通过 51/51 项、`POSTGRESQL_CURRENT_HEAD=PASS`，标记容器残留为 0。
- 默认 `scripts/verify-local-offline.ps1` 另行通过：Backend `1317 passed / 35 skipped`、Ruff/format `107`、Mypy `62`、pip 一致性、Frontend `216`、typecheck/build 均 PASS。该默认门禁故意不设置 `TEST_DATABASE_URL`，因此 PostgreSQL current-head 在这次运行中保持 `NOT_RUN`；Compose/browser/Provider/remote/production 也仍 `NOT_RUN`。它与上述显式 PostgreSQL 16 Gate 是两类独立证据。

| 项目 | 状态 |
|---|---|
| R1 base binding | `VERIFIED / NO STANDALONE R1 APPROVAL` |
| R2 `REL-D-001..005` effective selection | `APPROVED / APR-20260809-YHBX-CR004R2` |
| R2 decision preimage bytes | `39646` |
| R2 decision snapshot SHA-256 | `77a8a2e63a4668a5e7e6a028b18cc04f34ddc824d04096db8bede7bce844241b` |
| R2 decision snapshot | `APPROVED / EFFECTIVE CONTRACT BINDS R1 BASE + R2 ADDENDUM` |
| Prior unsigned R2 review snapshots | `WITHDRAWN / NOT APPROVABLE / NOT CONSUMABLE` |
| Handler Registry meta contract | `APPROVED / META CONTRACT ONLY` |
| Registry/Schema/Input/Summary/Handler artifact | `PENDING / NOT GENERATED / NOT APPROVED` |
| CR-011-R3 | `NOT APPROVED / REQUEST SYNC NOT AUTHORIZED / REQUEST NOT SYNCHRONIZED / AI RUNTIME BLOCKED` |
| 九份 Request + 正式 baseline manifest + active-baseline pin sync | `COMPLETED / POST IDENTITIES RECORDED / STATIC GATES PASS` |
| `20260807_007` | `IMPLEMENTED / EMPTY DDL/ORM / SYNTHETIC PG16 51/51 x2 PASS` |
| Job/Dispatcher/Worker/API runtime | `NOT AUTHORIZED / NOT IMPLEMENTED` |
| Redis/Broker/Provider/其他网络 | `NOT AUTHORIZED / NOT RUN` |
| 真实数据/部署/canary/production | `NOT AUTHORIZED / NOT RUN` |
