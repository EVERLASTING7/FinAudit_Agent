# CR-008-R2：CR-013 lineage 与 action-registry shared v2 successor addendum

> 文档类型：`CR-008-R1` 的最小 successor addendum
> 修订：`CR-008-R2`
> 静态性质：versioned successor contract；生命周期状态只记录在第 9 节
> 非目标：不复制或改写 R1 正文，不生成 snapshot、Schema、artifact、签名、migration 或批准事实

## 1. 基座与 effective contract

本 addendum 只在下列不可变 R1 基座上生效：

| 字段 | 固定值 |
|---|---|
| `base_revision` | `CR-008-R1` |
| `base_preimage_bytes` | `96741` |
| `base_decision_snapshot_sha256` | `2f67b69bc1dc8967f7299919a33f7b6e7253b0108ba77e9466b1613d0183f9b8` |
| `successor_revision` | `CR-008-R2` |

`CR-008-R2 effective contract` 的唯一含义是“上述精确 R1 snapshot 加本文件第 1—8 节的 R2 addendum snapshot”。它不复制 R1，不修改 R1 snapshot，也不把两份 bytes拼成未定义的第三个 hash。验证器必须先匹配 R1 byte length/hash，再验证本 addendum。

R1 的 `OPLREG-D-001..006`、122 API 历史锚点、动作字典、A—E 数据面、条件 AST、拒绝/GET/Worker规则、验收和非授权边界全部原样继承。只有本文件明确列出的 revision、lineage、shared support version、joint/E/effective-set绑定与生成顺序由 R2 覆盖；任何其他语义变化必须另升 revision。

R2 原子批准必须由 joint v2 的精确六键 `cr_bindings` 直接绑定同一 CR-014 与 DEP-005-R2 snapshot。该object保留原四键 `cr006_revision/cr006_decision_snapshot_sha256/cr008_revision/cr008_decision_snapshot_sha256`，并新增：精确复用 DEP R2 的五键 `successor_review_binding`，以及精确四键 `dep005_r2_decision_binding=revision/decision_snapshot_marker/decision_preimage_ref/decision_preimage_sha256`。验证器必须解析CR-014 snapshot并逐字复核其四份R1 identity、固定source baseline和八项decision，再复核DEP R2 snapshot。实际ref/hash只在这些snapshot生成后作为package-external input进入joint，禁止在本静态preimage中预填、置null、全零或使用placeholder。

## 2. R2 决策与批准全集

R2 不新增第二套业务决策 code。它冻结的 `cr008 decision universe` 仍恰为 `OPLREG-D-001`、`OPLREG-D-002`、`OPLREG-D-003`、`OPLREG-D-004`、`OPLREG-D-005`、`OPLREG-D-006`，含义逐字解析自第1节绑定的 R1 snapshot；本 addendum只改变 successor identity、lineage与机器绑定。

R2 joint `decision_scope.cr008_selected/cr008_rejected` 仍使用上述六项封闭全集和编号顺序。APPROVED时 selected恰为六项且 rejected为空；REJECTED时两数组无重复、互斥并精确分区六项全集，且 rejected非空。joint同时绑定 `CR-008-R2` addendum snapshot，因此“六项全选 + R2 snapshot”才表示批准 R2 effective contract；单独批准 R1、单独签 addendum、引入 `OPLREG-R2-*` alias或省略 R2 snapshot均不合格。

该批准不把文档、candidate或 hash冒充批准，也不授权 Request sync、migration、runtime、网络或 production。

## 3. Cumulative delta 与 CR-013 upstream delta

四元组顺序固定为 `api_path_delta/core_parent_table_delta/owned_alembic_revision_count/operation_log_action_delta`：

| 身份 | cumulative delta | 本次 addendum delta |
|---|---:|---:|
| `CR-008-R2` | `0/0/0/0` | `0/0/0/0` |

CR-008-R2 不新增 API path、core parent table、migration或 action。R1 action registry条目是生成制品内容，不是 `operation_log_action_delta` 数量。

CR-013-R1 delta固定为 `0/0/1/0`：其单一 migration在获批并完成 source-only Request sync后已属于 aggregate baseline；其 API/core/action均为0，认证事件复用 R1 action code。CR-013不得进入 E `delta_records`，不得增加 `deltas_and_counts` 字段，不得因 keyring artifact批准新增 operation action。

## 4. 八项 sync chain 与七项 dependency

E v2 `sync_evidence_chain` 必须恰有八项并按以下语义顺序排列：

`DEP-005/CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`。

首项引用 DEP-only `dep005-post-sync-baseline-attestation-v2`；后七项引用 `request-sync-transition-evidence-v2`。每项精确七键，ref/hash相等，后一项 pre baseline等于前一项 post baseline；末项 post、effective-set `baseline_manifest_sha256`、E `post_all_upstream_sync_baseline_manifest_sha256` 和可寻址 aggregate manifest必须逐字相等。

joint `dependency_bindings` 必须恰有七项、每项仍精确十一键，固定顺序：

`CR-003/CR-013/CR-004/CR-005/CR-007/CR-009/CR-010`。

CR-013项使用 `decision_preimage/CR-013-R1`，两个 fact-set Schema字段为 null，fact ref/hash解析到 no-replace CR-013 preimage/snapshot；批准事实必须沿其 transition → authorization → 九角色 source-contract v2 record set验证。CR-013 keyring artifact四角色记录和 current pin只服务 keyring activation，不进入 Request sync binding、dependency或 joint artifact角色。

CR-004 fact set继续使用 v1 root 17/八角色七键 item；CR-010 fact set继续使用 v1 root 16/八角色七键 item。两者 shape、role、detached payload和 null matrix均不因插入 CR-013改变。

## 5. Shared v2 与 Schema 复用矩阵

下列 raw Schema必须使用新 v2文件名，不得改写已定义或已生成的 v1：

1. `source-contract-approval-record-v2.schema.json`
2. `request-sync-authorization-v2.schema.json`
3. `request-sync-transition-evidence-v2.schema.json`
4. `dep005-post-sync-baseline-attestation-v2.schema.json`
5. `cr006-cr008-joint-approval-record-v2.schema.json`
6. `operation-log-baseline-delta-attestation-v2.schema.json`
7. `effective-api-set-v2.schema.json`
8. `cr006-migration-object-manifest-v2.schema.json`
9. `cr006-migration-implementation-attestation-v2.schema.json`

对应变化固定为：

- source approval root仍30键；source enum `5→6`、scope enum `3→4`；顶层branch selector精确10个 `oneOf` leaves（DEP R1两scope、四个legacy source、DEP R2两scope、CR-013两scope），artifact bindings精确7类（DEP R1 meta/artifact、DEP R2 meta/artifact、legacy source、CR-013 contract/artifact）；禁止误写为 `5→6` 或 `3→5`；
- request authorization root仍23键、source binding仍10键、source union `7→8`；
- transition root仍18键、source union `6→7`；
- DEP post-sync root仍21键、DEP approval refs仍8项、Request files仍9项；
- CR-013 contract records是九角色/八项决策/`0/0/1/0`；keyring artifact records是四角色/`AUTHKEY-A-001`，但只有前者可授权 Request sync。

以下 raw Schema按原 v1身份复用：`dep005-detached-approval-evidence-v1`（root15、scope7）、`approval-signer-registry-v1`（root3、key10）、CR-004 root17 fact set、CR-010 root16 fact set、`operation-log-fact-schema-bundle-v1`，以及结构语义未改变的 A—D和 CR-006机器 Schema。复用是 raw-byte identity，不是批准状态继承；registry/pin或 instance只在 no-replace bytes和所有外部 expected binding逐字相等时复用。

## 6. E、effective-set、A—D 与 joint v2

### 6.1 E v2

`operation-log-baseline-delta-attestation-v2` root仍精确22键：

- `sync_evidence_chain` 数量 `7→8`，顺序采用第4节；
- `delta_records` 数量仍2，且只含 `CR-006-R2` 与 `CR-008-R2`；每项仍7键；
- `declared_delta/effective_contribution` 仍各3键；CR-006为 `[]/[]/1`，CR-008为 `[]/[]/0`；
- `artifact_bindings` 仍仅A—D四项、每项6键；
- `baseline_source_bindings`、`baseline_counts`、`effective_counts`、`generator` 与 `dep005_zero_effect` 的 root shape不变；
- CR-013只存在于 chain/aggregate baseline，不是第三条 delta。

E仍不包含自身 instance hash或 joint record hash；`approval_status='prospective_joint_approval'`、`sync_status='unsynced'` 的历史 observation语义不变。

### 6.2 Effective-set v2

`effective-api-set-v2` root仍精确5键 `schema_version/set_version/baseline_manifest_sha256/delta_records/apis`。`delta_records` 与 E同一两项 JCS bytes；`apis` 必须从八项 aggregate baseline解析，恰为125个 identity，按 `(api_id,method,path_template)` 升序且 `api_id` 唯一。CR-013不新增 path；结果不是122，也不是126。

### 6.3 A—D 与 R1实现制品

| 制品 | 当前 successor 规则 |
|---|---|
| A Resource/Result Dictionary | R2 instance必须重生成并重新批准；即使内容集合相同，也不得复用旧 instance hash |
| fact-schema-bundle instance | 必须重生成以绑定新的 aggregate/effective API source identity；raw v1 Schema可复用 |
| B API Emission Registry | 必须重生成并绑定 effective-set v2、更新后的 API source hash及新 fact bundle |
| C Worker Handler Binding | 本次必须重生成，因为 fact bundle binding改变；Handler/input bundle自身未变不免除该要求 |
| D Action Registry | 必须重生成，因为 B/C hash改变；action tuple可相同但 instance hash不能沿用 |
| E、effective-set、joint、CR-008 companion/test vectors | 必须重生成以覆盖R2 revisions、八项 chain、七项 dependency和 v2负向量 |
| R1纯数据 raw Schema/静态输入 | raw bytes和全部嵌入 version/hash/ref逐字相等时可复用 Schema/输入 hash；R1 instance、companion与 fixed-vector bundle不得据此复用 |
| 含 `R1` revision/snapshot、七项旧 chain、六项 dependency、v1 successor ref或 aggregate hash的制品 | 必须重生成，不得保留旧 hash后只改元数据 |

### 6.4 Joint v2

`cr006-cr008-joint-approval-record-v2` root仍17键；`decision_scope`仍4键且两组 universe各保持6项；`approvals`仍8项/每项8键；`cr_bindings`从4键提升为第1节精确6键；`baseline_binding`仍12键；`artifact_bindings`仍51项/每项5键；`dependency_bindings` `6→7`/每项11键；`deltas_and_counts`仍17键；`scope`仍5键。

六键 `cr_bindings.successor_review_binding` 必须与 DEP R2 八条meta和八条approved-artifact record逐JCS相等；`dep005_r2_decision_binding` 的hash必须等于ref.sha256、DEP R2算法独立复算结果、上述records、post-sync、`baseline_binding.dep005_decision_snapshot_sha256`和E.`dep005_zero_effect`。joint source baseline必须逐字等于CR-014与DEP R2冻结值。完整六键object进入八个13键item payload与15键aggregate payload，因此joint root/item/aggregate键数均不变化。

51项 artifact role不新增 CR-013角色，只把 generic source approval、authorization、transition、DEP post-sync、joint、E与effective-set现有role切到 v2；A—D role按本节复用/重生成规则绑定实际 bytes。`deltas_and_counts` 不增加 `cr013_*` 字段，因为 CR-013已在 aggregate baseline中且 contribution为 `api=0/core=0/action=0`。

APPROVED时两组 selected各六项、rejected为空、八角色全 APPROVED、四组 binding non-null且完整；REJECTED矩阵和 safe codes逐字继承 R1。角色仍固定 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test`，不增加新 decision alias、frontend或 keyring artifact approver。

## 7. Hash DAG 与联合批准顺序

1. 先冻结并生成CR-014 snapshot，再冻结并生成DEP-005-R2 snapshot，最后复核两份R1 base tuple并分别生成CR-006-R2/CR-008-R2 addendum snapshot；生成snapshot本身不构成批准。
2. DEP owner revision批准 shared v2；detached/signing/fact-set v1只按第5节复用。
3. 形成 CR-013九角色 contract set；四角色 keyring artifact set及pin只能在其后形成，且不替代 source approval。
4. 先产生 DEP-only post-sync，再按八项 chain逐 source授权/同步，得到 aggregate baseline。
5. 从 aggregate baseline和两条 R2 prospective delta先生成 effective-set v2，再生成 fact bundle、A、B、C、D，最后生成引用它们的E；companion/vector不能反向嵌入最终 E hash。
6. joint unsigned shared fields完成后，按 `requirements_product/architecture/data_dba/backend_api/ai_rag/ops/security/test` 顺序生成八个 `joint_approver_decision` evidence和8键 approval items。
7. 八个 items完成后，对删除根 evidence两键的15键 payload生成 `joint_aggregate` evidence，再组装17键 no-replace joint record。

E不绑定 joint hash；joint artifact array只绑定 joint Schema、不绑定 joint instance；item payload不含 approvals array或自身 evidence；aggregate payload不含根 evidence。该顺序消除 E↔joint、approval↔aggregate、CR-006↔CR-008和 candidate↔live-state循环；任一缺项都只能保留为不可消费candidate。

## 8. R2 snapshot 算法与验收

1. 严格按 UTF-8读取本文件；拒绝BOM、非法序列、替换字符或其他编码。
2. 将 CRLF和孤立CR规范化为LF，不做 Unicode normalization。
3. marker必须是整行精确 `## 9. 当前状态`，全文件恰好一次，行首尾无其他字符。
4. preimage取 marker行首之前全部内容；删除末尾所有LF，再追加恰好一个LF。
5. 以UTF-8无BOM编码并计算SHA-256，输出64位小写hex；不裁剪空格、不改制表符、不重排Markdown。
6. snapshot record必须同时绑定 `revision=CR-008-R2` 和第1节R1 base tuple；后续joint必须通过精确六键 `cr_bindings` 直接绑定CR-014与DEP R2。第1—8节任何byte变化都必须提升revision并使旧R2签名失效；只更新第9节不改变preimage。
7. 生成前机械检查：R1 base tuple；唯一marker；R2决策仍为6项且无R2 alias；source record `oneOf/artifact oneOf=10/7`；lineage8；dependency7；E `root/chain/delta=22/8/2`；effective `root/apis/delta=5/125/2`；joint `root/cr_bindings/approvals/artifacts/dependencies=17/6/8/51/7`；CR-013仅在chain/dependency；无第三条delta、额外action、未知Schema version、占位或猜测hash。
8. snapshot计算属于静态合同冻结后的独立生命周期动作；结果只可写入第9节及外部no-replace binding。Schema、artifact或签名证据缺失时不得生成可消费joint。

## 9. 当前状态

| 项目 | 状态 |
|---|---|
| R1 base binding | `DEFINED / NOT RE-APPROVED` |
| `OPLREG-D-001..006` R2 effective selection | `REVIEW CANDIDATE / NOT APPROVED` |
| R2 decision preimage bytes | `13985` |
| R2 decision snapshot SHA-256 | `aa27ca424cb0b5065db214186aba9516c093619486fdf96217adaeacb3ad4165` |
| R2 decision snapshot | `GENERATED_FOR_REVIEW / NOT APPROVED` |
| shared v2 Schemas | `SOURCE RECORD SCHEMA GENERATED / POST-META SCHEMAS NOT GENERATED / NOT APPROVED` |
| effective-set、A—E、joint v2 | `DEFINED / NOT GENERATED / NOT APPROVED` |
| Request sync | `NOT AUTHORIZED / NOT EXECUTED` |
| migration/runtime/network/production | `NOT AUTHORIZED / NOT RELEASED` |
