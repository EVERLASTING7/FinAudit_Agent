# CR-013 Authentication Security Profile Closure

- revision：`CR-013-R1`
- profile：`auth-security-v1`
- permission profile：`p0-permissions-v1`
- source baseline manifest SHA-256：`717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`
- scope：认证合同、会话安全、浏览器令牌保管、P0 权限字典及迁移边界

## 1. 背景、目标与边界

### 1.1 待关闭缺口

`GAP-038` 尚未冻结密码哈希与密码策略、登录锁定、`remember_me`、JWT 与密钥轮换、Refresh Token 重放处置；`GAP-039` 尚未冻结 `/auth/me.permissions` 的完整字典和五角色映射。当前代码不得用默认配置、示例响应或实现偏好替代这些合同。

API 文档的 `AUTH-001～AUTH-004` 表示 login、refresh、logout、me；实施计划的同名编号表示数据层、认证、RBAC、用户管理工作包。本文出现编号时必须显式写成“API AUTH-*”或“计划 AUTH-*”。

### 1.2 本修订关闭的范围

1. 密码输入、策略、哈希、rehash、blocklist 和未知用户等成本验证。
2. 登录失败计数、临时/人工锁定、并发更新和匿名登录限流。
3. Access / password-change JWT 的固定算法、claims、时间边界和 keyring 生命周期。
4. opaque Refresh Token、会话族、旋转、并发重放和族撤销。
5. 强制换密错误包络、一次性 Token、logout 幂等特例和错误优先级。
6. 35 个 P0 permission code、五角色静态映射和动态授权边界。
7. 浏览器令牌保管、清理和用户可见行为。
8. 修改 `users/token_sessions` 的单一迁移、回滚、依赖、审计事务和测试门禁。

### 1.3 非目标与禁止边界

- 不新增 API path，不新增核心父表，不新增 operation-log action；不实现用户管理、break-glass 或业务资源状态机。
- 本合同不批准任何真实 secret、账号、密码、Token、密钥值、环境地址或生产数据。
- `network_scope=none`；不授权 `fixed_test_provider`、模型、Qdrant 或其他外部网络调用。
- `production_release_scope=none`；不授权 migration 执行、runtime 开放、canary、部署或 production 放行。
- 本合同不得把 CR-003、CR-006、CR-008 的 review snapshot 表述为已批准事实。
- PostgreSQL 是用户、会话和角色的权威来源；Redis 只保存可丢失后 fail-closed 的限流和短期一次性授权状态。

### 1.4 规范参考

- NIST SP 800-63B Rev.4 password requirements：<https://pages.nist.gov/800-63-4/sp800-63b/authenticators/>
- OWASP Password Storage Cheat Sheet：<https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
- RFC 8725 JSON Web Token Best Current Practices：<https://www.rfc-editor.org/rfc/rfc8725>
- RFC 8037 CFRG ECDH and Signatures in JOSE（Ed25519/EdDSA）：<https://www.rfc-editor.org/rfc/rfc8037>
- Python 3.10 `secrets`：<https://docs.python.org/3.10/library/secrets.html>

## 2. 决策全集、delta 与依赖

### 2.1 必选决策

批准必须逐项选择以下八项，顺序固定；“批准全部推荐”或自然语言别名不能替代精确数组。

1. `AUTHSEC-D-001=PASSWORD_HASH_AND_POLICY_PROFILE_V1`
2. `AUTHSEC-D-002=LOGIN_LOCKOUT_PROFILE_V1`
3. `AUTHSEC-D-003=JWT_KEYRING_AND_CLAIMS_PROFILE_V1`
4. `AUTHSEC-D-004=REFRESH_FAMILY_ROTATION_REPLAY_PROFILE_V1`
5. `AUTHSEC-D-005=PASSWORD_CHANGE_LOGOUT_ERROR_PROFILE_V1`
6. `AUTHSEC-D-006=P0_PERMISSION_DICTIONARY_ROLE_MAP_V1`
7. `AUTHSEC-D-007=BROWSER_TOKEN_CUSTODY_PROFILE_V1`
8. `AUTHSEC-D-008=MIGRATION_ROTATION_ROLLBACK_TEST_PROFILE_V1`

### 2.2 固定 delta

| 项目 | 值 | 说明 |
| --- | ---: | --- |
| `api_path_delta` | `0` | API AUTH-001～015 已存在；只闭合语义和 payload |
| `core_table_delta` | `0` | 只修改既有 `users/token_sessions`，不创建或删除 core table |
| `alembic_migration_delta` | `1` | 单一线性 revision，实际 identity 在实施前绑定 |
| `operation_log_action_delta` | `0` | 逐字复用 CR-008 已列认证动作 |

### 2.3 无环依赖

静态合同顺序固定为：

```text
CR-001-R2/D-004 已批准并同步
  -> CR-013-R1 生成静态 review snapshot，但尚不形成批准
  -> DEP/shared approval+sync successor 纳入 CR-013 并先获批
  -> 由本合同生成、校验并发布 `auth-keyring-manifest-v1` Schema
  -> CR-013 九角色使用该 successor 形成机器可验批准记录
     -> keyring manifest实例由 backend_api/ops/security/test 四角色形成独立 artifact批准，生成current-pin与派生immutable sign-policy，经包外可信 strict-time CAS激活并形成transition receipt后生成 runtime binding（仅约束 AUTH runtime）
     -> 按 DEP-005/CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010 顺序逐 source 授权并同步，形成 aggregate baseline
  -> CR-003 migration 落地 user_roles/break_glass_requests 并完成 PG16 验证
  -> CR-006/CR-008 successor 基于 aggregate baseline 原子联合批准并落地 operation_logs
  -> CR-013 token_sessions migration
  -> Backend AUTH Repository/Service/API
  -> Frontend 真实登录/RBAC
  -> PostgreSQL/API/E2E/AC-001 验收
```

CR-013 的合同批准不依赖 operation_logs；任何 AUTH 状态副作用与 runtime 开放依赖已落地的 CR-003 user-role 事实和 CR-006/008 operation-log 事实。不得先以普通应用日志冒充审计，也不得先建简化 `user_roles`。

## 3. Authentication Security Profile

### 3.1 AUTHSEC-D-001：密码和哈希

#### 3.1.1 输入与策略

`password_profile_version='auth-password-v1'`，`auth_unicode_data_version='13.0.0'`。所有节点必须使用该 Unicode data version 完成 NFC 与 Default Case Folding，版本不符时启动失败。新密码和重置密码按以下顺序处理：JSON string 严格解码；拒绝 U+0000；执行 Unicode NFC；不 trim、不 casefold、不折叠或删除空白。NFC 后必须同时满足 `15..128` Unicode code points 与 UTF-8 `15..512` bytes。允许空格和全部合法 Unicode，不设大写、小写、数字或符号组合规则。

密码不得包含 username 或 organization name 的 NFC+casefold 完整值；比较前仅对这两个上下文值及候选密码副本执行 NFC+casefold，不改变送入哈希的 NFC password bytes。密码必须通过本地 blocklist：

- artifact version 固定 `auth-password-blocklist-v1`；UTF-8、无 BOM、LF-only、末尾一个 LF；
- 每行恰为 `SHA-256(UTF8(casefold(NFC(blocked_password))))` 的64位小写hex；按 ASCII/code-point升序、无重复，内容必须由下述 source manifest和算法全量派生，不能以随机/自选1万行满足数量门槛；
- artifact 的项目名输入集合恰为 `FinAuditAgent/FinAudit Agent/FinAudit-Agent/FinAudit_Agent`：生成器固定取 ASCII token `FinAudit`、按 `""/" "/"-"/"_"` 顺序插入 separator、再拼接 `Agent`；每个输入执行上一行 NFC+casefold+UTF-8+SHA-256，去重后必须全部存在。大小写变体因 casefold 不另建输入或重复 digest；企业名和 username 不写入静态 artifact，而由上一段动态上下文比较覆盖。完整 plaintext source corpus、用户密码或 secret不得进入仓库和日志；本节四个产品名输入及第3.1.1节末尾六个公共弱口令仅是封闭、非秘密验收向量，允许逐字列在合同中，不得扩展为用户或企业数据；
- common/compromised source 固定为 SecLists release `2026.1` 的 `100k-most-used-passwords-NCSC.txt`。`auth-password-blocklist-source-v1` manifest根精确十三键 `schema/source_name/release_tag/commit_oid/source_path/source_uri/source_git_blob_sha1/source_raw_sha256/source_byte_length/source_nonempty_line_count/license_spdx/license_path/license_raw_sha256`，其值依次固定为：`auth-password-blocklist-source-v1`、`SecLists`、`2026.1`、`190c6f7bd58c847ceadfe57d9853592737f059e8`、`Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`、`https://raw.githubusercontent.com/danielmiessler/SecLists/190c6f7bd58c847ceadfe57d9853592737f059e8/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`、`38eb37702244f55fda75cab281eb2145cd7685b6`、`c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0`、`835538`、`99839`、`MIT`、`LICENSE`、`3dbdc93d5f8829de0941744841730a09c106d0732e5ae0e98ca1d77be7ded66c`。source必须strict UTF-8、无BOM/NUL/CR、LF-only且末尾一个LF；恰有99839个非空行和一个空内容行，空行忽略，其余每行不trim并全部进入生成器。任一 metadata/raw/license不符即拒绝；不得用master/latest或重定向后的不同bytes替代。
- generator固定为 `auth-password-blocklist-generator-v1`：验证上一条全部const -> strict解码/按LF切分 -> 忽略唯一空行 -> 每个非空原始行依次做Unicode13 NFC+Default Case Folding+UTF-8+SHA-256 -> 加入上一条四个项目名输入的同算法digest -> set去重 -> 64位小写hex ordinal排序 -> 每行加LF并以无BOM UTF-8输出。两个独立实现必须对 source manifest JCS、source raw bytes、generator source raw hash、最终非空行数和最终 artifact raw hash逐字一致；approval record绑定这些五项，不能只签最终文件。plaintext source只允许在隔离artifact构建目录暂存并在验证后清理，不进入仓库、日志、镜像或runtime。
- runtime 必须绑定已批准 artifact 的 version、source-manifest hash、generator hash、raw SHA-256和本地只读路径；缺失、hash不符、重复、未排序、派生receipt不符或最终集合未命中 `password/123456/qwerty/football/qwertyuiop12345/123456789012345` 的规范digest一律 fail closed。本文不在静态 preimage中预填尚未生成的 generator/final artifact identity，其生成状态只记录在第9节。

R1 runtime 只接受逐项等于本节参数的 Argon2id v=19 PHC；既有任一用户 hash 的算法、版本、m/t/p、salt length 或 digest length不符时，AUTH runtime激活前必须通过受控密码重置消除，禁止在线混用不同成本后声称未知用户等成本。登录请求的 password 受 512 UTF-8 bytes 输入上限；超限与畸形输入返回 `AUTH_INVALID_CREDENTIALS`，不得进入哈希函数造成资源放大。未来接受第二套 Profile 必须提升 CR revision，并冻结“每个 accepted profile 恰一次 real-or-dummy verify”的等工作量矩阵。

#### 3.1.2 哈希和 rehash

新 hash 固定为 Argon2id，参数为 `m=19456 KiB`、`t=2`、`p=1`、salt 16 random bytes、digest 32 bytes、PHC string。salt 由操作系统 CSPRNG逐次生成；禁止固定 salt、应用级共享 salt、截断密码和自行实现 Argon2。

成功验证后，若库的 `check_needs_rehash` 判定参数或编码不是本 Profile，必须在签发任何 Token 前于同一用户事务更新 hash；rehash 失败则本次登录整体失败且不得创建 session。不得在失败登录、锁定账号或未知账号路径 rehash。

环境必须提供一条通过同一 Profile 生成的 `AUTH_DUMMY_PASSWORD_HASH`；未知、软删除或不可建立可信组织的 username 必须对该 hash 执行一次完整 verify，再返回通用错误。dummy hash 格式/参数不符时服务启动失败；它不是用户凭据，不得与真实用户 hash 相同。

密码、hash、blocklist 命中值、Token 和 key material 不进入错误、trace、operation log、security log 或指标 label。

### 3.2 AUTHSEC-D-002：登录、锁定和限流

#### 3.2.1 持久锁定状态机

权威时间为 PostgreSQL `clock_timestamp()` UTC。已识别用户的普通登录判定使用 `SELECT ... FOR UPDATE`，密码验证可在锁外完成，但提交前必须重新锁行并重验 `status/locked_until/failed_login_count/password_hash/token_invalid_before/row_version`；任一漂移时丢弃旧验证结果并在锁后重新验证，禁止丢更新。若锁后发现本请求会执行 `active -> locked` 或“临时锁到期 -> active”状态转换，当前事务不得写任何 state/audit：必须整体回滚释放 user lock，再通过 CR-003 普通 mutation wrapper 从 `user_roles SHARE ROW EXCLUSIVE` 表锁开始重入，随后按 UUID 锁 user/role/user_roles 并重验用户、密码、计数、锁时间与 db_now，最后在同一 wrapper 事务完成本次登录结果；禁止持 user lock 后补取表锁。未改变 `users.status` 的失败计数、成功计数清零或拒绝路径不取得该表锁。

| 前置状态 / 结果 | 同事务写入 | API 结果 |
| --- | --- | --- |
| unknown、软删除或组织 inactive | 不写 `users`；执行 dummy verify | `401 AUTH_INVALID_CREDENTIALS` |
| `disabled` 且密码错误 | 不改计数 | `401 AUTH_INVALID_CREDENTIALS` |
| `disabled` 且密码正确 | 不改计数 | `403 AUTH_USER_DISABLED` |
| `locked` 且 `locked_until IS NULL` | 不改计数；执行一次真实 verify | 密码正确为 `423 AUTH_ACCOUNT_LOCKED`，否则 401 |
| `locked_until > db_now` | 不改计数；执行一次真实 verify | 密码正确为 423，带 `Retry-After=ceil(locked_until-db_now)`；否则 401 |
| 临时锁已到期 | 先恢复 `status='active'`、计数 0、`locked_until=NULL`，再处理本次结果 | 按 active 分支 |
| active、错误密码、第 1～4 次连续失败 | `failed_login_count += 1` | `401 AUTH_INVALID_CREDENTIALS` |
| active、错误密码、第 5 次连续失败 | `failed_login_count=5/status='locked'/locked_until=db_now+900s`，并写 lock 审计 | 仍为 `401 AUTH_INVALID_CREDENTIALS`；不暴露该 username 刚被锁定 |
| active、密码正确 | 计数 0、`locked_until=NULL`；完成 rehash 与其余门禁 | 普通登录或强制换密分支 |

阈值固定 5 次连续失败，临时锁定固定 900 秒；不另设时间窗口。成功登录或临时锁到期重置连续计数。人工无限锁定使用 `status='locked' AND locked_until IS NULL`，只有批准的用户管理流程可解除；临时锁不得被后台定时任务提前改写。

已识别目标的失败、拒绝和锁定按 CR-008 写 `auth.login.failure/auth.login.denied/auth.account.lock`；未知目标只写脱敏结构化 security log。用户状态效果与对应 operation log 必须遵循 CR-008 的同事务边界；日志不可用时不得提交锁定、登录 session 或 Token。

#### 3.2.2 匿名入口限流

限流在用户查询和密码验证前执行；只允许先做 trusted-client-IP解析与 username语法/canonical投影，不读取用户事实。Profile固定：

login username 只允许 ASCII，规范为：移除首尾 U+0020，匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`，再执行 ASCII lowercase 得到唯一 `username_login`。空值、其他空白、non-ASCII或control没有 canonical identity：该请求仍必须先消耗可信 IP bucket，通过后返回通用凭据错误，但不得建立 identity key。新建/修改/导入用户必须存储该 lowercase 值；migration 在任何写入前要求每个既有 `username::text` 已逐字等于其 canonical lowercase投影且投影无碰撞，任一不等或碰撞整体 fail closed，不做不可逆回填。随后增加精确 CHECK `username::text ~ '^[a-z0-9][a-z0-9._-]{0,99}$'`。数据库查询和限流 digest 都只使用该同一 canonical bytes，不混用 CITEXT collation 与 Unicode casefold。

- Redis sliding-window 60 秒；同一可信 client IP 上限 30 次，同一 `identity_digest` 上限 10 次；当前请求计入窗口，计数大于上限即拒绝；
- `identity_digest=HMAC-SHA-256(rate_limit_secret, UTF8(username_login))`；只保存 digest，不保存 username；rate-limit secret 与 JWT Ed25519 KMS/HSM signing-key控制面分离；
- 每次真正接收 HTTP attempt 都由服务端生成不可由客户端控制、绝不复用的 UUIDv4 `rate_event_id`；不得使用 `X-Request-ID/traceparent/Idempotency-Key` 或 username 作为 ZSET member；每个实际执行的 bucket恰插入该 member一次；
- canonical username存在时，IP和identity两个 Redis key使用共同 hash tag `{auth-login}`，由单一原子 Lua 在 standalone/cluster同slot执行；不存在 canonical username时，独立 Lua只处理IP key且绝不接触identity key。两脚本都使用 Redis `TIME`，删除 `score <= now_ms-60000` 后插入当前 `rate_event_id`并计数；双bucket任一超限移除本次两个member，IP-only超限只移除本次IP member；
- 非空 key每次执行都 `PEXPIRE 120000`，空 key立即`DEL`；禁止无TTL key。双bucket的 `Retry-After` 分别计算所需等待并取最大值、再与1取最大；IP-only只用IP等待值。响应不指出命中的 bucket；
- immediate peer 不在已批准 `AUTH_TRUSTED_PROXY_CIDRS` 时忽略转发头；在 allowlist 时从 `X-Forwarded-For` 右向左跳过可信代理并选择第一个不可信合法 IP；头畸形、为空或链全部可信时使用 immediate peer；
- Redis、Lua、rate-limit secret 或代理 Profile 不可用时，API AUTH-001 在密码验证前返回 `503 DEPENDENCY_UNAVAILABLE`；禁止 fail open、进程内替代计数或把一次失败写成账号锁定。

### 3.3 AUTHSEC-D-003：JWT、claims 与 keyring

`token_profile_version='auth-token-v1'`。只允许 RFC 8037 的 `EdDSA` 且曲线固定为 Ed25519；验证器的 allowed algorithms 为代码常量 `['EdDSA']`，不得从 token header、配置字符串或未认证 payload 推导，`HS256/RS256/ES256/none` 和其他算法全部拒绝。每把私钥必须由满足本节全部封闭能力且受部署信任根认证的 KMS/HSM 使用其 CSPRNG 在设备边界内生成，形成 fully version-qualified、create-only、不可导出的 Ed25519 key version；任何应用、signer、verifier、部署或控制面 principal 都不得读取、导出、解封或接收 seed/private bytes。verifier只持有manifest中的32-byte raw public key，signer只在受控时窗调用该精确 key version 的 Ed25519 sign capability。禁止自行实现Ed25519。

JWT header 精确三键 `alg/kid/typ`，其中 `alg='EdDSA'`。Access 使用 `typ='at+jwt'`；强制换密使用 `typ='pwd+jwt'`。`kid` 必须匹配 `^[A-Za-z0-9_-]{8,64}$` 并命中已批准 keyring；未知、重复、`revoked` 或不在本节验证时间窗内的 key 一律拒绝。

任何 `kid` 选择、Ed25519签名验证或业务查询之前，compact JWT 必须恰为三个非空、无 padding 的 canonical base64url segment：字符只允许 `[A-Za-z0-9_-]`，逐段解码后重新按无 padding base64url 编码必须与原 segment 逐字相等；header/payload bytes 必须是严格 UTF-8，signature 必须解码为恰好64 bytes。header 与 payload 分别只解析一次且都必须是 JSON object；解析器必须保留 raw member pair 并在构造映射前拒绝任意重复 member name，不能依赖 first-wins/last-wins。后续 key 选择、签名校验、claims 与业务授权必须消费同一不可变解析结果；若 JWT 库内部必须再次解析，预检必须先拒绝重复键，且库输出的键集、类型和值必须与该解析结果逐值相等，否则统一 token-invalid。禁止先由一个解析器用 `alg/kid` 验签、再由另一个解析器用不同 `sub/sid/purpose/iat` 授权。

Access payload 精确十键：`iss/aud/sub/sid/jti/purpose/iat/nbf/exp/auth_epoch_us`。强制换密 payload 精确九键：删除 `sid`，其余相同且 `purpose='password:change'`。类型和取值固定：

- `iss='finaudit-agent'`、`aud='finaudit-api'`；`sub/sid/jti` 为小写 canonical UUID；
- `purpose='access'|'password:change'` 与 header typ 一一对应；
- `iat/nbf/exp` 为非负 JSON safe integer NumericDate seconds；签发事务只取一次 PostgreSQL `db_now=clock_timestamp()`，固定 `iat=nbf=floor(extract(epoch from db_now))`；Access `exp=iat+1800`，password-change `exp=iat+300`；
- `auth_epoch_us` 为 `floor(extract(epoch from users.token_invalid_before)*1000000)` 的非负 JSON safe integer（`0..9007199254740991`）；`token_invalid_before` 必须 finite，验证时数值必须与当前用户列逐字相等；
- payload 禁止 roles、permissions、email、display_name、password 状态和额外 claim。

权威校验时刻来自同次 PostgreSQL 请求的 `clock_timestamp()`。固定 leeway 30 秒：`iat <= now+30`、`nbf <= now+30` 且 `now < exp+30`；`exp<=iat`、寿命不等于 Profile 或时刻越界均拒绝。Access 还必须验证 `sid` 对应当前用户、session 未撤销、未过期、family 当前成员唯一、session.`auth_epoch` 等于当前用户列；每个受控请求都查询权威状态，不以缓存或 JWT role 替代。

`auth-keyring-manifest-v1` 是不含 secret 的 create-only制品。其根精确九键 `schema_version/token_profile_version/keyring_version/environment_id/environment_class/generated_at/previous_manifest_ref/entries/entries_sha256`：前二者分别固定为 `auth-keyring-manifest-v1/auth-token-v1`；`keyring_version` 匹配 `^krg-[0-9]{8}$` 且数字后缀必须为 `1..99999999`。包外 expectation 仍为全null/0时，候选version固定为 `krg-00000001`、`previous_manifest_ref=null` 且 `entries` 恰一项active；已有current-pin N后，候选version数字必须恰为N+1，`previous_manifest_ref` 是 shared contract精确五键 ArtifactRef并逐字等于该pin的 `manifest_ref`。同一当前expectation下允许多个尚未激活的同version候选竞争，但每个 manifest/hash/key/pin/policy 与四角色批准集合必须独立且不得复用；它们不进入activated predecessor链，只有strict CAS胜者成为该version唯一合法hash，其余候选永久拒绝。`environment_id` 为小写 canonical UUID，`environment_class` 只允许 `development/test/staging/rehearsal/production`；`generated_at` 必须finite、UTC整秒并使用精确 `YYYY-MM-DDTHH:MM:SSZ`，有activated predecessor时还必须严格晚于它。后续版必须验证 predecessor raw hash与同一 profile/environment；只有包外current-pin链构成activated predecessor链，不得按未认证目录、文件名或“最大version”猜 predecessor。

`entries` 按 `kid` Unicode code point升序，entry精确九键 `kid/private_key_version_ref/public_key_b64url/public_key_fingerprint_sha256/sign_from/sign_until/verify_until/status/revocation_reason`；`kid` 使用本节 JWT header 已冻结的pattern，`private_key_version_ref` 匹配 `^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$`，`public_key_b64url` 是由该 KMS/HSM key version权威导出的32-byte raw Ed25519 public key之43字符canonical unpadded base64url，fingerprint为该32 bytes的64位小写SHA-256，三个时间/status使用本段封闭类型。active/retired 的 `revocation_reason=null`；revoked 时只能为 `expired|suspected_compromise`。首版之后每版恰新增一项active；predecessor中的所有 entry必须全量保留，`kid/private_key_version_ref/public_key_b64url/public_key_fingerprint_sha256/sign_from/sign_until/verify_until` 逐字不变。上一active可在manifest中预声明为reason=null的retired，状态只在该候选current-pin完成CAS时生效；manifest、公钥verifier配置和四角色批准允许提前部署，不得据此提前停止旧signer或开放新 key version 的 sign capability。上一active也可经本次四角色artifact批准以 reason=`suspected_compromise` 变为revoked；上一retired可保持retired，只有当新 manifest.`generated_at >= verify_until` 时可用 reason=`expired` 转revoked，或在任何时刻经本次四角色artifact批准以 reason=`suspected_compromise` 转revoked；上一revoked必须保持revoked且reason逐字不变。新项status=active且reason=null，其 `kid/private_key_version_ref/public_key_fingerprint_sha256` 必须与完整 predecessor链三列全集分别不相交。由此每版仍恰一项active，历史 identity永久不可复用，retired不会因快速连续轮换提前失效，revoked tombstone不得删除或复活。`entries_sha256=SHA-256(RFC8785-JCS(entries))`。manifest raw bytes必须逐字等于整个根对象的 RFC 8785 JCS UTF-8 bytes，无 BOM、前后空白或末尾 LF；raw SHA-256 只由外部 ArtifactRef和第6.2节批准记录承载，不写回根对象。该 Schema 使用 JSON Schema Draft 2020-12、所有对象 `additionalProperties=false`、`required=properties`，禁止 remote `$ref` 和注释；Schema raw identity必须先被第6.1节九角色合同批准共同绑定，实例不得先于合同批准自称 approved。

`private_key_version_ref` 必须是 KMS/HSM 中 fully version-qualified、create-only、不可导出且永不重定向的 key-version identity；alias、`latest`、可移动名称或只到 key container 而未到 immutable version 的地址一律拒绝。manifest、receipt、CAS、sign调用和永久禁用证明中的 ref 必须逐字指向同一精确版本。

status只允许 `active/retired/revoked`。entry三个时间必须finite、UTC整秒且使用精确 `YYYY-MM-DDTHH:MM:SSZ`，满足 `sign_from < sign_until <= verify_until` 与 `verify_until >= sign_until+1830s`。任一 manifest 恰好一个active entry。每个kid的 introduction pin是 predecessor链中首次出现该kid的manifest对应、已CAS激活且唯一的current-pin；retirement pin是后续链中第一次把该kid由active变为retired或revoked的current-pin，未发生时为null。active或retired public key验证时必须满足token.`iat=nbf`、`max(NumericDate(sign_from),NumericDate(introduction_pin.activated_at)) <= iat`，且 `iat < min(NumericDate(sign_until),NumericDate(retirement_pin.activated_at))`（retirement pin为null时只用sign_until）；retired还要求`now < verify_until`。revoked kid在Ed25519验证前立即拒绝。正常轮换中，旧Token只有在其声明 `iat` 严格早于retirement cutoff且仍处原寿命内时继续由public key验证；cutoff及之后的iat一律拒绝，疑似泄漏则revoked并立即拒绝全部该kid Token。任何进入activated predecessor链的新增、轮换、退役或撤销都必须相对当前已激活version创建恰高一号的manifest和全新artifact批准集合，禁止改写旧版本；未激活失败候选只适用第6.2节的同一下一version全新重建规则，不构成已激活版本或跳号依据。

verifier启动只解析active/retired entry的public key，逐项canonical decode为恰32 bytes并复算fingerprint；revoked public key可保留为tombstone但不进入验证key set。KMS/HSM 必须提供受部署信任根认证的 key-version attestation，至少证明 ref、algorithm=`Ed25519`、不可导出、raw public key及fingerprint；逐字不符即拒绝。`finaudit_auth_token_verifier` 及普通Backend principal不得拥有任何 private/export/unwrap/sign capability；独立 `finaudit_auth_token_signer` 也永远不得读取、导出或接收 private bytes，只能在 package外 expectation/current-pin 的CAS激活后，对当前active的精确 key version调用 Ed25519 sign capability。签名输入必须是compact JWS 的 ASCII `base64url(header_bytes) + '.' + base64url(payload_bytes)`，返回恰64-byte raw signature；signer在调用前使用同次 PostgreSQL `db_now`生成第3.3节固定claims，并要求 `max(sign_from,pin.activated_at) <= db_now < sign_until`。候选public key与attestation可提前部署，但激活前 KMS/HSM policy必须对所有 runtime、部署和控制面 principal拒绝该版本的sign；切换时predecessor active key version必须被密码学销毁或不可逆永久禁签，任何 principal 都不得恢复sign/export/unwrap能力。只撤销单一principal ACL、可撤销disable、计划稍后删除或仍有可签clone/备份均不构成完成。retired/revoked验证只依赖public material。缺失public key/attestation、decode/hash不符、key可导出、sign capability提前可用、verifier可sign、signer可导出、signer同时可调用两把active key、duplicate kid/ref/public-key/fingerprint或签名长度不等于64 bytes均 fail closed且不得记录private bytes。正常轮换先部署只有public key的新verifier，再由同一受信控制面原子切换pin和sign capability并不可逆禁用旧key；回滚只能创建并批准更高version的新独立key，禁止恢复旧key version、旧pin或revoked tombstone。

### 3.4 AUTHSEC-D-004：Refresh family、旋转和重放

Refresh Token 是 opaque string：32 CSPRNG bytes，RFC 4648 URL-safe base64 无 padding编码为恰 43 字符，再加前缀 `rft_`，总长恰 47；服务端仅保存 `SHA-256(UTF8(full_token))` 的 64 位小写 hex，并使用 constant-time digest comparison。Token 只在 login/refresh 成功响应中返回一次。

普通 family 的绝对寿命为初次 `issued_at+604800s`；`remember_me=true` 为 `issued_at+2592000s`。旋转不延长 family expiry；所有 child 逐字继承 root 的 `expires_at/remember_me/user_id/auth_epoch/family_id`。

#### 3.4.1 `token_sessions` 增量字段

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `family_id` | UUID | NOT NULL；root 等于自身 `id` |
| `parent_session_id` | UUID | nullable self FK；root 为 NULL，child 非 NULL且唯一 |
| `replaced_by_session_id` | UUID | nullable self FK且唯一；仅 rotated row 非 NULL |
| `rotation_counter` | INTEGER | NOT NULL、`>=0`；root 为 0、child=parent+1 |
| `remember_me` | BOOLEAN | NOT NULL；family 内不可变 |
| `auth_epoch` | TIMESTAMPTZ | NOT NULL；签发时复制 `users.token_invalid_before`，family 内不可变 |
| `reuse_detected_at` | TIMESTAMPTZ | nullable；只允许已 rotated row 首次检测重放时写入 |

`revoke_reason` 封闭为 `rotated/logout/reuse_detected/user_disabled/password_changed/password_reset/admin_revoked`。`revoked_at` 与 reason 同空同非空；active row 的 `replaced_by_session_id/reuse_detected_at` 必须为空；`replaced_by_session_id` 非空当且仅当 reason=`rotated`；`reuse_detected_at` 非空只允许 reason=`rotated` 且不得早于 `revoked_at`。

唯一约束固定为现有 token hash唯一，加 `UNIQUE(family_id,rotation_counter)`、partial unique active family、partial unique non-null parent、partial unique non-null replaced-by。两个 self FK 分别为：`parent_session_id` immediate FK、`replaced_by_session_id` `DEFERRABLE INITIALLY DEFERRED` FK。DEFERRABLE constraint trigger 必须在提交时验证 parent/child 同 user/family/auth_epoch/remember/expiry、counter 连续、parent `rotated` 且双向指针一致。

`family_id/user_id/auth_epoch/remember_me/expires_at/parent_session_id/rotation_counter/refresh_token_hash/issued_at` 创建后不可变且任何 runtime `DELETE` 被 trigger拒绝。`revoked_at/revoke_reason` 只允许同事务从双 NULL 写为一次非空合法 pair，之后不可改；`replaced_by_session_id` 只允许在该 `rotated` 转换中从 NULL 写为预生成 child UUID，之后不可改；`reuse_detected_at` 只允许 NULL→db_now 一次；`last_seen_at` 只允许 active row 按非递减数据库时间前移且不得超过 db_now。P0 不清理 family 历史；任何 retention/delete 需要新 CR。

#### 3.4.2 刷新事务和错误

family-only mutation 的唯一锁序为：先 `SELECT ... FOR UPDATE` 锁 user row，再按 UUID 升序锁定所有目标 family 的 `id=family_id` root rows，最后重读并 CAS 验证 tail；refresh、replay、logout、password change、password reset和独立 admin revoke不得使用其他顺序。AUTH-006 或其他同时改变 `users.status/user_roles` 的请求必须先完整执行 CR-003 的锁序前缀：`user_roles SHARE ROW EXCLUSIVE` 表锁 -> 受影响 user/role/user_roles 行按 UUID 升序；取得目标 user row 后才可继续按 UUID 升序锁 family roots，禁止任何 family 路径反向取得 `user_roles` 表锁。refresh 先按 token hash只读取 candidate user/family identity，再按适用顺序加锁；root 缺失或不满足 `id=family_id/rotation_counter=0/parent_session_id IS NULL` 时 fail closed。禁止以未冻结 hash 函数把 UUID 压缩成 advisory-lock key。

family tail 定义为同 family 最大 `rotation_counter` 的唯一 row。任何判断先检查 root/tail/绝对 expiry：`db_now >= root.expires_at` 返回 `AUTH_REFRESH_EXPIRED`；tail 已以 `logout/user_disabled/password_changed/password_reset/admin_revoked` 终止时返回 `AUTH_TOKEN_REVOKED`；tail 已以 `reuse_detected` 终止时返回 `AUTH_REUSE_DETECTED` 但不产生新撤销或新 operation-log side effect。只有存在未过期唯一 active tail，且提交的是其 rotated ancestor，才进入首次 replay 分支。

| 条件 | 效果 | 返回 |
| --- | --- | --- |
| 格式错误、hash 不存在、用户/组织不可用或 auth_epoch 漂移 | 无状态变化 | `401 AUTH_TOKEN_REVOKED` |
| `db_now >= root.expires_at` | 无状态变化 | `401 AUTH_REFRESH_EXPIRED` |
| 未过期 tail 已以 `logout/user_disabled/password_changed/password_reset/admin_revoked` 终止 | 无状态变化 | `401 AUTH_TOKEN_REVOKED` |
| 未过期 tail 已以 `reuse_detected` 终止 | 无新状态、无新 revoke action | `401 AUTH_REUSE_DETECTED` |
| current active tail 但 `root.expires_at-db_now <= 1830s` | 无状态变化；不签发寿命短于固定 Access Profile 的 Token | `401 AUTH_REFRESH_EXPIRED` |
| current active tail 且全部门禁通过 | 预生成 child UUID；先 CAS update parent为 `rotated/revoked_at/replaced_by=child_id`，释放 partial-active 条件，再 insert child；写 `auth.token.refresh` | 200 与新 Access/Refresh/session_id |
| rotated ancestor + 未过期 active tail + ancestor.`reuse_detected_at IS NULL` | 设置 ancestor.`reuse_detected_at`；撤销 active tail 为 `reuse_detected`；仅对实际新撤销写 `auth.token.revoke` | `401 AUTH_REUSE_DETECTED` |
| family tail 已 `reuse_detected`，或同 ancestor 已标记且无 active tail | 无新状态、无新 revoke action | `401 AUTH_REUSE_DETECTED` |
| 两个请求并发使用同一 current token | 第一个旋转；第二个锁后进入 replay 分支并撤销第一个返回的 child | 第二个 401；family 必须重新登录 |

rotation、replay 状态和 CR-008 operation log 在同一数据库事务提交；失败不得返回新 Token。不得把 `AUTH_REUSE_DETECTED` 用于 logout、admin、password-change 或过期造成的撤销。

### 3.5 AUTHSEC-D-005：强制换密、错误包络和 logout

#### 3.5.1 强制换密一次性状态

凭据正确且 `force_change_on_login=true` 时不创建 `token_sessions`，不签发 Access/Refresh，并按 CR-008 的 known-policy-denied 分支只产生 `auth.login.denied`；只有普通 session成功提交才产生 `auth.login.success`。签发 password-change JWT 前，在 Redis 以 `SHA-256(jti)` 建 create-only 记录，精确包含 `user_id/auth_epoch_us/issued_at/expires_at/consumed=false`，TTL 300 秒；已存在、Redis 不可用或 TTL 不符则 fail closed。

API AUTH-010 顺序固定：按 trusted-proxy Profile取得可信 client IP并执行验签前 IP bucket -> 验签/claims/time -> 读取且核对未消费 Redis record -> 对已认证 jti执行第二个 bucket -> 读取用户 snapshot并验证 current password、新密码 Profile及新密码不等于当前临时密码 -> 开启PG事务并按 user→family root 顺序加锁 -> 重验用户、auth_epoch、password hash/current password和新密码上下文 -> 在持锁状态原子 CAS `consumed=false -> true` -> 提交密码/family/audit事务。CAS 前任何凭据或policy失败不得消费 Token；CAS 失败、过期或字段不符返回 `AUTH_PASSWORD_CHANGE_TOKEN_INVALID`。只有 CAS 后数据库事务失败时 Token保持已消费，用户必须重新登录获取新 Token。

AUTH-010 限流使用同一 Redis/Lua安全属性但独立窗口：可信 client IP每300秒最多20次，且必须在解析 header/payload或执行 Ed25519签名验证前计数；只有固定 header/claims/signature/time 全部有效后才建立 `jti_digest=SHA-256(UTF8(canonical_jti))` 并执行每300秒最多5次的 jti bucket。两类 key TTL均600秒；服务端每次 HTTP attempt生成新 `rate_event_id`，IP已超限直接返回其 `429 RATE_LIMITED/Retry-After`，不得继续做 JWT 工作；IP通过而 jti超限时返回 jti等待值。无效/畸形 JWT仍消耗 IP 配额但不创建任意 jti key，禁止从未认证 token构造 Redis key。

AUTH-010 仍须验证当前临时密码、新密码 Profile、用户/组织状态与 auth_epoch；成功事务更新 PHC hash、`password_changed_at/token_invalid_before`，清除门禁和锁定计数，撤销全部 family 为 `password_changed`，并写既有审计动作。`token_invalid_before` 使用第 3.8.1 节的单调 auth-epoch 推进公式，不得直接赋同一微秒的 db_now。不得在密码事务提交前返回成功。

#### 3.5.2 唯一 `error.data` 例外

一般错误根精确五键 `code/message/details/trace_id/timestamp`，不得含 `data`。唯一例外 `403 AUTH_PASSWORD_CHANGE_REQUIRED` 根精确六键，在一般五键上增加 `data`；`details=[]`，`data` 精确二键 `password_change_token/expires_in` 且 `expires_in=300`。Token 不得重复出现在 message/details/header/URL/log。

临时锁定产生的 `AUTH_ACCOUNT_LOCKED` 与所有 `RATE_LIMITED` 使用标准 `Retry-After` 整数秒 header；人工无限锁定的 `AUTH_ACCOUNT_LOCKED` 不含该 header。body 不增加自由字段。任何验证库异常、畸形 Token、unknown kid、signature/issuer/audience/type/claim 失败统一映射为批准的认证错误，不返回库消息或 stack。

#### 3.5.3 Logout 矩阵

正常授权先验证 JWT signature、claims、用户、组织与 auth_epoch。body 省略 refresh 时 target family 为 Access `sid` 所属 family；body 提供 token 时必须解析为同一用户的任一历史 session，其 family 为 target。未知、畸形或外用户 refresh 返回 `401 AUTH_TOKEN_REVOKED`，不得泄露归属。

active Access 按 user→root统一锁序可处理自己的任一 family。锁后仅当 `db_now < root.expires_at` 且 tail 原为 `revoked_at IS NULL` 时，tail 才是可用 active session并首次写 `logout/revoked_at`；同事务写 `auth.logout`，其 `resource_type='token_session'`、`resource_id=该tail.id`，返回 204。若 target 不是 Access 自身 family，只有上述写入实际使一条原可用 session首次失效时才按 CR-008 产生 conditional `auth.token.revoke`，其 target user/resource语义逐字复用 CR-008。未撤销但已绝对过期的 target 不改状态、返回204并只写本次 `auth.logout` 请求审计，不得声称 `auth.token.revoke`；目标已因 `logout` 撤销时同样返回204且不重复状态效果。合法重复请求仍按 CR-008 产生或复用恰一条以同一 terminal/expired tail id 标识的 `auth.logout` 请求审计。因其他原因撤销时返回401。

唯一 revoked-Access 特例：Access signature、time、用户与 auth_epoch 仍有效，且 `sid` 指向的 session row 本身就是该 family 唯一最大 `rotation_counter` terminal tail、其 `revoke_reason='logout'` 且 `replaced_by_session_id IS NULL` 时，仅允许 body 省略或指向同一 family，直接返回 204；rotated ancestor 的 sid 即使后续 tail 已 logout 也不满足本特例。不得用该 Token 撤销其他 family或访问其他 API。expired、tampered、unknown-kid、用户 disabled/deleted、auth_epoch 漂移、family 因 replay/password/admin 等原因撤销均返回 401。该特例只关闭“同一 revoked logout Token重复 logout 必须204”与“撤销 Token必须401”的冲突，不扩大 bearer 权限。

### 3.6 AUTHSEC-D-006：P0 permission dictionary

`permission_profile_version='p0-permissions-v1'`。code 必须匹配 `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$`；禁止 wildcard、负权限、环境自定义 code 和自定义 role。以下 35 项是完整集合，角色缩写只用于本表：

| Permission code | SA | FIN | AUD | CON | RO |
| --- | :---: | :---: | :---: | :---: | :---: |
| `audit:complete` |  | ✓ | ✓ |  |  |
| `audit:execute` |  | ✓ |  |  |  |
| `audit:return_correction` |  |  | ✓ |  |  |
| `audit:review_high` |  |  | ✓ |  |  |
| `audit:review_non_high` |  | ✓ | ✓ |  |  |
| `audit:submit_high` |  | ✓ |  |  |  |
| `audit:view` |  | ✓ | ✓ | ✓ | ✓ |
| `break_glass:manage` | ✓ |  |  |  |  |
| `break_glass:view` | ✓ |  | ✓ |  |  |
| `contract_links:confirm` |  | ✓ |  |  |  |
| `contract_links:suggest` |  | ✓ |  | ✓ |  |
| `contract_links:view` |  | ✓ | ✓ | ✓ |  |
| `contracts:update` |  | ✓ |  | ✓ |  |
| `contracts:view` |  | ✓ | ✓ | ✓ | ✓ |
| `evaluations:export` | ✓ |  | ✓ |  |  |
| `evaluations:manage_business` |  |  | ✓ |  |  |
| `evaluations:view` | ✓ | ✓ | ✓ | ✓ |  |
| `files:download` | ✓ | ✓ | ✓ | ✓ |  |
| `files:maintain` | ✓ | ✓ | ✓ | ✓ |  |
| `files:upload` | ✓ | ✓ | ✓ | ✓ |  |
| `files:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `invoices:update` |  | ✓ |  |  |  |
| `invoices:view` |  | ✓ | ✓ | ✓ | ✓ |
| `knowledge:manage_technical` | ✓ |  |  |  |  |
| `knowledge:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `operation_logs:view` | ✓ |  | ✓ |  |  |
| `operations:manage` | ✓ |  |  |  |  |
| `policies:manage_business` |  |  | ✓ |  |  |
| `policies:manage_technical` | ✓ |  |  |  |  |
| `qa:query` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reports:export` |  | ✓ | ✓ |  |  |
| `reports:generate` |  | ✓ | ✓ |  |  |
| `reports:view` |  | ✓ | ✓ | ✓ | ✓ |
| `retrieval:debug` | ✓ | ✓ | ✓ | ✓ |  |
| `users:manage` | ✓ |  |  |  |  |

SA=`system_admin`、FIN=`finance_reviewer`、AUD=`audit_reviewer`、CON=`contract_admin`、RO=`read_only`。每个角色数组和 `/auth/me.permissions` 输出均按 Unicode code point 排序、去重；多角色取并集。有效角色只能来自 PostgreSQL 当前有效长期 assignment，或 CR-003 约束下已批准、生效、未过期、未撤销的 break-glass assignment。未知/禁用 role、缺映射或未知 code 一律 fail closed。

permission 是 UI capability hint，不是资源授权事实。后端每次请求仍按“有效用户和 session -> 当前角色 -> capability -> organization/data scope -> resource ownership -> object state/version -> SoD -> action+audit”校验；不得信任 JWT、Redis、Qdrant、header、body 或前端缓存提交的 role/permission。

以下已知漂移按 fail-closed 处理：POL-009/010 未闭合的双角色阶段不得仅凭 policy code开放破坏性按钮；SA 不获得报告正文权限，只用 `operations:manage` 看技术元数据；FIN/CON 不直接调用仅 SA/AUD 的 OPS-004，业务时间线由资源接口裁剪；缺失评测 dataset/case GET 不由 permission code 虚构；CON 的 `reports:view` 只允许后端返回的授权摘要，不暗示完整预览。

capability consumer 的机器表达式只允许四种封闭形态：`NONE`、`ONE(code)`、`ANY(code1,code2)`、`CONDITIONAL(rule_id)`；`ANY` 的 code 按 Unicode code point 排序且只要一个成立，`CONDITIONAL` 只能使用本段具名规则，未知形态或参数一律拒绝。下表 125 个 identity 互斥且行内按 code point 排序：当前 source baseline 恰激活其中 122 项；仅当 CR-005 已批准、授权同步并进入 aggregate lineage 时激活 `PARSE-006`，仅当 CR-009 满足相同三项门禁时激活 `CHUNK-008/CHUNK-009`。materialized active consumer set 必须逐字等于 aggregate effective API set；任一 active identity 命中零行/多行，或未激活 prospective identity 出现在路由/UI/API manifest 中，均使 Profile 无效。声明 prospective consumer 不新增 path，所以本 CR 的 `api_path_delta` 仍为 0。

| Capability expression | Exact API identities |
| --- | --- |
| `NONE` | `AUTH-001,AUTH-002,AUTH-003,AUTH-004,AUTH-010,OPS-001,OPS-002,OPS-006` |
| `ONE(users:manage)` | `AUTH-005,AUTH-006,AUTH-007,AUTH-008,AUTH-009` |
| `ONE(break_glass:manage)` | `AUTH-011,AUTH-013,AUTH-014,AUTH-015` |
| `ONE(break_glass:view)` | `AUTH-012` |
| `ONE(files:download)` | `FILE-008,MD-007` |
| `ONE(files:maintain)` | `FILE-006,MD-001,MD-004,MD-006,PARSE-004,PARSE-005` |
| `ANY(files:maintain,operations:manage)` | `FILE-007` |
| `ONE(files:upload)` | `FILE-001,FILE-002` |
| `ONE(files:view)` | `FILE-003,FILE-004,FILE-005,MD-002,MD-003,MD-005,MD-008,PARSE-001,PARSE-002,PARSE-003` |
| `ONE(contracts:update)` | `CON-002,CON-004,CON-005,CON-006,CON-007,SAGR-001,SAGR-003,SAGR-004,SUPP-003` |
| `ONE(contracts:view)` | `CON-001,CON-003,SAGR-002,SUPP-002` |
| `ONE(invoices:update)` | `INV-002,INV-004,INV-005` |
| `ANY(invoices:update,operations:manage)` | `INV-006` |
| `ONE(invoices:view)` | `INV-001,INV-003` |
| `ONE(contract_links:confirm)` | `LINK-003` |
| `ONE(contract_links:suggest)` | `LINK-002` |
| `ONE(contract_links:view)` | `LINK-001,SUPP-001` |
| `CONDITIONAL(link_cancel_v1)` | `LINK-004` |
| `ONE(knowledge:manage_technical)` | `CHUNK-001,CHUNK-002,CHUNK-003,CHUNK-006,CHUNK-008,CHUNK-009,EVAL-005,INDEX-002,INDEX-004,INDEX-005,KB-002,KB-004` |
| `ONE(knowledge:view)` | `CHUNK-004,CHUNK-005,CHUNK-007,INDEX-001,INDEX-003,KB-001,KB-003,POL-001,POL-003` |
| `ONE(policies:manage_business)` | `POL-004,POL-005,POL-006,POL-007` |
| `ANY(policies:manage_business,policies:manage_technical)` | `POL-002` |
| `ONE(policies:manage_technical)` | `POL-008` |
| `CONDITIONAL(policy_dual_phase_unavailable_v1)` | `POL-009,POL-010` |
| `ONE(retrieval:debug)` | `RET-001` |
| `ONE(evaluations:export)` | `EVAL-007` |
| `ONE(evaluations:manage_business)` | `EVAL-001,EVAL-002,EVAL-003,EVAL-004` |
| `ONE(evaluations:view)` | `EVAL-006,EVAL-008` |
| `ONE(qa:query)` | `QA-001,QA-002` |
| `ONE(audit:execute)` | `AUDIT-002,AUDIT-004,AUDIT-005,AUDIT-008` |
| `ANY(audit:execute,operations:manage)` | `AUDIT-007` |
| `ONE(audit:view)` | `AUDIT-001,AUDIT-003,AUDIT-006,RISK-001,RULE-002` |
| `ANY(audit:view,operations:manage)` | `RULE-001` |
| `CONDITIONAL(risk_review_level_v1)` | `RISK-002` |
| `ONE(audit:submit_high)` | `REVIEW-001` |
| `ONE(audit:return_correction)` | `REVIEW-002` |
| `ONE(audit:complete)` | `REVIEW-003` |
| `ONE(reports:export)` | `EXPORT-001` |
| `ONE(reports:generate)` | `REPORT-001` |
| `ONE(reports:view)` | `REPORT-002,REPORT-003` |
| `ONE(operations:manage)` | `PARSE-006` |
| `CONDITIONAL(ops_dependency_health_v1)` | `OPS-003` |
| `ONE(operation_logs:view)` | `OPS-004,OPS-005` |

`NONE` 不表示公开：AUTH-001 是匿名登录；AUTH-002/003/004 是当前 session；AUTH-010 是受限 `password:change` purpose；OPS-001 使用创建人/资源关系；OPS-002/006 使用独立探针或机器身份。四条 conditional rule 固定为：

- `link_cancel_v1`：未确认关系要求 `contract_links:suggest` 并继续校验“本人建议/业务范围”；已确认关系要求 `contract_links:confirm`；状态未知拒绝。
- `risk_review_level_v1`：锁后权威 `effective_risk_level='high'` 要求 `audit:review_high`，其余 `notice/low/medium` 要求 `audit:review_non_high`；未知等级拒绝。
- `policy_dual_phase_unavailable_v1`：POL-009/010 在 Request 尚未冻结业务发起与技术落地的分阶段 payload/state/CAS 前恒为拒绝；不得用同时拥有两个 permission、前端隐藏或单请求角色叠加绕过。后续 successor 必须提升 Profile version并替换此 sentinel，不能原地解释。
- `ops_dependency_health_v1`：交互式用户调用要求 `operations:manage`；非用户调用只允许部署合同已批准、可认证且网络来源受限的内部 health-probe machine identity，并继续执行其独立传输/来源门禁。两类同时不成立或身份不可区分时拒绝。

所有会发起 API 的 UI action 必须携带其唯一 API identity，并只用该行表达式控制可见/可用提示；UI action 不得另建 permission映射或把 capability 当最终授权。无 API 的本地导航/展示不产生授权能力。Backend 仍按第 3.6 节资源、组织、状态、SoD和审计链复验；测试必须分别从 source baseline manifest 解析 122 项、从完成第 2.3 节 lineage 的 aggregate manifest 解析 125 项，与相应 activated consumer set 做集合等式、零重复和每个 conditional predicate的正反向量。

### 3.7 AUTHSEC-D-007：浏览器令牌保管

P0 不引入 cookie/CSRF 新合同。Access、Refresh、password-change Token 只可保存在当前前端 JavaScript 进程内存；禁止 LocalStorage、SessionStorage、IndexedDB、Cookie、URL、DOM attribute、持久化 Pinia、Service Worker cache、日志、analytics 和错误上报。前端只以 `Authorization: Bearer` 发送 Access，并在 refresh/logout JSON body 中按 API 合同发送当前 Refresh。

任何响应 body/header 只要包含 Access、Refresh或password-change Token（至少 API AUTH-001/002 的成功响应和 `AUTH_PASSWORD_CHANGE_REQUIRED`）都必须同时发送 `Cache-Control: no-store` 与 `Pragma: no-cache`，不得发送可复用的 `ETag/Last-Modified`。Backend负责原始 header，Nginx 对这些路由必须 `proxy_cache off` 并保留/强制 no-store，浏览器、Service Worker、反向代理和中间缓存都不得落盘或重放；任何一层配置无法证明时 AUTH runtime保持关闭。

刷新页面、关闭 tab、进程重启或内存状态丢失后必须清理 user/roles/permissions 并返回登录页；不得只凭持久化 user object恢复登录。`remember_me` 只选择服务端 family 的 30 天绝对寿命，不承诺浏览器重启/刷新后的自动登录；UI 文案必须说明该限制。普通值为 7 天。

Access 到期前只允许单飞一次 refresh；并发请求等待同一结果。refresh 成功原子替换内存中的两个 Token；失败、reuse、logout、401、强制换密或用户禁用立即先清内存再导航登录。完整 Token 不进入浏览器 console、测试 snapshot 或 telemetry。CSP、输出编码和依赖安全仍是 XSS 防线，本条不把内存 Token描述为免受 XSS。

### 3.8 AUTHSEC-D-008：迁移、配置、回滚和运行边界

#### 3.8.1 单一 migration ownership

CR-013 只拥有一个线性 Alembic revision，实际 `migration_file/revision/down_revision` 必须在所有上游 migration 稳定且执行前绑定；review snapshot 不预填伪造值。upgrade 只修改既有 `users/token_sessions`：在 `token_sessions` 增加第 3.4.1 节七列、四个新 unique/index、两个 self FK、CHECK、不可变/一致性 trigger/function与必要 ACL；在 `users` 增加三个精确命名 CHECK：`ck_users_username_auth_canonical_v1`（第 3.2.2 节 regex）、`ck_users_lock_state_auth_v1`（`locked_until IS NULL OR status='locked'`）和 `ck_users_auth_epoch_json_safe_v1`（`isfinite(token_invalid_before) AND floor(extract(epoch from token_invalid_before)*1000000) BETWEEN 0 AND 9007199254740991`）。revision-owned object、函数签名、trigger、constraint与index必须在实施 artifact 中逐项 allowlist，不得包含第三张表。

upgrade preflight 在任何 DDL 前以受控停写窗口按 `users -> token_sessions` 取得 `ACCESS EXCLUSIVE` 锁，并要求 `token_sessions` 行数恰为 0；非空整体失败，禁止猜测 legacy `remember_me/auth_epoch/family` 或重新承认旧 Refresh Token。对 `users` 逐行验证 username 已 canonical且无投影碰撞、`status/failed_login_count/locked_until` 满足第 3.2.1 节、`token_invalid_before` finite且其微秒投影落在非负 JSON-safe范围；任一失败均在首个 DDL 前退出，不自动改写 `+infinity/-infinity` 或越界 epoch。因 session 表为空，七列直接以最终 nullability/约束创建，不执行 legacy session 回填；禁止创建账号、密码、Token、role、operation log或默认 secret。

AUTH-006 的状态投影固定为同一 CR-003 wrapper事务：目标 `locked` 表示人工锁，写 `status='locked'/locked_until=NULL/failed_login_count=0`并推进 auth epoch，撤销 active family 为 `admin_revoked`；目标 `disabled` 写 `status='disabled'/locked_until=NULL/failed_login_count=0`并推进 auth epoch，撤销 active family 为 `user_disabled`；从 `locked/disabled` 恢复 `active` 写 `status='active'/locked_until=NULL/failed_login_count=0`并推进 auth epoch，不得复活任何旧 family。auth epoch 的新值一律为 `GREATEST(db_now, old_token_invalid_before + interval '1 microsecond')`，其中 db_now 是持锁后同一事务捕获的 PostgreSQL时间；结果还必须通过 `ck_users_auth_epoch_json_safe_v1`，否则整个事务回滚。AUTH-009 reset、AUTH-010 change及任何 password/admin/session全量失效路径逐字复用该公式和 CHECK。状态未变只修改显示名/角色时不得伪造状态 transition或推进 epoch。状态、committed role set delta、family revoke及 CR-008 的 `user.enable/user.disable/auth.account.lock/user.role.revoke/user.role.assign/auth.token.revoke` conditional emissions 按 CR-008 successor固定 order 10/20/30/40原子提交；`auth.account.lock` 复用既有 action，`operation_log_action_delta` 仍为0。

role替换锁后以旧/新有效code集合计算 `set_removed=old-new`、`set_added=new-old`；两数组分别按Unicode code point排序且互斥。每个 removed code恰发一条 `user.role.revoke`（order20），每个 added code恰发一条 `user.role.assign`（order30），身份/resource/idempotency逐字复用CR-008；空集合不发对应action，两集合皆空不得伪造role审计。任一 operation-log append失败必须回滚role/status/session全部效果。

downgrade 只在 `token_sessions` 空表时允许；先删除本 revision triggers，再 functions、三个 users CHECK、token_sessions FK/index/CHECK、columns，严格逆序且禁止 `CASCADE`。username 和 auth epoch没有被本 revision自动改写，因此无需也禁止数据反向转换。非空时必须在任何 DDL 前失败；不得丢失 family/replay 证据。revision-owned object 使用精确 allowlist 和 catalog 验收，外部对象只读预检，不改变 owner/ACL。

#### 3.8.2 配置与 secret

非秘密配置必须显式绑定 Profile version、issuer/audience、TTL、leeway、Argon2 参数、blocklist ref/hash、rate limits、trusted proxy CIDR、keyring manifest ref/hash、current-pin ref/hash、immutable sign-policy ref/hash、package-external expectation ref/hash、private-transition receipt ref/hash和 runtime-binding ref/hash；启动时逐项与本文常量、provider当前attestation及包外受信输入比较，漂移即失败。`secret_key` 单值和现有默认 TTL 只能视为待迁移配置，不能证明本 Profile 已实现。

JWT Ed25519 private material必须始终留在满足第3.3节封闭能力且由部署信任根认证的不可导出 KMS/HSM key version内；应用只配置非秘密的 version-qualified ref，并用独立、最小权限的工作负载身份调用 sign，不配置或接收seed/private bytes。KMS/HSM认证凭据、rate-limit HMAC key 和任何 bootstrap/password 输入只来自 Secret Manager、工作负载身份、TTY/stdin 或受限 FD；不得进入 argv、镜像、migration、仓库、Request、`.env.example` 值、日志或 approval record。public key、fingerprint和不可移动key-version ref可以进入已批准manifest；配置校验只报告ref和错误类别，不回显凭据或private material。

#### 3.8.3 事务与 runtime gate

- login success 的 session、rehash/reset 和 operation log同事务；失败计数/锁定与安全审计按 CR-008 原子边界提交。
- refresh rotation/replay family revoke、logout、password change family revoke与对应 operation log同事务。
- operation-log 写失败必须回滚同一认证状态效果；未知账号和 rate-limit 只写脱敏 security log。
- Request 未同步、CR-003/006/008 successor 未批准、migration 未演练、blocklist/keyring/profile 未绑定或 PostgreSQL/Redis门禁未通过时，API AUTH runtime必须保持关闭。

## 4. API 兼容性与错误优先级

### 4.1 保持的响应和行为

- API path 数不变；login/refresh 仍返回 JSON Access+Refresh，logout 仍为 204，me 仍返回当前用户、roles、permissions。
- `expires_in=1800`；Refresh response 的 `session_id` 为新 child row id。
- `/auth/me` 每次从 PostgreSQL计算有效角色及 permission并集，不返回敏感列。
- Access/Refresh/password-change 绝不进入 query string。

### 4.2 同时命中时的确定优先级

login 在限流通过后：输入边界 -> 查找 canonical username；unknown/软删除/organization inactive 只执行 dummy verify并返回通用401；已知用户执行真实verify -> 错误密码统一401（即使本次内部达到阈值并提交lock）-> 密码正确后依次判断 disabled、locked、force-change、普通 session。只有正确密码命中既有锁时返回423，因此错误密码不泄露账号存在或本次锁定状态。

Access API：header/格式 -> fixed alg/kid/signature/type/claims/time -> user/organization/auth_epoch -> session/family -> role/resource。失败使用最具体已批准 code，但不得返回验证库细节。

refresh：格式/hash -> user/organization/auth_epoch -> root absolute expiry -> tail terminal reason -> current/replay。logout 只在第 3.5.3 节精确特例放宽 session-revoked 检查。

## 5. 验收与固定负向量

### 5.1 单元与跨实现

至少覆盖：NFC/空白/15、128、129 codepoints及512/513 bytes；blocklist source十三键const/raw/license、99839行、四个产品名、六个固定弱口令、generator receipt、hash、去重和上下文命中；username canonical/non-ASCII/碰撞；Argon2 PHC参数、随机salt、rehash、dummy等成本；JWT canonical compact三段、64-byte Ed25519 signature、EdDSA-only/algorithm confusion、header/payload任意重复member（至少 `alg/kid/sub/sid/iat` 的前值与后值互换两向量）、unknown kid、issuer/audience/type/purpose、额外claim、整秒key window；keyring Schema/root九键、九键entry/public-key raw与fingerprint/non-exportable key-version隔离、JCS/raw identity、predecessor全链、entry排序/唯一性、正常轮换retirement cutoff与旧Token继续验证、revoked立即拒绝、到verify_until后expired撤销、四角色批准的suspected-compromise撤销、两个record-set digest、current-pin strict-time CAS、十四键immutable sign-policy、八键package外 expectation、二十五键private transition receipt、durable monotonic floor、runtime binding、verifier无private/sign访问/新key预激活不可sign或export/激活后仅精确signer可sign/predecessor精确key version不可逆禁签且全principal不可恢复、CAS同时额外grant/CAS后policy漂移/provider snapshot不原子/同前驱同version候选竞争恰一成功/错过预定秒进入`missed_deny`且原候选永不激活/失败后全新同下一version候选/同版异hash/版本回退/跨环境替换/删tombstone/revoked复活/duplicate kid-key-version-public-key-fingerprint负向量、时间和 auth_epoch 微秒边界；Refresh 47字符格式/hash、7/30天绝对expiry、family继承和 constant-time comparison；35 code与五角色精确集合、122 baseline/125 aggregate API consumer集合等式、三项 prospective activation/拒绝、排序、union、四个 conditional rule和unknown fail-closed。

### 5.2 PostgreSQL 16 集成和并发

在 disposable PostgreSQL 16 实例执行真实 upgrade/downgrade：非空 `token_sessions` 在首个 DDL 前拒绝；canonical users + 空 session表的约束/trigger/ACL/catalog；non-canonical username、锁状态坏行、`+infinity/-infinity`、负数或超 JSON-safe auth epoch均 fail closed；非空 downgrade DDL 前拒绝；空表往返无残留。并发覆盖第4/5次失败、临时锁到期与 AUTH-006 竞争且证明普通 user lock整体回滚后才按 wrapper重入、rehash 与 reset竞争、两个 refresh恰一先成功且随后全族撤销、logout与refresh、AUTH-006 disable/password-change与refresh、CR-003 table-lock→user→family-root总顺序、同 family active partial unique；验证 AUTH-006三种状态投影、同一微秒 auth epoch仍恰推进1微秒、最大安全边界+1回滚和 operation-log rollback。

### 5.3 API、前端和安全

覆盖 unknown/disabled/locked 的不泄露矩阵、临时/人工锁 Retry-After差异、服务端唯一 rate_event_id、双 bucket最大等待、TTL与 Redis fail-closed、强制换密六键错误和其他错误无 data、AUTH-010验签前IP限流/验签后jti限流及畸形JWT不建key、一次性 Token预检/CAS/过期/重放/数据库失败后已消费、logout revoked-only特例仅允许sid自身terminal tail、rotated ancestor拒绝、expired other-family只审计不改reason/不发revoke、过期优先于 terminal reason、首次/重复 replay、角色变更下一请求可见、跨组织/IDOR/SoD、operation log原子回滚与全链路脱敏。

前端测试必须证明普通/受限 Token未写入任何持久化媒介，reload要求重新登录，refresh single-flight，失败先清理再跳转；Backend/Nginx/header测试覆盖全部token-bearing成功/错误响应的`no-store/no-cache`与无validator，真实浏览器E2E证明HTTP cache、Service Worker和disk cache无Token且不得输出真实Token。构建、Mock、SQLite、ORM unit或静态类型检查不能替代PostgreSQL16、Redis原子脚本和真实浏览器验收。

### 5.4 未授权验证

当前不得运行 Provider、Qdrant网络、production、canary或部署；这些也不是 AUTH contract验收条件。Docker/PostgreSQL/浏览器环境不可用时必须记 `NOT_RUN`，不得以离线测试冒充。

## 6. 审批责任与 successor 治理

### 6.1 九角色批准

必需角色按固定顺序为 `requirements_product/architecture/data_dba/backend_api/frontend_ui/ai_rag/ops/security/test`。当前 shared v1 不能表示 CR-013，因此本 review snapshot 生成后仍不得产生可计入批准的 standalone record；人工备注、聊天批准或无 Schema 签名均只作外部输入，不是机器批准。必须先批准第 6.2 节 successor并按第2.3节生成 keyring Schema；该 successor 的 strict JSON Schema、JCS preimage、detached evidence、signer-registry pin、ArtifactRef、role-complete set digest和签名时序必须逐字复用 DEP shared contract，仅新增 CR-013 branch。随后一人即使具备全部权限，也必须以 successor 为每个 role 形成独立记录；APPROVED 时 `selected_decisions` 恰为第 2.1 节八项全集，`rejected_decisions=[]`，并共同绑定 `CR-013-R1`、同一 decision snapshot、`source_baseline_manifest_sha256=717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`、`environment_scope=contract`、`network_scope=none`、`production_release_scope=none` 和第 2.2 节 delta。CR-013 contract scope 的 `artifact_bindings` 必须是精确四键 `approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref`；前三键逐字继承 shared `SourceContractArtifactBindings`，第四键是精确二键 `schema_version='auth-keyring-manifest-v1'/schema_sha256`，九条记录逐字相等并绑定实际 Schema raw hash。

拒绝或缺少任一角色、selection 不同、hash 不同、scope 扩大或 artifact/profile 状态不一致时整体不构成批准。合同批准不等于 Request 同步、migration/runtime 或 production 授权。

### 6.2 Shared v1 不兼容

现有 DEP-005 `source-contract-approval-record-v1`、`request-sync-authorization-v1` 及 CR-006/008 lineage 是封闭枚举且不含 CR-013。CR-013-R1 不定义第二套 standalone approval Schema；任何 standalone 人工记录不得自称 shared v1/successor record，也不得进入 joint package。

正式接入必须发布 versioned successor：将 CR-013 九角色、八项 selection、marker 和 `0/0/1/0` delta 纳入 DEP shared schema；Request sync source union新增 CR-013；ordered lineage 在 CR-003 后新增 CR-013；CR-006/008 提升 revision、重算 snapshot和artifact。禁止原地改写已有 review snapshot或 raw Schema。

同一 successor 还必须增加 `approval_scope='auth_keyring_artifact'`，其 decision全集只有 `AUTHKEY-A-001=SCHEMA_AND_MANIFEST_APPROVED`；APPROVED 时 `selected_decisions` 恰为该单项且 `rejected_decisions=[]`，REJECTED 时反之。必需角色按共享九角色顺序过滤后精确为 `backend_api/ops/security/test`，每角色恰一条；`environment_scope` 恰一项且 `environment_id/environment_class` 与 manifest逐字相等，`network_scope=none`、`production_release_scope=none`。四条记录的 `artifact_bindings` 精确十一键 `approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref/token_profile_version/auth_keyring_manifest_ref/auth_keyring_manifest_sha256/predecessor_current_pin_ref/predecessor_current_pin_sha256/contract_approval_record_refs/contract_approval_record_set_sha256`：前四键必须等于九角色 contract记录中的共同值，`token_profile_version='auth-token-v1'` 且等于 manifest，manifest ref为五键 ArtifactRef且其 `sha256` 等于后续独立hash；contract refs恰含九条已验证、APPROVED、同revision/snapshot的记录，按九角色顺序排列，set digest固定为 `SHA-256(RFC8785-JCS(contract_approval_record_refs))`。首版两个 predecessor pin字段都为null；后续版都非null，ref为五键 ArtifactRef、hash等于ref.`sha256`，并解析为本次激活前的 `auth-keyring-current-pin-v1`。四条 artifact记录的这十一键必须逐字相等，且 artifact批准不得先于其引用的九条 contract批准。

四条 artifact记录完成并各自形成 ArtifactRef 后，按 `backend_api/ops/security/test` 顺序组成 `artifact_approval_record_refs`，其 set digest固定为 `SHA-256(RFC8785-JCS(artifact_approval_record_refs))`；该 refs/digest 不写回四条记录，避免签名环。

`auth-keyring-current-pin-v1` 是在 artifact批准后生成的 create-only JCS制品，根精确十一键 `schema_version/token_profile_version/environment_id/environment_class/pin_generation/keyring_version/manifest_ref/manifest_sha256/artifact_approval_record_refs/artifact_approval_record_set_sha256/activated_at`。schema/profile固定为 `auth-keyring-current-pin-v1/auth-token-v1`；`pin_generation` 为 `1..99999999` 且等于 keyring version数字后缀；manifest、环境、四记录数组和digest逐字等于已验证候选；`activated_at` 为预定的finite UTC整秒且不早于manifest生成和四条批准，新active必须满足 `sign_from <= activated_at < sign_until`。该时刻同时是predecessor active的retirement cutoff和新active的introduction cutoff；manifest/public verifier与KMS/HSM non-exportable attestation可提前准备，但任何状态变化、新key sign capability或Token接受均不得提前。raw bytes恰为根对象RFC8785 JCS，无BOM/额外空白；其 ArtifactRef/hash不得写回本根。

`auth-keyring-sign-policy-v1` 是 current-pin 生成后、CAS 前确定性派生并安装到 KMS/HSM 的 create-only 制品，根精确十四键 `schema_version/token_profile_version/environment_id/environment_class/policy_version_ref/key_version_ref/current_pin_ref/current_pin_sha256/activated_at/sign_until/sign_allowed_principal_ids/private_material_access/pre_activation_sign/mutability`。schema/profile固定为 `auth-keyring-sign-policy-v1/auth-token-v1`；`current_pin_ref` 是五键 ArtifactRef且 `current_pin_sha256=current_pin_ref.sha256`，解析出的环境与activated_at逐字等于current-pin；`sign_until` 为finite UTC整秒并逐字等于manifest新active entry，必须满足 `activated_at < sign_until`。`policy_version_ref` 与 `key_version_ref` 都匹配 `^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$`，且是fully version-qualified、create-only、永不重定向的provider identity，后者逐字等于manifest新active的 `private_key_version_ref`；`sign_allowed_principal_ids=['finaudit_auth_token_signer']`，`private_material_access='none'`，`pre_activation_sign='deny_all'`，`mutability='immutable'`。数组不得为空、重复或增加任何部署/控制面/verifier principal。raw bytes恰为根对象RFC8785 JCS，无BOM/额外空白；其五键 ArtifactRef与独立SHA-256由transition receipt绑定，不写回本根。KMS/HSM必须由部署信任根认证：该精确key version只能关联这一policy version；activated_at前所有principal均不可sign，`activated_at <= provider_authoritative_time < sign_until` 时只有数组内精确signer可sign，到 `sign_until` 时全部principal硬性DENY；private material永不可访问。`mutability='immutable'` 冻结policy bytes、key attachment、allowlist、两个时间边界和gate predicate；provider另有不进入raw policy的单向状态位，初始 `pending_deny`。仅当第6.2节有效CAS在provider权威时刻逐字等于activated_at原子提交时，状态才从 `pending_deny` 转为 `active` 一次；该时刻没有成功提交这次CAS时，状态必须自动且不可逆转为 `missed_deny`，禁止晚到CAS、重排activated_at或重新启用同一policy/key。`active` 在sign_until自动且不可逆转为 `expired_deny`；`missed_deny/expired_deny` 都是终态且始终对全部principal拒绝sign。除此三个封闭单向转移外，policy不得修改、替换、旁路或追加授权。不能提供这种不可变、唯一关联、时窗硬门禁、错过即终态、单向状态与持续排他保证的provider不符合本Profile，AUTH runtime保持关闭。

package外权威输入 `auth-keyring-deployment-expectation-v1` 根精确八键 `schema_version/environment_id/environment_class/current_pin_ref/current_pin_sha256/minimum_keyring_version/private_transition_receipt_ref/private_transition_receipt_sha256`；schema固定为该version，环境来自部署目标而非包内manifest，`minimum_keyring_version` 为 `0..99999999`。首次激活前 pin与receipt两组ref/hash都为null且floor为0；其余状态两组都非null，ref均为五键 ArtifactRef、hash等于ref.`sha256`，分别解析为同环境 current-pin和下述private transition receipt，floor等于pin generation。该 expectation 的 raw JCS ArtifactRef/hash必须由 JWT keyring之外、已批准且防回滚的部署信任根签名并作为包外输入提供；普通环境变量、仓库文件、包内默认值或当前manifest自报均不构成认证。本文不创建或批准该部署信任根；证据缺失即保持 runtime关闭，production仍需独立放行。

`auth-keyring-private-transition-receipt-v1` 不含private bytes，根精确二十五键 `schema_version/token_profile_version/environment_id/environment_class/keyring_version/current_pin_ref/current_pin_sha256/activated_at/sign_policy_ref/sign_policy_sha256/new_active_kid/new_private_key_version_ref/new_public_key_fingerprint_sha256/predecessor_active_kid/predecessor_private_key_version_ref/signer_principal_id/verifier_principal_id/new_key_pre_activation_sign_denied/new_key_sign_capability_granted/post_activation_sign_exclusive_to_signer/sign_window_provider_enforced/new_key_private_material_non_exportable/sign_policy_immutable/verifier_private_capability_denied/predecessor_sign_capability_irrecoverable`。schema/profile、环境、version、pin、activated_at与候选逐字相等；current-pin与sign-policy ref均为五键 ArtifactRef，两个独立hash分别等于对应ref.`sha256`，sign-policy解析后必须逐字满足上一段十四键根及其与pin/key/principal/sign_until的全部等式；principal固定为 `finaudit_auth_token_signer/finaudit_auth_token_verifier`；new active三字段等于manifest。八个 control 字段都是 JSON boolean，前七项恒为true；首个实际激活候选的 predecessor两个identity都为null且 `predecessor_sign_capability_irrecoverable=false`，已有activated predecessor时两个identity都非null并逐字等于旧active且该布尔恒为true。receipt 本身是 KMS/HSM key-version、immutable sign-policy attachment 与 activation transition 的受信attestation：pre-activation true 表示从key创建至CAS权威时刻前全principal始终Sign=DENY；exclusive true表示有效签名窗内只有精确signer可Sign、其他全部principal持续DENY；sign-window true表示provider自身以权威时钟强制 `[activated_at,sign_until)` 且到界后全principal永久DENY；non-exportable/verifier-denied/immutable分别证明private material从未可访问、verifier无private/sign能力、provider当前且未来均不能修改/替换/旁路该policy；有activated predecessor时末项true表示旧key已密码学销毁或不可逆永久禁签。普通 ACL revoke、mutable IAM、仅应用检查sign_until、scheduled deletion、可撤销 disable、应用进程自报、仍有额外可签principal/clone/备份或未绑定policy ArtifactRef/hash均不得置true。raw bytes恰为RFC8785 JCS；receipt由执行CAS和KMS/HSM policy activation的包外受信控制面在同一原子提交中产生并由同一部署信任根认证，expectation逐字绑定其ArtifactRef/hash。receipt缺失、伪造、延迟补写、字段/attestation/policy等式不符、窗外可签、激活后非signer可签、policy可漂移、旧key仍可签或新key可导出时 runtime fail closed。

激活使用单一 compare-and-swap：首版只允许 expectation 的全null/0状态创建pin1；后续候选的两个 predecessor pin字段必须逐字等于当前 expectation ref/hash，解析后的pin必须指向 manifest.`previous_manifest_ref`，且当前候选通过第3.3节完整 predecessor链验证。控制面必须以旧 expectation ArtifactRef/hash和floor为CAS条件，预检provider当前安装的sign-policy逐字等于派生ArtifactRef/hash且仍处 `pending_deny`，使用finite UTC整秒权威时刻并要求其逐字等于pin.`activated_at`；同一原子切换只激活该immutable policy、只向 `finaudit_auth_token_signer` 开放新active精确KMS/HSM key version的sign capability（其他全部principal持续DENY、private material仍不可导出）、使predecessor active精确key version达到不可逆禁签状态、产生transition receipt，再发布绑定pin/receipt的新签名expectation并把floor推进恰一。竞争失败、时刻不等、policy ref/hash/状态漂移、存在额外可签principal、新key可导出、旧key仍可签或任一key-policy效果不能与CAS由同一receipt证明时，候选不得进入runtime。错过预定秒或CAS失败的候选policy必须已进入或按权威时钟进入 `missed_deny`，其key、manifest、四角色artifact批准、pin和policy均永久封存，任何一项不得重用或激活；由于包外 expectation 与floor未改变，恢复时仍以当前已激活 predecessor N 为依据创建version N+1（首次仍为version1）的全新候选，但必须使用全新的KMS/HSM key version、manifest raw/hash、四角色artifact批准集合、current-pin和sign-policy，并选择新的future activated_at。多个同前驱同version候选只有strict CAS胜者可成为已激活链中该version的唯一hash；其余候选全部终态拒绝，不造成版本跳号。持久floor存于包外防回滚控制面并在本地 durable启动水位取最大值：激活前的候选不构成floor事实；一旦某候选激活，同版本只接受该胜者相同的manifest/pin/policy/receipt hash，低版本一律拒绝；所谓回滚只能相对当前已激活version创建、批准并CAS激活下一version，禁止重新激活任何失败或历史pin、policy、manifest或key version。

Backend只接受派生的 `auth-keyring-runtime-binding-v1` 精确十六键 `schema_version/token_profile_version/environment_id/environment_class/approval_signer_registry_ref/auth_keyring_manifest_schema_ref/auth_keyring_manifest_ref/auth_keyring_manifest_sha256/contract_approval_record_refs/contract_approval_record_set_sha256/artifact_approval_record_refs/artifact_approval_record_set_sha256/current_pin_ref/current_pin_sha256/deployment_expectation_ref/deployment_expectation_sha256`，其中 `schema_version='auth-keyring-runtime-binding-v1'`。current-pin和expectation ref均为五键 ArtifactRef且hash分别等于ref.`sha256`；runtime必须先从包外受信通道取得 expected expectation ref/hash，再逐字比较binding，验证 expectation目标环境等于实际启动环境、pin和private transition receipt都等于expectation、receipt中的sign-policy等于provider当前不可变policy、manifest等于pin、两组record和detached signature等于manifest批准链，并把版本与durable floor比较。verifier只能使用current manifest的active/retired public key；signer永远不能取得private bytes，只能在runtime权威当前时刻 `>= pin.activated_at` 且receipt验证通过后调用当前active key version的sign capability。启动、健康检查以及每次sign前都必须从受信provider取得当前key→policy唯一关联与policy ref/hash/immutable attestation，逐字等于receipt；因policy本身不可变，该检查与紧随其后的sign必须由同一provider authorization snapshot执行，无法提供原子snapshot则拒绝签名。public-key/attestation等式、non-exportable属性、只有精确signer可sign、verifier无private/sign、CAS时刻、pre-activation deny和predecessor key不可逆禁签全部通过后才可健康。任一缺项、额外项、角色/环境/版本/hash不一致、同版异hash、低于floor、激活时刻未到、receipt/policy不符、出现额外可签principal、policy漂移、新key可导出、旧key仍可签或包外expected值不匹配均 fail closed。该 binding只是机器汇总，不是新的批准记录，不授权 production。

### 6.3 Request sync

本修订的 snapshot 或合同批准本身不授权 Request sync；实际授权状态只记录在第 9 节。同步必须由 `requirements_product` 使用 successor 独立签署 source-only授权，绑定 CR revision/marker/snapshot、九角色完整 approved set、同步前 baseline、有效期以及 network/production none；逐文件生成 pre/post hash和 verified changed/unchanged evidence。授权的 `request_paths` 必须按下列 Unicode code point 顺序恰含九项，不得用 glob、目录或别名：

1. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
2. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
5. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
7. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
8. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
9. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`

该授权不能替代九角色批准。aggregate sync 必须按第 2.3 节八 source 顺序逐项形成 lineage；只同步 CR-003/CR-013、standalone直接改 Request或遗漏任一 source都不能称为 aggregate baseline。

## 7. 实施与回滚 Gate

| Gate | 必须满足 |
| --- | --- |
| Contract | CR-013 review snapshot 已生成、九角色同 revision/hash 批准 |
| Governance | shared successor、CR-006/008 successor 和 CR-013 source sync 已批准并完成 |
| Data | CR-003 user-role事实、CR-006/008 operation-log事实已落地；CR-013 migration绑定并经PG16演练 |
| Security | blocklist、keyring Schema/manifest/predecessor链、九角色合同set、四角色artifact set、current-pin/immutable sign-policy/expectation/private-transition receipt/CAS/floor、runtime binding、EdDSA KMS/HSM non-exportable key 与 verifier-public/only-signer-sign-capability 隔离、dummy hash、rate-limit/proxy Profile 已绑定；无 secret 泄漏 |
| Runtime | Backend/Frontend聚焦测试、PG并发、Redis原子脚本、浏览器E2E全部通过 |
| Release | 另行production批准；本合同永不提供production授权 |

任一 Gate失败时不得通过 feature flag、环境变量默认值、Mock、跳过审计或临时表开放 AUTH runtime。回滚优先关闭路由并保留数据；只有空 `token_sessions` 才允许 schema downgrade。

## 8. Decision snapshot 生命周期

review snapshot 的唯一 marker 是将 ASCII bytes `## 9.` 与 UTF-8 bytes ` 当前状态` 拼接所得的完整行；该完整行在全文必须恰好出现一次且无前后空格。

算法固定：读取原始 bytes并拒绝 BOM、非法 UTF-8或替换字符；把 CRLF 和孤立 CR 规范化为 LF，不做 Unicode normalization；定位唯一 marker；取 marker 前全部内容，移除末尾全部 LF后恰好追加一个 LF；编码为无 BOM UTF-8并计算 SHA-256 64位小写hex。不裁剪空格、不重排 Markdown。

只有第1～8节静态复核通过后才可生成首次 snapshot，并只在第9节记录可变 review 状态。第1～8节任一byte变化必须提升 revision、重算并清空旧签名；第9节状态不进入preimage。生成hash只建立可签对象，不是批准、Request sync、migration/runtime、network或production授权。

## 9. 当前状态

| 项目 | 状态 |
| --- | --- |
| CR-013 revision | `CR-013-R1` |
| static contract | `REVIEW SNAPSHOT GENERATED / NOT APPROVED` |
| decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` |
| decision snapshot SHA-256 | `a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8` |
| decision snapshot preimage bytes | `80973` |
| required decisions | `AUTHSEC-D-001..008` |
| approval records | `NONE` |
| password blocklist artifact | `PENDING` |
| keyring Schema / manifest | `PENDING / NOT GENERATED / NOT APPROVED` |
| keyring artifact approval / current pin / immutable sign policy / runtime binding | `NONE / BLOCKS RUNTIME` |
| package-external deployment expectation / private transition receipt / durable floor | `NOT CONFIGURED / BLOCKS RUNTIME` |
| shared source/sync successor | `PENDING GOVERNANCE REVISION` |
| Request sync | `NOT AUTHORIZED` |
| CR-003 / CR-006 / CR-008 dependency | `NOT APPROVED / BLOCKS RUNTIME` |
| migration / Backend / Frontend runtime | `BLOCKED` |
| network scope | `none` |
| fixed_test_provider | `NOT AUTHORIZED` |
| production / canary / deployment | `NOT AUTHORIZED` |
