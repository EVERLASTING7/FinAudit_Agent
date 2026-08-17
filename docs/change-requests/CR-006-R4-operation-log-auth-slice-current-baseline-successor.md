# CR-006-R4：AUTH operation-log current-head successor addendum

> 文档类型：`CR-006-R3` 的最小 successor addendum  
> 修订：`CR-006-R4`  
> 日期：`2026-08-11`  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 10 节  
> source baseline manifest：`1689/a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3`  
> 非目标：不修改 predecessor、Request、manifest、`approval_pre_meta.py`、migration、代码或测试；不生成 approval、snapshot、receipt、bundle、artifact 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

本 addendum 逐字绑定下列不可变 predecessor；不修改、替换或追认其文件：

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-006-R3-operation-log-auth-slice-current-baseline-successor.md` |
| `base_revision` | `CR-006-R3` |
| `base_raw_bytes` | `67564` |
| `base_raw_sha256` | `298fc791e865e927ee8c3a67a76a25c44033032af1b12df83abbf481f9f8adb4` |
| `base_decision_preimage_bytes` | `66284` |
| `base_decision_preimage_sha256` | `c0ef1a5b6a8d23ebebe6842b33a3d65b8ddedb89552a0f09f41644dfc10084d1` |
| `successor_revision` | `CR-006-R4` |

`CR-006-R4 effective contract` 的唯一含义是：

```text
exact CR-006-R3 decision preimage
+ this document sections 1 through 9 addendum decision preimage
```

两份 preimage/hash 必须分别验证；不得拼接 bytes 后发明第三个 hash，也不得把 predecessor 的动态状态区纳入继承。未被第 3～6 节明确覆盖的 predecessor 决策原样继承；冲突时本 addendum 优先。任何其他变化必须另升 revision。

## 2. 零 substantive-semantic delta

本 revision 不新增、删除、重命名、重排或重新解释 source-owner substantive decision。决策全集仍且仅为 predecessor 固定的九项：

1. `OPLOGAUTH-D-001=AUTH_ACTION_REGISTRY_V1`
2. `OPLOGAUTH-D-002=TRUSTED_IDENTITY_AND_TELEMETRY_V1`
3. `OPLOGAUTH-D-003=PG16_COMPOSITE_TIME_IDENTITY_V1`
4. `OPLOGAUTH-D-004=UTC_MONTH_FAIL_CLOSED_DEFAULT_GUARD_V1`
5. `OPLOGAUTH-D-005=APPEND_ONLY_ACL_V1`
6. `OPLOGAUTH-D-006=LOCAL_TEST_DAILY_CHAIN_V1`
7. `OPLOGAUTH-D-007=LOCAL_TEST_RETENTION_BACKUP_RESTORE_V1`
8. `OPLOGAUTH-D-008=BOOTSTRAP_AND_FAULT_ATOMICITY_V1`
9. `OPLOGAUTH-D-009=AUTH_SLICE_ONLY_NO_PRODUCTION`

predecessor 对十个 action rows、AUTH 摘要白名单、trusted identity、PostgreSQL 16 composite identity、UTC 月分区、default fail-closed guard、append-only ACL、wrapper/bootstrap、daily chain、retention、backup/restore、fault atomicity、错误码、local/test 与 production 禁止边界的全部规范逐字继承。`OPLOGAUTH-C-010` 仍只是外部 governance dependency，不进入上述九项 `selected_decisions`。

## 3. current-baseline override

只覆盖 predecessor 中已漂移的 current-head 事实：

| 字段 | predecessor 旧值 | R4 唯一 active candidate 值 |
| --- | --- | --- |
| `accepted_unique_head` | `20260807_008` | `20260807_009` |
| `accepted_physical_table_count` | `15` | `18` |
| `baseline_core_table_count` | `57` | `57` |
| accepted head 边界 | AUTH/oplog candidate 之前的旧 active head | 当前已接受的 contract-linkage D-root；不授权 AUTH/oplog Repository、Service、Router 或 runtime |

当前 accepted storage head 只是本候选的新 predecessor，不追认或批准本 addendum 的任何 operation-log 选择。

## 4. migration identity override

predecessor 已规定 head 漂移时禁止原地 rebase，必须创建 successor。因此 migration identity 只作以下替换：

| 字段 | predecessor 旧候选 | R4 唯一候选 |
| --- | --- | --- |
| `candidate_migration_file` | `20260811_009_create_operation_log_auth_slice.py` | `20260811_010_create_operation_log_auth_slice.py` |
| `candidate_revision` | `20260811_009` | `20260811_010` |
| `candidate_down_revision` | `20260807_008` | `20260807_009` |
| `candidate_migration_path` | predecessor 对应 path | `backend/alembic/versions/20260811_010_create_operation_log_auth_slice.py` |

Gate B/C 的唯一 migration round-trip 必须为：

```text
20260807_009
  -> 20260811_010
  -> 20260807_009
  -> 20260811_010
```

只有 `alembic heads` 与目标 disposable PostgreSQL 16 的 `alembic current` 均逐字为 `20260807_009` 时，未来获批的 candidate 才可进入 upgrade。任何新漂移必须再次升 successor；禁止修改 `20260811_010` 的 `down_revision`、自动 rebase、sibling/merge head 或复用旧审 bytes。

当前 `18/57` 加 predecessor 已冻结的 `operation_logs` 与新增 baseline 外 `operation_log_chain_state` 后，候选 Gate C 物理计数为 `20/58`。该计数变化不改变两表的继承 Schema、ACL 或安全语义。

## 5. companion、共同治理与 approval-kind override

只覆盖 revision-bearing reference，不改变 Gate 顺序或授权模型：

| 字段 | predecessor 旧值 | R4 候选值 |
| --- | --- | --- |
| companion | `CR-013-R2` | `CR-013-R3` |
| governance owner | `CR-014-R2` | `CR-014-R3` |
| ordered source set | `[CR-006-R3,CR-013-R2]` | `[CR-006-R4,CR-013-R3]` |
| dependency value | `OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` | `OPLOGAUTH-C-010=CR014_R3_AUTH_OPLOG_SHARED_TRANSITION_V1` |
| source A1 approval kind | `CR006_R3_SOURCE_A1` | `CR006_R4_SOURCE_A1` |

`C010-GOVERNANCE` 仍只表示 `CR-014-R3` governance snapshot 与 BOSS direct approval 有效；`C010-PUBLISH` 仍表示后续两个 source A1、CR-013 A2、bundle、joint authorization 与 cooperative eleven-file transition 已完成。后置 publish 事实不得反向成为本 source snapshot/A1 的前置。

本文件不定义 approval message 格式、不包含 approval block，也不生成或接受任何 receipt/artifact。

## 6. cumulative delta 与投影边界

相对当前 active baseline 的候选累计 delta 保持：

| delta | exact candidate value |
| --- | ---: |
| `api_path_delta` | `0` |
| `ui_page_delta` | `0` |
| `baseline_core_table_delta` | `+1` |
| `operation_log_action_delta` | `+10` |
| `alembic_migration_delta` | `+1` for this source |
| `source_semantic_delta` | `NONZERO` |

Request projection 的 action、Schema、ACL、安全和 local/test 语义全部来自 effective contract；本 addendum 只使其 lineage 可基于当前 head 被审核。同步仍必须由 `CR-014-R3` 的同一 eleven-file transition 独占执行，禁止本文单独改 Request 或 manifest。

## 7. 非继承、权限与停止条件

以下 predecessor 动态事实一律不继承：生命周期状态、Gate 状态、decision snapshot、任何 approval/message、receipt、role record、A2 artifact、expected-post/inverse bundle、joint authorization、intent、terminal receipt、sync/publish evidence、migration/runtime/AC evidence。

本文件及其静态 bytes 不授权：

- 修改既有 CR、九份 Request、manifest、`approval_pre_meta.py`、代码或测试；
- 创建 migration、账号、Token、数据库对象，或启动 PostgreSQL、Redis、Backend、Frontend、浏览器、容器或网络；
- 生成 snapshot、approval block、receipt、bundle、artifact、签名、key、secret、部署、UAT 或 AC evidence。

任何 source baseline、predecessor identity、current head、companion 或 governance contract 漂移都立即 fail closed，并要求新的 successor；不得猜测修复。

## 8. Gate 顺序

1. `STATIC-DRAFT`：验证 predecessor raw/decision identities、本 addendum marker/bytes/hash、current manifest 与 unique accepted head；当前只允许停在此步。
2. `GOVERNANCE`：未来由 `CR-014-R3` 独立 review、生成 governance snapshot并取得其唯一 BOSS direct approval。
3. `SOURCE-A1`：再生成本 R4 source snapshot，由 `CR006_R4_SOURCE_A1` 精确批准九项 D decisions，并验证 C-010 dependency。
4. `PUBLISH`：等待 CR-013-R3 A1/A2、bundle 与 `AUTH_OPLOG_JOINT_SYNC`，再按唯一 cooperative eleven-file transition 同步。
5. `IMPLEMENT`：只有 active Request/manifest/pre-meta 已闭合后，才可生成 migration、代码与 local/test evidence。

不得跳步；静态 draft、hash 或 review 都不是 approval。

## 9. predecessor-literal allowlist 与静态验收

旧 revision literal 只允许出现在以下位置：

- 文档类型声明及第 1 节不可变 predecessor path/revision/identity/effective-contract 表达式；
- 第 3～5 节 `predecessor 旧值` 列；
- 本节 allowlist 描述。

允许的旧 literal 集合恰为：

```text
CR-006-R3
CR-013-R2
CR-014-R2
CR006_R3_SOURCE_A1
CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1
20260807_008
20260811_009
```

它们不得成为 R4 active candidate、target revision、ordered source、migration identity、approval kind 或 governance dependency 值。静态验收还必须证明文件为 UTF-8 no-BOM、LF-only，且 terminal lifecycle heading 前的 LF 是 decision-preimage 唯一切点；本文件 decision snapshot 当前不得生成。

## 10. 当前动态状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `APPROVED / SOURCE CONTRACT ONLY / RUNTIME NOT AUTHORIZED` |
| predecessor raw identity | `RECHECKED / PASS AT SOURCE SNAPSHOT GENERATION` |
| predecessor decision identity | `RECHECKED / PASS AT SOURCE SNAPSHOT GENERATION` |
| current accepted head | `20260807_009 / 18 TABLES / RECHECKED PASS` |
| R4 decision snapshot | `GENERATED / bytes=8945 / sha256=159dd1588d9366c85e8aa1ffc5f9b910ea9319732a491785ce2fdf10d8096e8c` |
| CR-014-R3 governance approval | `RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,a592ac07-5a2f-4dac-aae7-c960e9698fc3,item-572) / receipt_sha256=7421b7913ed31b12ba37da52f2a74d3ac28d7eab01bfeea0efc5bcde2c9bd08b` |
| CR006_R4 source A1 | `RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,019ff276-9da1-7491-8811-d872050f2cb6,item-652) / platform=2026-08-11T20:14:48Z / consumed=2026-08-11T20:25:48.332664Z / source_text_sha256=69886a5974497a981f8649f8071f476487319fe2f0abdfc9636b3618ef331695 / receipt=artifact://finaudit/auth-oplog-source-sync-v1/approval-receipts/CR006_R4_SOURCE_A1/227ddf1b-50f9-4a85-8245-c94ec88c9ba8 / receipt_bytes=1807 / receipt_sha256=d98c2556a07deb73b6683fdc8c325498a19815acb0034cbf2ac3f7905f2aab1c` |
| Request/manifest/pre-meta | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT GENERATED / NOT AUTHORIZED / NOT RUN` |
| production/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
