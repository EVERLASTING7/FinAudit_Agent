# CR-014-R3：AUTH/Oplog current-head governance successor addendum

> 文档类型：`CR-014-R2` 的最小 successor addendum  
> 修订：`CR-014-R3`  
> 日期：`2026-08-11`  
> 静态性质：versioned governance contract candidate；生命周期状态只记录在第 9 节  
> source baseline manifest：`1689/a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3`  
> 非目标：不修改 predecessor、Request、manifest、`approval_pre_meta.py`、代码或测试；不生成 approval、snapshot、receipt、bundle、artifact、post bytes 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

本 addendum 逐字绑定下列不可变 predecessor；R2 已生成但未获批的 governance snapshot 只作历史身份，不得复用：

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-014-R2-auth-oplog-current-baseline-approval-sync-successor.md` |
| `base_revision` | `CR-014-R2` |
| `base_raw_bytes` | `62869` |
| `base_raw_sha256` | `07ef160bad71df03a9b374d1c3fc8b3455103a3a093ccb60f02ffb2add562ce9` |
| `base_decision_preimage_bytes` | `61470` |
| `base_decision_preimage_sha256` | `38a8d329eb2d7ac4414d139431bc0c6448c788d8c21ecdba890a2d48b5207ae8` |
| `base_governance_snapshot_status` | `GENERATED / NOT APPROVED / RETIRED FOR SUCCESSOR` |
| `successor_revision` | `CR-014-R3` |

`CR-014-R3 effective contract` 的唯一含义是：

```text
exact CR-014-R2 decision preimage
+ this document sections 1 through 8 addendum decision preimage
```

两份 preimage/hash 必须分别验证；不得拼接 bytes 后发明第三个 hash，也不得把 predecessor 的动态状态区纳入继承。未被第 3～6 节明确覆盖的 predecessor governance contract 原样继承；冲突时本 addendum 优先。任何其他变化必须另升 revision。

R2 governance snapshot `61470/38a8d329eb2d7ac4414d139431bc0c6448c788d8c21ecdba890a2d48b5207ae8` 不是 R3 snapshot，不授权 R3，也不得被改名、复制、包裹或作为 R3 approval target。

## 2. 当前十一文件 pre identity

以下值逐项沿用当前 checkout 的实际 pre-state。bytes 为 raw byte length，hash 为 raw SHA-256 64 位小写 hex；路径、ordinal、大小写和顺序均属于 identity：

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

任何 independent review、snapshot、approval、staging 或 publish 开始前都必须重新读取全部十一项；任一 identity 漂移立即 `BLOCKED_BY_DRIFT`，必须新升 successor。本文只记录 pre identities，不修改这些文件，也不生成 post identities。

九份 Request 的路径职责、manifest post identity 职责、`approval_pre_meta.py` 最后 commit-marker 职责，以及 cooperative publisher/verifier 的 exact pre/post predicate 全部继承 predecessor。唯一 source order 由第 3 节覆盖。

## 3. ordered sources、lineage 与 migration chain override

只覆盖 current-head 漂移引起的 source lineage：

| 字段 | predecessor 旧值 | R3 唯一 candidate 值 |
| --- | --- | --- |
| ordered sources | `[CR-006-R3,CR-013-R2]` | `[CR-006-R4,CR-013-R3]` |
| accepted unique head | `20260807_008` | `20260807_009` |
| operation-log candidate | `20260811_009 -> 20260807_008` | `20260811_010 -> 20260807_009` |
| auth candidate | `20260811_010 -> 20260811_009` | `20260811_011 -> 20260811_010` |
| complete candidate chain | predecessor chain | `20260807_009 -> 20260811_010 -> 20260811_011` |

source snapshot、approval event refs、receipt correlation、projection manifest、bundle `ordered_sources`、`source_approval_event_refs`、publisher preflight、recovery 与 acceptance verification 必须全部使用同一新顺序；任何 R3/R2 混搭为 `INVALID_BUNDLE`。

## 4. substantive delta 与 choices 继承

治理与组合 source delta 只作 revision 前移，不改变数值或语义：

| delta | R3 exact candidate value |
| --- | ---: |
| `governance_delta` | `ZERO` |
| `combined_source_semantic_delta` | `NONZERO` |
| `api_path_delta` | `0` |
| `ui_page_delta` | `0` |
| `baseline_core_table_delta` | `+1` |
| `operation_log_action_delta` | `+10` |
| `permission_code_delta` | `+1` |
| `alembic_migration_delta` | `+2` candidate |
| `AUTH-010_cross_store_failure_semantics` | `NONZERO / UNCHANGED` |

下列 decision universe、顺序和 exact meanings 全部从 predecessor decision preimage 继承：

- predecessor 第 3.2 节七项 governance decisions，保留其既有 literal codes，不创建 R3 alias；
- CR-006 的 `OPLOGAUTH-D-001～D-009` 九项；
- CR-013 的 `AUTHSLICE-D-001～D-008`、`AUTHSLICE-C-001～C-008`、`AUTHSLICE-JS-001～JS-009`，但第 5 节明确覆盖的两个 shared-transition values 除外；
- predecessor 第 6.3 节四项 joint-sync decisions，保留其既有 literal codes，不创建 R3 alias；
- 十个 action rows、六个 API、所有 password/JWT/session/Redis/ACL/atomicity/error/security、blocklist artifact、publisher/recovery/acceptance substantive semantics。

保留 predecessor 中带旧 revision 前缀的 governance/sync decision code，是为了维持 decision universe byte-level identity；它们是 inherited decision identifiers，不是 R2 target revision、approval kind、snapshot 或 active source 别名。

## 5. shared dependency 与 approval-kind override

只替换 revision-bearing dependency、approval kind 和 target revision：

| 字段 | predecessor 旧值 | R3 candidate 值 |
| --- | --- | --- |
| CR-006 dependency | `OPLOGAUTH-C-010=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` | `OPLOGAUTH-C-010=CR014_R3_AUTH_OPLOG_SHARED_TRANSITION_V1` |
| CR-013 shared choice | `AUTHSLICE-C-007=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` | `AUTHSLICE-C-007=CR014_R3_AUTH_OPLOG_SHARED_TRANSITION_V1` |
| governance approval kind / target | `CR014_R2_GOVERNANCE / CR-014-R2` | `CR014_R3_GOVERNANCE / CR-014-R3` |
| CR-006 source A1 kind / target | `CR006_R3_SOURCE_A1 / CR-006-R3` | `CR006_R4_SOURCE_A1 / CR-006-R4` |
| CR-013 source A1 kind / target | `CR013_R2_SOURCE_A1 / CR-013-R2` | `CR013_R3_SOURCE_A1 / CR-013-R3` |
| CR-013 blocklist A2 kind / target | `CR013_R2_BLOCKLIST_A2 / CR-013-R2` | `CR013_R3_BLOCKLIST_A2 / CR-013-R3` |
| joint kind / target | `AUTH_OPLOG_JOINT_SYNC / CR-014-R2` | `AUTH_OPLOG_JOINT_SYNC / CR-014-R3` |

typed message 的 lexical rules、十五行 closed shape、roles、decision ordering、scope、nonce/time、artifact binding、platform transcript authority 与 local receipt non-authority 全部继承 predecessor。未来 validator 只允许上表 R3 candidate kind/target 组合；旧 kind/target 一律拒绝。

本文件不包含任何填写后的 approval block，不代表 BOSS 消息，不生成 receipt，也不创建 artifact。approval kind 名称只是未来 contract 的允许值。

## 6. snapshot、approval 与 publish 顺序

顺序固定如下：

1. 独立 reviewer 重新验证三份 successor 的 raw/decision identities、本节 effective contract 和第 2 节十一项 pre identities。
2. 仅在全部无漂移后，机械生成 `CR-014-R3` governance decision snapshot；当前 snapshot 必须保持 `NOT GENERATED`。
3. BOSS 使用 `CR014_R3_GOVERNANCE` 对同一 snapshot作唯一 authoritative direct approval；随后才能派生 non-authoritative governance receipt。
4. 分别生成 CR-006-R4 与 CR-013-R3 source snapshots，再由 `CR006_R4_SOURCE_A1`、`CR013_R3_SOURCE_A1` 批准。
5. source A1 后才可离线生成并独立验证 password blocklist artifact，再由 `CR013_R3_BLOCKLIST_A2` 精确绑定。
6. 只在上述 authority/evidence 全闭合后 staging 十一文件、计算 post/inverse、生成 create-only bundle。
7. bundle 冻结后才可由 `AUTH_OPLOG_JOINT_SYNC` direct message授权；随后才可按 inherited cooperative publisher 执行 transition。

任何 snapshot、receipt、source approval、A2 或自然语言批准都不能替代另一步，也不能授权 migration/runtime。R2 的 snapshot、approval、receipt、bundle、intent、terminal evidence 或 sync authorization均不得进入本序列。

## 7. 非继承、权限与停止条件

以下 predecessor 动态事实一律不继承：生命周期状态、Gate 状态、governance/source snapshot、任何 approval/message、receipt、role record、blocklist payload/final artifact、dependency artifact、expected-post/inverse bundle、joint authorization、intent/fence/backup、terminal receipt、post identity、sync/publish/migration/runtime/AC evidence。

本文件及其静态 bytes 不授权：

- 修改既有 CR、九份 Request、manifest、`approval_pre_meta.py`、代码或测试；
- 生成 approval block、snapshot、receipt、bundle、artifact、post bytes、intent 或 terminal evidence；
- 创建 migration、账号、Token、key、数据库对象，或启动 PostgreSQL、Redis、Backend、Frontend、浏览器、容器或网络；
- 发布、部署、canary、staging、production、UAT 或 AC。

任何 predecessor/source/raw/decision/pre-state identity 漂移都立即 fail closed，并要求新的 successor；不得原地改写、自动 rebase、选取 latest artifact 或猜测修复。

## 8. predecessor-literal allowlist 与静态验收

旧 revision literal 只允许出现在以下位置：

- 文档类型声明及第 1 节不可变 predecessor path/revision/identity/effective-contract/retired snapshot 说明；
- 第 3、5 节 `predecessor 旧值` 列；
- 第 4 节 inherited literal-code 边界；
- 第 6、7 节不继承/retirement 边界；
- 本节 allowlist 描述。

允许的旧 literal 集合恰为：

```text
CR-014-R2
CR-006-R3
CR-013-R2
CR014_R2_GOVERNANCE
CR006_R3_SOURCE_A1
CR013_R2_SOURCE_A1
CR013_R2_BLOCKLIST_A2
CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1
20260807_008
20260811_009
20260811_010
```

其中 predecessor 内继承的 governance/sync decision codes可保留其原 literal，但不得解释为 active revision。`20260811_010` 只在旧 auth candidate 或新 operation-log candidate 语境合法。其余旧值不得成为 R3 active source、target revision、approval kind、dependency、snapshot 或 bundle identity。

静态验收必须证明文件为 UTF-8 no-BOM、LF-only，且 terminal lifecycle heading 前的 LF 是 decision-preimage 唯一切点。本文件当前禁止记录 snapshot bytes/hash，禁止生成 approval block或 artifact。

## 9. 当前状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `APPROVED / GOVERNANCE CONTRACT ONLY` |
| independent reviews | `2/2 PASS / NO CRITICAL-HIGH-MEDIUM FINDINGS` |
| predecessor raw identity | `3/3 RECHECKED / PASS AT SNAPSHOT GENERATION` |
| predecessor decision identity | `3/3 RECHECKED / PASS AT SNAPSHOT GENERATION` |
| eleven-file pre identity | `11/11 RECHECKED / PASS AT SNAPSHOT GENERATION AND GOVERNANCE APPROVAL CONSUMPTION / RECHECK REQUIRED AT EVERY LATER GATE` |
| ordered sources | `[CR-006-R4,CR-013-R3] / CANDIDATE` |
| CR-014-R3 governance snapshot | `GENERATED / bytes=11956 / sha256=e5c00e6e47081d0e7418b48957d7895fe5a4705a1d5008256a7bb291d15b7cd9` |
| governance approval | `RECEIVED / VALID / codex-thread-event-v1:(019fee83-e431-7a32-86ea-b1e043e641b8,a592ac07-5a2f-4dac-aae7-c960e9698fc3,item-572) / platform=2026-08-11T14:08:04Z / consumed=2026-08-11T15:47:02.7228023Z / source_text_sha256=0f37052cf3b6126641e20d8e2311722066e35e4114d5b9ef328d55fe6ae4679c` |
| governance receipt | `CREATED / NON_AUTHORITATIVE_EVIDENCE_ONLY / artifact://finaudit/auth-oplog-source-sync-v1/approval-receipts/CR014_R3_GOVERNANCE/bf5caa4e-4658-42a5-9328-a018833c9a67 / bytes=1801 / sha256=7421b7913ed31b12ba37da52f2a74d3ac28d7eab01bfeea0efc5bcde2c9bd08b` |
| source A1 approvals | `CR-006-R4 RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,019ff276-9da1-7491-8811-d872050f2cb6,item-652) / receipt_sha256=d98c2556a07deb73b6683fdc8c325498a19815acb0034cbf2ac3f7905f2aab1c; CR-013-R3 RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,019ff394-603b-7562-8f17-df808256e983,item-684) / receipt_sha256=1454233d212979663e26e2699b924689cb081e893b456daa30530e81a778b9c8` |
| blocklist A2 | `NOT GENERATED / NOT RECEIVED` |
| expected-post/inverse bundle | `NOT GENERATED` |
| joint authorization | `NOT RECEIVED` |
| Request/manifest/pre-meta | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT GENERATED / NOT AUTHORIZED / NOT RUN` |
| production/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
