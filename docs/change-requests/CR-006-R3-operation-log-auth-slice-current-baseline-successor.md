# CR-006-R3：AUTH vertical slice operation-log current-baseline companion

> 文档状态：`PROPOSED / NOT APPROVED`
> Gate 状态：`BLOCKED / NOT RUN`
> decision snapshot：`NOT GENERATED`
> source baseline manifest SHA-256：`a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3`
> companion：`CR-013-R2-auth-system-admin-user-list-slice-successor.md`

## 1. 目的、证据与 current-baseline binding

本候选只定义首条 development/test AUTH 业务链所需的 operation-log companion。本文第 2～7 节中的值均为重新提出的 `candidate_values`，不是对 `CR-006-R1/R2`、`CR-008-R1/R2` 或其他旧候选的继承、批准或缩写。

当前事实边界：

- Request 明确要求认证审计至少覆盖登录、失败、锁定、退出、Token 撤销、权限拒绝及 `system_bootstrap`。
- Request 明确要求 `operation_logs` 追加写、脱敏、禁止应用账号 UPDATE/DELETE、按 `created_at` 月分区、每日链式哈希及备份清单。
- Request 当前字段表仍写成单列 `id UUID PK`。PostgreSQL 16 的分区表 PRIMARY KEY/UNIQUE 必须包含全部分区键，因此它不能与 `PARTITION BY RANGE(created_at)` 原样共存；本文候选必须显式改变日志身份，不能创建临时无分区表绕过。
- Request 的 `TBD-007` 尚未给出生产保留期；本文只能为 AUTH local/test 冻结安全的“不删除”值，不能猜测生产法定期限。
- 当前 accepted migration head 为 `20260807_008`，已验证 15/57 张正式核心表；当前 ORM、migration 与测试中不存在 `operation_logs` 或 `operation_log_chain_state` 实现。
- `GAP-046/GAP-053` 继续保持 `OPEN`。本文件获批也最多把它们推进到 AUTH slice 的 `PARTIAL`，不能冒充完整 P0 action registry、生产链或 AC。
- 已批准 `CR-003-R3` 不授权 operation-log migration、ACL、wrapper、Repository、Service、Router、账号或 runtime。
- BOSS direct-message approval、九角色集合、non-authoritative receipt、transition evidence 与十一文件 cooperative sync 协议由当前 `CR-014-R2-auth-oplog-current-baseline-approval-sync-successor.md` 候选单一拥有。本文把该依赖精确绑定为 `OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`，并拆成先后两个不可混用的 Gate：`C010-GOVERNANCE` 只表示 CR-014-R2 governance snapshot/direct approval 已有效，用于允许本文生成 source snapshot/A1；`C010-PUBLISH` 表示后续 A1/A2、bundle、joint authorization 与 cooperative publish 已完成，只约束 Request sync及实现。当前二者均未满足，因此 Gate A 继续阻塞。

本候选的 source-owner decision universe 恰为下列九个可审核选择值：

1. `OPLOGAUTH-D-001=AUTH_ACTION_REGISTRY_V1`
2. `OPLOGAUTH-D-002=TRUSTED_IDENTITY_AND_TELEMETRY_V1`
3. `OPLOGAUTH-D-003=PG16_COMPOSITE_TIME_IDENTITY_V1`
4. `OPLOGAUTH-D-004=UTC_MONTH_FAIL_CLOSED_DEFAULT_GUARD_V1`
5. `OPLOGAUTH-D-005=APPEND_ONLY_ACL_V1`
6. `OPLOGAUTH-D-006=LOCAL_TEST_DAILY_CHAIN_V1`
7. `OPLOGAUTH-D-007=LOCAL_TEST_RETENTION_BACKUP_RESTORE_V1`
8. `OPLOGAUTH-D-008=BOOTSTRAP_AND_FAULT_ATOMICITY_V1`
9. `OPLOGAUTH-D-009=AUTH_SLICE_ONLY_NO_PRODUCTION`

共同治理依赖值另固定为 `OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`。它不是第十个 substantive source decision，不进入 `CR-006-R3` 九项 `selected_decisions`；本文 source decision universe始终且仅为 `OPLOGAUTH-D-001～009`。`C010-GOVERNANCE` 只需当前 CR-014-R2 governance direct approval；`C010-PUBLISH` 才需其 source A1/A2、bundle、joint authorization与 cooperative transition。后置 publish 事实不得反向成为本文 snapshot/A1 的前置。

上述九项只有在 `CR006_R3_SOURCE_A1` BOSS direct message 逐项选择且第 8 节 `C010-GOVERNANCE` 已满足后才可能成为 approved values；C-010 只作为 dependency 单独验证，禁止追加为第十项 source selection，`C010-PUBLISH` 继续作为后置同步/实现 Gate。

## 2. `AUTH_ACTION_REGISTRY_V1` 候选

### 2.1 封闭字典

候选 registry version 固定为 `operation-log-auth-action-registry-v1`。每项身份是五元组 `(action_code, resource_type, producer_session_role, actor_mode, allowed_results)`；未知 action、resource、producer、actor mode、result、错误码或大小写变体全部 fail closed，不存在 `unknown/other/custom` 兜底。

`result` 字典恰为：

| code | 精确语义 |
|---|---|
| `success` | 该审计动作描述的状态效果已在同一 PostgreSQL 事务提交，或已接受的幂等 logout 请求完成且没有伪造新 revoke 效果 |
| `failure` | 已建立可信组织与目标用户的认证尝试失败；不是业务驳回、权限拒绝或系统异常的通用桶 |
| `denied` | 安全门禁阻止普通 session、目标 API 或目标权限效果发生 |

`resource_type` 字典恰为：

| code | `resource_id` 规则 |
|---|---|
| `user` | 必须是同一 `organization_id` 下已存在的目标 `users.id` |
| `token_session` | 必须是同一用户已验证的 `token_sessions.id`；不得保存 Token、hash 或 family secret |
| `api_request` | 必须为 NULL；目标对象 ID、URL 参数和“是否存在”事实不得写入摘要 |
| `organization` | 必须等于本行 `organization_id` |

`producer_session_role` 字典恰为：

| producer | 唯一入口 |
|---|---|
| `finaudit_app_rw` | `public.append_auth_operation_log_v1(...)`；只允许第 2.2 节前九个 action |
| `finaudit_bootstrap` | 唯一外部 `public.bootstrap_auth_system_admin_v1(...)`，由其内部调用 `public.append_system_bootstrap_log_v1(...)`；只允许 `system_bootstrap` |

producer 由 PostgreSQL `session_user` 和专用 wrapper 强制，不新增可由请求提交的 `producer` 列。两个 producer 必须直接认证；禁止共享登录后 `SET ROLE`、producer alias 或把应用用户冒充数据库 producer。

`actor_mode` 字典恰为：

| mode | `actor_id` | `actor_role_codes` |
|---|---|---|
| `authenticated_subject` | 必须是已验签、同组织且当前有效的用户 | PostgreSQL 在 action-time 计算的有效角色去重排序快照 |
| `verified_login_subject` | 必须是本次已完成真实密码验证、同组织且尚未签发普通 session/Access 的目标用户 | PostgreSQL 在 login action-time 计算的有效角色去重排序快照；只允许 login success/denied |
| `verified_refresh_subject` | 必须是本次 strict Refresh/session-family/auth-epoch 校验通过的同组织用户 | PostgreSQL 在 refresh action-time 计算的有效角色去重排序快照；不得声称持有或验证 Access |
| `known_pre_auth_target` | 必须 NULL | 必须 `{}`；只能用于已知组织与已知目标用户的登录失败/门禁/锁定 |
| `known_token_replay_target` | 必须 NULL | 必须 `{}`；只允许已验证 rotated-token hash 唯一定位到现有组织、用户和 session family 的首次 replay revoke |
| `verified_password_change_subject` | 必须是已验签 `password:change` purpose 的同组织用户 | action-time 有效角色快照；摘要另固定 `authorization_basis='password_change_purpose'` |
| `verified_logout_subject` | 必须是 CR-013-R2 logout-specific verifier 已建立的同组织 current active tail或 self-logout terminal 用户 | 必须 `{}`；只允许 AUTH-003 `logout_target_denied`，以及 self-terminal同 family的 `logout_without_new_revoke/auth.logout/logout_outcome='already_revoked'`；不授予角色、permission或资源访问 |
| `system_bootstrap` | 必须 NULL | 必须 `{}`；新管理员是被创建主体，不得伪装为 bootstrap actor |

### 2.2 exact action rows 与一语义一行规则

候选 action 恰为下列 10 个，`operation_log_action_delta=10`：

| `action_code` | resource | producer / actor mode | allowed result / error | 精确 emission |
|---|---|---|---|---|
| `auth.login.success` | `user` / 登录用户 | `finaudit_app_rw` / `verified_login_subject` | `success` / NULL | 普通 `token_sessions` row 与 session 审计各成功创建一次；每个成功普通登录恰一行，不冒充已存在 Access |
| `auth.login.failure` | `user` / 已知目标用户 | `finaudit_app_rw` / `known_pre_auth_target` | `failure` / `AUTH_INVALID_CREDENTIALS` | 已知用户的错误凭据尝试恰一行；第 5 次仍写本行 |
| `auth.login.denied` | `user` / 已知目标用户 | `finaudit_app_rw` / `verified_login_subject` | `denied` / `AUTH_ACCOUNT_LOCKED`、`AUTH_USER_DISABLED` 或 `AUTH_PASSWORD_CHANGE_REQUIRED` | 凭据正确但安全门禁不允许普通 session 时恰一行；force-change 不得写 `auth.login.success` |
| `auth.account.lock` | `user` / 被锁用户 | `finaudit_app_rw` / `known_pre_auth_target` | `success` / NULL | 只有本次事务实际执行 active→locked 时恰一行；第 5 次失败固定先写 failure，再写 lock |
| `auth.token.refresh` | `token_session` / 新 child session | `finaudit_app_rw` / `verified_refresh_subject` | `success` / NULL | AUTH-002 Refresh rotation 与新 child 提交时恰一行；未产生 child 的拒绝不写，绝不伪称 Access subject |
| `auth.logout` | `token_session` / 目标 terminal tail | `finaudit_app_rw` / `authenticated_subject` 或 exact `verified_logout_subject` self-terminal特例 | `success` / NULL | 每个获接受的 logout 请求恰一行；self-terminal只允许同 family重复 logout并固定空角色/`already_revoked`，不伪造新 revoke |
| `auth.token.revoke` | `user` / 被撤销用户 | `finaudit_app_rw` / `authenticated_subject`、`verified_password_change_subject` 或 `known_token_replay_target` | `success` / NULL 或 `AUTH_REUSE_DETECTED` | 只有至少一个 active session 首次转为 revoked 时恰一行；同一业务操作撤销多 family 仍聚合为一行并记录安全计数 |
| `user.password.change` | `user` / 换密用户 | `finaudit_app_rw` / `verified_password_change_subject` | `success` / NULL | 密码事实、门禁清除与 session revoke 同事务成功时恰一行 |
| `security.authorization.denied` | `api_request` / NULL | `finaudit_app_rw` / `authenticated_subject`、`verified_password_change_subject` 或 `verified_logout_subject` | `denied` / `AUTH_FORBIDDEN`、`AUTH_PASSWORD_CHANGE_REQUIRED` 或 `AUTH_TOKEN_REVOKED` | 已建立可信组织与主体的 403/隐藏资源拒绝恰一行；`AUTH_TOKEN_REVOKED` 只允许 AUTH-003 logout-specific verifier 已建立的 active或self-terminal actor之 target被拒绝，不记录原始目标 ID |
| `system_bootstrap` | `organization` / 新组织 | `finaudit_bootstrap` / `system_bootstrap` | `success` / NULL | 首组织、首管理员、首个长期 `system_admin` 与本行同事务成功时恰一行，也是首条 operation log |

每个 HTTP/CLI 事件有且只有一个由可信 Service/CLI 内部生成的 RFC 4122 UUIDv4 `request_event_id`；它不得来自 HTTP body、query、header、Cookie 或其他客户端输入。AUTH Service 对一个业务事件恰调用一次第 5.1 节 batch wrapper；wrapper 对该批次只取一次数据库 `event_created_at`，按下表派生 `emission_order`，调用方不得提交 emission order：

| event profile | exact ordered rows `(emission_order,action_code)` |
|---|---|
| `login_success` | `(10,auth.login.success)` |
| `login_failure_below_threshold` | `(10,auth.login.failure)` |
| `login_failure_and_lock` | `(10,auth.login.failure),(20,auth.account.lock)` |
| `login_denied` | `(10,auth.login.denied)` |
| `refresh_rotated` | `(10,auth.token.refresh)` |
| `refresh_replay_first_revoke` | `(10,auth.token.revoke)` |
| `logout_without_new_revoke` | `(10,auth.logout)`；active actor使用 `authenticated_subject`；self-terminal同 family幂等特例使用 `verified_logout_subject`且 `logout_outcome='already_revoked'` |
| `logout_with_revoke` | `(10,auth.logout),(20,auth.token.revoke)` |
| `password_change_without_active_session` | `(10,user.password.change)` |
| `password_change_with_revoke` | `(10,user.password.change),(20,auth.token.revoke)` |
| `authorization_denied` | `(10,security.authorization.denied)` |
| `logout_target_denied` | `(10,security.authorization.denied)`；固定 `actor_mode='verified_logout_subject'/api_id='AUTH-003'/http_method='POST'/error_code='AUTH_TOKEN_REVOKED'` |
| `standalone_session_revoke` | `(10,auth.token.revoke)` |
| `system_bootstrap` | `(10,system_bootstrap)`；只经 bootstrap wrapper |

不存在其他 action sequence、空批次、三行批次、重复 order 或单独 `auth.account.lock`。expired temporary lock 的 `locked->active` 不新增 action，必须由该请求最终产生的 `auth.login.success/failure/denied` summary 携带 `lock_transition='expired_to_active'`；CR-013-R2 必须冻结 expired+wrong 的最终事实为 `active/failed_login_count=1`。logout 首次实际撤销 session 时使用 `logout_with_revoke`；幂等重复或已过期但获接受时使用 `logout_without_new_revoke`；logout-specific verifier 已建立的 active或self-terminal actor之 AUTH-003 target拒绝使用 `logout_target_denied`。第 5 次登录失败固定使用 `login_failure_and_lock`。Refresh replay 只有首次实际撤销 active tail 时使用 `refresh_replay_first_revoke`；重复 replay 不伪造第二次 revoke。一个 batch 由单次函数调用以一个 INSERT statement 写入，任一行失败则全批次和同事务业务效果回滚。

### 2.3 AUTH 摘要白名单

`before_hash/after_hash/reason` 在本 AUTH slice 全部固定为 NULL。`change_summary_json` 必须是 JSON object，固定含 `schema_version='auth-operation-log-summary-v1'`，且 action-specific 键集和值域恰为：

- login success：`lock_transition` 只允许 `none/expired_to_active`。
- login failure：`cause_code='AUTH_INVALID_CREDENTIALS'`、`counter_outcome` 只允许 `incremented/unchanged`、`lock_transition` 只允许 `none/expired_to_active`；active 普通错误及 expired+wrong→active/count1 为 `incremented`，当前 locked/disabled 的错误密码为 `unchanged`。
- login denied：`cause_code` 只允许本 action 三个安全 error code，`lock_transition` 只允许 `none/expired_to_active`。
- account lock：`cause_code='threshold_reached'`、`lock_transition='active_to_locked'`。
- refresh：`rotation_outcome='rotated'`。
- logout：`logout_outcome` 只允许 `revoked/already_revoked/expired`。
- token revoke：`revoke_reason_code` 只允许 `logout/reuse_detected/password_changed/user_disabled/password_reset/admin_revoked`，`affected_session_count` 为 `1..9007199254740991` 的整数。
- password change：`authorization_basis='password_change_purpose'`。
- authorization denied：`api_id` 必须命中同 revision 的批准 API identity，`http_method` 只允许大写批准方法；`error_code='AUTH_TOKEN_REVOKED'` 时必须逐值为 `actor_mode='verified_logout_subject'/api_id='AUTH-003'/http_method='POST'`；不得含 path、query、body 或 resource ID。
- bootstrap：第 6.1 节六个固定键。

禁止额外键、自由文本、原始异常、用户名、邮箱、密码、hash、Token、Header、Cookie、URL、请求体或数据库错误正文。

## 3. `TRUSTED_IDENTITY_AND_TELEMETRY_V1` 候选

### 3.1 unknown username/Token 边界

下列请求不能建立可信 `organization_id/actor_id`，因此不写 `operation_logs`：未知/软删除 username、无法建立组织的 username、缺失/畸形/伪造/过期/unknown-kid Token、hash 不存在的 Refresh Token，以及 Token 不能唯一解析到当前组织和用户的请求。

它们只允许输出 `security.auth.pre_identity_rejected.v1` 脱敏 telemetry，字段恰为：

```text
event_schema_version, trace_id, occurred_at, endpoint_id,
safe_reason_code, client_network, user_agent_prefix, identity_digest
```

- `safe_reason_code` 只允许 `UNKNOWN_IDENTITY/MALFORMED_CREDENTIAL/INVALID_TOKEN/EXPIRED_TOKEN/RATE_LIMITED`，不得区分会泄露用户存在性的内部原因。
- `identity_digest` 只允许对 canonical identity 使用独立 rate-limit secret 的 HMAC-SHA-256；无 identity 时为 NULL。secret、原值和可逆编码不得输出。
- telemetry 不是 PostgreSQL operation-log 事实、不能计入 `operation_log_action_delta`、不能满足 AC-001/AC-015，也不能用 synthetic organization/user/resource UUID 补空。
- 已识别用户的错误密码属于第 2 节 `auth.login.failure`；仅“unknown username 统一 401”走本 telemetry。

### 3.2 trusted proxy、IP 与 User-Agent

local/test Profile 固定为 `oplog-client-context-local-test-v1`：

- `trusted_proxy_cidrs=[]`；只信任 ASGI/TCP immediate peer，`Forwarded/X-Forwarded-For/X-Real-IP` 一律忽略。future proxy allowlist、右向左链解析和 production Nginx 绑定必须另行批准。
- immediate peer 不能解析为 IPv4/IPv6 时 `ip_address=NULL`；可解析时先规范化，再把 IPv4 低 8 bit 清零并保存为 `/24`，IPv6 低 72 bit 清零并保存为 `/56`。operation log 永不保存完整 client IP。
- User-Agent 缺失时为 NULL。存在时先拒绝 CR/LF/NUL 及 C0/C1 控制字符，再 trim ASCII space，按 UTF-8 从左保留最多 256 bytes且不切断 code point；空结果为 NULL。完整 User-Agent、第二个 header 值和被截断后缀不保存。
- `ck_operation_logs_ip_prefix_v1` 只允许 NULL、IPv4 `/24` 或 IPv6 `/56`；`ck_operation_logs_user_agent_v1` 只允许 NULL 或 `octet_length<=256` 且无控制字符。

上述字段与 operation log 行使用相同 local/test 无限保留边界；production 隐私/保留评审仍未授权。

## 4. PostgreSQL 16 storage candidate

### 4.1 表、列、PK、unique 与 FK

`public.operation_logs` 候选为 `PARTITION BY RANGE (created_at)`，列恰为：

| column | PostgreSQL 16 type | null/default |
|---|---|---|
| `id` | `UUID` | NOT NULL；`DEFAULT pg_catalog.gen_random_uuid()` |
| `organization_id` | `UUID` | NULL |
| `actor_id` | `UUID` | NULL |
| `actor_role_codes` | `TEXT[]` | NOT NULL；`DEFAULT '{}'::text[]` |
| `action_code` | `VARCHAR(100)` | NOT NULL |
| `resource_type` | `VARCHAR(80)` | NOT NULL |
| `resource_id` | `UUID` | NULL |
| `before_hash` | `CHAR(64)` | NULL |
| `after_hash` | `CHAR(64)` | NULL |
| `change_summary_json` | `JSONB` | NOT NULL；`DEFAULT '{}'::jsonb` |
| `reason` | `TEXT` | NULL |
| `result` | `VARCHAR(20)` | NOT NULL；无默认 |
| `error_code` | `VARCHAR(80)` | NULL |
| `ip_address` | `INET` | NULL |
| `user_agent` | `TEXT` | NULL |
| `trace_id` | `UUID` | NOT NULL |
| `correlation_id` | `UUID` | NULL |
| `request_event_id` | `UUID` | NOT NULL；无默认，由可信 Service/CLI 每事件生成 UUIDv4 |
| `emission_order` | `SMALLINT` | NOT NULL；无默认，只允许 wrapper 派生 `10` 或 `20` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL；`DEFAULT pg_catalog.clock_timestamp()` |

固定约束：

- `operation_logs_pkey PRIMARY KEY(created_at,id)`。日志身份、cursor、导出、备份和任何未来引用必须使用完整二元组；禁止单列 `id` PK/UNIQUE 或只携带 `operation_log_id` 的 FK。
- `uq_operation_logs_event_emission_v1 UNIQUE(created_at,request_event_id,emission_order)`；它包含 partition key，因而可由 PostgreSQL 16 在 partitioned parent 上真实实现。一个 wrapper batch 的全部行必须共享同一数据库 `created_at`，所以该约束只负责拒绝该 batch/同一 `created_at` 下同 event/order 的重复 emission；它不声称提供跨 timestamp 或跨 partition 的全局唯一。
- `fk_operation_logs_organization_v1` → `organizations(id)`，`ON UPDATE RESTRICT ON DELETE RESTRICT`。
- `fk_operation_logs_actor_v1` → `users(id)`，`ON UPDATE RESTRICT ON DELETE RESTRICT`。
- `resource_id` 是多态目标，不建伪 FK；存在性、组织一致性和第 2 节字典由 wrapper 在同事务验证。
- `organization_id/actor_id` 列保持 nullable 以兼容 Request 的系统语义，但本 registry 的 10 个 action 全部要求 organization 非空；actor NULL 只允许第 2 节精确模式。
- CHECK 固定限制三态 result、action/resource 小写格式、hash 小写 64 hex、摘要为 object、actor role array 无 NULL、`emission_order IN (10,20)`、`request_event_id` 为 RFC 4122 UUIDv4、IP/UA 为第 3.2 节边界。
- 当前没有其他表引用 operation log；未来 FK 必须引用 `(created_at,id)`。PostgreSQL 16 不提供跨所有 range partition 的单列 UUID unique，应用层查重或 trigger 扫分区不能冒充数据库唯一约束。`request_event_id` 的跨分区不复用是 wrapper protocol invariant：每个 append 先取得该 UUID 的 transaction advisory lock，再扫描 parent 拒绝任何历史命中；restore verifier、sealer 与 Gate C 还必须扫描并拒绝跨不同 `created_at`/partition 重复的 `(request_event_id,emission_order)`，但本 slice 不为此新增全局索引表。

父级查询索引恰为：

```text
(organization_id, created_at DESC, id DESC)
(organization_id, resource_type, resource_id, created_at DESC, id DESC)
(organization_id, actor_id, created_at DESC, id DESC)
(organization_id, action_code, created_at DESC, id DESC)
(trace_id, created_at DESC, id DESC)
(request_event_id, created_at ASC, emission_order ASC, id ASC)
```

本 slice 不创建 `change_summary_json` GIN。

`public.operation_log_chain_state` 是新增的 singleton 技术父表，列恰为：

| column | type | null/default |
|---|---|---|
| `state_key` | `TEXT` | PK；只允许 literal `active` |
| `chain_id` | `UUID` | NOT NULL UNIQUE |
| `chain_epoch_utc` | `DATE` | NOT NULL |
| `genesis_sha256` | `CHAR(64)` | NOT NULL |
| `genesis_verified_at` | `TIMESTAMPTZ` | NOT NULL |
| `sealed_through_utc_date` | `DATE` | NULL |
| `sealed_day_anchor_sha256` | `CHAR(64)` | NULL |
| `sealed_manifest_sha256` | `CHAR(64)` | NULL |
| `append_enabled` | `BOOLEAN` | NOT NULL DEFAULT false |
| `bootstrap_completed_at` | `TIMESTAMPTZ` | NULL |
| `row_version` | `BIGINT` | NOT NULL DEFAULT 1；CHECK > 0 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL DEFAULT `clock_timestamp()` |

sealed 三元组必须全 NULL或全非 NULL；非空日期不得早于 epoch。`append_enabled=true` 只允许在 `bootstrap_completed_at` 非空时成立；maintenance/restore 可以保持完成事实不变而关闭 append。表只允许一行；不得 DELETE、创建第二条 active state、跳日、回拨封账水位或复用历史 chain ID。

genesis identity 不再使用隐含空值或 32-byte zero 常量。`initialize_operation_log_chain_v1()` 在一个 `db_now=pg_catalog.clock_timestamp()` 下生成 UUIDv4 `chain_id`，并令 `chain_epoch_utc=(db_now AT TIME ZONE 'UTC')::date`。genesis object 恰为以下五键；值的 UUID、DATE 与 SHA-256 均使用小写 canonical text，禁止额外键：

```json
{
  "chain_epoch_utc": "<YYYY-MM-DD>",
  "chain_id": "<lowercase-hyphenated-uuid>",
  "registry_version": "operation-log-auth-action-registry-v1",
  "schema_version": "operation-log-chain-genesis-v1",
  "source_baseline_manifest_sha256": "a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3"
}
```

canonicalization 与 domain separation 精确为：

```text
genesis_jcs         = RFC8785_JCS(genesis_object)
genesis_preimage    = UTF8("finaudit.operation-log.genesis.v1\n") || UTF8(genesis_jcs)
genesis_sha256_raw  = SHA256(genesis_preimage)                         # 32 bytes
genesis_sha256      = lowercase_hex(genesis_sha256_raw)                # 64 chars in state
genesis_verified_at = db_now
```

所有 state-mutating/append/seal/restore-verify 函数均须从 state 的 `chain_id/chain_epoch_utc` 与上述固定 registry/baseline 常量重建 object，重新计算并比较 raw hash；不匹配固定失败关闭为 `OPLOG_CHAIN_GENESIS_MISMATCH`。任何 JSON whitespace、key insertion order 或 hex text bytes 都不是 chain 输入。

### 4.2 UTC 月分区、default 与 late rows

- 初次 upgrade 创建 current UTC month、后两个完整 UTC month和 `operation_logs_default`。range 名称固定 `operation_logs_yYYYYmMM`，边界固定 UTC 半开区间 `[month_start 00:00:00Z,next_month_start 00:00:00Z)`；Session timezone 不改变边界。
- `public.ensure_operation_log_partitions_v1()` 是零参数、`SECURITY DEFINER`、每日候选 `00:05 UTC` 运行的唯一 future partition 入口，只能验证或创建“当前+后两月”。它不得 DROP/DETACH/TRUNCATE/RENAME、接收日期/表名/SQL、ATTACH 既有表或修改历史分区。
- app/bootstrap caller 不得提交 `id/created_at/actor_role_codes`。wrapper 取得数据库 `clock_timestamp()` 后按实际 UTC 日路由；AUTH runtime 因此没有 caller-supplied late row。
- `operation_logs_default` 只是不接收正常数据的防御对象。它具有相同 PK/UNIQUE/查询索引、不可变 trigger 与 ACL，并额外安装 `trg_operation_logs_default_reject_insert_v1 BEFORE INSERT FOR EACH ROW`，调用 `public.reject_operation_log_default_insert_v1()` 无条件抛 `SQLSTATE 55000`，其唯一安全 message/code 为 `OPLOG_DEFAULT_PARTITION_INSERT_REJECTED`，不含 relation、row、constraint、SQL 或原始异常。runtime、owner wrapper或 direct INSERT 均不得向 default 成功写一行。
- wrapper 先取得唯一 `db_now=pg_catalog.clock_timestamp()`，从其 UTC 月机械生成 `operation_logs_yYYYYmMM`，并在 INSERT 前验证该具名 relation 是 `operation_logs` 的 range child、bound 覆盖 `db_now`、owner/index/trigger/ACL 均等于本 revision allowlist。缺失或任一漂移固定抛 `OPLOG_PARTITION_UNAVAILABLE`，整笔 AUTH/审计事务回滚并只尝试外部 `CRITICAL` telemetry；不得改投 default或写 operation log。验证通过后 INSERT 仍核对 `tableoid` 等于该具名月分区；任何 DDL race 导致路由 default 会由上述 trigger 原子拒绝。
- default 必须始终零行。partition maintenance 发现 default 非空、具名月分区缺失或 bound/owner/index/trigger/ACL 漂移时统一失败关闭并输出 `OPLOG_PARTITION_MAINTENANCE_FAILED`；不得搬移、UPDATE、DELETE 或为恢复服务而接收临时行。
- 每日封账后禁止向 `sealed_through_utc_date` 及更早 UTC 日写入；时钟回拨或任何 privileged historical import 固定失败。COPY、直接 child INSERT 与 restore-side ACL replay 均不在 runtime 权限内。

default 路由失败遵循第 5.2 节封闭 safe-code 矩阵；telemetry 失败不改变数据库回滚，也不递归写 operation log。

## 5. append-only、chain、retention 与维护候选

### 5.1 owner/ACL 与受控入口

候选角色集合恰为：

```text
finaudit_oplog_ddl_owner          NOLOGIN
finaudit_oplog_runtime_owner      NOLOGIN
finaudit_bootstrap_owner          NOLOGIN
finaudit_migrator                 LOGIN, exact ACL controller + explicit SET ROLE
finaudit_app_rw                   LOGIN
finaudit_bootstrap                LOGIN
finaudit_oplog_partition_scheduler LOGIN
finaudit_oplog_chain_sealer       LOGIN
finaudit_restore_controller       LOGIN
finaudit_audit_ro                 LOGIN
finaudit_backup                   LOGIN
```

全部角色必须 `NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS/NOINHERIT`。角色必须在 migration 前由 local/test fixture 或部署/IaC 预置；migration 只验证 catalog，不创建真实账号、密码或 membership。migration 必须以 direct `session_user=current_user='finaudit_migrator'` 启动，禁止 superuser、其他 owner或 `SET ROLE` 后进入。role membership catalog 恰有三条本 slice 所需边：`finaudit_migrator -> finaudit_oplog_ddl_owner`、`finaudit_migrator -> finaudit_oplog_runtime_owner`、`finaudit_migrator -> finaudit_bootstrap_owner`，均为 `admin_option=false,inherit_option=false,set_option=true`；其他上述角色之间无 membership。生产者、scheduler、sealer、restore、read-only 与 backup 身份禁止 `SET ROLE` 到任一 owner 或彼此；禁止 nested role chain。

schema `public` 的 `PUBLIC CREATE` 必须已撤销。唯一 ACL controller `finaudit_migrator` 的部署前 catalog前置恰为：对 `public` schema持有 `USAGE,CREATE WITH GRANT OPTION`，对 `public.organizations(id)` 与 `public.users(id)` 各持有 column-level `REFERENCES WITH GRANT OPTION`；不得依赖 table ownership、schema ownership、superuser或未列 grant option。该 controller capability由 local/test fixture或IaC显式预置，本 migration只 fail-closed验证且不扩大。最终 catalog 中 `finaudit_oplog_ddl_owner` 保留 `USAGE,CREATE` 以供唯一 future partition function；`finaudit_oplog_runtime_owner` 与 `finaudit_bootstrap_owner` 最终只保留 `USAGE`。direct `current_user=finaudit_migrator` 必须在同一 migration transaction 内临时授予后两者 `CREATE`，并分别临时授予 DDL owner上述两个 column-level `REFERENCES`；创建并验证两个 FK及各自函数后、commit 前由同一 controller撤销全部临时 `CREATE/REFERENCES`并重验。最终 DDL owner对两张上游表没有 table-level或column-level `REFERENCES`。本 slice 的其他 LOGIN roles只需 `USAGE`，不得取得 schema CREATE。所有 SECURITY DEFINER 固定 function config `SET search_path = pg_catalog, public, pg_temp`，body 内 relation/function/type/operator全部 schema-qualified。每个 revision-owned function 创建后必须先按其完整 identity `REVOKE ALL ... FROM PUBLIC`及所有 LOGIN roles，再只授予下表精确 EXECUTE；`PUBLIC` 对任一函数均无 EXECUTE。

migration 创建顺序固定为：以 direct `finaudit_migrator` 验证上述 roles/membership与 controller exact grant options -> 由该 current_user在 transaction 内临时授予 runtime/bootstrap owner `USAGE,CREATE`及 DDL owner 两个 exact column-level `REFERENCES` -> `SET LOCAL ROLE finaudit_oplog_ddl_owner`，先创建两个 reject trigger functions，再创建 table/FK/partition/index/trigger及 `ensure_operation_log_partitions_v1` -> `RESET ROLE`恢复 `current_user=finaudit_migrator`、验证两个 FK并撤销 DDL owner临时 `REFERENCES` -> `SET LOCAL ROLE finaudit_oplog_runtime_owner` 创建 initialize/两个 lower append/complete/seal/restore functions -> `RESET ROLE`并由 migrator撤销 runtime-owner CREATE -> `SET LOCAL ROLE finaudit_bootstrap_owner` 创建唯一外部 bootstrap function -> `RESET ROLE`并由 migrator撤销 bootstrap-owner CREATE -> 应用第 5.1.2 节 grants并重验临时 grant零残留、controller grant-option前置未漂移。任一 session/current user、顺序、owner、transient/final ACL不等时整个 migration transaction回滚。

#### 5.1.1 exact function identities

函数名称、输入、返回、owner 与 security mode 恰为：

```text
public.initialize_operation_log_chain_v1()
  RETURNS TABLE(chain_id UUID, chain_epoch_utc DATE, genesis_sha256 TEXT, created BOOLEAN)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.append_auth_operation_log_v1(
  p_request_event_id UUID,
  p_organization_id UUID,
  p_actor_mode TEXT,
  p_actor_id UUID,
  p_action_codes TEXT[],
  p_resource_types TEXT[],
  p_resource_ids UUID[],
  p_results TEXT[],
  p_error_codes TEXT[],
  p_change_summaries JSONB[],
  p_trace_id UUID,
  p_correlation_id UUID,
  p_ip_address INET,
  p_user_agent TEXT
)
  RETURNS TABLE(request_event_id UUID, event_created_at TIMESTAMPTZ, log_identities JSONB)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.append_system_bootstrap_log_v1(
  p_request_event_id UUID,
  p_organization_id UUID,
  p_bootstrap_input_sha256 TEXT,
  p_admin_user_id UUID,
  p_user_role_id UUID,
  p_trace_id UUID,
  p_correlation_id UUID,
  p_ip_address INET,
  p_user_agent TEXT
)
  RETURNS TABLE(request_event_id UUID, event_created_at TIMESTAMPTZ, log_identities JSONB, created BOOLEAN)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.complete_operation_log_bootstrap_v1(p_request_event_id UUID)
  RETURNS TABLE(chain_id UUID, bootstrap_completed_at TIMESTAMPTZ, row_version BIGINT)
  VOLATILE PARALLEL UNSAFE SECURITY INVOKER

public.bootstrap_auth_system_admin_v1(
  p_request_event_id UUID,
  p_trace_id UUID,
  p_correlation_id UUID,
  p_bootstrap_input_sha256 TEXT,
  p_organization_id UUID,
  p_organization_name TEXT,
  p_unified_social_credit_code TEXT,
  p_tax_number TEXT,
  p_admin_user_id UUID,
  p_admin_username TEXT,
  p_admin_email TEXT,
  p_admin_display_name TEXT,
  p_admin_password_hash TEXT,
  p_user_role_id UUID,
  p_ip_address INET,
  p_user_agent TEXT
)
  RETURNS TABLE(chain_id UUID, organization_id UUID, admin_user_id UUID,
                system_admin_role_id UUID, user_role_id UUID,
                force_change_on_login BOOLEAN, bootstrap_completed_at TIMESTAMPTZ,
                request_event_id UUID, event_created_at TIMESTAMPTZ,
                log_identities JSONB, created BOOLEAN)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.ensure_operation_log_partitions_v1()
  RETURNS TABLE(month_start DATE, partition_name TEXT, outcome TEXT)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.seal_operation_log_day_v1()
  RETURNS TABLE(utc_date DATE, row_count BIGINT, day_anchor_sha256 TEXT, sealed_manifest_sha256 TEXT)
  VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.verify_operation_log_restore_v1(p_backup_manifest JSONB)
  RETURNS TABLE(chain_id UUID, operation_log_row_count BIGINT, sealed_through_utc_date DATE, unsealed_tail_sha256 TEXT, verified BOOLEAN)
  STABLE PARALLEL UNSAFE SECURITY DEFINER

public.reject_operation_log_mutation_v1()
  RETURNS TRIGGER VOLATILE PARALLEL UNSAFE SECURITY DEFINER

public.reject_operation_log_default_insert_v1()
  RETURNS TRIGGER VOLATILE PARALLEL UNSAFE SECURITY DEFINER
```

`finaudit_oplog_runtime_owner` 拥有 initialize、两个 lower append、complete、seal与 restore verifier；`finaudit_bootstrap_owner` 只拥有 `bootstrap_auth_system_admin_v1`；`finaudit_oplog_ddl_owner` 拥有两表、所有 partition/index/trigger、revision-owned composite/check objects、两个 reject trigger functions及 `ensure_operation_log_partitions_v1()`。owner 均不得是 LOGIN role。调用外部 wrapper时 `session_user=finaudit_bootstrap/current_user=finaudit_bootstrap_owner`；进入 SECURITY DEFINER initialize或 lower append后 `session_user`仍为 `finaudit_bootstrap`、`current_user=finaudit_oplog_runtime_owner`；lower append调用 SECURITY INVOKER complete时 `current_user`仍为 runtime owner。任何文本或测试不得把 initialize 的 owner/grantee/current_user误写为 bootstrap owner。

两个 append 的 `log_identities` 必须是 JSON array，元素按 `emission_order ASC`，每项根精确三键 `created_at/emission_order/id`：时间为 UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`、order 为 JSON integer 10或20、id 为 lowercase canonical UUID；每项 `(created_at,id)` 必须逐值等于实际复合主键，禁止返回或持久化裸 `log_ids`。

#### 5.1.2 exact EXECUTE 与 table grants

| function identity | 唯一 EXECUTE grantee | 约束 |
|---|---|---|
| `initialize_operation_log_chain_v1()` | `finaudit_bootstrap_owner`（NOLOGIN） | 只允许外部 bootstrap wrapper 内部调用；无 LOGIN EXECUTE |
| `append_auth_operation_log_v1(uuid,uuid,text,uuid,text[],text[],uuid[],text[],text[],jsonb[],uuid,uuid,inet,text)` | `finaudit_app_rw` | 必须 direct `session_user`；一次调用恰写一个完整事件 batch |
| `append_system_bootstrap_log_v1(uuid,uuid,text,uuid,uuid,uuid,uuid,inet,text)` | `finaudit_bootstrap_owner`（NOLOGIN） | 只允许外部 bootstrap wrapper 内部调用；无 LOGIN EXECUTE |
| `complete_operation_log_bootstrap_v1(uuid)` | 无 | 只允许 runtime-owner bootstrap wrapper 内部调用 |
| `bootstrap_auth_system_admin_v1(uuid,uuid,uuid,text,uuid,text,text,text,uuid,text,text,text,text,uuid,inet,text)` | `finaudit_bootstrap` | 唯一外部 bootstrap入口；必须 direct `session_user`，禁止经 SET ROLE |
| `ensure_operation_log_partitions_v1()` | `finaudit_oplog_partition_scheduler` | 仅 future local/test DB function call |
| `seal_operation_log_day_v1()` | `finaudit_oplog_chain_sealer` | 仅 future local/test DB function call |
| `verify_operation_log_restore_v1(jsonb)` | `finaudit_restore_controller` | ingress blocked 的 disposable restore drill only |
| 两个 trigger functions | 无 | 只由绑定 trigger 调用 |

返回集合也固定：initialize、两个 lower append、complete、外部 bootstrap 与 restore verifier成功时恰返回一行；两个 append与外部 bootstrap的 `log_identities` 按上述复合 identity顺序排列。ensure 成功时恰返回 current UTC month、+1 month、+2 month 三行并按 `month_start ASC`，`outcome` 只允许 `verified/created`。seal 每次只处理最早 eligible UTC 日并返回一行；没有 eligible 日时返回零行而不改 state。restore verifier 的成功行必须 `verified=true`；任一 manifest/schema/hash/count/topology/ACL 不匹配直接抛 safe error，不返回 `verified=false` 的“软成功”行。

table grants 恰为：runtime owner 对 `operation_logs`/全部 children有 `SELECT,INSERT`，对 chain state有 `SELECT,INSERT,UPDATE`；另只有下列 business column SELECT：`organizations(id,status,deleted_at)`、`users(id,organization_id,status,deleted_at,failed_login_count,locked_until,force_change_on_login,token_invalid_before)`、`roles(id,code,is_system_role,is_enabled)`、`user_roles(id,user_id,role_id,assignment_source,assigned_at,expires_at,revoked_at)`、`token_sessions(id,user_id,issued_at,expires_at,revoked_at,revoke_reason,last_seen_at)`。后继 010 创建 family 七列时必须原子追加 `token_sessions(family_id,parent_session_id,replaced_by_session_id,rotation_counter,remember_me,auth_epoch,reuse_detected_at)` SELECT，未追加前对应 AUTH runtime保持 blocked。runtime owner 明确无 `users.password_hash` 与 `token_sessions.refresh_token_hash` SELECT。

bootstrap owner 只有：`organizations(id,name,unified_social_credit_code,tax_number,status,deleted_at)` SELECT和 `organizations(id,name,unified_social_credit_code,tax_number,status)` INSERT；`users(id,organization_id,username,email,display_name,status,failed_login_count,locked_until,password_changed_at,force_change_on_login,token_invalid_before,deleted_at)` SELECT和 `users(id,organization_id,username,email,display_name,password_hash,status,failed_login_count,locked_until,password_changed_at,force_change_on_login,token_invalid_before)` INSERT；`roles(id,code,is_system_role,is_enabled)` SELECT；`user_roles(id,user_id,role_id,assigned_by,assignment_source,assigned_at,expires_at,break_glass_request_id,assignment_reason,revoked_at)` SELECT和 `user_roles(id,user_id,role_id,assigned_by,assignment_source,assigned_at,expires_at,break_glass_request_id,assignment_reason)` INSERT。bootstrap owner不得 SELECT `users.password_hash`，密码 hash只允许作为外部函数参数通过静态 parameter binding 写入。

DDL owner以 ownership管理 revision objects；`finaudit_audit_ro`只有 operation log parent SELECT；`finaudit_backup`只有两表 SELECT。除上述精确值外，`PUBLIC`与所有 LOGIN roles对两表/children均无 `INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER`，也无 schema DDL；runtime owner对 business tables无 INSERT/UPDATE/DELETE，bootstrap owner无 UPDATE/DELETE/TRUNCATE。

#### 5.1.3 wrapper 与 bootstrap state machine

`initialize_operation_log_chain_v1()` 是创建 singleton state 的唯一 lower-level入口，但不是外部入口。它先验证 `session_user='finaudit_bootstrap'`；由于 `finaudit_bootstrap` 无 EXECUTE、唯一 grantee是 NOLOGIN `finaudit_bootstrap_owner`，它只能由下述外部 wrapper调用。它取得固定 initialization advisory transaction lock并锁定 parent/state：

1. state 不存在且 `operation_logs` 全部 partition/default精确零行时，按第 4.1 节生成 genesis，创建唯一 `state_key='active'`、`append_enabled=false/bootstrap_completed_at=NULL/row_version=1` row，返回 `created=true`；
2. 恰有一个已完成 state、genesis可重算且 topology合法时只返回现值和 `created=false`，不更新、也不重新 enable；这只服务外部 wrapper 的成功幂等重入；
3. state 缺失但任一日志存在、未完成 state已从先前 transaction 泄漏、state多行、genesis不匹配或 topology漂移时，以 `SQLSTATE 55000,message=OPLOG_CHAIN_GENESIS_MISMATCH` 失败；不得推断、补齐或自动修复 chain identity。

唯一外部 bootstrap入口 `bootstrap_auth_system_admin_v1(...)` 必须验证 direct `session_user='finaudit_bootstrap'` 且 `current_user='finaudit_bootstrap_owner'`；结合第 5.1 节禁止 bootstrap role membership/SET ROLE的 catalog约束，这构成唯一 direct caller。它取得同一个 initialization advisory transaction lock，把本事务唯一 `db_now` 固定为 `pg_catalog.transaction_timestamp()`，并在一次 top-level function call/一次 PostgreSQL transaction内完成 initialize、business rows、首条审计与 complete。输入约束恰为：`p_request_event_id` 是非 NULL UUIDv4；`p_trace_id/p_organization_id/p_admin_user_id/p_user_role_id` 非 NULL；`p_correlation_id/p_admin_email/p_ip_address/p_user_agent` 可 NULL；其余 TEXT输入非 NULL并先按现有 column长度/格式约束验证；`p_bootstrap_input_sha256` 是 lowercase 64-hex；`p_admin_password_hash` 只接受 companion已冻结的 Argon2id encoded-hash profile。wrapper重建的 hash object恰为十二键 `schema_version/organization_id/organization_name/unified_social_credit_code/tax_number/admin_user_id/admin_username/admin_email/admin_display_name/user_role_id/system_admin_role_id/force_change_on_login`，其中 `schema_version='auth-oplog-bootstrap-input-v1'`、`system_admin_role_id='00000000-0000-0000-0000-000000000101'`、末项为 true；hash为 `lowercase_hex(SHA256(UTF8(RFC8785_JCS(object))))`，必须等于参数。password hash、IP、UA、trace/correlation/request UUID均不进入该 object。

上述第 5.1.1 节十六参数顺序及十一返回字段是本 source owner选择的唯一 protocol。当前 CR-013-R2 §6.3 已逐参数、nullability与返回顺序采用同一值；任何回退到十四参数旧顺序、缺失 `p_correlation_id/p_bootstrap_input_sha256`、六字段窄返回、双签名 overload或兼容 wrapper均为 `NOT SELECTED`，并使两份 A1、C-010与 Gate继续 blocked。

`append_auth_operation_log_v1(...)` 必须验证 direct `session_user='finaudit_app_rw'`、state存在且 `append_enabled=true/bootstrap_completed_at IS NOT NULL`、genesis与partition topology精确。它对 `p_request_event_id` 取得 event advisory transaction lock，扫描 parent；任一历史 row已使用该 UUID即以 `SQLSTATE 55000,message=OPLOG_EVENT_ID_REUSED` 拒绝。数组必须同为一维、lower bound 1、长度恰为 1或2，且其 action sequence精确命中第 2.2 节一个非-bootstrap profile。函数只取一次 `event_created_at=pg_catalog.clock_timestamp()`，从 array ordinal派生 `emission_order=ordinal*10`，在 action-time从 PostgreSQL计算 `actor_role_codes`，并以一个 INSERT statement写完整 batch。调用方可提交的只有签名列出的业务 identity/context；不得提交 `id/created_at/emission_order/actor_role_codes/producer`、before/after hash或 reason。所有 nullable array element、summary key、actor/resource/result/error与组织绑定均由 wrapper fail closed。

除 bootstrap 入口外，所有 append 在 state disabled时统一以 `SQLSTATE 55000,message=OPLOG_APPEND_DISABLED` 拒绝。外部 wrapper在新装分支使用同一个数据库 `db_now` 静态 parameter binding插入：一个 active organization；一个 active admin user（`failed_login_count=0/locked_until=NULL/password_changed_at=db_now/force_change_on_login=true/token_invalid_before=db_now`）；以及 role ID `00000000-0000-0000-0000-000000000101` 的长期 `system_admin` assignment（`assigned_by=NULL/assignment_source='bootstrap'/assigned_at=db_now/expires_at=NULL/break_glass_request_id=NULL/assignment_reason='system_bootstrap'`）。它随后调用 lower `append_system_bootstrap_log_v1(...)`；该函数只在 direct bootstrap session、state disabled、completion NULL、全部日志零行且上述 business facts精确匹配时写一条 `(10,system_bootstrap)`，再在返回前由 runtime owner内部调用 `complete_operation_log_bootstrap_v1(request_event_id)`。internal complete重验本 transaction唯一新增首行、summary/input hash及上述 business facts，然后设置 `bootstrap_completed_at=db_now/append_enabled=true/row_version=row_version+1`。任何 LOGIN role均无 complete EXECUTE；任何一步失败，chain state、organization、user、assignment、首行与 completion全部回滚，不存在合法的已提交 disabled半成品。

幂等分支仍经同一个外部 wrapper与 lower append执行：已完成 state（包括 maintenance暂时 `append_enabled=false`）只有在 organization/user/assignment及唯一 `system_bootstrap` 的六键 summary全部精确匹配时，返回已持久化的 chain/business/request/event/`log_identities` 与 `created=false`，不读取或比较既有 `password_hash`、不追加、不更新、不重新 enable；不同 input hash固定 `BOOTSTRAP_ALREADY_COMPLETED`。未完成 state、半初始化 business facts、首行数量/identity/summary不匹配均以 `OPLOG_CHAIN_GENESIS_MISMATCH` fail closed且不自动修复。

其余精确权限边界：

- 两表、所有 partition 对 `PUBLIC` 与全部 LOGIN producer 撤销 `INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER`；app/bootstrap 没有 direct table DML。
- `finaudit_app_rw` 与 `finaudit_bootstrap` 的 EXECUTE恰为第 5.1.2 节；bootstrap只可执行外部 wrapper，initialize/lower append/internal complete均无 LOGIN EXECUTE。
- scheduler 仅 EXECUTE `ensure_operation_log_partitions_v1`；chain sealer 仅 EXECUTE `seal_operation_log_day_v1`；restore controller 只可在 ingress blocked 的 local/test restore drill 调用只读 verifier，不获得 append 或 DDL。
- `finaudit_audit_ro` 只有 `SELECT operation_logs`；`finaudit_backup` 只有两表 SELECT。两者无 function execute、DML、DDL 或 role membership。
- runtime owner只拥有内部 append/state函数所需权利且不能登录；bootstrap owner只拥有外部 bootstrap wrapper及第 5.1.2 节最小 business grants且不能登录；DDL owner只拥有 revision DDL objects（包括两个 reject trigger functions）且不能登录。migrator只在受控 migration会话显式 SET ROLE，不得把 owner权限转授 producer。
- `reject_operation_log_mutation_v1` 在父表及每个 partition/default 拒绝 UPDATE/DELETE/TRUNCATE，错误码固定 `OPLOG_IMMUTABLE`。partition maintenance 只能创建未来 partition；本 revision 不提供清理、detach、truncate 或 delete function。

### 5.2 local/test 日链与告警

每行 canonical object 固定含 `operation_logs` 全部 20 个列（包括 `request_event_id/emission_order`），另加 `schema='operation-log-row-v1'`；UUID 小写带连字符，时间转 UTC 六位微秒，NULL 为 JSON null，IP 使用带 `/24` 或 `/56` 的 canonical text，JSON 使用 UTF-8 RFC 8785 JCS。摘要中的 JSON number 只允许 I-JSON safe integer。

```text
row_digest = SHA256(UTF8("operation-log-row-v1\n") || JCS(row))
chain_0    = previous_day_anchor_raw_32_bytes
chain_i    = SHA256(chain_(i-1) || row_digest_i)
day_anchor = SHA256(
  UTF8("operation-log-day-v1\n") ||
  UTF8(utc_date_YYYY-MM-DD) ||
  uint64_big_endian(row_count) ||
  chain_n
)
```

- 每日范围是 UTC `[00:00:00Z,next day 00:00:00Z)`，跨命中的具名 range children 合并后按 `(created_at ASC,request_event_id ASC,emission_order ASC,id ASC)` 排序；sealer 同时断言 default row count恰为 0，非零即失败且不得生成 anchor。hash前还必须按 parent全历史分组验证：每个 `request_event_id` 只对应一个 `created_at`，`emission_order`不重复且 action sequence恰命中第 2.2 节 profile；任何跨 partition/timestamp复用以 `OPLOG_CHAIN_MANIFEST_MISMATCH` 拒绝。restore verifier执行相同全历史扫描，任一复用以 `OPLOG_BACKUP_CHAIN_MISMATCH` 拒绝；不得新增辅助唯一表。
- epoch 首日 `previous_day_anchor_raw_32_bytes=genesis_sha256_raw`，即 `decode(operation_log_chain_state.genesis_sha256,'hex')` 的恰 32 bytes，绝不是 32 个 zero bytes或 64-byte hex text；以后使用前一日 anchor raw bytes。零行日也生成 anchor，禁止跳日或跨月断链。
- append wrapper 按本行数据库 UTC 日取得 shared advisory transaction lock并持有到业务事务结束；sealer 候选在 `00:15 UTC` 后只处理最早未封且不晚于昨日的日期，通过同一日 exclusive advisory transaction lock等待全部 append结束，再计算稳定 bytes并 CAS 更新 singleton state。已封日期永不重开。
- daily manifest 固定八键：`schema_version='operation-log-day-manifest-v1'/chain_id/utc_date/row_count/first_log/last_log/previous_day_anchor_sha256/day_anchor_sha256`；`first_log/last_log` 为 NULL 或精确四键 `created_at/request_event_id/emission_order/id`。`sealed_manifest_sha256=SHA256(JCS(manifest))`。
- local/test Gate 把 manifest bytes/hash作为测试 evidence；本文不选择 production MinIO/WORM、调度器、artifact object key 或签名 DAG。

local/test 数据库/外部错误矩阵封闭如下；表内 database safe code在数据库可达时一律是 `SQLSTATE 55000` 的唯一 message，禁止拼接原异常：

| condition | database/external `safe_code` |
|---|---|
| 连接不可达、未分类 SQL/constraint/function 异常、append内部故障 | `OPLOG_APPEND_UNAVAILABLE` |
| completed前普通 append、maintenance/restore disabled | `OPLOG_APPEND_DISABLED` |
| state缺失/多行/半初始化、genesis或 state invariant漂移 | `OPLOG_CHAIN_GENESIS_MISMATCH` |
| append历史扫描发现 request UUID复用 | `OPLOG_EVENT_ID_REUSED` |
| 具名月分区 preflight/topology失败 | `OPLOG_PARTITION_UNAVAILABLE` |
| default reject trigger命中 | `OPLOG_DEFAULT_PARTITION_INSERT_REJECTED` |
| future partition验证/创建失败 | `OPLOG_PARTITION_MAINTENANCE_FAILED` |
| direct mutation、sealed/late row、非空 downgrade | `OPLOG_IMMUTABLE` |
| sealer执行失败 | `OPLOG_CHAIN_SEAL_FAILED` |
| sealer manifest/hash/count/event-group不匹配 | `OPLOG_CHAIN_MANIFEST_MISMATCH` |
| backup/restore manifest/hash/count/event-group不匹配 | `OPLOG_BACKUP_CHAIN_MISMATCH` |
| completed bootstrap收到不同 input hash | `BOOTSTRAP_ALREADY_COMPLETED` |

每个数据库故障都先回滚对应 PostgreSQL transaction，再尽力发送同名外部结构化 telemetry；severity固定 `CRITICAL`，字段只允许 `safe_code/trace_id/occurred_at/chain_id/utc_date/log_created_at/log_id`。AUTH API无论命中表内哪项都只返回 HTTP 500既有脱敏 envelope `error.code=INTERNAL_ERROR` 与同一 `trace_id`；不得返回 SQLSTATE、database safe code、relation/constraint/function名或异常正文。bootstrap CLI及 scheduler/sealer/restore runner也只显示 safe code与 trace，不显示原始数据库错误；未知异常、未知 SQLSTATE或数据库根本未返回错误时一律外映射为 `OPLOG_APPEND_UNAVAILABLE`。telemetry失败不改变回滚，也不递归写 operation log或新增 action；production reliable alert carrier继续 `UNRESOLVED / NOT AUTHORIZED`。

`finaudit_oplog_partition_scheduler`、`finaudit_oplog_chain_sealer` 及其两个 DB functions 只是未来 Gate C disposable local/test 的 catalog/runtime-call candidate；本文不创建账号、不选择 cron/Celery/systemd/Kubernetes/Worker daemon、不启动循环，也不授权 deployment wiring。候选 `00:05/00:15 UTC` 只是未来测试调用时刻，当前均 `NOT RUN / NOT AUTHORIZED`。production scheduler、sealer、reliable alert carrier与值班响应继续 `NOT AUTHORIZED`。

### 5.3 retention、backup/restore 与 downgrade

AUTH local/test retention candidate 固定为 `INDEFINITE_NO_DELETE`：`TBD-007` 获生产批准前，日志、partition、chain state、manifest evidence 与 backup manifest 一律无限保留；任何自动 DROP/DETACH/TRUNCATE/DELETE、磁盘压力清理或“备份成功后删除”都不授权。production 法定期限、legal hold、归档介质和物理清理继续为 `UNRESOLVED / NOT AUTHORIZED`。

local/test backup candidate 只用于 Gate C disposable PostgreSQL 16：

- 先封账至昨日；对同一一致性 snapshot 生成 custom-format PostgreSQL dump，固定 `--no-owner --no-acl`，计算 dump SHA-256、日志 row count、当前未封 tail hash及已封水位。
- backup manifest 固定十一键：`schema_version='operation-log-auth-backup-manifest-v1'/backup_id/created_at/postgresql_server_version_num/alembic_revision/dump_sha256/operation_log_row_count/chain_id/sealed_through_utc_date/sealed_day_anchor_sha256/unsealed_tail_sha256`。
- manifest 只保存摘要，不复制 operation log 行、IP、UA、reason 或 summary。

local/test restore candidate 只允许恢复到空的 disposable PostgreSQL 16，ingress、Backend、Worker、partition scheduler和sealer保持停止，且不恢复 dump ACL/owner。任何 producer role 获权前，受控 restore session先把 restored state 的 `append_enabled` 原子置 false；随后逐项验证 manifest、唯一 Alembic head、row count、全部已封日 anchor、当前 tail、partition topology和 append-only ACL。该 drill 完成后目标保持 `append_enabled=false` 且不得承接 AUTH traffic；因此它不猜 production continuation/fork identity。production PITR、WAL、跨环境 re-enable、chain fork及 DEP-005 approved artifact binding继续 `NOT AUTHORIZED`。

downgrade 候选固定：同一事务设置 `lock_timeout='5s'`，取得 operation-log migration advisory lock，再对 parent（覆盖 descendants）和 chain state 取得 `ACCESS EXCLUSIVE`；验证 topology后，只要任一 partition有行或 state row已存在，就在任何 DDL前以 `SQLSTATE 55000,message=OPLOG_IMMUTABLE` 原子拒绝。只有全部 partition空且 state从未初始化时，才按逆依赖顺序以 `RESTRICT`删除本 revision自有 trigger/function/index/partition/tables；禁止 `CASCADE`，不得删除角色、上游表、外部 evidence或修改 `public` Schema ACL。空库重升必须使用新 chain ID。

## 6. bootstrap、同事务与 fault atomicity 候选

### 6.1 `system_bootstrap` 首事务 identity

新装 local/test固定顺序只有一条外部调用链：

1. bootstrap CLI从 TTY/stdin/受限 FD/Secret Manager取得 secret，在内存按 companion profile生成 encoded Argon2id hash；生成 UUIDv4 `request_event_id/trace_id`及明确 business IDs，按第 5.1.3 节十二键 object计算 input hash。password或 hash不得进入 argv、`.env`、仓库、日志、summary、telemetry或 input hash。
2. direct `finaudit_bootstrap` session开启一个 transaction并且只调用一次 `bootstrap_auth_system_admin_v1(...)`；它不得调用 initialize、lower append或 complete。外部 wrapper取得 advisory lock，调用 internal initialize，并以 `db_now=pg_catalog.transaction_timestamp()`在同一 transaction创建首 organization、首 admin user及长期 `system_admin` assignment；密码 hash只通过 `p_admin_password_hash`静态 parameter binding写 `users.password_hash`，wrapper从不 SELECT/拼接/回显该列。
3. 外部 wrapper调用 internal `append_system_bootstrap_log_v1(...)`，写唯一首行：`action_code='system_bootstrap'`、`emission_order=10`、organization/resource_id=新 organization ID、actor_id=NULL、roles=`{}`、resource=`organization`、result=`success`。summary根恰为六键 `schema_version/bootstrap_profile/bootstrap_input_sha256/admin_user_id/user_role_id/force_change_on_login`，其中 `schema_version='auth-operation-log-summary-v1'`、`bootstrap_profile='auth-oplog-bootstrap-v1'`、末项为 true。
4. lower append在返回前 internal调用 `complete_operation_log_bootstrap_v1(request_event_id)`并完成第 5.1.3 节重验；外部 wrapper最后按第 5.1.1 节顺序恰返回一行，`system_admin_role_id='00000000-0000-0000-0000-000000000101'`、`force_change_on_login=true`，其 `log_identities`为精确复合 identity array。任一步失败，initialize state、organization、user、assignment、operation log与 completion全部回滚。

相同 bootstrap input hash且全部持久化 facts精确匹配的成功重跑返回既有 identity与 `created=false`，不读取既有 password hash且不追加第二条 `system_bootstrap`；不同输入返回 `BOOTSTRAP_ALREADY_COMPLETED`；半初始化、首行不匹配或 state/hash漂移 fail closed且不自动修复。不存在可提交的“initialize only”阶段。

### 6.2 AUTH 状态与审计原子性

下列 PostgreSQL 状态与第 2 节行必须在同一 transaction commit/rollback：

- 登录成功：password rehash（如需）、失败计数清除、`token_sessions`创建与 `auth.login.success`；过期锁在本事务恢复 active时，该成功行 summary固定 `lock_transition=expired_to_active`，不新增 unlock action。
- 已知用户错误密码：恰一次真实 Argon2 verify后写 `auth.login.failure`。active或 expired-locked用户按 companion冻结规则递增，后者先转 active再从 1计数，summary为 `counter_outcome=incremented`且 expired分支 `lock_transition=expired_to_active`；尚未过期 locked或 disabled用户保持 counter/status不变，summary为 `counter_outcome=unchanged/lock_transition=none`。达到第 5次时同一 batch另含 status/locked_until与 `auth.account.lock`。
- force-change/disabled/尚未过期 locked 的已知用户在密码正确时，PostgreSQL状态重验与 `auth.login.denied`同事务；不得创建普通 session。失败密码不能泄漏该状态。
- refresh：parent rotation/new child 与 `auth.token.refresh`；首次 replay family revoke 与 `auth.token.revoke`。
- logout：首次 revoke 与 `auth.logout + auth.token.revoke`；幂等路径只写 `auth.logout`。
- AUTH-010：password hash、password_changed_at/token_invalid_before、force-change/失败计数清除、全部 family revoke、`user.password.change + auth.token.revoke`。
- 已识别主体 authorization denied：业务效果为零，`security.authorization.denied`在该请求事务提交后才返回既定拒绝；AUTH-003的 `logout_target_denied/AUTH_TOKEN_REVOKED`使用第 2.2 节唯一特例。

调用方可在内存预生成 Token，但只有 PostgreSQL commit成功后才能放入响应；审计、constraint、具名月分区 preflight、default guard或任意未知数据库失败时丢弃 Token并按第 5.2 节发送外部 safe telemetry、返回 HTTP 500 `INTERNAL_ERROR + trace_id`，不得提交 session、计数、锁定、密码或 revoke，也不得先提交后后台补审计。纯拒绝的审计失败仍保持零业务效果并返回相同 500，不能降级为正常 403 后吞掉审计错误。

API AUTH-010 的 Redis one-time CAS 与 PostgreSQL 不能形成分布式事务；遵循 companion 的安全顺序：CAS 后 PostgreSQL/审计失败时 Token 保持 consumed，PostgreSQL 整体回滚，用户重新登录。本文不宣称两者原子。

Gate C fault injection 至少固定在：具名月分区 preflight前后、append 前、append 后/业务 commit 前、第二条多行审计前、强制 default routing、chain-state读取失败、constraint violation和 bootstrap completion 前。每点都必须证明 PostgreSQL 业务表与 operation log 要么全部提交，要么全部不提交，default始终零行，且响应/异常/日志无 secret sentinel。

## 7. prospective delta 与非生产边界

| 项目 | 精确 candidate value | 边界 |
|---|---:|---|
| `api_path_delta` | `0` | 复用 AUTH-001/002/003/004/007/010 |
| `operation_log_action_delta` | `10` | 只含第 2.2 节 10 个 AUTH/bootstrap action |
| `baseline_core_table_delta` | `+1` | `operation_logs` 已在 57 表基线；只新增 `operation_log_chain_state`，批准同步后口径候选为 58 |
| `created_parent_table_count` | `2` | 本 migration 创建一个 baseline parent + 一个新增 singleton parent |
| `alembic_migration_delta` | `1` | 只拥有 operation-log slice revision |
| `owned_alembic_revision_count` | `1` | 不接管 AUTH companion migration |
| `candidate_migration_file` | `20260811_009_create_operation_log_auth_slice.py` | 当前未生成、未授权 |
| `candidate_revision` | `20260811_009` | 当前未生成、未授权 |
| `candidate_down_revision` | `20260807_008` | 只在 current head 未漂移时有效；漂移必须提升本 CR revision，禁止自动 rebase |
| `ORM_model_delta` | `2` | 候选 `OperationLog/OperationLogChainState`；当前不创建 |
| `registry_instance_delta` | `1` | `operation-log-auth-action-registry-v1`；当前 `NOT GENERATED` |

本候选只批准 development/test AUTH slice 的方向，不批准完整 P0 action registry、Worker/System startup actions、OPS-004 cursor、production scheduler、MinIO/WORM artifact DAG、PITR/WAL continuation、production retention/cleanup、真实账号、部署、canary、UAT 或 AC。禁止用本地 manifest、Mock、普通日志或无分区/JSON-only弱表替代上述边界。

`candidate_revision=20260811_009` 与 `candidate_down_revision=20260807_008` 是本 revision 的唯一 migration identity。执行 Gate B 前若 live accepted head不再是 `20260807_008`，必须创建并重新审批一个新 successor revision/filename/down_revision；禁止修改 `009` 的 down revision、自动 rebase、merge-head猜测或复用已审 bytes。

## 8. 仍未决项与共同治理

本文件已给出且只选择 `OPLOGAUTH-D-001～009`；`OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` 只是外部 dependency binding，不进入本文 source decision selection。`C-010` 当前为 `DEFINED / NOT APPROVED`，不是 `UNRESOLVED`：其 `C010-GOVERNANCE` 引用当前 `CR-014-R2` governance typed direct-message approval；其后置 `C010-PUBLISH` 引用 source A1/A2 artifacts、bundle、joint authorization与十一文件 cooperative transition。本文不得代批或复制其治理记录。

仍无法由当前证据安全裁决的项目只有：

1. password blocklist final ArtifactRef/hash及其 create-only artifact approval 属于 companion CR-013-R2；JWT/session-family与 Redis local/test exact contract也只由该 companion 拥有。本文不复制或代批。
2. production retention 的法律/业务期限、legal hold 与物理清理；状态 `UNRESOLVED / NOT AUTHORIZED`，local/test 固定使用无限保留。
3. production backup/PITR/WAL、restore chain continuation/fork、MinIO/WORM carrier及 DEP-005 approved artifact hashes；状态 `NOT AUTHORIZED`，不阻断本文 local/test review，但阻断 production。

两份 successor 仍必须消费同一个 `auth-oplog-source-sync-v1` 候选：source set 恰为 `CR-006-R3,CR-013-R2`；path set 恰为九份 Request、`docs/baseline-manifest.md`、`backend/app/approval_pre_meta.py`。只允许一个共同 pre-state、一个 post manifest和一次十一文件原子替换；不得生成两个同父分支、中间 manifest或分别 re-pin。

既有 CR-014-R1/DEP/CR-006/008 的 approval/transition artifacts不得隐式继承或改名复用。当前 `CR-014-R2` 仍须按其自身 Gate生成新的 exact bytes；`C010-GOVERNANCE` 未由其 governance direct approval满足前不得生成本文 decision preimage/snapshot。本文 source A1之后仍须等待 CR-013 A1/A2与 `C010-PUBLISH` 才可形成 Request sync authorization；migration、ORM、registry instance或 runtime始终晚于该后置 Gate。

## 9. Gate A/B/C 与验收

### Gate A：合同可签

当前：`BLOCKED / NOT RUN`。

生成本文 source snapshot/A1 的前置恰为：`OPLOGAUTH-D-001～009` 已冻结；当前 CR-014-R2 governance snapshot与九角色 direct approval有效并满足 `C010-GOVERNANCE`；source manifest仍为本文 hash；两份 revision无环；九角色审核相同 bytes。CR-013 source A1/A2、bundle、joint authorization与 `C010-PUBLISH` 全部是本文 A1之后的 Gate，不得反向阻塞 snapshot。完成上述前置前不生成本文 snapshot。

### Gate B：Request 同步与静态制品

当前：`NOT AUTHORIZED / NOT RUN`。

未来批准后才可按唯一十一文件 transition 同步 Request/manifest/pre-meta并生成 registry Schema/instance、migration object allowlist及静态 vectors。Gate B 不执行 migration、不创建账号、不启动 Auth runtime。

### Gate C：PostgreSQL 16 与 AUTH local/test

当前：`NOT AUTHORIZED / NOT RUN`。

未来前置满足后，在 disposable PostgreSQL 16 至少验证：

- 当前 head→009→008→009 往返；空库 downgrade成功，任一日志或 state row存在时 SQLSTATE 55000 且首个 DDL 前失败。
- parent/当前+后两月/default、复合 PK/FK/index/trigger/ACL catalog exact；月分区缺失 fail-closed、default无条件拒写和 sealed-day拒写。
- 10 action、四 resource、两 producer、八 actor mode和三 result逐项正负矩阵；unknown username/Token不伪造数据库行。
- immediate-peer、转发头忽略、IPv4 `/24`、IPv6 `/56`、UA 256-byte/控制字符边界。
- 唯一外部 `bootstrap_auth_system_admin_v1`、internal initialize/lower append/complete、同 input no-op、different input拒绝、任一故障含 chain state全回滚。
- 登录/失败/锁定/force-change/refresh/replay/logout/password-change/permission denied 的 request_event UUID、batch cardinality、10/20 order、partition-compatible UNIQUE 与 fault atomicity；另全历史扫描证明 request UUID不跨 timestamp/partition复用，并注入复用验证 append/sealer/restore固定拒绝。
- genesis固定 JCS/domain separator、首日 genesis raw anchor、每日/零行/跨月 hash、default零行断言、稳定重算、manifest mismatch Critical；local/test backup/empty-target restore read-only drill。
- runtime UPDATE/DELETE/TRUNCATE/direct INSERT/child绕过/unknown wrapper全部被数据库拒绝。
- secret sentinel 不出现在 DB、telemetry、error、repr、trace、test report或 backup manifest。

Gate C 通过也只证明 storage/action/atomicity local/test slice；staging、production、真实流量、production restore/retention、OPS-004、浏览器完整 E2E、UAT和 AC 均继续 `NOT RUN`。

## 10. 当前动态状态

| 项目 | 状态 |
|---|---|
| source baseline binding | `VERIFIED / CURRENT` |
| old CR-006/008 candidates | `REVIEW INPUT ONLY / NOT INHERITED` |
| exact AUTH/bootstrap candidate actions | `DEFINED: 10 / NOT APPROVED` |
| result/resource/producer/actor dictionary | `DEFINED / NOT APPROVED` |
| unknown identity/security telemetry | `DEFINED / NOT APPROVED` |
| PG16 PK/FK/partition/default/late-row candidate | `DEFINED / NOT APPROVED` |
| append-only owner/ACL/function signatures/membership | `DEFINED / NOT APPROVED` |
| local/test chain/retention/backup/restore/downgrade | `DEFINED / NOT APPROVED` |
| production retention/restore continuation | `UNRESOLVED OR NOT AUTHORIZED` |
| bootstrap identity/fault atomicity | `DEFINED / NOT APPROVED` |
| prospective delta | `0 API / +1 baseline core / 2 created parents / 1 migration / 10 actions` |
| GAP-046 / GAP-053 | `OPEN` |
| `OPLOGAUTH-C-010` current CR-014-R2 common transition dependency | `DEFINED / NOT APPROVED; ARTIFACTS NOT GENERATED` |
| decision preimage/snapshot | `NOT GENERATED` |
| Gate A | `BLOCKED / NOT RUN` |
| Gate B | `NOT AUTHORIZED / NOT RUN` |
| Gate C | `NOT AUTHORIZED / NOT RUN` |
| Request/manifest/runtime/production/AC | `NOT CHANGED / NOT AUTHORIZED / NOT RUN` |
