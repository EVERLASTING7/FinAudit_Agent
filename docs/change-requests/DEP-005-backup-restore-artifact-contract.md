# DEP-005-R1：备份、恢复与证据制品元合同

> 文档性质：可独立审批的静态元合同；审批状态只记录在第 9 节或外部审批记录中，不改写静态规范  
> 合同修订：`DEP-005-R1`  
> 编制日期：`2026-08-07`  
> 适用范围：合同与九类机器制品 Schema 的静态定义；不授权执行备份、恢复、迁移、网络调用、Request 同步或生产放行  
> 决策快照范围：本静态头与第 1—8 节；第 9 节为可变状态区，不进入 snapshot preimage

## 1. 变更原因、事实基线与边界

### 1.1 变更原因

现有 DEP-005 任务只给出备份、恢复和演练目标，不能唯一生成可验证的备份、恢复输入、恢复结果和放行证据，也不能闭合 CR-006 的 operation-log 恢复分叉接口或 CR-008 的零 action delta。本合同把这些前置条件冻结为九类机器制品、单向依赖、严格类型、状态矩阵和审批边界。

### 1.2 源基线

| 项目 | 本合同绑定值 |
| --- | --- |
| 正式需求源基线 | `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` 及其直接依赖文档 |
| source baseline manifest | `docs/baseline-manifest.md` |
| source baseline manifest SHA-256 | `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41` |
| `/api/v1` path delta | `0` |
| core table delta | `0` |
| Alembic migration delta | `0` |
| operation-log action delta | `0`；见 DEP5-D-008 |

该 hash 是本修订作出决策时的历史源基线，不得在后续 Request 同步后重新解释为“当前 baseline”。获授权同步 DEP-005 后必须另行生成 `post_sync_baseline_manifest_sha256` 留证；它不回写本文件第 1—8 节。最终 API、表和 action 总数由各自单一事实来源及已批准 delta ledger 计算，DEP-005 只贡献上表四个零 delta。

### 1.3 范围

本合同负责：

1. PostgreSQL 单一 MVCC snapshot、确定性备份 Profile、数据库 manifest 和事实校验；
2. 非秘密加密 Profile 及数据库与对象副本的加密绑定；
3. MinIO 精确版本 inventory、独立副本、audit-evidence 边界和 Qdrant snapshot subtype；
4. operation-log 源三态与目标三种 transition；
5. Qdrant snapshot 恢复或从 PostgreSQL 事实重算；
6. 环境恢复策略、恢复输入、pre-traffic 验证和流量放行证明；
7. 与 CR-006、CR-008 及 Request 同步的无环顺序。

本合同不负责：

- 新增 API、数据库表、Alembic migration 或 operation-log action；
- 生成真实密钥、真实业务备份或任何运行时制品；
- 调用 `fixed_test_provider`、内部 vLLM、embedding provider、Qdrant 或其他网络服务；
- 执行生产备份、生产恢复、生产流量切换或 production release；
- 修改或同步 `Request/`。

### 1.4 规范用语

- “必须”表示 approved artifact、实现和运行证据不可偏离的要求。
- “不得”表示 fail-closed 门禁。
- “PENDING”只表示尚未生成或尚未批准，不是默认值。
- 本文件中的“批准 Profile/Policy 引用”只绑定非秘密 version/schema hash/instance hash，不包含 secret。

## 2. DEP5-D-001—009 决策集

| 决策 ID | 决策 | 约束与用户影响 |
| --- | --- | --- |
| `DEP5-D-001` | DEP-005 是独立静态元合同，绑定第 1.2 节源基线；API/core table/migration/action delta 均为 `0`。 | 不因备份实现或其他 CR 的增量产生契约漂移。 |
| `DEP5-D-002` | PostgreSQL 事实备份来自一个持续存活的导出 MVCC snapshot；WAL LSN 仅作诊断。 | dump、数据库事实引用和 operation-log tail 属于同一数据库可见性边界。 |
| `DEP5-D-003` | 数据库制品和每个独立对象副本均使用批准的认证加密 Profile；key 永不进入制品、日志或审批记录。 | 备份可验证、可轮换且文档不泄密。 |
| `DEP5-D-004` | MinIO inventory 绑定数据库 snapshot 的事实引用，audit-evidence 使用独立冻结边界；所有源对象解析到精确 version，并复制到隔离、no-replace 的目标。 | 恢复不会引用缺失、被覆盖或不确定版本。 |
| `DEP5-D-005` | database manifest 精确表达 `chain_absent`、`initialized_unsealed`、`sealed`；恢复分别产生 `fresh_genesis`、`snapshot_tail_fork`、`day_anchor_fork`。 | 三种源状态均有唯一、可验证且不伪造历史的目标状态。 |
| `DEP5-D-006` | 恢复只能进入经受信 preflight 证明为空且隔离的目标；按固定顺序执行，发布不可变 pre-traffic verification 后才可进入独立 release 决策。 | 防止覆盖现有环境和修改已发布验证制品。 |
| `DEP5-D-007` | Qdrant 是派生状态；`snapshot_restore` 或 `embedding_recompute` 都以 PostgreSQL membership 为事实边界，并分别校验 provider outbound 和 Qdrant transport 授权。 | Qdrant 不反向成为业务事实，批准合同不等于批准联网。 |
| `DEP5-D-008` | 备份、恢复及其失败不写 `operation_logs`；审计载体为 no-replace 制品、CR-006 genesis 和脱敏部署日志；action delta 为 `0`。 | 数据库不可用时仍有证据，且备份不会改变自己的 snapshot。 |
| `DEP5-D-009` | 每个执行环境使用获批的机器 Policy 冻结 RPO、RTO、保留、独立副本和演练频率；完整性门禁与 SLA 结果分离。 | SLA miss 可被准确报告，不会因已经超时而永久阻止安全恢复流量。 |

## 3. 九类机器制品与严格 Schema

### 3.1 完整集合和通用规则

下表是 DEP-005-R1 的完整运行制品根 Schema 集合。A、B、E、F 是批准后复用的非秘密静态实例；C、D、G、H、I 是按运行生成的 no-replace 实例。

| ID | Schema 文件名 | 实例职责 |
| --- | --- | --- |
| A | `database-backup-profile-v1.schema.json` | PostgreSQL 导出、工具和事实 checksum Profile |
| B | `backup-encryption-profile-v1.schema.json` | 数据库与对象副本的认证加密 Profile |
| C | `database-backup-manifest-v1.schema.json` | 单次数据库备份、snapshot、事实和 chain 源状态 |
| D | `minio-backup-inventory-v1.schema.json` | 精确源版本、独立加密副本及 Qdrant snapshot subtype |
| E | `qdrant-rebuild-profile-v1.schema.json` | Qdrant 重建算法、membership 和固定评测 Profile |
| F | `environment-recovery-policy-v1.schema.json` | 环境 SLA、保留、隔离、网络和放行 Policy |
| G | `restore-run-input-v1.schema.json` | 单次恢复输入、目标 preflight 和授权引用 |
| H | `pre-traffic-restore-verification-v1.schema.json` | 不含开流量时间的恢复与完整性验证 |
| I | `traffic-release-attestation-v1.schema.json` | 独立流量 opened/held/closed 决策及实际 RTO |

外部共同审批记录、其 detached signature evidence、签名者注册表、Request 同步授权和同步后证明分别使用支持 Schema `source-contract-approval-record-v1.schema.json`、与 CR-006/008 共用的 `dep005-detached-approval-evidence-v1.schema.json`、`approval-signer-registry-v1.schema.json`、`request-sync-authorization-v1.schema.json`、`dep005-post-sync-baseline-attestation-v1.schema.json`。五者都不是运行制品，不改变 A..I 九类计数或依赖图；实际 raw Schema hash 按第 8 节绑定，本文不生成或预填。第 3.1 节另定义一个只服务未来 provider 环境批准的 runtime/provider support Schema `cr002-provider-environment-approval-v1.schema.json`；它不属于上述五者、A..I 或当前 meta/approved-artifact bundle，且不得在缺少独立 provider-environment 授权时生成批准实例。

九个制品 Schema 和五个支持 Schema 都使用 JSON Schema Draft 2020-12，并满足下列通则；独立 runtime/provider support Schema 在其另行授权生成流程中也必须逐字遵守同一 Draft、通则和负向量，但这不改变“五个支持 Schema”的计数或当前 bundle 范围：

1. 解码器先拒绝 duplicate key，再校验 Schema。
2. 每个 object 都设置 `additionalProperties: false`；本文列出的根键和嵌套键全部进入 `required`，条件缺值只能使用明确的 JSON `null`。
3. 不允许实现自行增加键、枚举值、隐式默认值、宽松类型转换或未知字段透传。
4. JSON 实例发布 bytes 必须等于 RFC 8785 JCS bytes；实例 SHA-256 是该发布 bytes 的 64 位小写十六进制 hash。Schema SHA-256 使用无 BOM UTF-8、LF 行尾的原始 Schema 文件 bytes。
5. 实例和 Schema 不在自身 JSON 内保存自身 hash。hash 只由上游实例、no-replace 对象元数据或外部审批记录保存。
6. 所有实例 create-only/no-replace；目标 key/version 已存在时只能读取并逐字节比较，相同可判幂等成功，不同必须失败。
7. 所有字符串拒绝前后空白、NUL、控制字符和 Unicode 隐式 normalization；需要规范化的字段只接受规范化后的唯一表示。

共同类型固定如下：

| 类型 | 唯一表示 |
| --- | --- |
| `Sha256` | string，正则 `^[0-9a-f]{64}$` |
| `Uuid` | string，正则 `^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` |
| `UuidV4` | `Uuid`，version nibble 为 `4`、variant 为 `8/9/a/b` |
| `UtcDate` | string，`YYYY-MM-DD`；还必须通过真实公历日期校验 |
| `UtcTimestamp` | string，UTC `Z`、恰好六位小数：`YYYY-MM-DDTHH:mm:ss.ffffffZ`；闰秒不允许 |
| `Version` | string，正则 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` |
| `OpaqueName` | string，正则 `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$` |
| `BucketName` | string，正则 `^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$` |
| `ObjectKey` | string，1..1024 UTF-8 code point；不以 `/` 开头，不含反斜杠、控制字符或等于 `.`/`..` 的 `/` 分隔段 |
| `SqlIdentifier` | string，正则 `^[a-z_][a-z0-9_]{0,62}$` |
| `SafeInteger` | JSON integer，`0..9007199254740991` |
| `PositiveInteger` | JSON integer，`1..9007199254740991` |
| `EnvironmentClass` | `development/test/staging/rehearsal/production` |
| `DomainName` | lowercase ASCII，正则 `^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$`，且解析为 canonical IPv4/IPv6 literal 时拒绝 |

`ArtifactRef` 是精确五键 object：`bucket`、`object_key`、`version_id`、`sha256`、`size_bytes`，类型依次为 `BucketName/ObjectKey/OpaqueName/Sha256/SafeInteger`。

`ApprovedInstanceRef` 是精确四键 object：`schema_version`、`schema_sha256`、`instance_version`、`instance_sha256`，分别为 `Version/Sha256/Version/Sha256`。

`ApprovedSchemaRef` 是精确两键 object：`schema_version`、`schema_sha256`，分别为 `Version/Sha256`。

`AddressableApprovedSchemaRef` 是精确三键 object：`schema_version`、`schema_sha256`、`schema_ref`，类型依次为 `Version/Sha256/ArtifactRef`，且 `schema_ref.sha256=schema_sha256`；它只用于必须从 package 外 expected pin 定位 raw Schema bytes 的 runtime/provider 审批边界，不得用两键 `ApprovedSchemaRef` 降级替代。

`AuthorizationRef` 是精确六键 object：`authorization_id`（`UuidV4`）、`authorization_type`（由使用处固定枚举）、`scope_sha256`（`Sha256`）、`approved_at`、`expires_at`（`UtcTimestamp`）和 `approver_id`（`Uuid`）。执行时必须满足 `approved_at <= now < expires_at`，且 scope 与本次 run/target/network 完全一致。

引用角色固定且不得互换：C/D/G/H/I 和 CR-006 运行证据的发布对象引用只能是 `ArtifactRef`；A/B/E/F 的已批准静态实例引用只能是 `ApprovedInstanceRef`；Schema bundle 条目只能是 `ApprovedSchemaRef`；所有运行授权只能是 `AuthorizationRef`。任何把实例 hash 当对象 version、把对象 ref 当静态 Profile ref、或把授权 ID 当授权 ref 的实现都必须拒绝。

| 制品 | 根/嵌套 ref 的封闭类型 |
| --- | --- |
| A/B/E | 无 `*_ref` |
| C | `backup_profile_ref/encryption_profile_ref/source_environment_policy_ref:ApprovedInstanceRef`；`minio_inventory_ref/database_artifact.encrypted_ref:ArtifactRef`；`source_genesis_ref/last_verified_anchor.chain_manifest_ref:ArtifactRef\|null` |
| D | `encryption_profile_ref/source_environment_policy_ref/qdrant_snapshot.qdrant_profile_ref:ApprovedInstanceRef`；`source_qdrant_snapshot_authorization_ref:AuthorizationRef\|null`；`entries.source_ref/backup_encrypted_ref:ArtifactRef` |
| F | `database_backup_profile_ref/encryption_profile_ref/qdrant_profile_ref:ApprovedInstanceRef` |
| G | `source_database_manifest_ref/source_minio_inventory_ref:ArtifactRef`；`qdrant_profile_ref/source_environment_policy_ref/target_environment_policy_ref:ApprovedInstanceRef`；`target_authorization.change_authorization_ref/provider_network_authorization_ref/qdrant_transport_authorization_ref:AuthorizationRef\|null` |
| H | `restore_input_ref/source_database_manifest_ref/source_minio_inventory_ref:ArtifactRef`；`operation_log_chain_result.transition_evidence_ref/transition.target_genesis_ref:ArtifactRef\|null`；`qdrant_profile_ref/source_environment_policy_ref/target_environment_policy_ref:ApprovedInstanceRef` |
| I | `pretraffic_verification_ref:ArtifactRef`；`previous_release_attestation_ref:ArtifactRef\|null`；`target_environment_policy_ref:ApprovedInstanceRef`；全部 release/SLA/production/originating `*_authorization_ref:AuthorizationRef\|null` |

表中未标 null 的 ref 必须 non-null；条件 null 只能服从各节矩阵。`source_genesis_ref` 和 `last_verified_anchor.chain_manifest_ref` 虽位于 C 的条件 union 中，non-null 时仍严格为 `ArtifactRef`。

除下文条件 null 外，`database_backup_id/inventory_id/restore_run_id/release_attestation_id/release_attempt_id/attestation_id/audit_namespace_write_barrier_id/source_qdrant_snapshot_id` 为 `UuidV4`；`source_chain_id/parent_chain_id/target_chain_id` 以及 `first_log.id/last_log.id` 为 `UuidV4`；environment、checker、approver、trace 和 actor ID 为 `Uuid`。所有 `*_version` 为 `Version`，`*_sha256` 为 `Sha256`，`*_at` 为 `UtcTimestamp`，`*_utc_date` 及 `chain_epoch_utc` 为 `UtcDate`，`*_count/*_bytes/*_seconds/*_days` 为 `SafeInteger`。tool/model/collection/storage/fault-domain/principal/key/reference/code/name 字段为 `OpaqueName`，SQL schema/relation 为 `SqlIdentifier`。与本段冲突时以下文更严格规则为准。

所有数组的顺序均是合同的一部分；除非下文另有顺序，object 数组按其主身份字段的 Unicode code point 升序并拒绝重复，字符串数组去重后按 Unicode code point 升序。

`NetworkEndpoint` 是精确三键 object：`scheme`（`http/https`）、`host`（`DomainName`）、`port`（JSON integer `1..65535`）；endpoint 数组按 `(scheme,host,port)` 升序且无重复。`CanonicalProviderBaseUrl` 是精确 string `${scheme}://${host}:${port}/v1`，scheme/host/port 必须逐字等于同一 approval ref 的 `NetworkEndpoint`，始终显式写十进制 port，禁止 userinfo、query、fragment、重定向、百分号编码、尾随 `/` 或额外 path；其 hash 固定为 `SHA256(UTF8(base_url))`。

`CR002ProviderEnvironmentApprovalRef` 是精确二十键 object：`cr_revision`、`decision_snapshot_sha256`、`approval_record_schema_ref`、`approval_record_ref`、`approval_record_sha256`、`approval_signer_registry_ref`、`environment_scope`、`environment_id`、`provider_id`、`allowed_model_ids`、`policy_version`、`policy_sha256`、`endpoint_id`、`endpoint`、`base_url`、`base_url_sha256`、`transport_profile_version`、`transport_profile_sha256`、`approved_at`、`expires_at`。`approval_record_schema_ref` 为 `AddressableApprovedSchemaRef` 且 version 固定 `cr002-provider-environment-approval-v1`；`approval_record_ref` 为 `ArtifactRef` 且 `approval_record_sha256=approval_record_ref.sha256`；registry ref 使用第 8.2 节精确类型；`cr_revision='CR-002-R4'`，`decision_snapshot_sha256='970eca0fffa2f88eb3e74ccc84adf042b38ac4cb9803d3d53d9d989057bb38a0'` 且必须按 CR-002 当前静态算法从其未改 preimage复算相等，其余 hash 字段为 `Sha256`。scope 只允许 `fixed_test_provider/production`，environment ID 为 `Uuid`，provider/endpoint ID 为 `OpaqueName`，`allowed_model_ids` 为非空、按 Unicode code point 升序且无重复的 `OpaqueName[]`，policy/transport version 为 `Version`，endpoint/base URL 使用本节类型且 hash 相等，时间为 `UtcTimestamp` 并满足 `approved_at < expires_at`。target class=production 当且仅当 scope=production；其他 target class 只能使用 fixed-test scope。

该 ref 必须离线解析到 no-replace JCS `cr002-provider-environment-approval-v1` 记录；记录根精确二十五键：`record_schema_version`、`canonicalization_version`、`hash_algorithm`、`approval_id`、`approval_record_schema_sha256`、`cr_revision`、`decision_snapshot_sha256`、`environment_scope`、`environment_id`、`provider_id`、`allowed_model_ids`、`policy_version`、`policy_sha256`、`endpoint_id`、`endpoint`、`base_url`、`base_url_sha256`、`transport_profile_version`、`transport_profile_sha256`、`decision`、`approvals`、`approved_at`、`expires_at`、`detached_approval_evidence_schema_ref`、`approval_signer_registry_ref`。前三个常量依次为 `cr002-provider-environment-approval-v1/RFC8785-JCS/SHA-256`，decision 固定 `APPROVED`；`approval_record_schema_sha256=outer.approval_record_schema_ref.schema_sha256` 并等于实际无 BOM UTF-8/LF raw Schema hash，detached Schema ref 固定 `dep005-detached-approval-evidence-v1`，registry ref 逐字等于外层并通过 external pin。`allowed_model_ids` 使用外层同一非空排序/唯一类型且逐字相等。`approvals[]` 恰好五项并按 `requirements_product/architecture/ai_rag/ops/security` 固定顺序，每项精确六键 `approver_id/approver_role/decision/decided_at/evidence_ref/evidence_sha256`，decision 均为 APPROVED，ref 为 `ArtifactRef` 且 hash 相等，五项都通过第 8.3 节 `provider_environment_approver_decision` scope；`approved_at=max(decided_at)`。每份 evidence 使用第 8.3 节独立二键 wrapper，只签目标 item 四键与本记录删除整个 approvals 数组后的二十四键 target，不共享或包含其他 item evidence，因而无签名环。记录的 revision/snapshot/environment/provider/allowed-model-set/policy/endpoint/base-url/transport/time/registry 必须与外层 ref 逐项相等。outer 的完整二十键 expected object及 `approval_record_schema_ref` 必须来自 package 外 authenticated provider-approval verifier input，禁止从待验 record、per-run authorization 或 provider 响应自报；Schema raw bytes 只可按本节静态结构在另行获准的 provider-environment approval 流程中离线生成和独立复核，生成 Schema 本身不授权网络或 production。五角色、Schema、签名、可寻址记录、registry pin或任一字段漂移都拒绝；单一 aggregate 签名或仅有不可寻址 hash 不合格。

每个 non-null `AuthorizationRef` 都必须存在一个 no-replace、可逐字节复核的 scope object；`scope_sha256=SHA256(JCS(scope))`，scope 的 `expires_at` 必须逐字等于 ref，实际副作用发生时 ref 与 scope 都必须仍有效。以下九种 `authorization_type` 和 scope 是封闭全集；每个 scope object 都固定 `scope_schema_version=<authorization_type>-scope-v1`、`additionalProperties=false`，并采用本节共同类型：

| authorization type | scope 的其余精确键、类型与顺序/矩阵 |
| --- | --- |
| `embedding_provider_outbound` | `restore_run_id:UuidV4`、`provider_id:OpaqueName`、`model_id:OpaqueName`、`qdrant_profile_instance_sha256:Sha256`、`target_environment_id:Uuid`、`endpoint_id:OpaqueName`、`base_url_sha256:Sha256`、`transport_profile_version:Version`、`transport_profile_sha256:Sha256`、`allowed_domains:DomainName[]`、`cr002_provider_environment_approval_ref:CR002ProviderEnvironmentApprovalRef`、`expires_at:UtcTimestamp`；domain 恰好为 approval endpoint host 的单元素数组；provider/environment/endpoint/base-url/transport 和 expiry 必须逐字等于或不晚于该 CR-002 ref，且 `model_id` 必须是其 `allowed_model_ids` 的一个精确成员并逐字等于 E `embedding_model_id`，不允许 null |
| `source_qdrant_snapshot_read` | `database_backup_id:UuidV4`、`source_environment_id:Uuid`、`qdrant_profile_instance_sha256:Sha256`、`collection_names:OpaqueName[]`、`allowed_endpoints:NetworkEndpoint[]`、`expires_at:UtcTimestamp`；两数组非空且按本节规则排序 |
| `isolated_qdrant_transport` | `restore_run_id:UuidV4`、`target_environment_id:Uuid`、`qdrant_profile_instance_sha256:Sha256`、`collection_names:OpaqueName[]`、`allowed_endpoints:NetworkEndpoint[]`、`expires_at:UtcTimestamp`；两数组非空且按本节规则排序 |
| `restore_target_change` | `restore_run_id:UuidV4`、`target_environment_id:Uuid`、`target_environment_class:EnvironmentClass`、`change_record_sha256:Sha256`、`expires_at:UtcTimestamp` |
| `traffic_release` | `release_attempt_id:UuidV4`、`restore_run_id:UuidV4`、`target_environment_id:Uuid`、`pretraffic_verification_sha256:Sha256`、`target_environment_policy_instance_sha256:Sha256`、`ingress_id:OpaqueName`、`expires_at:UtcTimestamp` |
| `traffic_close` | `release_attempt_id:UuidV4`、`restore_run_id:UuidV4`、`target_environment_id:Uuid`、`previous_opened_attestation_sha256:Sha256`、`target_environment_policy_instance_sha256:Sha256`、`ingress_id:OpaqueName`、`expires_at:UtcTimestamp` |
| `traffic_emergency_close` | `release_attempt_id:UuidV4`、`originating_release_attempt_id:UuidV4`、`restore_run_id:UuidV4`、`target_environment_id:Uuid`、`pretraffic_verification_sha256:Sha256`、`target_environment_policy_instance_sha256:Sha256`、`originating_release_precheck_at:UtcTimestamp`、`originating_traffic_release_authorization_id:UuidV4`、`ingress_id:OpaqueName`、`expires_at:UtcTimestamp` |
| `sla_exception` | `release_attempt_id:UuidV4`、`restore_run_id:UuidV4`、`target_environment_id:Uuid`、`pretraffic_verification_sha256:Sha256`、`missed_metrics:(rpo\|prospective_rto\|actual_rto)[]`、`rpo_threshold_seconds:SafeInteger`、`rto_threshold_seconds:SafeInteger`、`expires_at:UtcTimestamp`；`missed_metrics` 非空且按 enum 声明顺序排序 |
| `production_release` | `release_attempt_id:UuidV4`、`restore_run_id:UuidV4`、`target_environment_id:Uuid`、`target_environment_policy_instance_sha256:Sha256`、`pretraffic_verification_sha256:Sha256`、`change_record_sha256:Sha256`、`ingress_id:OpaqueName`、`expires_at:UtcTimestamp` |

scope 表中的字段顺序是文档展示顺序，hash 仍按 RFC 8785 排序。scope 无条件 null 字段。provider scope 的 CR-002 ref 始终 non-null，且 CR-002 环境批准与本次 `AuthorizationRef` 在副作用时都必须有效；per-run ref 不能扩大 CR-002 的 provider/model/environment/endpoint/base-url/transport 边界。scope 的 run/backup、target/source、profile、H hash、Policy hash、ingress、阈值和 attempt 必须逐项等于消费制品；批准时间不得晚于要授权的 precheck/副作用时间。当前 CR-002 的 `fixed_test_provider` 和 `production` 环境批准仍未授权，且本合同固定 `network_scope=none`、`production_release_scope=none`，因此 meta 或 approved artifact 都不产生这些运行授权。

### 3.2 A：`database-backup-profile-v1`

根对象精确键为：

`profile_schema_version`、`canonicalization_version`、`hash_algorithm`、`profile_version`、`tool_name`、`tool_version`、`compatible_postgresql_major_versions`、`format`、`compression`、`snapshot_isolation`、`snapshot_export_required`、`connection_interface`、`argument_template`、`database_fact_query_version`、`database_fact_query_sha256`、`database_row_checksum_version`、`database_row_checksum_sha256`、`operation_log_tail_hash_version`、`operation_log_tail_hash_sha256`、`plaintext_staging_policy`、`cleanup_verification`、`max_backup_duration_seconds`。

约束：

- 三个常量依次为 `database-backup-profile-v1`、`RFC8785-JCS`、`SHA-256`。
- `compatible_postgresql_major_versions` 是去重升序的 PositiveInteger 数组；运行服务端 major 和工具 major 都必须在数组内且相等。
- `format` 只允许 `pg_dump_custom`；`snapshot_isolation` 固定 `serializable_read_only_deferrable`；`snapshot_export_required=true`。
- `compression` 是精确三键 object：`algorithm`（`none/gzip/zstd`）、`level`（SafeInteger 或 null）、`deterministic_parameters_sha256`（Sha256）；`none` 时 `level=null`，其余 non-null。
- `connection_interface` 固定 `libpq_environment_or_restricted_service_file`。`argument_template` 固定为有序数组 `["--format=custom","--snapshot={EXPORTED_SNAPSHOT}","--file={OUTPUT_PATH}","--no-owner","--no-privileges","--compress={COMPRESSION}"]`；`{COMPRESSION}` 必须由 compression object 唯一渲染。连接参数只能通过受限进程环境或 service file 注入，不得进入参数、manifest 或日志。
- `plaintext_staging_policy` 只允许 `memory_only` 或 `restricted_temporary_file`；后者要求 `cleanup_verification` 为 `overwrite_unlink_and_absence_check`，前者固定为 `not_applicable`。
- query/checksum/tail 的 version/hash 由 approved artifact 实例选择；三个 hash 分别绑定无 BOM UTF-8/LF 的 no-replace query 或算法规范原始 bytes，而不是某次运行输出。它们定义事实 relation 集合、逐行规范化和 `operation-log-row-v1` digest 数组算法，不得由运行时更改；任一同 version 异 hash、规范 bytes 缺失或向量不匹配都拒绝备份与恢复。

### 3.3 B：`backup-encryption-profile-v1`

根对象精确键为：

`profile_schema_version`、`canonicalization_version`、`hash_algorithm`、`profile_version`、`algorithm`、`key_bits`、`nonce_bytes`、`tag_bytes`、`envelope_version`、`aad_schema_version`、`aad_fields`、`nonce_policy`、`key_source_interface`、`key_id_pattern`、`tool_name`、`tool_version`、`plaintext_staging_policy`、`cleanup_verification`、`key_rotation_days`、`decrypt_compatibility_days`。

约束：

- 三个常量依次为 `backup-encryption-profile-v1`、`RFC8785-JCS`、`SHA-256`。
- `algorithm` 只允许 `AES-256-GCM` 或 `XCHACHA20-POLY1305`。两者 `key_bits=256`、`tag_bytes=16`；nonce bytes 分别为 `12` 和 `24`。
- `aad_fields` 固定且按此顺序为 `artifact_class/artifact_id/source_environment_id/profile_version/plaintext_sha256`。
- AAD bytes 固定为上述五键 object 的 UTF-8 JCS bytes。数据库 artifact 使用 `artifact_class=database_dump`、`artifact_id=database_backup_id`；D entry 使用 `artifact_class=entry_kind`、`artifact_id=reference_id`。任何字段缺失或不相等都拒绝解密。
- `nonce_policy` 固定 `random_csprng_unique_per_key_and_artifact`；nonce 存在加密 envelope 中，任何相同 key ID 下重复 nonce 都必须拒绝。
- `key_source_interface` 只允许 `secret_manager` 或 `restricted_key_file`；`key_id_pattern` 的类型为 string 且固定字面量 `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$`。该字面量只序列化下列 ASCII grammar，不依赖宿主 regex dialect：长度 1..128、首字节为 `A-Z/a-z/0-9`、其余字节只允许 `A-Z/a-z/0-9._:/-`；运行时非秘密 `key_id` 必须按字节满足该 grammar。实例不得包含 key、密码、Token、DSN、私钥或可兑换凭据。
- staging 与 cleanup 使用 A 的同一矩阵；`decrypt_compatibility_days >= key_rotation_days`。

### 3.4 C：`database-backup-manifest-v1`

根对象精确键为：

`manifest_schema_version`、`canonicalization_version`、`hash_algorithm`、`database_backup_id`、`source_environment_id`、`backup_profile_ref`、`encryption_profile_ref`、`source_environment_policy_ref`、`snapshot`、`database_artifact`、`database_facts`、`chain_snapshot`、`minio_inventory_ref`、`backup_started_at`、`backup_completed_at`。

常量依次为 `database-backup-manifest-v1`、`RFC8785-JCS`、`SHA-256`；`database_backup_id` 为 `UuidV4`；三个 Profile/Policy ref 为 `ApprovedInstanceRef`。`source_environment_policy_ref` 必须解析为 F 的 `policy_scope=source_backup` 实例，其 `environment_id=source_environment_id`；该 F 的 A/B refs 分别等于 C 的 A/B refs，其 E ref 等于每个 non-null `D.entries[].qdrant_snapshot.qdrant_profile_ref`。

`snapshot` 精确十键：

`snapshot_export_id_sha256`、`snapshot_txid_snapshot`、`snapshot_txid_snapshot_sha256`、`snapshot_established_at`、`observed_wal_lsn`、`database_system_identifier`、`database_timeline_id`、`postgresql_major_version`、`alembic_revision`、`application_version`。

- export ID hash 的 preimage 是 export ID 原始 UTF-8 bytes；原值只在导出事务存活期内存，不写制品或日志。
- `snapshot_txid_snapshot` 匹配 `^(0|[1-9][0-9]*):(0|[1-9][0-9]*):((0|[1-9][0-9]*)(,(0|[1-9][0-9]*))*)?$`；xip 递增且无重复，xmin <= xmax；其 hash preimage 是该规范 string 的 JCS string value bytes。
- `observed_wal_lsn` 匹配 `^[0-9A-F]+/[0-9A-F]+$`，只作诊断。
- `database_system_identifier` 匹配 `^(0|[1-9][0-9]*)$`，以十进制 string 避免超过 JSON safe integer；timeline 和 major 为 PositiveInteger；revision/application version 为 `Version`。
- `chain_epoch_utc` 及所有 `*_utc_date` 是 `UtcDate`，不适用 `UtcTimestamp`。

`database_artifact` 精确七键：`plaintext_sha256`、`plaintext_size_bytes`、`encrypted_ref`、`key_id`、`envelope_metadata_sha256`、`backup_storage`、`readback_evidence_sha256`。`encrypted_ref` 是 `ArtifactRef` 且其 hash/size 是密文；key ID non-empty 且匹配 B 的 pattern；`readback_evidence_sha256` 为 `Sha256`，必须绑定 exact-version 密文回读以及 versioning/no-replace/retention metadata 的权威读取结果。`backup_storage` 必须与 C 所引 D 的同名十一键 object 逐 JCS byte相等，`encrypted_ref.bucket` 必须属于其 `bucket_names`，并且密文写入与回读必须遵守该对象的 versioning/no-replace、独立 storage/fault-domain/principal、retention、permission 和 lifecycle 证明；数据库 dump 不得旁路 D 的独立 backup storage。

`database_facts` 精确五键：`query_version`、`query_sha256`、`relation_count`、`relations`、`relations_sha256`。每个 `relations[]` 精确五键：`schema_name`、`relation_name`、`row_count`、`checksum_version`、`content_sha256`；按 `(schema_name, relation_name)` 排序且无重复。`relation_count=relations.length`，`relations_sha256=SHA256(JCS(relations))`，query/checksum 必须等于 A。

`minio_inventory_ref` 是已发布 D 实例的 `ArtifactRef`，其 bucket 必须属于 D `backup_storage.bucket_names`；D 的 `database_backup_id` 和 `snapshot_txid_snapshot_sha256` 必须与 C 相等。C 只能在数据库密文和 D 全部验证后，以 no-replace 写入同一 backup storage并回读 bytes、version、retention metadata；实际 C ref bucket也必须属于该集合。

`chain_snapshot` 精确十一键：

`source_chain_mode`、`source_chain_id`、`source_chain_epoch_utc`、`source_genesis_ref`、`source_genesis_sha256`、`covered_through_utc_date`、`last_verified_anchor`、`unsealed_tail`、`snapshot_txid_snapshot_sha256`、`source_operation_log_row_count`、`source_operation_log_first_log`。

`source_chain_id`、`last_verified_anchor.chain_id` 和所有 non-null log ID 均为 `UuidV4`；`source_genesis_ref`、`last_verified_anchor.chain_manifest_ref` 均为指向独立加密副本的 `ArtifactRef`，其 ref hash 是密文 hash，不得等同明文 hash。`last_verified_anchor` non-null 时精确五键：`chain_id`、`utc_date`、`day_anchor_sha256`、`chain_manifest_ref`、`chain_manifest_sha256`；显式 manifest hash 是解密后 plaintext hash，二者按下段 D entry等式分别验证。`unsealed_tail` non-null 时精确七键：`start_utc_date`、`snapshot_txid_snapshot_sha256`、`row_count`、`first_log`、`last_log`、`tail_rows_sha256`、`tail_hash_version`。`first_log/last_log` non-null 时均精确两键 `created_at:UtcTimestamp/id:UuidV4`；tail hash 等于按 A 的 tail version 对 snapshot 可见 `operation-log-row-v1` digest 数组按 `(created_at,id)` 排序后取 JCS SHA-256，零行使用 JCS `[]`。

`source_operation_log_row_count` 是同一数据库 snapshot 内全部 `operation_logs` 的 `SafeInteger` 行数；`source_operation_log_first_log` 为 `ArtifactRef` 以外的精确两键值 object `created_at:UtcTimestamp/id:UuidV4`。row count 为 0 时 first 必须 null；大于 0 时 first 必须 non-null 且等于全表按 `(created_at,id)` 升序首行。它只为 fresh target epoch 选择提供确定性事实，不改变 tail hash 边界。

源 chain null 矩阵固定为：

| source mode | chain ID | epoch | genesis ref/hash | covered/anchor | tail |
| --- | --- | --- | --- | --- | --- |
| `chain_absent` | null | null | null | 两者 null | null |
| `initialized_unsealed` | non-null | non-null | non-null | 两者 null | non-null，`start=epoch` |
| `sealed` | non-null | non-null | non-null | 两者 non-null 且日期相等 | non-null，`start=covered+1 day` |

non-null `source_genesis_ref` 只能绑定 D 中恰好一个满足 `entry_kind=audit_evidence`、`reference_type=operation_log_genesis`、`reference_id=source_chain_id` 的 entry：C ref 必须逐字等于该 entry `backup_encrypted_ref`，`source_genesis_sha256=entry.plaintext_sha256=entry.source_ref.sha256`。解密后的 plaintext 必须通过 CR-006 `operation-log-genesis-v1` Schema/JCS，并且其 `chain_id/chain_epoch_utc` 逐字等于 C，raw plaintext SHA-256 等于 `source_genesis_sha256`。non-null `last_verified_anchor` 只能绑定 D 中恰好一个满足 `entry_kind=audit_evidence`、`reference_type=operation_log_chain_manifest`、`reference_id="${chain_id}/${utc_date}"` 的 entry：anchor ref 等于该 entry `backup_encrypted_ref`，`chain_manifest_sha256=entry.plaintext_sha256=entry.source_ref.sha256`；解密 plaintext 必须通过 CR-006 `audit-chain-manifest-v1` Schema/JCS，且 `chain_id/utc_date/day_anchor_sha256` 逐字等于 anchor。任一 predicate 零匹配、多匹配、source/backup ref 被交换、解密 Schema/身份/hash不一致都拒绝 C。所有 mode 下 `chain_snapshot.snapshot_txid_snapshot_sha256` 都 non-null 且等于 `snapshot` 同名字段。tail `row_count=0` 时 first/last 同时 null；大于零时同时 non-null且 first <= last。`backup_started_at <= snapshot_established_at <= backup_completed_at`。

### 3.5 D：`minio-backup-inventory-v1`

根对象精确键为：

`inventory_schema_version`、`canonicalization_version`、`hash_algorithm`、`inventory_id`、`database_backup_id`、`source_environment_id`、`snapshot_txid_snapshot_sha256`、`encryption_profile_ref`、`source_environment_policy_ref`、`source_qdrant_snapshot_authorization_ref`、`source_storage`、`backup_storage`、`enumeration_boundary`、`inventory_created_at`、`entry_count`、`entries`。

常量依次为 `minio-backup-inventory-v1`、`RFC8785-JCS`、`SHA-256`；两个 ID 为 `UuidV4`。`encryption_profile_ref/source_environment_policy_ref` 为 `ApprovedInstanceRef`；source Policy 必须解析为 `policy_scope=source_backup` 且 `environment_id=source_environment_id`，其 encryption ref 等于 D 根 ref，所有 non-null qdrant subtype 的 E ref 等于该 Policy 的 E ref。

`source_storage` 和 `backup_storage` 都是精确十一键 object：

`storage_system_id`、`fault_domain_id`、`principal_id`、`bucket_names`、`versioning_enabled`、`no_replace_enforced`、`object_lock_mode`、`retention_until`、`permission_policy_sha256`、`retention_policy_sha256`、`lifecycle_policy_sha256`。`bucket_names` 是非空、Unicode code point 升序且无重复的 bucket-name string 数组；每个 entry ref 的 source/backup bucket 必须分别属于对应数组。

- 两端 `versioning_enabled=true`、`no_replace_enforced=true`。
- `storage_system_id/fault_domain_id/principal_id` 三组值必须分别不相等；两端 `object_lock_mode` 都只允许 `none/governance/compliance`，backup 值必须等于 F 的选择。P0 不强制 WORM/object lock；即使为 `none`，versioning、no-replace、独立 principal/fault domain 和独立 lifecycle 仍是硬门禁。
- 两端 permission policy hash 必须对应实际只读探测结果：source writer 无 backup overwrite/delete，backup writer 无 source write，普通应用无 backup write/delete；任一负向探测成功都拒绝 D。
- `retention_until` 使用 `UtcTimestamp`。source 值可为 null；backup 必须 non-null，且只能是在 D 序列化前根据已验证的 bucket/namespace retention、permission 与 lifecycle policy bytes及只读 probes计算出的最早政策保证时点，不得声称由尚未写出的 D/C manifest 自证。该固定时点必须同时满足 `retention_until >= C.backup_completed_at + F.database_retention_days*86400`、`retention_until >= D.inventory_created_at + F.independent_object_copy_retention_days*86400`、`retention_until >= C.backup_completed_at + F.manifest_retention_days*86400`；若后置 C 时间使任一不等式失效则禁止发布 C。database dump 与 entries 在 D 前逐对象 readback；D 写入后必须先回读其 bytes/version/政策生效 metadata，失败时该 D 只是不可接受 orphan且禁止 C；C 写入后同样回读，失败时 C 是不可接受 orphan且整个 backup不得登记为成功。两次后置 readback都不得回填或覆盖 D/C。backup lifecycle 不得传播 source delete/overwrite。

`enumeration_boundary` 精确十键：

`database_reference_query_version`、`database_reference_query_sha256`、`snapshot_txid_snapshot_sha256`、`audit_namespace_prefix`、`audit_namespace_write_barrier_id`、`audit_namespace_write_barrier_evidence_sha256`、`audit_namespace_cutoff_at`、`audit_namespace_observed_max`、`audit_listing_algorithm`、`stable_listing_passes`。

query 与 A 相等；write barrier ID 为 `UuidV4`，`audit_namespace_prefix` 为以 `/` 结尾的 `ObjectKey`，cutoff 为 source store 的 `UtcTimestamp` 诊断时点；`audit_listing_algorithm` 固定 `inclusive-observed-max-version-list-under-write-barrier-v1`，`stable_listing_passes=2`。`audit_namespace_observed_max` 为 null 或精确三键 object `source_last_modified_at:UtcTimestamp/object_key:ObjectKey/version_id:OpaqueName`。

audit-evidence 生产者先建立禁止 namespace 新写、覆盖和删除的可验证 write barrier，再进行一次完整 non-delete version listing，按 `(source_last_modified_at,object_key,version_id)` 升序去重；非空时把最大 tuple 逐字写入 observed max 并纳入所有 `tuple <= observed_max` 的版本，空集时 observed max=null 且 audit entry 数为零。保持 barrier 后重复同一 inclusive listing，两个完整有序集合必须逐 JCS byte 相等，才可释放 barrier。算法不使用 `last_modified_at < cutoff`，因此不会漏掉与 cutoff 同时间戳的版本；无法建立 barrier、列出完整历史版本或读取 exact version 时备份失败。

每个 `entries[]` 精确十一键：

`entry_kind`、`reference_type`、`reference_id`、`source_ref`、`source_last_modified_at`、`backup_encrypted_ref`、`plaintext_sha256`、`key_id`、`envelope_metadata_sha256`、`copy_outcome`、`qdrant_snapshot`。

- `entry_kind` 只允许 `database_fact_object/audit_evidence/qdrant_snapshot`。
- `copy_outcome` 在可发布 D 中固定为 `verified`，含密文 exact-version bytes/hash/size、versioning/no-replace 和逐对象 retention metadata 回读均通过；失败项只进入失败证据，不得混入 D。
- `source_ref` 和 `backup_encrypted_ref` 均为 `ArtifactRef`；`source_last_modified_at` 为该 exact source version 的权威 `UtcTimestamp` 元数据；source ref hash 必须等于 `plaintext_sha256`，backup ref hash/size 是密文。
- 数据库事实对象按 snapshot 中的 `bucket/key/content hash/size` 解析 source version：同 key 的历史版本中必须恰好一个 version 同时匹配 hash/size；零个或多个都 fail closed。audit-evidence key 必须 no-replace 且恰好一个非 delete version。
- `qdrant_snapshot` 只在同名 entry kind 时 non-null；其他 kind 必须为 null。
- `audit_evidence` 的 `reference_type/reference_id` 均为 `OpaqueName`；保留类型 `operation_log_genesis` 的 ID 必须是小写 `UuidV4` chain ID，保留类型 `operation_log_chain_manifest` 的 ID 必须严格匹配 `<小写UuidV4>/<UtcDate>`。同一 `(reference_type,reference_id)` 在整个 entries 中至多出现一次，且它的 source ref 必须是 no-replace plaintext artifact、backup ref 必须是按 B 加密并已回读验证的独立副本。C 只能按第 3.4 节两个保留 predicate 选择 chain evidence，禁止以其他 audit entry、仅同 hash对象或未验证 source ref替代。

`qdrant_snapshot` 精确八键：

`qdrant_profile_ref`、`collection_name`、`snapshot_format_version`、`collection_config_sha256`、`payload_schema_sha256`、`membership_set_sha256`、`point_count`、`source_qdrant_snapshot_id`。

profile 为 E 的 `ApprovedInstanceRef`；`source_qdrant_snapshot_id` 为 Qdrant 在本次已授权 backup operation 中返回且唯一标识精确 snapshot bytes 的 `UuidV4`，不得使用 collection ID、对象 version ID 或本地自造 ID。membership set 是按 E 定义的 PostgreSQL membership record 排序数组之 JCS SHA-256。snapshot 的 collection、payload、point count 和 membership 必须在复制前全部相等。

Qdrant snapshot entry 只允许 E 为 `snapshot_restore` 且 source F 的 `source_qdrant_snapshot_policy=per_run_authorization_required` 时存在，并且必须覆盖 E index definition 中每个 collection 恰好一次；E 为 recompute 或 source Policy 禁止 snapshot read 时数量必须为零。生成者必须先取得 type `source_qdrant_snapshot_read` 且 scope 精确匹配本节共同合同的 `AuthorizationRef`，通过 scope 内 source endpoints 生成 snapshot，并把返回 bytes 以 no-replace 写入 `source_storage.bucket_names` 内的隔离 staging bucket；该 exact version 才是 entry 的 `source_ref`。完成 membership/config/payload/count、snapshot ID 和 source_ref hash/size 验证后才能加密复制。存在任一 qdrant snapshot entry 时根 `source_qdrant_snapshot_authorization_ref` 必须是该同一有效引用；不存在时必须为 null。该引用只证明本次备份期 source read，不授权 restore target write。

`entries` 按 `(entry_kind,reference_type,reference_id,source_ref.bucket,source_ref.object_key,source_ref.version_id)` 排序且拒绝重复；`entry_count=entries.length`。D 只保存 source→backup 映射；restored version 映射只进入 H。`inventory_created_at` 必须不早于 audit cutoff、observed max（non-null 时）和全部 backup encrypted ref 的完成时刻。

### 3.6 E：`qdrant-rebuild-profile-v1`

根对象精确键为：

`profile_schema_version`、`canonicalization_version`、`hash_algorithm`、`profile_version`、`recovery_mode`、`index_definition_version`、`index_definition_sha256`、`membership_query_version`、`membership_query_sha256`、`membership_record_schema_version`、`membership_record_schema_sha256`、`embedding_model_id`、`embedding_model_version`、`vector_dimension`、`distance_metric`、`point_id_derivation_version`、`payload_schema_version`、`payload_schema_sha256`、`consistency_hash_algorithm`、`fixed_eval_dataset_version`、`fixed_eval_dataset_sha256`、`provider_execution_mode`。

约束：

- 三个常量依次为 `qdrant-rebuild-profile-v1`、`RFC8785-JCS`、`SHA-256`。
- `recovery_mode` 只允许 `snapshot_restore/embedding_recompute`；`distance_metric` 只允许 `cosine/dot/euclid`；dimension 为 PositiveInteger。
- `consistency_hash_algorithm` 的类型为 `Version` 且固定 `point-id-ordered-membership-records-jcs-sha256-v1`。membership record Schema 必须精确冻结 point ID、source content hash、payload hash 和 index version；membership set hash 固定为按 point ID Unicode code point 升序且无重复的完整 record 数组之 UTF-8 JCS bytes 的 SHA-256，不得使用数据库返回顺序、对象插入顺序或实现私有序列化。
- `expected_point_count` 不属于静态 Profile；运行期值只从 PostgreSQL membership 派生。
- snapshot mode 的 `provider_execution_mode=none`；recompute mode 只允许 `offline_local/networked_provider`。两种 mode 写目标 Qdrant 都受独立 transport authorization 控制。

### 3.7 F：`environment-recovery-policy-v1`

根对象精确键为：

`policy_schema_version`、`canonicalization_version`、`hash_algorithm`、`policy_version`、`policy_scope`、`environment_id`、`environment_class`、`database_backup_profile_ref`、`encryption_profile_ref`、`qdrant_profile_ref`、`target_preflight_profile_version`、`target_preflight_profile_sha256`、`rpo_formula_version`、`rto_formula_version`、`rpo_seconds`、`rto_seconds`、`database_retention_days`、`independent_object_copy_retention_days`、`independent_copy_object_lock_mode`、`manifest_retention_days`、`rehearsal_interval_days`、`maximum_rehearsal_age_days`、`restore_target_isolation_class`、`max_preflight_age_seconds`、`max_pretraffic_verification_age_seconds`、`max_traffic_switch_duration_seconds`、`provider_network_policy`、`source_qdrant_snapshot_policy`、`target_qdrant_transport_policy`、`production_release_authority_required`、`sla_exception_authority_required`。

约束：

- 三个常量依次为 `environment-recovery-policy-v1`、`RFC8785-JCS`、`SHA-256`。
- `policy_scope` 只允许 `source_backup/target_recovery`；`environment_id` 为 `Uuid`，`environment_class` 的类型严格为 `EnvironmentClass` 且不得由 ID、部署名称或运行时默认值推断；A/B/E refs 均为 `ApprovedInstanceRef`。所有根键始终 required；不适用于当前 scope 的值必须是 JSON null，不得省略、默认继承或复用另一 scope 的值。
- `target_preflight_profile_version/hash` 精确冻结用于证明 application DB 无对象/数据、目标 MinIO prefix 不存在、目标 Qdrant namespace 不存在、Redis namespace 为空和 ingress blocked 的只读 probes；G 的 checker 和副作用前重查只能执行该 version/hash。
- `rpo_formula_version=rpo-recovery-event-minus-source-point-ceil-v1`；`rto_formula_version=rto-traffic-open-minus-recovery-event-ceil-v1`。适用的 duration/retention 值为 `PositiveInteger`；`restore_target_isolation_class` 只允许 `disposable_isolated/approved_isolated`。每个 target Policy 必须满足 `rehearsal_interval_days <= maximum_rehearsal_age_days`。在同一 approved-artifact `environment_policy_instance_set` 内，按目标 F 的 `policy_version` 和 A/B/E refs 必须唯一选出一个 `source_backup` F；目标 class=`rehearsal` 时 rehearsal target就是自身，否则还必须唯一选出一个不同 environment ID、class=`rehearsal`、相同 policy version/A/B/E、相同 RTO formula/threshold/interval/max-age 的 target F；零个或多个匹配都使 Policy set非法。OPS scheduler 用该唯一 source/rehearsal-target pair 至少按 interval创建隔离 G。一次“按 SLA 成功 rehearsal”必须同时具备同 run 的 H `technical_outcome=passed_for_release_review/recovery_acceptance_outcome=passed/rpo_outcome=met`、I `opened/rto_outcome=met` 且两个 SLA exception ref均 null，并随后有同 attempt的 normal-close I；最大年龄固定从 opened I `traffic_opened_at` 到检查时刻计算。技术成功但 RPO/RTO missed、只靠 exception放流量、未完成 isolated ingress open/close或证据超龄都只能报告 rehearsal/readiness failed并触发新 rehearsal，不得伪造旧 H/I、放宽门槛或自动授权 production。
- `independent_copy_object_lock_mode` 只允许 `none/governance/compliance`；`none` 是 P0 合法值，governance/compliance 只在 source 环境明确选择时成为门禁。`max_traffic_switch_duration_seconds` 是 release controller 的硬超时和 RTO precheck 上界。
- `provider_network_policy` 只允许 `forbidden/per_run_authorization_required`；`source_qdrant_snapshot_policy` 只允许 `forbidden/per_run_authorization_required`；`target_qdrant_transport_policy` 只允许 `forbidden/isolated_target_per_run_authorization_required`。三者只是门禁，不是授权，且 source read 与 target write 永不共用 ref/scope。

F 的封闭 null/enum 矩阵为：

| 字段组 | `source_backup` | `target_recovery` |
| --- | --- | --- |
| A/B/E refs | 全 non-null | 全 non-null |
| target preflight version/hash | 全 null | 全 non-null |
| RPO formula/threshold | non-null / non-null | 全 null |
| RTO formula/threshold | 全 null | non-null / non-null |
| database/object-copy/manifest retention、object-lock | 全 non-null | 全 null |
| rehearsal interval/max age、target isolation、max preflight age、max H age、max switch duration | 全 null | 全 non-null |
| provider network policy | null | non-null enum |
| source Qdrant snapshot policy | non-null enum | null |
| target Qdrant transport policy | null | non-null enum |
| production release authority required | null | boolean；class=production 时固定 true，其他 class 固定 false |
| SLA exception authority required | null | 固定 true |

source Policy 决定 C/D 的备份、retention 和 source Qdrant read；target Policy 决定 G/H/I 的隔离恢复、network、SLA 和流量门禁。一个 approved-artifact 可绑定多个 F 实例，至少包含一个 source 与一个不同 environment ID 的 target；不得假设全系统只有一个 F 实例。

### 3.8 G：`restore-run-input-v1`

根对象精确键为：

`input_schema_version`、`canonicalization_version`、`hash_algorithm`、`restore_run_id`、`input_created_at`、`source_database_manifest_ref`、`source_minio_inventory_ref`、`qdrant_profile_ref`、`source_environment_policy_ref`、`target_environment_policy_ref`、`target_environment_id`、`target_environment_class`、`recovery_event_at`、`target_preflight`、`target_authorization`、`provider_network_authorization_ref`、`qdrant_transport_authorization_ref`、`operation_log_transition_plan`。

常量依次为 `restore-run-input-v1`、`RFC8785-JCS`、`SHA-256`；run ID 为 `UuidV4`，C/D/G 发布引用为 `ArtifactRef`，E 和两个 F 引用为 `ApprovedInstanceRef`。C 必须引用同一个 D；source Policy ref 必须逐字段等于 C/D 的 source ref并解析为 `policy_scope=source_backup`；target Policy 必须解析为 `policy_scope=target_recovery`，其 `environment_id/class` 等于 G target。`G.target_environment_class` 必须逐字等于已验证 target F 的 `environment_class`，并且只能是 `EnvironmentClass` 的五个枚举值；两个 Policy 的 `environment_id` 必须不相等，且其 A/B/E refs 与 C/D/G 相应 refs 相等。数据库 fact counts、expected MinIO count 和 Qdrant point count 均从已验证制品派生，不复制到 G。

`target_preflight` 精确十二键：

`attestation_id`、`checked_at`、`checker_id`、`target_environment_id`、`outcome`、`database_empty`、`minio_prefix_empty`、`qdrant_namespace_empty`、`redis_namespace_empty`、`ingress_blocked`、`error_codes`、`evidence_sha256`。

attestation ID 为 `UuidV4`，checker 为专用受信 `Uuid`，target ID 必须等于根字段，evidence 为 `Sha256`。`outcome=passed` 时五个值必须都是 JSON boolean true且 `error_codes=[]`；`failed` 时五个值各为 boolean 或 null、至少一个不是 true，且去重排序的 `Version` error codes 非空。preflight 只能由 restore controller 按 target F 的 version/hash 实测生成，不接受 API 调用方断言。

时间顺序必须满足 `C.snapshot.snapshot_established_at <= recovery_event_at <= target_preflight.checked_at <= input_created_at`，且 `0 <= epoch_seconds(input_created_at)-epoch_seconds(checked_at) <= target_F.max_preflight_age_seconds`。`recovery_event_at` 是故障或演练恢复计时起点，不得在 preflight/G 发布之后补记；任何负年龄、超龄或时钟回退都使 `target_preflight.outcome` 必须为 failed 并使用固定 error code。

failed G 仍可 no-replace 发布作为拒绝证据，但发布/回读 G 之后必须零解密、零 target write、零 provider/Qdrant 调用、零 CR-006 transition；H 把 input stage 标 failed 且其余 stage `not_run`。passed G 的固定顺序是：初次 preflight → 发布并逐字节回读验证 G → 紧邻第一个副作用前以同一 target F profile 重查 → 仅重查 passed 才开始 H/恢复；不得在 G 发布前实施副作用，也不得把初次结果冒充重查结果。

`target_authorization` 精确两键 `mode`、`change_authorization_ref`。`mode=disposable` 时 ref=null 且 target F `restore_target_isolation_class=disposable_isolated`；`mode=explicit_change_approved` 时 ref 是 type `restore_target_change`、scope 精确匹配共同合同的有效 `AuthorizationRef`，且 target F class 必须为 `approved_isolated`。

网络 null 矩阵：

| E mode/execution | provider authorization | Qdrant transport authorization |
| --- | --- | --- |
| `snapshot_restore/none` | 必须 null | 可 null；null 时不得执行 Qdrant stage |
| `embedding_recompute/offline_local` | 必须 null | 可 null；null 时不得写目标 Qdrant |
| `embedding_recompute/networked_provider` | 可 null；null 时不得调用 provider | 可 null；null 时不得写目标 Qdrant |

non-null provider ref 的 type 固定 `embedding_provider_outbound`；Qdrant ref 固定 `isolated_qdrant_transport`，二者 scope 必须分别精确匹配共同合同。target F 对应 policy 为 `forbidden` 时 ref 必须 null，即使存在外部 token 也不能覆盖 Policy；policy 要求 per-run 时只有 scope/期限均有效的 ref 才能执行。缺授权允许生成离线/部分恢复证据，但 H 必须为 `blocked_network_authorization`，不得进入 I 的 `opened`。

`operation_log_transition_plan` 是精确十三键 object：

`restore_run_id`、`source_chain_mode`、`transition_kind`、`target_chain_id`、`target_chain_epoch_utc`、`parent_kind`、`parent_chain_id`、`parent_utc_date`、`parent_day_anchor_sha256`、`parent_snapshot_txid_snapshot_sha256`、`parent_tail_rows_sha256`、`source_database_backup_id`、`source_database_manifest_sha256`。

plan 不含且不得预造 `target_genesis_ref`。plan 的 run 等于 G；source mode、source backup ID 和 parent facts 逐字来自 C；manifest hash 等于 `source_database_manifest_ref.sha256`；target/parent chain ID 为 `UuidV4`。三态矩阵和 epoch 算法见第 5.3 节，任何字段漂移都拒绝恢复。

### 3.9 H：`pre-traffic-restore-verification-v1`

`StageEnvelope` 是精确五键 object：`outcome`、`started_at`、`completed_at`、`evidence_sha256`、`error_codes`。矩阵固定为：

| outcome | started/completed | evidence hash | error_codes |
| --- | --- | --- | --- |
| `passed` | 均 non-null 且 start <= complete | non-null | 空数组 |
| `failed` | 均 non-null 且 start <= complete | null 或 non-null | 至少一项 |
| `not_run` | 均 null | null | 空数组 |
| `pending_authorization` | 均 non-null 且 start <= complete | non-null | 空数组 |

`error_codes` 是去重排序的 `Version` 数组。一个 stage failed 后，所有后续 stage 必须 `not_run`；不得把未执行写成 passed。

根对象精确键为：

`verification_schema_version`、`canonicalization_version`、`hash_algorithm`、`restore_run_id`、`target_environment_id`、`target_environment_class`、`restore_input_ref`、`source_database_manifest_ref`、`source_minio_inventory_ref`、`qdrant_profile_ref`、`source_environment_policy_ref`、`target_environment_policy_ref`、`restore_started_at`、`verification_completed_at`、`pretraffic_ready_at`、`input_preflight_result`、`postgresql_result`、`minio_result`、`operation_log_chain_result`、`qdrant_result`、`redis_result`、`smoke_test_result`、`e2e_test_result`、`source_recovery_point_at`、`recovery_event_at`、`measured_rpo_seconds`、`rpo_threshold_seconds`、`rpo_outcome`、`measured_recovery_ready_seconds`、`technical_outcome`、`recovery_acceptance_outcome`、`errors`。

常量依次为 `pre-traffic-restore-verification-v1`、`RFC8785-JCS`、`SHA-256`。运行制品 refs 为 `ArtifactRef`，静态 refs 为 `ApprovedInstanceRef`；所有 ref、run、target ID/class 及 source/target Policy 必须与 G 一致。`H.target_environment_class=G.target_environment_class=target_F.environment_class` 且类型为 `EnvironmentClass`；target Policy environment 等于 H target，source 与 target environment ID 不相等。

结果 object 精确键：

- `input_preflight_result` 精确四键：`stage`、`restore_input_sha256`、`initial_preflight_evidence_sha256`、`side_effect_preflight`。前两个 hash 始终 non-null并分别等于 G ref hash及 G 初次 evidence；`side_effect_preflight` 精确十一键：`attestation_id`、`checked_at`、`checker_id`、`outcome`、五个同名 target boolean、`error_codes`、`evidence_sha256`。passed/failed 使用 G 同一矩阵；G 初次 failed 时 outcome=`not_run`、前三键和五个 boolean及 evidence 全 null、error codes 空。G 初次 passed 但重查 failed 时完整保留实测 booleans、error codes 和 evidence，input stage=failed、后续全 not_run且零副作用。
- `postgresql_result`：`stage`、`alembic_revision`、`application_version`、`database_facts_sha256`。后三者只在 passed 时 non-null。
- `minio_result`：`stage`、`expected_entry_count`、`restored_entry_count`、`restored_version_mapping_sha256`。后三者只在 passed 时 non-null，两个 count 必须相等。
- `operation_log_chain_result` 精确三键：`stage`、`transition_evidence_ref`、`transition`。passed 时 evidence ref 为 CR-006 发布的 `operation-log-restore-transition-evidence-v1` `ArtifactRef`，`stage.evidence_sha256=transition_evidence_ref.sha256`，`stage.started_at=evidence.restore_transition_started_at`，`stage.completed_at` 必须等于同 run CR-006 state 的 `enablement_completed_at`，transition non-null；其他 outcome 时后两者均 null。transition 精确三键 `plan`、`target_genesis_ref`、`genesis_manifest_sha256`：`plan` 必须与 G plan 的 JCS bytes 逐字相等；genesis ref 为 `ArtifactRef` 且 `target_genesis_ref.sha256=genesis_manifest_sha256`。CR-006 evidence 中的 C/G/run/plan/target/genesis/start time字段必须逐项相等：fresh 且 C row count=0 时、以及 snapshot-tail 时，`UTC-date(evidence.restore_transition_started_at)=G.target_chain_epoch_utc`；fresh row count>0 时 target epoch 只等于 C first-log UTC date并允许早于 transition date；day-anchor 只验证 parent date加一日。H 只验收实际结果，不参与执行前决策。
- `qdrant_result`：`stage`、`recovery_mode`、`expected_point_count`、`actual_point_count`、`membership_set_sha256`、`fixed_eval_result_sha256`。`recovery_mode` 始终 non-null并逐字等于 G 所引用 E 的 `recovery_mode`；其余只在 passed 时 non-null且 count 相等；pending 时均 null。
- `redis_result`：`stage`、`initialization_mode`；passed 时 mode 固定 `empty_recoverable_state`，否则 null。
- `smoke_test_result` 和 `e2e_test_result`：`stage`、`suite_version`、`suite_sha256`、`passed_case_count`、`failed_case_count`。stage 为 passed/failed 时四个 detail non-null，passed 要求 failed count=0；not_run 时全 null。

`errors[]` 每项精确四键：`error_code`、`stage`、`safe_detail_code`、`trace_id`；前三者为 `Version`，trace ID 为 `Uuid`。不得含异常正文、命令、DSN、对象内容或 secret。technical failed 时 errors 至少一项；passed/blocked 时为空。

时间和 outcome 矩阵：

- `source_recovery_point_at` 等于 C 的 `snapshot.snapshot_established_at`；`recovery_event_at` 等于 G，且 `source_recovery_point_at <= recovery_event_at <= G.target_preflight.checked_at <= G.input_created_at <= restore_started_at`。
- `restore_started_at` 和 `verification_completed_at` 始终 non-null，且 `G.input_created_at <= restore_started_at <= verification_completed_at`。每个 non-null stage time 都落在该闭区间内；副作用前重查只能发生在 `restore_started_at` 之后。
- 重查 passed 时 `side_effect_preflight.checked_at <= postgresql_result.stage.started_at`，且两者精确 epoch 秒差不得超过 target F `max_preflight_age_seconds`；PostgreSQL stage 是首个允许产生副作用的 stage。重查 failed/not_run 时不得存在任何后续 non-null stage time。
- `measured_rpo_seconds = ceil(recovery_event_at - source_recovery_point_at)`，按精确 UTC epoch 秒计算；threshold 等于 F，`rpo_outcome` 为 `met` 当且仅当 measured <= threshold，否则 `missed`。
- `technical_outcome` 只允许 `passed_for_release_review/failed/blocked_network_authorization`。
- stage 固定顺序为 input/preflight → PostgreSQL → MinIO → operation-log → Qdrant → Redis → smoke → E2E。technical passed 时八个 stage 全 passed，`pretraffic_ready_at=verification_completed_at` 且 non-null，`measured_recovery_ready_seconds=ceil(pretraffic_ready_at-recovery_event_at)`；failed/blocked 时 pretraffic ready 和 measured ready 同时 null。
- 任一 stage failed => technical failed且后续全 not_run。没有 failed 且 Qdrant pending 时，Redis 可 passed，smoke/E2E 必须 not_run，technical outcome=blocked；其他组合非法。
- `recovery_acceptance_outcome` 只允许 `passed/failed_integrity/failed_sla/blocked_authorization`，封闭四行矩阵为：`passed_for_release_review + met -> passed`、`passed_for_release_review + missed -> failed_sla`、`failed + met|missed -> failed_integrity`、`blocked_network_authorization + met|missed -> blocked_authorization`。不得使用“其余对应”、优先级推断或实现默认值。
- H 永远不含 `traffic_opened_at`，也不得在发布后更新。

### 3.10 I：`traffic-release-attestation-v1`

根对象精确键为：

`attestation_schema_version`、`canonicalization_version`、`hash_algorithm`、`release_attestation_id`、`release_attempt_id`、`restore_run_id`、`target_environment_id`、`target_environment_class`、`target_environment_policy_ref`、`ingress_id`、`pretraffic_verification_ref`、`previous_release_attestation_ref`、`release_authorization_ref`、`sla_exception_authorization_ref`、`production_release_authorization_ref`、`originating_release_attempt_id`、`originating_release_precheck_at`、`originating_traffic_release_authorization_ref`、`originating_sla_exception_authorization_ref`、`originating_production_release_authorization_ref`、`preexisting_emergency_close_authorization_evidence_sha256`、`originating_actual_rto_status`、`originating_traffic_opened_at`、`originating_traffic_state_observed_at`、`originating_measured_rto_seconds`、`originating_rto_outcome`、`originating_traffic_state_evidence_sha256`、`release_actor_id`、`action`、`close_mode`、`release_precheck_at`、`prospective_rto_seconds`、`decision_at`、`traffic_opened_at`、`traffic_closed_at`、`traffic_state_evidence_sha256`、`measured_rto_seconds`、`rto_threshold_seconds`、`rto_outcome`、`reason_code`。

常量依次为 `traffic-release-attestation-v1`、`RFC8785-JCS`、`SHA-256`；attestation/attempt ID 为 `UuidV4`，release actor 为 `Uuid`；H/I refs 为 `ArtifactRef`，target Policy 为 `ApprovedInstanceRef` 且必须等于 H target Policy并解析为同一 target ID/class；`I.target_environment_class=H.target_environment_class=G.target_environment_class=target_F.environment_class` 且类型为 `EnvironmentClass`；`action` 只允许 `opened/held/closed`。

条件矩阵：

| action/close mode | previous ref | release auth | opened/closed time | measured RTO/threshold/outcome | emergency origin fields | reason |
| --- | --- | --- | --- | --- | --- | --- |
| `opened/null` | null 或前一 held I | non-null `traffic_release` | opened non-null、closed null | 全 non-null | 全 null | null |
| `held/null` | null | null 或有效 `traffic_release` | 两者 null | 全 null | 全 null | non-null held code |
| `closed/normal` | 必须为前一 opened I | non-null `traffic_close` | opened null、closed non-null | 全 null | 全 null | normal-close code |
| `closed/emergency_reconciliation` | null 或前一 held I | non-null `traffic_emergency_close` | opened null、closed non-null | 全 null | 按下述原 attempt 矩阵 | emergency-close code |

`reason_code` 的封闭 enum 为：held 使用 `PRETRAFFIC_NOT_READY/VERIFICATION_STALE/RELEASE_AUTHORIZATION_MISSING/PRODUCTION_RELEASE_AUTHORIZATION_MISSING/SLA_EXCEPTION_MISSING/NETWORK_AUTHORIZATION_MISSING/TRAFFIC_STATE_UNKNOWN`；normal close 使用 `ROLLBACK_APPROVED/POST_RELEASE_INTEGRITY_FAILURE/POST_RELEASE_SECURITY_FAILURE`；emergency reconciliation 只允许 `TRAFFIC_SWITCH_FAILURE/TRAFFIC_SWITCH_BOUND_EXCEEDED`；opened 必须 null。held 同时命中多项时固定采用首个成立项：`NETWORK_AUTHORIZATION_MISSING`（H blocked）→ `PRETRAFFIC_NOT_READY`（H failed）→ `VERIFICATION_STALE` → `TRAFFIC_STATE_UNKNOWN` → `RELEASE_AUTHORIZATION_MISSING` → `PRODUCTION_RELEASE_AUTHORIZATION_MISSING`（仅 target class=production 且没有有效 production ref）→ `SLA_EXCEPTION_MISSING`。非 production target 永不得命中 production-missing code。emergency 同时命中时 `TRAFFIC_SWITCH_BOUND_EXCEEDED` 高于 `TRAFFIC_SWITCH_FAILURE`。所有 action 的 `traffic_state_evidence_sha256` 均 non-null，绑定本次 decision 前后对 ingress 权威状态的读取证据。

任一 non-null previous ref 必须指向非自身的既有 I，且其 H ref、run、target ID/class、target Policy 和 ingress 都与当前 I 相等；previous `decision_at` 必须严格早于当前 decision。opened 的 previous 只可 null/held，normal close 只可 opened，emergency 只可 null/held；held 固定 null。opened 引用 held 时 `previous.release_attempt_id=current.release_attempt_id`，并满足 `previous.release_precheck_at <= previous.decision_at < current.release_precheck_at <= current.traffic_opened_at <= current.decision_at`；`previous.release_authorization_ref` non-null 时必须逐字等于 current release auth，为 null 时 current traffic-release auth 的 `approved_at` 必须严格晚于 previous decision且不晚于 current precheck。previous production ref non-null 时必须逐字等于 current production ref；previous reason=`PRODUCTION_RELEASE_AUTHORIZATION_MISSING` 时 current production ref必须 non-null且 `previous.decision_at < approved_at <= current.release_precheck_at`，previous reason=`SLA_EXCEPTION_MISSING` 时 current SLA ref也必须 non-null并满足同一批准时间区间，禁止用声称在 previous decision 前已存在的 ref 推翻既有 missing 事实。emergency 引用 held 时 `previous.release_attempt_id=current.originating_release_attempt_id`、`previous.release_precheck_at=current.originating_release_precheck_at` 且 previous release auth 必须逐字等于 originating traffic-release auth，禁止拼接其他 held attempt。normal close 必须满足 `current.release_attempt_id=previous.release_attempt_id` 及 `previous.traffic_opened_at <= previous.decision_at <= current.traffic_closed_at <= current.decision_at`；当前 `traffic_close` scope 的 `release_attempt_id` 必须等于该共同 attempt，`previous_opened_attestation_sha256` 必须等于 previous ref hash，其批准时间不晚于 close time。

opened/held 的 `release_precheck_at` 和 `prospective_rto_seconds` non-null；closed 时两者 null。令 `verification_age_seconds=epoch_seconds(release_precheck_at)-epoch_seconds(H.verification_completed_at)`，负值始终非法。opened 必须满足 `0 <= age <= target_F.max_pretraffic_verification_age_seconds`；held 且 reason=`VERIFICATION_STALE` 必须满足 `age > max`，其他 held reason 必须满足 `0 <= age <= max`。freshness 只使用 release precheck，不得改用 decision/opened 时点。prospective RTO 固定为 `ceil(epoch_seconds(release_precheck_at)+F.max_traffic_switch_duration_seconds-epoch_seconds(H.recovery_event_at))`。held/closed 的 `sla_exception_authorization_ref` 必须 null；opened 按下段条件取 null/non-null。`opened` 只允许引用 technical outcome 为 `passed_for_release_review` 的 H。`measured_rto_seconds=ceil(epoch_seconds(traffic_opened_at)-epoch_seconds(H.recovery_event_at))`；threshold 等于 target F，outcome 以 `<=` 判 `met/missed`。opened 时 `release_precheck_at <= traffic_opened_at <= decision_at`；held 时 `release_precheck_at <= decision_at`。

emergency 的 origin group 包含原有六字段以及 `originating_actual_rto_status`、`originating_traffic_opened_at`、`originating_traffic_state_observed_at`、`originating_measured_rto_seconds`、`originating_rto_outcome`、`originating_traffic_state_evidence_sha256`；其他 action 十二字段全为 null。当前 close `release_attempt_id` 必须不同于 originating open attempt ID；originating traffic-release ref 始终 non-null，`traffic_emergency_close` scope 同时绑定这两个 ID及该 originating traffic-release authorization ID。non-null 三个原授权 ref 必须绑定同 H/run/target/Policy/ingress和 originating attempt；每个原授权的 `approved_at <= originating_release_precheck_at < expires_at`。previous 为 held 时，全局顺序固定为 `H.verification_completed_at <= originating_release_precheck_at=previous.release_precheck_at <= previous.decision_at < originating_traffic_state_observed_at <= traffic_closed_at <= decision_at`；previous 为 null 时固定为 `H.verification_completed_at <= originating_release_precheck_at <= originating_traffic_state_observed_at <= traffic_closed_at <= decision_at`。

originating actual RTO 矩阵固定：`known_opened_at` 要求 opened time、observed time、measured seconds、`met/missed` outcome 和 ingress evidence hash 全 non-null，满足 `originating_release_precheck_at <= originating_traffic_opened_at <= originating_traffic_state_observed_at <= traffic_closed_at`，measured 按 H recovery event 计算且 threshold 取 target F；`unknown_opened_at` 要求 opened time/measured null、observed time non-null、outcome=`unknown`、evidence hash non-null并证明权威状态只能确认“曾或已打开”而不能给出精确打开时点。`TRAFFIC_SWITCH_BOUND_EXCEEDED` 要求 known opened time 晚于 `precheck + max switch duration`，或 unknown 的 observed time不早于该 deadline；仅在 deadline 内已获得确定失败证据、但 reconciliation 又发现意外打开时使用 `TRAFFIC_SWITCH_FAILURE`。

originating SLA/production/traffic ref 只记录 originating precheck 当时真实存在且有效的授权，严禁 emergency 时补签或反推。originating traffic-release scope 的 attempt/run/target/H/Policy/ingress 必须逐字等于 origin group；previous held 存在时，其 precheck、traffic-release ref及相应 scope也必须逐字等于该 origin group。H RPO 或 prospective RTO 在 originating precheck 已 missed 时，originating SLA ref 必须当时已 non-null并覆盖这些已知 metrics；二者均 met 时 ref 必须 null，后续 actual missed/unknown 只触发 emergency close，不得伪称原 attempt 已有 `actual_rto` exception。唯一例外是 previous held 的 reason=`SLA_EXCEPTION_MISSING`：originating SLA ref 必须仍为 null，表示违规 open attempt，当前记录只能 emergency close而不能追认权限。target class=production 时原 production ref必须 non-null；但 previous held reason=`PRODUCTION_RELEASE_AUTHORIZATION_MISSING` 时必须仍为 null并同样只允许 emergency close；非 production 必须 null。`preexisting_emergency_close_authorization_evidence_sha256` 固定为 `SHA256(JCS({"authorization_ref":current.release_authorization_ref,"authorization_scope":resolved_current_traffic_emergency_close_scope}))`；该 scope 的两个 attempt、run、target、H、Policy、originating precheck、originating traffic-release authorization ID 与 ingress 必须逐项等于当前/origin group，且 current release auth 的 `approved_at <= originating_release_precheck_at`、`traffic_closed_at < expires_at`。没有该预置且可复算的 emergency-close 能力时禁止开始 open attempt。

`production_release_authorization_ref` 在 `opened` 且 target class=production 时必须为有效 type `production_release` ref；opened 非 production和所有 closed 均必须 null。held 的非 production 必须 null；held 的 production 可携带 precheck 当时有效且 scope 精确匹配的 ref以证明该门禁已满足，也可为 null，此时在所有更高优先级 held reason 不成立时必须使用 `PRODUCTION_RELEASE_AUTHORIZATION_MISSING`。该 ref 与 traffic release、SLA exception 相互独立，任何一个都不能替代另一个。

H 的 RPO missed、prospective RTO 超 threshold 或实际 RTO missed 都要求在流量切换前已有 scope 精确匹配的 type `sla_exception` ref；三者均 met 时该 ref 必须 null。release controller 必须在固定 precheck 后于 target F 最大 switch duration 内完成 CAS 式流量切换并从 ingress 权威状态取得实际 opened time。超过 bound、结果未知或实际跨阈值却没有预先 exception 时不得发布 opened；未打开则发布 held，已意外打开则按 emergency 矩阵受控 close。SLA miss 不得标为 SLA passed；完整性/安全通过且有独立 exception 才可安全放流量。正常关闭使用 `closed/normal`；所有 I 都 create-only，不修改旧 H/I。

## 4. 备份生成、一致性与单向 hash 链

### 4.1 PostgreSQL snapshot 所有权

backup orchestrator 必须：

1. 使用 A，以 `SERIALIZABLE READ ONLY DEFERRABLE` 事务建立 snapshot，记录数据库时钟的 `snapshot_established_at` 并导出 snapshot。
2. 在 pg_dump、数据库事实引用枚举、database facts checksum 和 operation-log tail 枚举全部结束前保持导出事务存活；所有数据库读取会话导入同一个 snapshot。
3. dump 明文先 hash/size，再按 B 加密并记录 envelope/key ID，最后验证密文 ref/hash/size。
4. WAL LSN、system identifier 和 timeline 只用于误恢复检测，不替代 MVCC 边界。
5. 先完成并发布 D，再发布 C；失败时不得发布成功 C。

### 4.2 MinIO 独立副本

数据库事实引用只从 A 固定 query 在同一 snapshot 中产生；每个必须恢复的引用都必须带 bucket/key/content hash/size。缺 hash 的派生 preview 只能在 A 明确给出确定性重建规则时排除，否则备份失败。

源业务 key 和 audit-evidence key 都必须 no-replace。D 的 exact-version resolver、write barrier、version listing、源读取、加密、目标 create-only 写入和密文回读验证全部成功后，entry 才能进入发布 D。目标 storage/fault domain/principal 必须与源分别独立，源 delete/lifecycle 不得级联目标。任何独立性断言只能来自 F 和 D 的机器字段，不接受自由文本说明。

### 4.3 A..I 单向依赖

静态实例与运行实例的唯一依赖方向为：

1. A、B、E 独立生成并审批；
2. 每个 F source/target Policy 实例只引用 A/B/E；
3. D 只引用 B/E/source F、运行授权、`database_backup_id` 和数据库 snapshot hash；D 禁止引用 C hash；
4. C 只引用 A/B/D/source F；
5. G 只引用 C/D/E、source/target F 和运行授权，并冻结不含 genesis ref 的 transition plan；
6. CR-006 只消费 C/G 的事实和 plan，发布自己的 transition evidence；
7. H 只引用 G/C/D/E、source/target F 和 CR-006 已发布 evidence；
8. I 只引用 H、target F、矩阵允许的前一 I 和外部 release/close/exception/production authorization。

任何下游 hash 不得回写上游。Schema 文件不得嵌入彼此 raw file hash；跨 Schema 复用只使用固定 version URI 或内嵌 `$defs`。九个制品 Schema raw hash、A/B/E Profile 实例、F Policy instance set 和测试向量 bundle hash 只由外部 approved-artifact 审批记录汇总。五个支持 Schema 都不保存自身 hash；approval-record/detached-evidence/signer-registry 三个 pre-meta Schema及唯一 signer registry 实例在 snapshot 后、meta record 前生成，request-sync-authorization/post-sync-attestation 两个 post-meta Schema 在 meta 后生成。registry 只经第 8.2/8.4 节 package 外 authenticated verifier input 的 trust-anchor pin 引入，禁止从待验 package 推导 pin或用 registry 内任一 key 自签 registry；其后实例只向后指向既有 Schema/registry/record/signature，因此不存在 Schema、自身 hash、registry 自签或审批记录环。

## 5. 恢复顺序、chain transition、网络与 SLA

### 5.1 固定恢复顺序

1. 验证 approved-artifact 审批记录、五个支持 Schema、九个制品 Schema、A/B/E Profile 和所选 source/target F Policy instance set；
2. 验证 C、D 的 no-replace bytes/hash、独立 backup storage 和互相引用；
3. 保持 ingress、Backend、Worker 和调度停用，按 target F 执行初次 target preflight；
4. 以初次实测结果和 C/D/F 生成 G，no-replace 发布并逐字节回读验证；G failed 时发布 failure H 后停止且零副作用；
5. 紧邻首个副作用前按同一 target F 再次实测 preflight，把完整结果写入 H input result；重查 failed 时停止且零副作用；
6. 校验数据库密文，解密并校验明文，恢复 PostgreSQL；
7. 验证 Alembic/application version 和 C 的完整 database facts；
8. 按 D 解密恢复全部 MinIO entry，生成 source/backup/restored version mapping；
9. CR-006 消费 C/G plan，在独占锁内完成 operation-log transition，发布并回读自己的 evidence；H 随后验证 plan、genesis 与 evidence；
10. 在所需授权有效时恢复/重算 Qdrant；缺授权时不联网、不写 Qdrant并进入 pending；
11. 将 Redis 初始化为空的可恢复派生状态，执行 smoke/E2E并发布 H；
12. 只有 H technical passed 后，外部 release controller 才可按 I 的授权矩阵切换/关闭流量并发布 I。

任一步出现未知副作用时不得盲重试；先查询目标 no-replace object、数据库 target marker 和外部流量权威状态，再按同 run 幂等恢复或创建新隔离目标。任一失败都保持 ingress 关闭，并尝试发布 failure H；若证据存储本身不可用，只能写脱敏外部部署日志并保持 fail closed，不得声称 H 已发布。

### 5.2 最小验证门禁

- PostgreSQL：system/timeline、revision、application version、relation 集合、row count 和 content hash 全匹配。
- MinIO：D 全量恢复，source/backup/restored mapping 无遗漏、重复、覆盖或 hash/size 漂移。
- operation-log：source/target 矩阵、父证据、tail 和 genesis 全部验证。
- Qdrant：collection config、point count、membership hash、payload schema 和固定评测全匹配。
- Redis：只允许安全空初始化或从 PostgreSQL 事实重建。
- 安全：制品、错误和日志无 secret、DSN、Token、原始异常或业务正文。
- 技术完整性失败绝对禁止 `opened`；SLA miss 按第 3.10 节处理，不得伪造 passed。

### 5.3 source→target chain transition

G 的十三键 `operation_log_transition_plan` 是执行输入；H 的三键 transition 是 plan 加实际 genesis 的执行结果。plan null 矩阵固定为：

| C source mode | transition | target chain/epoch | parent kind | parent chain | parent date/day-anchor | parent snapshot/tail | source backup/manifest |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `chain_absent` | `fresh_genesis` | non-null | `none` | null | 全 null | 全 null | 全 non-null |
| `initialized_unsealed` | `snapshot_tail_fork` | non-null | `snapshot_tail` | C source chain ID | 全 null | C snapshot txid/tail hash | 全 non-null |
| `sealed` | `day_anchor_fork` | non-null | `day_anchor` | C anchor chain ID | C covered date/day-anchor hash | 全 null | 全 non-null |

- fresh：C `source_operation_log_row_count=0` 时 target epoch 固定为 `UTC-date(G.input_created_at)`；大于零时固定为 `UTC-date(C.source_operation_log_first_log.created_at)`。零行 plan 只可在 `UTC-date(transition started_at)=target epoch` 时执行，否则必须创建新 G；genesis parent 为 null。
- snapshot-tail：target epoch 固定为 `UTC-date(G.input_created_at)`，也只能在该 UTC date 执行；parent 精确绑定 C source chain ID、snapshot txid hash、tail rows hash、source backup ID 和 source manifest hash，新链 seed 使用 tail rows hash。
- day-anchor：target epoch 固定为 `C.covered_through_utc_date + 1 day`；parent 精确绑定 C anchor chain/date/day-anchor、source backup ID 和 source manifest hash，新链 seed 使用 parent day anchor。

CR-006 必须消费 C 和已经发布/验证的 G plan，在停写及其独占锁内完成 state transition、实际 genesis no-replace 发布和回读，然后发布 `operation-log-restore-transition-evidence-v1`。该 evidence 内嵌的 `transition` 必须是与 H 完全相同的精确三键 object `plan/target_genesis_ref/genesis_manifest_sha256`，其中 plan 与 G 逐 JCS byte 相等，genesis ref/hash 绑定实际发布制品；H 的 stage evidence hash必须等于该 evidence `ArtifactRef.sha256`，H transition 又必须与 evidence.transition 逐 JCS byte 相等。DEP-005 的 meta/approved-artifact 审批不等待 CR-006 先批准，但 CR-006 未完成消费与测试前不得真实恢复或联合批准；任何地方都不得把尚未生成的 H 当作 transition 执行输入。

### 5.4 双网络边界

provider outbound、source Qdrant snapshot read 和 isolated target Qdrant write 是三个彼此不可替代的 per-run scope；后两者同属 Qdrant 边界但不得共享 ref：

- provider authorization 只允许 E 为 `networked_provider` 的 embedding 请求，逐项匹配第 3.1 节 versioned JCS scope；无论 provider 名称为何都必须绑定可寻址、Schema/签名可验证且当前有效的 `CR002ProviderEnvironmentApprovalRef`。per-run scope 的 provider/model/target/endpoint/base-url/transport/domain/expiry 不能超过该环境批准，禁止重定向、IP 或其他 host。
- provider ID 不能决定是否需要 CR-002 批准；test/staging/rehearsal 等非 production target 只能使用另行获批的 `environment_scope=fixed_test_provider`，production 只能使用独立 production 批准。未来取得有效批准后可以在其精确范围内测试，本修订不把当前未授权永久化；当前两类 CR-002 环境批准、per-run provider ref、网络调用和 production 仍全部未授权。
- source Qdrant snapshot read 与 isolated target Qdrant write 分别匹配独立 F policy、authorization type、endpoint 和 collection set；不得共享 ref或扩大到公网、production 或任意 collection。
- 任一缺失、过期或 scope 不匹配都不执行对应调用；H 记录 pending/blocked。合同审批、Schema/Profile hash、离线向量或 `network_scope=none` 永远不等于运行授权。

### 5.5 RPO、RTO 与 SLA

- `source_recovery_point_at` 取 C 的数据库 snapshot 建立时刻；`recovery_event_at` 由 G 在任何 target preflight、G 创建或恢复准备之前冻结，并满足第 3.8/3.9 节完整时间链。
- `measured_rpo_seconds=ceil(epoch_seconds(recovery_event_at)-epoch_seconds(source_recovery_point_at))`，threshold 取 source F；负值非法而不是归零。
- H 的 `measured_recovery_ready_seconds` 是技术恢复就绪时长，不冒充用户可用 RTO。
- 正式 `measured_rto_seconds=ceil(epoch_seconds(traffic_opened_at)-epoch_seconds(recovery_event_at))`，threshold 取 target F且只在 I `opened` 计算。rehearsal 使用隔离 rehearsal ingress；production 使用 production ingress 且需要独立 production authority。
- RPO/RTO miss 使 SLA/演练验收失败；不得篡改时间或 threshold。完整性安全通过但 SLA miss 时，恢复安全流量需要独立 `sla_exception`；完整性或安全失败不可用 exception 绕过。

## 6. 审计载体、零 action delta 与测试向量

### 6.1 审计载体

DEP5-D-008 的机器接口固定为：

- `no_operation_log_write=true`；
- `no_new_action=true`；
- `operation_log_action_delta=0`；
- `audit_carrier=no_replace_artifacts`。

成功证据为 C、D、H、I，存在 chain 时加 CR-006 genesis；失败证据为 failure H（可发布时）和固定错误码的脱敏部署日志。备份、恢复、失败、技术重试、held/closed 都不得为 CR-008 发明 action。未来改变该选择必须发布新的 DEP 和 CR-008 修订。

### 6.2 approved-artifact 前测试向量

至少必须留存以下离线、可重复证据：

1. 九个制品 Schema 和五个支持 Schema 的正例，以及 duplicate key、未知字段、缺字段、错误类型/enum/pattern/null 的反例；
2. 所有共同类型边界、safe integer 越界、非法日期/时间、BOM/CRLF 和 Unicode 不规范输入；
3. A/B/E Profile 与 source/target F Policy set 的 scope/null/环境交叉引用、错误 hash/version 和 secret 扫描；
4. 三种 source mode、三种 G plan、CR-006 evidence、H actual genesis 和每个非法 parent/null/epoch 组合；
5. database snapshot、facts、D backup ID/snapshot hash，以及 C database encrypted ref 与 D backup storage 不一致时拒绝；
6. source version 零/多匹配、inclusive observed-max 同时间戳遗漏、barrier/listing 不稳定、fault domain/principal 相同、目标 key 冲突和 copy 篡改时拒绝；
7. Qdrant snapshot ID/source version、membership/count/config/payload 不一致时拒绝；
8. 九种 authorization scope 的正反向量；排序、expiry、fixed provider CR-002 ref、source/target Qdrant endpoint 或 scope 漂移时零调用；
9. G initial passed/failed、failed G 可发布且零副作用、发布回读前副作用、重查 failed、过期 preflight和 change authorization/isolation 映射反例；
10. stage failed 后 downstream not_run、H recheck failure evidence、CR-006 stage hash/ref 漂移、failure H 发布失败、no-replace 重跑和不同 bytes 冲突；
11. RPO/RTO 等于、低于、高于 threshold；SLA miss 无 exception 拒绝 opened，有 exception 仍标 missed；
12. H 永无 traffic time，I previous/H/run/target/Policy/时序矩阵、emergency origin 证据、production auth 和旧制品不可修改；
13. approval APPROVED meta/artifact 与 REJECTED 三矩阵、decision partition、policy set/schema hash、safe notes code 的正反例；
14. post-sync attestation 的八角色 record set digest、授权 ref/hash、九文件排序/hash、pre/post baseline、result 矩阵和 generator 漂移反例；
15. 全部制品、审批、错误和日志无 key、Token、DSN、原始异常或敏感正文；
16. 从实例引用构建 A..I、CR-006 evidence、五个支持 Schema 与审批汇总图并机械证明无环。

在任何 provider-environment approval record 生成前，独立 runtime/provider support Schema `cr002-provider-environment-approval-v1` 还必须通过与第 1、2、8、13、15 项相同的 Schema、签名、模型 allowlist、expected-ref 和 secret-safe 正反向量；该额外门禁不把它并入当前五个支持 Schema或 approved-artifact bundle。上述向量只证明合同和离线制品；没有真实备份、隔离恢复、网络授权下的实际调用和 RPO/RTO 实测，不得声称运行验收通过。

## 7. CR 接口、迁移所有权与无环同步顺序

### 7.1 消费接口

| 消费方 | DEP-005 提供 | 消费方必须做 |
| --- | --- | --- |
| CR-006 | C chain union/snapshot/tail facts、G `operation_log_transition_plan` 和九类 artifact version/hash | 消费 C/G plan，在锁内完成 transition/genesis，发布 `operation-log-restore-transition-evidence-v1`，供 H 事后逐项验证 |
| CR-008 | `no_new_action=true`、`action_delta=0`、`audit_carrier=no_replace_artifacts`、DEP-only post-sync attestation | 在 E 的 ordered sync lineage 中把 DEP 中间 baseline 与其余上游同步证据推进到 aggregate baseline，并在最终 registry evidence 明确记录 DEP-005 零增量 |
| Request 同步 | 已批准决策、九类制品、零 delta、运行/网络/生产边界 | 只同步已批准 DEP-005 事实并重算 baseline，不预写 CR-006/008 未批准内容 |

DEP-005 不依赖 CR-006/008 的最终 action 总数，也不要求它们先批准；CR-006/008 在消费本合同前不得进入最终联合批准。

### 7.2 唯一无环顺序

1. 完成第 1—8 节静态复核并生成不含审批状态的 decision snapshot；
2. 从该未改字节 snapshot 生成、离线独立复核 `source-contract-approval-record-v1`、共同 `dep005-detached-approval-evidence-v1`、`approval-signer-registry-v1` 三个 pre-meta 支持 Schema及唯一 no-replace signer registry 实例的 raw bytes/hash，并由 package 外既有 approval-system trust anchor产生第 8.2 节 authenticated pin；它们均不含 snapshot hash、record instance hash 或自身 hash，registry 不得自签；
3. 八个角色使用同一三个 pre-meta Schema、同一 signer registry、同一 snapshot 和 detached signature 分别提交 `meta_contract_only` record，全部 APPROVED 后才形成 meta 批准；
4. meta 批准后生成九个制品 Schema、`request-sync-authorization-v1` 与 `dep005-post-sync-baseline-attestation-v1` 两个 post-meta 支持 Schema、A/B/E Profile、所需 F Policy instance set 和测试向量，完成 `approved_artifact` 审批；approved-artifact record 必须绑定全部五个支持 Schema及同一 signer registry；
5. 完成 CR-006/CR-008 静态合同复核与各自 contract-review snapshot，只生成并独立复核其共同 `request-sync-transition-evidence-v1`、CR-004/CR-010 fact-set 与其他 shared support Schema raw bytes/hash；此步不生成 A—E/final registry、不形成联合批准，也不授权实现；
6. 取得绑定 DEP revision/snapshot/record-set/source baseline/九个路径的单独 Request 同步授权后，只同步 DEP-005 已批准事实，重算 baseline 并按第 8.6 节生成 DEP-only post-sync baseline attestation；
7. 其余 CR-003/004/005/007/009/010 分别以第 8.2/8.5 节 role-complete signed approval binding和单 source 同步授权产生 transition evidence；CR-008 E 按下述固定 lineage 把 DEP 中间 baseline推进到 final aggregate baseline；
8. CR-006 只证明其 transition evidence Schema 与 C/G plan/H 后验合同兼容，CR-008 消费零 action delta并生成 final registry/aggregate evidence；此步不读取或执行任何 per-run C/G。随后对 CR-006/CR-008 静态 artifacts进行原子联合审批；
9. 取得相应授权后同步 CR-006/CR-008 自身内容，再实施 migration、wrapper 和运行代码；
10. 真实备份/隔离恢复开始后，CR-006 才可消费该 run 已验证的 C/G transition plan并发布 H 所需 evidence；provider/Qdrant 网络和 production 工作仍分别取得运行授权。

CR-008 E 的 `sync_evidence_chain` 固定按 `DEP-005/CR-003/CR-004/CR-005/CR-007/CR-009/CR-010` 排序；每项精确七键 `source_id/revision/decision_snapshot_sha256/pre_baseline_manifest_sha256/post_baseline_manifest_sha256/sync_evidence_ref/sync_evidence_sha256`。首项 ref/hash 必须等于本 DEP post-sync attestation，pre 等于第 1.2 节 source baseline，post 等于 DEP-only `post_sync_baseline_manifest_sha256`；其后每项 pre 等于前项 post，末项 post 才是 `post_all_upstream_sync_baseline_manifest_sha256`。joint package 必须同时绑定 DEP attestation ref/hash、CR-008 E ref/hash和两个独立 baseline hash；不得要求二者相等，也不得因 bytes 偶然相等而把两个语义身份合并。

该顺序满足 CR-008“已批准上游事实先同步 Request，未批准 CR-006/008 不提前同步”的门禁。第 5 步只建立静态 support bytes，不能反向批准 CR-006/008。缺少第 6 步授权时，DEP-005 的合同审批仍有效，但 DEP attestation、aggregate E、CR-006/008 最终制品和联合审批保持阻断。

### 7.3 migration 和计数所有权

本合同不拥有数据库 migration，不新增表/字段/endpoint/action。实现若发现需要非零 delta，必须停止并提出新 CR；不得把变化隐藏在 DEP-005-R1。九类 JSON 制品使用外部 no-replace 存储，不构成核心表。

## 8. 审批记录、snapshot 算法与禁止边界

### 8.1 两级审批范围

| approval scope | 可批准内容 | 不授权内容 |
| --- | --- | --- |
| `meta_contract_only` | DEP5-D-001—009、A..I 九类结构、五个支持合同结构、共同类型、状态矩阵、公式、DAG、同步顺序与零 delta；外部 meta record 还必须绑定三个 pre-meta 支持 Schema 的真实 raw hash、同一可寻址 signer registry 与外部 trust-anchor pin | 不绑定九个制品 Schema、两个 post-meta 支持 Schema 的真实 hash、Profile/Policy 实例或 vector，不授权备份、恢复、网络、Request 同步或 production |
| `approved_artifact` | 九个制品 Schema raw hash、五个支持 Schema raw hash、同一 signer registry、A/B/E Profile instance set、F Policy instance set 和测试向量 bundle | 不预生成 C/D/G/H/I 运行实例，不自动授权 Request 同步、任何网络调用、真实恢复或 production |

### 8.2 `source-contract-approval-record-v1` 支持 Schema

该 Schema 与第 8.3 节 detached-evidence Schema 只能在本修订静态 snapshot 已生成且第 1—8 节 bytes 不再变化后生成；两份 Schema 都不得包含 snapshot 值、record instance ref/hash、自身 raw hash或审批状态。独立实现复核其 raw bytes/hash 后，八个 meta record 才能引用同一真实 hash；Schema 或第 1—8 节随后变化必须提升 DEP revision并废弃全部旧 record，不能反填原 Schema/record。

`ApprovalSignerRegistryRef` 是精确七键 object：`schema_version`、`schema_sha256`、`registry_version`、`registry_ref`、`registry_sha256`、`trust_anchor_pin_ref`、`trust_anchor_pin_sha256`。Schema/version/hash 分别固定或使用 `approval-signer-registry-v1/Version/Sha256`；两个 ref 均为 `ArtifactRef` 且各自显式 hash 等于 ref.sha256。`registry_ref` 指向通过第 8.4 节 exact raw Schema 的 no-replace registry JCS；`trust_anchor_pin_ref` 指向外部 approval system 通过预先配置 trust anchor 认证并钉住同一 Schema/version/ref/hash tuple 的 no-replace pin。validator 必须从 package 外的 authenticated verifier input 取得并逐字匹配整个七键 expected object，禁止只信待验对象自报的 pin ref/hash，也禁止从待验 registry、approval record、signature 或 artifact bundle 自行推导。

每位审批人的外部 no-replace 记录必须通过该 JSON Schema。Schema 使用 `record_kind` 区分 DEP 与其他上游合同，但两类共用一个根对象和一套签名证据；根对象精确三十键：

`approval_record_schema_version`、`canonicalization_version`、`hash_algorithm`、`record_kind`、`approval_record_id`、`source_id`、`source_revision`、`approval_scope`、`approver_id`、`approver_name`、`approver_role`、`decision`、`selected_decisions`、`rejected_decisions`、`decision_snapshot_marker`、`decision_snapshot_sha256`、`source_baseline_manifest_sha256`、`approval_record_schema_sha256`、`detached_approval_evidence_schema_sha256`、`request_sync_authorization_schema_ref`、`sync_evidence_schema_ref`、`artifact_bindings`、`deltas`、`environment_scope`、`network_scope`、`production_release_scope`、`decided_at`、`evidence_ref`、`evidence_sha256`、`safe_notes_code`。

- 三个常量依次为 `source-contract-approval-record-v1`、`RFC8785-JCS`、`SHA-256`；record ID 为 `UuidV4`，decision 为 `APPROVED/REJECTED`。`approver_id` 为 `Uuid`；name 是 1..128 code point、无首尾空白/控制字符的 string；role 是封闭 enum `requirements_product/architecture/data_dba/backend_api/frontend_ui/ai_rag/ops/security/test`。一条 record 只代表一个 role；同一人承担多个角色时必须为每个 role 单独生成 record。
- `record_kind/source_id/source_revision/approval_scope/decision_snapshot_marker/required roles/selected decisions/deltas` 使用下表唯一矩阵。selected/rejected 数组按表内声明顺序、无重复、互不相交；APPROVED 时 selected=全集且 rejected=[]，REJECTED 时两者构成全集分区且 rejected 非空。

| record kind / source | revision / scope / marker | 必需 roles | selected decisions 全集 | deltas `(api,core,migration,action)` |
| --- | --- | --- | --- | --- |
| `dep005_contract/DEP-005` | `DEP-005-R1`；`meta_contract_only/approved_artifact`；第 8.7 节拼接得到的本文件 marker bytes | `requirements_product,architecture,data_dba,backend_api,ai_rag,ops,security,test` | `DEP5-D-001,DEP5-D-002,DEP5-D-003,DEP5-D-004,DEP5-D-005,DEP5-D-006,DEP5-D-007,DEP5-D-008,DEP5-D-009` | `0,0,0,0` |
| `source_contract/CR-003` | `CR-003-R1`；`contract_only`；`## 6. 当前状态` | 上述八角色加 `frontend_ui` | `D-010=DECIDED_BY_STATE_CAS,D-011=REVOKE_REASON,D-012=GIST_HALF_OPEN_RANGE,D-013=ENV_INDEPENDENT_SOD,D-014=LONG_TERM_ADMIN_ONLY` | `0,0,1,0` |
| `source_contract/CR-005` | `CR-005-R1`；`contract_only`；`## 8. 当前状态` | DEP 同八角色 | `DOC-D-001,DOC-D-002,DOC-D-003,DOC-HANDLER-DOCUMENT-CORRECTION,DOC-HANDLER-ASSET-SECURITY-REVALIDATION,DOC-CR010-SCANNER-EVIDENCE-PROJECTION,DOC-PARSE-006,DOC-MIGRATION-DOWNGRADE` | `1,0,1,1` |
| `source_contract/CR-007` | `CR-007-R1`；`contract_only`；`## 8. 当前状态` | DEP 同八角色 | `FILEKB-D-001,FILEKB-D-002,FILEKB-D-003,FILEKB-D-004,FILEKB-D-005,FILEKB-D-006,FILEKB-D-007,FILEKB-D-008` | `0,0,1,0` |
| `source_contract/CR-009` | `CR-009-R1`；`contract_only`；`## 10. 当前状态` | DEP 同八角色 | `CHUNK-FIELDS-JCS,CHUNK-STATE-MACHINE,CHUNK-008-009-API,CHUNK-IDEMPOTENCY-CAS,CHUNK-CURSOR,CHUNK-REVISION-OWNERSHIP,CHUNK-DOWNGRADE` | `2,0,1,1` |

- `source_baseline_manifest_sha256` 对本 revision 五个 source 都固定为 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`。snapshot、baseline、Schema/evidence hash 都为 `Sha256`；`approval_record_schema_sha256` 是本 shared Schema 无 BOM UTF-8/LF raw bytes hash。snapshot marker/hash 必须逐字匹配对应 source preimage；CR-005/009 的机器 decision code 与其表内自然语言责任逐项映射，不得漏项或扩大 scope。
- `request_sync_authorization_schema_ref/sync_evidence_schema_ref` 为 `ApprovedSchemaRef|null`。DEP meta 两者 null；DEP approved-artifact 分别固定 `request-sync-authorization-v1/dep005-post-sync-baseline-attestation-v1` 且 non-null；四个 source-contract record 分别固定 `request-sync-authorization-v1/request-sync-transition-evidence-v1` 且 non-null。
- `artifact_bindings` 是分支封闭 object。DEP 分支精确五键 `approval_signer_registry_ref/artifact_schema_set/profile_instance_set/environment_policy_instance_set/test_vector_bundle_sha256`：registry ref 始终 non-null；meta 其余四项全 null，approved-artifact 全 non-null。source-contract 分支精确三键 `approval_signer_registry_ref/decision_preimage_ref/decision_preimage_sha256`：三者全 non-null，preimage ref 为 `ArtifactRef` 且两个 hash 都等于外层 snapshot。所有同 source/scope record 必须逐字绑定同一 `ApprovalSignerRegistryRef` 和外部 expected trust-anchor pin。
- DEP `artifact_schema_set` 是精确九键 object：`database_backup_profile/backup_encryption_profile/database_backup_manifest/minio_backup_inventory/qdrant_rebuild_profile/environment_recovery_policy/restore_run_input/pretraffic_restore_verification/traffic_release_attestation`，每个值都是对应 A..I `schema_version` 的 `ApprovedSchemaRef`；不得用数组、缩写或一个 bundle hash替代。
- DEP `profile_instance_set` 是精确三键 object `database_backup_profile/backup_encryption_profile/qdrant_rebuild_profile`，每值为对应 A/B/E 的 `ApprovedInstanceRef`。`environment_policy_instance_set` 是非空 array；每项精确四键 `policy_scope:source_backup|target_recovery`、`environment_id:Uuid`、`environment_class:EnvironmentClass`、`policy_ref:ApprovedInstanceRef`，解析实例的 scope/ID/class 必须逐项相等；按 `(policy_scope source_backup先于target_recovery,environment_id,policy_ref.instance_sha256)` 排序且无重复，至少各含一个 source/target，且用于同一恢复路径的 source/target environment ID 不相等。
- DEP approved-artifact record 的根 `environment_scope` 是对上述 Policy set 投影后按 `environment_id` Unicode code point 排序去重的非空 array，每项精确两键 `environment_id:Uuid/environment_class:EnvironmentClass`；同一 ID 映射多个 class 时整个 set非法。meta 的 root environment scope为 null；source-contract 分支固定 string `contract`。`test_vector_bundle_sha256` 为实际 fixed positive/negative/cross-implementation vector bundle raw bytes 的 `Sha256`，不允许实例缺失时预填。
- `deltas` 精确四键 `api_path_delta/core_table_delta/alembic_migration_delta/operation_log_action_delta`，逐字等于矩阵。DEP meta 的 environment scope=null，DEP artifact 为 Policy 环境数组；source-contract 固定 string `contract`。所有分支的 network/production scope 固定 `none`，`decided_at` 为 `UtcTimestamp`。
- `evidence_ref` 指向通过第 8.3 节 exact raw Schema 的 detached evidence JCS artifact且 `evidence_sha256=evidence_ref.sha256`；signature bytes只由 evidence 内 `signature_ref` 指向。`safe_notes_code` 是封闭 enum `NONE/SCOPE_REJECTED/SNAPSHOT_MISMATCH/BASELINE_MISMATCH/SCHEMA_SET_REJECTED/INSTANCE_SET_REJECTED/EVIDENCE_INSUFFICIENT`；APPROVED 只能 `NONE`，REJECTED 必须非 `NONE`。禁止自由 notes、secret、原始异常、泛型 evidence URI 或一条 record 合并多个角色。

每个 source 的共同批准要求其必需 roles 各一份 APPROVED record，并对 record kind/source/revision/scope/marker/snapshot/baseline/shared Schema、registry/pin、selected set、deltas和分支 artifact bindings 逐字一致。排序后的 record `ArtifactRef[]` 及 `SHA256(JCS(refs))` 才构成 role-complete approved record set；raw preimage 或 snapshot hash 单独不能证明批准。DEP meta 的两个 post-meta ref 按矩阵为 null，DEP approved-artifact 才绑定全部五个支持 Schema。C/D/G/H/I per-run instance hash永不进入静态审批集合。

### 8.3 `dep005-detached-approval-evidence-v1` 支持 Schema

本 Schema 与 CR-006/008 逐字共用 version、根字段和签名算法。根对象精确十五键：

`evidence_schema_version`、`canonicalization_version`、`hash_algorithm`、`evidence_scope`、`approval_id`、`approver_role`、`approval_payload_sha256`、`signature_algorithm`、`signature_encoding`、`signer_registry_version`、`signer_registry_sha256`、`key_id`、`signature_ref`、`signature_sha256`、`signed_at`。

- 三个常量依次为 `dep005-detached-approval-evidence-v1`、`RFC8785-JCS`、`SHA-256`；`evidence_scope` 是下表七值封闭 enum。approval ID 为 `UuidV4`，payload/registry/signature hash 为 `Sha256`，registry version/key ID 为 `Version/OpaqueName`，signed time 为 `UtcTimestamp`。
- 每个 payload object 及其嵌套 object 都是 `additionalProperties=false` 的精确对象；`approval_payload_sha256=SHA256(JCS(payload))`。目标 item 的 `evidence_ref/evidence_sha256` 永不进入自己的 payload；CR-004/010 set digest 只在全部 item evidence 完成后计算；joint aggregate 最后生成，故没有 hash/signature 自环。

| evidence scope | approval ID / role / signed time | 唯一 payload |
| --- | --- | --- |
| `source_contract_approver_decision` | `approval_id=target.approval_record_id`；role=`target.approver_role`；`signed_at=target.decided_at` | 目标 30 键 shared approval record 删除根 `evidence_ref/evidence_sha256` 后的精确 28 键 object；`record_kind` 唯一判定 DEP 或其他 source 分支 |
| `joint_approver_decision` | `approval_id=joint.approval_id`；role=目标 item role；`signed_at=item.decided_at` | 精确十三键 `approval_id/approver_id/approver_role/decision/decided_at/decision_scope/cr_bindings/baseline_binding/artifact_bindings/dependency_bindings/deltas_and_counts/scope/safe_notes_code`；`approval_id` 只取 joint root，`approver_id/approver_role/decision/decided_at/safe_notes_code` 五项只取目标 item，其余七项只取 joint root，禁止同名字段回退或覆盖 |
| `joint_aggregate` | `approval_id=joint.approval_id`；role=null；`signed_at=joint.decided_at` | joint 十七键 root 删除根 `evidence_ref/evidence_sha256` 后的精确十五键 object |
| `cr004_artifact_approver_decision` | `approval_id=item.approval_id`；role=item role；`signed_at=item.decided_at` | 精确二键 wrapper：`approval` 是 item 删除 evidence 后的 `approval_id/approver_id/approver_role/decision/decided_at` 五键；`target` 是 CR-004 fact-set root 删除 approvals/set digest 后的十五键 object |
| `cr010_contract_approver_decision` | `approval_id=item.approval_id`；role=item role；`signed_at=item.decided_at` | 精确二键 wrapper：`approval` 同上五键；`target` 是 CR-010 fact-set root 删除 approvals/set digest 后的十四键 object |
| `provider_environment_approver_decision` | `approval_id=provider root.approval_id`；role=item role；`signed_at=item.decided_at` | 精确二键 wrapper：`approval` 是目标 provider item 删除 evidence 后的 `approver_id/approver_role/decision/decided_at` 四键；`target` 是二十五键 provider root 删除 `approvals` 后的二十四键 object |
| `request_sync_authorization_decision` | `approval_id=authorization.authorization_id`；role=`authorization.approver_role`；`signed_at=authorization.approved_at` | request-sync authorization root 删除根 `evidence_ref/evidence_sha256` 后的精确 object；其 source union 由第 8.5 节冻结 |

CR-004/010 的 approval item 因此必须增加 `approval_id:UuidV4` 并成为七键 item；两个 fact-set target 的十五/十四键列表以 CR-006/008 共同 Schema 为唯一事实来源，字段增删必须同步提升相关 Schema revision。provider、joint、request-sync 与任一 source-contract target 的 registry binding 必须解析为同一第 8.4 节 Schema/instance/pin；scope、target kind、approval ID、role 或 payload shape 不允许隐式多态。
- 签名 message 固定为 UTF-8 bytes `FINAUDIT_APPROVAL_V1` + 单个 `0x00` + 从 64 hex `approval_payload_sha256` 解码的 32 raw bytes，禁止签 hex ASCII。`ed25519` 只配 `signature_encoding=raw_64_bytes`；`ecdsa_p256_sha256` 只配 IEEE-P1363 `p1363_64_bytes`，验证器要求 strict uncompressed P-256 public key、r/s 范围合法且 low-S，禁止 DER/高-S/非规范 key。
- `signature_ref` 为 `ArtifactRef`，其 sha256/size 精确绑定 no-replace raw detached signature bytes而非 evidence JCS，`size_bytes=64` 且 `signature_sha256=signature_ref.sha256`。signer registry version/hash/key ID 必须解析到 signed_at 有效、未撤销且获准签署对应 role/scope 的 key；任何 Schema、payload、domain separator、encoding、registry、key 或 signature 漂移都拒绝。

### 8.4 `approval-signer-registry-v1` 支持 Schema

该 pre-meta Schema 的 registry 根对象精确三键：`schema_version='approval-signer-registry-v1'`、`registry_version`、`keys`。`keys[]` 非空，每项精确十键：`key_id`、`approver_id`、`algorithm`、`public_key_encoding`、`public_key`、`allowed_roles`、`allowed_scopes`、`valid_from`、`valid_until`、`revoked_at`。

- key 按 `key_id` Unicode code point 升序且唯一；`approver_id` 为 person 或 service principal 的 `Uuid`。algorithm/encoding 只允许 `ed25519/raw_32_bytes_base64url` 或 `ecdsa_p256_sha256/sec1_uncompressed_65_bytes_base64url`；base64url 无 padding并解码为精确长度，P-256 point 必须在曲线上。
- `allowed_scopes` 非空、去重并按第 8.3 节七值声明顺序排序。只签 `joint_aggregate` 的 service key 必须满足 `allowed_scopes=['joint_aggregate']` 且 `allowed_roles=[]`；其他 key 禁止包含 `joint_aggregate`，`allowed_roles` 必须非空、去重并按 `requirements_product/architecture/data_dba/backend_api/frontend_ui/ai_rag/ops/security/test` 顺序排序。individual evidence 必须同时满足 `key.approver_id=payload approver_id`、role 在 allowed_roles、scope 在 allowed_scopes；aggregate evidence 的 role 必须为 null，只按专用 service key 和 scope 校验。
- 时间矩阵固定为 `valid_from <= signed_at`、`valid_until=null || signed_at < valid_until`、`revoked_at=null || signed_at < revoked_at`；`valid_until` non-null 时还必须晚于 valid_from。registry 禁止 private key、certificate chain、secret 或任意扩展字段。
- registry raw bytes 通过本 Schema、no-replace 保存，并由第 8.2 节 `ApprovalSignerRegistryRef.registry_ref/hash` 定位。验证器必须另从 package 外的 authenticated approval-system configuration 获得并逐字匹配整个七键 expected `ApprovalSignerRegistryRef`；禁止接受待验 package 自报的 pin、用 registry 内 key 自签 registry、或让任一 approval record反向建立 trust。实际 registry/pin 尚未生成时，第 1—8 节仍可做静态 snapshot，但任何 meta/artifact approval record 都无效。

### 8.5 `request-sync-authorization-v1` 支持 Schema

该 post-meta Schema 与 CR-006/008 共用；只定义“单一已批准 source 在指定 baseline 上同步九份 Request”的可签署授权记录，不执行同步，也不允许一次授权合并多个 source。根对象精确二十三键：

`authorization_schema_version`、`canonicalization_version`、`hash_algorithm`、`authorization_id`、`authorization_type`、`source_id`、`source_revision`、`decision_snapshot_marker`、`decision_snapshot_sha256`、`source_approval_binding`、`pre_sync_baseline_manifest_sha256`、`request_sync_scope`、`request_paths`、`network_scope`、`production_release_scope`、`approved_at`、`expires_at`、`approver_id`、`approver_role`、`detached_approval_evidence_schema_sha256`、`approval_signer_registry_ref`、`evidence_ref`、`evidence_sha256`。

- 三个常量依次为 `request-sync-authorization-v1`、`RFC8785-JCS`、`SHA-256`；authorization type/scope 固定 `request_sync/source_only`。ID 为 `UuidV4`，hash 为 `Sha256`，时间为 `UtcTimestamp` 且 `approved_at < expires_at`；network/production scope 固定 `none`。approver ID 为 `Uuid`，role 固定 `requirements_product`；该授权不能代替 source 合同的多角色批准。
- `source_id` 只允许 `DEP-005/CR-003/CR-004/CR-005/CR-007/CR-009/CR-010`；revision、marker、snapshot 与第 7.2 节 ordered lineage 中同 source 的获批事实逐字相等。`request_paths` 按 Unicode code point 升序且恰好等于第 8.6 节九项 enum；授权不能在其他 source/revision/snapshot/baseline/record-set/path 重放。
- `source_approval_binding` 是精确十键 object：`binding_kind`、`schema_version`、`schema_sha256`、`decision_preimage_ref`、`decision_preimage_sha256`、`required_approver_roles`、`decision_selections`、`approval_artifacts`、`approval_binding_sha256`、`approval_signer_registry_ref`。preimage/ref、approval artifact ref 都是 `ArtifactRef`；preimage 两个 hash 等于外层 snapshot；approval artifacts 按 `(sha256,bucket,object_key,version_id)` 升序且无重复；binding hash 固定 `SHA256(JCS(approval_artifacts))`；registry ref 与授权外层及所有 approval evidence 逐字相等。roles 按第 8.2/8.4 节九角色 enum 顺序过滤，selections 按第 8.2 节对应 source 的声明顺序，均非空、无重复且必须精确覆盖表中全集。

| source | revision / exact snapshot marker | binding kind / Schema / approval artifacts | roles / selections |
| --- | --- | --- | --- |
| `DEP-005` | `DEP-005-R1` / 第 8.7 节拼接 marker | `source_contract_record_set/source-contract-approval-record-v1`；恰好八个 APPROVED/approved_artifact record refs | 第 8.2 节 DEP 八角色与九个逐字枚举的 `DEP5-D-*` 选择 |
| `CR-003` | `CR-003-R1` / `## 6. 当前状态` | `source_contract_record_set/source-contract-approval-record-v1`；恰好九个 APPROVED/contract_only record refs | 第 8.2 节九角色与五个 `D-010=...` 精确选择 |
| `CR-005` | `CR-005-R1` / `## 8. 当前状态` | 同上；恰好八个 APPROVED/contract_only refs | DEP 八角色与第 8.2 节八个 DOC 选择 |
| `CR-007` | `CR-007-R1` / `## 8. 当前状态` | 同上；恰好八个 APPROVED/contract_only refs | DEP 八角色与第 8.2 节八个逐字枚举的 `FILEKB-D-*` 选择 |
| `CR-009` | `CR-009-R1` / `## 10. 当前状态` | 同上；恰好八个 APPROVED/contract_only refs | DEP 八角色与第 8.2 节七个 CHUNK 选择 |
| `CR-004` | `CR-004-R1` / `## 6. 当前状态` | `cr004_handler_registry_fact_set/cr004-handler-registry-approved-fact-set-v1`；恰好一个 fact-set ref | DEP 八角色与 `REL-D-001,REL-D-002,REL-D-003,REL-D-004,REL-D-005`；fact set 内八个已签 item 全 APPROVED |
| `CR-010` | `CR-010-R1` / `## 8. 当前状态` | `cr010_scanner_registry_fact_set/cr010-scanner-registry-contract-fact-set-v1`；恰好一个 fact-set ref | DEP 八角色与 `SCANREG-D-001,SCANREG-D-002,SCANREG-D-003,SCANREG-D-004,SCANREG-D-005,SCANREG-D-006,SCANREG-D-007,SCANREG-D-008`；fact set 内八个已签 item 全 APPROVED |

- 每个 binding 的 `schema_sha256` 必须是对应 exact raw Schema hash。外层 `source_revision/decision_snapshot_marker` 必须逐字等于表中身份；`decision_preimage_ref/hash` 必须按该 marker 所属 CR 的静态算法重算并等于外层 snapshot。source-contract record set 的每项解析为不同必需 role、相同 source/revision/marker/snapshot/baseline/selection/delta/registry 的第 8.2 节 APPROVED record；CR-004/010 fact set 虽不重复 marker，也必须携带相同 revision/snapshot并通过 CR-006/008 共同 Schema验证其 role-complete detached signature set。仅有 preimage、snapshot、scope string、泛型 evidence URI 或未签名 fact set 一律不是批准。
- `pre_sync_baseline_manifest_sha256` 是本次同步前实际 baseline raw hash，不要求等于 source contract 的历史 baseline，但必须等于 ordered lineage 前一跳 post hash；首项 DEP 等于第 1.2 节 source baseline。`approval_signer_registry_ref`、detached Schema hash 与 source binding逐字一致，且外部 trust-anchor pin仍有效。
- `evidence_ref` 指向第 8.3 节 `request_sync_authorization_decision` evidence JCS且 hash相等；`approval_id=authorization_id`、role=`requirements_product`、`signed_at=approved_at`，payload 是本 23 键授权 root 删除 `evidence_ref/evidence_sha256` 后的精确二十一键 object。该前向 projection 不含自身 evidence，故没有签名/hash环。
- authorization Schema raw hash只从 role-complete DEP approved-artifact record set 的共同 `request_sync_authorization_schema_ref` 取得，并作为所有 authorization validator 的 package 外 expected raw hash；各 `source_approval_binding.schema_version/schema_sha256` 只绑定自己的 approval-record 或 fact-set Schema，不声称包含 authorization Schema ref。record 不含 secret、Token、自由 notes、production/network扩展或默认 path。任何 source 尚无完整 signed approval set 时，只阻断该 source 的 authorization/sync，不把其 snapshot冒充批准。

### 8.6 `dep005-post-sync-baseline-attestation-v1` 支持 Schema

该 Schema 只在第 7.2 节单独授权的 Request 同步完成后生成实例；meta/approved-artifact 审批不生成实例，也不授予同步权限。根对象精确二十一键：

`attestation_schema_version`、`canonicalization_version`、`hash_algorithm`、`attestation_id`、`dep_revision`、`decision_snapshot_sha256`、`approved_artifact_approval_records`、`approved_artifact_approval_record_set_sha256`、`pre_sync_baseline_manifest_sha256`、`post_sync_baseline_manifest_sha256`、`request_sync_authorization_schema_version`、`request_sync_authorization_schema_sha256`、`request_sync_authorization_ref`、`request_sync_authorization_sha256`、`request_file_count`、`request_files`、`deltas`、`sync_result`、`synced_at`、`generator_version`、`generator_source_sha256`。

- 三个常量依次为 `dep005-post-sync-baseline-attestation-v1`、`RFC8785-JCS`、`SHA-256`；attestation ID 为 `UuidV4`，DEP revision 固定 `DEP-005-R1`，所有 digest/hash 为 `Sha256`。
- `approved_artifact_approval_records` 是恰好八项的 `ArtifactRef[]`，按 `(sha256,bucket,object_key,version_id)` 升序且无重复；每项解析为第 8.2 节 `record_kind=dep005_contract/source_id=DEP-005`、不同必需 role 的 APPROVED/approved_artifact record，并对相同 revision/snapshot/baseline/schema/registry/Profile/Policy/vector bundle 一致。set hash 固定为 `SHA256(JCS(approved_artifact_approval_records))`，并必须等于 authorization 的 `source_approval_binding.approval_binding_sha256`。
- pre-sync baseline hash 必须等于八个 record 的共同 `source_baseline_manifest_sha256`；post-sync hash 是同步后 `docs/baseline-manifest.md` 无 BOM UTF-8/LF raw bytes SHA-256。解析 manifest 的九个 Request 行时，先验证其 hash token 为恰好 64 位 ASCII hex，再转 lowercase 与 JSON `post_sync_raw_sha256:Sha256` 逐项比较；这兼容 manifest 当前 uppercase 展示但不允许值漂移。
- authorization Schema version 固定 `request-sync-authorization-v1`，raw hash 必须等于八个 approved-artifact record 的共同 ref。`request_sync_authorization_ref` 为指向通过该 exact raw Schema 的外部 no-replace record 的 `ArtifactRef`，`request_sync_authorization_sha256=request_sync_authorization_ref.sha256`；授权必须满足第 8.5 节 `source_id=DEP-005` 分支的全部签名、baseline、record-set、九路径和期限矩阵，且 `approved_at <= synced_at < expires_at`。缺失或漂移都禁止同步及 attestation 发布。
- `request_file_count` 固定 JSON integer 9。`request_files[]` 每项精确两键 `path/post_sync_raw_sha256`；path 是下列封闭 enum，使用 `/`、不得大小写折叠，数组按 path 的 Unicode code point 升序且恰好覆盖九项：
  - `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
  - `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
  - `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
  - `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
  - `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
  - `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
  - `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
  - `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
  - `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
- `deltas` 使用第 8.2 节同一精确四键零矩阵。`sync_result` 只允许 `applied_and_verified/no_change_required_and_verified`；前者要求 pre/post baseline hash 不相等，后者要求相等。失败或部分同步不得发布该 attestation，只能保留脱敏 failure evidence并保持 CR-006/008 联合审批阻断。
- `synced_at` 为 `UtcTimestamp`；`generator_version` 为 `Version`，`generator_source_sha256` 为实际生成/验证器 source bytes 的 `Sha256`。生成器必须拒绝额外/缺失路径、非稳定排序、baseline entry 漂移、非零 delta、授权 Schema/签名/期限漂移和 approval record set 不一致。本实例只证明 DEP-only 中间 baseline，不包含、替代或声称等于第 7.2 节 final aggregate baseline。

### 8.7 decision snapshot preimage 与 SHA-256

算法固定如下：

1. 读取本文件原始 bytes；拒绝非法 UTF-8 或 BOM。
2. 将 CRLF 和孤立 CR 统一为 LF；不做其他 Unicode normalization。
3. 按 LF 分行，以 ordinal byte-equivalent 方式匹配完整且无前后空格的唯一 marker；marker bytes 由 ASCII `## 9.`、单个 ASCII space 与 UTF-8 `当前状态` 依次拼接，出现零次或多次都失败。该写法避免在规范正文内复制完整 marker literal。
4. 取 marker 行之前的全部内容；移除末尾已有的所有 LF，再追加且只追加一个 LF。
5. 以无 BOM UTF-8 编码；不裁剪行尾空格，不改写 Markdown。
6. 对所得 bytes 计算 SHA-256，输出 64 位小写十六进制；生成前不得预填或猜测，生成后可写入第 9 节 `GENERATED_FOR_REVIEW / NOT APPROVED` 状态行，并由后续外部 no-replace 审批记录逐字复用。
7. 首次 snapshot 只能在第 1—8 节静态检查通过后生成。
8. snapshot 后第 1—8 节任何 byte 变化都必须提升 DEP 修订号、重新生成 hash 并清空旧修订签名；第 9 节状态变化不改变 preimage。

本静态规范不随审批进展改变措辞。`meta_contract_only` 只批准结构；`approved_artifact` 只在外部记录绑定已生成 bundle；两者都不改写本 preimage。

### 8.8 禁止边界

- 本合同审批不等于 Request 同步授权。
- 本合同审批不等于 `fixed_test_provider`、内部 vLLM、embedding provider、Qdrant 或其他网络授权。
- 本合同审批不等于真实 key、真实备份、生产数据访问、生产恢复、迁移、流量切换或 production release。
- approved artifact、离线测试或合同 hash 不得代替真实隔离恢复、网络边界验证和 RPO/RTO 实测。

## 9. 当前状态

| 项目 | 当前状态 | 说明 |
| --- | --- | --- |
| DEP5-D-001—009 | `STATIC REVIEW PASSED / NOT APPROVED` | 合同与首次 review snapshot 已完成独立静态复核；尚无 meta 审批记录，不构成批准 |
| source baseline binding | `RECORDED` | hash 为 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`；审批前仍须验证未漂移 |
| API/core table/migration/action delta | `0 / 0 / 0 / 0` | 不固定最终总数 |
| 九个制品 Schema | `PENDING / NOT GENERATED / NOT APPROVED` | meta 合同不生成或伪造 hash |
| 三个 pre-meta 支持 Schema | `GENERATED_FOR_REVIEW / NOT APPROVED` | `source-contract-approval-record-v1.schema.json`: `bytes=73641`, `sha256=022ce67fb2e9ed75c3acf3b00c4c6afe904678fc1ecf8facdc75032b2141e067`；`dep005-detached-approval-evidence-v1.schema.json`: `bytes=9633`, `sha256=cdd04ea8bed4a411f0bd0d5aeda56ad8adb9428e3a6f72f9297bf48be9956bac`；`approval-signer-registry-v1.schema.json`: `bytes=5981`, `sha256=d6346eba93031ede42887fc6e031dd7a60b5b0ce5f8b8dd55a21f3725715063f`；均仅为已复核候选，不是审批事实 |
| 两个 post-meta 支持 Schema | `PENDING / NOT GENERATED / NOT APPROVED` | `request-sync-authorization-v1` 与 `dep005-post-sync-baseline-attestation-v1` 只能在 meta 批准后按生命周期生成 |
| signer registry instance / external trust-anchor pin | `PENDING / NOT GENERATED / EXTERNAL TRUST MATERIAL REQUIRED` | 未生成公钥、registry instance 或 pin；待验 package 不得自建信任，缺失时任何 meta/artifact approval record 都无效 |
| provider runtime support Schema / environment approval | `DEFINED / NOT GENERATED / NOT AUTHORIZED` | 独立 `cr002-provider-environment-approval-v1` Schema、record、模型 allowlist 与 package 外 expected ref 仅在另行授权流程中生成；当前不并入五支持 Schema且不授权调用 |
| A/B/E Profile 与 F Policy instance set | `PENDING / NOT GENERATED / NOT APPROVED` | 仅允许非秘密实例；F 不假设 singleton |
| C/D/G/H/I 运行实例 | `NOT GENERATED / NOT AUTHORIZED` | 需要独立运行权限和真实环境证据 |
| decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` | `preimage_bytes=121827`；`decision_snapshot_sha256=d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110`；仅供静态合同评审，不批准 meta、artifact、同步或运行 |
| CR-006 interface | `DEFINED / NOT CONSUMED` | 需消费 C/G plan并发布 transition evidence，H 再验证 |
| CR-008 interface | `DEFINED / NO_NEW_ACTION` | `action_delta=0`，需在最终 registry evidence 显式消费 |
| Request 同步 | `NOT AUTHORIZED / NOT PERFORMED` | 依第 7.2 节另行授权 |
| provider/source Qdrant/target Qdrant 网络 | `NOT AUTHORIZED / NOT PERFORMED` | 三类运行 scope 均未放行 |
| production | `NOT AUTHORIZED / NOT PERFORMED` | 不构成生产放行 |

以下事项明确保留给 `approved_artifact`、CR-006/008 联合审批或运行验收；不得在 meta snapshot 中生成、预填或伪造，最终 meta 可审批性仍以独立静态复核结论为准：

1. 继续生成并独立验证九个制品 Schema、两个 post-meta 支持 Schema、signer registry instance及外部 trust-anchor pin；三个 pre-meta Schema 候选仍须由真实 meta record 共同绑定并批准；
2. 选择并审批 A/B/E Profile、F source/target Policy instance set、工具兼容矩阵、环境数值和真实 hash；
3. 生成正反、跨实现和无环测试向量 bundle；
4. 由 CR-006 消费 C/G transition plan并发布 evidence，由 CR-008 显式消费零 action delta；
5. 获得 Request 同步授权并完成第 7.2 节 post-sync baseline attestation；
6. 真实备份、隔离恢复、RPO/RTO 实测和网络验证分别取得权限并留证；
7. production change、production network 和 production release 继续使用独立审批。
