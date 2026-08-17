# CR-014-R4：AUTH/Oplog approval transport-normalization successor addendum

> 文档类型：`CR-014-R3` 的最小 transport successor addendum  
> 修订：`CR-014-R4`  
> 日期：`2026-08-11`  
> 静态性质：versioned governance contract candidate；生命周期状态只记录在第 6 节  
> 唯一 delta：platform `userMessage` raw text 的 CRLF-to-LF canonicalization  
> 非目标：不修改 predecessor、Request、manifest、`approval_pre_meta.py`、代码或测试；不生成 approval、snapshot、receipt、artifact、bundle、post bytes 或 runtime evidence

## 1. 不可变 predecessor 与 effective contract

本文逐字绑定下列 current-checkout predecessor；其既有 governance snapshot 只作历史身份，不批准本文：

| 字段 | 固定值 |
| --- | --- |
| `base_document_path` | `docs/change-requests/CR-014-R3-auth-oplog-current-baseline-approval-sync-successor.md` |
| `base_revision` | `CR-014-R3` |
| `base_raw_bytes` | `13030` |
| `base_raw_sha256` | `e9a79705ef474c78a997616c5e66e30fd91cb0ddab514b217009a6b3e00f54e4` |
| `base_decision_preimage_bytes` | `11956` |
| `base_decision_preimage_sha256` | `e5c00e6e47081d0e7418b48957d7895fe5a4705a1d5008256a7bb291d15b7cd9` |
| `base_governance_snapshot_status` | `GENERATED / NOT APPROVED / NOT VALID FOR R4` |
| `successor_revision` | `CR-014-R4` |

`CR-014-R4 effective contract` 的唯一含义是：

```text
exact CR-014-R3 decision preimage
+ this document sections 1 through 5 addendum decision preimage
```

两份 preimage/hash 必须分别验证；不得拼接 bytes 后发明第三个 hash，也不得继承 predecessor 的动态状态。未被第 2～5 节明确覆盖的 R3 effective contract 原样继承；冲突时本文优先。本文生命周期 marker 固定为 `## 6. 当前状态`；未来 R4 snapshot 仍使用 R3 第 8.1 节算法，但只对本文 marker 前的 addendum decision preimage计算。该 snapshot 在 2/2 independent review 与 R3 第 2 节十一项 pre identity 同次重读全部通过前不得生成。

## 2. raw platform text 与 canonical text 唯一规则

R3 第 4.1～4.2 节只覆盖如下 lexical transport rule；sender、event ref、authority、消息闭形、字段语义和授权边界不变。

validator 必须按固定顺序执行：

1. 只从 `codex-thread-event-v1` 精确定位的 platform item取得 exact raw text bytes；拒绝 UTF-8 BOM、非法 UTF-8、解码替换字符和 NUL。
2. 任一不属于 CRLF pair 的 `0x0D` 为 lone CR，立即拒绝。
3. 定义 `canonical_text_bytes = raw_platform_text_bytes.replace(b"\r\n", b"\n")`。不允许 trim、Unicode normalization、Markdown rewrite、空白折叠、行重排或其他 byte 改写。
4. `canonical_text_bytes` 必须逐 byte 等于 R3 唯一闭形：开 fence 恰为 `````text\n``，随后恰十五行且每行末尾一个 LF，闭 fence 恰为 `````\n``，terminal LF 后无任何 byte。
5. 只从通过第 4 步的 canonical bytes解析十五行字段，再应用 R3 全部联合约束；规范化不能补造 fence、字段、行或 terminal LF。

因此 LF-only、全 CRLF，以及内部 CRLF但 closing-fence terminal newline 为 LF 的 raw transport都可得到同一合法 canonical text；任何其他 LF/CRLF混排也只有在第 1～5 步全部通过时才可能合格。不同 raw bytes即使 canonical text相同，也具有不同 raw identity。

`source_message_text_sha256` 的定义保持为：

```text
SHA256(exact raw_platform_text_bytes)
```

它不绑定 canonical bytes，也不包含 UI metadata。receipt 的该字段、platform event ref重读和后续 publisher重验都必须使用同一 raw hash；禁止用 canonical hash替换、双写或新增 receipt 字段。

## 3. 全量继承且不得改写的闭集

除第 2 节外，下列 R3 contract逐字继承：

- direct BOSS/YHBX platform `userMessage` authority、无 delegation要求，以及 `(thread_id,turn_id,user_message_item_id)` event ref；
- exact fifteen-line key order、RFC 8785 JCS lexical rules、nonce防重放、平台消息时间与消费时间均落入半开 `valid_utc` 的要求；
- 五种 approval kind/target revision组合、角色顺序、role decisions、selected decisions、scope、artifact kind/ref/hash binding；本文不创建 R4 kind、target或 decision alias；
- R3 ordered sources、migration chain、governance/source/A2/joint Gate顺序，以及 cooperative eleven-file publisher、recovery和 acceptance predicates；
- local receipt 恰二十键，`authority_class='NON_AUTHORITATIVE_EVIDENCE_ONLY'`，create-only、JCS、路径与 collision规则；receipt、截图、转述和本地文件仍无审批权；
- R3 第 2 节十一文件的 ordinal/path/raw identity；每次 review、snapshot、approval、staging或 publish前仍须 11/11重读，任一漂移即 `BLOCKED_BY_DRIFT`。

未来 R4 snapshot 只替换旧 R3 snapshot的可绑定 identity；R3 的 approval kind/target revision literals及其联合矩阵保持不变，`target_snapshot_sha256` 必须绑定经本节前置检查生成的 R4 snapshot，而不得复用 `e5c00e6e47081d0e7418b48957d7895fe5a4705a1d5008256a7bb291d15b7cd9`。R3 snapshot、旧消息、旧 receipt或自然语言确认都不能批准本文。

## 4. 已观察 platform item：只作失败证据

对当前 task 的只读 platform observation 为：

| 字段 | 观察值 |
| --- | --- |
| `thread_id` | `019fee83-e431-7a32-86ea-b1e043e641b8` |
| `turn_id` | `b9088310-db8a-4987-be42-adb2d3348a87` |
| `user_message_item_id` | `msg_019ff108-54e9-7320-9e35-407943f0cdf6` |
| platform classification | `type=message / role=user / input_text / no delegation metadata` |
| exact raw bytes | `1449` |
| exact raw SHA-256 | `ad193e294da2d60e3f90934166267e9ad84cde76a24571e167638658756db368` |
| newline inventory | `14 CRLF + 1 LF + 0 lone CR` |
| text fence count | `0` |

该 item不是 approval：CRLF替换后仍无唯一 `text` fence，不能通过第 2 节第 4 步。它携带的 nonce `2f66b905-82e3-46b4-8895-a0670e052e27` 未形成合格授权，但自本文起禁止复用；后续候选必须使用此前从未出现、未消费的新 lowercase canonical UUIDv4 nonce。上述 tuple/hash/newline inventory只证明一次失败输入的 byte identity，不是 receipt、sender签名、snapshot approval或 authorization。

## 5. 最低封闭验收

在生成任何 R4 snapshot前，除 R3 既有静态闭集外必须完成：

| 检查 | 必须结果 |
| --- | --- |
| LF-only 合格 fixture | canonical逐 byte等于 R3 closed shape；lexical PASS |
| 同内容全 CRLF fixture | canonical逐 byte同上；lexical PASS；raw hash与 LF-only fixture不同 |
| 同内容内部 CRLF + terminal LF fixture | canonical逐 byte同上；lexical PASS；raw hash与前两者不同 |
| lone CR、BOM、非法 UTF-8、NUL | 全部 FAIL |
| fence前/后额外 byte、额外空行、多 fence | 全部 FAIL |
| 行尾空格或任一字段/顺序/JSON变化 | 全部 FAIL |
| 第 4 节无 fence item或其旧 nonce复用 | 全部 FAIL |
| independent review | `2/2 PASS / NO CRITICAL-HIGH-MEDIUM FINDINGS` |
| predecessor identities | R3 raw/decision `2/2`重算全等；R3三 predecessor identities按 R3规则重读全等 |
| eleven-file pre identities | 同一 Gate 内 `11/11`逐项重读全等 |

正向 fixture只验证无状态 lexical canonicalization；真实 authority仍须独立满足唯一 event、未消费 nonce、有效期及全部 R3 Gate。任何失败继续使用 R3 inherited `NOT APPROVED/NOT_AUTHORIZED`或对应既有 safe code；本文不增加授权分支或失败码。

## 6. 当前状态

| 项目 | 当前状态 |
| --- | --- |
| 文档 | `WITHDRAWN / NOT APPROVABLE / SUPERSEDED BY VALID CR-014-R3 GOVERNANCE APPROVAL` |
| independent reviews | `0/2 / NOT RUN` |
| R3 raw/decision identity | `2/2 RECHECKED / PASS AT DRAFT CREATION` |
| R3 predecessor identities | `NOT RECHECKED / REQUIRED BEFORE SNAPSHOT` |
| eleven-file pre identity | `NOT RECHECKED / REQUIRED BEFORE SNAPSHOT AND EVERY LATER GATE` |
| CR-014-R4 snapshot | `NOT GENERATED / RETIRED BEFORE SNAPSHOT` |
| governance/source/A2/joint approvals | `NOT APPLICABLE / MUST USE ACTIVE CR-014-R3 LINEAGE` |
| receipt/artifact/bundle/post/inverse | `NOT GENERATED / NOT AUTHORIZED` |
| Request/manifest/pre-meta | `NOT CHANGED / NOT AUTHORIZED` |
| migration/code/test/runtime | `NOT CHANGED / NOT AUTHORIZED / NOT RUN` |
| production/UAT/AC | `NOT AUTHORIZED / NOT RUN` |
