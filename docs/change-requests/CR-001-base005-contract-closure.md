# CR-001：关闭 BASE-005 数据库契约阻断项

状态：`DRAFT`（未批准）  
决策状态：`PROPOSED`（以下内容仅为待审批推荐方案）  
CR 版本：`CR-001-R2`  
提出日期：2026-08-06  
影响范围：需求、架构、数据库、API、页面、AI/RAG、测试、部署与开发任务计划

> 本 CR 不修改正式需求基线，不代表任何推荐方案已经生效。只有第 8 节审批矩阵中每项标记为必需的负责人全部批准、迁移/回滚方案完成专项签署，并完成 `Request/` 内受影响事实来源的同步后，才允许据此实现完整 `BASE-005`。

## 1. 背景与当前边界

`BASE-005` 当前要求基于数据库设计中的 55 张 PostgreSQL 核心表生成基线迁移，并写入固定角色、P0 规则元数据和默认分块配置。八处跨文档冲突使开发者无法在不猜测契约的情况下完成该任务。原 `GAP-009` 经证据复核确认不存在第二个持久化活动索引事实，已于 2026-08-07 从本 CR 移出。

批准前只允许保留已经完成的安全基础设施切片：SQLAlchemy/Alembic/psycopg 配置、PostgreSQL 必需扩展、迁移测试隔离和相关文档。禁止创建未获批准的业务表、业务种子、默认组织、默认管理员或默认凭据，也禁止进入依赖完整数据库契约的 `BASE-006`。

## 2. 决策摘要

| 决策 | Gap | 待审批推荐方案 | 直接影响 |
|---|---|---|---|
| D-002 | GAP-010 | 扩展 `async_jobs`，新增追加写 `async_job_steps` | 可恢复 Job、幂等和阶段历史；新增 1 张表 |
| D-003 | GAP-011 | 在 `files` 持久化上传意图，并冻结到 Job 输入快照 | Worker 不依赖请求内存或 Redis 临时值 |
| D-004 | GAP-013 | 增加 `force_change_on_login` 和受限换密流程 | 临时密码不能换取完整会话 |
| D-005 | GAP-014 | 统一六态安全扫描枚举并全流程 fail-closed | 数据库、Adapter、API 和测试使用同一语义 |
| D-006 | GAP-016 | 新增 `break_glass_requests`，用双人控制批准限时授权 | 审批证据可验证；新增 1 张表 |
| D-007 | GAP-025 | 使用一次性离线 CLI 初始化首组织和首管理员 | 无匿名初始化 HTTP；凭据不进入参数或日志 |
| D-008 | GAP-026 | `BASE-005` 只建规则表；`AUD-003` 发布真实规则版本 | 不以占位规则或未知代码哈希充当种子 |
| D-009 | GAP-027 | `KB-004` 创建并发布首个组织级分块配置 | 参数成为受控版本，不在迁移中静默写入 |

按上述推荐，数据库清单新增 `async_job_steps` 和 `break_glass_requests` 两张表；在不合并或移除既有表的前提下，核心表总数将由 55 调整为 **57**。该数字只是本 CR 的推荐结果，必须经批准并同步数据库设计、开发计划和验收材料后才能成为新基线。

## 3. 待审批推荐合同

### 3.1 已移出：GAP-009

SRS、数据库、架构和 API 均可由 `document_index_versions.status='active'` 条件唯一及事务切换形成单一持久化事实；API 的 `active_index_version_id` 是校验入参或响应派生值，不是第二个数据库指针。因此本项不需要审批，原提议的 `expected_active_index_version_id` 重命名也不获得实现授权。

### 3.2 D-002：可恢复异步 Job

**推荐方案**

- 在现有 `async_jobs` 上补充：`input_json`、`input_schema_version`、`idempotency_record_id`、`lease_owner`、`lease_expires_at`、`heartbeat_at`；保留现有 `input_hash`、`attempt_no` 和 `max_attempts`。
- `input_json` 只保存执行所需的稳定标识、版本和参数，不保存文件正文、密码、Token、模型原文或其他 secret。
- 新增追加写 `async_job_steps`，至少包含 `job_id`、`step_seq`、`step_code`、`status`、`attempt_no`、开始/结束时间、脱敏摘要、错误码和 `trace_id`；已完成步骤禁止更新或删除。
- 活动任务条件唯一键为 `(organization_id, job_type, resource_type, resource_id, input_hash)`，适用于 `queued/running/cancel_requested`。
- 同一 Job 重试沿用 `job_id` 并递增 `attempt_no`；每次步骤执行追加新历史，不覆盖旧失败记录。
- Outbox 事件只携带 `job_id` 和事件 Schema 版本；Worker 从 PostgreSQL 重新读取输入和状态。Redis 只负责可恢复的投递、锁和短期协调。
- Lease 到期且心跳超时的 `running` Job 才允许被恢复；恢复动作必须受 `max_attempts` 限制并写操作日志。

**不采用的方案**

- 不把 Celery 消息体、Redis 值或 API 进程内对象作为唯一 Job 输入。
- 不为每次重试创建新的业务 Job，从而破坏幂等响应和追踪关系。

**批准后验收**

- Worker 在投递后崩溃、重启或丢锁时，可仅凭 PostgreSQL 继续或安全失败。
- 相同幂等键和相同请求不会生成第二个活动 Job；请求哈希不同返回冲突。
- Job/Step 历史可还原每次尝试，日志和错误均通过敏感信息检查。

### 3.3 D-003：上传意图与不可丢失输入

**推荐方案**

- 在 `files` 增加 `intended_business_type`、`target_knowledge_base_id` 和 `auto_process_requested`；后者表示该文件是否曾被请求进入自动处理，采用只允许 `FALSE → TRUE` 的单向语义。
- `intended_business_type='policy'` 时必须提供有效 `target_knowledge_base_id`；其他类型必须为空。该约束同时在 API Schema、Service 和数据库 CHECK/触发器执行。
- `file_primary_business_objects.business_type` 必须与 `files.intended_business_type` 一致，后续绑定不得改写原分类。
- 创建处理 Job 时，把 `file_id`、业务类型、知识库 ID、`auto_process_requested` 和输入 Schema 版本冻结到 `async_jobs.input_json`；Worker 不再读取原请求上下文。
- `auto_process_requested=false` 只停止解析、Markdown、分块和索引等业务流水线，不得跳过对象持久化、安全扫描和拒绝判定。
- 内容去重命中已有 `file_id` 时，业务类型和目标知识库必须与本次一致；不一致返回 `409 FILE_CLASSIFICATION_CONFLICT`，不得静默改写。
- 去重时必须同时处理 `auto_process_requested`：新请求为 `TRUE`、既有值为 `FALSE` 时，在行锁和幂等约束下原子升级为 `TRUE` 并最多创建一个处理 Job；两者相同则复用现有文件/Job。新请求为 `FALSE`、既有值为 `TRUE` 时不得取消或回退既有处理，响应必须显式返回 `reused=true`、有效值 `auto_process_requested=true` 和现有 Job 状态，避免把结果伪装为“仅存储”。
- 批量上传沿用同一规则；包含制度文件的批次必须显式提供目标知识库，禁止根据文件名猜测。

**不采用的方案**

- 不把 `business_type`、`knowledge_base_id` 或 `auto_process` 只保存在 Redis、Celery 消息或前端状态。
- 不在第一次业务对象绑定后反向推断原始上传意图。

**批准后验收**

- API 返回 202 后即使服务重启，Worker 仍能确定同一处理目标。
- 单文件上传、批量上传、去重复用和 `auto_process=true` 四条已定义路径得到一致分类结果；本决策不新增“首次手动启动处理”API。
- 制度文件不会进入错误知识库，非制度文件不会携带知识库目标。

### 3.4 D-004：首次登录强制换密

**推荐方案**

- `users` 增加 `force_change_on_login BOOLEAN NOT NULL DEFAULT FALSE`。
- 首管理员 bootstrap 和管理员密码重置必须把该字段设为 `TRUE`；用户完成强制换密后原子地设为 `FALSE`。
- 正确临时凭据命中该状态时，AUTH-001 返回 `403 AUTH_PASSWORD_CHANGE_REQUIRED`，只返回 5 分钟有效、用途限定为 `password:change` 的一次性 `password_change_token`，不返回 Access/Refresh Token，也不创建 `token_sessions`。
- 新增 `POST /api/v1/auth/password-change`：同时校验受限 Token、当前临时密码和新密码策略。成功返回 204，更新密码哈希、`password_changed_at`、`token_invalid_before`，撤销既有会话并消费该 Token；用户必须重新登录。
- 受限 Token 不得访问其他接口，不得进入日志、数据库明文字段、URL 或前端持久化存储。
- 管理员重置接口不得提供关闭强制换密的自由开关；P0 固定为强制。

**不采用的方案**

- 不向临时密码用户签发完整 Access/Refresh Token 后再依赖前端跳转换密。
- 不以 `password_changed_at` 是否为空推断状态；现有字段有其他审计语义。

**批准后验收**

- 临时密码无法调用任何业务 API，换密 Token 过期、重放或越权均被拒绝。
- 换密成功后旧临时密码、旧会话和旧 Token 全部失效。
- 登录和换密失败不泄露账号是否存在，且审计日志不包含密码或 Token。

### 3.5 D-005：文件安全扫描状态

**推荐方案**

统一 `security_scan_status` 为：

| 状态 | 语义 | 后续行为 |
|---|---|---|
| `pending` | 尚未完成扫描 | 不允许解析 |
| `clean` | 扫描通过 | 允许继续 |
| `infected` | 检出恶意内容 | 拒绝并隔离，不自动重试 |
| `scan_failed` | 扫描器或传输失败 | 可受限重试，不允许解析 |
| `unsupported` | 文件无法被当前扫描器处理 | P0 确定性拒绝 |
| `not_configured` | 当前环境未配置扫描器 | 仅本地/测试可记录；生产 fail-closed |

- 删除含糊的 `error`；历史数据迁移为 `scan_failed`，并保留原错误码于脱敏历史。
- API 响应和筛选使用独立 `security_scan_status`，不得与文件业务 `status` 混用。
- 当前扫描 Job、扫描器版本、时间和结果摘要通过 Job/Step 及审计记录追踪，不在 `files` 保存原始扫描输出。
- 生产环境扫描器未配置或不可用时，依赖健康检查失败，上传不得进入解析流水线。

**不采用的方案**

- 不把所有失败压缩为 `error`，也不把扫描失败当作 `clean`。
- 不允许 `not_configured` 在生产环境变成隐式放行。

**批准后验收**

- Adapter、数据库 CHECK、API Schema、筛选条件和测试夹具只使用上述六态。
- 只有 `clean` 可触发解析；其余状态均有确定性错误码和恢复策略。

### 3.6 D-006：break-glass 审批证据

**推荐方案**

- 新增 `break_glass_requests`，保存目标用户/角色、请求人、原因、请求时长、实际生效/结束时间、状态、批准人、决定时间、决定原因、撤销人、撤销时间、`row_version` 和审计字段。
- 状态统一为 `pending/approved/rejected/revoked/expired`；记录不可物理删除，决定后关键请求内容不可原地覆盖。
- `user_roles` 增加可空 `break_glass_request_id`。临时敏感角色分配必须引用已批准请求，并与目标用户、角色、`assigned_at` 和 `expires_at` 完全一致。
- 每个请求只允许申请一个临时角色；P0 allowlist 固定为 `system_admin/finance_reviewer/audit_reviewer/contract_admin`。`read_only` 必须通过普通 AUTH-008 流程授予，未知角色、多个角色或目标用户已经持有的有效角色均拒绝。
- 请求人必须是同一组织内有效且未禁用的 `system_admin`；目标用户必须是同一组织内有效且未禁用的用户，请求人可以等于目标用户。批准人必须是另一名有效 `system_admin`，且同时不得是请求人或目标用户。单管理员环境 fail-closed，必须先通过正常受控流程建立第二名管理员。
- AUTH-008 只管理普通固定角色；新增独立的请求、查询、批准、拒绝和撤销 API。批准与创建临时 `user_roles` 记录必须在同一事务中完成。
- P0 禁止预约未来生效：`requested_duration_seconds` 必须是 `1..14400` 的整数；批准事务以数据库当前时间同时写入请求的 `effective_from` 和角色的 `assigned_at`，再按已批准时长计算同一 `expires_at`。单次授权最长 **4 小时（14400 秒）**，禁止延期、续期或原地改写；仍需继续时创建新请求。**角色 allowlist、人员关系和 4 小时上限必须由安全负责人显式批准，否则 D-006 保持未决。**
- 授权判定以数据库时间为准，必须同时满足请求 `status='approved'`、`effective_from <= db_now < expires_at`，以及关联角色 `assigned_at <= db_now < expires_at`；后台回收任务只负责补写 `expired`，不能成为拒绝访问的唯一防线。

**不采用的方案**

- 不只在 `user_roles.assignment_reason` 中写自由文本批准信息。
- 不允许请求人自批、不允许单管理员自动降级绕过，也不复用普通角色替换接口隐式授予 break-glass。

**批准后验收**

- 未批准、自批、批准人与目标相同、跨组织、用户禁用、未知/多角色、`read_only`、已有有效同角色、未来生效、超过 4 小时、延期、过期、被撤销或字段不一致的授权均无法生效。
- 所有状态变化和访问拒绝均可从数据库审计证据独立复核。

### 3.7 D-007：首组织与首管理员 bootstrap

**推荐方案**

- 使用一次性离线 CLI；允许受控 Init Job 调用同一实现，但禁止匿名 HTTP 初始化入口。
- `BASE-005` 负责幂等写入五个全局固定角色。bootstrap 只验证角色集合和哈希完全匹配，然后创建单一组织、首管理员和首个 `system_admin` 分配。
- bootstrap 使用 PostgreSQL advisory lock 和单一事务；组织、用户、角色分配和审计记录任一失败则全部回滚。
- 首管理员必须 `force_change_on_login=TRUE`。密码仅允许从交互式 TTY、标准输入、受限文件描述符或 Secret Manager 注入，不允许出现在命令参数、环境回显、日志或文档中。
- 为解决首个分配没有合法操作者的问题，`user_roles.assigned_by` 仅在 `assignment_source='bootstrap'` 时允许为空；普通分配必须为 `assignment_source='user'` 且 `assigned_by` 非空。使用数据库 CHECK 强制该关系。
- 首次成功写 `operation_logs.action_code='system_bootstrap'`，允许 `actor_id=NULL`；只记录非敏感输入哈希、迁移 Revision、结果和 `trace_id`。
- 完全相同的组织与管理员身份参数重跑返回 no-op；已初始化后使用不同参数返回 `BOOTSTRAP_ALREADY_COMPLETED`。发现半初始化或角色种子不匹配时失败退出，不自动修复。

**不采用的方案**

- 不创建默认组织、默认用户名或默认密码。
- 不以临时伪用户满足 `assigned_by` 外键，也不在迁移脚本中读取真实凭据。

**批准后验收**

- 并发执行最多一次创建成功；重跑和冲突行为确定。
- secret 泄漏测试覆盖进程参数、控制台、日志、审计记录和错误响应。
- 初始化完成后必须先换密，随后才可创建第二名管理员或开展业务配置。

### 3.8 D-008：内置审核规则种子所有权

**推荐方案**

- `BASE-005` 只创建 `audit_rules` 表、唯一约束、不可变约束和 fail-closed 的版本化种子机制，不写任何规则行。
- `AUD-003` 在 15 条 P0 规则（RULE-001～RULE-015）的真实纯函数实现、输入 Schema 和测试完成后，发布首批规则版本。
- 每个规则版本必须同时携带真实 `implementation_key` 与按已发布代码计算的 `implementation_hash`；相同 `(rule_code, version)` 内容一致时重跑 no-op，内容不一致时失败，禁止覆盖。
- 规则发布由显式发布命令或版本化迁移执行，绑定应用发布版本并记录变更原因；应用启动不得自动补种或改写规则。
- `BASE-005` 的输出应由“固定角色/内置规则种子”调整为“固定角色种子、规则 Schema 与种子机制”；`AUD-003` 保持规则种子的唯一任务所有者。

**不采用的方案**

- 不写占位 `implementation_key`、虚假代码哈希或未实现规则。
- 不让 `BASE-005` 和 `AUD-003` 同时拥有同一批规则行。

**批准后验收**

- 空数据库完成 `BASE-005` 后规则表为空且 Schema 完整。
- 完成 `AUD-003` 后 15 条规则与实际注册函数、版本和测试一一对应，重复发布不产生漂移。

### 3.9 D-009：默认分块配置

**推荐方案**

- `BASE-005` 创建 `chunking_configs` 表和约束，但不写默认组织级配置。
- 首组织 bootstrap 完成后，由 `KB-004` 通过 CHUNK-001/CHUNK-002 创建并发布首个组织级配置；P0 不按制度类型复制多份默认配置。
- 首版推荐值：`strategy=markdown_ast_structural`、`target_length=700`、`max_length=1200`、`min_length=50`、`overlap_length=100`。
- 标题继承完整路径；小于最大长度的表格尽量整体保留，拆分时重复表头；只排除已批准的噪声模式。
- 配置发布后不可覆盖；任何参数变化创建新版本并保留 `config_hash`、发布人、时间和原因。
- **上述首版数值和处理策略必须由需求、AI/RAG 和架构负责人显式批准，否则 D-009 保持未决。**

**不采用的方案**

- 不在组织尚不存在的 `BASE-005` 迁移中写组织级配置。
- 不按文件名或制度类型静默选择不同参数，也不把 API 示例值直接当成已批准事实。

**批准后验收**

- 首个配置通过正式 API/Service 校验与发布，参数边界、哈希幂等和不可变约束可测试。
- 没有已发布配置时分块任务明确失败，不回退到代码内隐藏默认值。

## 4. 跨决策约束与实施顺序

1. 按第 8 节矩阵逐项批准 D-002～D-009；D-006 的批准人资格、角色 allowlist、人员关系和 4 小时上限必须由安全负责人明确签署，D-009 的首版参数必须由 AI/RAG 负责人明确签署。
2. 更新 `Request/` 中所有受影响事实来源，并重新生成基线哈希；同步前本 CR 不产生实现授权。
3. 将数据库核心表清单从 55 调整为经批准的最终数量；按当前推荐为 57，并更新全部引用和验收统计。
4. 实施 `BASE-005`：57 张表（若批准当前方案）、约束、触发器、固定角色种子和种子机制；不写组织、管理员、规则行或分块配置行。
5. 通过离线 bootstrap 创建首组织与首管理员，并完成强制换密。
6. `AUD-003` 完成真实规则实现后发布规则版本；`KB-004` 创建并发布首个分块配置。
7. 架构、数据库、运维和安全负责人先签署第 6 节迁移/回滚方案；随后执行 PostgreSQL 16 迁移、回滚/前向修复、并发、幂等、恢复、安全和端到端验收，才可标记相关任务完成。

## 5. 必须同步的事实来源

批准后至少同步以下 `Request/` 文档；同步内容必须保持单一事实来源和任务/API 编号一致：

- 需求规格：关闭对应 TBD，确认双人控制、首次换密、表数量和 P0 范围。
- 系统架构：Job 恢复、扫描 fail-closed、bootstrap 和职责分离。
- 数据库设计：57 表清单（若批准当前方案）、字段、枚举、约束、触发器和种子所有权。
- API 设计：上传意图、强制换密、break-glass 独立 API 和错误码。
- 页面与交互：强制换密状态、上传分类/知识库校验、临时授权审批状态。
- AI/RAG/Prompt：分块首版参数。
- 测试与验收：并发、幂等、崩溃恢复、扫描、换密、双人控制和 secret 泄漏用例。
- 部署与运维：迁移、固定角色种子、离线 bootstrap、规则发布和分块配置顺序。
- 开发任务计划：BASE-005、AUTH、FILE、KB-004、AUD-003 的输入、输出、依赖、表数和验收标准。

## 6. 迁移、回滚与失败处理

- 新装环境：按“扩展 → Schema → 约束/触发器 → 固定角色种子 → 离线 bootstrap → 业务配置/规则发布”执行。
- 已有环境：采用 Expand → Backfill → Validate → Switch → Contract；历史 `security_scan_status='error'` 回填为 `scan_failed`，保留脱敏来源信息。
- break-glass 批准必须单事务提交；外部派生状态失败时保留 PostgreSQL 已知状态并进入显式恢复，不伪装成功。
- 可逆 Schema 变更可使用 Alembic downgrade；涉及用户、授权、规则、任务历史或扫描结果的数据变换优先前向修复，不删除审计证据。
- 若任一推荐未获批准，回到该决策的备选方案评审，不得只实现其余部分后宣称 `BASE-005` 完成。

## 7. CR 验收门槛

- D-002～D-009 每项均形成单一、可执行、可测试的批准合同。
- 每项所需负责人及迁移/回滚专项审批记录均包含审批人、日期、决策版本和证据链接；不存在“口头同意”或默认同意，`N/A` 只表示该角色对该行不承担签署责任。
- `Request/` 九份文档的受影响内容已同步，表清单、API、任务和测试追踪无冲突。
- 空库升级、迁移失败原子性、已有数据保留、幂等重跑和恢复路径在 PostgreSQL 16 上通过。
- bootstrap、换密和 break-glass 的 secret/权限/并发测试通过。
- 本 CR 获批只表示契约可实施，不等于 `BASE-005`、P0 或 AC-001～AC-016 已验收通过。

### 7.1 规范性审批要求（纳入决策快照）

| 决策 | 必需签署角色 |
|---|---|
| D-002、D-003、D-004、D-005、D-006、D-008 | 需求、架构、数据库、安全负责人 |
| D-007 | 需求、架构、数据库、运维、安全负责人 |
| D-009 | 需求、架构、数据库、AI/RAG、安全负责人 |
| 第 6 节迁移/回滚方案 | 架构、数据库、运维、安全负责人 |

`N/A` 只允许用于不在上表必需集合内的角色；必需角色不得被表格空白、默认同意或口头同意替代。每条审批记录必须包含：`姓名 / 角色 / 决策编号 / APPROVED 或 REJECTED / 所选方案与批准值 / cr_revision / decision_snapshot_sha256 / 日期 / 证据链接 / 备注`。D-006 必须逐项记录批准人资格、角色 allowlist、人员关系和时长上限；D-009 必须记录完整首版参数；迁移/回滚必须链接 PostgreSQL 16 演练计划。

每条审批必须绑定 `cr_revision='CR-001-R2'` 和 `decision_snapshot_sha256`。计算时先把全文行尾规范化为 LF，定位内容完全等于 `## 8. 审批矩阵` 的 Markdown 标题行，取该行之前的全部行并在末尾保留恰好一个 LF，再对其 UTF-8 bytes 计算 SHA-256 小写十六进制；因此快照包含本节规范性审批要求但不含第 8 节可变记录。不同 revision/hash 的审批不得混合聚合；第 1～7 节或本节审批要求任一修改都必须提升 CR 版本并把全部签署重置为 `PENDING`。

## 8. 审批矩阵

所有必需签署项已由 `APR-20260807-YHBX-CR001` 明确批准。`N/A` 表示该负责人不承担该行签署责任，不得改写为默认同意。

| 决策 | 需求负责人 | 架构负责人 | 数据库负责人 | AI/RAG 负责人 | 运维负责人 | 安全负责人 |
|---|---|---|---|---|---|---|
| D-002 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-003 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-004 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-005 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-006 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-007 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | APPROVED [APR-CR001] | APPROVED [APR-CR001] |
| D-008 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | N/A | APPROVED [APR-CR001] |
| D-009 | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | APPROVED [APR-CR001] |
| 第 6 节迁移/回滚方案 | N/A | APPROVED [APR-CR001] | APPROVED [APR-CR001] | N/A | APPROVED [APR-CR001] | APPROVED [APR-CR001] |

本节只保存依据第 7.1 节生成的可变签署记录；第 7.1 节是角色、字段和快照规则的唯一规范来源，本节不得降低其要求。

### 8.1 APR-20260807-YHBX-CR001

| 字段 | 批准记录 |
|---|---|
| 姓名 | YHBX（BOSS） |
| 角色 | 需求负责人、架构负责人、数据库负责人、AI/RAG 负责人、运维负责人、安全负责人；审批人已明确声明具备全部必需审批权限 |
| 决策编号 | D-002～D-009；第 6 节迁移/回滚方案 |
| 决策 | APPROVED |
| 所选方案与批准值 | 批准第 3.2～3.9 节及第 6 节的全部推荐合同和精确值，不采用各节列出的备选方案 |
| D-006 明确批准值 | 批准人必须是另一名有效 `system_admin` 且不得是请求人或目标用户；P0 临时角色 allowlist 为 `system_admin/finance_reviewer/audit_reviewer/contract_admin`；请求人与目标用户可以相同，批准人必须与二者不同；`requested_duration_seconds=1..14400`，最长 4 小时，禁止预约、延期、续期或原地改写 |
| D-009 完整首版参数 | `strategy=markdown_ast_structural`、`target_length=700`、`max_length=1200`、`min_length=50`、`overlap_length=100`；继承完整标题路径；小于最大长度的表格尽量整体保留，拆分时重复表头；只排除已批准噪声模式 |
| 迁移/回滚演练计划 | 批准第 6 节方案；实施与 PostgreSQL 16 演练入口见 [数据库迁移运行手册](../database-migrations.md)，未实际通过的演练不得记为完成 |
| cr_revision | `CR-001-R2` |
| decision_snapshot_sha256 | `8dea28314445b331856ec9b9bf6662444bf92e265d74263f43659d230df5b615` |
| 日期 | 2026-08-07 |
| 证据链接 | Codex task `019fd61e-c0e0-76a1-ad69-7283325be591` 中用户明确审批声明 |
| 备注 | 授权同步受影响 `Request/` 文档；本记录不等于 BASE-005、迁移演练、P0 或 AC 验收通过 |

### 8.2 合同生效记录

- 生效日期：2026-08-07。
- `CR-001-R2` 的 D-002～D-009 与第 6 节迁移/回滚合同已同步至九份 `Request/` 事实来源；接口总数为 122、P0 核心物理表为 57、P0 工作包仍为 86。
- 页首 `DRAFT / PROPOSED` 与第 1～7 节中的待审批措辞属于已签署决策快照，不得在不提升 revision、使原签署失效的情况下改写；当前有效状态以本节的审批与生效记录为准。
- 本次生效解除对应合同阻断，不表示 BASE-005/006、AUTH、FILE、测试、迁移演练或 AC 已实现或通过。
