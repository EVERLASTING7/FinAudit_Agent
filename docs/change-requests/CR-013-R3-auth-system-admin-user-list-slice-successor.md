# CR-013-R3：system_admin auth/user-list current-head successor addendum

> 文档类型：`CR-013-R2` 的最小 successor addendum  
> 修订：`CR-013-R3`  
> 日期：`2026-08-11`  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 10 节  
> source baseline manifest：`1689/a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3`  
> 非目标：不修改 predecessor、Request、manifest、`approval_pre_meta.py`、migration、代码或测试；不生成 approval、snapshot、password blocklist、receipt、bundle、artifact 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

本 addendum 逐字绑定下列不可变 predecessor；不修改、替换或追认其文件：

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-013-R2-auth-system-admin-user-list-slice-successor.md` |
| `base_revision` | `CR-013-R2` |
| `base_raw_bytes` | `75253` |
| `base_raw_sha256` | `83b6e7878110665921c6b8f189f70f9118380e1050ba9a53fca369e80c8058ba` |
| `base_decision_preimage_bytes` | `73678` |
| `base_decision_preimage_sha256` | `0c009b21ee156a36130a8514519f59aea260de12d16450c1dc72029a0e36a727` |
| `successor_revision` | `CR-013-R3` |

`CR-013-R3 effective contract` 的唯一含义是：

```text
exact CR-013-R2 decision preimage
+ this document sections 1 through 9 addendum decision preimage
```

两份 preimage/hash 必须分别验证；不得拼接 bytes 后发明第三个 hash，也不得把 predecessor 的动态状态区纳入继承。未被第 3～6 节明确覆盖的 predecessor 决策原样继承；冲突时本 addendum 优先。任何其他变化必须另升 revision。

## 2. substantive decision universe 原样继承

本 revision 不新增、删除、重命名、重排或重新解释以下 source-owner substantive decisions：

- top-level `AUTHSLICE-D-001～AUTHSLICE-D-008` 八项及其 exact values；
- `AUTHSLICE-C-001～AUTHSLICE-C-008` 八项及其 exact values，但第 5 节明确覆盖的 revision-bearing `AUTHSLICE-C-007` value 除外；
- nested `AUTHSLICE-JS-001～AUTHSLICE-JS-009` 九项及其 exact values。

predecessor 的 password/login、JWT/refresh、ephemeral Ed25519 local/test signer、session family、Redis one-time password-change token、bootstrap/browser custody、`users:manage`、AUTH-007 read model、password-blocklist staged artifact、API errors、atomicity、security、dependency evidence 与 Gate 语义全部逐字继承。

最短业务链仍且仅为：

```text
offline bootstrap
  -> AUTH-001 first login / AUTH_PASSWORD_CHANGE_REQUIRED
  -> AUTH-010 forced password change
  -> AUTH-001 relogin
  -> AUTH-004 /auth/me
  -> AUTH-007 GET /api/v1/users
  -> UI-014 /users read-only list
```

API path 仍且仅复用 AUTH-001/002/003/004/007/010；`api_path_delta=0`、`ui_page_delta=0`、`permission_code_delta=+1`、`core_table_delta=0`，不得借 successor 扩展 API、角色、permission、DTO、状态、错误码或 UI 行为。

## 3. operation-log predecessor override

CR-006 companion 已因 accepted head 漂移提升 revision；本文件只作下列 lineage 替换：

| 字段 | predecessor 旧值 | R3 唯一 active candidate 值 |
| --- | --- | --- |
| operation-log companion | `CR-006-R3` | `CR-006-R4` |
| operation-log migration revision | `20260811_009` | `20260811_010` |
| operation-log migration predecessor | `20260807_008` | `20260807_009` |
| operation-log source A1 kind | `CR006_R3_SOURCE_A1` | `CR006_R4_SOURCE_A1` |

R3 不复制或改变 CR-006-R4 的 action、table、ACL、wrapper、chain 或 local/test substantive contract；它只消费其未来获批、已同步且已成为 actual unique head 的 `20260811_010`。

## 4. auth migration identity override

只替换 predecessor 的后继 migration identity：

| 字段 | predecessor 旧候选 | R3 唯一候选 |
| --- | --- | --- |
| `migration_file` | `backend/alembic/versions/20260811_010_extend_auth_session_family.py` | `backend/alembic/versions/20260811_011_extend_auth_session_family.py` |
| `revision` | `20260811_010` | `20260811_011` |
| `down_revision` | `20260811_009` | `20260811_010` |

完整候选链固定为：

```text
20260807_009
  -> 20260811_010
  -> 20260811_011
```

进入 auth migration 前，`20260811_010` 必须是 CR-006-R4 最终批准、已检入、已同步且 `alembic heads`/disposable PostgreSQL 16 `alembic current` 唯一返回的 actual head。任一条件不满足，`20260811_011` 整体 `BLOCKED / NOT RUNNABLE`；禁止自动修改 `down_revision`、rebase、sibling/merge head 或复用旧审 bytes。

operation-log candidate 后为 `20/58`；auth migration 只修改 inherited `users/token_sessions` shape，不新增物理表，完成后仍为 `20/58`。列、约束、empty-table precondition、upgrade/downgrade 与 session semantics 全部继承 predecessor。

## 5. 共同治理、source set 与 approval-kind override

只覆盖 revision-bearing reference，不改变 authority、角色、decision order、artifact binding 或 Gate 顺序：

| 字段 | predecessor 旧值 | R3 候选值 |
| --- | --- | --- |
| governance owner | `CR-014-R2` | `CR-014-R3` |
| ordered source set | `[CR-006-R3,CR-013-R2]` | `[CR-006-R4,CR-013-R3]` |
| shared transition choice | `AUTHSLICE-C-007=CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1` | `AUTHSLICE-C-007=CR014_R3_AUTH_OPLOG_SHARED_TRANSITION_V1` |
| source A1 approval kind | `CR013_R2_SOURCE_A1` | `CR013_R3_SOURCE_A1` |
| blocklist A2 approval kind | `CR013_R2_BLOCKLIST_A2` | `CR013_R3_BLOCKLIST_A2` |

future source A1 仍须按 predecessor 固定顺序绑定完整 `D -> C -> JS` universe；A2 仍只批准 exact 四角色 blocklist artifact binding。两者都必须由 `CR-014-R3` effective contract 冻结的 typed direct-message contract 校验。本文件不包含 approval block，也不生成 snapshot、payload、final blocklist、receipt 或 artifact。

## 6. source semantic delta 与投影边界

累计候选 delta 不变：

| delta | exact candidate value |
| --- | ---: |
| `api_path_delta` | `0` |
| `ui_page_delta` | `0` |
| `core_table_delta` | `0` for this source |
| `alembic_migration_delta` | `+1` for this source |
| `permission_code_delta` | `+1` |
| `declared_python_dependency_delta` | `3` |
| `source_semantic_delta` | `NONZERO` |

九份 Request 中 AUTH-001/002/003/004/007/010、UI-001/UI-014、数据库、架构、安全、测试和部署投影仍由 predecessor effective contract 定义。同步必须与 CR-006-R4 共用 `CR-014-R3` 的唯一 eleven-file transition；禁止只同步本 source、生成中间 manifest 或分别 re-pin。

## 7. 非继承、权限与停止条件

以下 predecessor 动态事实一律不继承：生命周期状态、Gate 状态、decision snapshot、任何 approval/message、receipt、role record、password blocklist payload/final artifact、dependency artifact、expected-post/inverse bundle、joint authorization、intent、terminal receipt、sync/publish evidence、migration/runtime/AC evidence。

本文件及其静态 bytes 不授权：

- 修改既有 CR、九份 Request、manifest、`approval_pre_meta.py`、代码或测试；
- 创建 bootstrap 账号、密码 hash、Token、keyring、Redis/PostgreSQL 状态、migration 或 runtime；
- 安装 package，访问网络、数据库、容器、Backend、Frontend 或浏览器；
- 生成 snapshot、approval block、receipt、bundle、artifact、部署、UAT 或 AC evidence。

任何 source baseline、predecessor identity、CR-006-R4、CR-014-R3 或 dependency identity 漂移都立即 fail closed，并要求新的 successor；不得猜测修复。

## 8. Gate 顺序

1. `STATIC-DRAFT`：验证 predecessor raw/decision identities、本 addendum marker/bytes/hash、current manifest 与 accepted head；当前只允许停在此步。
2. `GOVERNANCE`：未来由 CR-014-R3 独立 review、生成 governance snapshot并取得其唯一 BOSS direct approval。
3. `SOURCE-A1`：CR-006-R4 与本 R3 分别生成 source snapshot；本 R3 只能由 `CR013_R3_SOURCE_A1` 精确批准完整 D/C/JS universe。
4. `BLOCKLIST-A2`：在 A1 后离线生成并独立验证 exact artifact，再由 `CR013_R3_BLOCKLIST_A2` 绑定；不得提前生成。
5. `PUBLISH`：bundle 与 `AUTH_OPLOG_JOINT_SYNC` 完成后才可执行唯一 cooperative eleven-file transition。
6. `IMPLEMENT`：只有 active Request/manifest/pre-meta 已闭合后，才可生成 migration、代码与 development/test evidence。

不得跳步；静态 draft、hash 或 review 都不是 approval。

## 9. predecessor-literal allowlist 与静态验收

旧 revision literal 只允许出现在以下位置：

- 文档类型声明及第 1 节不可变 predecessor path/revision/identity/effective-contract 表达式；
- 第 3～5 节 `predecessor 旧值` 列；
- 本节 allowlist 描述。

允许的旧 literal 集合恰为：

```text
CR-013-R2
CR-006-R3
CR-014-R2
CR006_R3_SOURCE_A1
CR013_R2_SOURCE_A1
CR013_R2_BLOCKLIST_A2
CR014_R2_AUTH_OPLOG_SHARED_TRANSITION_V1
20260807_008
20260811_009
20260811_010
```

其中 `20260811_010` 只在 predecessor 旧 auth candidate 或新 operation-log candidate 语境合法；不得成为 R3 auth `revision`。其余旧值不得成为 R3 active target、ordered source、approval kind 或 governance dependency。静态验收还必须证明文件为 UTF-8 no-BOM、LF-only，且 terminal lifecycle heading 前的 LF 是 decision-preimage 唯一切点；本文件 decision snapshot 当前不得生成。

## 10. 当前动态状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `APPROVED / SOURCE CONTRACT ONLY / RUNTIME NOT AUTHORIZED` |
| predecessor raw identity | `RECHECKED / PASS AT SOURCE SNAPSHOT GENERATION` |
| predecessor decision identity | `RECHECKED / PASS AT SOURCE SNAPSHOT GENERATION` |
| current accepted head | `20260807_009 / 18 TABLES / RECHECKED PASS` |
| R3 decision snapshot | `GENERATED / bytes=9496 / sha256=6cecc269e6517bb5b30d535350cdcb7e9aa2a00cf827199c2c2cb3789eae3d1a` |
| CR-014-R3 governance approval | `RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,a592ac07-5a2f-4dac-aae7-c960e9698fc3,item-572) / receipt_sha256=7421b7913ed31b12ba37da52f2a74d3ac28d7eab01bfeea0efc5bcde2c9bd08b` |
| CR013_R3 source A1 | `RECEIVED / VALID / event=(019fee83-e431-7a32-86ea-b1e043e641b8,019ff394-603b-7562-8f17-df808256e983,item-684) / platform=2026-08-12T01:26:55Z / consumed=2026-08-12T01:36:49.393901Z / source_text_sha256=572c102327f313c2a6e82ad582c4369f827e62c613c74ab14aecfe6b8971a37b / receipt=artifact://finaudit/auth-oplog-source-sync-v1/approval-receipts/CR013_R3_SOURCE_A1/046c93d2-d9f5-4270-b7d4-a94f51a2561a / receipt_bytes=2607 / receipt_sha256=1454233d212979663e26e2699b924689cb081e893b456daa30530e81a778b9c8` |
| CR013_R3 blocklist A2 | `NOT GENERATED / NOT RECEIVED` |
| Request/manifest/pre-meta | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT GENERATED / NOT AUTHORIZED / NOT RUN` |
| production/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
