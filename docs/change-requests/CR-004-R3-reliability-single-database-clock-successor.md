# CR-004-R3：可靠性单一数据库时钟实现门禁 closure

> 文档类型：`CR-004-R2` 的最小 successor problem/decision closure  
> 修订：`CR-004-R3`  
> 日期：`2026-08-11`  
> 静态性质：versioned contract candidate；生命周期状态表只记录在第 8 节  
> 非目标：不修改 predecessor、Request、既有 migration、代码、测试或证据文档；不生成 snapshot、approval、对象 profile、migration 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-004-R2-reliability-contract-closure.md` |
| `base_revision` | `CR-004-R2` |
| `base_raw_bytes` | `48294` |
| `base_raw_sha256` | `71e2a6c765d00c94cbbdd7b591af4c6d9e45e4ced857de03fbdc24bdab43f67e` |
| `base_decision_preimage_bytes` | `39646` |
| `base_decision_preimage_sha256` | `77a8a2e63a4668a5e7e6a028b18cc04f34ddc824d04096db8bede7bce844241b` |
| `successor_revision` | `CR-004-R3` |

`CR-004-R3 effective contract` 仅表示上述精确 R2 decision preimage 加本文件第 1～7 节 addendum preimage。两份 identity 必须分别验证；不得继承 R2 动态状态区或拼接 bytes 发明第三个 hash。未被本文件覆盖的 R1+R2 条款原样继承。

R2 的 `REL-D-001..005` 全部保留。本 revision 只新增：

```text
REL-R3-D-001=ONE_DATABASE_NOW_FOR_EVERY_TIME_BEARING_RELIABILITY_TRANSITION
REL-R3-D-002=IMPLEMENTATION_BLOCKED_UNTIL_EXACT_FUNCTION_TRIGGER_ACL_PROFILE
REL-R3-D-003=AUDIT_EXECUTION_BRANCH_NOT_APPLICABLE_UNTIL_OWNER_TABLE
```

## 2. 已确认缺口与决策结果

当前 007 制品为 `backend/alembic/versions/20260807_007_create_reliability_core.py`，身份 `65444/8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df`，`revision/down_revision=20260807_007/20260807_006`。其中 `public.enforce_async_jobs_state_v1()`、`public.enforce_async_job_steps_state_v1()` 与 `public.enforce_outbox_events_state_v1()` 分别独立调用 `clock_timestamp()`。事务、writable CTE 或 deferred constraint trigger 都不能把这些独立 trigger invocation 自动变成同一个数据库时间。

R2 同时冻结“只存在四个 trigger functions、禁止第五个 helper”和“每个转换只捕获一次数据库时钟”。在没有精确 transition function、签名、owner、security、search path、ACL 与直接 DML profile 时，直接宣称新增统一入口会越过已批准对象所有权；保留现状又不能满足单一时钟。因此本 R3 的决策结果是：冻结完整问题范围并关闭隐式解释，实施 Gate 保持失败关闭；本文件本身不选择或授权一个猜测性 runtime API。

## 3. 全部 time-bearing transition 范围

下表每一行都是一个独立原子转换。未来获批实现必须让该行只经过其 profile 登记的唯一数据库入口，在锁定并复核前像后恰好取得一次 `database_now := clock_timestamp()`，并把该值用于该行全部时间谓词和时间字段。不同表、trigger、Repository statement 或应用时钟不得再次取权威时间。

| 原子转换 | 必须同一原子边界覆盖 | `database_now` 的唯一用途 |
| --- | --- | --- |
| Job 创建 + dispatch Outbox | `async_jobs INSERT` + `outbox_events INSERT` | Job/Outbox `created_at` 与创建时序校验 |
| 通用/业务结果/AI Outbox 创建 | 独立或随权威业务事务执行的 `outbox_events INSERT -> pending` | Outbox `created_at` 与同一事务的创建时序校验；没有已批准 owner/profile 的分支保持 `BLOCKED/NOT_APPLICABLE` |
| queued claim | Job CAS + 首个 running Step | Job `started_at/heartbeat_at/lease_expires_at` 与 Step `started_at` |
| running/cancel-requested heartbeat | Job fencing CAS | `heartbeat_at`、`lease_expires_at` 与 Lease 未到期谓词 |
| stage advance | 当前 Step 终结 + 下一 Step 创建 + Job stage CAS | 当前 `finished_at`、下一 `started_at`、Job `heartbeat_at/lease_expires_at` |
| success terminal | 当前 Step + Job 终结 | 两者同一 `finished_at` 与 Lease 谓词 |
| fail terminal | 当前 Step + Job 终结 | 两者同一 `finished_at`，可重试时 `next_retry_at=database_now` |
| failed retry + dispatch Outbox | Job `failed->queued` + Outbox INSERT | retry eligibility 与 Outbox `created_at`；不创建 Step |
| queued cancel | Job `queued->cancelled` | Job `finished_at`；不创建当前计划 Step |
| running cancel request | Job `running->cancel_requested` | Lease 未到期谓词；既有时间/fencing 原样保留 |
| running cancel finalization | 当前 Step + Job `cancel_requested->cancelled` | 两者同一 `finished_at`；checkpoint/reaper Lease 谓词 |
| pre-claim dispatch finalizer | Outbox dead-letter + 条件式 queued Job failure | Outbox 终结判断与 Job `finished_at`；不伪造 Step |
| Lease recovery | 旧 Step 终结 + Job recovery/terminal + 条件式新 Step | 旧 `finished_at`、新 `started_at/heartbeat_at/lease_expires_at` 与 grace 谓词 |
| Outbox claim | `pending|failed->processing` CAS | claim eligibility 与 `next_attempt_at=database_now+60s` |
| Outbox reaper | 过期 processing CAS | expiry 谓词、retry `next_attempt_at` 或 exhausted dead-letter |
| Outbox publish | `processing->published` CAS | `published_at` |
| Outbox failure | `processing->failed` 或 `processing|failed->dead_letter` CAS | 可恢复失败只计算 retry `next_attempt_at`；仅 `job.dispatch.requested` 的 dead-letter 分支复用上文 `pre-claim dispatch finalizer` 原子语义 |

捕获 `database_now` 后禁止 Broker、Redis、Provider、文件或其他外部 I/O。Broker publish 必须发生在 Outbox claim 提交后、publish/failure 转换调用前，不能嵌入数据库函数。任一前像、CAS、fencing、affected-row、时间或相等关系不匹配时整行转换零部分写入。

## 4. 当前数据库对象与 ACL 精确 delta

本 R3 是 problem/decision closure，不是对象 profile。为避免把“候选修复”伪装成授权，当前 exact delta 固定为零：

| schema-qualified 对象 | R3 动作 | owner/security/search_path/ACL delta |
| --- | --- | --- |
| `public.enforce_async_jobs_state_v1()` | `RETAIN / NOT REPLACED` | `NONE` |
| `public.enforce_async_job_steps_state_v1()` | `RETAIN / NOT REPLACED` | `NONE` |
| `public.enforce_job_step_consistency_v1()` | `RETAIN / NOT REPLACED` | `NONE` |
| `public.enforce_outbox_events_state_v1()` | `RETAIN / NOT REPLACED` | `NONE` |
| new reliability transition function | `NONE / NOT AUTHORIZED` | `NONE` |

| schema-qualified trigger | R3 动作与既有绑定 |
| --- | --- |
| `public.trg_async_jobs_state_v1` | retain `BEFORE INSERT OR UPDATE -> public.enforce_async_jobs_state_v1()` |
| `public.trg_async_jobs_consistency_v1` | retain deferred constraint trigger `-> public.enforce_job_step_consistency_v1()` |
| `public.trg_async_job_steps_state_v1` | retain `BEFORE INSERT OR UPDATE OR DELETE -> public.enforce_async_job_steps_state_v1()` |
| `public.trg_async_job_steps_no_truncate_v1` | retain `BEFORE TRUNCATE -> public.enforce_async_job_steps_state_v1()` |
| `public.trg_async_job_steps_consistency_v1` | retain deferred constraint trigger `-> public.enforce_job_step_consistency_v1()` |
| `public.trg_outbox_events_state_v1` | retain `BEFORE INSERT OR UPDATE OR DELETE -> public.enforce_outbox_events_state_v1()` |
| `public.trg_outbox_events_no_truncate_v1` | retain `BEFORE TRUNCATE -> public.enforce_outbox_events_state_v1()` |

ACL delta 也恰为零：本 R3 不 `CREATE/ALTER/DROP FUNCTION`，不改变四函数 owner、`SECURITY INVOKER/DEFINER`、volatility、`search_path` 或 `PUBLIC` EXECUTE，不向 `finaudit_app_rw`/`finaudit_worker_rw` GRANT function EXECUTE，也不对三表 GRANT/REVOKE `SELECT/INSERT/UPDATE/DELETE/TRUNCATE`。因此本 R3 不建立直接 DML 防绕过边界，Job/Dispatcher/Worker runtime 必须保持 `BLOCKED`；任何实现者都无权自行补一个第五函数、JSONB 万能入口、Session GUC、临时表或私有 helper。

## 5. audit execution 边界

当前 accepted migration 链没有 `audit_task_executions` 物理表。故本 R3 只定义通用 `async_jobs/async_job_steps/outbox_events` 的单时钟问题；所有 `resource_type='audit_task_execution'` 的 claim、stage、terminal、retry、cancel 和 pre-claim finalizer 均为 `BLOCKED / NOT_APPLICABLE`。

未来只有在该表的 owner migration 与状态投影合同另行获批、成为实际前置后，新的 CR-004 successor 才能定义 execution + Job + Step + Outbox 的统一入口、锁序、ACL 和单一 `database_now`。本 R3 不宣称三表或四表 audit 原子闭合。

## 6. 后续 exact object-profile Gate B

解除 `REL-R3-D-002` 必须另升 CR-004 revision，并在 decision preimage 中同时给出以下唯一机器事实；缺一项即 `NO-GO`：

1. 每个第 3 节转换映射到哪个 schema-qualified database entrypoint，且每行只能命中一项。
2. 每个新增/替换 function 的 exact identity、完整 typed signature、return type、owner、language、volatility、parallel、`SECURITY INVOKER|DEFINER`、固定 `search_path` 与 function-body allowlist。
3. 对 R2“四 trigger functions、无第五 helper”的逐对象 override：哪些 body 被替换、哪些保留、是否新增非-trigger transition function，以及升级后允许的完整 function 集合。
4. `PUBLIC`、`finaudit_app_rw`、`finaudit_worker_rw` 与 owner 的 exact function/type/table ACL；直接 DML、SET ROLE、继承 membership 与 owner 旁路的失败关闭证明。
5. exact typed operation/request schema。单一 `text,jsonb` 万能入口若没有逐 operation closed-key/type/nullability schema、未知键拒绝和 server-owned time/identity 禁止输入，不得批准。

Gate B profile 获批前，Repository/Worker 不得以多条 DML、客户端 timestamp 或当前三个独立 trigger clock 实现任何第 3 节转换。

## 7. migration、回滚与测试边界

本 R3 的 migration/upgrade/downgrade 均为 `NOT AUTHORIZED / NOT APPLICABLE`。当前 `20260807_009 / 18 TABLES` 只是 checkout 观测，不是授权，不预占未来 revision/down_revision，也不允许改写 007。

未来 exact object profile 至少还必须冻结并验证：actual unique head 上的 forward-only migration；三表空且按 Job→Step→Outbox、`lock_timeout='5s'` 的升级/回滚门禁；四函数/全部 trigger/pre-post ACL 的 catalog identity；无第五未登记 helper；失败事务零混合对象；PostgreSQL 16 `upgrade->downgrade->upgrade`；第 3 节每行正常、等值边界、过期、CAS 0、并发仅一方成功和零部分写入。Audit 用例只能报告 `BLOCKED/NOT_APPLICABLE`，不得计入通用三表 PASS。

历史 current-head PASS、静态 SQL、ORM 或 Mock 均不证明本时钟缺口已修复，也不构成 Dispatcher/Worker/真实业务链、部署、UAT 或 AC 证据。

## 8. 当前动态状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `PROPOSED / NOT APPROVED` |
| predecessor identities | `RECORDED / CURRENT CHECKOUT` |
| 007 implementation identity | `RECORDED / CLOCK GAP PRESENT` |
| current unique head observation | `20260807_009 / 18 TABLES / NOT AN AUTHORIZATION` |
| exact function/trigger/ACL profile | `NOT GENERATED / GATE B BLOCKED` |
| audit execution branch | `BLOCKED / NOT_APPLICABLE / OWNER TABLE ABSENT` |
| R3 decision snapshot | `NOT GENERATED` |
| R3 approval | `NOT RECEIVED` |
| Request/manifest | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT GENERATED / NOT AUTHORIZED / NOT RUN` |
| network/real data/deployment/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
