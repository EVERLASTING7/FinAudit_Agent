# CR-014-R2：AUTH/Oplog current-baseline 审批与协作原子同步 successor

## 1. 身份、目标、权威来源与历史边界

### 1.1 文档身份

| 项目 | candidate 固定值 |
| --- | --- |
| CR / revision | `CR-014 / CR-014-R2` |
| 日期 | `2026-08-11` |
| 状态 | `PROPOSED / NOT APPROVED` |
| ordered sources | 精确为 `[CR-006-R3,CR-013-R2]` |
| current Codex task/thread | `019fee83-e431-7a32-86ea-b1e043e641b8` |
| 唯一审批权威 | 当前 task 中由平台认证为直接用户的 BOSS/YHBX 消息 |
| local canonical receipt | `NON_AUTHORITATIVE_EVIDENCE_ONLY`；单独存在绝不授权 |
| governance delta | `ZERO` |
| combined source semantic delta | `NONZERO` |
| source lineage 身份 | `none`；本 CR 永不成为 Request source |

本 revision 只协调两个 source 的共同审批、CR-013 password-blocklist A2、expected-post/inverse bundle、BOSS joint authorization 与十一文件 cooperative atomic publish。它不代替 source owner 决策，也不把本地 JSON、Markdown、agent 输出、snapshot 或 validator 结果提升为授权。

### 1.2 当前与历史身份

| 对象 | raw bytes | raw SHA-256 / snapshot SHA-256 | 边界 |
| --- | ---: | --- | --- |
| 当前 `docs/baseline-manifest.md` | `1689` | `a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3` | 本 revision 唯一 active source baseline |
| 旧 `CR-014-R1` 文件 | `42551` | raw `6e78b4c8450c17efa40fead973c44650b411e19a629c334fdfe96d6796fe348a` | 只作历史审计输入 |
| 旧 `CR-014-R1` decision preimage | `40628` | `a0a5c71cbdd1b881a6572ac994d76bca942191ba388f2a1b6e5c15c0d236c830` | 只作历史 review identity |
旧 R1 bytes、snapshot、machine record、签名、registry 或 pin 均不是当前批准事实。不得改名、别名、复制旧 machine contract 或把旧 `717c...` record 解释为本 revision。

### 1.3 权限边界

当前文档及其未来 snapshot 均不授权：

- 修改 Request、manifest、`approval_pre_meta.py`、代码或测试；
- 创建账号、bootstrap/seed、migration、PostgreSQL、Redis、Backend、Frontend、浏览器、容器或网络运行；
- 生成或伪造 message ID、signature、signer registry、registry pin、key、secret 或 production evidence；
- 发布、部署、canary、staging、production、UAT 或 AC；
- 把 agent/assistant 消息、文件 receipt、validator、聊天摘要或同一人的自填 JSON冒充 BOSS 直接授权。

若未来需要在另一个 Codex task/thread、CI、离线包或外部系统发起新的 publish 或重放本次 authorization，必须新建并批准 cryptographic signature/signer-registry successor；不得跨 task 搬运本 task 的本地 receipt 当权威。无法再读取本 task transcript 只阻断新的 publish/reuse，不自动否定已经通过第 7.2 节 acceptance predicate 的 committed baseline。

## 2. 当前十一文件 pre identity 与路径职责

### 2.1 唯一 pre identity set

bytes 为原始文件长度，SHA-256 为原始 bytes 的 64 位小写 hex；路径区分大小写且不得使用别名。

| ordinal | path | raw bytes | raw SHA-256 |
| ---: | --- | ---: | --- |
| 1 | `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | `131596` | `d3a88b94fcc8351c71925ee944f63665ad1c029daba96513f1a2ac081dce9059` |
| 2 | `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | `93300` | `150a986e14538242bd9c39ae1f0e8c91427b94d3f0752616dd7618859161d425` |
| 3 | `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | `117732` | `458586e55b9360344a5b9e7485290dc378b89b2a19c251582707196dd7fcf341` |
| 4 | `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | `330151` | `8f27af9edb3f195d26a0541d36ec3ab40bfe4c1f5ff864f454a70bafc1a64410` |
| 5 | `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | `85242` | `6804fa2525cb7cf9f3293dc111e7a37aec83880bd2bafd2e19f8d20a7bfb8f14` |
| 6 | `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | `53524` | `9b406bc5e7d82fce96b402aa6230aa44d7306acc681c2f892f9aea437c04ff82` |
| 7 | `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | `52656` | `56b3ba9ae04b797452a9318db83fea9c1c8e4d5f20ce5981b6167e26dff37afb` |
| 8 | `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | `56491` | `e008610d49c16c96cbb7819f9b5e017db3a500347acfec95142666279b8a5ab2` |
| 9 | `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | `108745` | `dbfd0243b413cee89ad6d570a013e313704e053ae3b0f8217871ee7b6472b445` |
| 10 | `docs/baseline-manifest.md` | `1689` | `a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3` |
| 11 | `backend/app/approval_pre_meta.py` | `22193` | `331a8afef48e53a587d7454418426fdfe043b4813dc90322ea207627473b7cd9` |

任何 Gate、staging 或 publish 开始前都必须重新读取全部十一项；缺失、额外目标、路径、bytes 或 hash 任一不等立即 `BLOCKED_BY_DRIFT`。漂移时不得生成 snapshot、approval receipt、A2 artifact、expected-post bundle、joint authorization、intent 或 post bytes，也不得自动修正当前文件。

### 2.2 路径职责

1. 九份 `Request/*.md` 只投影 ordered sources `[CR-006-R3,CR-013-R2]` 的获批内容；本 CR 不是 Request source。
2. `docs/baseline-manifest.md` 只记录九份 Request 的 post raw bytes/hash；不列本 CR、receipt、bundle、manifest 自身或 `approval_pre_meta.py`。
3. `backend/app/approval_pre_meta.py` 只改 `_BASELINE_IDENTITY` 的 manifest raw-byte-length 与 raw-SHA-256 两个 literal；路径 literal、控制流和其他 byte 不变。其既有 `verify_pre_meta()` 只验证 static pre-meta artifacts，明确不是第 7.2 节 active-baseline acceptance consumer，运行中间态时的输出不得作为 publish/commit/rollback证据。
4. 第 7.2 节 predicate 由未来冻结 source hash的 cooperative publisher及显式声明 `auth-oplog-active-baseline-verifier-v1` 的 verifier实现；当前仓库不存在该 verifier。本文件不在十一文件集合中，不随 publish 替换。

## 3. delta 口径与 exact source choices

### 3.1 不得再称 overall zero semantic delta

| delta | exact candidate value | owner / 语义 |
| --- | ---: | --- |
| `governance_delta` | `ZERO` | 本 CR 自身只增加治理，不增加业务事实 |
| `combined_source_semantic_delta` | `NONZERO` | 两个 source 合并后会改变 active Request 语义 |
| `api_path_delta` | `0` | 复用 AUTH-001/002/003/004/007/010 |
| `ui_page_delta` | `0` | 复用 UI-001/UI-014 |
| `baseline_core_table_delta` | `+1` | CR-006-R3 新增 `operation_log_chain_state`；`operation_logs` 已在 57 表基线 |
| `operation_log_action_delta` | `+10` | CR-006-R3 AUTH/bootstrap action registry |
| `permission_code_delta` | `+1` | CR-013-R2 新增 `users:manage` |
| `alembic_migration_delta` | `+2` candidate | operation-log revision + 后继 auth revision；当前均未授权 |
| `AUTH-010_cross_store_failure_semantics` | `NONZERO` | Redis consume 成功而 PostgreSQL/audit失败时 Token保持 consumed、PG整体回滚、禁止 unconsume/自动重试，用户重新登录 |

### 3.2 CR-014-R2 governance decisions

本 CR 获批时 `selected_decisions` 必须按顺序恰为：

1. `CR014R2-D-001=CURRENT_ELEVEN_PRE_IDENTITY_BINDING`
2. `CR014R2-D-002=PLATFORM_AUTHENTICATED_BOSS_DIRECT_MESSAGE_AUTHORITY`
3. `CR014R2-D-003=TYPED_RECEIPT_NON_AUTHORITATIVE_EVIDENCE_ONLY`
4. `CR014R2-D-004=EXACT_TWO_SOURCE_A1_AND_BLOCKLIST_A2_BINDING`
5. `CR014R2-D-005=EXPECTED_POST_INVERSE_BEFORE_JOINT_AUTHORIZATION`
6. `CR014R2-D-006=NTFS_COOPERATIVELY_ATOMIC_ELEVEN_FILE_PUBLISH`
7. `CR014R2-D-007=GOVERNANCE_ZERO_COMBINED_SOURCE_NONZERO`

### 3.3 CR-006-R3 exact choices

CR-006-R3 A1 的 `selected_decisions` 必须按顺序恰为：

1. `OPLOGAUTH-D-001=AUTH_ACTION_REGISTRY_V1`
2. `OPLOGAUTH-D-002=TRUSTED_IDENTITY_AND_TELEMETRY_V1`
3. `OPLOGAUTH-D-003=PG16_COMPOSITE_TIME_IDENTITY_V1`
4. `OPLOGAUTH-D-004=UTC_MONTH_FAIL_CLOSED_DEFAULT_GUARD_V1`
5. `OPLOGAUTH-D-005=APPEND_ONLY_ACL_V1`
6. `OPLOGAUTH-D-006=LOCAL_TEST_DAILY_CHAIN_V1`
7. `OPLOGAUTH-D-007=LOCAL_TEST_RETENTION_BACKUP_RESTORE_V1`
8. `OPLOGAUTH-D-008=BOOTSTRAP_AND_FAULT_ATOMICITY_V1`
9. `OPLOGAUTH-D-009=AUTH_SLICE_ONLY_NO_PRODUCTION`

`OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` 是独立 governance dependency，不是 CR-006 source-owner substantive decision，不得进入上述 `selected_decisions`。验证 CR-006 A1 时必须另验：本 CR governance direct approval 已有效且其 snapshot逐值匹配 C-010 所指 revision；缺失时 A1 dependency 不满足。

### 3.4 CR-013-R2 exact choices

CR-013-R2 A1 必须同时绑定三组值。top-level `selected_decisions` 按顺序恰为：

1. `AUTHSLICE-D-001=PASSWORD_AND_LOGIN_PROFILE_V1`
2. `AUTHSLICE-D-002=JWT_AND_REFRESH_PROFILE_V1`
3. `AUTHSLICE-D-003=LOCAL_TEST_SIGNER_PROFILE_V1`
4. `AUTHSLICE-D-004=USER_LIST_PERMISSION_SLICE_V1`
5. `AUTHSLICE-D-005=AUTH007_READ_MODEL_V1`
6. `AUTHSLICE-D-006=BOOTSTRAP_AND_BROWSER_CUSTODY_V1`
7. `AUTHSLICE-D-007=OPLOG_COMPANION_AND_GATE_PROFILE_V1`
8. `AUTHSLICE-D-008=PASSWORD_BLOCKLIST_ARTIFACT_BINDING_V1`

BOSS choices 按顺序恰为：

1. `AUTHSLICE-C-001=TWO_CR`
2. `AUTHSLICE-C-002=EPHEMERAL_ED25519_LOCAL_TEST_ONLY`
3. `AUTHSLICE-C-003=ALLOW_READ_ONLY_AUTH007`
4. `AUTHSLICE-C-004=EFFECTIVE_ROLE_UNION`
5. `AUTHSLICE-C-005=STAGED_SECLISTS_2026_1_BLOCKLIST_V1`
6. `AUTHSLICE-C-006=LOCAL_TEST_JWT_SESSION_FAMILY_V1`
7. `AUTHSLICE-C-007=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1`
8. `AUTHSLICE-C-008=AUTHSLICE_PROFILE_AND_GATES_V1`

`AUTHSLICE-C-006` 的 JS 子决策按顺序恰为：

1. `AUTHSLICE-JS-001=STRICT_COMPACT_JWS_EDDSA_V1`
2. `AUTHSLICE-JS-002=EXACT_ACCESS_AND_PASSWORD_CHANGE_CLAIMS_V1`
3. `AUTHSLICE-JS-003=SINGLE_PROCESS_EPHEMERAL_ED25519_V1`
4. `AUTHSLICE-JS-004=POSTGRESQL_USER_SESSION_ORG_EPOCH_BINDING_V1`
5. `AUTHSLICE-JS-005=REFRESH_FAMILY_STORAGE_V1`
6. `AUTHSLICE-JS-006=ROOT_LOCK_ROTATE_REPLAY_CAS_V1`
7. `AUTHSLICE-JS-007=LOGOUT_TERMINAL_MATRIX_V1`
8. `AUTHSLICE-JS-008=REDIS_PASSWORD_CHANGE_ONETIME_V1`
9. `AUTHSLICE-JS-009=EMPTY_SESSION_AUTH_MIGRATION_SHAPE_V1`

任一组缺项、额外、别名、重排或仍写 `UNRESOLVED`，CR-013-R2 A1 不成立。

## 4. 唯一权威的 approval-only typed BOSS direct message

### 4.1 平台 transcript 权威边界

只有同时满足下列条件的消息才可能授权：

1. 消息位于仍可由平台 `read_thread` 直接读取的 active task/thread `019fee83-e431-7a32-86ea-b1e043e641b8`；
2. `read_thread` 对精确 turn/item返回 `type=userMessage`，平台把它认证为当前 BOSS/YHBX 的直接用户输入且无 delegation/代发标记；
3. 消息正文逐 byte 符合第 4.2 节 approval-only 十五行模板与五种 kind 联合矩阵；
4. `approval_nonce` 是该 thread 中此前未消费的 RFC 4122 UUIDv4 小写 canonical text；
5. 目标 snapshot、角色逐项决定、choices、scope、artifact binding 与有效期全部通过；
6. publisher 消费授权时仍在同一 active thread，能用平台返回的 event ref直接重读同一 item、sender type与 exact text。

权威 event ref profile固定为 `codex-thread-event-v1`，三元组恰为 `(thread_id,turn_id,user_message_item_id)`。三个值都必须逐字来自平台 `read_thread` 返回；`turn_id/user_message_item_id` 不得出现在 BOSS 模板中，不得由正文、本地脚本、receipt、nonce或 hash生成/猜测。publisher用三元组定位时必须恰匹配一个 item，并验证该 item `type=userMessage`、无 delegation、正文中的 nonce与 exact text hash；缺失、多匹配、类型不同、delegated或正文不等均为 `NOT_AUTHORIZED`。

platform `userMessage` text必须只含一个 `text` fence：开 fence恰为 `````text\n``，随后是十五行且每行末尾一个 LF，闭 fence恰为 `````\n``；fence前后不得有其他 byte。`source_message_text_sha256=SHA256(exact platform item UTF-8 text bytes)`，因此包含两个 Markdown fence与全部 LF，但不包含平台 UI metadata。`approval_nonce` 只负责正文防重放，不冒充 event ref、平台签名或 sender proof。本文不声称 `codex-thread-event-v1` 是平台签名 URI；它只是 platform-returned locator与重读规则。

Agent、assistant、tool、文件、数据库行、local receipt、截图、转述或复制文本均无审批权。publisher 只能在同一 active thread中通过 `read_thread` 重验并消费 platform item；一旦 event ref或 item不可读取，禁止发起新的 publish、从 exact pre/混合态继续任何 forward live写入或复用旧 authorization。唯一例外是同一 deterministic intent已完成全部 live replace、active/retired fence可验证，且第 6.4 节全部十一项 `forward_temp_files` identity逐值证明 live exact post：此时禁止回滚或再写 live target，只允许补齐/验证 COMMITTED terminal receipt与fence retirement，使既成 post进入可裁决 terminal state。该例外不由 receipt重新授权，只收口此前已消费且已执行的 intent；也不自动否定已经完成第 7.2 节 acceptance predicate 的 committed baseline。

### 4.2 exact fifteen-line format 与 JSON lexical rule

BOSS 直接消息必须包含一个 UTF-8 fenced text block，恰为以下十五行；字段顺序固定，每行只在首个 ASCII `=`处分割，不允许重复键、额外行、CR、BOM、行尾空格或第十五行后的空内容行：

```text
FINAUDIT_DIRECT_APPROVAL_V1
thread_id=019fee83-e431-7a32-86ea-b1e043e641b8
boss_name=YHBX
approval_nonce=<lowercase-canonical-uuidv4>
approval_kind=<CR014_R2_GOVERNANCE|CR006_R3_SOURCE_A1|CR013_R2_SOURCE_A1|CR013_R2_BLOCKLIST_A2|AUTH_OPLOG_JOINT_SYNC>
target_revision=<CR-014-R2|CR-006-R3|CR-013-R2>
target_snapshot_sha256=<64-lowercase-hex>
represented_roles=<compact-json-array-of-strings>
role_decisions=<compact-json-array-of-objects>
selected_decisions=<compact-json-array-of-strings>
scope=<governance_contract_only|source_contract_only|blocklist_artifact_only|cooperative_eleven_file_sync_only>
bound_artifact_kind=<none|auth_password_blocklist_a2_payload|expected_post_inverse_bundle>
bound_artifact_ref=<none|exact-create-only-artifact-ref>
bound_artifact_sha256=<none|64-lowercase-hex>
valid_utc=[<RFC3339-UTC-inclusive>,<RFC3339-UTC-exclusive>)
```

三个 JSON value 必须各自是 RFC 8785 JCS compact bytes的单行 UTF-8表示，无空白、重复值或额外元素。`represented_roles` 是有序 string array；`selected_decisions` 是有序 string array；`role_decisions` 与角色数组等长同序，每项根恰为 `{"decision":"APPROVED","role":"<same-role>"}`。本模板只有 approval，不存在 `decision=REJECTED`、`rejected_decisions`、部分批准或空角色分支；不批准时 BOSS 不发送该 kind 的合格 block。

九角色数组精确为：

```json
["requirements_product","architecture","data_dba","backend_api","frontend_ui","ai_rag","ops","security","test"]
```

A2 四角色数组精确为：

```json
["backend_api","ops","security","test"]
```

`valid_utc` 两端必须是秒精度或更高精度的 RFC3339 UTC `Z` 时间，起点严格早于终点；平台消息时间与实际消费时间均须落在半开区间。`none` 只能是无引号 ASCII literal。

### 4.3 五种 approval kind 联合矩阵

下表是联合约束，不得把任一列按独立 enum 自由组合：

| `approval_kind` | target revision / snapshot | roles | selected decisions | scope | bound artifact |
|---|---|---|---|---|---|
| `CR014_R2_GOVERNANCE` | `CR-014-R2` / 本 CR 第 8.1 节 snapshot | 九角色 | 第 3.2 节七项 | `governance_contract_only` | kind/ref/sha 全为 `none` |
| `CR006_R3_SOURCE_A1` | `CR-006-R3` / 本文第 8.1 节算法对 CR-006 生成的 snapshot | 九角色 | 第 3.3 节 D-001～D-009 九项；另验 C-010 governance dependency | `source_contract_only` | kind/ref/sha 全为 `none` |
| `CR013_R2_SOURCE_A1` | `CR-013-R2` / 本文第 8.1 节算法对 CR-013 生成的 snapshot | 九角色 | 第 3.4 节 top-level D、C、JS 三组依次连接后的二十五项 | `source_contract_only` | kind/ref/sha 全为 `none` |
| `CR013_R2_BLOCKLIST_A2` | `CR-013-R2` / 与已批准 A1 相同的 CR-013 snapshot | 四角色，且四个 role decision逐项 `APPROVED` | `["AUTHSLICE-A2-001=CREATE_ONLY_BLOCKLIST_ARTIFACT_APPROVED"]` | `blocklist_artifact_only` | kind=`auth_password_blocklist_a2_payload`；ref=十键 payload 内 final artifact create-only ref；sha=payload JCS raw SHA-256 |
| `AUTH_OPLOG_JOINT_SYNC` | `CR-014-R2` / 已批准 governance 使用的同一 snapshot | 九角色 | `CR014R2-SYNC-001～004` 四项，按第 6.3 节顺序 | `cooperative_eleven_file_sync_only` | kind=`expected_post_inverse_bundle`；ref/sha=第 6.2 节 bundle create-only ref/raw SHA-256 |

A2 `bound_artifact_ref` 必须逐字等于 payload 的 `artifact_ref`，其尾部 `/sha256/<digest>` 必须等于 payload `final_raw_sha256`；`bound_artifact_sha256` 只表示十键 payload raw SHA-256，不得误作 final artifact hash。joint ref/hash必须属于同一 bundle。任一 kind/target/snapshot/role/order/scope/binding组合不等即不是 approval。

### 4.4 local canonical receipt：只作 evidence

允许从合格 platform item派生本地 JCS receipt，但根恰为以下二十键：

```text
receipt_version,authority_class,thread_id,turn_id,user_message_item_id,boss_name,approval_nonce,approval_kind,
target_revision,target_snapshot_sha256,represented_roles,role_decisions,selected_decisions,
scope,bound_artifact_kind,bound_artifact_ref,bound_artifact_sha256,valid_utc,
platform_message_timestamp_utc,source_message_text_sha256
```

固定 `receipt_version='finaudit-direct-approval-receipt-v1'`、`authority_class='NON_AUTHORITATIVE_EVIDENCE_ONLY'`。`thread_id/turn_id/user_message_item_id` 逐字等于 `codex-thread-event-v1` platform-returned locator；receipt 每层禁止额外键，使用严格 UTF-8 no-BOM RFC 8785 JCS，其余字段逐项等于 platform item正文与平台时间。create-only ref固定为 `artifact://finaudit/auth-oplog-source-sync-v1/approval-receipts/<approval_kind>/<approval_nonce>`，workspace-relative path固定为 `.finaudit/approval-artifacts/auth-oplog-source-sync-v1/approval-receipts/<approval_kind>/<approval_nonce>.jcs.json`。既有 path 一律 collision fail，不覆盖。

receipt raw hash只能证明本地 bytes identity，不能证明 sender/thread，不能单独通过任何 Gate或供另一个 task授权。Machine validator只能机械实现本文闭集并输出 PASS/FAIL与安全原因码；不得增加字段、角色、choices、authority、scope或授权分支。

## 5. source A1、CR-013 A2 与依赖闭合

### 5.1 CR-014 governance approval

先完成第 8.1 节 independent review 与十一文件 pre recheck，再生成本 revision snapshot；随后由 BOSS 使用 `CR014_R2_GOVERNANCE` direct message批准九角色 governance choices。该 direct message是唯一 authority；进入 source snapshot阶段前必须 create-only 派生一份第 4.4 节 governance receipt，以固定后续 bundle可重验的 event correlation。snapshot 或 receipt 本身不批准，receipt生成失败则不得生成 source snapshot。

### 5.2 两个 source A1 approval

governance approval 有效后才允许生成 source snapshots：

1. 按第 8.1 节分别生成 `CR-006-R3` 与 `CR-013-R2` snapshot；
2. BOSS 分别发送 `CR006_R3_SOURCE_A1` 与 `CR013_R2_SOURCE_A1` direct message；
3. 每条消息绑定对应唯一 snapshot、完整九角色逐项 `APPROVED` 的 role decisions和第 3.3/3.4 节 exact choices；
4. CR-013 A1 必须按顺序同时绑定 top-level D、C001～C008、JS 九项，不能只选 top-level D；
5. 两个 source approval 都有效才可继续；任一拒绝、缺项、漂移或过期整体失败关闭。

每个 A1 的唯一 authoritative record 是对应平台认证 BOSS direct message。CR-006 A1 还必须验证 `OPLOGAUTH-C-010` 所指 CR-014 governance approval确已有效；C-010 不加入九项 source selections。由 direct message派生的 local canonical receipt只是 A1 evidence，不能独立满足本节；但进入 bundle 前必须为两个 A1 各 create-only 生成一份第 4.4 节 receipt，以便固定 audit correlation，生成失败则不得形成 bundle。

### 5.3 CR-013 password-blocklist A2

两个 source A1 全部有效后，才允许按 CR-013-R2 已冻结的 source/generator 合同离线生成 create-only artifact。A2 payload 根必须逐集合等于以下十键：

```text
schema_version,artifact_version,source_manifest_jcs_sha256,source_raw_sha256,
generator_profile,generator_source_sha256,independent_verifier_source_sha256,final_nonempty_line_count,
final_raw_sha256,artifact_ref
```

payload 固定 `schema_version='auth-password-blocklist-artifact-approval-payload-v1'`、`artifact_version='auth-password-blocklist-v1'`、`generator_profile='auth-password-blocklist-generator-v1'`；五个 SHA-256字段均为64位小写 hex，且 `generator_source_sha256 != independent_verifier_source_sha256`。`artifact_ref` 固定为 `artifact://auth/password-blocklist/auth-password-blocklist-v1/sha256/<final_raw_sha256>`；payload 使用严格 UTF-8 no-BOM RFC 8785 JCS。payload evidence create-only ref固定为 `artifact://finaudit/auth-oplog-source-sync-v1/blocklist-a2-payloads/sha256/<payload_raw_sha256>`，path固定为 `.finaudit/approval-artifacts/auth-oplog-source-sync-v1/blocklist-a2-payloads/sha256/<payload_raw_sha256>.jcs.json`；已存在即 collision fail，不覆盖。

随后 BOSS 使用一条 `CR013_R2_BLOCKLIST_A2` direct message，逐字绑定 payload raw SHA-256、final artifact create-only ref及四个有序 role decisions；`bound_artifact_sha256=payload_raw_sha256`，ref尾 digest逐字等于 payload `final_raw_sha256`。该 direct message才是当前 task 的批准权威；local receipt仅是 non-authoritative evidence，但进入 bundle 前必须 create-only 生成恰一份第 4.4 节 A2 receipt。A2 缺失、任一 role decision缺失、payload/ref/hash不同、消息过期或 receipt生成失败时，不得 staging、joint authorize 或 publish。

## 6. expected-post/inverse bundle 与后置 joint authorization

### 6.1 先 staging，后授权

只有两个 source A1 与 CR-013 A2 全部有效后，执行器才可在隔离本地 staging 中读取 live 十一项并生成候选；此阶段不得写 live path。顺序固定：

1. 重验第 2.1 节十一 pre identities；
2. 按 `[CR-006-R3,CR-013-R2]` 只投影获批内容到九份 staged Request；
3. 从九份 staged Request raw identities生成 staged post manifest；
4. staged `approval_pre_meta.py` 只更新 `_BASELINE_IDENTITY` 两个 literal；
5. 冻结十一项 expected post identities；
6. 为十一项 pre/post exact bytes生成第 6.2 节 immutable content-addressed raw blob，逐 byte回读并验证 length/hash；
7. 以每个 changed path的 pre/post raw blob执行 post读取与 pre恢复演练，逐 byte恢复第 2.1 节 pre identity；
8. 生成 create-only `expected-post-inverse-bundle-v1` JCS bytes与 raw SHA-256。

### 6.2 artifact root、bundle closed types 与 create-only identity

所有本 CR approval artifacts 的唯一 workspace-relative root固定为：

```text
.finaudit/approval-artifacts/auth-oplog-source-sync-v1
```

执行器必须从当前 workspace root解析该路径并确认最终 normalized path仍在 workspace内、同一 volume、且 `.finaudit` 以下任一既有 component都不是 symlink/junction/reparse point。对第 2.1 节十一 live targets，还必须以 Windows handle逐级检查 workspace root、每个 parent component与 target：`GetFinalPathNameByHandleW` 的 normalized final path必须仍在同一 workspace root，volume identity相同，`FileAttributeTagInfo` 不含 reparse point，target为 regular file；preflight读取后保存 file identity，并在每项 replace前重新打开复核，任一 path/file identity/volume/reparse漂移为 `LIVE_TARGET_PATH_DRIFT`，不得备份或替换 workspace外对象。artifact ref URI authority固定为 `artifact://finaudit/auth-oplog-source-sync-v1`。所有 JSON artifact均为严格 UTF-8 no-BOM RFC 8785 JCS；除下述 raw blob CAS与第 6.4 节 exact terminal-receipt recovery外，所有 create操作使用 create-new语义，目标 path、大小写折叠等价 path或 transaction directory已存在即 `ARTIFACT_REF_COLLISION`，禁止覆盖、truncate、别名或自选目录。

raw blob ref/path固定为 `artifact://finaudit/auth-oplog-source-sync-v1/raw-blobs/sha256/<raw_sha256>` 与 `.finaudit/approval-artifacts/auth-oplog-source-sync-v1/raw-blobs/sha256/<raw_sha256>.raw`。首次写入必须 create-new、flush并复核 exact bytes；既有同 path只有在 handle/path检查通过且 raw length/hash/bytes逐值相等时可只读复用，不等即 `ARTIFACT_REF_COLLISION`。raw blob一经形成永不覆盖、truncate、删除或按 mtime选择。

bundle 根逐集合等于以下二十键：

```text
bundle_version,source_baseline_manifest_sha256,ordered_sources,
governance_approval_event_ref,governance_approval_receipt_sha256,
cr006_snapshot_sha256,cr013_snapshot_sha256,source_approval_event_refs,
source_approval_receipt_sha256s,blocklist_a2_event_ref,
blocklist_a2_payload_evidence_ref,blocklist_a2_payload_sha256,
blocklist_final_artifact_ref,blocklist_a2_receipt_sha256,
pre_files,post_files,inverse_entries,projection_manifest,generator_identity,publisher_identity
```

closed type规则固定如下：

- `bundle_version='expected-post-inverse-bundle-v1'`；baseline/snapshot/receipt/payload hash全部是64位小写 hex；`ordered_sources=["CR-006-R3","CR-013-R2"]`。
- `source_baseline_manifest_sha256` 必须逐值等于第 2.1 节 ordinal 10 pre SHA-256 `a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3` 与 `pre_files[ordinal=10].raw_sha256`。`cr006_snapshot_sha256` 必须逐值等于 CR006 source A1 platform message/receipt 的 `target_snapshot_sha256`；`cr013_snapshot_sha256` 必须同时逐值等于 CR013 source A1与blocklist A2 platform messages/receipts的 `target_snapshot_sha256`。bundle generator、joint consumer、publisher preflight与 recovery每次都重验这些等式；任一错配为 `INVALID_BUNDLE`。
- `approval_event_ref` 是六键 closed object `profile/thread_id/turn_id/user_message_item_id/source_message_text_sha256/approval_nonce`，`profile='codex-thread-event-v1'`，其余值逐字来自第 4 节已重验 platform item。`source_approval_event_refs` 恰为 `[cr006_event_ref,cr013_event_ref]` 并与 `ordered_sources` 同序；`blocklist_a2_event_ref` 恰为 A2 direct-message event ref。它们使 publisher可确定性重读 authority，不得由 receipt或本地文件反推。
- `governance_approval_event_ref` 恰为第 5.1 节 governance direct-message event ref；`governance_approval_receipt_sha256` 恰为其 mandatory local receipt hash。publisher、prepare与 recovery在任何 forward动作前必须连同 source/A2/joint refs重验它；CR-006 的 `C010-GOVERNANCE` 不得只靠 source receipt推断。
- `source_approval_receipt_sha256s` 恰为 `[cr006_receipt_sha256,cr013_receipt_sha256]`；`blocklist_a2_receipt_sha256` 恰为 A2 direct-message receipt hash。receipt hashes只是必须形成的关联 evidence，不提供 authority。
- `blocklist_a2_payload_evidence_ref` 恰为第 5.3 节 payload evidence create-only ref，尾 digest等于 `blocklist_a2_payload_sha256`；`blocklist_final_artifact_ref` 恰为十键 payload 的 `artifact_ref`，尾 digest等于 payload `final_raw_sha256`。二者不得混用。
- `pre_files/post_files` 各恰十一项并按第 2.1 节 ordinal升序；每项根恰为 `ordinal/path/raw_bytes/raw_sha256/raw_blob_ref`。ordinal为 `1..11` JSON safe integer，path逐字等于第 2.1 节 repo-relative `/` path，raw_bytes为非负 JSON safe integer，ref尾 digest逐字等于 raw SHA-256且回读 bytes匹配。
- `inverse_entries` 恰覆盖所有且仅覆盖 `pre_raw_sha256 != post_raw_sha256` 的 path，并按对应 ordinal升序；每项根恰为 `ordinal/path/pre_raw_sha256/post_raw_sha256/pre_raw_blob_ref/post_raw_blob_ref/restored_pre_raw_sha256`，两个 ref逐字等于对应 file entry，最后一项 hash必须等于 pre hash。本文删除未闭合的 patch hash概念；publisher forward只读 post blob，rollback优先使用本 intent exact backup并与 pre blob交叉验证。
- `projection_manifest` 根恰为 `schema_version/ordered_sources/request_paths/source_semantic_delta`；值固定为 `auth-oplog-request-projection-manifest-v1`、上述 ordered sources、第 2.1 节前九个 path有序数组、`NONZERO`。
- `generator_identity` 与 `publisher_identity` 均是根恰为 `profile/source_raw_sha256/runtime/network_scope` 的 closed object；前者值固定为 `auth-oplog-source-sync-generator-v1/<future frozen generator source raw SHA-256>/python-3.10/none`，后者固定为 `auth-oplog-cooperative-publisher-v1/<future frozen publisher source raw SHA-256>/python-3.10/none`。两个 source hash都必须在 bundle前冻结且不同实现职责不得共用 source identity；joint authorization绑定整个 bundle，因而逐值批准实际 publisher bytes。
- 所有 object禁止额外键；所有 array顺序均有语义，不排序重排；字符串不得包含反斜杠 path、`..`、绝对 path、NUL或 Unicode normalization别名。

令 `bundle_sha256=SHA256(bundle_jcs_bytes)`。bundle create-only ref与 path恰为：

```text
ref  = artifact://finaudit/auth-oplog-source-sync-v1/bundles/sha256/<bundle_sha256>
path = .finaudit/approval-artifacts/auth-oplog-source-sync-v1/bundles/sha256/<bundle_sha256>.jcs.json
```

### 6.3 BOSS joint authorization

bundle 冻结后，BOSS 才可发送 `AUTH_OPLOG_JOINT_SYNC` direct message。消息必须绑定 bundle create-only ref/raw SHA-256、完整九角色、四个 sync choices和有效期。任何早于 bundle 的自然语言批准、source approval、A2、snapshot 或 local receipt都不能替代 joint authorization。

四个 sync choices按顺序恰为：

```json
["CR014R2-SYNC-001=EXACT_EXPECTED_POST_AND_INVERSE_BUNDLE","CR014R2-SYNC-002=EXCLUSIVE_PUBLISHER_LOCK_AND_COMMIT_MARKER","CR014R2-SYNC-003=BYTE_EXACT_ORDERED_ROLLBACK","CR014R2-SYNC-004=NO_RUNTIME_OR_PRODUCTION"]
```

发布前必须在同一 active thread通过 `read_thread` 再次验证 `codex-thread-event-v1` event ref、唯一 item、`type=userMessage`、无 delegation、十五行正文/text hash、nonce未消费、有效期、bundle identity、governance/source/A2 authority与 live pre identities；任一失败为 `NOT AUTHORIZED`。joint `approval_nonce` 同时是第 6.4 节唯一 `intent_id`；第 7 节成功取得 publisher lock并以该 deterministic path原子 create-new transaction directory时 nonce即永久 consumed。directory创建前失败不消费；创建后不论 pending、rollback或失败均不得以该 nonce新建第二 intent，只能按本文恢复同一 intent，或取得新 bundle/nonce/direct message。

### 6.4 transaction intent、backup 与 terminal receipt identities

每次 publish 的 lowercase UUIDv4 `intent_id` 必须逐字等于对应 `AUTH_OPLOG_JOINT_SYNC` platform message的 `approval_nonce`，禁止另生成、改写或散列。该等式使 transaction directory成为 nonce的 deterministic create-new consumption record。transaction root与 refs固定为：

```text
transaction_path = .finaudit/approval-artifacts/auth-oplog-source-sync-v1/transactions/<intent_id>/
intent_path      = <transaction_path>/intent.prepared.jcs.json
intent_ref       = artifact://finaudit/auth-oplog-source-sync-v1/transactions/<intent_id>/intent
active_fence_path = .finaudit/approval-artifacts/auth-oplog-source-sync-v1/active-intent.jcs.json
active_fence_ref  = artifact://finaudit/auth-oplog-source-sync-v1/active-intent
active_fence_pending_path = <transaction_path>/active-intent.pending.tmp
retired_fence_path = <transaction_path>/active-intent.terminal.jcs.json
backup_root_path = <transaction_path>/backup/
backup_root_ref  = artifact://finaudit/auth-oplog-source-sync-v1/transactions/<intent_id>/backup
committed_path   = <transaction_path>/receipt.committed.jcs.json
committed_ref    = artifact://finaudit/auth-oplog-source-sync-v1/transactions/<intent_id>/receipts/COMMITTED
committed_pending_path = <transaction_path>/receipt.committed.pending.tmp
rolled_back_path = <transaction_path>/receipt.rolled-back.jcs.json
rolled_back_ref  = artifact://finaudit/auth-oplog-source-sync-v1/transactions/<intent_id>/receipts/ROLLED_BACK
rolled_back_pending_path = <transaction_path>/receipt.rolled-back.pending.tmp
```

transaction directory必须原子 create-new；已存在即 collision fail。backup files恰为 `<backup_root_path>/01.raw`～`11.raw`，另有 `<backup_root_path>/01.security-descriptor.bin`～`11.security-descriptor.bin`；ordinal逐项映射第 2.1 节 path，分别保存 exact pre bytes与 handle读取的 exact self-relative Windows security descriptor bytes，每项 create-new、写完并 `FlushFileBuffers`。security profile固定为 `auth-oplog-live-file-security-v1`：query mask恰为 `OWNER_SECURITY_INFORMATION|GROUP_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION|SACL_SECURITY_INFORMATION`，由完整 SACL bytes覆盖 mandatory label、resource attribute、scope及其他 SACL ACE，不单独增加 subset flag；`PROCESS_TRUST_LABEL_SECURITY_INFORMATION` 是 reserved，`ACCESS_FILTER_SECURITY_INFORMATION` 不属于本 file-object profile，二者均禁止。backup还必须保存 `SECURITY_DESCRIPTOR_CONTROL` 的 `SE_DACL_PROTECTED/SE_SACL_PROTECTED` 两个 bit。apply base mask恰为同一四项，并按 backup control bit对 DACL恰加 `PROTECTED_DACL_SECURITY_INFORMATION` 或 `UNPROTECTED_DACL_SECURITY_INFORMATION` 之一、对 SACL恰加 `PROTECTED_SACL_SECURITY_INFORMATION` 或 `UNPROTECTED_SACL_SECURITY_INFORMATION` 之一；不得沿用 staging 的 protected状态或省略继承语义。publisher必须只在本 transaction内启用 `SeSecurityPrivilege` 与 `SeRestorePrivilege`，以显式 `READ_CONTROL|WRITE_DAC|WRITE_OWNER|ACCESS_SYSTEM_SECURITY` handle access查询/应用，并验证 `AdjustTokenPrivileges` 未返回 `ERROR_NOT_ALL_ASSIGNED`；前者用于完整 SACL，后者用于恢复任意有效 owner/group。transaction结束必须恢复原 token privilege状态。任一 query/apply flag、privilege、access、control bit、完整 owner/group/DACL/SACL bytes或 exact回读不支持/不等即 `LIVE_TARGET_SECURITY_UNSUPPORTED`，首次 replace前失败关闭，禁止降级、丢弃 SACL ACE或改写 inheritance。在写 PREPARED intent前还必须为十一项 forward target按第 7.3 节创建并保持 exclusive handle的 secure temp，记录下述 identity。fixed `active_fence_path` 在取得 publisher lock后必须先证明不存在；若存在，新 publish不得创建 transaction或消费 nonce，只能按 fence精确恢复。

PREPARED intent根恰为十三键：

```text
intent_version,status,intent_id,created_at_utc,bundle_ref,bundle_sha256,
joint_approval_event_ref,joint_authorization_receipt_sha256,
pre_files,post_files,backup_root_ref,forward_temp_files,publisher_identity
```

固定 `intent_version='auth-oplog-publish-intent-v1'`、`status='PREPARED'`。`joint_approval_event_ref` 根恰为 `profile/thread_id/turn_id/user_message_item_id/source_message_text_sha256/approval_nonce`；profile固定 `codex-thread-event-v1`，三元 locator逐字来自平台，hash/nonce来自已重验 item。intent `publisher_identity` 必须逐 byte等于已获 joint authorization 的 bundle `publisher_identity`，不得在 joint 后自报或替换。`pre_files/post_files` 使用第 6.2 节 exact file-entry type。`forward_temp_files` 恰十一项同 ordinal顺序，每项根恰为 `ordinal/path/temp_path/raw_bytes/raw_sha256/volume_serial/file_id/staging_security_descriptor_sha256/final_security_descriptor_sha256`；`file_id` 是 handle读取的 128-bit lowercase hex，`volume_serial` 是恰16位 lowercase hex string而非 JSON number，staging hash绑定第 7.3 节 restricted temp ACL，final hash逐值绑定对应 target preflight/backup security descriptor。publisher source hash未冻结不得创建 intent。

PREPARED intent create-new、flush并复核 raw hash后，publisher才可物化 fixed active fence。fence根恰为十一键 `fence_version/status/intent_id/intent_ref/intent_raw_sha256/bundle_ref/bundle_sha256/created_at_utc/volume_serial/file_id/security_descriptor_sha256`，固定 `fence_version='auth-oplog-active-intent-fence-v1'/status='PREPARED'`，其余逐值绑定该 intent/bundle与 fence自身 handle identity；`volume_serial` 同样是恰16位 lowercase hex string，`file_id` 是128-bit lowercase hex。ACL profile固定为 `auth-oplog-active-fence-acl-v1`：protected DACL、owner=direct publisher SID、只有该 SID与 `SYSTEM` 的 full-control allow ACE、无其他 ACE；security descriptor hash按 `OWNER_SECURITY_INFORMATION|GROUP_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION` 的 exact self-relative bytes计算。

active fence必须先用 `CreateFileW` 以固定 `dwDesiredAccess=GENERIC_READ|GENERIC_WRITE|DELETE|READ_CONTROL|WRITE_DAC|WRITE_OWNER`、`dwShareMode=0`、`dwCreationDisposition=CREATE_NEW`、`dwFlagsAndAttributes=FILE_ATTRIBUTE_TEMPORARY` 在本 intent的 fixed `active_fence_pending_path` 创建，立即应用并回读 ACL，从仍打开 handle取得 file ID/volume/descriptor hash并写入 fence JCS，`FlushFileBuffers`后以同一 handle验证 normalized pending path、same volume、regular/no-reparse/hard-link count恰1、exact bytes/JCS/ACL/identity；随后只允许 `SetFileInformationByHandle(FileRenameInfoEx,Flags=0)` no-replace rename到全局 fixed `active_fence_path`，再重开 final并证明 path、同一 file ID/volume/content/ACL。nonce已由 deterministic transaction directory消费；只有完整 active final验证成功后才允许首次 live replace，pending-only状态不授权或触碰任一 live target。

active materialization recovery同样是闭集：active不存在且 operator显式 exact intent/ref定位到唯一 pending时，必须重验 `intent_id=joint approval_nonce`、PREPARED intent、全部 governance/source/A2/joint platform events仍有效、该 nonce只由此 deterministic transaction directory消费、live仍 exact pre、pending closed JCS/ACL/path/file identity完全一致，才可完成 pending→active `Flags=0` rename并复核；否则不得继续。active存在且 pending不存在时只按其 closed JCS/identity定位并恢复；二者同时存在为 `BASELINE_CONFLICT`。两者均不存在表示该已消费 nonce的 intent没有 active publish资格，不得凭空继续或重放。pending malformed/partial/mismatch固定 `BASELINE_CONFLICT`，不得删除、修补、覆盖或认领；它尚未成为全局 active，因此不阻断另一个具全新 bundle/nonce/transaction、仍通过 fixed-active-absent preflight的 publish。新 publish不得扫描或复用任何旧 pending。

任何 crash recovery重开本节既有 active-fence pending或terminal-receipt pending，都必须固定调用 `CreateFileW(dwDesiredAccess=GENERIC_READ|DELETE|READ_CONTROL,dwShareMode=0,dwCreationDisposition=OPEN_EXISTING,dwFlagsAndAttributes=FILE_FLAG_OPEN_REPARSE_POINT)`；从该 handle验证 normalized path、same volume、regular/no-reparse/hard-link count恰1、closed JCS/content/ACL及其绑定 identity后，只能在同一仍打开 handle上执行 `SetFileInformationByHandle(FileRenameInfoEx,Flags=0)` no-replace rename。缺 `DELETE` access、打开/验证/rename失败或 final已存在均按对应 conflict规则失败关闭，禁止退回 path-based rename。

fence retirement是单独的两路径 closed state machine。在 terminal final receipt已验证后，若 `active_fence_path` 存在且 `retired_fence_path` 不存在，必须以 `CreateFileW(dwDesiredAccess=GENERIC_READ|DELETE|READ_CONTROL,dwShareMode=0,dwCreationDisposition=OPEN_EXISTING)` 打开 active，逐值重验 normalized path、intent/ref/hash、volume/file ID/security descriptor、regular/no-reparse/link count，再只用 `SetFileInformationByHandle(FileRenameInfoEx,Flags=0)` no-replace rename到 fixed retired path；rename后重开 retired并证明同一 file ID/volume/content/ACL。若 active不存在而 retired存在，只允许 operator显式提供 exact `intent_id/ref`，并在验证 retired仍是上述同一 fence、对应 terminal final receipt与 live exact terminal state全部闭合后幂等返回既成 terminal classification，不得重建 active或再次 rename。active与retired同时存在、retired预先存在/identity不等、或两者均不存在但 caller声称恢复该 intent，均固定 `BASELINE_CONFLICT`。terminal receipt尚未形成、`ROLLBACK_INCOMPLETE`、`COHERENT_UNAUTHORIZED` 或任何 replace/rollback conflict发生在 retirement rename前时必须保留 active；rename已成功而复核前崩溃时以 retired路径恢复，不再声称 active仍存在。新 publish仍只以 fixed active存在为阻断，不得扫描或覆盖任一 retired fence。

terminal receipt根恰为十六键：

```text
receipt_version,status,intent_ref,bundle_ref,bundle_sha256,
joint_approval_event_ref,joint_authorization_receipt_sha256,
pre_files,post_files,replace_phase_started_at_utc,verified_at_utc,publisher_identity,
volume_serial,file_id,security_descriptor_sha256,failure_safe_code
```

固定 `receipt_version='auth-oplog-publish-transition-receipt-v1'`；`status` 只允许 `COMMITTED/ROLLED_BACK`。`replace_phase_started_at_utc` 对两种 status均必须逐值等于已经 flush的 active fence `created_at_utc`，`verified_at_utc` 是 terminal state完成验证时间；两者均为 RFC3339 UTC且后者不得早于前者。该字段只证明 replace phase gate已开始，不声称记录不可恢复的首次 live replace瞬时。COMMITTED 要求 `failure_safe_code=null`；ROLLED_BACK safe code只允许 `PREPARE_FAILED/REPLACE_FAILED/POST_VERIFY_FAILED/RECOVERY_ROLLBACK`。每个 status只使用对应 fixed pending/final path；不得同时存在两种 status 的 pending 或 final receipt。terminal ACL profile固定为 `auth-oplog-terminal-receipt-acl-v1`：protected DACL、owner=direct publisher SID、只有该 SID与 `SYSTEM` 的 full-control allow ACE、无其他 ACE；其 descriptor hash只按 `OWNER_SECURITY_INFORMATION|GROUP_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION` 的 exact self-relative bytes计算。首次形成 terminal receipt时必须用 `CreateFileW` 以固定 `dwDesiredAccess=GENERIC_READ|GENERIC_WRITE|DELETE|READ_CONTROL|WRITE_DAC|WRITE_OWNER`、`dwShareMode=0`、`dwCreationDisposition=CREATE_NEW`、`dwFlagsAndAttributes=FILE_ATTRIBUTE_TEMPORARY` 在对应 pending path创建，立即应用并回读上述 ACL profile；从仍打开 handle取得 file ID、16位 lowercase hex volume serial与 descriptor hash并写入 receipt对应三字段，再写 exact JCS bytes、`FlushFileBuffers`，以同一 handle复核 normalized path、same volume、regular file、no reparse、hard-link count恰1、三项 identity、exact bytes/JCS/ACL。随后只允许用 `SetFileInformationByHandle(FileRenameInfoEx)`、`Flags=0` 把该 handle no-replace rename到对应 final path。rename后必须重新以 handle验证 final normalized path、原 file ID/volume/descriptor hash、regular/no-reparse/link count、exact bytes/JCS/ACL均未变；任一失败固定 `BASELINE_CONFLICT`，禁止覆盖、删除、truncate或另选 path，并按下述 active/retired fence状态恢复。

`joint_authorization_receipt_sha256` 只绑定 non-authoritative local receipt作audit correlation；真正 authority始终是 `joint_approval_event_ref` 指向的 platform `userMessage` item。任何尚未提交的 forward publish或从 exact pre-state继续 PREPARED intent都必须重新 `read_thread` 验证 governance/source/A2/joint event refs；只有 rollback到 exact pre-state不需要重新取得批准。恢复者取得 exclusive handle后按前段 active/retired两路径定位唯一 intent，并在任何 state-based forward/rollback选择前按下段检查四个 terminal pending/final fixed paths。若恰有一个 status 的一份 pending或final存在，它只确定待验证的 terminal candidate而不自行证明成功：COMMITTED candidate必须同时证明 live exact post、bundle `post_files`与全部十一项 `forward_temp_files` ordinal的 intent volume serial/file ID/post hash/final security descriptor逐项相等，即使某项 pre/post bytes相同也不得跳过；ROLLED_BACK candidate必须同时证明 live exact pre。完全通过后只完成 pending→final（若需）与 exact fence retirement，禁止重新 forward或rollback；任一不等为 `BASELINE_CONFLICT`。只有四个 terminal path全不存在时才执行第 7.2 节 state分类：live exact post且上述全部十一项 intent identities全等时完成 COMMITTED terminalization；live exact pre时只有全部 event仍可重验且有效才可继续 forward，否则完成 ROLLED_BACK terminalization；live `COHERENT_UNAUTHORIZED` 时禁止 forward、rollback或terminal receipt，保留 active fence并等待人工处理；live `INCOHERENT` 只有在每个偏离 exact pre identity的 live target逐项属于本 intent已记录 forward temp时才允许按 backups rollback，否则同样 `BASELINE_CONFLICT`。event不可读不得逆转由 intent file identities证明的 exact post，只能完成其 terminal evidence；没有 matching active或retired fence的旧 intent永远不得恢复或覆盖当前 baseline。

四个 terminal path 的检查必须早于任何 live-state方向选择与新写入。若两种 status 都有 pending/final，或同一 status 同时存在 pending与 final，一律 `BASELINE_CONFLICT`并保留 active fence或既有 retired evidence。若恰有一个 final，恢复器必须以 handle验证 normalized path、same volume、regular/no-reparse/hard-link count恰1、`auth-oplog-terminal-receipt-acl-v1`，并把 closed-type JCS 的 `status/intent_ref/bundle_ref/bundle_sha256/joint_approval_event_ref/joint_authorization_receipt_sha256/pre_files/post_files/replace_phase_started_at_utc/verified_at_utc/publisher_identity/volume_serial/file_id/security_descriptor_sha256/failure_safe_code` 逐值重验为该 candidate、active fence持久时间、actual handle identity与 live-state约束所允许的唯一值；完全一致时不得重写 receipt，只按前段完成或验证 fence retirement，不一致即 `BASELINE_CONFLICT`。若恰有一个 pending且所有 final均不存在，必须按前述共用 pending-reopen规则打开并验证其 exact bytes/JCS/ACL/path及 receipt所绑定的 actual file ID/volume/descriptor hash；完全一致时仅在该同一 handle上以 `Flags=0` no-replace rename完成 final并复核，再按前段 retirement，任一不等即 `BASELINE_CONFLICT`。只有四个 path全不存在时才可按前段 create-new流程形成本次 state分类选定的 receipt。terminal final验证成功前不得 retirement rename；receipt已完整落入 final但进程在 fence retirement前崩溃时，恢复只能走“验证既有 final并完成或验证 retired fence”的幂等分支，不得再次 create-new receipt。

approval receipts仍只是 non-authoritative audit evidence。transition terminal receipt与 retired active fence共同证明一个已验证 intent的 terminal classification，但不替代原 platform authority；第 7.2 节将它们作为 post approved-state anchor。查验由 operator显式提供 exact `intent_id/ref`；恢复优先从 fixed active fence定位 intent；若 active已因 retirement rename消失，只能从 operator显式提供的 exact intent/ref解析该 transaction的 fixed retired path并按前述闭集验证。禁止目录扫描后按 mtime、文件名或自报 status自动挑选 transaction。

## 7. workspace-bound exclusive publisher 与 lock-free acceptance

### 7.1 事实边界与唯一 publisher lock

NTFS 不提供跨十一文件的物理原子 transaction；本文只使用同卷单文件 atomic replace、`approval_pre_meta.py` 最后提交标记与 lock-free identity predicate。任何 reader在发布或 rollback中途都可能读取混合 bytes；只有实现第 7.2 节的 cooperative publisher/显式 verifier保证拒绝混合态，既有 static `verify_pre_meta()` 或任意普通文件读取不具备该保证，也不得产生 acceptance evidence。本文不宣称 power-loss physical transaction或 shared-reader quiescence；单独 receipt/fence均不建立 active baseline，只有第 7.2 节完整 `ACCEPTED_POST` 闭合才成立。

唯一 publisher lock path固定为：

```text
.finaudit/locks/request-baseline-publish.lock
```

publisher 必须将其解析为当前 workspace内 normalized absolute path，确认 `.finaudit/locks` 不是 symlink/junction/reparse point，并通过 Windows `CreateFileW` 使用 `dwDesiredAccess=GENERIC_READ|GENERIC_WRITE`、`dwShareMode=0`、`dwCreationDisposition=OPEN_ALWAYS`、`FILE_ATTRIBUTE_NORMAL` 取得唯一跨进程 exclusive handle。等待使用 monotonic clock，deadline精确为首次尝试后5秒；只允许对 sharing/lock violation重试，超时为 `PUBLISH_LOCK_TIMEOUT`。handle覆盖 preflight、prepare、replace、post verify及必要 rollback；进程崩溃由 Windows 自动释放 handle。lock file可永久存在且不得因正常完成而删除；文件内容没有 authority或状态语义。

本合同删除 shared-reader lock。只有 publisher互斥；contract-conforming verifier不等待 publisher，也不读取 lock/intent/receipt决定基线有效性。

### 7.2 cooperative publisher / active-baseline verifier predicate

cooperative publisher或显式 `auth-oplog-active-baseline-verifier-v1` 先按下列 lock-free double-read判断十一文件 coherence；其他工具即使输出 PASS也不构成本合同 evidence：

1. 读取 `backend/app/approval_pre_meta.py` raw bytes为 `P1`，只按既有静态语法提取 `_BASELINE_IDENTITY` 中 manifest raw byte length与raw SHA-256两个 literal；解析失败即拒绝。
2. 读取 `docs/baseline-manifest.md` raw bytes为 `M1`，其长度/hash逐值等于 `P1` 两 literal；否则拒绝。
3. 严格解析 `M1`，其 path set必须恰为第 2.1 节前九份 Request且每项只有 exact raw bytes/hash identity；缺失、额外、重复、别名或 path escaping均拒绝。
4. 按 manifest顺序读取九份 Request并逐项验证 raw length/hash；任一不等即拒绝，不使用部分内容。
5. 再读取 manifest为 `M2`、pre-meta为 `P2`；必须满足 `M2==M1` 且 `P2==P1` raw-byte equality，并重新验证 P2 literals仍绑定 M2。任一变化即拒绝并从步骤1重新开始，不能把两次读取拼成成功。

前五步只产生 `COHERENT(tuple)`，不独立证明批准。approved-state分类恰为：

1. `ACCEPTED_PRE`：tuple逐项等于第 2.1 节十一项 pre identity；
2. `ACCEPTED_POST`：tuple逐项等于 operator显式提供的 bundle `post_files`，且同一 intent的 COMMITTED receipt、retired active fence、bundle/ref/hash、governance/source/A2/joint event refs逐值闭合；该 intent在提交时已由 frozen publisher重验 platform authority；
3. 任一其他自洽 tuple固定为 `COHERENT_UNAUTHORIZED`，不得建立 approved baseline；任一混合态为 `INCOHERENT`。

当前 static `approval_pre_meta.verify_pre_meta()` 不实现上述分类。publisher在 PREPARED恢复时只从 fixed active fence取得唯一 expected bundle，不接受 caller自由提交另一 post tuple。transition完成后 verifier必须由 operator显式给出 exact committed intent ref；禁止扫描或挑选“latest”。已经形成 `ACCEPTED_POST` 的 baseline不因原审批 transcript以后不可读取而自动失效。

### 7.3 publish、commit marker 与 byte-exact rollback

publisher 在 exclusive handle内按以下顺序执行：

1. 证明 fixed active fence不存在；重验 live baseline为第 7.2 节 `ACCEPTED_PRE`且等于 bundle `pre_files`；按第 6.2 节对 workspace root、十一 target全路径 component、file identity、volume与 reparse状态完成 handle-based preflight；重验 governance/source/A2 approvals、joint platform event、nonce、有效期、bundle ref/hash与 generator/publisher identities。
2. create-new transaction directory并保存 `01.raw～11.raw` exact pre backups与十一份 `auth-oplog-live-file-security-v1` exact target descriptor backups。为每个 post target从 bundle 对应 `post_files.raw_blob_ref` 回读 exact bytes，在目标同目录用 `CreateFileW` 固定 `dwDesiredAccess=GENERIC_READ|GENERIC_WRITE|DELETE|READ_CONTROL|WRITE_DAC|WRITE_OWNER|ACCESS_SYSTEM_SECURITY`、`dwShareMode=0`、`dwCreationDisposition=CREATE_NEW`、`FILE_ATTRIBUTE_TEMPORARY` 创建 forward temp；staging ACL profile恰为 `auth-oplog-publisher-temp-acl-v1`：protected DACL、owner=direct publisher SID、只有该 SID与 `SYSTEM` 的 full-control allow ACE、无其他 ACE。保持 handle打开，写/flush后以 handle验证 regular file、no reparse、hard-link count恰1、same volume、`FILE_ID_INFO`与完整 staging self-relative security descriptor hash，并把 staging/final两个 descriptor hash记录到 intent `forward_temp_files`。
3. transaction directory按 `intent_id=joint approval_nonce` create-new成功时 nonce已永久 consumed；随后 create-new写入并 flush第 6.4节 PREPARED intent，再按同节 fixed pending→active `Flags=0` handle-rename协议物化并验证 active final fence。任一 forward temp既有、identity/ACL/link count不等，active fence已存在，或 pending物化/验证失败，均在首次 live replace前失败且不触碰 live target；只能恢复同一 deterministic intent或取得全新 bundle/nonce，不得认领未记录 temp。
4. 按 ordinal `1→9`、10、11顺序处理。每项 replace前再次执行第 6.2 节 target parent/path/volume/reparse复核，并验证仍打开的 temp handle等于 intent记录的 file ID/staging ACL/link count/hash；随后在同一 handle上按 `auth-oplog-live-file-security-v1` 全 mask应用并回读验证对应 target备份的 exact final security descriptor，file ID/link count/content不得改变。只允许调用 `SetFileInformationByHandle(FileRenameInfoEx)` 并固定 `FILE_RENAME_FLAG_REPLACE_IF_EXISTS`，从仍具 `DELETE|ACCESS_SYSTEM_SECURITY` access且 shareMode=0 的同一 handle执行 same-volume replace；失败统一 `LIVE_TARGET_REPLACE_FAILED`。禁止关闭 handle后按 path rename、增加其他 rename flag、`MoveFileExW/os.replace`、truncate-and-write、copy-over或先删除 target。crash recovery只可认领 intent已记录、file ID/link count/hash及完整 security descriptor恰为 staging或final之一的 forward temp；若 temp path已消失，则 live target必须已具有该记录 file ID、final descriptor与 exact post bytes，否则按前述 state分类处理。
5. ordinal 11 `approval_pre_meta.py` replace是 coherence commit marker。完成后立即按第 7.2 节 double-read证明完整 tuple逐项等于 bundle `post_files`；此时状态为 `POST_COHERENT_PENDING_TERMINAL`，不得回滚。
6. 按第 6.4 节 COMMITTED terminalization形成或幂等验证 final receipt，再按同节 active→retired `Flags=0` handle-rename协议完成或幂等验证 fence retirement。只有 final receipt、retired fence与 live exact post全部闭合后状态才是 `ACCEPTED_POST`。receipt失败或 retirement rename前失败时保持 active fence；rename成功后复核前崩溃则保留 retired并走其幂等验证分支。两类失败都不回滚 exact post，也不允许未经 state分类的新 publish。

在成功证明 `POST_COHERENT_PENDING_TERMINAL` 前发生任一失败，且 state分类证明所有偏离 exact pre identity的 target都属于本 intent时，必须仍持 exclusive handle按固定顺序 rollback：先 restore ordinal 11 old pre-meta，再 ordinal 10 old manifest，最后按 `9→1` 恢复九份 Request；每个 backup先与 bundle对应 `pre_files.raw_blob_ref`逐 byte交叉验证，再在同目录以与 forward相同的 desired access、staging ACL、regular/no-reparse/link-count=1 profile create-new rollback temp，应用并验证对应 target backup的 final security descriptor，然后在 handle保持 exclusive时只用 `SetFileInformationByHandle(FileRenameInfoEx,FILE_RENAME_FLAG_REPLACE_IF_EXISTS)` replace。rollback temp path固定为 `.<target-basename>.finaudit-<intent_id>-<two-digit-ordinal>-rollback.tmp`；若已存在一律 `RECOVERY_TEMP_COLLISION` 并保留 active fence，禁止按 bytes认领、删除、复用或覆盖。每次 restore前仍须重验 target parent path/volume/reparse状态。完成后按第 7.2 节证明 `ACCEPTED_PRE`，按第 6.4 节 ROLLED_BACK terminalization形成或幂等验证 final receipt，再按同节完成或验证 fence retirement。若为 `COHERENT_UNAUTHORIZED` 或任一偏离 exact pre identity的 target不属于本 intent，则固定 `BASELINE_CONFLICT`且不写任何 live target或terminal receipt。恢复者只按第 6.4 节 fixed active或显式 exact retired path定位 intent并重验 backups/hash，禁止扫描或选择“latest”。

若 rollback不能恢复 exact pre predicate，状态为 `ROLLBACK_INCOMPLETE`，保持 publisher操作失败并禁止新 publish；不得伪造 COMMITTED/ROLLED_BACK receipt。本文的一次性同步仅表示一个 BOSS-authorized、publisher-exclusive、commit-marker-last transaction，不表示十一文件对所有 reader物理原子可见；非 conforming reader在混合态读取到内容不构成 accepted baseline。

## 8. snapshot、Gate 与验证

### 8.1 snapshot 算法

本 CR marker 为 `## 9. 当前状态`；两个 source marker 均为 `## 10. 当前动态状态`。每个文件独立执行：

1. 读取 raw bytes；拒绝 UTF-8 BOM、非法 UTF-8、解码替换字符、NUL；
2. CRLF和孤立 CR规范化为 LF，不做 Unicode normalization、trim或 Markdown重排；
3. 对目标 marker按完整行逐 byte匹配，必须恰好一次；
4. 取 marker 行前全部规范化内容，移除末尾全部 LF后追加一个 LF；
5. UTF-8 no-BOM编码为 preimage，计算 raw bytes与 SHA-256小写 hex；
6. snapshot 只建立 direct-message 可绑定对象，不构成 approval、A2、joint authorization或 publish权限。

本次 draft/edit任务不得生成任何 snapshot。第 1～8 节冻结后，必须先由非作者 independent reviewer 对本 revision做只读审查，并在同一生成动作前重新计算第 2.1 节十一项 pre identities；两项均 PASS时才允许生成 `CR-014-R2` snapshot。source snapshots绝不与 governance snapshot并行生成，只有 `CR014_R2_GOVERNANCE` platform event已按第 4 节批准并仍有效后，才允许分别生成 CR-006-R3 与 CR-013-R2 snapshot。任一 review/pre identity/governance失败均保持 `NOT GENERATED`。

### 8.2 唯一 Gate 顺序

```text
current 11 pre identities
  -> independent review + exact 11-pre recheck
  -> CR-014-R2 snapshot -> BOSS governance platform event                     [Gate A]
  -> CR-006-R3 snapshot/A1 + CR-013-R2 snapshot/A1                           [Gate B1]
  -> CR-013-R2 blocklist create-only artifact + one BOSS/four-role-decisions A2 [Gate B2]
  -> read-only-to-live staging -> expected-post/inverse bundle                [Gate C1]
  -> BOSS joint platform event binding exact bundle                           [Gate C2]
  -> exclusive publisher handle -> PREPARED -> 9 Request -> manifest -> pre-meta
  -> post coherence -> mandatory COMMITTED receipt -> retire active fence -> ACCEPTED_POST [Gate C3]
```

禁止先 joint authorize 后生成 post、生成决定权限的新 machine contract、竞争 sibling baseline、中间 active manifest、单 source publish、部分授权或在 exclusive publisher handle外执行 replace。

### 8.3 最小验收

| 检查 | PASS | FAIL |
| --- | --- | --- |
| pre identity | 第 2.1 节十一项全等 | `BLOCKED_BY_DRIFT` |
| direct authority | `codex-thread-event-v1` 三元 locator唯一命中 direct `userMessage`、无 delegation、typed正文/hash/nonce/有效期全通过 | `NOT APPROVED/NOT_AUTHORIZED` |
| source A1 | CR006九项且 C-010 dependency另验；CR013 top-level D+C+JS共二十五项 | `NOT APPROVED` |
| blocklist A2 | exact十键 payload、互异实现 source hash、ref/hash与一条消息四个 role decisions一致 | `BLOCKED_A2` |
| bundle | exact pre/post/inverse，round-trip逐 byte通过 | `INVALID_BUNDLE` |
| publisher lock | workspace-bound CreateFileW shareMode=0、5秒 monotonic deadline | `PUBLISH_LOCK_TIMEOUT` |
| publish | fixed fence + 9 Request→manifest→pre-meta + post coherence + mandatory terminal evidence，或 exact ordered rollback | `ROLLED_BACK`、`ROLLBACK_INCOMPLETE`或`NOT COMMITTED` |
| scope | runtime/DB/Redis/browser/network/production未调用 | `OUT_OF_SCOPE` |

### 8.4 动态事实与 revision

snapshot/hash、BOSS消息、平台时间、local receipts、A2 payload/artifact、expected post、inverse、bundle、intent与transition receipt都是后续动态事实，不得回填第 1～8 节。第 1～8 节任一 byte在 snapshot后变化必须创建 successor revision，并使旧 approval、bundle和authorization失效。

本次不创建 validator、snapshot、receipt、artifact、bundle、intent或transition evidence；也不运行 runtime、数据库、Redis、浏览器、容器或网络。

## 9. 当前状态

| 项目 | 当前值 |
| --- | --- |
| revision | `CR-014-R2` |
| static contract | `FROZEN CANDIDATE / NOT APPROVED` |
| governance delta / combined source semantic delta | `ZERO / NONZERO` |
| independent final review | `2 READ-ONLY REVIEWERS / NO CRITICAL-HIGH-MEDIUM FINDINGS` |
| current pre identities | `RECHECKED IMMEDIATELY BEFORE SNAPSHOT / PASS` |
| CR-014-R2 snapshot | `GENERATED / bytes=61470 / sha256=38a8d329eb2d7ac4414d139431bc0c6448c788d8c21ecdba890a2d48b5207ae8` |
| BOSS governance direct approval | `NOT RECEIVED / NOT APPROVED` |
| CR-006-R3 snapshot/A1 | `NOT GENERATED / NOT APPROVED` |
| CR-013-R2 snapshot/A1 | `NOT GENERATED / NOT APPROVED` |
| password-blocklist artifact/A2 | `NOT GENERATED / NOT APPROVED` |
| local canonical receipts | `NONE / NON_AUTHORITATIVE ONLY` |
| signature / signer registry / registry pin | `NONE / NOT GENERATED / NOT CLAIMED` |
| expected-post/inverse bundle | `NOT GENERATED` |
| BOSS joint direct authorization | `NOT RECEIVED / NOT AUTHORIZED` |
| publisher intent / transition audit receipt | `NONE / NOT GENERATED` |
| Request / manifest / pre-meta writes | `NONE / NOT AUTHORIZED` |
| login / JWT / RBAC / operation-log runtime | `NOT AUTHORIZED / NOT RUN` |
| bootstrap / seed / migration / DB / Redis / browser / container / network | `NOT AUTHORIZED / NOT RUN` |
| deployment / production | `NOT AUTHORIZED` |
