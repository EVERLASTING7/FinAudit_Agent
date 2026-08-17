# CR-013-R4：system_admin AUTH/user-list source transport successor addendum

> 文档类型：`CR-013-R3` 的最小 transport-lineage successor addendum  
> 修订：`CR-013-R4`  
> 日期：`2026-08-11`  
> 静态性质：versioned source contract candidate；生命周期状态只记录在末节  
> 唯一 delta：对齐 `CR-014-R4` transport governance 与同批 source successor revision  
> 非目标：不修改 predecessor、Request、manifest、migration、代码、测试或证据；不生成 snapshot、approval、blocklist、receipt、artifact、bundle 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-013-R3-auth-system-admin-user-list-slice-successor.md` |
| `base_revision` | `CR-013-R3` |
| `base_raw_bytes` | `10213` |
| `base_raw_sha256` | `f7ebfd746ce065c0ee69a024eaa786ad24c924005d82c4cdcf19fd1742554ac0` |
| `base_decision_preimage_bytes` | `9497` |
| `base_decision_preimage_sha256` | `dd8f58fcc09bd3dc526ef5c4ddaa10374ddae148952e183f876ef2c9ccefa4b8` |
| `successor_revision` | `CR-013-R4` |

`CR-013-R4 effective contract` 仅表示 exact `CR-013-R3` decision preimage 加本文第 1～6 节 decision preimage。两份身份必须分别验证；不拼接生成第三个 hash，不继承 predecessor 动态状态。除第 2 节明确覆盖项外，predecessor effective contract 全量继承；冲突时本文优先。

## 2. 唯一 revision-bearing delta

| 字段 | predecessor 值 | R4 active candidate 值 |
| --- | --- | --- |
| governance owner | `CR-014-R3` | `CR-014-R4` |
| operation-log companion | `CR-006-R4` | `CR-006-R5` |
| ordered source set | `[CR-006-R4,CR-013-R3]` | `[CR-006-R5,CR-013-R4]` |
| shared transition choice | `AUTHSLICE-C-007=CR014_R3_AUTH_OPLOG_SHARED_TRANSITION_V1` | `AUTHSLICE-C-007=CR014_R4_AUTH_OPLOG_SHARED_TRANSITION_V1` |
| source A1 approval kind | `CR013_R3_SOURCE_A1` | `CR013_R4_SOURCE_A1` |
| blocklist A2 approval kind | `CR013_R3_BLOCKLIST_A2` | `CR013_R4_BLOCKLIST_A2` |

`CR-006-R5` 在本文只作为 revision companion，不绑定其尚未冻结的 raw 或 preimage hash。最终必须由 `CR-014-R4` 在同一冻结 Gate 同时绑定本文件与 `CR-006-R5` 的 exact decision preimages；任一漂移均整体 fail closed。禁止用交叉 raw-hash 引用制造循环。

## 3. substantive、migration、D/C/JS 与 A2 语义零变化

- `AUTHSLICE-D-001～D-008`、`AUTHSLICE-C-001～C-008`、`AUTHSLICE-JS-001～JS-009` 的名称、顺序与 exact values 全部继承，唯有第 2 节明确列出的 revision-bearing C-007 value 替换。
- password/login、JWT/refresh、session family、one-time password-change token、bootstrap/browser custody、`users:manage`、AUTH-007 read model、安全、atomicity、API error 与 dependency Gate 全部继承。
- blocklist A2 仍只绑定 predecessor 定义的 exact 四角色 artifact；payload、生成、校验、审批顺序与不可提前生成语义不变。
- migration 仍且仅为 `backend/alembic/versions/20260811_011_extend_auth_session_family.py`，`revision=20260811_011`、`down_revision=20260811_010`；本文不创建、改名、重排或授权 migration。
- 既定最短业务链、DTO、API/UI delta、物理计数、Request projection 与所有 production 禁止边界不变。

## 4. Gate 与授权顺序

1. `STATIC-DRAFT`：复算 predecessor identities、本文 marker/preimage、编码与 current baseline；当前只允许停在此步。
2. `GOVERNANCE`：由 `CR-014-R4` 完成独立 review、snapshot 与有效 BOSS direct approval。
3. `SOURCE-A1`：生成本 R4 source snapshot，并仅由 `CR013_R4_SOURCE_A1` 按原顺序批准完整 D/C/JS universe。
4. `BLOCKLIST-A2`：A1 后才可生成 exact artifact，并仅由 `CR013_R4_BLOCKLIST_A2` 绑定；不得提前生成。
5. `PUBLISH`：等待 `CR-006-R5` A1、joint authorization 与 cooperative transition，禁止单 source publish。
6. `IMPLEMENT`：只有 Request/manifest/pre-meta 已共同闭合后，才允许 migration、代码与 local/test evidence。

静态 draft、revision 名、hash 或 review 均不是 approval；不得跳步。

## 5. 非继承、禁止事项与停止条件

predecessor 的 lifecycle、Gate、snapshot、approval/message、receipt、role record、blocklist payload/artifact、bundle、joint authorization、publish、migration/runtime/AC evidence 一律不继承。本文不授权修改既有文件、Request、manifest、pre-meta、migration、代码、测试或数据库，也不授权创建账号、Token、keyring、服务、网络、部署、UAT 或 AC。predecessor、companion、governance owner、accepted head 或 baseline 任一漂移即停止并升新 revision。

## 6. 静态验收

- 文件必须为 UTF-8 no-BOM、LF-only，并以唯一 terminal lifecycle heading 前的 byte offset 作为 decision-preimage 切点。
- predecessor raw 与 decision identities 必须复算全等；本文件 raw、preimage、行数与 SHA-256 必须冻结后再供 review。
- active references 必须只使用 `CR-013-R4`、`CR-006-R5`、`CR-014-R4`、R4 A1/A2 kinds 与 `CR014_R4_AUTH_OPLOG_SHARED_TRANSITION_V1`；旧值只允许作为 predecessor/delta 证据。
- 本文件与 companion 不互绑未冻结 hash；`CR-014-R4` 必须在同一 Gate 同时绑定两者 preimages。

## 7. 当前动态状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `WITHDRAWN / NOT APPROVABLE / ACTIVE SOURCE REMAINS CR-013-R3` |
| predecessor raw/decision identities | `RECHECKED / PASS AT DRAFT CREATION` |
| R4 decision snapshot | `NOT GENERATED / RETIRED BEFORE SNAPSHOT` |
| CR-014-R4 governance approval | `NOT APPLICABLE / CR-014-R4 WITHDRAWN` |
| CR013_R4 source A1 / blocklist A2 | `NOT APPLICABLE / MUST USE CR013_R3_SOURCE_A1 AND CR013_R3_BLOCKLIST_A2` |
| Request/manifest/pre-meta | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT GENERATED / NOT AUTHORIZED / NOT RUN` |
| production/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
