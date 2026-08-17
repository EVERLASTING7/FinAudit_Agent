# CR-003-R3：特权授权当前 R6 基线前向见证 successor

> 文档类型：`CR-003-R1` + `CR-003-R2` effective contract 的治理型 successor addendum  
> 修订：`CR-003-R3`  
> 日期：2026-08-11  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 9 节  
> 目标：不改变 D-010～D-014 的任何业务、安全、数据或运行时语义，只把未获批 R2 的旧 active-baseline 输入前向见证到当前 `CR-011-R6` active baseline，并重新建立可签署、可同步、可实施的 Gate 顺序  
> 非目标：不追认 R2，不修改 Request，不创建 migration，不连接数据库，不开放 AUTH runtime，不处理真实数据，不授权 Provider/其他外网、部署、canary 或 production

对应差异：GAP-034～GAP-037

## 1. 不可变合同链、零语义边界与当前锚点

### 1.1 R1/R2 不可变输入与历史状态

本 R3 逐字绑定下列两个既有候选，不修改其文件：

| 对象 | raw identity | decision identity | R3 创建时的生命周期事实 |
|---|---|---|---|
| `docs/change-requests/CR-003-privileged-auth-integrity-closure.md` / `CR-003-R1` | `24838/7ca3e30460b4b2449c40a4ed01faa7cf05dbfaf0232214a0ed612cae43df48d7` | `24270/cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045` | `DRAFT / PROPOSED / NOT APPROVED` |
| `docs/change-requests/CR-003-R2-privileged-auth-integrity-closure.md` / `CR-003-R2` | `37504/2e9c9e2c25d2e46fbc8de7ee738c08ef6a0a026f5af23f715d29d2131d653736` | `35977/7a69b8555d422a7c2bee9d74da7030b8170692c934d83c12dd722c15c85c8363` | `DRAFT / PROPOSED / NOT APPROVED；审批 0/9；Gate B/C NOT AUTHORIZED / NOT RUN` |

R2 第 9 节记载的历史 `Gate A PASS` 只表示当时 post-R4 输入下的作者静态复核。当前十一文件已经经过后续获批 CR 前移；R2 的旧 Gate A、旧 pre identities、旧 active-baseline source 和 `0/9` 状态均不沿用、不追认，也不能授权任何同步、代码、migration 或数据库连接。

### 1.2 R3 effective contract

`CR-003-R3 effective contract` 的唯一含义是三个分别验证的 snapshot：

```text
exact CR-003-R1 decision snapshot
+ exact CR-003-R2 sections 1 through 8 decision snapshot
+ this document sections 1 through 8 governance addendum
```

三份 preimage/hash 必须分别验证；不得拼接 bytes 生成未定义的第四个 hash，也不得以 R1/R2 的动态状态节代替其 decision snapshot。R1、R2 文件保持 byte-for-byte 不变。

R3 审批选择的是上述完整 effective contract，不是追认 R1 或 R2 的历史审批状态，也不是只批准 008 空表。有效 R3 九角色审批形成前，R1/R2 继续保持各自 `NOT APPROVED`；R3 的未来批准只使 R3 effective contract 成为新的可执行合同入口，不回写或伪造 R1/R2 的历史签署记录。

### 1.3 D-010～D-014 零语义 delta 与封闭治理覆盖

R3 不新增、删除、重命名或重新解释任何 `D-*`。决策全集及顺序仍为：

```text
D-010
D-011
D-012
D-013
D-014
```

`selected_option` 仍逐字为：

```text
D-010=DECIDED_BY_STATE_CAS;D-011=REVOKE_REASON;D-012=GIST_HALF_OPEN_RANGE;D-013=ENV_INDEPENDENT_SOD;D-014=LONG_TERM_ADMIN_ONLY
```

R1 的状态/字段/来源矩阵、CAS、幂等、锁序、GiST 半开区间、职责分离、长期管理员资格、历史保留与 downgrade 语义，以及 R2 的 action-time 资格矩阵、单一 `db_now` owner、trigger/ACL/storage-schema 限制、work package/API 编号区分和 runtime 隔离，全部逐字继承。

R3 的非零 delta 仅为 active-baseline 治理，封闭如下：

1. R2 第 1.2 节的 `CR-011-R4` 保留为历史上游锚点；当前 active-baseline source 改由本节第 1.4 节的 `CR-011-R6` 与其 Gate B post state 见证。
2. R2 第 4 节的 post-R4 十一项旧 pre identities、同步入口和 DAG，被本 R3 第 3 节的当前 R6 十一项 pre identities、同步入口和 DAG 覆盖。
3. R2 第 5 节的 canonical approval record 被本 R3 第 4 节替代；R2 的 `0/9` 不转移，不存在可复用签名。
4. R2 第 6.1～6.2 节中依赖旧 pre state 的 Gate A/B 输入和状态，被本 R3 第 5 节与第 6.1 节替代；R2 第 6.3 节 Gate C 的 008 storage-schema/PG16 行为与验收语义原样继承，但必须等待本 R3 Gate B PASS 后才可授权。
5. R2 第 8 节只定义 R2 自身 snapshot/lifecycle；R3 使用第 8 节自己的算法。R2 第 9 节不属于 R2 decision preimage，也不进入 R3 effective contract。
6. R2 第 3.6 节所称“本次 post-sync evidence”因 R2 始终 `0/9` 且 Gate B 未授权、未运行而从未产生，不得伪造、追认或作为下游输入。就 CR-003 approval/post lineage 而言，R3 签署只绑定 R1/R2/R3 三份 decision snapshot 与第 3.1 节 current 11 pre identities；未来的 R3 Gate B post 不进入签署 preimage。只有经验证的 R3 Gate B PASS post evidence 可以替代该不存在的 R2 post；Gate B PASS 前禁止任何下游消费。未来下游必须发布 versioned successor，显式绑定 R1/R2/R3 三份 snapshot、R3 Gate B post evidence，并取得自身独立批准。

除上述六项治理覆盖外，发生冲突时 R1+R2 原文优先，R3 不得被解释为新的业务、安全、Schema、API、UI、AI、测试或运维选择。若实现或同步需要改变 D-010～D-014、R2 action-time/storage-schema 语义、对象集合、migration identity 或非授权边界，必须停止并提升至少 `CR-003-R4`。

累计产品与实施 delta 继续为：

| 项目 | R3 effective contract delta |
|---|---:|
| API path / HTTP error code | `0 / 0` |
| P0 核心物理表总数 | `0`，仍为 `57` |
| Gate C 成功后的已实现核心表增量 | `+2`，从当前 `13/57` 到 `15/57` |
| UI page / route / P0 work item | `0 / 0 / 0` |
| operation-log action / seed row | `0 / 0` |
| application/runtime write entry | `0` |
| D-010～D-014 业务与安全语义 | `0` |

### 1.4 当前 R6 active-baseline source

R3 不重新审批 AI/BASE-004，只绑定已经批准并完成十一文件 Gate B 同步的当前 active-baseline 来源：

| 对象 | 固定 identity | 绑定用途 |
|---|---|---|
| `docs/change-requests/CR-011-R6-base004-startup-evidence-boundary.md` raw | `65121/54a42ade8b20846504e56c6a004503216462f6c71807d0d21c94e74efd087ede` | 见证 R6 当前生命周期、9/9 批准、Gate B PASS 与第 9.1 节 post identities |
| `CR-011-R6` decision snapshot | `60493/113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815` | 绑定 R6 规范 preimage；不授权本 CR 的 AUTH/DB/runtime |
| `docs/baseline-manifest.md` current raw | `1675/9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11` | 当前九份 Request active-baseline manifest |

R6 通过其合同链绑定 `CR-011-R3/R4/R5` 的 AI/启动治理事实，但本 `CR-003-R3` 不消费或扩大其 Gate C、Provider、网络、依赖或 startup 授权。R6 Gate C 仍阻断/未运行，与本 R3 的特权授权候选可签署性互不替代。

CR-001-R2 仍作为 D-006 与 57 表基线的已批准上游锚点：decision snapshot 为 `22618/8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615`。CR-001-R2 或 CR-011-R6 的批准均不替代本 R3 九角色审批。

## 2. 008 lineage 与 storage-schema 范围的当前见证

### 2.1 当前 Alembic 事实

R3 Gate A 只读见证如下事实：

```text
unique_head=20260807_007
head_file=backend/alembic/versions/20260807_007_create_reliability_core.py
head_raw_bytes=65444
head_raw_sha256=8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df
target_revision=20260807_008
target_down_revision=20260807_007
target_file=backend/alembic/versions/20260807_008_create_privileged_auth_core.py
target_file_state=ABSENT
btree_gist_provider_revision=20260806_001
```

因此 R2 第 3.1 节固定的 008 identity 尚未发生 lineage 漂移，无需重编号、改名或接到新 head。008 仍只在有效 R3 九角色批准和第 3 节十一文件同步 Gate B PASS 后才可创建。

若签署前 unique head、007 raw identity、008 文件状态、`btree_gist` 来源、两表对象集合或允许的既有表 trigger 范围发生任何漂移，本 R3 立即失去可签署性；不得自动选择“下一个 revision”或在第 9 节更新 identity，必须提升 successor。

### 2.2 008 授权范围零变化

R2 第 3.2～3.6 节完整继承。Gate C 的唯一实现范围仍是：

- 创建空的 `break_glass_requests` 与 `user_roles` 两张核心表、对应 ORM/export，以及实现 R1+R2 数据库自身可强制不变量所必需的 revision-owned trigger/内部函数；
- 只在既有 `users/roles` 上安装 008-owned invariant trigger，不改列、既有约束、owner、ACL 或数据；
- upgrade 在任何 DDL 前验证五个固定 role code 恰好存在、无额外/重复且 `is_system_role=TRUE`，不补种、不修数；
- 对新表和内部 trigger function `REVOKE ALL FROM PUBLIC`，不向任何 named application/worker/runtime/login role 授权；
- 只在本地或专用可丢弃合成 PostgreSQL 16 执行 R2 Gate C 的 catalog、行为、往返、失败与 downgrade Gate。

本 R3 不授权第三张表、helper/permission/lock table、view、partition、RLS、seed、app-callable wrapper、Repository、Service、Router、Worker、Scheduler、ACL grant、认证 actor binding、idempotency 写链、operation log、真实账号或业务数据。008 constraint probe 仍不得表述为认证/API/业务并发证据。

## 3. 当前 R6 十一文件 pre state 与批准后同步

### 3.1 精确目标与 pre identities

批准后的同步目标必须恰为以下十一项；本表也是签署时的完整 current pre-state：

| path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 130357 | `b0f7b4422f3bd32d8fb0b3ace4417a63da3a48b9b931c3fbd48239399eb3c511` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 92246 | `061f4a2fdce8e813abdc904d7657cd70bfee46ff46e804725d4eb462e9fa2a57` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 116615 | `8f4878fe396910cc6176ddc044b4e23a1d81aa68035e2896a254bbcc171e29df` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 328953 | `4659754f5939f51316fa41ddc94b4a98fb57933df3f04f7092aef97e3ad2c2db` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 84259 | `0b9c5bfb4f5de94758aa54366ef82b7a1665487717bb9f57580f8809143b596b` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 52541 | `494f98ea9ccb39d1621e257d8473ee1848dc5bc96ea7a636a26c510c75d7fe4a` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 51649 | `43631352a945ce56cabaeafee4d6090def7c9ca0256ecd5a135bfc2b9f52fa7d` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 55466 | `78023778b650260b59232ab1e77a040b512bd12b0ee8a0f7dae29228b241d481` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 107675 | `52a07e78f5776196f2a6fc53d873b478c3f6e3d1dc1bb7a252076fa48c365d7a` |
| `docs/baseline-manifest.md` | 1675 | `9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11` |
| `backend/app/approval_pre_meta.py` | 22193 | `f5ec3483e005902c4cea94ca428ffbaf71c6a3624d4ef0c77c81a7212e4fa881` |

`approval_pre_meta.py::_BASELINE_IDENTITY` 必须精确指向 `1675/9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11`。其唯一允许变化仍是 `_BASELINE_IDENTITY.byte_length` 与 `.sha256` 两个 literal re-pin；其他 byte、旧 CR-003-R1 tuple、Schema、fact-set、decision universe、角色、解析/批准逻辑和 CLI scope 均不得变化。

任一 pre identity、R1/R2/R6/CR-001 binding、current pin 或 007/008 lineage 不匹配时，整个同步不得开始。不得以 Git 时间、文件名、内容相似、历史 Gate A 或 R6 的其他业务证据替代 raw identity。

### 3.2 九份 Request 的唯一领域投影

有效 R3 九角色批准后，九份 Request 只允许各增加一条 `CR-003-R3 / approved privileged-auth current-baseline successor` 修订记录，并同步 R1+R2 effective contract 的既有内容：

- 需求：D-010～D-014 原子生效、R2 action-time 资格矩阵与 57 表/API/P0 计数不变。
- 架构：数据库硬约束、历史身份与当前资格分离、固定锁后 `db_now`；Frontend/AI 不参与授权决定。
- 数据库：`decided_by/revoke_reason`、状态/来源矩阵、GiST 半开区间、不可变/双向/SoD trigger、008 ownership 与安全 downgrade；同步本身不建表。
- API：区分 `api.AUTH-005` 与 `work_package.AUTH-005`；同步 AUTH-011～AUTH-015 的 `decided_by`、CAS、幂等和 action-time 语义，但 runtime 不授权。
- 页面：五态、决定/撤销事实、冲突和过期语义；页面不得推断 actor 资格或延长授权。
- AI/RAG：模型输出不得创建、批准、拒绝、撤销、过期或延长权限；不授权 Provider。
- 测试：区分 R3 Gate A/B、008 storage-schema Gate C 与未来 runtime Gate；数据库 probe 不冒充认证、API、wrapper 或业务并发证据。
- 部署：008 只限本地/专用可丢弃合成 PostgreSQL 16；固定 lock timeout、非空 downgrade 失败和 catalog 恢复；部署/production 不授权。
- 计划：008 两空表切片成功后只达到 `15/57`；`BASE-005`、`work_package.AUTH-005` 仍为 partial，API runtime、P0 和 AC 状态不升级。

R2 从未获批或同步，因此不得另写一条伪造的 `CR-003-R2 approved` 修订记录。R3 修订记录必须明确其 effective contract 绑定 R1/R2 snapshots；不得顺带同步 CR-013、operation-log、ACL、wrapper、真实账号或其他候选合同。

### 3.3 无环 DAG、两 literal re-pin 与原子性

生成 DAG 固定为：

```text
R1 snapshot + R2 sections 1-8 snapshot
+ CR-001/R6 anchors + exact current 11 pre identities
+ R3 sections 1-8 snapshot + valid R3 nine-role approval
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
        approval_pre_meta._BASELINE_IDENTITY two-literal re-pin
                              v
        full Gate B verification + verified R3 post evidence
                              v
              R3 section 9 / external tracking
                              v
        future independently approved versioned successor
   (R1/R2/R3 snapshots + R3 Gate B post evidence)
```

Request 不得包含自身 post identity；baseline manifest 只记录九份 Request post identities，不记录自身、R3 或 `approval_pre_meta.py` identity。九份 Request post identity、manifest post identity、pre-meta post identity 和实际审批实例只能进入第 9 节或外部 tracking，不得进入 R3 decision preimage。R2 没有 post-sync evidence；Gate B PASS 前 DAG 必须停止在 R3 签署/current pre state，任何下游节点均不可达。Gate B PASS 后形成的 R3 post evidence 是 CR-003 lineage 唯一 post 输入，但未来下游仍须独立批准，不能由该 evidence 自动授权。

必须先在隔离临时区生成和验证 11 个 post bytes，再一次性替换全部目标。任一生成、hash、manifest、two-literal diff、UTF-8/LF、baseline verifier、逆向重建或原子替换失败，必须恢复全部 11 个 pre bytes，不得留下部分 active baseline。同步不得修改 R1/R2/R3 文件本身。

## 4. R3 九角色审批合同

### 4.1 必需角色与责任

本 R3 必须由下列九角色共同批准；一人具备多个角色权限时可合并一条记录，但必须逐项列明全部角色：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | 五项原决策、action-time 用户语义、零计数变化与当前十一文件同步 |
| 架构 | R1+R2+R3 effective contract、历史/当前资格分层、三层 Gate 与 runtime 隔离 |
| 数据/DBA | 两表、008 lineage、GiST/trigger/不变量、ACL 非授权和 downgrade |
| 后端/API | AUTH 编号区分、actor/CAS/幂等合同与 Repository/Service/API 非授权 |
| 前端/UI | 五态与决定/撤销显示，页面不推断资格或运行状态 |
| AI/RAG | AI 不参与权限裁决，R6 只是 active-baseline source，Provider/网络非授权 |
| 测试/质量 | current 11 原子同步、R3 fresh Gate A、PG16/catalog/失败路径和证据边界 |
| 运维/可靠性 | 固定 008 revision、锁/超时/回退、无 named grant、部署非授权 |
| 安全 | D-010～D-014 零语义、长期管理员、双人控制、SoD、降权可达与真实调用者边界 |

### 4.2 canonical approval record

以下字段必须由有效审批逐项提供；任何占位、缺失、乱序决策、不同 identity/scope 或扩大授权的备注均不构成批准：

```text
姓名
角色
decision=APPROVED|REJECTED
selected_option=D-010=DECIDED_BY_STATE_CAS;D-011=REVOKE_REASON;D-012=GIST_HALF_OPEN_RANGE;D-013=ENV_INDEPENDENT_SOD;D-014=LONG_TERM_ADMIN_ONLY
selected_decisions
rejected_decisions
cr_revision=CR-003-R3
base_revision=CR-003-R1
base_raw_bytes=24838
base_raw_sha256=7ca3e30460b4b2449c40a4ed01faa7cf05dbfaf0232214a0ed612cae43df48d7
base_decision_preimage_bytes=24270
base_decision_snapshot_sha256=cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045
r2_revision=CR-003-R2
r2_raw_bytes=37504
r2_raw_sha256=2e9c9e2c25d2e46fbc8de7ee738c08ef6a0a026f5af23f715d29d2131d653736
r2_decision_preimage_bytes=35977
r2_decision_snapshot_sha256=7a69b8555d422a7c2bee9d74da7030b8170692c934d83c12dd722c15c85c8363
r2_historical_gate_a=NOT_INHERITED
r2_approval_state=0_OF_9_NOT_APPROVED
r2_gate_b_state=NOT_AUTHORIZED_NOT_RUN
r2_gate_c_state=NOT_AUTHORIZED_NOT_RUN
decision_snapshot_sha256
cr001_revision=CR-001-R2
cr001_decision_snapshot_sha256=8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615
active_baseline_source_revision=CR-011-R6
active_baseline_source_raw_bytes=65121
active_baseline_source_raw_sha256=54a42ade8b20846504e56c6a004503216462f6c71807d0d21c94e74efd087ede
active_baseline_source_decision_preimage_bytes=60493
active_baseline_source_decision_snapshot_sha256=113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815
current_request_pre_identity_set=CR003_R3_SECTION_3_1_EXACT_9_OF_9
environment_scope=contract
network_scope=none_except_local_or_disposable_synthetic_pg16
baseline_manifest_pre_raw_bytes=1675
baseline_manifest_pre_raw_sha256=9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11
approval_pre_meta_pre_raw_bytes=22193
approval_pre_meta_pre_raw_sha256=f5ec3483e005902c4cea94ca428ffbaf71c6a3624d4ef0c77c81a7212e4fa881
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

有效 `APPROVED` 的 `selected_decisions` 必须逐字为 `[D-010,D-011,D-012,D-013,D-014]`、`rejected_decisions=[]`。有效 `REJECTED` 必须按 R2 第 1.3 节规则，用两个数组无重复、互斥且按声明顺序精确分区五项全集，且 `rejected_decisions` 非空。

任一必需角色缺失或拒绝，R3 整体保持 `NOT APPROVED`。审批只按 Gate 顺序授权第 3 节十一文件同步、纯 contract/offline 检查与第 2 节 008 空 storage-schema；不批准 application/runtime write path、真实 ACL、账号/权限业务运行时、真实数据、其他网络、部署或 production。

## 5. R3 Gate A：当前基线下的只读静态可签署性

Gate A 必须在任何 R3 签署前重新、只读完成；R2 的历史结果不能替代：

1. 严格 UTF-8/LF 机械复算 R1、R2 raw 与 decision identities，确认两文件未改，并确认 R2 仍为 `0/9 / NOT APPROVED / Gate B/C NOT AUTHORIZED`。
2. 复算 CR-001-R2 decision snapshot、R6 raw/decision identities；确认 R6 为当前已批准且 Gate B 已同步的 active-baseline source，但其 AUTH/DB/runtime 授权为零。
3. 复算第 3.1 节 11/11 current pre identities；验证 baseline manifest 九项与实际 Request 一致，`approval_pre_meta.py::_BASELINE_IDENTITY` 精确指向 current manifest。
4. 以 revision graph 证明 Alembic unique head=`20260807_007`；复算 007 source identity，确认 008 文件不存在且 `btree_gist` 已由既有 lineage 提供。
5. 对照 R1/R2 证明 R3 的规范覆盖只落在第 1.3 节六项治理集合；D-010～D-014、R2 action-time/storage-schema、008 对象/ACL/downgrade 和始终非授权范围零语义变化。
6. 验证第 4 节九角色 schema、当前十一文件领域投影、无环 DAG、two-literal re-pin 与 Gate 顺序闭合；不存在历史签名继承或 R2 approval 追认路径。
7. 以至少两个独立实现执行严格 UTF-8、LF、无 BOM/NUL/替换字符检查，并按第 8 节复算同一 R3 decision preimage/hash；任一结果不一致即失败。
8. material-value scan 必须为零：不得包含真实 secret、账号、业务数据、Provider/业务 endpoint、CIDR/Profile、production 放行值或新增网络许可。

Gate A 禁止修改 Request、manifest、pre-meta、migration、代码或 tracking；禁止连接数据库、Redis/Broker、Provider 或任何网络；禁止读取真实 `.env`、secret 或业务正文；禁止 Git 写。Gate A PASS 只证明候选可签署，不授权 Gate B/C 或任何实现。

## 6. 批准后 Gate B/C 与证据边界

### 6.1 Gate B：十一文件原子同步与 contract/offline

只有九角色以同一 R3 decision snapshot 有效批准后才授权 Gate B：

- 按第 3 节在临时区生成、验证并原子替换恰好十一文件；所有 pre/post identities、manifest 九项、two-literal re-pin、逆向重建和 UTF-8/LF 必须匹配。
- 每份 Request 的领域投影与 `CR-003-R3` 修订记录唯一；不得写入 `CR-003-R2 approved`、CR-013、operation-log/runtime、ACL、真实账号或其他候选合同。
- `approval_pre_meta.py` 逆向替换两个 literal 后必须精确恢复第 3.1 节 pre identity；既有 snapshot/Schema/decision universe 与 CLI scope 输出不变。
- `scripts/verify-baseline.ps1`、`backend/tests/unit/test_approval_pre_meta.py`、同步负向和回滚检查实际通过。
- contract/offline 测试不得连接数据库、Redis/Broker、Provider/其他网络，不读取真实 `.env` 或业务正文。
- Gate B 只有在 11/11 post identities、manifest、two-literal re-pin、逆向重建与全部验证同时 PASS 后，才产生唯一可供未来下游引用的 `R3 Gate B post evidence`；不得生成、补写或别名化任何 R2 post-sync evidence。

Gate B PASS 才可授权 Gate C，并解除“下游完全不可消费”的时序阻断；解除后也只允许未来 versioned successor 绑定 R1/R2/R3 snapshots 与本次 R3 Gate B post，再取得自身独立批准。Gate B 不创建表，不证明 ORM/catalog、AUTH runtime、P0、AC 或任何下游合同已批准。

### 6.2 Gate C：008 两空表 storage-schema / PostgreSQL 16

Gate C 完整继承 R2 第 6.3 节及其 downgrade 合同，不删减任何机械或行为要求。它只覆盖：

- 008 migration/ORM、两张空表、允许的 008-owned trigger/内部函数与 `users/roles` invariant trigger；
- local/disposable synthetic PostgreSQL 16 上的 role preflight、catalog manifest、CHECK/FK/GiST/状态/不可变/来源/双向/SoD/action-time、时钟 owner、往返、非空 downgrade、锁超时与 catalog 恢复；
- Ruff、format、mypy、聚焦/全量 pytest、Alembic single head、离线门禁与 PostgreSQL catalog Gate。

直接 SQL 只能称为 constraint probe。app wrapper 调用者绑定、真实 ACL、幂等、operation log、跨业务入口并发、Repository/Service/API 和业务 E2E 必须保持 `NOT_RUN / NOT AUTHORIZED`。

Gate C PASS 后只允许记录 `15/57` 与对应 storage-schema evidence；`BASE-005`、`work_package.AUTH-005` 仍为 partial，AUTH runtime、P0、AC-001 和任何其他 AC 不升级。

## 7. 失败、回滚与始终非授权范围

### 7.1 失败与回滚

- Gate A 任一 identity、encoding、lineage、current pin、语义 diff 或 scope 检查失败：保持 `NOT APPROVED`，不得签署或更新第 1～8 节的固定值来适配漂移；必须提升 successor。
- Gate B 任一生成、identity、领域投影、测试或原子替换失败：恢复完整十一项 pre bytes，不得保留部分 active baseline，也不得开始 008。
- R3 Gate B 未 PASS、失败或回滚时：R2 post-sync evidence 继续为不存在，R3 post evidence 也不得形成；全部下游消费必须失败关闭，禁止用部分 post、动态状态、历史 R2 Gate A 或外部说明补造 lineage。
- Gate C upgrade、catalog 或行为检查失败：保留实际失败状态，按 R2 合同执行安全前向修复；不得把离线 SQL/ORM metadata 冒充 PostgreSQL 16 证据。
- Gate C downgrade 完整继承 R2：先按 `break_glass_requests -> user_roles` 取得 `ACCESS EXCLUSIVE` 且 `SET LOCAL lock_timeout='5s'`；任一表非空以 SQLSTATE `55000` 原子失败，锁超时以 `55P03` 失败；禁止 `CASCADE/TRUNCATE/DELETE/导出后清空`。空表时再按 R2 固定顺序移除 008-owned 对象并证明 catalog delta 归零。

### 7.2 始终非授权范围

无论 R3 Gate A/B/C 状态如何，本 R3 始终不授权：

- Gate B PASS 前的任何下游消费，或 Gate B PASS 后未同时绑定 R1/R2/R3 snapshots、R3 Gate B post evidence 且未取得自身独立批准的下游合同/实现；
- `api.AUTH-005`、AUTH-011～AUTH-015 或任何其他账号/权限 API runtime；
- app-callable database wrapper、Repository、Service、Router、Worker、Scheduler、后台 expire/revoke runtime；
- application/worker ACL grant、认证调用者绑定、密码/Token/session、bootstrap、permission code 字典或真实管理员；
- `idempotency_records` 写链、operation log/action registry、Outbox、审计投影或业务 E2E；
- 真实用户、组织、角色、授权或其他业务数据的导入、清理、回填、迁移、导出后删除或修复；
- Redis、Broker、Provider、DNS、TLS、HTTP、Chat、Embedding 或其他网络；唯一例外仍是 Gate C 明确限定的本地/专用可丢弃合成 PostgreSQL 16，不得访问共享、远程或生产数据库；
- Docker image pull、云资源、部署、canary、production migration、production 放行、提交、推送或 PR。

后续 runtime 必须由独立、已批准并同步的合同冻结 app-callable signature、owner/grantee/ACL、认证 actor binding、idempotency、operation log、Repository/Service/API、并发锁序和恢复证据；不得从 R3 或 008 storage-schema Gate 推导授权。

## 8. R3 decision snapshot 与生命周期算法

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次；不得用 substring 命中正文或代码块。
4. decision preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256，小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定 R1/R2 identities、R2 未批准/历史 Gate 不继承边界、R2 post-sync evidence 从未产生且不得伪造的事实、CR-001/R6 anchors、current 十一项 pre identities、008 lineage、第 4 节审批 schema 和第 7 节非授权范围。
7. 第 1～8 节不得包含 R3 自身 snapshot hash、任何实际审批实例或任何 post-sync identity。R3 签署只以 R1/R2/R3 snapshots 与 current 11 pre identities 建立 CR-003 approval/post lineage；实际审批和未来 R3 Gate B post identities 只可进入第 9 节或外部 tracking，避免自引用。
8. 首条有效 approval、Gate B authorization 或下游消费事实产生前，第 1～8 节可在 review 阶段修订，但每次必须废弃旧 unsigned hash、重新执行完整 Gate A 并保持审批 0/9。
9. 任一有效 approval 或下游消费事实产生后，第 1～8 节任何 byte 变化必须提升至少 `CR-003-R4` 并重置九角色审批。
10. 第 9 节只记录动态生命周期，不能覆盖规范条款，也不改变 decision snapshot。
11. 生成 snapshot 只建立可签署对象，不等于批准；有效九角色批准前不得运行 Gate B，Gate B PASS 前不得执行 Gate C 或发生任何下游消费。未来下游只有显式绑定 R1/R2/R3 snapshots、经验证的 R3 Gate B post evidence 并独立获批后才可消费。

## 9. 当前状态

本节位于 decision snapshot 之外，只记录动态生命周期与证据，不得覆盖第 1～8 节。

| 项目 | 状态 |
|---|---|
| CR revision | `CR-003-R3；APPROVED / ACTIVE EFFECTIVE CONTRACT；GATE B PASS；GATE C PASS` |
| R1 base | `VERIFIED；raw 24838/7ca3e30460b4b2449c40a4ed01faa7cf05dbfaf0232214a0ed612cae43df48d7；decision 24270/cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045；FILE UNCHANGED` |
| R2 addendum | `VERIFIED；raw 37504/2e9c9e2c25d2e46fbc8de7ee738c08ef6a0a026f5af23f715d29d2131d653736；decision 35977/7a69b8555d422a7c2bee9d74da7030b8170692c934d83c12dd722c15c85c8363；FILE UNCHANGED` |
| R2 lifecycle inheritance | `FORBIDDEN；HISTORICAL GATE A NOT INHERITED；APPROVAL 0/9；GATE B/C NOT AUTHORIZED / NOT RUN` |
| CR-003 post-sync lineage | `R2 POST-SYNC EVIDENCE DOES NOT EXIST / MUST NOT BE FABRICATED；R3 GATE B POST PRODUCED；FUTURE CONSUMER MUST BIND R1/R2/R3 SNAPSHOTS + THIS R3 POST EVIDENCE AND OBTAIN INDEPENDENT APPROVAL` |
| CR-001 / R6 anchors | `VERIFIED；CR-001-R2 decision 22618/8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615；CR-011-R6 raw 65121/54a42ade8b20846504e56c6a004503216462f6c71807d0d21c94e74efd087ede；decision 60493/113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815` |
| D-010～D-014 delta | `ZERO；R1/R2 BUSINESS/SECURITY/DATA/RUNTIME SEMANTICS UNCHANGED` |
| current R6 eleven pre identities | `11/11 VERIFIED；BASELINE PIN CURRENT` |
| R3 Gate B nine Request post identities（第 3.1 节顺序） | `131596/d3a88b94fcc8351c71925ee944f63665ad1c029daba96513f1a2ac081dce9059；93300/150a986e14538242bd9c39ae1f0e8c91427b94d3f0752616dd7618859161d425；117732/458586e55b9360344a5b9e7485290dc378b89b2a19c251582707196dd7fcf341；330151/8f27af9edb3f195d26a0541d36ec3ab40bfe4c1f5ff864f454a70bafc1a64410；85242/6804fa2525cb7cf9f3293dc111e7a37aec83880bd2bafd2e19f8d20a7bfb8f14；53524/9b406bc5e7d82fce96b402aa6230aa44d7306acc681c2f892f9aea437c04ff82；52656/56b3ba9ae04b797452a9318db83fea9c1c8e4d5f20ce5981b6167e26dff37afb；56491/e008610d49c16c96cbb7819f9b5e017db3a500347acfec95142666279b8a5ab2；108745/dbfd0243b413cee89ad6d570a013e313704e053ae3b0f8217871ee7b6472b445` |
| R3 Gate B manifest / pre-meta post identities | `baseline-manifest=1689/a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3；approval_pre_meta=22193/331a8afef48e53a587d7454418426fdfe043b4813dc90322ea207627473b7cd9` |
| Alembic lineage | `UNIQUE SOURCE HEAD=20260807_008；DOWN_REVISION=20260807_007；007=65444/8ec278209d7b431aedca4b53b7dd9aaed1db413f6819841718522f68ff9bd0df；008 SOURCE / ORM PRESENT；CURRENT DISPOSABLE POSTGRESQL VERIFIED HEAD=20260807_008；EXACT ACCEPTED TABLES=15/57` |
| R3 Gate A | `PASS；AUTHOR + TWO INDEPENDENT READ-ONLY REVIEWS；NO HIGH/MEDIUM FINDING；STRICT UTF-8/LF；INDEPENDENT IMPLEMENTATIONS MATCH；AT GATE A REVIEW TIME: 0 PROJECT WRITE EXCEPT THIS NEW CANDIDATE / 0 DB / 0 NETWORK / 0 SECRET READ / 0 GIT WRITE` |
| 九角色审批 | `9/9 VALID；YHBX MERGED RECORD ENUMERATES ALL NINE ROLES；50/50 FIELDS；APPROVED 2026-08-11；EVIDENCE=THIS CODEX TASK USER APPROVAL MESSAGE` |
| Gate B Request / manifest / pin sync | `PASS；11/11 Q；9/9 REVISION + 9/9 PROJECTION UNIQUE；MANIFEST 9/9；TWO-LITERAL RE-PIN；11/11 BYTE-EXACT INVERSE；BASELINE/21 UNIT/CLI/TEST-ASSETS/NEGATIVE PASS；TWO INDEPENDENT ACTUAL-POST REVIEWS PASS；0 DB / 0 NETWORK / 0 SECRET READ` |
| Gate C FIX3 six-file identities | `008=54290/086d9a3bb27f1cf04460d44ace0df3c9b0b7ca23a1164fde7286bef38561380c；auth.py=19273/38a961ba3399b3cfd2a99f974ce119924c349f992c9ab0c8ed786e69f84afccd；models/__init__.py=1700/4c1ab7edf39b45887818ebb8e204b35f6e56995b69b2ad3487809392df766b09；test_auth_models.py=6284/a56542464833bda28d07b5096cf90f0e556f6481b06caad143ad11680fd472bc；test_reliability_models.py=23171/ac929b170af94b1bd28296a96e90a7b235b11ac30407133ff5cdd4e5375836b5；test_migrations.py=407351/2b0e56898edee8f1463c5cabaaffe542f304a691b8f21711717e1b9a387a6f16` |
| Gate C 008 empty storage schema | `PASS；POSTGRESQL 16.14；server_version_num=160014；INTEGRATION/DATABASE=71 TESTS；TWO ISOLATED CURRENT-HEAD ROUNDS=71/71 EACH；POSTGRESQL_CURRENT_HEAD=PASS；UPGRADE / EXACT CATALOG / STATE / SOURCE / BIDIRECTIONAL / SOD / ACTION-TIME / GIST / ROUNDTRIP / DOWNGRADE / FAILURE GUARDS VERIFIED；BACKEND FULL PYTEST=1782 PASSED / 54 SKIPPED；ACCEPTED-SOURCE RUFF / FORMAT 138 FILES / MYPY 77 SOURCES / PIP CHECK PASS；FRONTEND TYPECHECK / 222 VITEST / VITE WRITE-FALSE 119 MODULES PASS；TWO INDEPENDENT FINAL LOCK REVIEWS PASS / NO HIGH OR MEDIUM；DEDICATED LABELLED CONTAINER FINAL RESIDUAL=0；TEST_DATABASE_URL + CONFIRMATION VARIABLES RESTORED；RECOVERY CANDIDATE=NOT_APPLICABLE / BYTE-EXACT PRESERVED` |
| app wrapper / ACL / idempotency / oplog / Repository / Service / API runtime | `NOT AUTHORIZED / NOT IMPLEMENTED` |
| 真实数据 / Provider / 其他网络 / 部署 / canary / production | `NOT AUTHORIZED / NOT RUN` |
| R3 decision snapshot | `APPROVED；preimage_bytes=29321；decision_snapshot_sha256=35b1cdd758128afa485f91e34c5ef0dcfd95c4a648906e488099f68ff792e68c` |
