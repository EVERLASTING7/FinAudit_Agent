# DEP-005-R2 Backup/Restore Artifact Contract — Versioned Successor Addendum

## 1. 生效合同、冻结输入与零权限边界

### 1.1 R1 精确继承与 R2 生效公式

本文件是 `DEP-005-R2` 的 versioned successor addendum，不是
`docs/change-requests/DEP-005-backup-restore-artifact-contract.md` 的副本、重述或原地修订。R1 owner truth 以其静态 decision preimage 的唯一身份冻结：

| 字段 | 冻结值 |
| --- | --- |
| predecessor revision | `DEP-005-R1` |
| predecessor path | `docs/change-requests/DEP-005-backup-restore-artifact-contract.md` |
| predecessor preimage bytes | `121827` |
| predecessor decision snapshot SHA-256 | `d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110` |
| source baseline manifest SHA-256 | `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41` |

`DEP-005-R2 effective contract` 严格等于：上述 length/hash 唯一定位的 R1 静态第 1—8 节全部语义，加上本 addendum 第 1—8 节。验证器必须按 R1 自身 snapshot 算法独立重算 predecessor preimage；length 或 hash 任一不等即失败关闭。R1 第 9 节动态状态不进入 R2 的静态继承输入。

本 addendum 只在明确列出的 successor integration point 把 shared support identity 提升到 v2、加入 `CR-013-R1` 和八跳 lineage。未明确替换的 R1 规则、A—I 语义、环境矩阵、恢复顺序、RPO/RTO、hash DAG、测试向量要求和禁止边界全部继续生效。发生冲突时，仅本 addendum 明示的 v2 分支、版本和排序覆盖 R2 消费路径；任何覆盖都不得反向改写或重新解释 R1 bytes、R1 snapshot、v1 Schema 或既有 no-replace instance。

### 1.2 R2 自身 delta 与授权范围

本 addendum 的固有 delta 精确为：

| 字段 | 值 |
| --- | ---: |
| `api_path_delta` | `0` |
| `core_table_delta` | `0` |
| `alembic_migration_delta` | `0` |
| `operation_log_action_delta` | `0` |

该零矩阵只描述 DEP successor 治理本身，不覆盖各 source 的既有 delta；特别是 `CR-013-R1` 仍为 `0/0/1/0`。本文件不授权 Request 写入、`fixed_test_provider` 或任何 provider 网络调用、真实备份、真实恢复、migration、runtime、流量切换或 production release。

### 1.3 `CR-014-R1` review snapshot 的 package-external binding

`CR-014-R1` 不进入 source union 或 lineage。它只作为待批准的 successor review payload，由 `DEP-005-R2` 八角色 record 的签名 payload 绑定。`artifact_bindings.successor_review_binding` 是精确五键 object：

`cr014_revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256/selected_decisions`。

固定规则如下：

- `cr014_revision='CR-014-R1'`；
- `decision_snapshot_marker` 逐 byte 等于本文件第 8.3 节所定义的同一组件 marker；
- `decision_preimage_ref` 为五键 `ArtifactRef`，指向 `docs/change-requests/CR-014-shared-approval-sync-successor-closure.md` 冻结后产生的唯一 no-replace preimage；
- `decision_preimage_sha256=decision_preimage_ref.sha256`，并且必须由 package 外 verifier 从所指 raw bytes独立重算相等；
- `selected_decisions` 按下列顺序恰含八项：
  1. `CR014-D-001=R1_SNAPSHOT_AND_SOURCE_BASELINE_BINDING`
  2. `CR014-D-002=V1_IMMUTABILITY_AND_REUSE_BOUNDARY`
  3. `CR014-D-003=SOURCE_CONTRACT_APPROVAL_RECORD_V2`
  4. `CR014-D-004=V1_DETACHED_EVIDENCE_AND_SIGNER_REGISTRY_REUSE`
  5. `CR014-D-005=REQUEST_SYNC_SUCCESSOR_V2`
  6. `CR014-D-006=CR006_CR008_JOINT_AND_EFFECTIVE_SET_V2`
  7. `CR014-D-007=ORDERED_LINEAGE_AND_ACYCLIC_APPROVAL_DAG`
  8. `CR014-D-008=ZERO_AUTHORITY_AND_ZERO_DELTA`

本 addendum 的静态第 1—8 节不得预填 CR-014 preimage ref 或 hash；两者只能在 CR-014 bytes冻结后作为 package-external approval-time input提供，也不允许全零、空 string、占位符、文件名猜测或聊天批准替代。八条 `DEP-005-R2/meta_contract_only` record 必须逐字绑定同一五键 object；八条 `approved_artifact` record 必须再次逐字复用。该 object 不含 approval、signature、registry 或自身 hash；它被包含在三十键 record 删除 evidence 两键后的已签 payload 中，因此不会产生 hash/signature 环。

CR-014 的机器批准由 DEP R2 meta 的八角色集合完成，角色固定为 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test`。`frontend_ui` 不另签 CR-014；它只在后续 `CR-013-R1/contract_only` 九角色集合中形成独立 record。CR-014 snapshot 缺失、未能独立重算、八项 selection 漂移或任一 meta role 缺失时，DEP R2 meta 不成立。

## 2. `source-contract-approval-record-v2` 封闭合同

### 2.1 Schema 与精确三十键根

owner 必须新建 `docs/change-requests/artifacts/DEP-005/source-contract-approval-record-v2.schema.json`；不得覆盖 v1 文件或用 alias 兼容。Schema 使用 JSON Schema Draft 2020-12、无 remote `$ref`；解析前拒绝 duplicate key、BOM、非法 UTF-8、替换字符、NUL、非有限数和额外属性。每层 object 都必须 `additionalProperties=false` 且 `required` 精确等于 `properties`；条件缺值只用 JSON null。实例发布为 RFC 8785 JCS bytes，任何对象都不保存自身 hash。

根对象精确三十键，本文列序只用于审计，JCS 仍按 RFC 8785 排序：

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

前三个常量依次为 `source-contract-approval-record-v2/RFC8785-JCS/SHA-256`。role 封闭 enum 和全局排序仍为 `requirements_product/architecture/data_dba/backend_api/frontend_ui/ai_rag/ops/security/test`。ID、时间、hash、`ArtifactRef`、`ApprovedSchemaRef`、`ApprovalSignerRegistryRef`、decision、safe-note、环境和签名时序逐字继承 R1 第 8.2—8.4 节。

所有分支的 `source_baseline_manifest_sha256` 固定为第 1.1 节 baseline；`network_scope='none'`、`production_release_scope='none'`。`approval_record_schema_sha256` 必须等于实际 v2 Schema 无 BOM UTF-8/LF raw hash；`detached_approval_evidence_schema_sha256` 必须等于第 3 节逐字复用的 v1 detached Schema raw hash，二者都不得在本静态 addendum 中预填。

`decision='APPROVED'` 时 selected 必须按分支声明顺序等于全集且 rejected=[]；`REJECTED` 时两者必须构成全集分区且 rejected 非空。每个 required role 恰一条 record；同一 role-complete set 的 revision、scope、marker、snapshot、baseline、Schema、registry/pin、selection、delta、environment 和 branch-specific bindings 必须逐字一致。

### 2.2 v2 branch union

v2 必须保留 R1 的全部 branch 语义，再加入 DEP R2 与 CR-013。保留不表示旧 v1 record 被改写为 v2：任何 v2 record 都必须新生成并绑定实际 v2 Schema raw hash；现有或未来 v1 record 仍只由 v1 Schema解释。

| `record_kind/source_id` | revision / scope | required roles | decisions | delta `(api,core,migration,action)` |
| --- | --- | --- | --- | --- |
| `dep005_contract/DEP-005` | `DEP-005-R1/meta_contract_only` | DEP 八角色 | R1 第 8.2 节九个 `DEP5-D-*` 精确全集 | `0,0,0,0` |
| `dep005_contract/DEP-005` | `DEP-005-R1/approved_artifact` | DEP 八角色 | 同一 R1 九项全集 | `0,0,0,0` |
| `source_contract/CR-003` | `CR-003-R1/contract_only` | 九角色，含 `frontend_ui` | R1 第 8.2 节五个 `D-010..014` 精确选择 | `0,0,1,0` |
| `source_contract/CR-005` | `CR-005-R1/contract_only` | DEP 八角色 | R1 第 8.2 节八个 DOC 精确选择 | `1,0,1,1` |
| `source_contract/CR-007` | `CR-007-R1/contract_only` | DEP 八角色 | R1 第 8.2 节八个 `FILEKB-D-*` 精确选择 | `0,0,1,0` |
| `source_contract/CR-009` | `CR-009-R1/contract_only` | DEP 八角色 | R1 第 8.2 节七个 CHUNK 精确选择 | `2,0,1,1` |
| `dep005_contract/DEP-005` | `DEP-005-R2/meta_contract_only` | DEP 八角色 | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | `0,0,0,0` |
| `dep005_contract/DEP-005` | `DEP-005-R2/approved_artifact` | DEP 八角色 | 同一 R2 九项全集 | `0,0,0,0` |
| `source_contract/CR-013` | `CR-013-R1/contract_only` | 九角色，含 `frontend_ui` | 第 2.3 节八项全集 | `0,0,1,0` |
| `source_contract/CR-013` | `CR-013-R1/auth_keyring_artifact` | `backend_api,ops,security,test` | `AUTHKEY-A-001=SCHEMA_AND_MANIFEST_APPROVED` | `0,0,1,0` |

Schema 的顶层 branch selector 必须是与上表逐行一一对应的精确十个 `oneOf` leaves：DEP R1 两个scope、四个legacy source-contract、DEP R2 两个scope、CR-013两个scope。不得把两个DEP revision合并为宽松revision enum、把CR-013双scope合并后遗漏不同roles/bindings，也不得沿用v1五个source group或误计为六个分支。每个leaf必须同时约束 `record_kind/source_id/source_revision/approval_scope` 四元组及其roles、decision全集、refs、environment、bindings和delta；一个实例必须且只能命中一个leaf。

两条 DEP R1 branch 的 marker、snapshot、support-ref version、五键 DEP `artifact_bindings`、environment matrix 和所有其余约束逐字沿用 R1；它们是 legacy validation branches，不进入第 6 节 R2 lineage。CR-003/005/007/009 的 source identity、marker、snapshot、decision、role 和 delta 沿用 R1，但在 R2 closed union 中新生成的 record 必须把两个 support refs提升为 `request-sync-authorization-v2` 与 `request-sync-transition-evidence-v2`。`CR-004/CR-010` 不进入三十键 branch union，继续通过各自 v1 signed fact set进入 Request authorization和joint dependency。

### 2.3 CR-013 两个 scope

`CR-013-R1/contract_only` 的 marker 与 snapshot 必须逐字等于其冻结 review identity；snapshot SHA-256 为 `a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8`，preimage bytes为 `80973`。八项 decision 按顺序固定为：

1. `AUTHSEC-D-001=PASSWORD_HASH_AND_POLICY_PROFILE_V1`
2. `AUTHSEC-D-002=LOGIN_LOCKOUT_PROFILE_V1`
3. `AUTHSEC-D-003=JWT_KEYRING_AND_CLAIMS_PROFILE_V1`
4. `AUTHSEC-D-004=REFRESH_FAMILY_ROTATION_REPLAY_PROFILE_V1`
5. `AUTHSEC-D-005=PASSWORD_CHANGE_LOGOUT_ERROR_PROFILE_V1`
6. `AUTHSEC-D-006=P0_PERMISSION_DICTIONARY_ROLE_MAP_V1`
7. `AUTHSEC-D-007=BROWSER_TOKEN_CUSTODY_PROFILE_V1`
8. `AUTHSEC-D-008=MIGRATION_ROTATION_ROLLBACK_TEST_PROFILE_V1`

contract branch 的两个 support refs 分别固定为实际 `request-sync-authorization-v2` 与 `request-sync-transition-evidence-v2` `ApprovedSchemaRef`，`environment_scope='contract'`。`artifact_bindings` 精确四键：

`approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref`。

前三键逐字复用 R1 shared source binding；第四键是精确二键 `schema_version='auth-keyring-manifest-v1'/schema_sha256`，绑定实际 no-replace Schema raw hash。九条 record 的四键 object 必须逐字相等。

keyring artifact branch 的两个 support refs都为 null，永远不能授权 Request sync；`environment_scope` 恰一项精确二键 `environment_id/environment_class`，与目标 manifest逐字相等。`artifact_bindings` 精确十一键：

`approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256/auth_keyring_manifest_schema_ref/token_profile_version/auth_keyring_manifest_ref/auth_keyring_manifest_sha256/predecessor_current_pin_ref/predecessor_current_pin_sha256/contract_approval_record_refs/contract_approval_record_set_sha256`。

前四键等于九角色 contract set 的共同值；`token_profile_version='auth-token-v1'`；manifest ref/hash相等且指向通过已批准 Schema 的同环境 JCS。`contract_approval_record_refs` 恰含九条已验证 APPROVED record，按九角色顺序排列，digest 为 `SHA-256(RFC8785-JCS(contract_approval_record_refs))`。首版 predecessor 两字段都为 null，后续版都 non-null且解析为激活前 current pin。四条 artifact record 的十一键 object 必须逐字相等且晚于其引用的九条合同批准。

四条 artifact record完成后，按 `backend_api/ops/security/test` 顺序在 record 外组成 `artifact_approval_record_refs`，其 digest为 `SHA-256(RFC8785-JCS(refs))`；refs/digest不得写回四条 record。该集合、manifest、pin、sign-policy、transition receipt和runtime binding都不进入 Request authorization、lineage、E或joint dependency。

### 2.4 DEP R2 branch-specific bindings

DEP R2 的 `artifact_bindings` 精确六键：

`approval_signer_registry_ref/artifact_schema_set/profile_instance_set/environment_policy_instance_set/test_vector_bundle_sha256/successor_review_binding`。

- `meta_contract_only`：registry ref 与 `successor_review_binding` non-null；中间四个 artifact字段全部 null；两个 post-meta support refs和 `environment_scope` 都为 null。
- `approved_artifact`：六键全部 non-null；前五键逐字满足 R1 DEP approved-artifact矩阵，`successor_review_binding` 与八条 meta record逐字相等；两个 support refs分别固定为实际 `request-sync-authorization-v2` 与 `dep005-post-sync-baseline-attestation-v2` `ApprovedSchemaRef`；`environment_scope` 是 R1 Policy set投影得到的 non-empty exact array。

DEP R2 的 marker 是本文件第 8.3 节算法使用的唯一 marker；snapshot 必须在本文件冻结后外部生成。八条 meta和八条 artifact record分别形成 role-complete set；每组 record refs/digest按 R1 的 no-replace `ArtifactRef`、排序和 JCS规则生成，digest不写回目标 record。

## 3. v1 detached evidence 与 signer registry 的逐字复用

### 3.1 只允许复用的两个 v1 owner truth

以下文件保持原路径、原 version和原 raw bytes，不建立 v2 copy：

1. `docs/change-requests/artifacts/DEP-005/dep005-detached-approval-evidence-v1.schema.json`
2. `docs/change-requests/artifacts/DEP-005/approval-signer-registry-v1.schema.json`

逐字复用意味着 package verifier 必须对 owner path 的实际无 BOM UTF-8/LF raw bytes独立计算 identity，并与 record、evidence、registry instance、joint package和 package-external expected `ApprovalSignerRegistryRef`逐字相等。任何 byte、`$id`、version、root key、scope enum、role enum、算法或时间矩阵变化都不再是复用，必须由新的 versioned contract显式批准；不得原地修改 v1。

### 3.2 detached projection 与签名

v2 record 根仍精确三十键，因此 `source_contract_approver_decision` payload继续是目标 record 删除根 `evidence_ref/evidence_sha256` 后的精确二十八键 object。`approval_scope` 和所有 nested `artifact_bindings` 都在该 payload内；DEP R2、CR-013 contract与keyring artifact无需也禁止新增 evidence scope。签名 domain separator、hash decode、Ed25519/P-256 encoding、low-S、64-byte raw signature、时间和 no-replace `ArtifactRef`约束逐字沿用 R1 第 8.3 节。

`request_sync_authorization-v2` 的签名继续使用 v1 `request_sync_authorization_decision` scope；payload是二十三键 authorization root删除 evidence两键后的精确二十一键 object。CR-006/008 v2 joint item和aggregate仍分别使用 `joint_approver_decision/joint_aggregate`，且 projection根键数不变。复用不得扩大任何 key 的 `allowed_scopes` 或 `allowed_roles`。

### 3.3 registry 与 package-external trust pin

registry 根三键、每个 key十键、算法/公钥编码、role/scope排序、validity/revocation矩阵和禁含 private material规则逐字复用 v1。全部 v2 record和evidence必须绑定同一精确七键 `ApprovalSignerRegistryRef`，并由 package 外 authenticated verifier input提供整个 expected object；不得从待验 registry、record、signature、bundle或pin自报值推导信任。

若现有 registry instance没有某 approver/role/scope授权，只能按同一 v1 Schema创建新的 no-replace registry version并由既有 package-external trust root认证；不得改写旧 instance、绕过 scope或把聊天批准转换成 signature。registry/pin缺失只允许生成静态 snapshot和Schema candidate，不允许产生有效 meta、artifact、source、authorization或joint approval。

## 4. Request authorization 与 DEP post-sync v2

### 4.1 `request-sync-authorization-v2`

owner 必须新建 `docs/change-requests/artifacts/DEP-005/request-sync-authorization-v2.schema.json`。根保持精确二十三键：

`authorization_schema_version/canonicalization_version/hash_algorithm/authorization_id/authorization_type/source_id/source_revision/decision_snapshot_marker/decision_snapshot_sha256/source_approval_binding/pre_sync_baseline_manifest_sha256/request_sync_scope/request_paths/network_scope/production_release_scope/approved_at/expires_at/approver_id/approver_role/detached_approval_evidence_schema_sha256/approval_signer_registry_ref/evidence_ref/evidence_sha256`。

常量固定 `request-sync-authorization-v2/RFC8785-JCS/SHA-256`、`authorization_type='request_sync'`、`request_sync_scope='source_only'`、`approver_role='requirements_product'`、network/production均为 `none`。source union按声明顺序精确为：

`DEP-005/CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`。

`source_approval_binding` 保持精确十键：

`binding_kind/schema_version/schema_sha256/decision_preimage_ref/decision_preimage_sha256/required_approver_roles/decision_selections/approval_artifacts/approval_binding_sha256/approval_signer_registry_ref`。

分支约束固定为：

| source | revision | 唯一 approval source |
| --- | --- | --- |
| `DEP-005` | `DEP-005-R2` | 恰八条 v2 `approved_artifact` record |
| `CR-003` | `CR-003-R1` | 恰九条 v2 `contract_only` record |
| `CR-013` | `CR-013-R1` | 恰九条 v2 `contract_only` record；四角色 keyring artifact set禁止进入 |
| `CR-004` | `CR-004-R1` | 逐字复用 `cr004-handler-registry-approved-fact-set-v1` signed fact set |
| `CR-005` | `CR-005-R1` | 恰八条 v2 `contract_only` record |
| `CR-007` | `CR-007-R1` | 恰八条 v2 `contract_only` record |
| `CR-009` | `CR-009-R1` | 恰八条 v2 `contract_only` record |
| `CR-010` | `CR-010-R1` | 逐字复用 `cr010-scanner-registry-contract-fact-set-v1` signed fact set |

每个 authorization 只允许一个 source。record/fact-set refs按 `(sha256,bucket,object_key,version_id)` 排序且无重复，`approval_binding_sha256=SHA-256(RFC8785-JCS(approval_artifacts))`；preimage、snapshot、roles、selections、baseline、Schema、registry/pin、scope和delta必须与 source owner truth逐字相等。snapshot、preimage、合同批准或本 addendum都不能替代单独签署且未过期的 authorization。

`request_paths` 按 Unicode code point顺序恰含九项：

1. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
2. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
5. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
7. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
8. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
9. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`

Schema 只能在 DEP R2 meta role-complete approval后生成并独立复核；其真实 raw hash只能由 DEP R2 `approved_artifact` records共同绑定。authorization instance只能在目标 source的完整 signed approval set存在后生成；`approved_at < expires_at`，Request sync时还必须满足 `approved_at <= synced_at < expires_at`。

### 4.2 `dep005-post-sync-baseline-attestation-v2`

owner 必须新建 `docs/change-requests/artifacts/DEP-005/dep005-post-sync-baseline-attestation-v2.schema.json`。根保持精确二十一键：

`attestation_schema_version/canonicalization_version/hash_algorithm/attestation_id/dep_revision/decision_snapshot_sha256/approved_artifact_approval_records/approved_artifact_approval_record_set_sha256/pre_sync_baseline_manifest_sha256/post_sync_baseline_manifest_sha256/request_sync_authorization_schema_version/request_sync_authorization_schema_sha256/request_sync_authorization_ref/request_sync_authorization_sha256/request_file_count/request_files/deltas/sync_result/synced_at/generator_version/generator_source_sha256`。

常量固定 `dep005-post-sync-baseline-attestation-v2/RFC8785-JCS/SHA-256`，`dep_revision='DEP-005-R2'`。record array恰含八条不同必需 role 的 v2 APPROVED/approved-artifact record，通过同一 registry/pin、R2 snapshot和 `successor_review_binding`；set digest按完整 refs JCS计算。pre baseline固定为第1.1节 source baseline；authorization必须通过第4.1节 exact v2 Schema及DEP branch；九路径恰为第4.1节顺序；delta固定 `0/0/0/0`。

`request_files[]` 仍是第4.1节九路径的精确 `path/post_sync_raw_sha256` 二键项。`sync_result` 只允许 R1 的 `applied_and_verified/no_change_required_and_verified` 等式。失败、部分写入、路径漂移、authorization漂移或未验证写入不得发布 attestation。该实例只证明第一跳 DEP-only baseline，不等于第6节最终 aggregate baseline，也不授权后续 source同步。

### 4.3 两类 post-meta support 的生命周期

两个 v2 Schema都是 DEP R2 post-meta制品：meta批准前不得生成；生成、独立复核并形成实际 raw identity后，必须由八条 DEP R2 approved-artifact records共同绑定。Schema candidate、approved-artifact set、authorization和post-sync instance严格单向：Schema不得保存 record/instance hash，record set digest不得回写record，authorization不得回写source approval，post-sync不得回写authorization。任何环、占位 hash或live-state字段都失败关闭。

## 5. 其他 v2 support owner 边

### 5.1 强制 owner/version 矩阵

| owner | 必须新建或复用的 machine identity | 消费边界 |
| --- | --- | --- |
| `DEP-005-R2` | 新建 `source-contract-approval-record-v2`、`request-sync-authorization-v2`、`dep005-post-sync-baseline-attestation-v2`；逐字复用 v1 detached/registry | 唯一 shared source approval、authorization与first-hop owner truth |
| `CR-006-R2 + CR-008-R2` | 新建 `request-sync-transition-evidence-v2` 与 `cr006-cr008-joint-approval-record-v2` | transition source union加入CR-013；joint dependency由六项升为七项 |
| `CR-008-R2` | 新建 `operation-log-baseline-delta-attestation-v2`、`effective-api-set-v2` 及实例 | E chain由七项升为八项，effective-set绑定新aggregate baseline |
| `CR-006-R2` | 为内嵌 `CR-006-R1`、旧joint identity或旧support identity的 migration-object-manifest Schema/instance、migration implementation attestation Schema建立R2 successor | migration实例仍只在joint批准后生成 |
| `CR-006-R2/CR-008-R2` | 新建各自 companion validator与fixed-vector bundle，重绑source、recipe、results和raw identity | 证明全部跨Schema等式、八跳链和artifact-role闭集 |
| `CR-004-R1` | 逐字复用 `cr004-handler-registry-approved-fact-set-v1` | 仅作为source approval/joint fact set，不改Schema |
| `CR-010-R1` | 逐字复用 `cr010-scanner-registry-contract-fact-set-v1` | 同上 |
| `CR-013-R1` | successor meta后生成 `auth-keyring-manifest-v1` Schema | 由九角色contract set绑定；不计入DEP A—I |

`request-sync-transition-evidence-v2` 根保持v1精确十八键，source union按第6节只允许DEP之后七项 `CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`；authorization必须通过v2 exact raw Schema、同一registry/pin、九路径、期限和source approval矩阵。`request_file_count=9`，每项保持精确四键 `path/pre_raw_sha256/post_raw_sha256/change_kind`；失败或部分同步不发布 evidence。

joint v2 根保持精确十七键；`cr_bindings` 从精确四键提升为六键：原四键固定 `CR-006-R2/CR-008-R2`及各自新snapshot，新增精确五键 `successor_review_binding` 与精确四键 `dep005_r2_decision_binding`。前者必须与本文件八条 meta、八条 approved-artifact record 中的对象逐 JCS 相等；后者为 `revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256`，revision固定 `DEP-005-R2`，ref/hash必须等于本文件独立复算结果、全部 DEP R2 records、post-sync attestation、joint baseline binding与 E zero-effect中的同一身份。两个nested object都进入八个item和aggregate签名payload；动态ref/hash未生成时禁止joint candidate。`dependency_bindings` 恰七项并按 `CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010` 排序。CR-013 dependency为 `decision_preimage/CR-013-R1` 且fact-set Schema字段为null；是否批准只由对应authorization内九角色 v2 contract set证明。四角色keyring artifact branch及其runtime链禁止进入 dependency。

E v2 根保持精确二十二键，`sync_evidence_chain` 恰八项；首项绑定DEP post-sync v2，后七项绑定transition v2。`delta_records` 仍只含 `CR-006-R2/CR-008-R2` prospective joint贡献；CR-013的 migration delta已由aggregate baseline承载，不得误加入E两项delta。effective-set v2根保持精确五键，baseline和完整delta-records JCS bytes必须与E逐字相等。

### 5.2 data-plane Schema/instance 的机械提升规则

与 revision、lineage、support version/hash或joint artifact-role matrix无关且 raw bytes逐字不变的 data-plane Schema可以保持原 version，例如CR-006基础 row/chain/restore Schema、CR-008 A—D Schema与fact-schema-bundle Schema。复用只适用于确实不变的 Schema raw bytes，不适用于旧 instance、旧aggregate hash或旧artifact binding。

任何 Schema或实例一旦内嵌 R1 revision、v1 support version/hash、七source lineage或旧joint artifact-role enum，就必须创建新 version；禁止用validator兼容分支、文件名alias或只替换外部hash掩盖。即使Schema可逐字复用，基于新aggregate baseline、v2 effective set、v2 fact/source hash或v2 support ref的 A—E/fact-bundle instance也必须重新生成、赋新instance identity并重新批准；旧instance不得进入R2 joint package。

## 6. 八 source ordered lineage 与 closed union

### 6.1 唯一顺序

Request source顺序唯一固定为：

```text
DEP-005 -> CR-003 -> CR-013 -> CR-004 -> CR-005 -> CR-007 -> CR-009 -> CR-010
```

| ordinal | source / revision | approval source | sync evidence |
| ---: | --- | --- | --- |
| 1 | `DEP-005/DEP-005-R2` | 八角色 v2 approved-artifact set | `dep005-post-sync-baseline-attestation-v2` |
| 2 | `CR-003/CR-003-R1` | 九角色 v2 contract set | `request-sync-transition-evidence-v2` |
| 3 | `CR-013/CR-013-R1` | 九角色 v2 contract set；不含keyring artifact set | `request-sync-transition-evidence-v2` |
| 4 | `CR-004/CR-004-R1` | v1 signed Handler fact set | `request-sync-transition-evidence-v2` |
| 5 | `CR-005/CR-005-R1` | 八角色 v2 contract set | `request-sync-transition-evidence-v2` |
| 6 | `CR-007/CR-007-R1` | 八角色 v2 contract set | `request-sync-transition-evidence-v2` |
| 7 | `CR-009/CR-009-R1` | 八角色 v2 contract set | `request-sync-transition-evidence-v2` |
| 8 | `CR-010/CR-010-R1` | v1 signed Scanner fact set | `request-sync-transition-evidence-v2` |

首跳 `pre_baseline_manifest_sha256` 等于第1.1节 source baseline；每一后跳pre必须逐字等于前一跳post；只有第八跳post是 final aggregate baseline。source遗漏、重复、交换、部分同步、只同步CR-013、把DEP-only post冒充aggregate、插入CR-014或插入keyring artifact branch都失败关闭。

### 6.2 closed union 消费等式

`request-sync-authorization-v2.source_id` 恰为上述八项；DEP post-sync只消费第一项；transition v2只消费后七项；E v2 chain恰覆盖全部八项；joint v2 dependency恰覆盖除DEP外七项。四处集合和顺序必须来自同一owner truth，不得各自维护不同enum或排序。

CR-013的九角色contract set同时作为authorization的approval source和joint dependency的批准证明；四角色keyring artifact set只服务manifest/runtime安全链。CR-014只服务DEP meta的 `successor_review_binding`。这两个非lineage集合都不得计入source count、Request path count、E chain count、joint dependency count或effective API source count。

## 7. 无环生成、审批与同步 DAG

### 7.1 唯一顺序

1. 冻结并独立验证第1.1节R1 predecessor identity、CR-003/004/005/007/009/010/013既有snapshot与source baseline；任何旧snapshot都不改写。
2. 冻结 `CR-014-R1` 第1—8节并在其文件外生成review snapshot；随后冻结本 addendum并生成DEP R2 snapshot，最后冻结CR-006-R2/CR-008-R2 addendum并生成各自snapshot。顺序固定为CR-014→DEP-005-R2→CR-006/008-R2；CR-014只提供静态review payload，不先要求v2 approval。
3. 从冻结合同生成并复核 `source-contract-approval-record-v2` raw Schema；逐字复核两个v1 Schema，生成或选择no-replace registry instance并从package外取得authenticated seven-key pin。此时不得生成签名。
4. DEP R2八角色分别形成 `meta_contract_only` record与detached signature；所有record共同绑定本R2 snapshot、R1 predecessor identity的传递性承诺和同一CR-014五键binding。全部验证后才形成meta approval。
5. meta批准后生成并复核DEP A—I Schema/Profile/Policy/vector及第4节post-meta v2 Schema，并生成CR-013 `auth-keyring-manifest-v1` Schema；随后DEP八角色形成 `approved_artifact` record set。
6. 使用v2 source record为CR-003/005/007/009生成role-complete合同集合，验证CR-004/010既有signed fact set，并由CR-013九角色形成 `contract_only` set。任何set都只批准目标source合同。
7. 为第6节每个source分别取得 `requirements_product` 签署、未过期的source-only authorization；按唯一顺序同步九份Request并形成连续post/transition evidence，得到aggregate baseline。
8. 基于aggregate baseline、CR-006-R2/CR-008-R2 snapshots和第5节全部artifact生成R2 A—E、effective-set、fact-bundle、companion、vectors与joint candidate；八角色item signatures和aggregate signature全部验证后才构成原子joint approval。实施migration时，既有CR-003、CR-010及其他适用上游事实先落地，随后才是CR-006 `operation_logs` migration。
9. CR-013九角色合同批准后，可在独立分支生成manifest并取得四角色keyring artifact批准；pin/policy/receipt/runtime仍按CR-013自身strict CAS和包外信任链。CR-013 `token_sessions` migration必须在CR-006 `operation_logs` migration之后，其 `down_revision` 指向已落地的CR-006 migration head；CR-006 migration的 `down_revision` 只能指向CR-006之前的真实上游head，绝不能指向后置CR-013 migration。downgrade严格逆序为CR-013再CR-006再上游。该分支不阻断joint合同审批，但AUTH runtime必须等待CR-003及CR-006/008实施事实。
10. Request同步、migration、runtime、provider网络和production各自仍需独立授权；任何snapshot、Schema、record、artifact或joint approval都不能替代。

### 7.2 无环不变量

- CR-014 snapshot不依赖v2 Schema，也不是standalone approval；DEP meta签名payload单向绑定它。
- 本 addendum snapshot通过静态bytes传递性绑定R1 predecessor length/hash；R1不反向保存R2 identity。
- v2 source Schema与两个复用v1 Schema都不包含instance、record、signature或自身hash；meta只引用既有Schema/registry/pin/CR-014 preimage。
- post-meta Schema只在meta后生成；approved-artifact record只向后绑定其raw identity；record-set digest形成后不回写record。
- CR-013 contract set先于keyring artifact set；九record refs可写入四record的bindings，四record refs/digest只在四record外形成。
- authorization先绑定完整source approval，再产生detached signature；post/transition evidence只在实际同步后形成，且不回写authorization。
- E/effective-set不含joint record hash；joint最后绑定它们。joint不依赖keyring runtime；runtime只沿joint实施事实正向依赖。
- migration DAG固定为上游head到CR-006 `operation_logs`，再到CR-013 `token_sessions`；任一 `down_revision` 反指后置revision都会形成实施环并必须拒绝。
- registry trust只来自package外expected pin；registry不得自签，也不得从待验package推导。

## 8. 不可变性、snapshot 与禁止边界

### 8.1 R1/v1/no-replace 不可变规则

禁止原地修改：DEP-005-R1合同与snapshot、CR-003/004/005/006/007/008/009/010/013既有R1合同与snapshot、`source-contract-approval-record-v1`、`request-sync-authorization-v1`、`request-sync-transition-evidence-v1`、`dep005-post-sync-baseline-attestation-v1`、`cr006-cr008-joint-approval-record-v1`、E/effective-set v1、两个逐字复用Schema，以及所有已发布no-replace record/instance/signature/registry/pin。successor只创建新文件、新version和新ArtifactRef。

旧snapshot继续证明旧静态bytes，不因八跳lineage而重算；旧Schema继续只解释旧branch union，不因CR-013而扩展；旧instance继续保留历史身份，不因R2 candidate出现而转换状态。任何需要改静态字段、enum、revision、hash或artifact-role的对象都必须提升version并重新审批。

### 8.2 零授权与禁止生成

本 addendum 的静态snapshot只建立可签对象，不批准meta、artifact、CR-013、Request sync、joint、migration、runtime、provider网络或production。第1—8节不得内嵌或预填本文件decision snapshot、CR-014 snapshot/ref/hash、任一v2 Schema identity、Schema instance、approval record、detached signature、registry instance/pin、authorization、sync evidence、A—I、A—E、manifest、pin、policy、receipt、runtime binding或joint record的动态生成值。

`network_scope` 与 `production_release_scope` 在所有本 addendum定义的record/authorization中固定为 `none`。`fixed_test_provider`、内部vLLM、embedding provider、Qdrant或其他网络端点都没有授权；离线Schema校验、hash identity或fixed vector也不能替代网络、恢复、RPO/RTO、迁移、E2E或production验收。

### 8.3 唯一 decision snapshot 算法

本文件只使用以下严格算法；不得沿用R1结果或CR-014结果：

1. 读取本文件原始bytes；拒绝UTF-8 BOM、非法UTF-8、解码替换字符与NUL。
2. 把CRLF和孤立CR规范化为单个LF；不做Unicode normalization、不trim、不重排Markdown。
3. marker line的bytes为ASCII hex `23 23 20 39 2e 20`，随后依次拼接U+5F53、U+524D、U+72B6、U+6001的UTF-8 bytes。按LF分行后，内容与该序列完全相等且无前后空格的完整行必须恰好出现一次；零次或多次都失败。
4. 取marker行之前全部规范化内容；移除末尾全部LF后追加恰好一个LF。
5. 以无BOM UTF-8编码得到唯一preimage bytes；只在本文件第1—8节冻结且静态自检通过后，才可在后续独立步骤计算SHA-256并输出64位小写hex。
6. 第9节动态状态不进入preimage；第1—8节任一byte变化都必须提升revision、重算snapshot并废弃该旧R2 snapshot下全部record/signature引用。
7. snapshot计算、Schema实例化和签名都是本文冻结后的独立外部步骤；其结果不得回填第1—8节。

本文件第1—8节只陈述静态规则；审批、生成、同步和运行的当前值只允许记录在第9节。更新第9节不得暗示第1—8节的任何授权自动发生。

## 9. 当前状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| `DEP-005-R2` addendum | `FROZEN FOR REVIEW / NOT APPROVED` | 仅建立versioned successor静态候选 |
| R1 predecessor binding | `RECORDED / NOT REAPPROVED` | 只转录第1.1节既有length/hash，不重算、不改R1 |
| CR-014 review snapshot / external binding | `GENERATED_FOR_REVIEW / NOT BOUND / NOT APPROVED` | ref/hash尚未进入任何批准record |
| 本文件 decision preimage bytes | `36263` | 第1—8节唯一规范化preimage长度 |
| 本文件 decision snapshot SHA-256 | `68ac5dac456f1c28624b4002332b35422a351f1023584ee3f07933e414458eb0` | 仅review identity |
| 本文件 decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` | 未生成approval record或签名 |
| `source-contract-approval-record-v2` | `SCHEMA GENERATED / RECORDS NONE / NOT APPROVED` | raw `340459` bytes；SHA-256 `4f3bd94ca2cfd21f805e3487666796ecacc565136766db8ca93df6f22015b866`；未生成record或签名 |
| pre-meta static verifier | `PASS / APPROVAL、REGISTRY PIN、SIGNATURES NOT EVALUATED` | `backend/app/approval_pre_meta.py` 已只读复核三份Schema、十四份snapshot与source baseline；不生成record、签名、pin或同步证据 |
| v1 detached/registry reuse binding | `SCHEMAS VERIFIED / INSTANCE AND PIN NONE / NOT APPROVED` | detached raw SHA-256 `cdd04ea8bed4a411f0bd0d5aeda56ad8adb9428e3a6f72f9297bf48be9956bac`；registry Schema raw SHA-256 `d6346eba93031ede42887fc6e031dd7a60b5b0ce5f8b8dd55a21f3725715063f`；未生成registry instance、pin或signature |
| DEP R2 meta approval | `NOT GENERATED / NOT APPROVED` | 八角色record均不存在 |
| post-meta v2 Schema / DEP artifact approval | `NOT GENERATED / NOT APPROVED` | authorization与post-sync Schema均不存在 |
| CR-013 contract / keyring artifact approval | `NOT GENERATED / NOT APPROVED` | 九角色与四角色record均不存在 |
| eight-source Request authorization / sync | `NOT GENERATED / NOT APPROVED` | 未授权、未同步、无aggregate baseline |
| CR-006/008 R2 addendum snapshots | `GENERATED_FOR_REVIEW / NOT APPROVED` | 两份snapshot仅建立joint待签输入 |
| CR-006/008 R2 joint package | `NOT GENERATED / NOT APPROVED` | 无A—E/effective-set/joint candidate或签名 |
| `fixed_test_provider` / network | `NONE / NOT AUTHORIZED` | 本合同明确不授权 |
| production release | `NONE / NOT AUTHORIZED` | 本合同明确不放行 |

当前只有本 addendum的 review snapshot；不存在可消费的meta、artifact、source approval、Request sync、migration、runtime、network或production事实。
