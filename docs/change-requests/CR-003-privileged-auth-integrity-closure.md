# CR-003-R1：特权授权数据完整性合同闭合

文档类型：合同候选；可变生命周期状态只记录在第 6 节。

日期：2026-08-07

对应差异：GAP-034～GAP-037

## 1. 变更原因与边界

`CR-001-R2/D-006` 已冻结 break-glass 的角色范围、人员关系、最长 4 小时和双人批准主流程，但当前 Request 仍不能唯一生成 `break_glass_requests`、`user_roles` 及 AUTH-011～AUTH-015：

1. `break_glass_requests.approved_by` 无法表达 AUTH-014 的拒绝操作者，且缺少 AUTH-015 所需的 `revoke_reason`。
2. `uq_user_role_active WHERE revoked_at IS NULL` 不感知 `expires_at`，自然过期但尚未回收的临时授权会阻止后续不重叠授权。
3. 长期职责分离只声明 production 生效，却没有可信且不可绕过的数据库环境来源。
4. 初始态、完整状态边、字段空值矩阵、乐观锁、角色分配来源矩阵、撤销与过期并发裁决以及含数据 downgrade 语义尚未冻结。

本 CR 只关闭 GAP-034～GAP-037，不改变 P0 的 57 张核心表总数，不增加角色，不放宽 `CR-001-R2/D-006`。它不批准 AUTH 运行时代码、真实环境迁移、production 放行或任何 Provider 网络调用。

## 2. 推荐合同

### 2.1 D-010：决定事实、状态机与并发裁决

#### 2.1.1 字段与初始态

- `break_glass_requests.approved_by` 改为 `decided_by UUID NULL REFERENCES users(id)`；数据库、API 和页面只使用 `decided_by`，不保留会形成第二事实来源的 `approved_by` 别名。
- 新行只能以 `status='pending'`、`row_version=1` 创建。`created_at/updated_at` 使用同一个数据库时间，`requested_duration_seconds` 必须是整数 `1..14400`。
- `id/organization_id/target_user_id/target_role_code/requested_by/reason/requested_duration_seconds/created_at/trace_id` 创建后不可修改；`reason/decision_reason/revoke_reason` 在要求非空时必须满足 `length(btrim(value)) > 0`。决定后，`decided_by/decision_at/decision_reason/effective_from/expires_at` 同样成为不可变批准/拒绝事实，撤销或过期不得改写。
- 请求人、目标用户和所有治理操作者必须属于请求组织且用户为 `status='active' AND deleted_at IS NULL`。请求人可以等于目标用户；决定人不得等于请求人或目标用户。

#### 2.1.2 唯一状态机

允许的状态边只有：

~~~text
pending  -> approved
pending  -> rejected
approved -> revoked
approved -> expired
~~~

`rejected/revoked/expired` 是终态。未列出的边全部禁止，包括同态 UPDATE、`pending -> revoked|expired`、`approved -> rejected|pending`、任何终态回退或终态之间转换。记录禁止物理 DELETE；继续授权必须创建新请求，禁止延期、续期或原地重开。

每条允许边的唯一 UPDATE 白名单固定为：

| 状态边 | 可修改字段 |
|---|---|
| `pending -> approved` | `status/decided_by/decision_at/decision_reason/effective_from/expires_at/row_version/updated_at` |
| `pending -> rejected` | `status/decided_by/decision_at/decision_reason/row_version/updated_at` |
| `approved -> revoked` | `status/revoked_by/revoked_at/revoke_reason/row_version/updated_at` |
| `approved -> expired` | `status/row_version/updated_at` |

任何未列字段的同时修改都由数据库拒绝，即使修改后的值仍满足空值、时间或跨表等值矩阵；空 UPDATE 也拒绝。`approved -> revoked|expired` 必须逐字保留原决定人、决定时间、决定原因、生效时间和到期时间。

字段非空/空值矩阵固定为：

| status | `effective_from` | `expires_at` | `decided_by` | `decision_at` | `decision_reason` | `revoked_by` | `revoked_at` | `revoke_reason` |
|---|---|---|---|---|---|---|---|---|
| `pending` | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL |
| `approved` | NOT NULL | NOT NULL | NOT NULL | NOT NULL | NOT NULL/非空 | NULL | NULL | NULL |
| `rejected` | NULL | NULL | NOT NULL | NOT NULL | NOT NULL/非空 | NULL | NULL | NULL |
| `revoked` | NOT NULL | NOT NULL | NOT NULL | NOT NULL | NOT NULL/非空 | NOT NULL | NOT NULL | NOT NULL/非空 |
| `expired` | NOT NULL | NOT NULL | NOT NULL | NOT NULL | NOT NULL/非空 | NULL | NULL | NULL |

数据库时间约束固定为：

- 批准事务在取得所需行锁后只捕获一次 `db_now=clock_timestamp()`，并写 `decision_at=effective_from=db_now`、`expires_at=db_now + requested_duration_seconds * interval '1 second'`；必须满足 `created_at <= decision_at=effective_from < expires_at`。
- 拒绝写 `decision_at=db_now >= created_at`，不得写生效、到期或撤销字段。
- 撤销只在锁内捕获的 `db_now < expires_at` 时允许，写 `revoked_at=db_now`，并满足 `effective_from <= revoked_at < expires_at`。
- 过期只在锁内捕获的 `db_now >= expires_at` 时允许，状态转为 `expired`，不伪造撤销人、撤销时间或撤销原因。即使后台尚未补写 `expired`，授权查询也必须以 `db_now < expires_at` 失败关闭。

#### 2.1.3 CAS、幂等与撤销/过期竞争

- 四条合法状态边每次成功都只递增一次 `row_version` 并写数据库 `updated_at`。AUTH-013～AUTH-015 必须携带当前 `row_version`，条件更新同时匹配 `id/status/row_version`；后台过期动作也必须以锁后读到的 `status='approved'` 和 `row_version` 做条件更新，不能无条件覆盖。0 行更新必须重读权威状态并返回或记录稳定的 `ROW_VERSION_CONFLICT` / `BREAK_GLASS_STATE_CONFLICT`，不得覆盖新状态。
- AUTH-011、AUTH-013、AUTH-014、AUTH-015 先按既有 `idempotency_records` 合同处理相同 Key：相同规范请求重放返回第一次结果，不再次执行状态边或递增版本；同 Key 不同请求哈希返回幂等冲突。`idempotency_records` 已由当前迁移链的 `20260807_003` 创建，本 CR 不重复创建或修改该表。
- 同一请求的批准、拒绝、撤销和过期都先锁定 `break_glass_requests`。AUTH-013/015 需要插入或撤销关联角色时，唯一总顺序固定为：请求行 → `user_roles SHARE ROW EXCLUSIVE` 表锁 → 受影响 `users`/`roles`/`user_roles` 行按各表 UUID 升序；锁后重新校验状态、版本和数据库时间。AUTH-014 与后台过期不修改角色，只持请求行锁。任何已取得 `user_roles` 表锁后再尝试锁 break-glass 请求的路径都禁止；普通角色 mutation 不读取或锁定 break-glass 请求。禁止用锁前快照裁决。
- 撤销与过期竞争时，以取得请求行锁后捕获的单一 `db_now` 裁决：`db_now < expires_at` 仅撤销可提交；`db_now >= expires_at` 必须提交 `approved -> expired`，撤销作为状态冲突返回。恰好等于 `expires_at` 时过期胜出。先提交的合法终态使另一事务 CAS 为 0 行；另一事务只能重读并返回权威终态。
- 批准必须与唯一临时 `user_roles` 插入处于同一事务；撤销必须与该角色分配的撤销三字段更新处于同一事务。任一步失败全部回滚，不允许只改变请求或只改变角色。

### 2.2 D-011：保存撤销事实

- `break_glass_requests` 新增 `revoke_reason TEXT NULL`。`status='revoked'` 时 `revoked_by/revoked_at/revoke_reason` 三者全部非空；其他状态三者全部为 NULL。
- 撤销人必须满足 2.5 节长期管理员谓词，但可以等于请求人、目标用户或决定人；撤销是降权动作，不新增第二人限制。
- 关联 `user_roles` 的 `revoked_by/revoked_at/revoke_reason` 必须与请求逐字段相等。不得把撤销原因只写操作日志、自由文本响应或 Redis。

### 2.3 D-012：角色分配来源矩阵与有效时间排除

`user_roles` 的来源字段矩阵固定为：

| `assignment_source` | `assigned_by` | `expires_at` | `break_glass_request_id` | 必须满足的等值/唯一关系 |
|---|---|---|---|---|
| `bootstrap` | NULL | NULL | NULL | 只允许一次性 bootstrap 路径创建；不引用 break-glass |
| `user` | NOT NULL | NULL | NULL | 普通 AUTH-008 长期分配；不引用 break-glass |
| `break_glass` | NOT NULL | NOT NULL | NOT NULL | `assigned_by=request.decided_by`、`assigned_at=request.effective_from`、`expires_at=request.expires_at`、`user_id=request.target_user_id`、角色代码等于 `request.target_role_code` |

同时冻结以下数据库不变量：

- `assignment_source='break_glass'` 当且仅当 `break_glass_request_id IS NOT NULL`；该外键必须 `UNIQUE`，一个请求至多对应一条角色分配。
- `bootstrap/user` 的 `expires_at` 和 `break_glass_request_id` 必须为 NULL，且只允许在写事务中捕获的数据库当前时间立即生效：`assigned_at=db_now`，禁止预约或客户端时间；`break_glass` 的 `assigned_by/expires_at/break_glass_request_id` 必须非空。`assigned_at` 创建后对全部来源不可修改，所有非空 `expires_at` 均满足 `assigned_at < expires_at`。
- `pending/rejected` 请求必须对应零条 `user_roles`；`approved/revoked/expired` 请求必须恰好对应一条。提交时的可延迟约束触发器必须验证基数、组织、用户、角色、决定人和时间等值关系，不能只由 Service 先查后写。
- `break_glass` 分配只能由 AUTH-013 的批准事务创建，且请求在该事务提交时必须为 `approved`；普通角色写入口不得伪造 `assignment_source` 或请求外键。
- `assignment_reason` 对三种来源都必须非空：bootstrap 精确为 `system_bootstrap`，user 精确等于 AUTH-008 经去首尾空白后的必填 `reason`，break-glass 精确等于请求的不可变 `decision_reason`；不得从模型输出、环境默认或 Scanner/Worker 错误生成。
- 请求—角色撤销矩阵固定为：`approved` 的关联分配 `revoked_by/revoked_at/revoke_reason` 全部为 NULL；`revoked` 时三者全部非空且与请求逐字段相等；`expired` 时三者全部为 NULL并仅由 `[assigned_at, expires_at)` 时间边界失效。普通 AUTH-008 及其 Repository 不得 UPDATE/DELETE `assignment_source='break_glass'` 的行；该行只有 AUTH-015 撤销事务可一次写撤销三字段，其他更新、物理删除或原地续期全部拒绝。双向可延迟触发器必须同时拒绝“请求 approved 但角色已撤销”和“请求 revoked 但角色未同步撤销”。
- 所有来源的 `id/user_id/role_id/assigned_by/assignment_source/assigned_at/expires_at/break_glass_request_id/assignment_reason` 创建后不可修改，全部 `user_roles` 物理 DELETE 均由数据库拒绝。`bootstrap/user` 新行的撤销三字段必须全为 NULL，之后只允许由 AUTH-008 的同一替换事务一次性从“全 NULL”变为 `revoked_by/revoked_at/revoke_reason` 全部非空，`revoked_at=db_now >= assigned_at`、reason 等于该请求经去首尾空白后的必填 reason；三者不得部分写入、清空或二次改写。重新授予同一角色必须 INSERT 新历史行，禁止原地更换角色、来源、操作者、原因或复活旧行。

删除 `uq_user_role_active(user_id, role_id) WHERE revoked_at IS NULL`，使用已批准的 `btree_gist` 扩展建立未撤销有效区间排除约束：

~~~sql
EXCLUDE USING gist (
  user_id WITH =,
  role_id WITH =,
  tstzrange(
    assigned_at,
    COALESCE(expires_at, 'infinity'::timestamptz),
    '[)'
  ) WITH &&
)
WHERE (revoked_at IS NULL);
~~~

同一 `(user_id, role_id)` 的未撤销区间不得重叠；区间固定为半开 `[assigned_at, expires_at)`，长期分配上界为 `infinity`。自然到期记录无需先更新或删除即可创建后续不重叠授权；重叠批准在数据库并发下只能一个提交。

### 2.4 D-013：环境无关的长期职责分离

- 所有环境统一禁止同一有效用户通过 `assignment_source IN ('bootstrap','user')` 同时长期持有 `system_admin` 与 `finance_reviewer`，或同时长期持有 `system_admin` 与 `audit_reviewer`。
- “有效长期分配”固定为：用户同组织、`status='active' AND deleted_at IS NULL`；角色 `is_enabled=TRUE`；分配来源为 `bootstrap/user`、`assigned_at <= db_now`、`expires_at IS NULL`、`revoked_at IS NULL`。
- 该不变量必须由数据库触发器在用户、角色和角色分配的相关 INSERT/UPDATE 上按事务内最终事实校验。不得使用客户端可设置的 session GUC、Header、环境变量或测试开关跳过；测试数据使用不同账号表达不同职责。
- 所有可能改变长期职责分离结果的 `user_roles` INSERT/UPDATE/DELETE 尝试、`users.status/deleted_at` 变更和 `roles.code/is_enabled` 变更，必须通过唯一数据库 mutation wrapper；应用与 Worker 角色没有目标表的直接写权限，DELETE 尝试由 wrapper 和表级触发器一律拒绝。普通 mutation 的唯一顺序是先取得 `user_roles SHARE ROW EXCLUSIVE` 表锁，再按 UUID 升序锁定受影响 user/role/user_roles 行并复验最终组合；AUTH-013/015 只能使用 2.1.3 的“请求行在前”专用 wrapper，且专用 wrapper 禁止再取得任何其他 break-glass 请求锁。相互冲突的长期授权事务因此被串行化；未按相应入口先取得锁的路径不得写表。禁止改用只读“先查后写”触发器或客户端 advisory lock。
- `break_glass` 限时分配不纳入长期组合约束，但必须满足本 CR 的请求、人员、时间、等值和唯一规则。AI、前端或客户端输出不得成为权限裁决事实。

### 2.5 D-014：治理动作只接受长期管理员

创建、批准、拒绝和撤销 break-glass 的管理员资格只接受当前有效的长期 `system_admin`，谓词固定为：

~~~text
users.organization_id = request.organization_id
AND users.status = 'active'
AND users.deleted_at IS NULL
AND roles.code = 'system_admin'
AND roles.is_enabled = TRUE
AND user_roles.assignment_source IN ('bootstrap', 'user')
AND user_roles.assigned_at <= db_now
AND user_roles.expires_at IS NULL
AND user_roles.revoked_at IS NULL
~~~

临时取得的 `system_admin` 不得创建、批准、拒绝或撤销其他 break-glass，避免权限链式延长。批准和拒绝的决定人必须同时不同于请求人和目标用户；单管理员环境 fail closed。任一满足上述谓词的同组织长期管理员都可撤销尚未到期的批准授权，D-014 不放宽自批、跨组织、禁用用户或单管理员限制。

## 3. 实施、同步与回滚

### 3.1 实施影响与依赖事实

获批并完成 Request 同步后，由当时下一个可用线性 Alembic revision 在同一切片创建 `break_glass_requests` 与 `user_roles`；本 CR 不预占 revision 编号，不创建种子、组织、用户或授权。创建顺序为 `break_glass_requests` 后 `user_roles`，再创建排除约束、状态/不可变触发器和可延迟跨表约束。

`organizations/users/roles` 与 `idempotency_records` 已在当前迁移链中存在；其中 `idempotency_records` 是已实现的既有事实，不再写成“待后续创建”的前置。完整 AUTH-005 仍依赖尚未实现的 `operation_logs`、Repository/Service/API、权限查询和 PostgreSQL 16 验收；两表 DDL 不等于 AUTH-005、AUTH-011～AUTH-015 或 AC-001 完成。

### 3.2 Request 同步范围

本 CR 获批后必须在一个受控变更中同步九份正式 Request，并重新生成基线哈希；同步完成前不得创建特权授权 migration：

1. **需求规格**：状态机、双人关系、长期管理员资格、最长 4 小时及撤销/过期裁决。
2. **系统架构**：Backend 权限裁决、数据库硬约束、事务/锁顺序，以及前端和 AI 不参与授权决定。
3. **数据库设计**：`decided_by/revoke_reason`、完整空值矩阵、`user_roles` 来源矩阵、排除约束、不可变/可延迟触发器和 downgrade 门禁。
4. **API 设计**：AUTH-011～AUTH-015 的 `decided_by` 响应、请求体、`row_version` CAS、幂等重放、稳定冲突和终态响应；删除 `approved_by` 别名。
5. **页面与交互设计**：五态展示、决定人/决定原因、撤销事实、版本冲突和过期优先语义，不由页面推断权限。
6. **AI/RAG/Prompt 设计**：明确模型输出不得创建、批准、拒绝、撤销或延长授权，本合同不需要 Provider 网络。
7. **测试与验收方案**：状态/空值/来源矩阵、职责分离、排除约束、CAS、幂等、双连接竞争及 downgrade 原子性。
8. **部署与运维说明**：维护模式、写入排空、固定锁顺序、5 秒锁超时、SQLSTATE `55000`、失败观察和前向修复。
9. **开发任务计划**：AUTH-005 的依赖、验收证据和“DDL 不等于 API/AC 完成”边界；同步对应追踪材料。

### 3.3 Downgrade 安全

- 执行 downgrade 前，部署流程必须进入维护模式、停止 Backend 新写入、排空 Worker 写任务并确认无活跃业务写事务；该准备不构成 production 放行。
- downgrade 在同一 PostgreSQL 事务先执行 `SET LOCAL lock_timeout = '5s'`，再严格按 `break_glass_requests`、`user_roles` 的顺序分别取得 `ACCESS EXCLUSIVE` 锁。锁超时必须完整失败，不得继续检查或 DDL。
- 取得两个锁后、执行任何 DDL 前，在同一快照检查两表。任一表存在任一行（包括 pending、rejected、revoked、expired 或已撤销角色历史）时，必须以 SQLSTATE `55000` 原子失败；两表、全部约束/触发器和 Alembic revision 保持不变。
- 只有两表均为空时，才按依赖安全顺序删除 `user_roles` 的约束/触发器和表，再删除 `break_glass_requests` 的对象和表。禁止 `CASCADE`、`TRUNCATE`、自动 DELETE、把数据导出后清空再删、改写终态或绕过门禁。
- 非空环境只允许保留当前 revision 并采用经评审的前向修复；数据导出或备份不是删除权威授权历史的许可。

## 4. 验收 Gate

- **状态与字段矩阵**：创建只接受 pending/版本 1；逐项覆盖四条允许边和所有禁止边，验证五态的 NULL/NOT NULL、非空文本、不可变字段、时间等式/不等式、终态不可改和禁止 DELETE。
- **CAS、幂等与锁序**：AUTH-013～015 覆盖正确/过期 `row_version`、相同 Key 同请求重放、同 Key 异请求冲突、两个决定并发及重放不重复递增；确认使用既有 `idempotency_records`，不创建第二套幂等事实。双连接覆盖 pending 批准与无效撤销、approved 撤销与普通角色 mutation 并发，证明请求行→表锁与普通表锁入口不会形成反向等待、死锁或超时泄漏。
- **撤销/过期竞争**：双连接在到期前、恰好边界和到期后竞争；证明锁后 `db_now` 唯一裁决、边界时 expired 胜出、只有一个终态提交，关联角色不会出现部分撤销。
- **来源与基数矩阵**：三种 `assignment_source` 覆盖 `assigned_by/assigned_at/expires_at/break_glass_request_id/assignment_reason` 的全部合法和非法组合；验证长期分配只可数据库当前时间立即生效、break-glass 请求外键唯一、字段等值、pending/rejected 为零分配、其余三态恰好一条分配，以及 approved/revoked/expired 与角色撤销三字段双向一致。覆盖普通/Bootstrap 原地换用户、角色、来源、操作者或原因，撤销三字段部分写入/清空/二次改写、DELETE 和旧行复活，全部必须失败；AUTH-008 修改 break-glass 行也必须失败。
- **时间排除**：同用户同角色覆盖重叠、相邻半开区间、长期与临时、自然到期后新授权、撤销后新授权和双连接同时批准；重叠只能一个提交且不依赖后台回收。
- **职责分离与治理资格**：所有环境拒绝长期冲突组合、未来 `assigned_at` 和任何环境开关绕过；两个连接分别并发插入冲突长期角色或并发启用角色时只能一个提交。验证所有 mutation wrapper 使用相同表锁/行锁顺序且应用角色不能直接 DML。临时 `system_admin` 不能治理其他请求；自批、决定人与目标相同、单管理员、跨组织、禁用用户和普通入口伪造 break-glass 全部 fail closed。
- **迁移往返**：PostgreSQL 16 空库 `head -> previous -> head` 可重复；分别在两表任一非空和两表均非空时验证 downgrade 在任何 DDL 前以 SQLSTATE `55000` 原子失败。第二连接分别持有两个目标表的冲突锁超过 5 秒时，验证锁超时不删除任何对象且 revision 不变。
- Ruff、格式、mypy、全量 pytest、Alembic 单一 head 和 PostgreSQL catalog 核对必须通过。未配置安全 `TEST_DATABASE_URL` 时真实 PostgreSQL 证据标记 `NOT_RUN`，不得以离线 SQL 或 ORM 元数据冒充。

## 5. 审批合同

### 5.1 精确审批角色矩阵

本 CR 必须作为一个不可拆分合同由下列九个角色全部签署；一人具备多个审批权限时可以合并一条记录，但 `approver_role` 必须逐项列出承担的全部角色。任一必需角色缺失、拒绝或附带互相冲突的条件时，整体保持 `NOT APPROVED`。

| `approver_role` | 必需 | 责任范围 |
|---|---:|---|
| `requirements_owner` | 是 | 五态、人员关系、时长、撤销/过期和用户可见语义 |
| `architecture_owner` | 是 | API→Service→Repository 边界、数据库硬约束和事务一致性 |
| `data_owner` | 是 | 两表 Schema、跨表不变量、排除约束、不可变性和历史保留 |
| `backend_api_owner` | 是 | AUTH-011～015、CAS、幂等、错误码和响应兼容性 |
| `frontend_ui_owner` | 是 | `decided_by`、五态、冲突与撤销事实的页面兼容性 |
| `ai_rag_owner` | 是 | AI 不参与权限裁决且本合同不授权 Provider 调用 |
| `test_owner` | 是 | 第 4 节全部矩阵、并发和 PostgreSQL 16 Gate |
| `operations_owner` | 是 | 维护模式、固定锁顺序、超时、SQLSTATE 和前向修复可实施性 |
| `security_owner` | 是 | 长期管理员资格、双人控制、职责分离和 fail-closed 边界 |

### 5.2 审批记录字段与选项

每条记录必须包含：

~~~text
approver_name / approver_role / decision=APPROVED|REJECTED /
selected_option / cr_revision / decision_snapshot_sha256 /
environment_scope=contract / decided_at_utc / evidence_uri / note
~~~

`selected_option` 必须逐字等于：

~~~text
D-010=DECIDED_BY_STATE_CAS;D-011=REVOKE_REASON;D-012=GIST_HALF_OPEN_RANGE;D-013=ENV_INDEPENDENT_SOD;D-014=LONG_TERM_ADMIN_ONLY
~~~

`cr_revision` 必须为 `CR-003-R1`，`decision_snapshot_sha256` 必须是第 5.4 节算法生成的同一 64 位小写十六进制值，`environment_scope` 必须为 `contract`，`decided_at_utc` 必须为 UTC RFC3339 时间。任何选项缺失、拼写不同、hash 不一致或 scope 扩大都不构成批准。

### 5.3 授权与禁止边界

合同获完整批准后，只授权同步第 3.2 节 Request、创建空表迁移并在离线/专用 PostgreSQL 16 测试库验证；不自动授权业务 API、真实历史数据处理、production migration、部署或放行。

在第 6 节记录的首次 snapshot 与全部必需签署完成前，本文件不授权：

- 修改或同步任何 `Request/` 文档；
- 创建或执行特权授权 migration、实现 AUTH-011～AUTH-015 或开放 API；
- 清理、导入、导出后删除或改写任何真实授权数据；

即使合同完成签署，本 CR 也始终不授权：

- 调用 `fixed_test_provider`、内部 vLLM、Chat、Embedding 或任何真实 Provider 网络；
- production、canary、部署、提交、推送或创建 PR。

### 5.4 Decision snapshot 算法

全文行尾先规范化为 LF。定位内容完全等于 `## 6. 当前状态` 的标题行；该标题行在全文必须恰好出现一次。取该行之前的全部行，并在末尾保留恰好一个 LF；将结果编码为无 BOM 的 UTF-8 bytes，计算 SHA-256，输出 64 位小写十六进制，作为 `decision_snapshot_sha256`。因此第 1～5 节全部纳入签署，当前状态表不进入 preimage。

首次 snapshot 生成只建立可签署对象，不等于批准。首次生成后，任何规范性内容变化都必须提升 CR revision、重新生成 hash 并清空全部签署；不得原地修改已签署 preimage。首次生成值只填写在第 6 节，不修改本节 preimage。

## 6. 当前状态

| 项目 | 状态 |
|---|---|
| CR-003-R1 | `DRAFT / PROPOSED / NOT APPROVED` |
| D-010～D-014 | `PROPOSED` |
| decision snapshot | `GENERATED FOR REVIEW；decision_snapshot_sha256=cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045；NOT APPROVED` |
| 审批记录 | `NONE` |
| Request 同步 | `NOT AUTHORIZED` |
| 特权授权 migration | `BLOCKED UNTIL APPROVAL AND REQUEST SYNC` |
| AUTH-011～AUTH-015 | `NOT AUTHORIZED` |
| fixed_test_provider / Provider 网络 | `NOT AUTHORIZED` |
| production / canary | `NOT AUTHORIZED` |
