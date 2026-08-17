# CR-003-R2：特权授权数据完整性 active-baseline successor

> 文档类型：`CR-003-R1` 的最小 successor addendum  
> 修订：`CR-003-R2`  
> 日期：2026-08-10  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 9 节  
> 非目标：不改写 R1，不开放账号/权限业务运行时，不处理真实数据，不授权 Provider/其他外网、部署、canary 或 production

对应差异：GAP-034～GAP-037

## 1. 不可变基座、锚点与 effective contract

### 1.1 R1 不可变基座

本 successor 只在下列 R1 decision snapshot 上生效：

| 字段 | 固定值 |
|---|---|
| `base_document_path` | `docs/change-requests/CR-003-privileged-auth-integrity-closure.md` |
| `base_revision` | `CR-003-R1` |
| `base_status_at_successor_creation` | `DRAFT / PROPOSED / NOT APPROVED` |
| `base_status_marker` | exact whole line `## 6. 当前状态` |
| `base_raw_bytes_at_binding` | `24838` |
| `base_raw_sha256_at_binding` | `7ca3e30460b4b2449c40a4ed01faa7cf05dbfaf0232214a0ed612cae43df48d7` |
| `base_decision_preimage_bytes` | `24270` |
| `base_decision_snapshot_sha256` | `cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045` |

`CR-003-R2 effective contract` 的唯一含义是：

```text
exact CR-003-R1 decision snapshot
+ this document sections 1 through 8 successor addendum
```

两份 snapshot 必须分别验证，不得拼接 bytes 后生成未定义的第三个 hash，也不得用 R1 第 6 节动态状态替代 R1 decision snapshot。R1 文件保持 byte-for-byte 不变。

R2 **不是 zero-semantic-delta addendum**。它对以下且仅以下事项形成有优先级的规范覆盖：第 2 节 action-time 资格矩阵；第 3.3 节五个 role code 的 preflight 与后续 mutation 边界；第 3.5 节 `work_package.AUTH-005`、`api.AUTH-005`、API AUTH-011～AUTH-015 的命名区分；第 3.1～3.4 节 008 identity、对象/ACL/storage-schema 范围；以及第 4～8 节 active-baseline 治理、审批和 Gate。上述事项与 R1 冲突时 R2 优先；R1 的其余 D-010～D-014、字段/状态/来源矩阵、锁序、降级和验收语义原样继承。审批选择的是完整 R1 snapshot + R2 addendum，不是只选择 R1 或只选择 008。若实现发现还需改变上述封闭集合以外的 R1 规范条款，必须停止并提升至少 `CR-003-R3`，不得在代码或动态状态区暗改。

### 1.2 已批准上游锚点

R2 不重复审批下列锚点，只绑定其已批准事实：

| 锚点 | revision / marker | decision preimage | decision snapshot | 绑定用途 |
|---|---|---:|---|---|
| `docs/change-requests/CR-001-base005-contract-closure.md` | `CR-001-R2` / `## 8. 审批矩阵` | `22618` | `8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615` | D-006 的双人 break-glass、最长 4 小时、角色 allowlist 与 57 表基线 |
| `docs/change-requests/CR-011-R4-ai-policy-active-baseline-successor.md` | `CR-011-R4` / `## 9. 当前状态` | `27384` | `cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` | 本 R2 创建时 active baseline 的 post-R4 来源身份；不授权 AI runtime |

CR-001-R2 的批准不替代本 R2 九角色审批；CR-011-R4 只提供 active-baseline 来源锚点，不成为 AUTH、数据库或网络运行时授权。

### 1.3 决策全集与累计 delta

R2 不新增 `D-*` alias。审批只能原子选择以下五项，顺序固定：

```text
D-010
D-011
D-012
D-013
D-014
```

其含义逐字继承 R1：

```text
D-010=DECIDED_BY_STATE_CAS;D-011=REVOKE_REASON;D-012=GIST_HALF_OPEN_RANGE;D-013=ENV_INDEPENDENT_SOD;D-014=LONG_TERM_ADMIN_ONLY
```

- `APPROVED` 时，`selected_decisions` 必须逐字等于 `[D-010,D-011,D-012,D-013,D-014]`，`rejected_decisions=[]`，且 `selected_option` 必须逐字等于上面的分号连接值。
- `REJECTED` 时，两数组必须无重复、互斥并按声明顺序精确分区五项全集，且 `rejected_decisions` 非空；`selected_option` 仍逐字保留第 65 行的完整分号串，但它只标识本次被裁决的不可拆分 contract option，不表示五项已获批准，实际选择与拒绝只由两个数组的精确分区表达。
- 缺项、额外项、乱序、别名、只批准空表而不批准 R1+R2 effective contract，或附带扩大运行时/网络/生产范围的条件，均不构成有效批准。

累计 delta 固定为：

| 项目 | R2 effective contract delta |
|---|---:|
| API path | `0` |
| HTTP API error code | `0` |
| P0 核心物理表总数 | `0`，仍为 `57` |
| Gate C 实施后的已实现核心表增量 | `+2`，从当前 `13/57` 到 `15/57` |
| UI page / route | `0` |
| P0 work item | `0` |
| operation-log action | `0` |
| seed row | `0` |
| application/runtime write entry | `0` |

## 2. R2 规范覆盖一：action-time 资格矩阵

### 2.1 覆盖原因

R1 第 2.1.1 节把“请求人、目标用户和所有治理操作者属于请求组织且当前 active”写成统一句子，但没有区分动作发生时间。若把该句应用于所有后续动作，请求人或目标用户在请求创建后被禁用、软删除或离开组织，会使 pending 请求无法拒绝、approved 请求无法撤销，甚至使自然过期依赖已失效历史主体，形成永久卡死。

本节只覆盖这一 action-time 解释：创建与批准必须重验授予资格；拒绝、撤销和过期必须能够安全降权或闭合历史。请求中不可变的 `requested_by/target_user_id/organization_id` 始终是历史事实，不因后续资格变化被改写。R1 的人员分离、CAS、幂等、状态边、数据库时间和锁序继续有效。

### 2.2 唯一资格矩阵

所有“当前”谓词都在取得 R1 要求的锁后，以同一事务捕获的单一 `db_now=clock_timestamp()` 求值；不得使用锁前快照、客户端时间、Header、环境变量或缓存。

| 动作 | 当前 actor 要求 | 请求人/目标用户的 action-time 要求 | 其他锁后要求 | 唯一结果 |
|---|---|---|---|---|
| `create` / AUTH-011 | actor 必须等于 `requested_by`，是请求组织当前有效的长期 `system_admin` | `requested_by` 与目标用户均须当前 `status='active' AND deleted_at IS NULL` 且属于请求组织；仍允许请求人等于目标用户 | 角色代码在 CR-001/R1 allowlist；目标当前不得已有效持有该角色；新行只能为 `pending/row_version=1` | 创建一个 pending 历史事实，不创建 `user_roles` |
| `approve` / AUTH-013 | `decided_by` 必须是请求组织当前有效的长期 `system_admin`，且不同于历史请求人与目标用户 | 锁后重新验证请求人与目标用户仍 active、未软删除且仍属请求组织 | pending + expected row_version；目标角色存在且 `is_enabled=TRUE`；无重叠有效分配；用同一 `db_now` 写批准与唯一 break-glass `user_roles` | 请求批准与角色分配在同一事务提交或全部回滚 |
| `reject` / AUTH-014 | `decided_by` 必须是请求组织当前有效的长期 `system_admin`，且不同于历史请求人与目标用户 | 历史请求人/目标用户无需仍 active、未删除或仍属该组织 | pending + expected row_version；零关联 `user_roles` | 允许安全闭合为 rejected；不得因历史主体失效而卡死 |
| `revoke` / AUTH-015 | `revoked_by` 必须是请求组织当前有效的长期 `system_admin`；沿用 R1，可等于历史请求人、目标用户或决定人 | 历史请求人/目标用户/决定人无需仍 active、未删除或仍属该组织 | approved + expected row_version 且锁后 `db_now < expires_at`；关联角色事实必须完整匹配 | 请求与角色撤销三字段在同一事务提交或全部回滚 |
| `expire` / 后台闭合 | 无 actor；不得伪造 `decided_by/revoked_by` | 不要求任何历史主体当前 active、未删除或仍属该组织 | approved + 锁后 row_version 且 `db_now >= expires_at` | 只写 `status/row_version/updated_at`；角色撤销三字段保持 NULL |
| 授权读取 | 不是治理 mutation，不产生 actor | 目标用户必须当前 active、未软删除且仍属请求组织 | 角色 `is_enabled=TRUE`；请求为 approved；请求与分配逐项匹配；分配未撤销；`effective_from <= db_now < expires_at` | 任一条件不满足即无权限；后台尚未写 expired 不延长授权 |

边界 `db_now = expires_at` 时只允许过期，不允许撤销或授权读取。批准重验失败时仍允许另一名合格长期管理员按 reject 行关闭 pending 请求。拒绝与撤销的“历史主体无需当前合格”只解除降权/闭合阻塞，不允许改写历史身份，也不允许不合格 actor 执行动作。

break-glass 多表动作的时间所有权固定如下，不得由实现自行选择：

- `break_glass_requests` 的 BEFORE row trigger 是 `create/approve/reject/revoke/expire` 唯一 time owner；在对应动作已取得适用锁后，每个实际执行的 transition branch 必须且只能显式调用一次 `pg_catalog.clock_timestamp()` 并保存为该动作唯一 `db_now`，忽略或覆盖调用方提交的服务器时间字段；资格、状态边界和全部本动作时间都只使用该值。
- `create` 写 `created_at=updated_at=db_now`；`approve` 写 `decision_at=effective_from=updated_at=db_now` 且 `expires_at=db_now + requested_duration_seconds * interval '1 second'`；`reject` 写 `decision_at=updated_at=db_now`；`revoke` 写 `revoked_at=updated_at=db_now`；`expire` 只写 `updated_at=db_now`，不得伪造决定或撤销时间。
- `approve/revoke` 的关联 `user_roles` trigger 不得再次读取时钟；它只从锁定的请求事实复制或校验不可变时间：批准时 `assigned_at=request.effective_from`、`expires_at=request.expires_at`，撤销时 `revoked_at=request.revoked_at`。deferred 双向 constraint trigger 在提交时逐字段验证请求与分配时间相等；任一复制、等值或资格检查失败时整个事务回滚。
- `bootstrap/user` 来源的普通 `user_roles` mutation，以及独立的 `users/roles` mutation，可以在各自独立动作中各自捕获一次数据库时间；它们不是同一 break-glass 多表动作，不得把自己的时钟替代或改写上述请求 time owner 的 `db_now`。

### 2.3 数据库可证事实与调用者身份边界

Gate C 的内部 trigger 可以验证行内 actor UUID 指向当前合格长期管理员、状态前像、角色/用户当前事实和跨表等值，但在没有认证上下文与 app-callable mutation wrapper 时，不能证明 SQL 调用者就是行内 actor，也不能完成 API 幂等、operation log 或跨业务入口锁序。因此：

- 008 的直接 SQL 只可作为数据库约束 probe，不是 AUTH 请求执行路径；
- 任何“存储的 actor 合格”证据都不得表述为“已认证调用者获授权”；
- R1 要求的 app-callable wrapper、真实 ACL、并发业务 mutation、idempotency 与 operation-log 原子性全部留给后续独立批准的 runtime Gate。

## 3. 008 空存储 Schema 切片与旧下游隔离

### 3.1 固定 lineage 与文件

只有有效九角色批准和第 4 节十一文件同步全部通过后，才允许创建下列唯一 revision：

```text
revision=20260807_008
down_revision=20260807_007
file=backend/alembic/versions/20260807_008_create_privileged_auth_core.py
predecessor_file=backend/alembic/versions/20260807_007_create_reliability_core.py
predecessor_raw_bytes=65444
predecessor_raw_sha256=8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df
```

R2 创建时已只读确认 Alembic 唯一 head 为 `20260807_007`，目标文件不存在。审批后若 head、down revision、文件名、两表对象集合、允许的既有表 trigger 范围或权限边界发生漂移，必须停止并提升至少 `CR-003-R3`；不得把 008 接到新的 head、改名或合并其他 migration。

### 3.2 008 唯一授权对象

008 只允许：

1. 按 `break_glass_requests -> user_roles` 创建两张空表及对应 SQLAlchemy ORM model/export；列、CHECK、FK、唯一/部分索引、GiST 半开区间排除、状态/字段矩阵、不可变性、来源矩阵、双向请求—角色一致性、DELETE/TRUNCATE 拒绝和 R1/R2 action-time 中数据库自身可强制的谓词，全部来自 R1+R2 effective contract。
2. 在两张新表上创建实现上述约束所必需的 revision-owned row/constraint/TRUNCATE trigger 与仅供 trigger 调用的内部函数。
3. 只为 D-013 和 action-time 当前事实，在既有 `users`、`roles` 上安装 008-owned invariant trigger；不得修改这两表的列、既有约束、owner、ACL 或数据。
4. 复用既有 `btree_gist`；不得创建/升级 extension、enum type、helper/permission/lock table（包括不在 57 表基线中的 `role_permissions`）、view、materialized view、partition、RLS policy 或额外业务对象。
5. 对两张新表和全部 008-owned 内部函数执行 `REVOKE ALL FROM PUBLIC`；不得向任何命名 application/worker/runtime/login role `GRANT`，不得改变既有对象 ACL/owner，也不得创建 owner membership。

所有内部函数必须是 zero-argument `RETURNS trigger`，并显式声明 `LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE SET search_path = pg_catalog, pg_temp`；所有非 `pg_catalog` 对象必须逐项 schema-qualified。trigger body 唯一允许的显式函数调用是 `pg_catalog.clock_timestamp()`，且只能用于第 2.2 节指定的 time-owner branch 或各自独立的普通 mutation 单时钟；允许的其余核心构造封闭为局部变量、`IF/ELSIF`、布尔/比较/算术与 NULL 谓词、`IS [NOT] DISTINCT FROM`、`EXISTS`、`SELECT ... INTO [STRICT]`、`OLD/NEW` 字段读取或赋值、`TG_*`、`RAISE/RETURN`，以及对 `public.users/public.roles/public.break_glass_requests/public.user_roles` 的静态只读 SQL。`btrim/length` 只可出现在 table CHECK，`tstzrange` 只可出现在 exclusion DDL，角色 preflight 的 `count`/聚合只可出现在 migration SQL，三者均不属于 trigger-body allowlist。禁止 `SECURITY DEFINER`、动态 `EXECUTE`、DDL/DCL、关系写入、role/session/config/ACL/owner 变更、advisory lock、网络、文件、program、large object、FDW、dblink、`LISTEN/NOTIFY` 或任何其他显式函数调用。`REVOKE ALL FROM PUBLIC` 只防止直接调用，不能替代 trigger 自动执行时的安全上下文。

这些函数只可作为 trigger-only 内部约束实现，不得作为应用写 API 消费；若实现需要 app-callable function/procedure、稳定调用签名、命名 runtime owner/grantee 或额外授权对象，即超出 R2，必须先提交后续 CR。

### 3.3 roles 与既有表边界

008 upgrade 必须在任何 DDL 前验证 `roles.code` 恰好为以下五项、无缺项/额外项/重复项，且现有行 `is_system_role=TRUE`：

```text
audit_reviewer
contract_admin
finance_reviewer
read_only
system_admin
```

008 不补种、不修正、不删除角色数据。升级后 008-owned invariant trigger 必须拒绝 `roles` INSERT/DELETE 以及 `id/code/is_system_role` 变化；`name/description/is_enabled` 只保留给未来获批的受控路径，008 本身不创建该路径或授予写权限。对 `users` 只允许新增验证当前 `status/deleted_at/organization_id` 与长期职责分离结果所必需的 008-owned trigger；不得改变用户行、用户 Schema 或现有权限。

### 3.4 不属于 008 的内容

008 明确不创建或实现：

- app-callable mutation wrapper、Repository、Service、Router、Worker task、Scheduler 或后台过期 Job；
- application/worker 的表级或函数级 ACL grant、production role、owner 切换或 credential；
- `idempotency_records` 新对象或其写入、operation log/action registry、Outbox 或 audit runtime；
- AUTH-011～AUTH-015 请求执行、认证调用者绑定、幂等重放、API 错误映射、UI 行为或业务并发入口；
- 默认组织、用户、管理员、角色、`user_roles`、break-glass 请求或任何 seed/真实数据。

数据库原生 GiST 冲突和 trigger 约束可以验证，但 008 Gate 不得宣称 R1 的 wrapper-only 反向等待防护、真实 ACL、两个业务写入口并发、API 幂等或 operation-log rollback 已通过。

### 3.5 work package 与 API 编号不混用

开发计划中的 `work_package.AUTH-005` 是“实现职责分离与 break-glass 约束”，归集 API AUTH-011～AUTH-015；API 文档中的 `api.AUTH-005` 则是 `POST /api/v1/users` 创建用户。008 只为前者提供两空表存储 Schema：

- 不实现 `api.AUTH-005`，也不实现 API AUTH-011～AUTH-015；
- 008 通过后核心表只能记为 `15/57`，`BASE-005` 和 `work_package.AUTH-005` 仍为 `partial`；
- 完整 `work_package.AUTH-005` 仍依赖 AUTH-003/004、`policy_approval_records`、`retrieval_eval_datasets`、`operation_logs`、app-callable wrapper、Repository/Service/API 和真实并发/审计链；
- 不得据此宣称 AUTH runtime、P0、AC-001 或任一其他 AC 完成。

### 3.6 旧 R1-only 下游隔离

下列既有内容只绑定 CR-003-R1 或旧 aggregate lineage：

- `backend/app/approval_pre_meta.py` 及 `backend/tests/unit/test_approval_pre_meta.py`；
- `DEP-005` / `DEP-005-R2` 与其 `source-contract-approval-record-v1/v2` Schema；
- `CR-014`、`CR-006/CR-006-R2`、`CR-008/CR-008-R2`；
- `CR-013` 及其 AUTH runtime 依赖。

它们不是 008 的前置，也不得把 R2 审批消息、R1 snapshot 或本次 active-baseline 同步解释为自身 fact-set、joint package、registry/pin、签名、migration 或 runtime 批准。R2 不授权修改这些文档、Schema、artifact、snapshot tuple 或 verifier 逻辑。未来若下游要消费 R2，必须发布 versioned successor，显式绑定 R1 base snapshot、R2 snapshot 和本次 post-sync evidence，并取得其自身审批。

唯一机械例外是第 4 节 `approval_pre_meta.py::_BASELINE_IDENTITY` 的 byte length 与 SHA-256 两个 literal re-pin；它不把 legacy verifier 升级成 R2 approval consumer。

## 4. post-R4 十一文件 active-baseline 同步

### 4.1 精确目标与 pre identities

同步目标必须恰为：

1. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
2. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
5. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
7. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
8. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
9. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
10. `docs/baseline-manifest.md`
11. `backend/app/approval_pre_meta.py`

九份 Request 必须精确匹配 CR-011-R4 同步后的 current pre identities：

| Request path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 128874 | `0c8ece722c3935cf0fad9117db96985228ceaee864f542fc407cf5e3c8234492` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 90344 | `3074ad8e1640cd709adf0defbd40d9f3e6417ca5345276244c96c31d865ccd89` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 115654 | `4ffa09ded6c0351730070d140d4bf9709060531306bebe9dfb99c39d35512ddf` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 328001 | `fee560512e39086bc3e1340c127054623c701b6e4d92dd058efb70cb8a5cf830` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 83278 | `f6730f09f95f761af31657fe14ad80d65c11bc914de7285ba09501c611d52ac9` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 51306 | `6676a2d8cdaa5a85e8f62937292aa4530dedd456dd9a6bbc2ebd627d808b5a43` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 49975 | `63ef73a6c98c0e57b8e88271db930294cf1934f3fdc62a8f6322628adaa1bea5` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 54314 | `99ba1c5226dc104ce2d96e1c80ee935de0a117116d5a608e3047c2ca2f7232ac` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 106372 | `e52cffaa687c2460ce021a23b2565b1948673a84226552cc3460523b5bf22a3e` |

同步配套文件 pre identity 固定为：

```text
path=docs/baseline-manifest.md
raw_bytes=1647
raw_sha256=4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94

path=backend/app/approval_pre_meta.py
raw_bytes=22193
raw_sha256=67a3457c5a0958e9bd443033a6cb1654a4ef5f0ec9b04e99437a1d2331203f71
allowed_change=_BASELINE_IDENTITY.byte_length|_BASELINE_IDENTITY.sha256
```

同步开始时 `_BASELINE_IDENTITY` 必须精确指向 `1647/4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94`。任一 pre identity、CR-001/CR-011/R1/R2 binding 或 current pin 不匹配时，整个同步不得开始；不得用“内容看起来相同”替代 raw identity。

### 4.2 九领域投影

九份 Request 只同步 R1+R2 effective contract 与本 CR 的授权边界：

- 需求：D-010～D-014 原子生效、action-time 资格矩阵和 57 表/API/P0 计数不变。
- 架构：数据库硬约束、历史身份与当前资格分离、固定锁后 `db_now`；Frontend/AI 不参与授权决定。
- 数据库：`decided_by/revoke_reason`、状态/来源矩阵、GiST 半开区间、不可变/双向/SoD trigger、008 ownership 与安全 downgrade；本同步本身不建表。
- API：区分 `api.AUTH-005` 与 `work_package.AUTH-005`；同步 AUTH-011～AUTH-015 的 `decided_by`、CAS、幂等和 action-time 语义，但明确 runtime 未授权。
- 页面：五态、决定/撤销事实、冲突和过期语义；页面不得推断 actor 资格或延长授权。
- AI/RAG：模型输出不得创建、批准、拒绝、撤销、过期或延长权限；不授权 Provider。
- 测试：分离 Gate A/B/C 与后续 runtime Gate；数据库 probe 不冒充认证、API、wrapper 或业务并发证据。
- 部署：008 仅本地/专用可丢弃合成 PostgreSQL 16；固定 lock timeout、非空降级失败和 catalog 恢复；部署/production 不授权。
- 计划：008 两空表存储切片使核心表达到 `15/57`，但 `BASE-005`、`work_package.AUTH-005` 仍 partial，API runtime 与 AC 不变。

每份 Request 只保留一条 `CR-003-R2 / approved contract scope` 修订记录，不得嵌入该文件自身 post byte length/hash。不得顺带同步 CR-013、operation-log、ACL、wrapper、真实账号或任何其他候选合同。

### 4.3 无环 DAG、两 literal re-pin 与原子性

生成 DAG 固定为：

```text
R1 snapshot + R2 sections 1-8 snapshot
+ CR-001/CR-011 anchors
+ exact 11 pre identities
+ valid nine-role approval
                    |
                    v
          nine Request post bytes
                    v
       nine Request post identities
                    v
        baseline-manifest post bytes
                    v
        baseline-manifest post identity
                    v
approval_pre_meta._BASELINE_IDENTITY
    byte_length + sha256 literal re-pin
                    v
R2 section 9 external post-sync evidence
```

Request 不得包含自身 post identity；baseline manifest 只记录九份 Request post identities，不记录自身、R2 或 `approval_pre_meta.py` identity。九份 post identities只能进入 manifest、第 9 节或外部证据；manifest post identity 除 `_BASELINE_IDENTITY` 两个 literal 外只能进入第 9 节或外部证据；`approval_pre_meta.py` 自身 post identity 只能进入第 9 节或外部证据。R2 第 1～8 节不得包含 R2 自身 snapshot 或任何 post-sync identity。

必须先在临时区生成和验证 11 个 post bytes，再一次性替换全部目标。`approval_pre_meta.py` diff 只能替换 `_BASELINE_IDENTITY.byte_length` 与 `.sha256` 两个 literal；路径、`_SCHEMA_IDENTITIES`、`_SNAPSHOT_IDENTITIES`、CR-003-R1 tuple、decision universe、Schema/fact-set、角色、解析/批准逻辑和 CLI scope 输出全部不变，`backend/tests/unit/test_approval_pre_meta.py` 不修改。任一生成、hash、manifest、two-literal diff、UTF-8/LF、测试或原子替换失败，必须恢复全部 11 个 pre bytes，不得留下部分 active baseline。

## 5. 九角色审批合同

### 5.1 必需角色

本 R2 必须由以下九角色共同批准；一人具备多个角色权限时可合并一条记录，但必须逐项列明全部角色：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | 五项决策、action-time 用户语义、计数零变化与九份 Request 同步 |
| 架构 | R1+R2 effective contract、历史/当前资格分层、三层 Gate 与 runtime 隔离 |
| 数据/DBA | 两表、008 lineage、GiST/trigger/不变量、ACL 非授权和 downgrade |
| 后端/API | AUTH 编号区分、actor/CAS/幂等合同与 Repository/Service/API 非授权 |
| 前端/UI | 五态与决定/撤销显示，页面不推断资格或运行状态 |
| AI/RAG | AI 不参与权限裁决，Provider/网络非授权 |
| 测试/质量 | 11 文件原子同步、三层 Gate、PG16/catalog/失败路径和证据边界 |
| 运维/可靠性 | 固定 revision、锁/超时/回退、无 named grant、部署非授权 |
| 安全 | 长期管理员、双人控制、SoD、降权可达、actor 与真实调用者边界 |

### 5.2 canonical approval record

每条审批记录必须包含：

```text
姓名
角色
decision=APPROVED|REJECTED
selected_option=D-010=DECIDED_BY_STATE_CAS;D-011=REVOKE_REASON;D-012=GIST_HALF_OPEN_RANGE;D-013=ENV_INDEPENDENT_SOD;D-014=LONG_TERM_ADMIN_ONLY
selected_decisions
rejected_decisions
cr_revision=CR-003-R2
base_revision=CR-003-R1
base_decision_preimage_bytes=24270
base_decision_snapshot_sha256=cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045
decision_snapshot_sha256
cr001_revision=CR-001-R2
cr001_decision_snapshot_sha256=8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615
active_baseline_source_revision=CR-011-R4
active_baseline_source_decision_snapshot_sha256=cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10
environment_scope=contract
network_scope=none_except_local_or_disposable_synthetic_pg16
baseline_manifest_pre_raw_bytes=1647
baseline_manifest_pre_raw_sha256=4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94
approval_pre_meta_pre_raw_bytes=22193
approval_pre_meta_pre_raw_sha256=67a3457c5a0958e9bd443033a6cb1654a4ef5f0ec9b04e99437a1d2331203f71
approval_pre_meta_repin_scope=_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY
migration_revision=20260807_008
migration_down_revision=20260807_007
migration_file=backend/alembic/versions/20260807_008_create_privileged_auth_core.py
migration_predecessor_raw_bytes=65444
migration_predecessor_raw_sha256=8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df
authorized_scope=exact_nine_request_plus_baseline_manifest_sync|approval_pre_meta_active_baseline_identity_repin_only|cr003_contract_offline_gate|20260807_008_two_empty_storage_tables_ddl_orm|local_or_disposable_synthetic_pg16
runtime_scope=none
real_data_scope=none
deployment_scope=none
production_scope=none
日期
证据链接
备注
```

有效 `APPROVED` 记录的 `selected_decisions` 必须为 `[D-010,D-011,D-012,D-013,D-014]`，`rejected_decisions=[]`。任一角色缺失、拒绝、snapshot/anchor/pre identity/revision/file/scope 不同，或备注与非授权边界冲突时，整体保持 `NOT APPROVED`。

批准只能按 Gate 顺序授权第 4 节十一文件同步、纯 contract/offline 证据和第 3 节 008 空存储 Schema；它不批准任何 application/runtime write path、真实 ACL grant、账号/权限业务运行时、真实数据、其他网络、部署或 production。

## 6. 三层验收 Gate

### 6.1 Gate A：审批前静态可签署性

Gate A 必须在任何签署前只读通过：

- 机械复算 R1 `24270/cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045`，确认 R1 全文件和规范 preimage 未改；
- 机械复算 CR-001-R2 与 CR-011-R4 锚点 snapshot，确认前者已批准同步、后者为当前 active-baseline 来源；
- 验证九份 Request、baseline manifest、approval pre-meta 的 11/11 pre identity 与 current pin；
- 验证 Alembic 唯一 head=`20260807_007`、predecessor source=`65444/8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df`、008 文件不存在、`btree_gist` 已由既有 lineage 提供；
- 审查 action-time 矩阵可使 reject/revoke/expire 在历史主体失效后仍安全可达，同时 approve/read fail closed；
- 扫描 R2 不包含 secret、真实账号、真实数据、endpoint、Provider/其他外网、named ACL grant、app-callable wrapper、部署或 production 授权；
- 按第 8 节生成并至少两路独立复算 R2 snapshot。

Gate A PASS 只证明候选可签署；不授权同步、代码、migration 或数据库连接。

### 6.2 Gate B：批准后的十一文件同步与 contract/offline

只有有效九角色批准后才运行 Gate B：

- 按第 4 节临时生成、验证并原子替换恰好 11 个文件；pre/post identity、manifest 九项和 two-literal re-pin 全部匹配；
- 每份 Request 的领域投影与修订记录唯一，无自引用、无 CR-013/operation-log/runtime 夹带；
- `approval_pre_meta.py` 逆向替换两个 literal 后精确重建 pre identity，既有 snapshot/Schema/decision universe 和 CLI scope 输出不变；
- `scripts/verify-baseline.ps1`、`backend/tests/unit/test_approval_pre_meta.py` 及同步负向/回滚检查实际通过；
- 纯 contract/offline 测试可以验证 R1/R2 矩阵、Schema 投影和 migration source 静态边界，但不得连接数据库、Redis/Broker、Provider/其他网络，也不得读取真实 `.env` 或业务正文。

Gate B PASS 才允许开始 008。Gate B 不创建表、不证明 ORM/catalog、AUTH runtime 或 AC。

### 6.3 Gate C：008 两空表 storage-schema / PostgreSQL 16

Gate C 仅覆盖 008 与 ORM：

- 再次确认 unique head/down/file 与第 3.1 节完全一致；upgrade preflight 在任何 DDL 前验证五个 role code exact、`is_system_role=TRUE`，不补种或修数据；
- migration/ORM/catalog 精确核对两表、全部列/约束/index/GiST、状态/不可变/来源/双向一致性/SoD/action-time 内部 trigger；无第三张表、helper、seed、app-callable function 或 named grant；从实际 trigger 的 `tgfoid` 反查函数，并机械断言 `prolang=plpgsql/prosecdef=false/provolatile=v/proparallel=u/proconfig` 精确为 `search_path=pg_catalog, pg_temp`、PUBLIC 无 EXECUTE，同时审查 `pg_get_functiondef` 与迁移源码不存在第 3.2 节禁止副作用；
- 机械与行为双重证明第 2.2 节 time owner：每个 `break_glass_requests` transition branch 恰一次 `pg_catalog.clock_timestamp()`，关联 `user_roles` 的 approve/revoke branch 零时钟调用；create/approve/reject/revoke/expire 的调用方时间均被数据库值覆盖并在回读时满足字段矩阵，approve/revoke 最终请求—分配时间逐字段相等；在关联 `user_roles` 中故意写入第二个、未来或客户端时间造成任一不等时，必须以固定 `23514` 整体失败；
- 生成 pre/post catalog manifest，逐项记录 008 新对象及 `users/roles` 上 008-owned trigger；证明既有表的列、约束、owner、ACL、数据不变，新表/内部函数已 REVOKE PUBLIC；
- 在本地或专用可丢弃合成 PostgreSQL 16 上验证 `007 -> 008 -> 007 -> 008`、空表无残留、真实 CHECK/FK/GiST/状态/不可变/来源/双向/SoD 负例与 action-time 矩阵；测试数据只存在于可重建测试库；
- 只可把直接 SQL 表述为 constraint probe；数据库原生 exclusion 冲突可验证，但 app wrapper 的调用者绑定、跨入口锁序、真实 ACL 和完整并发业务 Gate保持 NOT_RUN；
- Ruff、format、mypy、聚焦/全量 pytest、Alembic single head、离线门禁和 PostgreSQL catalog Gate 全部通过，失败必须保留实际状态。

#### Gate C downgrade

downgrade 必须在一个事务内：

1. `SET LOCAL lock_timeout='5s'`，按 R1 固定顺序先对 `break_glass_requests`、再对 `user_roles` 取得 `ACCESS EXCLUSIVE`；任一锁超时以 `55P03` 整体失败。
2. 在任何 destructive DDL 前验证两表均为空；任一表存在任一历史行都以 SQLSTATE `55000` 整体失败，禁止清理、导出后删除、TRUNCATE 或改写状态。
3. 空表时仍受同一 5 秒 timeout 约束，按 `users -> roles` 固定顺序取得删除 008-owned trigger 所需的 DDL 锁；先删除既有 `users/roles` 上全部 008-owned trigger，再删除其余 008 trigger。随后按 child `user_roles` -> parent `break_glass_requests` 删除两表，最后删除无依赖的 008-owned internal function。全程禁止 `CASCADE`。
4. 用 pre/post catalog manifest 证明 008 对 `users/roles` 的 trigger delta 和全部其他 008 对象归零，既有列、约束、owner、ACL 与 catalog 精确恢复；任一残留使 Gate 失败。

Gate C PASS 后只允许记录 `15/57` 与相应 storage-schema evidence；`BASE-005`、`work_package.AUTH-005` 仍为 partial。它不授权或证明后续 runtime Gate。

## 7. 始终非授权范围

无论 Gate A/B/C 状态如何，本 R2 始终不授权：

- `api.AUTH-005`、AUTH-011～AUTH-015 或任何其他账号/权限 API runtime；
- app-callable database wrapper、Repository、Service、Router、Worker、Scheduler、后台 expire/revoke runtime；
- 真实 application/worker ACL grant、认证调用者绑定、密码/Token/session、bootstrap、权限字典或真实管理员；
- `idempotency_records` 写链、operation log/action registry、Outbox、审计投影或业务 E2E；
- 真实授权/用户/组织数据的导入、清理、回填、迁移、导出后删除或修复；
- Redis、Broker、Provider、DNS、TLS、HTTP、Chat、Embedding 或其他网络；唯一例外是 Gate C 明确限定的本地/专用可丢弃合成 PostgreSQL 16 连接，不得访问共享、远程或生产数据库；
- Docker image pull、云资源、部署、canary、production migration、production 放行、提交、推送或 PR。

后续 runtime 至少需要独立冻结 app-callable function signature、owner/grantee/ACL、认证 actor binding、idempotency、operation log、Repository/Service/API、并发锁序和恢复证据，并发布显式绑定本 R2 的 successor；不得从 storage-schema Gate 推导授权。

## 8. R2 decision snapshot 与生命周期算法

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次；不得以 substring 命中正文或代码块。
4. preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256 小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定 R1 base、CR-001/CR-011 anchors、post-R4 十一项 pre identity、008 lineage 和第 5 节授权范围。
7. R2 snapshot 不包含自身 hash、任何实际审批记录实例或任何 post-sync identity；第 5 节只冻结 canonical record 的字段与验证规则。合法的 post identity 只能按第 4.3 节进入第 9 节或外部证据，不能反向自嵌。
8. 首条有效 approval、sync authorization 或下游消费证据形成前，第 1～8 节可在 review 阶段修订，但每次必须撤回旧 unsigned hash并全量重审；任一上述事实形成后，第 1～8 节任何 byte 变化都必须提升至少 `CR-003-R3` 并重置签署。
9. 第 9 节只记录动态生命周期，不能覆盖规范条款，也不改变 decision snapshot。
10. 生成 snapshot 只建立可签署对象，不等于批准；有效审批前不得同步十一文件或创建 008。

## 9. 当前状态

本节位于 decision snapshot 之外，只记录生命周期和证据。

| 项目 | 状态 |
|---|---|
| CR revision | `CR-003-R2；DRAFT / PROPOSED / NOT APPROVED` |
| R1 base | `VERIFIED；24270/cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045；R1 FILE UNCHANGED` |
| CR-001 / CR-011 anchors | `VERIFIED；CR-001-R2=22618/8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615；CR-011-R4=27384/cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` |
| action-time blocker | `CANDIDATE CLOSED BY §2；NOT ACTIVE BEFORE APPROVAL/SYNC` |
| post-R4 active-baseline pre identities | `11/11 VERIFIED；manifest pin=CURRENT` |
| Alembic lineage | `CURRENT HEAD=20260807_007；008 FILE ABSENT；20260807_008/down=007 RESERVED ONLY IF APPROVED` |
| Gate A | `PASS；READ-ONLY STATIC SIGNABILITY；0 WRITE / 0 NETWORK` |
| 九角色审批 | `0/9；NONE` |
| Gate B Request / manifest / pin sync | `NOT AUTHORIZED / NOT RUN` |
| Gate C 008 empty storage schema | `NOT AUTHORIZED / NOT RUN` |
| legacy R1-only downstream | `ISOLATED / NOT UPGRADED / NOT APPROVED BY R2` |
| app wrapper / ACL / idempotency / oplog / Repository / Service / API runtime | `NOT AUTHORIZED / NOT IMPLEMENTED` |
| 真实数据 / Provider / 其他网络 / 部署 / canary / production | `NOT AUTHORIZED / NOT RUN` |
| R2 decision snapshot | `GENERATED FOR REVIEW；preimage_bytes=35977；decision_snapshot_sha256=7a69b8555d422a7c2bee9d74da7030b8170692c934d83c12dd722c15c85c8363；NOT APPROVED` |
