# CR-014：Shared Approval and Request-Sync Successor Closure

## 1. 目的、冻结输入与权限边界

### 1.1 文档身份

| 项目 | 固定值 |
| --- | --- |
| CR | `CR-014` |
| revision | `CR-014-R1` |
| 日期 | `2026-08-08` |
| 主题 | 协调 `DEP-005-R2`、`CR-006-R2`、`CR-008-R2` 与 `CR-013-R1` 的 shared approval / Request-sync successor |
| source lineage 身份 | `none`；本 CR 永不成为 Request source |
| 固有 delta 顺序 | `api_path_delta/core_table_delta/alembic_migration_delta/operation_log_action_delta` |
| 固有 delta | `0/0/0/0` |

现有 shared v1 的 source union、Request-sync source union、七跳 lineage、CR-006/008 joint artifact-role matrix 和 R1 revision 常量均不含 `CR-013-R1`。本 CR 只定义不可原地改写的 successor 边界、机器对象版本、闭合分支、排序、DAG 和审批门禁；不改变任何业务合同事实。

### 1.2 永久 R1 snapshot 与 source baseline 绑定

下表是本 revision 的不可变输入。`decision_snapshot_sha256` 均为对应 R1 文件已经记录的 review preimage 身份，不是本 CR 重新计算的值，也不表示已批准。

| source | 文件 | 固定 revision | marker 身份 | preimage bytes | `decision_snapshot_sha256` |
| --- | --- | --- | --- | ---: | --- |
| `DEP-005` | `docs/change-requests/DEP-005-backup-restore-artifact-contract.md` | `DEP-005-R1` | ASCII `## 9.` + UTF-8 ` 当前状态` | `121827` | `d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110` |
| `CR-006` | `docs/change-requests/CR-006-operation-log-integrity-closure.md` | `CR-006-R1` | ASCII `## 9.` + UTF-8 ` 当前状态` | `204739` | `180b8de06ecc445d97cb734ebd884d6736cd3443fdbc364c6e4a549f2663a4be` |
| `CR-008` | `docs/change-requests/CR-008-operation-log-action-registry-closure.md` | `CR-008-R1` | `## 11. 当前决策状态` | `96741` | `2f67b69bc1dc8967f7299919a33f7b6e7253b0108ba77e9466b1613d0183f9b8` |
| `CR-013` | `docs/change-requests/CR-013-authentication-security-profile-closure.md` | `CR-013-R1` | ASCII `## 9.` + UTF-8 ` 当前状态` | `80973` | `a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8` |

source baseline 唯一固定为：

| 项目 | 固定值 |
| --- | --- |
| manifest path | `docs/baseline-manifest.md` |
| manifest raw SHA-256 | `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41` |
| Request path count | `9` |

任何 successor 都必须把上述 revision、marker、preimage length、snapshot hash 和 source baseline 当作 package 外 expected input 逐字验证。不得修改 R1 bytes、把 R1 状态段写回 preimage、用 R2 hash冒充 R1、把 snapshot 当批准，或因新 lineage 重算这些 R1 identity。

### 1.3 零授权边界

本 CR 及其未来 snapshot 均不提供下列权限：

- 不授权修改或同步 `Request/`；
- 不授权生成、代签、接受或发布任何 approval signature；
- 不授权 migration、Backend、Frontend、Worker、Redis、PostgreSQL 或 KMS/HSM 实施；
- 不授权任何 Provider、`fixed_test_provider`、内部 vLLM、Qdrant 或其他网络调用；
- 不授权 canary、部署、production release、恢复执行或数据变更；
- 不创建 secret、private key、registry key、trust anchor、环境凭据或 production evidence。

`CR-014` 不加入 `source-contract-approval-record-v2.source_id`、`request-sync-authorization-v2.source_id`、transition evidence、lineage、E、effective-set 或 joint dependency。它只作为 `DEP-005-R2` addendum 的静态 review input；机器生效必须经第 8 节后续审批链完成。

## 2. 决策全集与零 delta

### 2.1 决策全集

本 revision 的决策全集按下列顺序固定，禁止别名、范围缩写、部分选择或自由文本替代：

1. `CR014-D-001=R1_SNAPSHOT_AND_SOURCE_BASELINE_BINDING`
2. `CR014-D-002=V1_IMMUTABILITY_AND_REUSE_BOUNDARY`
3. `CR014-D-003=SOURCE_CONTRACT_APPROVAL_RECORD_V2`
4. `CR014-D-004=V1_DETACHED_EVIDENCE_AND_SIGNER_REGISTRY_REUSE`
5. `CR014-D-005=REQUEST_SYNC_SUCCESSOR_V2`
6. `CR014-D-006=CR006_CR008_JOINT_AND_EFFECTIVE_SET_V2`
7. `CR014-D-007=ORDERED_LINEAGE_AND_ACYCLIC_APPROVAL_DAG`
8. `CR014-D-008=ZERO_AUTHORITY_AND_ZERO_DELTA`

`selected_decisions` 对本 CR 的有效批准必须恰为上述八项且保持声明顺序，`rejected_decisions=[]`；拒绝时两数组必须构成八项全集的不交叉分区且 `rejected_decisions` 非空。本文件不新增 standalone CR-014 approval-record branch，避免先依赖 successor Schema 才能批准 successor 本身的环。

CR-014 snapshot 只作为待批准 payload。`DEP-005-R2` 的八角色 `meta_contract_only` records 必须通过第 8.1 节 `successor_review_binding` 逐字绑定该 snapshot和八项选择；八角色固定为 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test`。`frontend_ui` 不另签 CR-014；它在后续 `CR-013-R1/contract_only` 九角色 record set 中承担其职责。

### 2.2 固有 delta

| 字段 | 固定值 | 原因 |
| --- | ---: | --- |
| `api_path_delta` | `0` | 不新增、删除或重命名 API path |
| `core_table_delta` | `0` | 不新增或删除 core table |
| `alembic_migration_delta` | `0` | 本 CR 不拥有 migration |
| `operation_log_action_delta` | `0` | 不新增或删除 operation-log action |

该 `0/0/0/0` 只描述 CR-014 固有贡献，不覆盖 `CR-013-R1` 的 `0/0/1/0`，也不覆盖 `CR-006-R2` 自身的 core/migration贡献。任何 aggregate count 仍由获批 lineage 和 R2 E 的确定性公式产生。

## 3. v1 不可变边界、可复用项与强制 v2 项

### 3.1 v1 永久不可原地扩展

以下 identity 和已存在或未来按其生成的 raw bytes 均为 immutable legacy。它们不得增加 `CR-013`、更改 revision 常量、改变 lineage、增加 approval scope 或修改 artifact-role enum：

1. `source-contract-approval-record-v1`
2. `request-sync-authorization-v1`
3. `request-sync-transition-evidence-v1`
4. `dep005-post-sync-baseline-attestation-v1`
5. `cr006-cr008-joint-approval-record-v1`
6. `operation-log-baseline-delta-attestation-v1`
7. `effective-api-set-v1`
8. `DEP-005-R1`、`CR-006-R1`、`CR-008-R1` 的静态合同与 snapshots

其中已生成的 `source-contract-approval-record-v1.schema.json` 候选保持 `bytes=73641`、记录值 `sha256=022ce67fb2e9ed75c3acf3b00c4c6afe904678fc1ecf8facdc75032b2141e067` 的 legacy identity；它不能验证或批准 CR-013，也不能被重命名为 v2。

### 3.2 可逐字复用的 v1 approval-plane 全集

在本 successor 的 approval plane 中，允许逐字复用且不提升 version 的 Schema 只有：

1. `dep005-detached-approval-evidence-v1.schema.json`
2. `approval-signer-registry-v1.schema.json`
3. `cr004-handler-registry-approved-fact-set-v1.schema.json`
4. `cr010-scanner-registry-contract-fact-set-v1.schema.json`
5. common types：`ArtifactRef`、`ApprovedSchemaRef`、`AddressableApprovedSchemaRef`、`ApprovalSignerRegistryRef`、`Sha256`、`Uuid/UuidV4`、`UtcTimestamp`、`SafeInteger`

前两项的 immutable raw identity 记录为：

| Schema | recorded bytes | recorded SHA-256 |
| --- | ---: | --- |
| `dep005-detached-approval-evidence-v1.schema.json` | `9633` | `cdd04ea8bed4a411f0bd0d5aeda56ad8adb9428e3a6f72f9297bf48be9956bac` |
| `approval-signer-registry-v1.schema.json` | `5981` | `d6346eba93031ede42887fc6e031dd7a60b5b0ce5f8b8dd55a21f3725715063f` |

上述值只转录 owner contract 已记录的候选身份，本 CR 不重新计算。逐字复用必须满足第 5 节全部条件，并由 `DEP-005-R2` meta/approved-artifact records 绑定实际 raw identity；候选存在不等于批准。

与 revision、lineage、support identity 无关且 raw bytes 完全不变的 data-plane Schema可以保持原 version，例如 `operation-log-row-v1`、`operation-log-genesis-v1`、`audit-chain-manifest-v1`、`audit-chain-verification-event-v1`、`audit-chain-difference-v1`、`operation-log-restore-transition-evidence-v1`、A—D Schema 与 `operation-log-fact-schema-bundle-v1`。但其 R2 package 中的实例、source hash、aggregate baseline、support ref 和 artifact binding 必须重新生成和审批；旧实例不得冒充 R2 instance。任何 raw Schema 若实际内嵌 R1 revision、v1 support version/hash、七 source lineage或旧 joint artifact-role enum，就不属于本可复用集合，必须按下一节提升。

### 3.3 必须新建的 v2 与 R2 制品

以下是 successor 核心的强制新 identity，禁止用 v1 alias、兼容模式或仅改文件名替代：

1. `source-contract-approval-record-v2.schema.json`
2. `request-sync-authorization-v2.schema.json`
3. `request-sync-transition-evidence-v2.schema.json`
4. `dep005-post-sync-baseline-attestation-v2.schema.json`
5. `cr006-cr008-joint-approval-record-v2.schema.json`
6. `operation-log-baseline-delta-attestation-v2.schema.json` 与同名 v2 instance
7. `effective-api-set-v2.schema.json` 与同名 v2 instance
8. `DEP-005-R2` addendum、`CR-006-R2` addendum、`CR-008-R2` addendum及各自新 snapshot
9. 内嵌 `CR-006-R1` 的 migration-object-manifest Schema/instance 的 R2 successor
10. 内嵌 `CR-006-R1` 或旧 joint identity 的 migration implementation attestation Schema 的 R2 successor
11. CR-006/008 R2 companion validator 与 fixed-vector bundle；其 source、recipe、结果和 raw hash均重新绑定
12. A—D/E/support Schema 或实例中任何内嵌旧 support version/hash、七 source lineage、R1 revision或旧 artifact-role matrix 的对象

第 12 项是机械判定而非实现选择：命中任一旧 identity 即必须新 version；未命中且 raw bytes逐字不变的 Schema才可归入第 3.2 节。所有实例 no-replace；即使 Schema复用，基于新 aggregate baseline 或 v2 support ref 的实例也必须有新的 instance version/hash。

## 4. `source-contract-approval-record-v2` 机器合同

### 4.1 根对象与通用规则

Schema 使用 JSON Schema 2020-12、无 remote `$ref`；解析前拒绝 duplicate key、BOM、非法 UTF-8、非有限数和额外属性。每层 object 都必须 `additionalProperties=false` 且全部属性 required；条件性缺值只使用 JSON null。实例发布为 RFC 8785 JCS bytes，自身不保存自身 hash。

根对象精确三十键，顺序仅用于本文审计，JCS 仍按 RFC 8785 排序：

1. `approval_record_schema_version`
2. `canonicalization_version`
3. `hash_algorithm`
4. `record_kind`
5. `approval_record_id`
6. `source_id`
7. `source_revision`
8. `approval_scope`
9. `approver_id`
10. `approver_name`
11. `approver_role`
12. `decision`
13. `selected_decisions`
14. `rejected_decisions`
15. `decision_snapshot_marker`
16. `decision_snapshot_sha256`
17. `source_baseline_manifest_sha256`
18. `approval_record_schema_sha256`
19. `detached_approval_evidence_schema_sha256`
20. `request_sync_authorization_schema_ref`
21. `sync_evidence_schema_ref`
22. `artifact_bindings`
23. `deltas`
24. `environment_scope`
25. `network_scope`
26. `production_release_scope`
27. `decided_at`
28. `evidence_ref`
29. `evidence_sha256`
30. `safe_notes_code`

前三个常量分别为 `source-contract-approval-record-v2/RFC8785-JCS/SHA-256`。所有分支固定 `source_baseline_manifest_sha256=717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`、`network_scope=none`、`production_release_scope=none`。`approval_record_schema_sha256` 必须等于实际 v2 Schema raw hash；`detached_approval_evidence_schema_sha256` 必须等于第 5 节获批 v1 detached Schema raw hash。

`decision='APPROVED'` 时 selected 必须等于目标分支全集且 rejected为空；`REJECTED` 时二者必须构成全集分区且 rejected非空。每个 required role 恰一条；同一 record set 的 revision、marker、snapshot、baseline、Schema、registry、selection、delta和 branch-specific artifact bindings必须逐字相等。

role顺序只有两套：DEP八角色固定为 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test`；九角色固定为 `requirements_product/architecture/data_dba/backend_api/frontend_ui/ai_rag/ops/security/test`。CR-013 keyring artifact从九角色顺序过滤后固定为 `backend_api/ops/security/test`。任何别名、排序变化、缺失、重复或额外role都拒绝。

### 4.2 分支矩阵

下表是 v2 branch union 全集。`delta` 顺序固定为第 1.1 节四元组。

| `record_kind/source_id` | revision / scope | required roles | decisions | marker / snapshot | delta |
| --- | --- | --- | --- | --- | --- |
| `dep005_contract/DEP-005` | `DEP-005-R1/meta_contract_only` | `requirements_product,architecture,data_dba,backend_api,ai_rag,ops,security,test` | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | 第1.2节DEP R1 marker / `d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110` | `0/0/0/0` |
| `dep005_contract/DEP-005` | `DEP-005-R1/approved_artifact` | 同上 | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | 与R1 meta同一identity | `0/0/0/0` |
| `dep005_contract/DEP-005` | `DEP-005-R2/meta_contract_only` | `requirements_product,architecture,data_dba,backend_api,ai_rag,ops,security,test` | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | R2 addendum marker / R2 snapshot，均须外部重算 | `0/0/0/0` |
| `dep005_contract/DEP-005` | `DEP-005-R2/approved_artifact` | 同上 | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | 与 meta 同一 R2 identity | `0/0/0/0` |
| `source_contract/CR-003` | `CR-003-R1/contract_only` | 九角色，含 `frontend_ui` | `D-010=DECIDED_BY_STATE_CAS,D-011=REVOKE_REASON,D-012=GIST_HALF_OPEN_RANGE,D-013=ENV_INDEPENDENT_SOD,D-014=LONG_TERM_ADMIN_ONLY` | `## 6. 当前状态` / `cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045` | `0/0/1/0` |
| `source_contract/CR-005` | `CR-005-R1/contract_only` | DEP 八角色 | `DOC-D-001,DOC-D-002,DOC-D-003,DOC-HANDLER-DOCUMENT-CORRECTION,DOC-HANDLER-ASSET-SECURITY-REVALIDATION,DOC-CR010-SCANNER-EVIDENCE-PROJECTION,DOC-PARSE-006,DOC-MIGRATION-DOWNGRADE` | `## 8. 当前状态` / `739f2004bd6cc785d0a06a69445af2c35a373bbe1746d9ed1b194cb3f94dd029` | `1/0/1/1` |
| `source_contract/CR-007` | `CR-007-R1/contract_only` | DEP 八角色 | `FILEKB-D-001,FILEKB-D-002,FILEKB-D-003,FILEKB-D-004,FILEKB-D-005,FILEKB-D-006,FILEKB-D-007,FILEKB-D-008` | `## 8. 当前状态` / `40a38d45aeab262c2b54d65b1b95e7e6bbcbcdf3d892900d9b4150fefcf2b98e` | `0/0/1/0` |
| `source_contract/CR-009` | `CR-009-R1/contract_only` | DEP 八角色 | `CHUNK-FIELDS-JCS,CHUNK-STATE-MACHINE,CHUNK-008-009-API,CHUNK-IDEMPOTENCY-CAS,CHUNK-CURSOR,CHUNK-REVISION-OWNERSHIP,CHUNK-DOWNGRADE` | `## 10. 当前状态` / `68d002c6f851c7d18a670b992dc4c03026c4d08a67e02797735a048e44e8a597` | `2/0/1/1` |
| `source_contract/CR-013` | `CR-013-R1/contract_only` | 九角色，含 `frontend_ui` | `AUTHSEC-D-001..008` 的第 4.3 节精确展开 | 本文第 1.2 节 CR-013 marker / `a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8` | `0/0/1/0` |
| `source_contract/CR-013` | `CR-013-R1/auth_keyring_artifact` | `backend_api,ops,security,test` | `AUTHKEY-A-001=SCHEMA_AND_MANIFEST_APPROVED` | 与 CR-013 contract branch 同一 identity | `0/0/1/0` |

`CR-004` 和 `CR-010` 不进入该表；它们继续分别通过 `cr004-handler-registry-approved-fact-set-v1` 与 `cr010-scanner-registry-contract-fact-set-v1` 的八角色 signed fact set进入 Request authorization和joint dependency。

两个 DEP-005-R1 branch只在v2 closed union中保留既有矩阵和无别名验证能力：实际v1 record仍只能按v1 Schema验证，不得重新解释为v2 bytes；新R2链的DEP authorization、post-sync、lineage、E和joint均只接受 `DEP-005-R2` branch，R1 branch不能满足或降级替代。

### 4.3 CR-013 决策与 artifact binding

CR-013 `contract_only` 的八项全集按原合同顺序逐字为：

1. `AUTHSEC-D-001=PASSWORD_HASH_AND_POLICY_PROFILE_V1`
2. `AUTHSEC-D-002=LOGIN_LOCKOUT_PROFILE_V1`
3. `AUTHSEC-D-003=JWT_KEYRING_AND_CLAIMS_PROFILE_V1`
4. `AUTHSEC-D-004=REFRESH_FAMILY_ROTATION_REPLAY_PROFILE_V1`
5. `AUTHSEC-D-005=PASSWORD_CHANGE_LOGOUT_ERROR_PROFILE_V1`
6. `AUTHSEC-D-006=P0_PERMISSION_DICTIONARY_ROLE_MAP_V1`
7. `AUTHSEC-D-007=BROWSER_TOKEN_CUSTODY_PROFILE_V1`
8. `AUTHSEC-D-008=MIGRATION_ROTATION_ROLLBACK_TEST_PROFILE_V1`

branch-specific矩阵固定：

| branch | `request_sync_authorization_schema_ref` | `sync_evidence_schema_ref` | `environment_scope` | `artifact_bindings` |
| --- | --- | --- | --- | --- |
| DEP R1 meta | null | null | null | 逐字保留v1精确五键 `approval_signer_registry_ref/artifact_schema_set/profile_instance_set/environment_policy_instance_set/test_vector_bundle_sha256`；后四键为null |
| DEP R1 approved artifact | `request-sync-authorization-v1` | `dep005-post-sync-baseline-attestation-v1` | non-empty exact `EnvironmentScope` | 同一v1五键，全部non-null；只服务legacy R1 branch |
| DEP R2 meta | null | null | null | 精确六键 `approval_signer_registry_ref/artifact_schema_set/profile_instance_set/environment_policy_instance_set/test_vector_bundle_sha256/successor_review_binding`；后四个 artifact字段为null，binding non-null |
| DEP R2 approved artifact | `request-sync-authorization-v2` | `dep005-post-sync-baseline-attestation-v2` | non-empty exact `EnvironmentScope` | 同一六键；五类 artifact与 binding全部 non-null |
| CR-003/005/007/009 contract | `request-sync-authorization-v2` | `request-sync-transition-evidence-v2` | `contract` | 精确三键 `approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256` |
| CR-013 contract | `request-sync-authorization-v2` | `request-sync-transition-evidence-v2` | `contract` | 精确四键 `approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref` |
| CR-013 keyring artifact | null | null | 恰一项 `{environment_id,environment_class}` | 下述精确十一键 |

CR-013 keyring artifact bindings逐字为：`approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref/token_profile_version/auth_keyring_manifest_ref/auth_keyring_manifest_sha256/predecessor_current_pin_ref/predecessor_current_pin_sha256/contract_approval_record_refs/contract_approval_record_set_sha256`。前四键必须等于九角色 contract set 的共同值；profile固定 `auth-token-v1`；contract refs恰为九条已验证 APPROVED record，按九角色顺序排列。首版两个 predecessor字段均为null，后续版均非null并解析为激活前 current pin。四条 artifact record 的十一键逐字相等，且不得早于其引用的九条合同批准。

artifact record refs按 `backend_api/ops/security/test` 顺序组成外部数组，其 digest不写回四条记录。keyring artifact set 不得进入 Request authorization、transition evidence、lineage、E或joint dependency。

## 5. v1 detached evidence 与 signer registry 的逐字复用

### 5.1 Detached evidence

`dep005-detached-approval-evidence-v1` 根保持精确十五键：`evidence_schema_version/canonicalization_version/hash_algorithm/evidence_scope/approval_id/approver_role/approval_payload_sha256/signature_algorithm/signature_encoding/signer_registry_version/signer_registry_sha256/key_id/signature_ref/signature_sha256/signed_at`。七值 scope enum、签名 message、algorithm/encoding矩阵、64-byte signature和 ArtifactRef规则全部保持 v1 owner contract不变。

CR-013 两种 scope 均使用既有 `evidence_scope=source_contract_approver_decision`。payload 是目标 v2 三十键 shared record 删除根 `evidence_ref/evidence_sha256` 后的精确二十八键 object。二十八键中已经包含 `approval_record_schema_version`、`approval_record_schema_sha256`、`record_kind`、`source_id`、`source_revision`、`approval_scope`、角色、decision、snapshot、environment、delta和完整 artifact bindings，因此：

- v1 record签名不能重放为 v2 record；
- `contract_only` 不能重放为 `auth_keyring_artifact`；
- 一个 source/revision/environment/role不能重放到另一个；
- evidence字段不进入自己的 payload，不形成签名环。

`approval_id/approver_role/signed_at` 必须分别等于目标 record 的 `approval_record_id/approver_role/decided_at`。payload hash必须从唯一不可变解析结果的 RFC 8785 JCS重算；禁止签原始非规范 JSON、hex ASCII摘要、缺字段投影或另一 record的同名字段。

### 5.2 Signer registry

`approval-signer-registry-v1` 根保持精确三键 `schema_version/registry_version/keys`；每个 key保持精确十键 `key_id/approver_id/algorithm/public_key_encoding/public_key/allowed_roles/allowed_scopes/valid_from/valid_until/revoked_at`。本 successor 不增加 allowed scope；CR-013 两种 record都消费既有 `source_contract_approver_decision`。

逐字复用必须同时满足：

1. Schema raw bytes和实际 hash与第 3.2 节获批 identity相等；
2. registry instance no-replace，且通过 package 外 authenticated `ApprovalSignerRegistryRef` 与 expected trust-anchor pin验证；
3. key的 `approver_id`、目标 role和 `source_contract_approver_decision` scope同时匹配；新增 branch不得隐式扩大 key权限；
4. `valid_from <= signed_at`，且未到 `valid_until/revoked_at`；
5. registry和pin不能从待验 record、signature、joint package或artifact bundle自报或推导；
6. registry不得包含 private key、certificate chain、secret或额外字段；
7. 当前 candidate Schema或未来 registry instance只有在 DEP R2 meta/approved-artifact record共同绑定后才可消费。

若既有 key没有目标 role或 scope授权，只能按同一 v1 Schema创建并外部认证新的 registry version；不得修改旧 key、忽略 `allowed_scopes` 或把全部权限主体的聊天批准转换为 signature。

## 6. Request sync、post-sync、joint、E 与 effective-set v2

### 6.1 `request-sync-authorization-v2`

根保持精确二十三键：`authorization_schema_version/canonicalization_version/hash_algorithm/authorization_id/authorization_type/source_id/source_revision/decision_snapshot_marker/decision_snapshot_sha256/source_approval_binding/pre_sync_baseline_manifest_sha256/request_sync_scope/request_paths/network_scope/production_release_scope/approved_at/expires_at/approver_id/approver_role/detached_approval_evidence_schema_sha256/approval_signer_registry_ref/evidence_ref/evidence_sha256`。

常量固定 `request-sync-authorization-v2/RFC8785-JCS/SHA-256`、`authorization_type=request_sync`、`request_sync_scope=source_only`、`approver_role=requirements_product`、network/production均为 `none`。source union按 lineage声明顺序只允许 `DEP-005/CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`，其中 DEP revision为R2，其余采用第 7.1 节固定 revision/snapshot。

`source_approval_binding` 保持精确十键 `binding_kind/schema_version/schema_sha256/decision_preimage_ref/decision_preimage_sha256/required_approver_roles/decision_selections/approval_artifacts/approval_binding_sha256/approval_signer_registry_ref`：

- DEP绑定恰八条 `DEP-005-R2/approved_artifact` v2 records；
- CR-003/005/007/009绑定各自完整 v2 `contract_only` record set；
- CR-013只绑定九角色 `contract_only` set，明确拒绝四角色 keyring artifact set；
- CR-004/010分别绑定既有 v1 signed fact set；
- 所有 refs按 v2 owner truth的 ArtifactRef tuple排序，binding digest从完整数组 JCS计算；
- snapshot/preimage、record set、registry/pin、Schema、角色、selection、delta或scope任一不等都拒绝。

`request_paths` 按 Unicode code point顺序恰含：

1. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
2. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
5. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
7. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
8. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
9. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`

authorization evidence继续使用 v1 detached Schema 的 `request_sync_authorization_decision` scope，payload为二十三键根删除 evidence两键后的精确二十一键 object。授权必须满足 `approved_at < expires_at`；snapshot、合同批准或本 CR 都不能替代该独立签名授权。

### 6.2 `request-sync-transition-evidence-v2`

根保持精确十八键：`schema_version/canonicalization_version/hash_algorithm/source_id/source_revision/decision_snapshot_sha256/sync_authorization_schema_version/sync_authorization_schema_sha256/sync_authorization_ref/sync_authorization_sha256/pre_baseline_manifest_sha256/post_baseline_manifest_sha256/request_file_count/request_files/sync_result/synced_at/generator_version/generator_source_sha256`。

source union恰为 DEP之后七项：`CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`。authorization必须通过 v2 exact Schema和第 6.1 节全部 record/fact-set、registry/pin、九路径、期限、scope矩阵；`approved_at <= synced_at < expires_at`。`request_file_count=9`；每项 `request_files[]` 精确四键 `path/pre_raw_sha256/post_raw_sha256/change_kind`，按第 6.1 节路径顺序且恰覆盖九项。

`unchanged` 当且仅当 pre=post；`modified` 当且仅当不等。result只允许 `applied_and_verified` 或 `no_change_required_and_verified` 的原有封闭矩阵。失败、部分写入、未验证写入或 baseline断链不得发布 evidence。

### 6.3 `dep005-post-sync-baseline-attestation-v2`

根保持精确二十一键：`attestation_schema_version/canonicalization_version/hash_algorithm/attestation_id/dep_revision/decision_snapshot_sha256/approved_artifact_approval_records/approved_artifact_approval_record_set_sha256/pre_sync_baseline_manifest_sha256/post_sync_baseline_manifest_sha256/request_sync_authorization_schema_version/request_sync_authorization_schema_sha256/request_sync_authorization_ref/request_sync_authorization_sha256/request_file_count/request_files/deltas/sync_result/synced_at/generator_version/generator_source_sha256`。

`dep_revision=DEP-005-R2`；record array恰含八条 v2 approved-artifact record并通过同一 registry/pin和 `successor_review_binding`；pre baseline固定为第 1.2 节 source baseline；authorization固定 v2并验证 DEP branch；paths恰九项；delta固定 `0/0/0/0`。它只证明 DEP first-hop同步，不能冒充最终 aggregate baseline。

### 6.4 `cr006-cr008-joint-approval-record-v2`

根保持精确十七键：`record_schema_version/canonicalization_version/hash_algorithm/approval_id/decision/decision_scope/approvals/cr_bindings/baseline_binding/artifact_bindings/dependency_bindings/deltas_and_counts/scope/decided_at/evidence_ref/evidence_sha256/safe_notes_code`。

固定变化只有机器身份和闭合集合：

- `cr_bindings` 从 v1 精确四键提升为精确六键：原 `cr006_revision/cr006_decision_snapshot_sha256/cr008_revision/cr008_decision_snapshot_sha256` 四键绑定 `CR-006-R2/CR-008-R2` 及各自新 snapshot；新增 `successor_review_binding` 和 `dep005_r2_decision_binding` 两个 nested object；
- `successor_review_binding` 精确复用第 8.1 节五键 object，并与 DEP R2 八条 meta、八条 approved-artifact record 中的对象逐 JCS 相等；`dep005_r2_decision_binding` 精确四键 `revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256`，revision 固定 `DEP-005-R2`，ref 为五键 `ArtifactRef`，显式 hash 等于 ref.sha256、按本 addendum 算法独立复算值、全部 DEP R2 records、post-sync attestation、`baseline_binding.dep005_decision_snapshot_sha256` 和 E.`dep005_zero_effect` 中的同名身份；
- 两个 nested object 都进入八个 joint item 的十三键 payload和根 aggregate 的十五键 payload；joint source baseline必须等于第 1.2 节与 DEP R2 冻结的同一 baseline。任一动态 ref/hash 尚未生成时，不得填 null、全零或 placeholder，也不得生成 joint candidate；
- `decision_scope` 仍完整划分 `OPLOG-D-001..006` 与 `OPLREG-D-001..006`；
- `approvals[]` 仍按 DEP八角色各一项，全部通过 v1 detached `joint_approver_decision`；根使用 `joint_aggregate` service key；
- `dependency_bindings[]` 恰七项，按 `CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010` 排序；
- CR-013 dependency固定 `decision_preimage/CR-013-R1`，两个 fact-set Schema字段为null；它的批准事实只由对应 authorization中九角色 v2 contract set证明；
- CR-013四角色 keyring artifact set、current pin、sign policy、transition receipt和runtime binding均不得进入 joint dependency；
- artifact roles必须绑定第 3.3 节全部 v2 Schema/instance、复用的 v1 Schema/instance、DEP R2 approved-artifact records、registry/pin、DEP post-sync attestation、R2 A—E/effective-set/fact-bundle、companion/vector和Handler bundle；
- migration implementation attestation instance仍在批准后生成，不进入该 joint record。

joint item payload、aggregate payload、signature message和 signer registry全部逐字复用 v1规则。joint candidate、E或effective-set不能自称批准；只有同一 no-replace joint root的八角色和aggregate signatures全部验证通过才构成原子联合批准。

### 6.5 E v2

`operation-log-baseline-delta-attestation-v2` 根保持精确二十二键：`schema_version/attestation_version/observation_point/source_baseline_manifest_sha256/dep005_post_sync_baseline_attestation_schema_sha256/dep005_post_sync_baseline_attestation_ref/dep005_post_sync_baseline_attestation_sha256/dep005_post_sync_baseline_manifest_sha256/post_all_upstream_sync_baseline_manifest_sha256/sync_evidence_chain/baseline_source_bindings/baseline_counts/delta_records/effective_api_set_version/effective_api_set_schema_sha256/effective_api_set_sha256/effective_counts/artifact_bindings/generator/companion_validator_sha256/test_vector_bundle_sha256/dep005_zero_effect`。

v2固定要求：

- observation point为 R2 joint批准前的 prospective/unsynced目标；candidate不得读取live approval状态改写；
- `sync_evidence_chain` 恰八项并按第 7.1 节顺序，首项为 DEP R2 post-sync attestation，其余七项为 v2 transition evidence；
- `delta_records` 恰两项 `CR-006-R2/CR-008-R2`，snapshot与joint `cr_bindings` 相等；status仍固定 prospective joint approval与unsynced语义；
- CR-006和CR-008的 API add/remove均为空；core contribution仍分别为 `+1/0`；
- `dep005_zero_effect` 绑定 DEP-005-R2 snapshot、`no_new_action=true`、action delta 0和 no-replace artifact carrier；
- CR-013的 `0/0/1/0` 已在 aggregate baseline，不是 E 两项 prospective delta，也不新增 operation-log action；
- A—D、fact bundle、companion和vectors都从最终 aggregate baseline及R2 inputs重新生成、绑定；不得复用旧实例hash；
- E不保存自身hash或joint record hash，joint从外部绑定E，保持单向。

### 6.6 `effective-api-set-v2`

根保持精确五键 `schema_version/set_version/baseline_manifest_sha256/delta_records/apis`，其中 schema常量为 `effective-api-set-v2`。baseline必须等于E的最终 aggregate baseline；`delta_records` 整个 JCS array bytes必须与E逐字相等；`apis[]` 每项精确五键 `api_id/method/path_template/source_contract_id/source_contract_sha256`，按 `(api_id,method,path_template)` 排序且api_id唯一。

由于 R2 joint的四个 API add/remove arrays均为空，effective API set必须逐字等于已经包含全部八跳 source同步结果的 aggregate baseline API set。B和E必须绑定同一 v2 Schema raw hash、set version和instance hash。joint批准前该实例不可被runtime、migration或Request sync消费。

## 7. Ordered lineage 与无环 DAG

### 7.1 唯一 lineage

Request source顺序唯一固定为：

```text
DEP-005 -> CR-003 -> CR-013 -> CR-004 -> CR-005 -> CR-007 -> CR-009 -> CR-010
```

逐跳 identity 固定：

| ordinal | source/revision | marker identity | snapshot identity | approval source | sync evidence |
| ---: | --- | --- | --- | --- | --- |
| 1 | `DEP-005/DEP-005-R2` | R2 addendum的第8.3节组件marker | R2 addendum freeze后生成 | 八角色 v2 approved-artifact set | `dep005-post-sync-baseline-attestation-v2` |
| 2 | `CR-003/CR-003-R1` | `## 6. 当前状态` | `cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045` | 九角色 v2 contract set | transition v2 |
| 3 | `CR-013/CR-013-R1` | 第1.2节CR-013 marker | `a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8` | 九角色 v2 contract set；不含keyring artifact set | transition v2 |
| 4 | `CR-004/CR-004-R1` | `## 6. 当前状态` | `387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6` | v1 signed Handler fact set | transition v2 |
| 5 | `CR-005/CR-005-R1` | `## 8. 当前状态` | `739f2004bd6cc785d0a06a69445af2c35a373bbe1746d9ed1b194cb3f94dd029` | 八角色 v2 contract set | transition v2 |
| 6 | `CR-007/CR-007-R1` | `## 8. 当前状态` | `40a38d45aeab262c2b54d65b1b95e7e6bbcbcdf3d892900d9b4150fefcf2b98e` | 八角色 v2 contract set | transition v2 |
| 7 | `CR-009/CR-009-R1` | `## 10. 当前状态` | `68d002c6f851c7d18a670b992dc4c03026c4d08a67e02797735a048e44e8a597` | 八角色 v2 contract set | transition v2 |
| 8 | `CR-010/CR-010-R1` | `## 8. 当前状态` | `17877a4cef3ca0a145f32ac06acf44e7fb65b49c06dec710a04a6078aca319de` | v1 signed Scanner fact set | transition v2 |

每跳 `pre_baseline_manifest_sha256` 必须等于前一跳 `post_baseline_manifest_sha256`；首跳pre等于第1.2节source baseline，末跳post才是aggregate baseline。source遗漏、重复、交换、部分同步、用DEP-only post冒充aggregate或插入CR-014都失败关闭。

### 7.2 无环 DAG

```text
CR-014-R1 static snapshot
  -> DEP-005/CR-006/CR-008 R2 addendum snapshots
  -> source-contract-approval-record-v2 + reused detached/registry Schema
  -> DEP-005-R2 eight-role meta records
  -> post-meta v2 Schemas + DEP approved-artifact bundle
  -> DEP-005-R2 eight-role approved-artifact records
  -> CR-013 auth-keyring-manifest Schema + nine-role contract records
     -> CR-013 four-role keyring artifact records -> pin/policy/receipt/runtime branch
     -> ordered eight-source authorization and sync chain
        -> aggregate baseline
        -> CR-006/008 R2 A-E/effective-set/companion/vectors
        -> CR-006/008 R2 atomic joint approval
        -> separately authorized implementation and Request sync
        -> CR-013 runtime only after CR-003 and CR-006/008 facts are deployed
```

箭头只表示单向输入依赖。无环不变量：

1. CR-014 snapshot不是approval record，也不依赖 v2 Schema；DEP R2 meta record通过自身R2 snapshot间接绑定它；
2. DEP meta approval先于post-meta Schema和approved-artifact approval；
3. CR-013 contract approval只绑定keyring Schema，不依赖keyring manifest/current pin/runtime；
4. joint只依赖CR-013合同批准和sync，不依赖四角色keyring artifact或AUTH runtime；
5. AUTH runtime依赖已落地CR-003和CR-006/008，因此只有 joint -> implementation -> runtime 的正向边；
6. 任何 Schema、record、signature、instance、pin、E或joint都不保存自身hash；下游hash不得回写上游；
7. signer registry trust只来自package外expected pin，registry不得自签或从待验package推导。

## 8. R2 addendum snapshot、审批顺序与生成门禁

### 8.1 R2 addendum 与 `successor_review_binding`

R2 必须以新 addendum bytes保留R1 owner truth，不得改写现有R1文件。三个 addendum 各自至少绑定：自身R1 revision/snapshot、第1.2节source baseline、`CR-014-R1` revision/snapshot、适用R1 decision全集、本CR八项decision、v1/v2版本边界和零授权声明。

DEP R2 `meta_contract_only` 与 `approved_artifact` 的 `artifact_bindings.successor_review_binding` 精确五键：`cr014_revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256/selected_decisions`。值固定规则为：

- `cr014_revision='CR-014-R1'`；
- marker是第8.3节由三个组件拼接的完整行；
- `decision_preimage_ref` 为五键 `ArtifactRef`，指向本文件唯一 no-replace preimage bytes；
- `decision_preimage_sha256=decision_preimage_ref.sha256`，并须按第8.3节独立重算相等；
- `selected_decisions` 恰为第2.1节八项声明顺序数组。

八条DEP meta records的该五键object必须逐字相等；approved-artifact records必须再次逐字复用相同object。binding不含approval、signature、registry或自身hash，不构成环。CR-006/008 R2 的 joint `cr_bindings` 必须以第 6.4 节精确六键直接签入同一 CR-014 snapshot和DEP R2 snapshot，不创建第二种successor identity。

### 8.2 唯一生成和审批顺序

1. 冻结本文件第1～8节；按第8.3节生成 `CR-014-R1` snapshot。此步只产生静态review identity。
2. 先新建并冻结 DEP-005-R2 addendum并生成其 snapshot；随后冻结 CR-006-R2、CR-008-R2 addendum。两份 operation-log addendum通过第6.4节六键 `cr_bindings` 规则直接绑定本CR与DEP R2 snapshot，并传递性验证第1.2节四份R1 identity、source baseline和对应R1 decisions；分别生成新 snapshot。顺序固定为 CR-014 → DEP-005-R2 → CR-006/008-R2，不得交换。
3. 生成并独立复核 `source-contract-approval-record-v2`；逐字复核可复用v1 detached/registry Schema，生成唯一no-replace registry instance并从package外取得authenticated pin。此时不得生成签名。
4. DEP-005-R2八角色各自生成 `meta_contract_only` record和detached signature；全部验证通过后才形成meta approval。缺一角色、拒绝、binding/hash不同或pin不匹配即不批准。
5. meta approval后生成并复核第3.3节post-meta v2 Schema、DEP artifact Schema/Profile/Policy/vector bundle及CR-013 `auth-keyring-manifest-v1` Schema；随后DEP八角色形成 `approved_artifact` records。
6. 使用v2 source record为CR-003/005/007/009形成各自role-complete合同集合；使用既有fact-set Schema验证CR-004/010 signed sets；CR-013九角色形成 `contract_only` set。任何set只批准其source合同，不授权同步。
7. 为每个source单独取得第6.1节authorization，按第7.1节顺序同步并生成连续post/transition evidence；完成后形成唯一aggregate baseline。CR-014不参与此步。
8. 基于aggregate baseline和CR-006/008 R2 snapshots生成R2 A—E、effective-set、fact bundle、companion、vectors及joint candidate；八角色item signatures和aggregate signature全部验证后才形成原子joint approval。
9. CR-013九角色合同批准后，可在独立分支生成manifest并取得四角色keyring artifact批准；该分支不阻塞joint合同审批，但任何AUTH runtime必须等待CR-003与CR-006/008实施事实及CR-013全部安全gate。
10. Request同步、migration、runtime、网络和production仍各需独立授权；上述任何snapshot、Schema、artifact或approval都不能替代。

### 8.3 唯一 snapshot 算法

本文件及三个R2 addendum都使用以下严格算法；每个文件独立执行并记录自己的结果：

1. 读取原始bytes；拒绝UTF-8 BOM、非法UTF-8、解码替换字符或NUL。
2. 把CRLF与孤立CR规范化为单个LF；不做Unicode normalization、不trim、不重排Markdown。
3. marker bytes依次由ASCII `## 9.`、一个ASCII space和UTF-8 `当前状态`拼接；按LF分行后，内容与这些bytes完全相等且无前后空格的完整行必须恰好出现一次，零次或多次都失败。
4. 取marker行之前全部规范化内容；移除末尾全部LF后追加恰好一个LF。
5. 以无BOM UTF-8编码得到唯一preimage bytes；只在文件冻结且静态自检通过后计算SHA-256并输出64位小写hex。
6. 第9节状态不进入preimage；第1～8节任一byte变化都必须提升revision、重算并清空旧record/signature引用。
7. 生成snapshot只建立可签对象，不批准任何Schema、artifact、Request同步、实现、网络或production。

第5步属于静态合同冻结后的独立生命周期动作；计算结果只能记录在第9节及外部 no-replace binding中，不得回填第1—8节。

## 9. 当前状态

| 项目 | 当前值 |
| --- | --- |
| CR-014 revision | `CR-014-R1` |
| static contract | `FROZEN FOR REVIEW` |
| decision preimage bytes | `40628` |
| decision snapshot SHA-256 | `a0a5c71cbdd1b881a6572ac994d76bca942191ba388f2a1b6e5c15c0d236c830` |
| decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` |
| approval | `NOT APPROVED` |
| decision set | `CR014-D-001..008 / REVIEW CANDIDATE` |
|固有 delta | `0/0/0/0` |
| R1 snapshot/source baseline binding | `DEFINED / NOT APPROVED` |
| DEP-005-R2 / CR-006-R2 / CR-008-R2 addendum snapshots | `GENERATED_FOR_REVIEW / NOT APPROVED` |
| shared v2 Schema / instances | `SOURCE RECORD SCHEMA GENERATED / INSTANCES NONE / NOT APPROVED`；`source-contract-approval-record-v2.schema.json` raw `340459` bytes，SHA-256 `4f3bd94ca2cfd21f805e3487666796ecacc565136766db8ca93df6f22015b866`；post-meta v2 Schema 均未生成 |
| pre-meta static verifier | `PASS / APPROVAL, REGISTRY PIN AND SIGNATURES NOT EVALUATED`；`backend/app/approval_pre_meta.py` 已只读复核三份Schema、十四份snapshot与source baseline；不生成record、签名、pin或同步证据 |
| reusable v1 detached/registry Schema | `SCHEMAS VERIFIED / REGISTRY INSTANCE AND PIN NONE / NOT APPROVED`；detached raw SHA-256 `cdd04ea8bed4a411f0bd0d5aeda56ad8adb9428e3a6f72f9297bf48be9956bac`，registry Schema raw SHA-256 `d6346eba93031ede42887fc6e031dd7a60b5b0ce5f8b8dd55a21f3725715063f` |
| approval records / detached signatures / aggregate signature | `NONE / NOT GENERATED` |
| Request edits / sync authorization / transition evidence | `NONE / NOT AUTHORIZED` |
| migration / Backend / Frontend / Worker / database implementation | `NOT AUTHORIZED` |
| Provider / fixed_test_provider / internal vLLM / Qdrant / network | `NOT AUTHORIZED / NOT CALLED` |
| canary / deployment / production release | `NOT AUTHORIZED` |
| secret / private key / production evidence | `NONE` |
