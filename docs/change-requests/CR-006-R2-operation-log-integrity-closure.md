# CR-006-R2：CR-013 lineage 与 shared v2 successor addendum

> 文档类型：`CR-006-R1` 的最小 successor addendum
> 修订：`CR-006-R2`
> 静态性质：versioned successor contract；生命周期状态只记录在第 9 节
> 非目标：不复制或改写 R1 正文，不生成 snapshot、Schema、artifact、签名、migration 或批准事实

## 1. 基座与 effective contract

本 addendum 只在下列不可变 R1 基座上生效：

| 字段 | 固定值 |
|---|---|
| `base_revision` | `CR-006-R1` |
| `base_preimage_bytes` | `204739` |
| `base_decision_snapshot_sha256` | `180b8de06ecc445d97cb734ebd884d6736cd3443fdbc364c6e4a549f2663a4be` |
| `successor_revision` | `CR-006-R2` |

`CR-006-R2 effective contract` 的唯一含义是“上述精确 R1 snapshot 加本文件第 1—8 节的 R2 addendum snapshot”。它不是 R1 全文副本，也不把两份 bytes 拼接成第三个隐式 hash。验证器必须先按 R1 算法复算并匹配基座的 byte length 与 hash，再验证本 addendum；任一不等均 fail closed。

R1 的 `OPLOG-D-001..006`、数据面、锁、事务、Schema、migration 对象、验收和非授权边界全部原样继承。只有本文件明确列出的 revision、lineage、shared support version、joint/E/effective-set 绑定和生成顺序由 R2 覆盖；其他差异不是“兼容解释”，必须提升 revision。

R2 原子批准必须由 joint v2 的精确六键 `cr_bindings` 直接绑定同一 CR-014 与 DEP-005-R2 snapshot。该object保留原四键 `cr006_revision/cr006_decision_snapshot_sha256/cr008_revision/cr008_decision_snapshot_sha256`，并新增：精确复用 DEP R2 的五键 `successor_review_binding`，以及精确四键 `dep005_r2_decision_binding=revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256`。验证器必须解析 CR-014 snapshot并逐字复核其四份R1 identity、固定source baseline和八项decision；再复核DEP R2 snapshot。实际ref/hash只在这些snapshot生成后作为package-external input进入joint，禁止在本静态preimage中预填、置null、全零或使用placeholder。

## 2. R2 决策与批准全集

R2 不新增第二套业务决策 code。它冻结的 `cr006 decision universe` 仍恰为 `OPLOG-D-001`、`OPLOG-D-002`、`OPLOG-D-003`、`OPLOG-D-004`、`OPLOG-D-005`、`OPLOG-D-006`，含义逐字解析自第 1 节绑定的 R1 snapshot；本 addendum只改变这些决策的 successor identity、lineage与机器绑定。

R2 joint `decision_scope.cr006_selected/cr006_rejected` 仍使用上述六项封闭全集和编号顺序。APPROVED 时 selected恰为六项且 rejected为空；REJECTED时两数组无重复、互斥并精确分区六项全集，且 rejected非空。joint同时绑定 `CR-006-R2` addendum snapshot，因此“六项全选 + R2 snapshot”才表示批准 R2 effective contract；单独批准 R1、单独签 addendum、引入 `OPLOG-R2-*` alias或省略 R2 snapshot均不合格。

该批准不自动批准 CR-013、DEP-005、CR-008、Request sync、migration release、runtime、网络或 production。

## 3. Cumulative delta 与 addendum delta

四元组顺序固定为 `api_path_delta/core_parent_table_delta/owned_alembic_revision_count/operation_log_action_delta`：

| 身份 | cumulative delta | 本次 addendum delta |
|---|---:|---:|
| `CR-006-R2` | `0/1/1/0` | `0/0/0/0` |

R2 cumulative delta 逐字继承 R1：CR-006 仍只增加 `operation_log_chain_state` 一个 core parent table并拥有一个 Alembic revision；本 addendum 不增加第二张表、第二个 revision、API path 或 action。

CR-013-R1 的上游 delta 固定为 `0/0/1/0`。它在 CR-013 获批并完成 source-only Request sync 后进入 aggregate baseline；不得写入 CR-006 的 cumulative/addendum delta，不得成为 E 的第三条 `delta_records`，也不得再次加到 joint `deltas_and_counts`。CR-013 的 `operation_log_action_delta=0`，认证动作继续复用 CR-008 注册值。

## 4. CR-013 dependency 与八项 lineage

aggregate sync lineage 固定为八项，顺序不可按字典序重排：

1. `DEP-005`
2. `CR-003`
3. `CR-013`
4. `CR-004`
5. `CR-005`
6. `CR-007`
7. `CR-009`
8. `CR-010`

首项继续解析 DEP-only post-sync attestation；后七项分别解析 `request-sync-transition-evidence-v2`。每项 pre baseline 必须等于前项 post baseline，末项 post 才是 aggregate `post_all_upstream_sync_baseline_manifest_sha256`。DEP-only 中间 baseline 不得等同或冒充 aggregate baseline。

joint `dependency_bindings` 从六项变为七项，元素仍为 R1 精确十一键，固定顺序为 `CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`。新增 CR-013 元素固定：

- `source_id='CR-013'`、`revision='CR-013-R1'`；
- `decision_snapshot_sha256` 等于经 CR-013 静态算法复算的 snapshot；
- `sync_evidence_ref/hash` 解析为本八项 chain 使用的 CR-013 transition；
- `approved_fact_set_kind='decision_preimage'`、`approved_fact_set_version='CR-013-R1'`；
- `approved_fact_set_schema_version=null`、`approved_fact_set_schema_sha256=null`；
- `approved_fact_set_ref/hash` 指向 no-replace CR-013 decision preimage且 hash 等于其 snapshot。

preimage 只标识已签内容；CR-013 是否批准必须继续通过 transition → source-only authorization → 九角色 `source-contract-approval-record-v2` APPROVED set及同一 signer registry/pin证明。四条 `auth_keyring_artifact` 批准记录不是 Request sync source binding，也不进入 joint dependency 或 51 项 artifact array。

## 5. Shared v2 与 v1 复用矩阵

禁止原地修改任何 v1 raw Schema。下列身份必须发布新文件名和新 raw hash：

| 必须 v2 | 触发原因 |
|---|---|
| `source-contract-approval-record-v2.schema.json` | 新增 CR-013 contract/artifact branch |
| `request-sync-authorization-v2.schema.json` | source union 由 7 增至 8 |
| `request-sync-transition-evidence-v2.schema.json` | non-DEP source union 由 6 增至 7 |
| `dep005-post-sync-baseline-attestation-v2.schema.json` | 绑定 DEP R2、source record v2 与 authorization v2 |
| `cr006-cr008-joint-approval-record-v2.schema.json` | 绑定 R2 snapshots、七项 dependency和两组六项决策全集 |
| `operation-log-baseline-delta-attestation-v2.schema.json` | E 绑定八项 chain及 R2 delta identities |
| `effective-api-set-v2.schema.json` | 绑定新 aggregate baseline和 R2 delta identities |
| `cr006-migration-object-manifest-v2.schema.json` | R1 Schema/instance内嵌 CR-006-R1 与旧 predecessor identity |
| `cr006-migration-implementation-attestation-v2.schema.json` | R1 Schema内嵌 CR-006-R1 或旧 joint identity |

`source-contract-approval-record-v2` 根仍精确 30 键；`source_id` enum 由 5 增至 6，`approval_scope` enum 由 3 增至 4。顶层branch selector必须是精确10个 `oneOf` leaves：DEP R1 meta/artifact、四个legacy source-contract、DEP R2 meta/artifact、CR-013 contract/artifact；`artifact_bindings.oneOf` 必须精确7类：DEP R1 meta/artifact、DEP R2 meta/artifact、legacy source、CR-013 contract/artifact。禁止把revision或scope宽松合并而误写为 `5→6` 或 `3→5`。CR-013 contract branch 使用九角色和八项 AUTHSEC 决策；artifact branch使用 `backend_api/ops/security/test` 四角色和 `AUTHKEY-A-001`。两分支都绑定 CR-013 source delta `0/0/1/0`，但只 contract branch进入 Request sync。

以下 raw Schema 结构未变，继续复用 v1 文件名/hash，不得仅因 R2 重命名：`dep005-detached-approval-evidence-v1.schema.json`（root 15、scope 7）、`approval-signer-registry-v1.schema.json`（root 3、key 10）、`cr004-handler-registry-approved-fact-set-v1.schema.json`（root 17）、`cr010-scanner-registry-contract-fact-set-v1.schema.json`（root 16）、`operation-log-fact-schema-bundle-v1.schema.json`，以及 R1 中未改变结构语义的 CR-006/A—D 数据 Schema。registry instance/pin 只有在 key、scope、有效期或外部 expected pin 不变且 no-replace bytes逐字相等时才可复用；否则使用同一 v1 Schema生成新 instance/version，不修改旧 bytes。

## 6. Joint、E、effective-set 与实现制品

### 6.1 Joint v2

`cr006-cr008-joint-approval-record-v2` 的 root 仍精确 17 键；`decision_scope` 仍 4 键；`approvals` 仍恰好 8 项且每项 8 键；`cr_bindings` 从4键提升为第1节精确6键；`baseline_binding` 仍 12 键；`artifact_bindings` 仍恰好 51 项且每项 5 键；`dependency_bindings` 元素仍 11 键但数量 `6→7`；`deltas_and_counts` 仍 17 键；`scope` 仍 5 键。现有 artifact role 只把对应 source/auth/transition/post-sync/joint/E/effective-set version换为 v2，不新增 CR-013 role，故 51 不变。

六键 `cr_bindings.successor_review_binding` 必须与 DEP R2 八条 meta和八条approved-artifact record逐JCS相等；`dep005_r2_decision_binding` 的hash必须等于ref.sha256、DEP R2算法独立复算结果、上述records、post-sync、`baseline_binding.dep005_decision_snapshot_sha256`和E.`dep005_zero_effect`。joint source baseline必须逐字等于CR-014与DEP R2冻结值。完整六键object进入八个13键item payload与15键aggregate payload，因此joint root/item/aggregate键数均不变化。

APPROVED/REJECTED null matrix、两组六项 decision universe、safe-code enum、八角色顺序 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test` 和 detached evidence payload键数均继承 R1。唯一成员数量变化是 dependency `6→7`；不得增加新 decision alias、frontend approver或 CR-013 artifact approver。

### 6.2 E v2

`operation-log-baseline-delta-attestation-v2` root 仍精确 22 键。`sync_evidence_chain` 数量 `7→8` 并使用第 4 节顺序；`delta_records` 仍恰好 2 项且只允许 `(CR-006,CR-006-R2)`、`(CR-008,CR-008-R2)`；每项仍 7 键，两个 delta object仍各 3 键。CR-006 contribution保持 `api_add=[]/api_remove=[]/core_parent_tables=1`，CR-008 保持 `0/0/0`；CR-013 不进入该数组。`artifact_bindings` 仍只含 A—D 四项、每项 6 键。E 不含 joint instance hash。

### 6.3 Effective-set v2

`effective-api-set-v2` root仍精确 5 键；`delta_records` 仍与 E 同一两项 JCS array；`apis` 从八项 aggregate lineage解析并固定为 125 个 identity，仍按 `(api_id,method,path_template)` 排序且唯一。CR-013 的 API delta 为 0，不能产生第 126 项或第三条 delta record。

### 6.4 Hash 复用和重生成

| 制品 | 本次规则 |
|---|---|
| A Resource/Result Dictionary | R2 instance必须重生成并重新批准；即使内容集合相同，也不得复用旧 instance hash |
| effective-set、fact-schema-bundle instance | 必须重生成；它们绑定新的 aggregate baseline、R2 delta identity或 v2 effective-set |
| B API Emission Registry | 必须重生成；绑定 effective-set v2与更新后的 API source hash |
| C Worker Handler Binding | 本次必须重生成；其 fact-bundle instance binding已变化 |
| D Action Registry | 必须重生成；它绑定新的 B/C，即使 action tuple集合相同 |
| E、joint candidate、CR-006/008 companion与 fixed-vector bundle | 必须重生成；source、recipe、结果、lineage、revision、array count或 v2 Schema已变化 |
| R1 CR-006 row/genesis/manifest/difference/restore及A—D raw Schema | 只有 raw bytes且全部嵌入身份逐字未变时可复用原 Schema hash/version；这不允许复用 R1 instance |
| Alembic migration file/manifest/implementation attestation | CR-006 的 `down_revision` 必须指向其实施前已经批准并落地的真实上游唯一head；随后 CR-013 migration的 `down_revision` 才指向已落地CR-006 head，禁止CR-006反指后置CR-013。migration file bytes、manifest v2 Schema/instance及implementation-attestation v2 Schema/instance全部重生成，SQL对象定义相同不构成hash复用证明 |
| registry SQL或其他实现制品 | 不含 revision/snapshot/baseline/v2 ref且 raw bytes逐字相等时才可复用；任一绑定漂移即重生成 |

## 7. 无环生成与八角色联合批准

顺序固定如下：

1. 先冻结并生成CR-014 snapshot，再冻结并生成DEP-005-R2 snapshot，最后复核R1基座并分别生成CR-006-R2、CR-008-R2 addendum snapshot；生成snapshot本身不构成批准。
2. DEP owner revision批准 shared v2；复用 detached/signing v1只表示格式复用，不表示批准复用。
3. 生成 CR-013 九角色 contract records；其后才可生成四角色 keyring artifact records和 current pin。Request sync只消费九角色 contract set。
4. 先生成 DEP-only post-sync v2，再按八项 lineage逐 source授权、同步并形成连续 aggregate baseline。
5. 从 aggregate baseline和两条 R2 prospective delta生成 effective-set v2、fact bundle、A—E、companion/vector；先有 effective-set，后有引用它的 E。
6. 生成 joint v2 unsigned shared fields。按固定八角色顺序，各自对精确 13 键 item payload签 detached evidence并完成 8 键 approval item。
7. 八项 approval完成后，对 joint root删除根 `evidence_ref/evidence_sha256` 的 15 键 payload生成 `joint_aggregate` evidence，再组装 17 键 no-replace record。

joint artifact array只含 joint Schema，不含 joint instance；E 不含 joint hash；item payload不含 approvals array或自身 evidence；aggregate payload不含根 evidence。因此不存在自签、E↔joint、record↔evidence或 CR-006↔CR-008 批准环。任一步失败只保留不可消费 candidate。

## 8. R2 snapshot 算法与机械验收

1. 读取本文件原始 bytes，拒绝非法 UTF-8、UTF-8 BOM、其他编码或替换字符。
2. 将 CRLF 与孤立 CR 统一为 LF；不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，行首尾无其他字符，且全文件恰好一次。
4. preimage 是 marker 行首之前的全部字符；移除末尾所有 LF，再追加且只追加一个 LF。
5. 以无 BOM UTF-8 编码后计算 SHA-256并输出 64 位小写 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. R2 snapshot record必须同时绑定本文件 `revision=CR-006-R2` 和第1节R1 base tuple；后续joint必须通过精确六键 `cr_bindings` 直接绑定CR-014与DEP R2。第1—8节任一byte变化都必须提升revision并废弃旧R2签名；只更新第9节不改变preimage。
7. 生成 snapshot前必须机械验证：唯一 marker；章节 1—8齐全；R1 base tuple精确；decision全集6且无R2 alias；source record `oneOf/artifact oneOf=10/7`；lineage8；dependency7；joint root/cr_bindings/artifact/approval计数 `17/6/51/8`；E root/chain/delta计数 `22/8/2`；effective root/API计数 `5/125`；无额外 source、第三条 delta、未知 Schema version、占位或猜测 hash。
8. snapshot计算属于静态合同冻结后的独立生命周期动作；结果只可写入第9节及外部no-replace binding。Schema、artifact、签名或批准证据缺失时不得生成可消费joint，也不能以口头批准替代。

## 9. 当前状态

| 项目 | 状态 |
|---|---|
| R1 base binding | `DEFINED / NOT RE-APPROVED` |
| `OPLOG-D-001..006` R2 effective selection | `REVIEW CANDIDATE / NOT APPROVED` |
| R2 decision preimage bytes | `15030` |
| R2 decision snapshot SHA-256 | `cf39c94ea4817de91114094630070d5934e444963e1ea77abbfd22094aa5fc0d` |
| R2 decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` |
| shared v2 Schemas | `SOURCE RECORD SCHEMA GENERATED / POST-META SCHEMAS NOT GENERATED / NOT APPROVED` |
| effective-set、A—E、joint v2 | `DEFINED / NOT GENERATED / NOT APPROVED` |
| Request sync | `NOT AUTHORIZED / NOT EXECUTED` |
| migration/runtime/network/production | `NOT AUTHORIZED / NOT RELEASED` |
