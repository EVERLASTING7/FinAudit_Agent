# CR-011-R4：AI Policy active-baseline governance successor

> 文档类型：`CR-011-R3` 的治理型 successor addendum  
> 修订：`CR-011-R4`  
> 日期：2026-08-09  
> 静态性质：versioned contract candidate；生命周期状态只记录在第 9 节  
> 非目标：不改写 `AI-D-009`～`AI-D-014`，不修改 R3 机器制品，不授权持久化 AI runtime、Provider 网络、真实数据、部署或 production

对应差异：GAP-057～GAP-062

## 1. R3 不可变基座与 R4 effective contract

### 1.1 R3 规范基座

R4 只在下列不可变 R3 decision snapshot 与 artifact manifest 上生效：

| 字段 | 固定值 |
|---|---|
| `base_document_path` | `docs/change-requests/CR-011-ai-policy-transport-implementability-closure.md` |
| `base_revision` | `CR-011-R3` |
| `base_status_at_successor_creation` | `DRAFT / PROPOSED / NOT APPROVED` |
| `base_status_marker` | exact whole line `## 8. 当前状态` |
| `base_decision_preimage_bytes` | `26563` |
| `base_decision_snapshot_sha256` | `b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` |
| `artifact_manifest_path` | `docs/change-requests/artifacts/CR-011/manifest.json` |
| `artifact_manifest_raw_bytes` | `5128` |
| `artifact_manifest_sha256` | `f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` |
| `policy_version` | `1` |

创建 R4 时观测到的 R3 全文件 raw identity 为 `27376/e89320fc4eed9bfa51b289fc8decc9b344bc78cf0391c0bc22bf9156a563db7f`。该值包含 R3 第 8 节可变生命周期状态，只是来源复核证据，不是 R4 的持续规范前置；R4 的规范 base 只绑定上表 decision preimage 与 artifact manifest。

`CR-011-R4 effective contract` 的唯一含义是：

```text
exact CR-011-R3 decision snapshot
+ exact CR-011-R3 artifact manifest and its 15 leaf artifacts
+ this document sections 1 through 8 governance addendum
```

R4 不复制、不改写也不重新解释 R3 第 3 节的 `AI-D-009`～`AI-D-014`。R3 规范语义和机器制品保持 byte-for-byte 不变；R4 只补足 active-baseline 绑定、九角色审批、十一文件同步、分层实施授权和生命周期证据。语义审查必须同时核对 R3 decision snapshot、artifact manifest 和本 R4 snapshot，不得拼接 bytes 后生成未定义的第三个 hash。

### 1.2 决策全集与无语义 delta

R4 不新增 `AI-D-*` 决策，也不创建 alias。审批只能原子选择以下六项，顺序固定：

```text
AI-D-009
AI-D-010
AI-D-011
AI-D-012
AI-D-013
AI-D-014
```

- `APPROVED` 时，`selected_decisions` 必须逐字等于上述六项，`rejected_decisions` 必须为空。
- `REJECTED` 时，两数组必须无重复、互斥并精确分区上述全集，且 `rejected_decisions` 非空；数组保持声明顺序。
- 缺项、额外项、乱序、别名、条件互相冲突或只批准 Policy 不批准 Event/Sink 合同，均不构成有效批准。

累计产品与架构 delta 固定为零：

| 项目 | R4 delta |
|---|---:|
| API path | `0` |
| HTTP API error code | `0` |
| 核心物理表 | `0` |
| UI page / route | `0` |
| P0 work item | `0` |
| operation log action | `0` |
| R3 artifact bytes | `0` |
| Provider/network authorization | `0` |

## 2. CR-004 effective identity 与兼容性绑定

CR-004-R2 已批准并同步，而且其 `REL-D-004` 明确把本 CR 的 sequence 3、Sink 和后续投影作为独立依赖。R4 因此同时绑定以下 R1/R2 effective identity：

| 字段 | 固定值 |
|---|---|
| `cr004_base_document_path` | `docs/change-requests/CR-004-reliability-contract-closure.md` |
| `cr004_base_revision` | `CR-004-R1` |
| `cr004_base_raw_bytes_at_binding` | `41523` |
| `cr004_base_decision_preimage_bytes` | `40544` |
| `cr004_base_decision_snapshot_sha256` | `387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6` |
| `cr004_successor_document_path` | `docs/change-requests/CR-004-R2-reliability-contract-closure.md` |
| `cr004_successor_revision` | `CR-004-R2` |
| `cr004_successor_decision_preimage_bytes` | `39646` |
| `cr004_successor_decision_snapshot_sha256` | `77a8a2e63a4668a5e7e6a028b18cc04f34ddc824d04096db8bede7bce844241b` |
| `cr004_approval_record` | `APR-20260809-YHBX-CR004R2` |
| `cr004_contract_status` | `APPROVED / REQUEST SYNCHRONIZED / 007 CONTRACT-OFFLINE SLICE VERIFIED` |

CR-004-R2 第 3.7 节已经逐字绑定本 R3 decision snapshot 和 artifact manifest。R4 不改变 sequence 3 字段、状态、幂等 identity、late-completion 或 Sink 语义，因此不触发 CR-004 升版；它只把同一候选合同接入新的 active baseline。若审查发现 R4 与任一 R1/R2 规范条款不兼容，R4 必须保持 `NOT APPROVED`，并分别提升受影响的 CR revision，不能以 R4 单方面覆盖 CR-004。

批准 R4 不授权 CR-004 的 Repository、Dispatcher、Worker、Outbox、reaper、Redis/Broker 或生产 Handler runtime。CR-004 的空表 DDL/ORM 证据也不能冒充本 CR 的 Sink 行为或 AI-005 持久化证据。

## 3. R3-origin 机器制品的原样采纳

### 3.1 不可变制品集合

R4 原样采纳 R3 `manifest.json` 及其精确列出的 15 个 leaf JSON。审批前必须重新证明：

1. `manifest.json` raw identity 精确为 `5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c`。
2. manifest 恰好列出 15 个不同的相对文件路径，不包含自身，不缺项、不多项。
3. 每个 leaf 的 raw byte length 和 SHA-256 与 manifest 逐项一致。
4. `docs/change-requests/artifacts/CR-011/` 除 manifest 与这 15 个 leaf 外没有被当作本合同机器制品消费的额外文件。
5. Policy 完整验证仍由 Draft 2020-12 Schema 与全部 companion rules 按固定顺序共同组成；单独 JSON 解析、单独 Schema PASS 或单独 hash PASS 都不是完整验证。

manifest 的 `artifact_set="CR-011-R3-contract-offline-draft"` 以及 Schema description 中的 `CR-011 draft machine contract` 是 R3-origin 不可变 provenance。R4 为保持 artifact hash 原样而保留这些字样；它们不代表 R4 的动态生命周期状态。只有本 R4 获得有效九角色批准后，这组 R3-origin candidate bytes 才通过 R4 的原样采纳成为 active contract 制品。

### 3.2 漂移规则

- R4 不授权修改 R3 文档第 1～7 节、`manifest.json` 或任一 leaf artifact。
- 任一制品 byte、文件集合、Schema、companion rule、固定向量、Policy/Event 字段或 `AI-D-009`～`AI-D-014` 语义变化，都必须提升至少 `CR-011-R5`，生成新的 decision snapshot 与 artifact manifest hash，并重置全部签署。
- R3 第 8 节生命周期状态可以保留其历史记录，但不得用动态状态覆盖、撤销或暗改 R3 decision snapshot。
- R4 的批准记录必须同时绑定 R3 snapshot、artifact manifest、CR-004 R1/R2 tuple 和 R4 snapshot；只写 `CR-011 approved` 不构成可验证事实。

## 4. 批准后的分层授权与非授权边界

### 4.1 批准并完成十一文件同步后可执行的范围

只有第 6 节九角色批准有效且第 5 节十一文件原子同步完成后，才授权以下 `BASE-004 contract/offline` 最小切片：

- 消费既有 `ai-policy-v1.schema.json` 与 `ai-policy-v1.companion-validator.json` 的严格 Schema/companion 组合验证；
- 严格 raw JSON parser、重复 key 与整数词法门禁、RFC 8785 JCS pre-hash/hash 校验、封闭字段和数组规范顺序检查；
- operation/Profile 引用图、capability、network scope、hostname/CIDR registry 的纯 resolver 与 fail-closed 校验；Resolver/peer 输入只允许注入的合成集合；
- retry/deadline/`Retry-After`、header/body/gzip 和成功/失败响应的纯 parser/算法证据，时钟、随机源和 bytes 都由测试注入，不真实 sleep；
- `AiCallEventV1` started/completed/late 的版本化 DTO、严格构造、JCS 序列化、hash 投影和固定向量验证；
- 零 socket（包括数值 loopback、hostname/DNS、Unix domain/其他本地 socket）、无数据库、无 Redis/Broker 的 Fake/in-memory `AiCallEventSink` Port 行为证据，覆盖 R3 冻结的 reserve 六结果、complete 六结果、故障窗口、相同重放/冲突、`SendPermit` 与 `AdoptPermit` 单次消费；
- 对上述切片的单元、性质、固定向量和离线集成测试，以及不读取真实 `.env`、secret 或业务正文的本地验证。

允许的 Fake/in-memory Sink 只用于证明 Port 调用顺序、结果处理和 fail-closed 行为。它不得声明 durable、transactional、exactly-once、Outbox-backed 或 restart-safe，也不得接入真实 HTTP Transport、业务结果采用链或非测试 Settings。

Gate B 通过不自动决定 `BASE-004` 完成。通过后必须按正式 `BASE-004` Definition of Done 逐项复核：全部条目及其要求的证据都满足时才可记为 `implemented`；否则保持 `partial`，并逐项列出仍缺的 DoD 与证据。`AI-001` 仍保持 `partial`。任何一种状态都不能据此宣称 `AI-005`、`BASE-005/006`、P0、任一 AC、Provider、性能、费用、部署或 production 完成。

### 4.2 始终不由 R4 授权的范围

以下内容保持 `PENDING / NOT AUTHORIZED`：

- AI-005 数据库表、migration、Repository、durable reserve/complete、`ai_call_logs` 投影、Outbox、late reconciler、Worker、Job 或 operation-log runtime；
- 生产 `AiCallEventSink` adapter、持久事务、跨进程/重启恢复、真实 permit 发放或业务结果采用；
- Redis 熔断/限流、Broker、Celery、DNS、TLS、socket、真实 HTTP Transport 或任何 Provider/其他外网请求；
- `fixed_test_provider`、内部 vLLM、真实 Chat/Embedding、真实 Profile/endpoints/model/Tokenizer/pricing/quota/CIDR/capacity；
- secret slot 的值、真实 `.env`、Token、API Key、密码、私钥、生产配置或真实业务数据；
- API route、UI page、数据库 Schema、核心表数量、P0 work item 或 operation action 的新增；
- Docker/Compose 运行时、云资源、部署、canary、production migration、production 放行、提交、推送或 PR。

`AI_PROVIDER_CALLS_ENABLED` 必须继续为 `false`。第 7.2 节 contract/offline Gate 未通过前，任何 HTTP send 或业务结果采用都必须失败关闭；即使该 Gate 通过，Provider/network 仍须另行环境审批，不能由 R4 自动开启。

## 5. 九份 Request、正式 manifest 与 active-baseline pin 的十一文件原子同步

### 5.1 精确目标与 pre identities

批准后的同步目标必须恰为：

1. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
2. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
5. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
7. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
8. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
9. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
10. `docs/baseline-manifest.md`
11. `backend/app/approval_pre_meta.py`

九份 Request 的 pre-sync raw identity 固定如下；hash 使用小写列示，比较 manifest 的显示值时必须严格解码为 32 bytes，不能以十六进制大小写差异制造假冲突：

| Request path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 127311 | `28f71bde8257c99af4be8f6bee7414d3f147258949795348572422ae6715ab88` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 88992 | `ff3a3a66dae560009e2ae35af677f6b6b71ff4f4c1a5359352d51b7886903214` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 114800 | `5b7783fe1230d9c1e3df3a5cd27ca325a4e79850d65c20b957aca902baeba56f` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 327158 | `1a00bf91e7c3c543685db815054dbbc9558b9277962b52fd61ac2609eab103b2` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 82514 | `5964160ee0d4e814c2dc92c00ae1c8b48d70864504502c6dbb9b966e578ecc40` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 50039 | `7e8dbdff494815e61f6d0fe48a7787bd9aa9046ce99f8b028cfbc59e5483ffb0` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 48590 | `f0d1ce76986df85405984d2b3a6ce3fb99c6963b46c8c9bd7b9d92d51ef3466e` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 53183 | `0f223f98c8a674905a40650b394fd704828491d8b47c5957e385509d1cd91108` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 105222 | `9bf8b51593260ddbabe9f7557fc9726fb11331d9feda250a4f52042ed73b00a0` |

同步配套文件 pre identity 固定为：

```text
path=docs/baseline-manifest.md
raw_bytes=1633
raw_sha256=d833c568277fae4f3b74f520acb31dfd58d8caaafad67fdaee1b1d54740d08b7

path=backend/app/approval_pre_meta.py
raw_bytes=22193
raw_sha256=f76f5f59f99a95d088990820fdd1b50124e6caa24bcfaa12dfe0946a947a99fd
allowed_change=_BASELINE_IDENTITY.byte_length|_BASELINE_IDENTITY.sha256
```

`approval_pre_meta.py` 当前 `_BASELINE_IDENTITY` 必须精确为 manifest 的 `1_633/d833c568277fae4f3b74f520acb31dfd58d8caaafad67fdaee1b1d54740d08b7`。本 CR 只允许把该对象的 `byte_length` 与 `sha256` 两个 literal 替换为 post-sync manifest identity；不得修改路径、`_SCHEMA_IDENTITIES`、`_SNAPSHOT_IDENTITIES`、数量、角色/fact-set、解析/批准逻辑或 CLI 的 `OUT_OF_SCOPE_NOT_EVALUATED/NOT_AUTHORIZED` 输出。`backend/tests/unit/test_approval_pre_meta.py` 不修改。

### 5.2 领域投影

九份 Request 只同步 R3 已冻结语义、R4 治理和本 CR 授权边界：

- 需求：记录 `AI-D-009`～`AI-D-014` 原子生效、Provider 默认关闭和 contract/offline 范围；不增加 P0 交付项。
- 架构：同步 Policy/companion/parser/resolver/Event DTO/Sink Port 分层、依赖注入和 Fake/in-memory 边界；不引入数据库或网络 runtime。
- 数据库：只同步 `AiCallEventV1` 与未来 AI-005 投影兼容关系及“本轮不建表”；不得增加表、列、约束、migration 或 seed。
- API：只同步内部 DTO/Port 与既有错误分类的兼容说明；不新增 route、状态码或客户端可调用 Provider 能力。
- 页面：明确页面/路由 delta 为零，前端不得读取 Policy secret、直连 Provider 或从离线制品推断运行状态。
- AI/RAG：完整引用 R3 snapshot、R3-origin manifest 和 `AI-D-009`～`AI-D-014`；不得复制出漂移的第二套算法或字段合同。
- 测试：把审批前静态 Gate、批准后 contract/offline Gate 和未来 persistent/runtime Gate 分开；Mock/Fake 证据不得冒充真实 Provider 或 durability。
- 部署：同步 `AI_PROVIDER_CALLS_ENABLED=false`、缺失/漂移 fail-closed 与全部环境非授权边界；不写真实 endpoint、CIDR、secret 或 production 值。
- 计划：记录获批后的 `BASE-004/AI-001` contract/offline 切片和 Gate B 证据；`BASE-004` 按正式 DoD 逐项裁定为 `implemented` 或带缺项的 `partial`，`AI-001` 仍为 `partial`；AI-005、BASE-005/006 与业务 E2E 继续独立阻塞。

每份 Request 只保留一条 `CR-011-R4 / approved contract scope` 修订记录，不得写入该文件自身的 post length/hash。具体批准日期、R4 decision snapshot 和 R3 artifact manifest identity 可以写入修订记录或共同基线说明，但不得引入任何 downstream post identity。

### 5.3 无环生成 DAG 与原子验收

生成顺序固定为：

```text
R3 snapshot + R3 artifact manifest + CR-004 R1/R2 tuple
                    |
R4 sections 1-8 snapshot + valid nine-role approval
                    v
          nine Request post bytes
                    v
       nine Request post identities
                    v
        baseline-manifest post bytes
                    v
        baseline-manifest post identity
                    v
approval_pre_meta._BASELINE_IDENTITY two-literal re-pin
                    v
R4 section 9 external post-sync evidence
```

该 DAG 必须保持无自引用：Request 不包含自身 post identity；baseline manifest 可且只可记录九份 Request post identities，不记录自身 identity；唯一跨出 manifest 的消费例外是 `approval_pre_meta.py::_BASELINE_IDENTITY` 两个 literal 可以消费已经生成的 manifest post identity。九份 Request post identities 除进入上述 manifest 九项表外，只能进入第 9 节动态状态和外部跟踪证据；manifest post identity 除该两-literal re-pin 例外外，只能进入第 9 节和外部证据；re-pin 源文件自身的 post raw identity 也只能进入第 9 节和外部证据。R4 第 1～8 节不包含 R4 自身 snapshot 或任何 post-sync identity。

实现必须先在临时区生成并验证全部 post bytes，再一次性替换 11 个目标。九份 Request、manifest 与 re-pin 必须全有或全无地生效。任一 pre identity、领域投影、R3/artifact/CR-004 binding、post hash、manifest 条目、两-literal diff、UTF-8/LF 门禁或测试失败，都必须回滚整个十一文件集合，不得留下部分 active baseline。

post-sync manifest 必须仍恰好列出九份 Request，并明确已同步 `CR-011-R4`；不得把 manifest 自身、R4 文件、R3 artifacts 或 `approval_pre_meta.py` 加入九项表。manifest 与 re-pin 的 post raw identities只能记录在第 9 节动态区和外部证据，不得自嵌。

## 6. 九角色审批边界与记录格式

本 CR 必须由以下九角色共同批准；一人具备多个角色权限时可以合并一条记录，但必须逐项列明全部角色：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | 六项决策原子生效、用户影响、P0 delta 为零与九份 Request 同步 |
| 架构 | R3/R4 effective contract、Policy/Event/Sink Port 分层、CR-004 兼容和依赖边界 |
| 数据/DBA | AI-005 投影兼容、零数据库 delta 与持久 runtime 非授权 |
| 后端/API | parser/resolver/Event DTO/Fake Sink 范围、无 API delta 与业务采用门禁 |
| 前端/UI | 页面/路由 delta 为零、前端不直连 Provider、不消费 secret 或推断 runtime |
| AI/RAG | `AI-D-009`～`AI-D-014`、R3-origin artifacts 和真实 Provider 非授权 |
| 测试/质量 | 三层 Gate、十一文件原子同步、固定向量、故障窗口和证据边界 |
| 运维/可靠性 | deadline/retry、Sink 故障语义、Provider 关闭、部署/恢复非授权 |
| 安全 | secret、出站、Parser/Resolver、脱敏、permit 和真实环境边界 |

每条审批记录必须包含：

```text
姓名
角色
decision=APPROVED|REJECTED
selected_option=AI-D-009～AI-D-014_R3_EXACT_CONTRACT_WITH_R4_ACTIVE_BASELINE_GOVERNANCE
selected_decisions
rejected_decisions
cr_revision=CR-011-R4
base_revision=CR-011-R3
base_decision_preimage_bytes=26563
base_decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be
artifact_manifest_raw_bytes=5128
artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c
cr004_base_revision=CR-004-R1
cr004_base_decision_snapshot_sha256=387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6
cr004_successor_revision=CR-004-R2
cr004_successor_decision_snapshot_sha256=77a8a2e63a4668a5e7e6a028b18cc04f34ddc824d04096db8bede7bce844241b
decision_snapshot_sha256
environment_scope=contract
policy_version=1
baseline_manifest_pre_raw_bytes=1633
baseline_manifest_pre_raw_sha256=d833c568277fae4f3b74f520acb31dfd58d8caaafad67fdaee1b1d54740d08b7
approval_pre_meta_pre_raw_bytes=22193
approval_pre_meta_pre_raw_sha256=f76f5f59f99a95d088990820fdd1b50124e6caa24bcfaa12dfe0946a947a99fd
approval_pre_meta_repin_scope=_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY
authorized_scope=exact_nine_request_plus_baseline_manifest_sync|approval_pre_meta_active_baseline_identity_repin_only|base004_contract_offline_schema_companion_parser_resolver_event_dto_in_memory_sink_behavior_evidence
日期
证据链接
备注
```

有效 `APPROVED` 记录的 `selected_decisions` 必须为 `[AI-D-009,AI-D-010,AI-D-011,AI-D-012,AI-D-013,AI-D-014]`，`rejected_decisions=[]`。任一角色缺失、拒绝、使用不同 snapshot/artifact/baseline/CR-004 identity、把 `environment_scope` 扩大到网络或 production，或备注与 `authorized_scope` 冲突时，整体保持 `NOT APPROVED`。

批准只可授权第 5 节十一文件原子同步，以及第 4.1 节 contract/offline 最小切片。它不授权第 4.2 节任何持久化、网络、真实数据、部署或 production 行为。

## 7. 三层验收 Gate

### 7.1 Gate A：审批前静态可签署性

Gate A 必须在任何签署前通过：

- 按 R3 exact whole-line marker 机械复算 `26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be`；R3 动态状态不替代该 snapshot。
- 验证 artifact manifest `5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` 和全部 15 个 leaf identity，确认零修改、零缺项、零额外消费。
- 对 manifest 与 15 个 leaf 执行严格 UTF-8/无 BOM/重复 key 拒绝的只读 JSON 解析；JSON 文件、路径、声明类型和引用目标必须完整且唯一。
- 用 Draft 2020-12 meta-schema 静态检查两个 Schema，解析全部本地 `$ref`，核对封闭 object、discriminator/conditional、required/nullability 与 companion validator 声明的固定执行顺序和 rule/fixture 引用完整性；本项只检查声明，不执行完整运行时语义。
- 对照既有 positive、prehash JCS、negative-vector 清单和 manifest 的固定结构及 identity；机械核对删除顶层 `policy_hash` 后的既有 JCS/prehash/hash 链接，不把该结构对照表述为两套独立实现或全部负向行为已通过。
- 对照 `AiCallEventV1` Schema 与固定 started/completed/late vectors 的 event type、sequence、required key、conditional 分支和显式 nullability 结构；静态 vectors 不冒充 DTO、JCS 或 Sink 状态机行为证据。
- 机械复算 CR-004 R1/R2 两个 decision snapshot，确认 R2 已批准记录绑定同一 R3 snapshot/manifest，且 R4 没有 `AI-D-*` 或 sequence 3 语义 delta。
- 验证九份 Request、baseline manifest 和 approval pre-meta 全部 pre identity，确认当前 pin 指向当前 manifest。
- 机械扫描 R4 不包含真实 endpoint、secret、生产 CIDR、真实 Profile、网络放行、数据库/Outbox runtime 或部署授权。
- 按第 8 节生成并独立复算 R4 decision snapshot；snapshot 生成只建立可签署对象，不等于批准。

Gate A 不要求两套独立实现执行完整 Schema+companion 语义，不要求运行全部负向向量，也不要求 DTO/JCS、parser/resolver 或 Fake Sink 六加六行为证据。它不授权同步 Request 或实现代码，只证明候选合同和静态制品声明完整、身份一致、可以进入九角色审批。

### 7.2 Gate B：批准并同步后的 contract/offline 实施

只有有效九角色批准和十一文件同步全部完成后，才运行 Gate B：

- 两个独立实现按 Draft 2020-12 Schema 加全部 companion rules 的固定顺序验证同一完整正向 Policy，得到相同 pre-hash bytes/hash，并使 R3 固定的全部负向向量按其 expected stage/rule/code fail closed。
- Schema 与 companion validator 在应用入口组合执行；原始 JSON 词法、重复 key、JCS/hash、数组与引用图全部 fail closed。
- parser/resolver/retry/response/gzip/network-policy 算法使用固定和性质向量；时钟、随机源、DNS 结果与 peer 全部作为纯值注入，不调用系统 resolver，不打开任何 socket、不 sleep、不读取真实 `.env`。
- Event DTO/JCS 覆盖 started、五类 completed、late、数值边界、nullability、重复/冲突和 hash 投影。
- Fake/in-memory Sink 分别覆盖 `reserve_attempt` 六种结果、`complete_attempt` 六种结果、commit-before-return、return-before-call-site、crash-before-send、crash-after-send、同 payload replay、不同 payload conflict、unknown、single-use `SendPermit` 和 single-use `AdoptPermit`。
- Fake Gate 必须证明 conflict/unknown/replayed-after-restart 不发送，`outcome_unknown` 不自动重放，late 不产生 AdoptPermit，已消费 permit 不能复用。
- 测试、异常、日志、Trace、指标和报告不出现 secret 或业务正文 sentinel；网络门禁必须证明整个 Gate B 零 socket，包括数值 loopback、`localhost`/其他 hostname DNS、Unix domain/其他本地 socket，并且不启动、不连接也不依赖任何本地或远程服务。

Gate B PASS 只证明纯算法、DTO 和 Port 合同；它不证明 durability、数据库原子性、Outbox、Worker、真实 HTTP、Provider 响应、费用、性能或业务采用。Gate B 未通过前禁止任何 HTTP send 或业务结果采用；Gate B 通过后仍必须等待独立 Provider/环境/runtime 授权。

### 7.3 Gate C：未来 persistent AI-005/runtime

Gate C 继续 `PENDING / NOT AUTHORIZED`，至少包括：

- BASE-005/006 对应表、migration、约束、事务、锁序、Outbox、Job/Worker 与恢复链；
- durable reserve/complete、commit unknown 查询、跨进程 permit 安全、late reconciliation 与 `ai_call_logs` 投影；
- Redis 熔断/限流、Broker、真实 HTTP Transport、DNS/TLS/peer 绑定、Provider error/usage 对账；
- fixed-test/production Profile 环境签署、secret provisioning、费用与容量门禁、canary、部署和 production。

Gate C 必须由后续获批的 BASE-005/006、AI-005、Provider 环境和部署合同共同授权。不得从 Gate A/B 或 R4 的 contract scope 推导其已获批。

## 8. R4 decision snapshot 算法与生命周期

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次；不得用普通 substring search 命中正文代码或反引号中的相同文本。
4. preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256 小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定第 1 节 R3 base snapshot/artifact manifest、第 2 节 CR-004 R1/R2 tuple 和第 5.1 节 active-baseline pre identities。
7. R4 decision snapshot 不包含自身 hash 或任何 post-sync identity；九份 Request post identities、manifest post identity、re-pin 源文件自身 post raw identity 的合法落点严格遵循 §5.3 DAG 与唯一例外，均不得进入 R4 decision snapshot，因此无自引用。
8. 在首条有效 approval record、Request sync authorization 或下游消费证据产生前，第 1～8 节可在 `CR-011-R4` review 阶段修订，但每次都必须撤回旧 unsigned hash、重算并全量复审。任一前述事实产生后，第 1～8 节任何 byte 变化必须提升 `CR-011-R5` 并重置签署。
9. 第 9 节动态状态更新不改变 R4 decision snapshot；不得把动态状态反向解释为规范条款。
10. 生成 snapshot 只建立可签署对象，不等于批准。在有效九角色审批前，不得同步十一文件或实施第 4.1 节切片。

## 9. 当前状态

本节位于 decision snapshot 之外，只记录生命周期和证据；不得用于覆盖第 1～8 节。

| 项目 | 状态 |
|---|---|
| CR revision | `CR-011-R4；APPROVED / ACTIVE CONTRACT` |
| R3 decision base | `VERIFIED；26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` |
| R3-origin artifact manifest | `VERIFIED IDENTITY；5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c；BYTE-REUSED / ADOPTED BY APPROVED R4` |
| `AI-D-009`～`AI-D-014` semantic delta | `ZERO` |
| CR-004 compatibility | `R1/R2 TUPLE BOUND；NO REL-D-004 OR SEQUENCE-3 DELTA` |
| 批准 / 同步日期 | `2026-08-09` |
| 必需角色审批 | `9/9；INDEPENDENT APPROVAL ADJUDICATION=VALID；ACTIVE-BASELINE PRE IDENTITIES=11/11 MATCH` |
| Gate A | `PASS；READ-ONLY STATIC SIGNABILITY；R3=26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be；manifest=5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c（15/15 leaf，strict JSON 16/16，Draft 2020-12 meta 2/2，local refs 150/150，companion rules 12/12，fixtures 3/3，negative declarations 25/25）；prehash=7569/db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d；Event static vectors=8/8（2 started/5 completed/1 late）；CR-004 R1/R2 snapshot+approval binding=PASS；active-baseline pre identities=11/11，pin=CURRENT；material-value scan=0；R4=27384/cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10；0 write/0 network；APPROVAL INPUT VALID` |
| Request / manifest / active pin 同步 | `PASS；11/11 ATOMIC BASELINE SYNC；SRS=128874/0c8ece722c3935cf0fad9117db96985228ceaee864f542fc407cf5e3c8234492；Architecture=90344/3074ad8e1640cd709adf0defbd40d9f3e6417ca5345276244c96c31d865ccd89；Database=115654/4ffa09ded6c0351730070d140d4bf9709060531306bebe9dfb99c39d35512ddf；API=328001/fee560512e39086bc3e1340c127054623c701b6e4d92dd058efb70cb8a5cf830；Page=83278/f6730f09f95f761af31657fe14ad80d65c11bc914de7285ba09501c611d52ac9；AI=51306/6676a2d8cdaa5a85e8f62937292aa4530dedd456dd9a6bbc2ebd627d808b5a43；Test=49975/63ef73a6c98c0e57b8e88271db930294cf1934f3fdc62a8f6322628adaa1bea5；Deploy=54314/99ba1c5226dc104ce2d96e1c80ee935de0a117116d5a608e3047c2ca2f7232ac；Plan=106372/e52cffaa687c2460ce021a23b2565b1948673a84226552cc3460523b5bf22a3e；manifest=1647/4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94；approval_pre_meta.py=22193/67a3457c5a0958e9bd443033a6cb1654a4ef5f0ec9b04e99437a1d2331203f71` |
| Gate B Stage1 contract/offline implementation（2026-08-10） | `PASS；273/273；ZERO-SOCKET ATTEMPTS=0；NEGATIVE RUNNER=PASS；STRICT PARSER / COMPANION / RESOLVER / RETRY / RESPONSE BOUNDARY / NETWORK POLICY / EVENT DTO / FAKE SINK ONLY` |
| 完整 Gate B dual Draft 2020-12 engines（2026-08-10） | `PASS；CASES=27/27（2 POSITIVE + 25 NEGATIVE）；NEGATIVE VECTORS=25/25；SCHEMA CALLS=PYTHON 20 + NODE 20；SCHEMA ENGINES=2/2；ZERO-SOCKET GUARD=PASS；ZERO-SOCKET ATTEMPTS=0；NODE SELFTEST=PASS；ANTI-FORGERY=11/11；TEST-ONLY EXACT LOCKS / ISOLATED MATERIALIZATION` |
| Gate C persistent AI-005/runtime | `PENDING / NOT AUTHORIZED` |
| fixed_test_provider / Provider 网络 | `NOT AUTHORIZED` |
| 真实数据 / secret / 部署 / canary / production | `NOT AUTHORIZED` |
| Stage1 未执行环境 | `PostgreSQL / Docker / browser / Provider / remote / deploy / production = NOT_RUN` |
| R4 decision snapshot | `APPROVED / ACTIVE；preimage_bytes=27384；decision_snapshot_sha256=cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` |
