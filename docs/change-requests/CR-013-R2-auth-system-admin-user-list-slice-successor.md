# CR-013-R2：system_admin 登录与用户只读列表 current-baseline successor

> 文档状态：`PROPOSED / NOT APPROVED`
> 运行时状态：`NOT AUTHORIZED / NOT RUN`
> decision snapshot：`NOT GENERATED`
> source baseline manifest SHA-256：`a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3`
> supersedes review candidate：`CR-013-R1`，不继承其批准状态、旧 baseline binding 或未生成制品

## 1. 目标、事实与边界

### 1.1 最短真实业务链

本候选只面向 development/test 的首条真实身份链：

```text
offline bootstrap
  -> API AUTH-001 首次登录返回 AUTH_PASSWORD_CHANGE_REQUIRED
  -> API AUTH-010 完成强制换密
  -> API AUTH-001 重新登录
  -> API AUTH-004 /auth/me
  -> API AUTH-007 GET /api/v1/users
  -> UI-014 /users 只读列表
```

该链解决“真实 system_admin 可登录并读取同组织用户列表”的最小用户价值，但不等于 UI-014 完整用户管理、AC-001、production readiness 或 P0 完成。

### 1.2 当前阻断事实

- `GAP-038` 仍为 OPEN：密码、锁定、JWT、Refresh Token、浏览器保管与重放处置未进入 active baseline。
- `GAP-039` 仍为 OPEN：P0 permission 字典、五角色映射和资源范围未冻结。
- API AUTH-007 只给出 `items/pagination` 概述，UI-014 又要求 `email/locked_until`；分页默认值、稳定排序与 `role_codes` 投影语义均未唯一冻结。
- `operation_logs` 仍受 `GAP-046/GAP-053` 阻断；认证状态副作用不得在没有同事务审计事实时开放。
- Backend 业务 Router、Auth Service/Repository、Frontend 真实会话和 UI-014 API 绑定当前均未授权。

### 1.3 关系与非继承

- `CR-013-R1`、`CR-014`、`CR-006-R1/R2`、`CR-008-R1/R2` 仅是未批准 review candidates，且旧 lineage 绑定过期 baseline；本修订不得把其 snapshot、Schema、签名或自然语言结论视为 active approval。
- 已批准的 `CR-003-R3` 只提供 `user_roles/break_glass_requests` storage-schema 事实，不授权 Auth、ACL、operation-log、Repository、Service、Router 或真实账号。
- 本文件不修改九份 Request，不修改 active manifest，不生成密码 blocklist、keyring、签名、账号、Token、迁移或运行时代码。

## 2. 候选决策全集

以下八项是 top-level profile decisions。完整 source approval universe 必须按顺序绑定“本节 `AUTHSLICE-D-001～D-008` -> 第 9 节 `AUTHSLICE-C-001～C-008` -> 第 3.3 节嵌套 `AUTHSLICE-JS-001～JS-009`”，不能只选择 top-level、不能用“批准推荐值”替代精确 code，也不能用 `AUTHSLICE-C-006` 聚合值替代九项 JS 逐项选择：

1. `AUTHSLICE-D-001=PASSWORD_AND_LOGIN_PROFILE_V1`
2. `AUTHSLICE-D-002=JWT_AND_REFRESH_PROFILE_V1`
3. `AUTHSLICE-D-003=LOCAL_TEST_SIGNER_PROFILE_V1`
4. `AUTHSLICE-D-004=USER_LIST_PERMISSION_SLICE_V1`
5. `AUTHSLICE-D-005=AUTH007_READ_MODEL_V1`
6. `AUTHSLICE-D-006=BOOTSTRAP_AND_BROWSER_CUSTODY_V1`
7. `AUTHSLICE-D-007=OPLOG_COMPANION_AND_GATE_PROFILE_V1`
8. `AUTHSLICE-D-008=PASSWORD_BLOCKLIST_ARTIFACT_BINDING_V1`

本文第 3～8 节仅为 `candidate_values`。在第 10 节状态变为有效批准前，它们不是 `approved_values`。

候选 delta：

| 项目 | 候选值 | 边界 |
|---|---:|---|
| `api_path_delta` | `0` | 复用 API AUTH-001/002/003/004/007/010 |
| `ui_page_delta` | `0` | 复用 UI-001、UI-014 |
| `core_table_delta` | `0` | 不新增 core table |
| `alembic_migration_delta` | `1` | 仅允许未来修改既有 `users/token_sessions`；当前未授权 |
| `permission_code_delta` | `1` | 仅候选 `users:manage`，不代表全 P0 字典 |
| `declared_python_dependency_delta` | `3` | 只冻结 `argon2-cffi==25.1.0`、`argon2-cffi-bindings==25.1.0`、`cryptography==49.0.0`；本 CR 不安装 |
| `source_semantic_delta` | `NONZERO` | 必须逐项投影 AUTH-001/002/003/004/007/010 及九份 Request；不得只投影 AUTH-010，也不得声明 zero semantic delta |

`source_semantic_delta=NONZERO` 至少包含：AUTH-001 canonical login、锁定/到期恢复、force-change、限流与 `Retry-After`；AUTH-002 strict Refresh family/rotation/replay；AUTH-003 self-terminal 幂等 logout 与 actor 已建立后的安全拒绝审计；AUTH-004 PostgreSQL session/user/organization/epoch/角色绑定；AUTH-007 `users:manage`、同组织只读 DTO/分页；AUTH-010 blocklist、一次性 Redis CAS、依赖失败与 Redis 已消费而 PostgreSQL 回滚。上述任一投影缺失都不是本文完整 source delta。

## 3. Authentication candidate profile

### 3.1 密码与登录

```yaml
password:
  normalization: NFC
  unicode_data_version: 13.0.0
  codepoints_min: 15
  codepoints_max: 128
  utf8_bytes_max: 512
  hash: Argon2id
  version: 19
  memory_kib: 19456
  iterations: 2
  parallelism: 1
  salt_bytes: 16
  digest_bytes: 32
  dummy_verify_for_unknown_user: required
  rehash_before_token_issue: required
login:
  consecutive_failure_threshold: 5
  temporary_lock_seconds: 900
  authoritative_time: PostgreSQL
  disclose_unknown_user: false
username_login:
  trim: ASCII U+0020 at both ends only
  accepted_pattern: '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'
  canonicalization: ASCII lowercase
  noncanonical_or_collision_at_migration: fail_closed
```

- 密码、hash、Token、blocklist 命中内容和用户存在性不得进入错误、日志、operation log、trace 或指标 label。
- 第五次连续失败提交锁定事实；错误响应仍不得泄露“该用户名刚被锁定”。
- 用户状态、失败计数、rehash、session 创建和相关审计必须遵循确定的事务/锁顺序；实现不得自行简化为内存计数。
- 密码 blocklist 采用 staged artifact approval：本文只冻结 source 与 generator 的候选输入，不预填尚未生成的 generator/final artifact identity，也不把旧 CR-013-R1 的任何批准状态带入本 revision。

#### 3.1.1 password blocklist staged candidate

```yaml
blocklist_candidate:
  artifact_version: auth-password-blocklist-v1
  source_manifest_schema: auth-password-blocklist-source-v1
  source_name: SecLists
  release_tag: '2026.1'
  commit_oid: 190c6f7bd58c847ceadfe57d9853592737f059e8
  source_path: Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
  source_git_blob_sha1: 38eb37702244f55fda75cab281eb2145cd7685b6
  source_raw_sha256: c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0
  source_byte_length: 835538
  source_nonempty_line_count: 99839
  license_spdx: MIT
  license_path: LICENSE
  license_raw_sha256: 3dbdc93d5f8829de0941744841730a09c106d0732e5ae0e98ca1d77be7ded66c
  generator_profile: auth-password-blocklist-generator-v1
  unicode_data_version: '13.0.0'
  final_artifact_ref: UNRESOLVED_NOT_GENERATED
  final_artifact_sha256: UNRESOLVED_NOT_GENERATED
```

`source_uri` 候选精确为：

```text
https://raw.githubusercontent.com/danielmiessler/SecLists/190c6f7bd58c847ceadfe57d9853592737f059e8/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
```

`auth-password-blocklist-source-v1` 根必须精确十三键：
`schema/source_name/release_tag/commit_oid/source_path/source_uri/source_git_blob_sha1/source_raw_sha256/source_byte_length/source_nonempty_line_count/license_spdx/license_path/license_raw_sha256`。source 必须为 strict UTF-8、无 BOM/NUL/CR、LF-only、末尾恰一个 LF；恰含 `99839` 个非空行与一个空内容行。空行忽略，其余行不 trim。metadata、raw bytes 或 license 任一不符即拒绝；不得使用 `master/latest`、重定向后的不同 bytes 或自选弱口令集合替代。

generator 候选算法精确为：

1. 先验证上述十三键常量、source raw identity 与 license raw identity。
2. strict UTF-8 解码并按 LF 切分，只忽略唯一空内容行。
3. 每个非空原始行依次执行 Unicode 13 NFC、Default Case Folding、UTF-8 编码、SHA-256；不得 trim。
4. 再加入四个封闭产品名输入 `FinAuditAgent/FinAudit Agent/FinAudit-Agent/FinAudit_Agent` 的同算法 digest；它们由 ASCII token `FinAudit`、按 `""/" "/"-"/"_"` 顺序的 separator 与 `Agent` 组成。
5. 对 64 位小写 hex digest 做 set 去重、ASCII/code-point 升序排序，每行加 LF，以无 BOM UTF-8 输出，末尾恰一个 LF。
6. primary generator 与 independent verifier 必须分别使用独立、自包含、stdlib-only entrypoint：`scripts/build-auth-password-blocklist.py` 与 `scripts/verify-auth-password-blocklist-independent.py`。两者都必须在开始转换前验证 `platform.python_implementation()=='CPython'`、Python major/minor 为 `3.10` 且 `unicodedata.unidata_version=='13.0.0'`；任一不符 fail closed。两个脚本禁止互相 import、复制运行时状态、import 任何项目转换 helper，或共享除 Python 标准库以外的转换代码/依赖；各自独立实现 source identity 验证、Unicode 13 NFC/default case folding、digest、去重、排序及 final bytes 复核。
7. 两个 implementation 各形成一个 create-only `auth-password-blocklist-implementation-source-manifest-v1`。manifest raw bytes 是根对象 RFC 8785 JCS UTF-8 bytes、无 BOM/额外空白，根键集合逐集合等于 `schema/implementation_kind/entrypoint/runtime/toolchain/dependencies/files`：`implementation_kind` 分别为 `primary_generator/independent_verifier`；`entrypoint` 分别为上述 exact POSIX path；`runtime='CPython-3.10'`、`toolchain='stdlib-only'`、`dependencies=[]`；`files` 恰一项且按 POSIX path 排序，该项键集合恰为 `path/raw_bytes/raw_sha256`，`path` 等于 entrypoint，`raw_bytes` 为正 JSON safe integer byte length，`raw_sha256` 为脚本 exact raw bytes 的 64 位小写 hex。禁止把 `.pyc`、工作树元数据、绝对路径、mtime、环境变量或生成产物纳入 manifest。
8. 每个 manifest 的 identity 是其 JCS raw bytes SHA-256；两个 hash 必须不同。create-only ref 分别为 `artifact://auth/password-blocklist/implementation-source-manifest-v1/<implementation_kind>/sha256/<manifest_raw_sha256>`。相同 ref 已存在但 bytes/hash 不同即失败，禁止覆盖。两实现都独立验证固定 source raw identity；两份 execution receipt 之间只要求 `source_manifest_jcs_sha256/final_nonempty_line_count/final_raw_sha256` 三项逐值一致，不要求、也禁止把两个 implementation manifest 伪装成相同 identity。

最终 artifact approval 必须 create-only，并同时绑定 source manifest JCS hash、source raw hash、两个互异 implementation source-manifest raw hash/ref、最终非空行数与 final raw hash；只签 final hash 不足以批准。plaintext source 只可在隔离 artifact 构建目录暂存并在复核后清理，不得进入仓库、日志、镜像或 runtime。runtime 还必须验证 artifact 格式、排序、去重和 `password/123456/qwerty/football/qwertyuiop12345/123456789012345` 六个公共向量的规范 digest 命中。

Gate A1 冻结的 artifact approval typed payload contract 固定为 `auth-password-blocklist-artifact-approval-payload-v1`，根精确十键：

```text
schema_version,artifact_version,source_manifest_jcs_sha256,source_raw_sha256,
generator_profile,generator_source_sha256,independent_verifier_source_sha256,final_nonempty_line_count,
final_raw_sha256,artifact_ref
```

`schema_version/artifact_version/generator_profile` 分别固定为 `auth-password-blocklist-artifact-approval-payload-v1/auth-password-blocklist-v1/auth-password-blocklist-generator-v1`；五个 SHA-256 字段都是 64 位小写 hex。`generator_source_sha256` 精确等于 primary-generator implementation manifest JCS raw SHA-256，`independent_verifier_source_sha256` 精确等于 independent-verifier implementation manifest JCS raw SHA-256，且二者必须不同；对应 create-only manifest ref 只能按上一段由各 hash 机械派生。`final_nonempty_line_count` 是正 JSON safe integer；`artifact_ref` 固定为 create-only URI `artifact://auth/password-blocklist/auth-password-blocklist-v1/sha256/<final_raw_sha256>`。payload raw bytes 必须是根对象 RFC 8785 JCS UTF-8 bytes，无 BOM 或额外空白。

Gate A2 的唯一审批权威必须是 CR-014-R2 typed direct-message contract 冻结 exact `role_decisions` 后，当前 task/thread 中平台认证为 BOSS/YHBX 直接 `user` 消息的恰一条 `CR013_R2_BLOCKLIST_A2` 消息。该消息必须绑定同一十键 payload raw SHA-256、create-only final artifact ref/hash、两个 implementation manifest identity，并含 exact `represented_roles=["backend_api","ops","security","test"]` 与同序 exact `role_decisions=[{"decision":"APPROVED","role":"backend_api"},{"decision":"APPROVED","role":"ops"},{"decision":"APPROVED","role":"security"},{"decision":"APPROVED","role":"test"}]`。缺键、缩写角色、任一非 APPROVED、拒绝、payload/ref/hash 漂移、消息过期或非平台认证直接用户消息均不构成 A2。由消息派生的四条 local canonical role records/receipts 只能是 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，不得单独或合并授权，也不得冒充签名、registry、pin 或 message ID。

本次不下载 source、不生成 artifact、不调用网络。Gate A1 只批准 source/generator/payload/role 合同，并允许 operator 提供与十三键 manifest 逐字匹配的 exact source bytes，在隔离环境离线生成候选 artifact；它不授权 Codex、脚本或 runtime 获取网络。`final_artifact_ref/final_artifact_sha256` 保持 `UNRESOLVED_NOT_GENERATED` 不阻止 A1 形成 snapshot/approval，但 Gate A2、joint Request sync、migration 与 AUTH runtime 必须继续 BLOCKED/NOT AUTHORIZED。

#### 3.1.2 exact login mutation、锁定与并发

login mutation 顺序固定如下：

1. 先执行第 3.1 节 username canonicalization 与匿名限流。没有 canonical identity 的输入只消耗可信 IP bucket，执行 dummy verify 后返回通用 `401 AUTH_INVALID_CREDENTIALS`，不得创建 identity Redis key。
2. 有 canonical identity 时，先只读定位 candidate user ID；未命中时执行与真实 Argon2id Profile 同参数、恰一次 dummy verify，返回同一通用错误。dummy path 不创建用户、session、password-change record 或 operation-log 假事实。
3. 已知 user 的普通尝试先开启 PostgreSQL 事务，执行 `SELECT public.users ... FOR UPDATE`，再捕获一次 `db_now=clock_timestamp()`；锁后重验 canonical username、organization、deleted/status、password hash、`failed_login_count/locked_until/force_change_on_login/token_invalid_before`。candidate ID 漂移、组织无效或软删除时 fail closed，且不得使用锁前密码结果。
4. 初始 snapshot 为 expired temporary lock（`status='locked' AND locked_until IS NOT NULL AND db_now>=locked_until`）时，普通尝试不得先 verify，必须直接进入第 6～8 项 transition 重入。其余已知且未软删除的 locked（人工无限锁或未过期临时锁）或 disabled user 必须对锁后 hash 执行恰一次真实 Argon2id verify。密码错误统一写脱敏 `auth.login.failure` audit，summary 固定含 `cause_code='AUTH_INVALID_CREDENTIALS'/counter_outcome='unchanged'`，返回 `401 AUTH_INVALID_CREDENTIALS`，且不得修改 counter、status、`locked_until`、password、session 或 Token；只有密码正确时才进入 status gate：`locked -> 423 AUTH_ACCOUNT_LOCKED`，`disabled -> 403 AUTH_USER_DISABLED`，并写 `auth.login.denied` audit。
5. 正确密码命中未过期临时锁时，响应唯一携带 delay-seconds 形式的 `Retry-After=max(1,ceil(extract(epoch from locked_until-db_now)))`；人工无限锁 `locked_until IS NULL` 不返回 `Retry-After`；disabled 不返回该 Header。第五次错误刚形成锁定时仍只返回通用 401 且不返回 `Retry-After`，不得泄露“本次刚锁定”。
6. `status='locked' AND locked_until IS NOT NULL AND db_now>=locked_until` 需要 `locked -> active`；`status='active'`、真实密码错误且锁后 `failed_login_count=4` 需要 `active -> locked`。这两类 status transition 必须服从 `20260807_008` 的长期角色 SoD 并使用两阶段重入：一旦普通尝试在已经持有 users row lock 后发现需要 transition，立即回滚整个事务，不写状态/audit、不复用其中的 `db_now` 或 Argon2 结果。
7. transition 重入事务必须先执行 `LOCK TABLE public.user_roles IN SHARE ROW EXCLUSIVE MODE`，再执行 `SELECT public.users ... FOR UPDATE`，然后重新捕获唯一 `db_now=clock_timestamp()`、重读全部 user/organization/role facts，并对当次锁后 hash 重新执行真实 Argon2id verify。绝对禁止先持有 users row lock 再补 `user_roles` table lock。若重验后不再需要 transition，则按重入 snapshot 的实际 status/password 分支处理；不得强行应用首次尝试的判断。
8. expired locked 重入仍满足 expiry 时，自动恢复不新增 `auth.account.unlock` action；它必须由本次唯一 login action 的 summary 携带 `lock_transition='expired_to_active'`。真实密码错误时最终状态固定为 `status='active'/failed_login_count=1/locked_until=NULL`，写 `auth.login.failure` 并返回 `401 AUTH_INVALID_CREDENTIALS`；正确且非 force-change 时最终为 `active/0/NULL`，创建普通 root session并写 `auth.login.success`；正确且 force-change 时最终为 `active/0/NULL`，不创建普通 session，按第 10 项写 `auth.login.denied` 并返回受限流程。三类 summary 都必须含 `lock_transition='expired_to_active'`，且不得另写不存在的 unlock action。active 第五次失败重入仍满足 counter=4 且密码错误时，同一事务写 `failed_login_count=5/status='locked'/locked_until=db_now+interval '900 seconds'` 与 failure/lock audit。
9. 不发生 status transition 的 active 密码错误使用锁后 `new_count=failed_login_count+1`，仅在 `new_count<5` 时保存 counter 并写 failure audit；密码正确时清零 counter/lock。需要 rehash 时先在内存产生 PHC 候选，数据库写入失败则整个事务回滚。普通登录的 rehash、root session insert 与对应 operation log 同事务，commit 前不得向调用方暴露 Access/Refresh。
10. active 且密码正确但 `force_change_on_login=true` 时，不得创建普通 session。持 user lock 后使用同一 `db_now` 在内存生成全新 jti 与 password-change JWT bytes，但不返回；随后执行第 3.9.1 节 Redis create-only，成功后才在 PostgreSQL 写 `auth.login.denied`、必要 rehash 与 counter 清零并 commit，commit 成功后才返回 `403 AUTH_PASSWORD_CHANGE_REQUIRED` 与该 Token。Redis create-only 失败则 PostgreSQL 全事务回滚并返回 `503 DEPENDENCY_UNAVAILABLE`；Redis 成功而 PostgreSQL/audit/commit 失败时，未向调用方暴露的 record 保持原 TTL 自灭，不删除、不 unconsume、不补发或重用同一 Token。
11. operation-log、SoD deferred trigger、constraint 或任一 PostgreSQL 写入/commit 失败时，counter、锁定、解锁、rehash、session 与 audit 效果全部回滚，丢弃未返回 Token，唯一响应为 `500 INTERNAL_ERROR + trace_id` 且不含 `Retry-After`；不得降级为原 401/403/423。未知用户仍只允许脱敏 security telemetry。

并发语义：非 transition 的同一 user 尝试由 `users FOR UPDATE` 串行化；所有可能改变 `users.status` 的登录尝试则由 `user_roles SHARE ROW EXCLUSIVE -> users FOR UPDATE` 的共同锁序串行化并满足 008 deferred SoD。并发第 4/5 次错误中只有重入后仍观察到 counter=4 的事务可提交第五次锁定；等待者不得产生第六次计数或延长 900 秒。并发 expired locked 尝试中只有按完整锁序重入后仍观察到 expiry 的事务可提交恢复；所有发现事务都必须丢弃旧 snapshot、旧 `db_now` 与旧 verify 结果。

匿名入口限流候选值：登录使用 Redis 60 秒 sliding window，可信 client IP 上限 30、canonical identity digest 上限 10；API AUTH-010 使用 300 秒窗口，IP 上限 20、已验签 `jti` digest 上限 5。identity/jti 只存 HMAC/SHA-256 digest；每个真实 HTTP attempt 使用服务端新 UUID。原子脚本必须对每个耗尽 bucket 返回“最早可再次接受请求”的非负剩余秒数；HTTP `Retry-After` 固定为 `max(1,ceil(max(exhausted_bucket_remaining_seconds)))` 的 canonical base-10 integer seconds。任一 bucket 耗尽统一返回 `429 RATE_LIMITED + trace_id` 与该 Header；不得因 username 是否命中而改变响应。Redis 原子脚本、限流 secret 或权威时间源不可用时 fail closed，返回 `503 DEPENDENCY_UNAVAILABLE + trace_id`，不返回 `Retry-After`，且不得回退进程内计数。development/test 默认不信任任何转发代理并忽略 forwarded headers；未来代理 allowlist 必须另行批准。

### 3.2 JWT 与 Refresh Token

```yaml
jwt:
  token_profile_version: auth-token-local-test-v1
  serialization: compact_jws
  algorithm: EdDSA
  curve: Ed25519
  allowed_algorithms: [EdDSA]
  issuer: finaudit-agent
  audience: finaudit-api
  access_ttl_seconds: 1800
  password_change_ttl_seconds: 300
  leeway_seconds: 30
  compact_ascii_bytes_max: 4096
  roles_or_permissions_in_token: forbidden
refresh:
  random_bytes: 32
  wire_encoding: rft_ + unpadded_base64url
  stored_value: sha256_only
  normal_absolute_ttl_seconds: 604800
  remember_absolute_ttl_seconds: 2592000
  minimum_remaining_for_access_seconds: 1830
  rotate_on_every_success: true
  replay_effect: revoke_entire_family
  rotation_extends_absolute_expiry: false
```

- API AUTH-010 的受限 Token 只能调用换密接口，不得创建普通 session。
- Refresh Token 只保存 SHA-256，明文只在必要响应边界短暂存在。
- 角色与权限每次请求从 PostgreSQL 权威事实计算；JWT 不携带可陈旧的角色或权限。

#### 3.2.1 Python 密码与 Ed25519 dependency identity

本 source 只批准以下三个 exact direct package/version identity，不代表已下载、已安装、可 import 或通过安全验收：

```text
argon2-cffi==25.1.0
argon2-cffi-bindings==25.1.0
cryptography==49.0.0
```

- Argon2id hash/verify/rehash 只能通过上述 `argon2-cffi` facade 与其单独发行的 exact `argon2-cffi-bindings` 低层实现；Ed25519 key generation/sign/verify 只能通过上述 `cryptography`。禁止手写 Argon2、Ed25519、ASN.1/key parser、constant-time compare 或用标准库/其他包替代密码学实现。
- 本次不访问网络、不解析安装器缓存、不安装或升级任何 package，也不声称当前环境满足依赖。进入 Gate B 静态制品和任何实现前，必须从离线提供的 exact distribution bytes 形成 create-only dependency evidence，逐项绑定 canonical package name、version、目标 CPython 3.10/platform tag、wheel filename、raw byte length、SHA-256、license identifier、license artifact ref/raw SHA-256，并冻结解析后的完整 transitive wheel closure；sdist、unpinned transitive dependency、floating index、源码现场构建或 hash 漂移一律 fail closed。
- 三个 direct package 与完整 transitive closure 必须进入同一 lock/evidence identity，并由 backend_api/ops/security/test 在 source-approved 边界内复核；未形成 wheel/hash/license evidence 时，migration 可保持未生成，Auth runtime、bootstrap password hash、JWT signer 与 Gate C 必须继续 `BLOCKED / NOT RUN`。

### 3.3 exact candidate decision set

以下九项共同构成 `AUTHSLICE-C-006=LOCAL_TEST_JWT_SESSION_FAMILY_V1`。它们只是本 revision 的候选值，不是 active approval：

| 子决策 | exact candidate value |
|---|---|
| `AUTHSLICE-JS-001` | `STRICT_COMPACT_JWS_EDDSA_V1` |
| `AUTHSLICE-JS-002` | `EXACT_ACCESS_AND_PASSWORD_CHANGE_CLAIMS_V1` |
| `AUTHSLICE-JS-003` | `SINGLE_PROCESS_EPHEMERAL_ED25519_V1` |
| `AUTHSLICE-JS-004` | `POSTGRESQL_USER_SESSION_ORG_EPOCH_BINDING_V1` |
| `AUTHSLICE-JS-005` | `REFRESH_FAMILY_STORAGE_V1` |
| `AUTHSLICE-JS-006` | `ROOT_LOCK_ROTATE_REPLAY_CAS_V1` |
| `AUTHSLICE-JS-007` | `LOGOUT_TERMINAL_MATRIX_V1` |
| `AUTHSLICE-JS-008` | `REDIS_PASSWORD_CHANGE_ONETIME_V1` |
| `AUTHSLICE-JS-009` | `EMPTY_SESSION_AUTH_MIGRATION_SHAPE_V1` |

任何实现库只能作为上述合同的 mechanism。库默认 parser、claim、clock、algorithm allowlist、key lifecycle、session 撤销或 Redis serializer 值均不得补充或覆盖本文。

### 3.4 strict compact JWT parser 与 claims

#### 3.4.1 compact/header canonical contract

1. 输入必须是 ASCII，长度 `1..4096` bytes，且恰含两个 `.`，形成三个非空 segment。
2. 每个 segment 只允许 `[A-Za-z0-9_-]`，禁止 `=` padding。逐段 canonical unpadded base64url 解码后重新编码必须与原 segment 逐字相等。
3. header 与 payload bytes 必须 strict UTF-8；signature 必须恰为 `64` raw bytes。
4. header 与 payload 各只解析一次，必须是 JSON object。parser 必须在构造映射前保留 member pairs，并拒绝任意重复 member name、NaN/Infinity、trailing data、非 JSON integer 的 NumericDate 与 JSON boolean 冒充 integer。
5. header 键集必须逐集合等于 `alg/kid/typ`，不得包含 `crit/cty/jku/jwk/x5u/x5c/b64` 或任何其他键。
6. `alg` 必须逐字等于 `EdDSA`；verifier allowed-algorithm 常量恰为单项 `['EdDSA']`，不得从 header、配置自由字符串或 payload 推导。
7. Access 的 `typ` 必须为 `at+jwt`；password-change 的 `typ` 必须为 `pwd+jwt`。header type 与 payload purpose 不匹配即拒绝。
8. `kid` 必须匹配 `^eph_[A-Za-z0-9_-]{43}$`，并逐字命中当前进程 verifier allowlist 的唯一 entry。unknown、missing 或 second entry 均拒绝。
9. `alg/kid` 选择、Ed25519 verify、claims、时间与业务绑定必须消费同一不可变解析结果。若第三方库内部重解析，库输出键集、JSON 类型和值必须与预检结果逐值相等，否则拒绝。
10. Access parser/verify 失败统一映射为已批准认证错误，不回显 parser/library 原因；password-change 失败映射为 `AUTH_PASSWORD_CHANGE_TOKEN_INVALID`。Token bytes、header/payload 原文与 signature 不进入日志、trace、operation log 或指标 label。

#### 3.4.2 exact payloads

Access payload 键集必须逐集合等于以下十键：

```text
iss,aud,sub,sid,jti,purpose,iat,nbf,exp,auth_epoch_us
```

password-change payload 键集必须逐集合等于以下九键：

```text
iss,aud,sub,jti,purpose,iat,nbf,exp,auth_epoch_us
```

字段合同：

| 字段 | exact type/value |
|---|---|
| `iss` | JSON string，逐字 `finaudit-agent` |
| `aud` | JSON string，逐字 `finaudit-api`；array 不接受 |
| `sub` | lowercase canonical hyphenated UUID string；等于 `users.id` |
| `sid` | 仅 Access；lowercase canonical hyphenated UUID string；等于本次 session tail 的 `token_sessions.id` |
| `jti` | 每次签发由 OS CSPRNG 产生的新 UUIDv4 lowercase canonical string；不得复用 |
| `purpose` | Access 为 `access`；password-change 为 `password:change` |
| `iat` | 非负 JSON safe integer NumericDate seconds |
| `nbf` | 非负 JSON safe integer，且逐值等于 `iat` |
| `exp` | 非负 JSON safe integer；Access=`iat+1800`，password-change=`iat+300` |
| `auth_epoch_us` | `0..9007199254740991` 的 JSON integer；定义见下文 |

除上述键外全部 extra claim 拒绝；尤其禁止 `roles/permissions/organization_id/email/display_name/scope/password_state`。组织身份从 PostgreSQL 用户事实派生，不在 JWT 重复存储。

签发事务在取得所需 PostgreSQL 锁后只调用一次 `clock_timestamp()` 得到 `db_now`，并要求 `users.token_invalid_before` finite 且不晚于 `db_now`：

```text
iat = nbf = floor(extract(epoch from db_now))
auth_epoch_us = floor(extract(epoch from users.token_invalid_before) * 1000000)
```

验证同样只使用当前 PostgreSQL 请求捕获的一次 `db_now`，令 `now_s=floor(extract(epoch from db_now))`。必须同时满足：

```text
iat = nbf
exp - iat = expected_ttl_seconds
iat <= now_s + 30
nbf <= now_s + 30
now_s < exp + 30
```

`exp<=iat`、TTL 不精确、future skew 超限或到达 `exp+30` 边界均拒绝。应用主机时间不得替代 PostgreSQL 时间。

### 3.5 development/test ephemeral signer

1. provider ID 固定为 `single-process-ephemeral-ed25519-v1`，只允许 `environment_class=development|test`。
2. 进程在开放监听前使用 OS CSPRNG 和已锁定 `cryptography==49.0.0` 的 Ed25519 API 生成一对 key；禁止手写 Ed25519 或切换库。dependency evidence/import/key generation 任一失败时启动失败。
3. raw public key 必须恰为 `32` bytes；`public_key_fingerprint_sha256` 为该 raw bytes 的 64 位小写 SHA-256 hex。
4. `kid='eph_'+base64url_no_pad(SHA-256(raw_public_key))`；SHA-256 输出编码后恰为 43 字符，因此 kid 恰为 47 字符并匹配第 3.4.1 节 pattern。
5. verifier allowlist 在启动时原子构造为恰一项 `{kid: raw_public_key}`；不存在历史 key、grace key、动态 reload、JWKS discovery 或远程 key fetch。
6. private key object 只驻当前进程内存，不得序列化、导出、写文件、写环境、写数据库、写 Redis、写日志、写 snapshot 或通过 API 返回。本文不声称 Python heap 可证明 zeroize/lock；这正是该 provider 不能用于 production 的原因之一。
7. key lifetime 精确为单一进程本次生命周期。重启生成新 key/kid；旧 Token 因 unknown kid 立即失效，不保留跨重启验证能力。
8. runtime 必须以单进程、单 worker、无多进程 preload/reload 模式运行；无法证明 process count 恰为 1 时启动失败。多个实例、滚动轮换与跨进程 key distribution 不在本切片。
9. `staging/rehearsal/production` 检测到该 provider 必须启动失败。production keyring、KMS/HSM、rotation、recovery 与 multi-instance verifier 均为 `NOT AUTHORIZED / NOT DEFINED BY THIS CR`。
10. rate-limit secret 与 signer key 分离，由 OS CSPRNG 生成至少 `32` bytes，只驻同一 local/test 进程内存；不得从 private key、public key、kid 或 fingerprint 派生。

### 3.6 Token 到 PostgreSQL 权威事实绑定

#### 3.6.1 Access binding

Access 验证顺序固定为：canonical compact/header -> kid allowlist -> Ed25519 signature -> exact claim 键/类型/常量 -> PostgreSQL snapshot 与 `db_now` -> time/user/organization/session/family binding -> 当前角色/permission -> resource scope。签名与静态 claim 校验未通过前不得使用不可信 `sub/sid` 查询业务资源。

PostgreSQL 权威 snapshot 必须证明全部条件：

- `users.id = UUID(sub)`，`users.deleted_at IS NULL`，`users.status='active'`；
- 用户所属 `organizations.id=users.organization_id`，组织 `status='active'` 且 `deleted_at IS NULL`；
- `token_sessions.id = UUID(sid)` 且 `token_sessions.user_id=users.id`；
- session 的 `auth_epoch` 逐值等于 `users.token_invalid_before`；两者的微秒投影都逐值等于 JWT `auth_epoch_us`；
- session 是其 family 唯一最大 `rotation_counter` row，`revoked_at/revoke_reason/replaced_by_session_id` 均为空；
- family root 满足 `id=family_id`、未绝对过期，且 root/user/session family 约束完整；
- Access `exp` 不晚于 session family 的绝对有效边界；
- 当前有效角色与 permission 只从 PostgreSQL `user_roles/roles` 按同一权威时间求值，JWT、Redis、Frontend 均不是授权来源。

Refresh 成功旋转后旧 `sid` 变为 rotated，因此绑定旧 `sid` 的 Access 从下一请求起失效。logout、replay、换密、禁用、重置或 auth epoch 推进也必须在下一请求拒绝旧 Access；不得用本地 cache 延迟。

#### 3.6.2 password-change binding

password-change JWT 没有 `sid`，不得创建或恢复普通 session。它必须同时绑定：valid local/test signer、`sub` 用户、用户当前 organization、当前 `auth_epoch_us`、`force_change_on_login=true` 与第 3.9 节 Redis create-only record。用户/组织失效、epoch 漂移、门禁已清除、record 缺失/已消费/不匹配时全部拒绝。

### 3.7 Refresh family storage、rotation 与 replay

#### 3.7.1 wire/digest

Refresh Token 必须匹配 `^rft_[A-Za-z0-9_-]{43}$`。suffix canonical unpadded base64url decode 后必须恰为 `32` OS-CSPRNG bytes，重新编码与原 suffix 逐字相等。数据库只保存 `SHA-256(UTF8(full_47_character_token))` 的 64 位小写 hex；明文仅在 login/refresh 成功响应边界返回一次。

普通 family 的绝对 expiry 为 root `issued_at+604800 seconds`；`remember_me=true` 为 root `issued_at+2592000 seconds`。rotation 不延长 expiry。所有 child 逐值继承 root 的 `user_id/family_id/remember_me/auth_epoch/expires_at`。

#### 3.7.2 `token_sessions` candidate columns

在既有表上仅增加七列：

| 列 | PostgreSQL type/nullability | exact semantics |
|---|---|---|
| `family_id` | UUID NOT NULL | root 等于自身 `id`；child 指向 root |
| `parent_session_id` | UUID NULL | root NULL；child 指向直接 parent |
| `replaced_by_session_id` | UUID NULL | 仅 rotated row 指向直接 child |
| `rotation_counter` | INTEGER NOT NULL | root=0；child=parent+1 |
| `remember_me` | BOOLEAN NOT NULL | family 内不可变 |
| `auth_epoch` | TIMESTAMPTZ NOT NULL | 签发时复制 `users.token_invalid_before`；family 内不可变 |
| `reuse_detected_at` | TIMESTAMPTZ NULL | 仅 rotated ancestor 首次重放时 NULL -> db_now |

`revoke_reason` 候选闭集恰为：

```text
rotated,logout,reuse_detected,user_disabled,password_changed,password_reset,admin_revoked
```

状态矩阵：

| row state | `revoked_at` | `revoke_reason` | `replaced_by_session_id` | `reuse_detected_at` |
|---|---|---|---|---|
| active tail | NULL | NULL | NULL | NULL |
| rotated ancestor | NOT NULL | `rotated` | NOT NULL | NULL 或首次 replay 时间 |
| replay terminal tail | NOT NULL | `reuse_detected` | NULL | NULL |
| other terminal tail | NOT NULL | `logout/user_disabled/password_changed/password_reset/admin_revoked` | NULL | NULL |

绝对 expiry 不是 revoke reason，不因过期改写历史行。

#### 3.7.3 required keys/constraints/triggers candidate

- 保留既有 `uq_token_sessions_refresh_token_hash`，并新增 lowercase SHA-256 hex CHECK。
- `family_id`、`parent_session_id`、`replaced_by_session_id` 都是 `token_sessions.id` 的 self FK，`ON DELETE RESTRICT`；`replaced_by_session_id` FK 必须 `DEFERRABLE INITIALLY DEFERRED`。
- 新增 `UNIQUE(family_id,rotation_counter)`。
- 新增 non-null `parent_session_id` partial unique 与 non-null `replaced_by_session_id` partial unique。
- 新增 `family_id WHERE revoked_at IS NULL` partial unique，保证每 family 最多一个 active row。
- root shape 必须为 `family_id=id AND parent_session_id IS NULL AND rotation_counter=0`；child 必须为 `family_id<>id AND parent_session_id IS NOT NULL AND rotation_counter>0`。
- `revoked_at` 与 `revoke_reason` 同空同非空；`replaced_by_session_id` 非空当且仅当 reason=`rotated`；`reuse_detected_at` 只允许 reason=`rotated` 且不得早于 `revoked_at`。
- `issued_at/expires_at/auth_epoch/revoked_at/reuse_detected_at/last_seen_at` 必须 finite；`expires_at>issued_at`；auth epoch 微秒投影必须位于 JSON-safe 非负整数范围。
- deferred family-consistency trigger 必须验证 parent/child 同 user/family/auth_epoch/remember/expiry、counter 连续、parent rotated、双向 pointer 一致与 root shape。
- `family_id/user_id/auth_epoch/remember_me/expires_at/parent_session_id/rotation_counter/refresh_token_hash/issued_at` 创建后不可变；任何 runtime DELETE/TRUNCATE 拒绝。
- `revoked_at/revoke_reason/replaced_by_session_id` 只允许一次合法 terminal transition；`reuse_detected_at` 只允许一次 NULL->db_now；`last_seen_at` 只允许 active row 非递减前移且不得晚于 db_now。

#### 3.7.4 mutation lock order 与 rotation CAS

所有 family mutation 使用同一顺序：

1. canonical Refresh format/hash 只读定位 candidate `user_id/family_id/session_id`；该结果尚不可信。
2. `SELECT users ... FOR UPDATE` 锁 user。
3. 按 root UUID 升序 `SELECT token_sessions WHERE id=family_id FOR UPDATE` 锁全部目标 family roots；单 family 也遵守该顺序。
4. 重读 presented row 与唯一 tail，并锁待更新 tail；捕获一次 PostgreSQL `db_now=clock_timestamp()`。
5. 重验 user、organization、auth epoch、root shape、family constraints、expiry 与 terminal state；任一漂移 fail closed。任何路径不得先持 family lock 再获取 user 或 `user_roles` 锁。

current active tail rotation 只有在下列 CAS 更新恰返回一行时成立：

```text
presented.id = tail.id
presented.revoked_at IS NULL
presented.revoke_reason IS NULL
presented.replaced_by_session_id IS NULL
presented.reuse_detected_at IS NULL
```

事务预生成 child UUID 与新 Refresh Token；先把 parent 原子更新为 `revoked_at=db_now/revoke_reason='rotated'/replaced_by_session_id=child_id/last_seen_at=db_now`，再插入 child。child 使用 `rotation_counter=parent+1`、继承 family immutable facts，且初始为 active。CAS rowcount 不等于 1、child insert/constraint/operation-log 失败时整个 PostgreSQL 事务回滚，且不得返回新 Token。

当 `root.expires_at-db_now <= interval '1830 seconds'` 时不旋转、不签发固定 1800 秒 Access，返回 `AUTH_REFRESH_EXPIRED`。成功所需 Access/Refresh bytes 可在事务内生成和签名，但只能在 PostgreSQL 状态与 companion operation log 成功提交后返回。

#### 3.7.5 replay/terminal precedence

锁后判断顺序固定：

| precedence/condition | state effect | response |
|---|---|---|
| 格式/hash 不存在，或 user/org/auth epoch 不匹配 | none | `401 AUTH_TOKEN_REVOKED` |
| `db_now >= root.expires_at` | none | `401 AUTH_REFRESH_EXPIRED` |
| tail reason=`logout/user_disabled/password_changed/password_reset/admin_revoked` | none | `401 AUTH_TOKEN_REVOKED` |
| tail reason=`reuse_detected` | none | `401 AUTH_REUSE_DETECTED` |
| current active tail 且剩余时间不足 | none | `401 AUTH_REFRESH_EXPIRED` |
| current active tail 且全部门禁通过 | parent rotation CAS + child insert | 200，新 Access/Refresh/session_id |
| presented 是 rotated ancestor、tail active、ancestor marker NULL | ancestor `reuse_detected_at=db_now`；tail 一次终止为 `reuse_detected` | `401 AUTH_REUSE_DETECTED` |
| ancestor 已标记或 tail 已 reuse terminal | no new mutation/log revoke | `401 AUTH_REUSE_DETECTED` |
| presented 为其他 terminal/corrupt relation | none | `401 AUTH_TOKEN_REVOKED` |

首次 replay 的 ancestor-marker CAS 与 active-tail terminal CAS 必须同一 PostgreSQL 事务各影响恰一行；任一 rowcount 不符整体回滚。两个并发请求使用同一 current token 时，第一个可先旋转，第二个取得 root lock 后必须进入 replay 分支并撤销刚生成的 active child；因此第一个响应也随即失效，family 必须重新登录。这是 `revoke_entire_family` 的精确定义，不允许 grace window。

### 3.8 logout terminal matrix

logout 禁止先调用第 3.6.1 节“必须为 active tail”的通用 Access binding。它使用封闭的 logout-specific verifier，顺序固定为：canonical compact/header -> kid allowlist -> Ed25519 signature -> exact claim 键/类型/常量 -> PostgreSQL `db_now` -> JWT time -> user/organization/auth epoch -> session/family logout state。签名与静态 claim 未通过前不得用 `sub/sid` 查询数据库。

logout-specific session/family state 只接受两类 actor：一是满足第 3.6.1 节全部 active session/root 条件的 current active tail；二是 actor `sid` 自身仍为该 family 唯一最大 `rotation_counter` row、`revoke_reason='logout'`、`revoked_at IS NOT NULL`、`replaced_by_session_id IS NULL`，且 JWT、user、organization、auth epoch 与 root absolute expiry 仍有效的 self-logout terminal 特例。第二类只允许 body 省略或定位同一 family；不得取得角色/permission/resource 权限，也不得访问其他 family。完成上述 actor 分类后，body 省略 Refresh 时 target 才是 actor `sid` 所属 family；body 提供 Refresh 时必须 canonical parse/hash 并解析为同一用户历史 session，其 family 为 target。unknown、malformed、cross-user locator 一律 `401 AUTH_TOKEN_REVOKED`，不得泄露归属。

审计边界固定为：Access signature/claims/time/user/organization/auth epoch 未能建立 actor 时不得使用不可信 `sub/sid` 写 PostgreSQL，只发 companion `security.auth.pre_identity_rejected.v1` 脱敏 telemetry。actor 已按上一段建立后，body 明确或解析后定位 cross-user family，或 self-logout terminal 尝试同用户其他 family，必须在返回隐藏式 `401 AUTH_TOKEN_REVOKED` 前，以 CR-006-R3 `logout_target_denied` event profile和 `actor_mode='verified_logout_subject'` 写一行 `security.authorization.denied`：`actor_role_codes={}/resource_type='api_request'/resource_id=NULL/api_id='AUTH-003'/http_method='POST'/error_code='AUTH_TOKEN_REVOKED'`，不得写 target/session/hash/是否存在事实，也不得取得 permission。该 denied audit 失败时仍保持零业务效果并按 companion 返回 `500 INTERNAL_ERROR + trace_id`。CR-006-R3 未把这一 exact error/profile 纳入封闭 registry 前，AUTH-003 runtime 保持 BLOCKED。

| actor Access / target | effect | response |
|---|---|---|
| actor 为当前 active tail；target 为同用户相同或其他 family 的未过期 active tail | 按 user->root 锁序把 target tail 一次终止为 `logout` | 204 |
| actor active；body locator 是 target 的 rotated ancestor，但 target family 当前 tail active | locator 只标识 family；终止当前 active tail，不改 ancestor | 204 |
| actor active；target root 已绝对过期 | 不改 revoke reason；只产生本次安全审计 | 204 |
| actor active；target tail 已为 `logout` | 无重复状态效果；重复请求仍审计/复用按 companion 决定 | 204 |
| actor active；target tail 为 `reuse_detected/user_disabled/password_changed/password_reset/admin_revoked` | none | `401 AUTH_TOKEN_REVOKED` |
| actor active；body 指向其他用户 family | none | `401 AUTH_TOKEN_REVOKED` |
| actor session 自身是唯一 tail、reason=`logout`、无 replacement，JWT signature/time/user/org/auth epoch 仍有效；body 省略或同 family | revoked-Access 唯一幂等特例；无状态变更；以 CR-006 `verified_logout_subject/logout_without_new_revoke` 写恰一行 `auth.logout`，roles=`{}`、`logout_outcome='already_revoked'` | 204 |
| 上一特例尝试 target 其他 family | none | `401 AUTH_TOKEN_REVOKED` |
| actor `sid` 是 rotated ancestor，即使后续 tail 已 logout | none | `401 AUTH_TOKEN_REVOKED` |
| Access expired/tampered/unknown kid，或 user/org/auth epoch 已失效 | none | `401 AUTH_TOKEN_REVOKED` |

active Access 可以撤销同一用户的其他 family，但不得撤销其他用户。revoked-Access 特例只允许重复关闭自身 family，不能扩大 bearer 权限。`db_now>=root.expires_at` 的 expired 判定先于 target terminal reason；绝不把 expiry 写成 revoke reason。

### 3.9 Redis password-change one-time record/CAS

#### 3.9.1 key 与 exact value schema

令 `jti_sha256=SHA-256(UTF8(canonical_lowercase_jti))` 的 64 位小写 hex。Redis key 精确为：

```text
finaudit:auth:password_change:v1:{<jti_sha256>}
```

value 使用 Redis Hash，字段集合必须逐集合等于以下八项，任何 extra/missing field 都是损坏状态：

| field | exact Redis string value |
|---|---|
| `schema_version` | `auth-password-change-state-v1` |
| `jti_sha256` | 与 key hash tag 相同的 64 位小写 hex |
| `user_id` | `sub` 的 lowercase canonical UUID |
| `organization_id` | 签发时 PostgreSQL `users.organization_id` lowercase canonical UUID |
| `auth_epoch_us` | canonical base-10 integer string；无前导零，0 除外 |
| `issued_at` | JWT `iat` canonical base-10 integer string |
| `expires_at` | JWT `exp` canonical base-10 integer string，且 `expires_at-issued_at=300` |
| `consumed` | create 时 `0`；CAS 后 `1` |

签发 password-change JWT 前执行单 key create-only Lua：key 已存在则返回 `COLLISION`；否则一次 HSET 八字段、设置相对 TTL 恰 `300` 秒并复核 key type/HLEN/TTL。创建后 invariants 不成立时脚本删除新 key并返回 `CORRUPT_CREATE`。Redis unavailable、script error、collision 或 corrupt create 均 fail closed，不返回 Token。

#### 3.9.2 consume precheck 与 CAS

AUTH-010 顺序固定：验签前 IP rate limit -> strict JWT parser/signature/静态 claims -> PostgreSQL read-only user/organization snapshot 与 `db_now` 完成 time/epoch/门禁校验 -> Redis read-only record exact-match -> 验签后 jti rate limit -> current-password/new-password policy -> user 与所有 family root 加锁并重验 -> Redis consume CAS -> PostgreSQL password/session/audit mutation与 commit。

consume Lua 只操作上述单 key，并使用调用方从已验证 JWT/PG snapshot 提供的八个 expected strings：

1. key 不存在或 TTL 已到界：`MISSING`。
2. key type 不是 hash、HLEN 不等于 8、字段格式非法或 TTL 不在 `1..300`：`CORRUPT`。
3. 七个 immutable field 与 expected 任一不等：`MISMATCH`。
4. `consumed='1'`：`ALREADY_CONSUMED`。
5. `consumed='0'`：原子 HSET 为 `1`，不得延长/重建 TTL，返回 `CONSUMED_NOW`。

映射固定为：`MISSING/MISMATCH/ALREADY_CONSUMED -> 401 AUTH_PASSWORD_CHANGE_TOKEN_INVALID`；`CORRUPT`、Redis unavailable 或 script error -> `503 DEPENDENCY_UNAVAILABLE`；只有 `CONSUMED_NOW` 允许继续 PostgreSQL 写入。`DEPENDENCY_UNAVAILABLE` 是既有 global stable code，但当前 AUTH-010 专属错误表尚未列出；shared Request transition 必须把它加入 AUTH-010 错误表。错误响应只含稳定 code 与 `trace_id`，不回显 key、record、jti 或比较值。

CAS 成功后 PostgreSQL 事务使用持锁后捕获的同一 `db_now` 精确写入：

```text
password_changed_at = db_now
new_token_invalid_before = GREATEST(db_now, old_token_invalid_before + interval '1 microsecond')
```

计算前后都必须证明 timestamp finite，且 `floor(extract(epoch from new_token_invalid_before)*1000000)` 位于 `0..9007199254740991`。`old+1 microsecond` 发生 PostgreSQL overflow、结果非 finite 或超出 JSON-safe 微秒范围时，Redis record 保持 `consumed=1` 并沿原 TTL 到期，PostgreSQL password/session/audit 事务整体回滚，固定返回 `500 INTERNAL_ERROR + trace_id` 且不含 `Retry-After`；不得钳位、环绕、unconsume 或复用旧 epoch。

同一事务更新 password hash，清除 `force_change_on_login/failed_login_count/locked_until`，终止全部 active family 为 `password_changed`，并提交 companion operation log。后续重新登录创建的新 root session 必须把 `auth_epoch` 逐值复制为该已提交的 `new_token_invalid_before`，新 Access 的 `auth_epoch_us` 也从同一值投影；严格 `+1 microsecond` 下任何旧 session/JWT epoch 必然不等并被拒绝。

若 PostgreSQL/审计提交失败，Redis record 保持 `consumed=1` 且沿原 TTL 到期，PostgreSQL 状态整体回滚；不得 unconsume、自动重试提交或重发同 Token，用户必须重新登录取得新 password-change Token。Redis 与 PostgreSQL 不构成分布式原子事务；这会把 Request 中“消费 Token 与密码事实单一事务”细化为明确的跨存储 fail-closed 语义，属于 `source_semantic_delta=NONZERO`，必须经 shared approval 并投影进 AUTH-010，禁止使用 zero-semantic-delta authorization。

Redis 丢失 record 时只会使受限 Token fail closed 并要求重新登录；它不是用户、密码、session 或审计的永久事实来源。

### 3.10 auth migration candidate shape

`AUTHSLICE-JS-009` 的 migration identity 现冻结为 candidate，不代表 artifact 已生成或获准执行：

```text
migration_file=backend/alembic/versions/20260811_010_extend_auth_session_family.py
revision=20260811_010
down_revision=20260811_009
branch_labels=None
depends_on=None
```

`20260811_009` 必须是 CR-006-R3 最终批准、已检入且 `alembic heads` 唯一返回的实际 head，目标数据库 `alembic current` 也必须逐字为 `20260811_009`。任一条件不满足时 `20260811_010` 整体 `BLOCKED / NOT RUNNABLE`；禁止自动改 `down_revision`、自动 rebase、建立 sibling branch 或把当前 `20260807_008` 猜成 predecessor。

upgrade 候选固定为：在任何 DDL 前 `SET LOCAL lock_timeout='5s'`，依次取得 `public.user_roles SHARE ROW EXCLUSIVE -> public.users ACCESS EXCLUSIVE -> public.token_sessions ACCESS EXCLUSIVE`；要求 `token_sessions` 行数恰为 0，并先验证所有既有 users 满足新增约束。非空、锁超时或 preflight 失败时在任何 DDL 前整体失败，不猜 legacy family/replay facts、不自动改写 users。

revision-owned object allowlist 精确如下；migration 不得创建任何未列对象：

- columns：`family_id,parent_session_id,replaced_by_session_id,rotation_counter,remember_me,auth_epoch,reuse_detected_at`，类型/nullability 逐值等于第 3.7.2 节；
- user CHECK constraints：`ck_users_username_canonical_lower_v1`、`ck_users_locked_until_requires_locked_v1`、`ck_users_token_invalid_before_epoch_v1`；
- token-session CHECK constraints：`ck_token_sessions_refresh_hash_lower_hex_v1`、`ck_token_sessions_root_child_shape_v1`、`ck_token_sessions_terminal_state_v1`、`ck_token_sessions_finite_times_v1`、`ck_token_sessions_auth_epoch_json_safe_v1`；
- self FKs：`fk_token_sessions_family_id_token_sessions`、`fk_token_sessions_parent_session_id_token_sessions`、`fk_token_sessions_replaced_by_session_id_token_sessions`，全部 `ON DELETE RESTRICT`，最后一项且仅最后一项 `DEFERRABLE INITIALLY DEFERRED`；
- unique constraint：`uq_token_sessions_family_rotation_counter_v1`；partial unique indexes：`uq_token_sessions_parent_session_id_not_null_v1`、`uq_token_sessions_replaced_by_session_id_not_null_v1`、`uq_token_sessions_family_active_v1`；既有 `uq_token_sessions_refresh_token_hash` 与 `idx_token_sessions_user_active` 原样保留；
- functions：`public.enforce_token_session_user_epoch_v1()`、`public.enforce_token_sessions_row_guard_v1()`、`public.enforce_token_sessions_family_v1()`、`public.reject_token_sessions_truncate_v1()`；全部 `SECURITY INVOKER`、body 只使用 schema-qualified object，且 `REVOKE ALL ON FUNCTION ... FROM PUBLIC`；
- triggers：`trg_token_sessions_user_epoch_v1`（`BEFORE INSERT`）、`trg_token_sessions_row_guard_v1`（`BEFORE UPDATE OR DELETE`）、`trg_token_sessions_family_v1`（`AFTER INSERT OR UPDATE` constraint trigger，`DEFERRABLE INITIALLY DEFERRED`）、`trg_token_sessions_no_truncate_v1`（`BEFORE TRUNCATE`）。

`trg_token_sessions_user_epoch_v1` 必须验证 user 存在、user/organization 未失效且 `auth_epoch=users.token_invalid_before`；organization 继续只由 user 派生。row guard、family constraint 与 truncate guard 必须逐项落实第 3.7.3 节 immutable、terminal transition、双向 pointer、family consistency 与禁止 runtime DELETE/TRUNCATE 语义。

downgrade 使用同一 `5s` timeout 和同一 table lock 顺序，且必须在任何 DROP 前证明 `token_sessions` 空表；随后严格按 trigger -> function -> index/unique/FK/CHECK -> column 的逆依赖顺序删除 allowlist 对象，禁止 `CASCADE`，不得删除、重命名或重建 002/008 owner object。任一 preflight、DROP 或 postcheck 失败时整个 downgrade 回滚并保留 revision。

本节不生成 migration/ORM/test，不把 frozen candidate identity/allowlist 表述为已实现、已静态检查或 PostgreSQL Gate 通过；named runtime ACL 仍等待 operation-log/auth runtime Gate。

### 3.11 source evidence 与 non-inheritance

- active Request 已冻结 AUTH-001/002/003/004/007/010、Access 1800 秒、五分钟一次性换密、Refresh rotation/replay、logout 204 与 PostgreSQL 为业务事实；它没有冻结上述 parser、claims、ephemeral kid、family CAS、logout terminal 或 Redis record 细节。
- 当前 `users/token_sessions` 与 002 migration 只提供 base identity/session columns；008 只提供已批准 privileged-role storage，不授权 Auth runtime。第 3.10 节因此是未来 migration candidate，而不是当前 Schema 事实。
- 旧 CR-013-R1 的 JWT/family/blocklist 内容仅作为 review input。本 revision 逐项重述所选 local/test candidate，并明确拒绝继承其 production keyring、snapshot、approval 或 baseline binding。
- shared approval record、九角色证据与十一文件同步算法不在本文件重定义；只允许已指定 owner `CR-014-R2` 在两份 companion exact revisions、A1/A2 与 nonzero source delta 闭合后统一冻结和授权。

## 4. 最小 permission candidate profile

```yaml
profile: auth-admin-user-list-slice-v1
permission_codes:
  - users:manage
role_map:
  system_admin: [users:manage]
  finance_reviewer: []
  audit_reviewer: []
  contract_admin: []
  read_only: []
consumers:
  API_AUTH_001: anonymous
  API_AUTH_002: current_session
  API_AUTH_003: current_session
  API_AUTH_004: current_session
  API_AUTH_007: ONE(users:manage)
  API_AUTH_010: password_change_purpose_only
backend_authority: PostgreSQL
frontend_authority: forbidden
unknown_role_or_permission: deny
```

- `users:manage` 是本 successor 的候选新增 code，不是现行 Request 已批准事实。
- 该切片最多把 `GAP-039` 推进为 `PARTIAL`；其余 P0 permission、角色映射和资源范围仍为 OPEN。
- Frontend 的 menu/route guard 只作展示提示，不能代替 Backend authorization。
- 临时有效 `system_admin` 是否可读取 API AUTH-007 仍是第 9 节必须批准的选择；治理写操作继续要求长期角色并不在本切片范围。

## 5. API AUTH-007 candidate read model

`UserListItemV1` 候选为精确八键：

| 字段 | 类型/语义 |
|---|---|
| `id` | UUID |
| `username` | string |
| `display_name` | string |
| `email` | string or null |
| `status` | `active/disabled/locked` |
| `role_codes` | sorted unique role code array；投影选择见第 9 节 |
| `locked_until` | RFC3339 UTC datetime or null |
| `row_version` | integer, `>=1` |

响应 `data` 仅含 `items` 与 `pagination`；`pagination` 精确三键 `page/page_size/total`。

```yaml
pagination:
  page_default: 1
  page_min: 1
  page_size_default: 20
  page_size_min: 1
  page_size_max: 100
query:
  status: active|disabled|locked|null
  role_code: one_of_five_fixed_roles|null
  keyword_fields: [username, display_name, email]
  organization_scope: actor_organization_only
  soft_deleted_users: excluded
  stable_order: username ASC, id ASC
```

不得返回 `password_hash/failed_login_count/token_invalid_before/refresh_token_hash` 或其他敏感认证事实。过滤与分页必须在 Repository 查询中完成，Router 不直接访问数据库。

## 6. UI-014 与 bootstrap 边界

### 6.1 只读 UI 切片

本候选只覆盖：

- 真实登录与 API AUTH-004 会话恢复；
- API AUTH-007 查询、状态/角色/关键字筛选与分页；
- UI-014 的 loading、empty、error、401、403 和 `trace_id` 展示；
- 删除该列表的 mock/sessionStorage 事实和“演示数据”行为。

创建用户、启停/解锁、角色替换、密码重置、break-glass 申请/批准/撤销按钮必须保持禁用且不得调用假 API。因此 UI-014 完整验收仍为 `NOT RUN`。

### 6.2 浏览器 Token custody

```yaml
browser:
  token_storage: javascript_memory_only
  cookie_storage: forbidden
  local_storage: forbidden
  session_storage: forbidden
  persistent_store: forbidden
  refresh_single_flight: required
  reload_requires_login: true
  token_response_cache_control: no-store
```

页面刷新、进程重启或前端运行时丢失后不得从持久介质恢复 Token；用户必须重新登录。任何 401 会话失效处理都不得误把匿名登录的 `AUTH_INVALID_CREDENTIALS` 当作已有会话撤销事件。

### 6.3 secret-safe bootstrap

CR-006-R3 必须新增并独占唯一高层入口 `public.bootstrap_auth_system_admin_v1(...)`；在该 exact wrapper 的签名、ACL、内部 oplog 调用与 fault atomicity 进入同一 source approval 前，本节保持 BLOCKED。bootstrap CLI 以 direct `session_user='finaudit_bootstrap'` 只允许执行一次参数化 `SELECT * FROM public.bootstrap_auth_system_admin_v1(...)`；不得对 `organizations/users/user_roles/operation_logs/operation_log_chain_state` direct DML，不得直接 EXECUTE `initialize_operation_log_chain_v1/append_system_bootstrap_log_v1/complete_operation_log_bootstrap_v1` 或任何 owner-only helper。

高层 wrapper 的输入字段集合与顺序固定为：

```text
p_request_event_id UUID,
p_trace_id UUID,
p_correlation_id UUID NULL,
p_bootstrap_input_sha256 TEXT,
p_organization_id UUID,
p_organization_name TEXT,
p_unified_social_credit_code TEXT,
p_tax_number TEXT,
p_admin_user_id UUID,
p_admin_username TEXT,
p_admin_email TEXT NULL,
p_admin_display_name TEXT,
p_admin_password_hash TEXT,
p_user_role_id UUID,
p_ip_address INET NULL,
p_user_agent TEXT NULL
```

- CLI 只允许从 TTY、stdin、受限 file descriptor 或 Secret Manager 取得 plaintext password，使用已锁定 `argon2-cffi==25.1.0`/`argon2-cffi-bindings==25.1.0` 生成符合第 3.1 节的 PHC，然后仅以数据库 bind parameter 传入 `p_admin_password_hash`。plaintext/PHC 均不得进入 argv、`.env`、仓库、默认值、shell history、日志、trace、error、telemetry、operation-log summary、snapshot 或 bootstrap input hash；调用结束后只作运行时可行的 best-effort 引用释放，不宣称 Python 内存可证明 zeroize。
- wrapper 内部取得同一事务/advisory lock，验证组织未初始化、固定五角色完整且 `system_admin` 唯一匹配，内部初始化 chain state，依次创建首组织、`status='active'/failed_login_count=0/locked_until=NULL/force_change_on_login=true` 的首管理员和 `assignment_source='bootstrap'/assigned_by=NULL/expires_at=NULL` 的首个长期 `system_admin` assignment，再内部追加/完成唯一 `system_bootstrap`。CLI 不能供应 role code、role ID、status、counter、force-change、assignment source、审计 action/result/order 或 chain state。
- `p_bootstrap_input_sha256` 精确采用 CR-006-R3 第 5.1.3 节十二键 RFC 8785 JCS object 与 SHA-256 framing：覆盖 `schema_version`、organization 四字段、admin 的 `id/username/email/display_name`、`user_role_id`、固定 `system_admin_role_id` 与 `force_change_on_login=true`；明确排除 `p_admin_password_hash/p_request_event_id/p_trace_id/p_correlation_id/p_ip_address/p_user_agent`。实现不得自行选择另一 JSON、字符串拼接、domain separator 或字段顺序。
- 返回表键与顺序固定为 `chain_id/organization_id/admin_user_id/system_admin_role_id/user_role_id/force_change_on_login/bootstrap_completed_at/request_event_id/event_created_at/log_identities/created`；`log_identities` 逐值采用 CR-006-R3 冻结的复合日志 identity array，不返回 password/hash/Token。首个成功事务返回 `created=true`；相同 input identity 的成功重跑返回既有同一十一字段且 `created=false`，不写第二行日志、不更新 password/hash/timestamp/row_version；不同 input hash固定返回 `BOOTSTRAP_ALREADY_COMPLETED`，半初始化、identity/hash/首行漂移固定 fail closed且不自动修复。
- wrapper 内部任一步失败时，chain state、组织、用户、assignment、首条 operation log 与 completion 全事务回滚；不存在可合法独立提交并保留的 disabled chain 半初始化分支。自动化测试可以在 disposable PostgreSQL 使用 synthetic fixture，但只有调用该高层 wrapper并验证同事务审计、幂等与 fault matrix 才能作为 bootstrap Gate evidence。
- synthetic 身份、邮箱、密码和 Token 不得进入生产镜像、文档或持久测试 snapshot；本 CR 不创建账号、不调用 wrapper。

## 7. Operation-log companion

认证状态副作用与审计追加必须在同一 PostgreSQL 事务中提交或回滚；拒绝路径必须生成不泄露资源存在性的安全审计。密码、Token、原始请求、认证 Header、完整 user-agent 或异常正文不得落入审计事实。

本切片依赖 `CR-006-R3-operation-log-auth-slice-current-baseline-successor.md` 的后续批准和 Gate。该 companion 未批准前：

- 不创建 `operation_logs` migration；
- 不开放登录、换密、refresh、logout、锁定或 AUTH-007 runtime；
- 不以普通应用日志替代追加写审计事实。

两份 source A1 还必须绑定 CR-006-R3 对以下 exact companion surface 的同 revision 修订：登录 summary 允许 `counter_outcome='unchanged'` 与 `lock_transition='expired_to_active'`；expired unlock 复用唯一 login action而不新增 action；`security.authorization.denied`/`authorization_denied` profile 对已建立 AUTH-003 actor 允许隐藏式 `AUTH_TOKEN_REVOKED`；唯一 bootstrap 高层入口为第 6.3 节 `public.bootstrap_auth_system_admin_v1(...)`，CLI 对低层 oplog helper 无 EXECUTE。CR-006-R3 任一项仍未冻结时，本 CR 不得形成 A1 snapshot；不得靠实现自行扩展封闭 registry。

## 8. Gate 与验收

### 8.1 shared approval 与同步 owner

本文件不复制共同 approval record、九角色证据、transition evidence、十一文件 path set、pre/post identity、re-pin 或原子替换算法。该 shared contract 的唯一 owner 是 `CR-014-R2`，本文件对其选择的 exact candidate 为 `AUTHSLICE-C-007=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`。唯一审批权威是 CR-014-R2 正文冻结的 typed direct-message contract 所校验、当前 task/thread 中平台认证为 BOSS/YHBX 直接 `user` 的消息；本地 JSON/JCS receipt、validator、snapshot、agent 输出或文件均无授权权威。在 CR-014-R2 governance direct approval 先行有效且该 typed contract 绑定本文件 exact bytes 前：

- `CR-006-R3` 与 `CR-013-R2` 不得分别生成竞争 post-state；
- 不得从旧 `CR-014`、旧 CR-013-R1 或 CR-006/008 review candidate 隐式继承 Schema、签名或同步授权；
- 不得生成中间 manifest、Request postimage、approval record、transition evidence 或 active-baseline re-pin；
- Gate A1 不得独立或先于 CR-014-R2 governance approval 形成 snapshot/approval；Gate A2 在 artifact 生成前保持 `BLOCKED / NOT RUN`，Gate B 保持 `NOT AUTHORIZED / NOT RUN`。

`CR-014-R2` 的 typed direct-message contract必须在 governance approval前冻结可承载两份 companion exact revision/hash、current manifest identity、本文完整 `D/C/JS` decisions、两条 source A1 BOSS direct message、A2 artifact/四角色 message identity与 `source_semantic_delta=NONZERO` 的 closed type；这只冻结未来字段与顺序，不要求尚未产生的 A1/A2实例。本文 A1 snapshot只以前置 CR-014 governance approval为依赖；两个 source A1、A2 artifact/message及其 exact identity均在 A1之后形成，并只作为 bundle/joint authorization的后置输入。缺任一后置实例均不能形成 joint authorization。禁止创建或依赖另一个 approval JSON Schema 文件。

### 8.2 Gate A1：contract approval

当前状态：`BLOCKED / NOT RUN`。

A1 只建立可签的 contract 对象，不生成 password blocklist artifact，不授权 Request sync、migration 或 runtime。它只能在 CR-014-R2 governance BOSS direct approval 有效、其正文 typed direct-message contract 已冻结后生成，且必须同时满足：

1. 第 9 节 `AUTHSLICE-C-001～C-008` 除 final artifact identity 外已逐项冻结，其中 `AUTHSLICE-C-007=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`、`AUTHSLICE-C-008=AUTHSLICE_PROFILE_AND_GATES_V1` 必须逐字选择；
2. 第 3.1.1 节 source manifest、两个独立 implementation manifest、artifact approval 十键 typed payload contract 与 A2 exact `role_decisions` 完整且内部唯一；
3. source binding 仍等于本文 current manifest hash；
4. CR-014-R2 governance snapshot 与九角色 BOSS direct approval 已先行有效，其正文 typed direct-message contract 明确绑定本文 exact revision/hash、完整 `D/C/JS` universe、A1/A2 与 nonzero semantic delta；
5. 本文 login/JWT/session-family/logout/Redis exact candidate 完整，bootstrap/operation-log companion 合同边界明确；
6. 九个合同审核角色审阅相同 revision、candidate values、staged artifact 规则与非目标；
7. 上述输入全部冻结后才可机械生成本 CR 唯一 decision preimage/snapshot；随后只有一条符合 CR-014-R2 typed contract、`approval_kind=CR013_R2_SOURCE_A1`、绑定该 snapshot、完整九角色与完整 `D/C/JS` choices 的平台认证 BOSS direct message可形成 contract approval。由消息派生的 local receipt 仅是 non-authoritative evidence。任何上游 bytes/typed-contract/decision 漂移都必须重新从 governance Gate 开始，禁止回填旧 snapshot。

`final_artifact_ref/final_artifact_sha256=UNRESOLVED_NOT_GENERATED` 是 A1 的预期输入，不是 A1 blocker。A1 snapshot/approval 只能批准“如何离线生成与如何批准 artifact”的合同，不能自称 artifact 已存在、A2 已通过或 active baseline 已同步。本 revision 当前没有生成该 snapshot，也没有任何 A1 approval 事实。

### 8.3 Gate A2：create-only password blocklist artifact approval

当前状态：`BLOCKED / NOT RUN`。

A2 只能在 CR-006-R3 与 CR-013-R2 两条 source A1 BOSS direct approval 都有效后运行：

1. operator 以离线方式提供 exact source/license bytes；执行器只接受与 A1 十三键 manifest 全部 identity 逐字相等的输入，不下载、不 follow redirect、不访问网络。
2. primary generator 与 independent verifier 的 implementation manifest JCS raw SHA-256 必须不同；两个 create-only manifest ref/hash 均逐值匹配 A1 contract。两实现分别验证固定 source raw identity，且只对 source manifest JCS hash、final nonempty line count 与 final raw hash 三项产生逐值相同 execution receipt。
3. final artifact 写入由 final raw hash 决定的 create-only `artifact_ref`；同 ref 已存在但 bytes/hash 不同即失败，禁止覆盖。
4. 形成第 3.1.1 节十键 payload；CR-014-R2 typed contract 必须逐值绑定其 raw SHA-256、final artifact ref/hash、两个 implementation manifest identity。
5. BOSS/YHBX 发送恰一条平台认证 `CR013_R2_BLOCKLIST_A2` direct message，其中 exact `represented_roles` 与同序四项 `role_decisions` 等于第 3.1.1 节固定值。四项 decision 全部为 `APPROVED`、有效期和所有 artifact identity 通过后 A2 才可标为 PASS；派生的四条 local role records只是 non-authoritative evidence。

A2 失败不撤销已批准的 A1 合同，但不得进入 joint Request sync、migration、runtime 或 Gate C。修复只能用相同 A1 合同生成全新 create-only candidate并取得新的合格 BOSS direct message；不得改写失败 artifact、拼接多条消息或追填 local receipt。

### 8.4 Gate B：Request 同步与静态合同

当前状态：`NOT AUTHORIZED / NOT RUN`。

只有两个 source A1 与 A2 BOSS direct approvals 都有效，且 CR-014-R2 joint authorization 逐值绑定它们、本文完整 decisions 与 `source_semantic_delta=NONZERO` 后，才可按其 exact shared transition 同步、重新计算 manifest 并 re-pin verifier。任何 `semantic_delta=ZERO` authorization 对本 source 无效。六个 API 的必需投影逐项为：

| API | Gate B 必须出现的 exact projection |
|---|---|
| AUTH-001 | canonical username/dummy verify、locked/disabled zero-counter failure、第五次锁定、expired→active 三分支、force-change、423/429 Retry-After、503 dependency failure及审计原子性 |
| AUTH-002 | strict Refresh wire/hash、root/tail family、每次 rotation、replay 首次整族 revoke/重复 no-new-effect、稳定 401 codes及 operation-log event |
| AUTH-003 | active/self-terminal verifier、重复自身 logout 204、actor 已建立后的 cross-user/other-family `401 AUTH_TOKEN_REVOKED` + `security.authorization.denied`、无效 Access pre-identity telemetry |
| AUTH-004 | strict Access parser、user/organization/session/family/auth_epoch 与当前 PostgreSQL role/permission 绑定，响应 DTO 不信任 JWT role |
| AUTH-007 | `users:manage`、临时有效 system_admin 只读选择、同组织 scope、八键 item、筛选/稳定分页、敏感字段禁出与 401/403 trace_id |
| AUTH-010 | password-change purpose Token、blocklist artifact、current/new password policy、Redis one-time CAS、429/503/500、epoch严格推进、Redis consumed/PG rollback及全部 session revoke |

九份 Request 的 staging postimage 必须分别投影且逐文件复核：

| Request 文件 | 必需投影 |
|---|---|
| `FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 六 API 的产品/安全语义、GAP-038/039/046 的本 slice 边界、非 production 与未闭合项 |
| `FinAudit_Agent_系统架构设计说明书_V1.0.md` | API→Service→Repository、PG/Redis trust boundary、单进程 local/test signer、dependency fail-closed、bootstrap wrapper |
| `FinAudit_Agent_数据库设计说明书_V1.0.md` | users/token_sessions 010 candidate、009 predecessor、SoD锁序、operation-log companion、统一 bootstrap transaction/ACL |
| `FinAudit_Agent_API接口设计说明书_V1.0.md` | AUTH-001/002/003/004/007/010 request/response/error/Header/permission/audit exact contract |
| `FinAudit_Agent_页面与交互设计说明书_V1.0.md` | UI-001/UI-014、内存 Token custody、force-change、Retry-After、401/403/429/503/trace_id、无 mock |
| `FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 明确本 Auth slice 不调用 AI/Provider、不把模型输出作为认证/授权事实；无 AI/RAG/Prompt 行为 delta |
| `FinAudit_Agent_测试与验收方案_V1.0.md` | 六 API、并发锁定/解锁/replay/logout、blocklist双实现、dependency evidence、009→010、bootstrap及故障回滚矩阵 |
| `FinAudit_Agent_部署与运维说明书_V1.0.md` | 三个 dependency/完整 wheel lock、single-process local/test、PG/Redis/DB role、secret-safe bootstrap、staging/production hard stop |
| `FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | source/A2/joint Gate顺序、009→010依赖、实现/测试工作包与未授权边界 |

Gate B 还必须生成并复核第 3.2.1 节三个 direct package及完整 transitive closure 的 wheel/hash/license evidence，验证 OpenAPI/DTO/UI fixtures与上述六行一致；缺任一 API、Request 文件或 dependency identity 整体失败。本文不提供可执行同步算法，也不授权 migration、package 安装、账号创建、服务启动或业务流。

### 8.5 Gate C：development/test 真实链

当前状态：`NOT AUTHORIZED / NOT RUN`。

前置包括：companion operation-log PG16 Gate、auth migration 往返、已锁定三项 direct dependency与完整 closure可离线安装/import、真实 PostgreSQL/Redis fail-closed、唯一高层 bootstrap wrapper/CLI、API AUTH-001/002/003/004/007/010、UI browser E2E、脱敏与并发失败路径。production、staging、provider、部署、canary、UAT、AC-001 均不在本 Gate 授权范围。

候选验收至少覆盖：首次登录强制换密且无普通 session；换密后重新登录；第五次失败锁定；Refresh 重放撤销整族；同组织 AUTH-007 成功；其他角色/跨组织拒绝；分页稳定无重复漏项；敏感字段缺失；UI 无 mock；Token 不进入持久浏览器存储；审计与状态原子提交。

## 9. BOSS 必须逐项决定的非可推断项

1. `AUTHSLICE-C-001`：是否批准拆成 CR-013-R2 + CR-006-R3 两份 companion；推荐 `TWO_CR`。
2. `AUTHSLICE-C-002`：development/test signer 是否采用“单进程 ephemeral Ed25519，staging/production 硬拒绝”；推荐 `EPHEMERAL_ED25519_LOCAL_TEST_ONLY`。
3. `AUTHSLICE-C-003`：当前有效的临时 `system_admin` 是否可读取 API AUTH-007；推荐 `ALLOW_READ_ONLY_AUTH007`，治理写操作仍要求长期角色。
4. `AUTHSLICE-C-004`：API AUTH-007 的 `role_codes` 是否表示当前有效角色并集；推荐 `EFFECTIVE_ROLE_UNION`。未来编辑固定角色必须另增 `fixed_role_codes` revision。
5. `AUTHSLICE-C-005`：是否批准第 3.1.1 节 staged source/generator candidate；推荐 `STAGED_SECLISTS_2026_1_BLOCKLIST_V1`。final ArtifactRef/hash 必须在后续独立 artifact approval 中生成，当前仍 `UNRESOLVED_NOT_GENERATED`。
6. `AUTHSLICE-C-006`：是否批准第 3.3～3.10 节九项 exact local/test 子决策；推荐 `LOCAL_TEST_JWT_SESSION_FAMILY_V1`，不得沿用库默认或旧 R1 approval。
7. `AUTHSLICE-C-007`：shared approval record、九角色 evidence、transition 与十一文件同步合同 exact candidate 固定为 `CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`；由 `CR-014-R2` 独占治理，当前 `NOT APPROVED / NOT AUTHORIZED`。
8. `AUTHSLICE-C-008`：本文第 3～7 节 candidate profile 与第 8 节 Gate 分层 exact candidate 固定为 `AUTHSLICE_PROFILE_AND_GATES_V1`；不包含 CR-014-R2 独占的 typed direct-message/receipt/transition bytes。必须逐项确认，不接受模糊自然语言批准。

任一项未决时不得生成 snapshot、同步 Request 或实施 runtime。

## 10. 当前动态状态

| 项目 | 状态 |
|---|---|
| source baseline binding | `VERIFIED / CURRENT` |
| candidate profile | `DEFINED FOR REVIEW / NOT APPROVED` |
| BOSS choices | `PENDING` |
| password blocklist source/generator candidate | `DEFINED FOR REVIEW / NOT APPROVED` |
| password blocklist final ArtifactRef/hash | `UNRESOLVED_NOT_GENERATED` |
| Python crypto dependency identity | `3 DIRECT VERSIONS DEFINED / WHEEL-HASH-LICENSE EVIDENCE NOT GENERATED / NOT INSTALLED` |
| JWT/session-family exact sub-contract | `DEFINED FOR REVIEW / NOT APPROVED` |
| operation-log companion exact contract | `DEFINED IN CR-006-R3 / NOT APPROVED` |
| shared approval / eleven-file transition | `CANDIDATE CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1 / CR-014-R2 GOVERNANCE NOT APPROVED` |
| source semantic delta | `NONZERO / AUTH-001/002/003/004/007/010 + NINE REQUEST PROJECTIONS REQUIRED / NOT APPROVED` |
| auth migration revision identity | `FROZEN CANDIDATE 20260811_010 -> 20260811_009 / PREDECESSOR NOT ACTUAL HEAD / NOT AUTHORIZED` |
| decision preimage/snapshot | `NOT GENERATED` |
| Gate A1 contract approval | `BLOCKED / NOT RUN / NO SNAPSHOT` |
| Gate A2 blocklist artifact approval | `BLOCKED / NOT RUN / ARTIFACT NOT GENERATED` |
| Gate A | `BLOCKED / NOT RUN` |
| Request sync / manifest update | `NOT AUTHORIZED / NOT RUN` |
| migration / Repository / Service / Router | `NOT AUTHORIZED / NOT RUN` |
| real account / PostgreSQL / Redis / browser E2E | `NOT AUTHORIZED / NOT RUN` |
| staging / production / deployment / UAT / AC | `NOT AUTHORIZED / NOT RUN` |
