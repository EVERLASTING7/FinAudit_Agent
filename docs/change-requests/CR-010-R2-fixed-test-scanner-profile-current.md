# CR-010-R2：Scanner Registry 当前基线与 fixed_test 隔离 Profile

状态：`APPROVED / AUTHORIZED FOR ISOLATED LOCAL_TEST`

日期：2026-08-18

## 1. 前向关系与目的

本 R2 是 `CR-010-R1` 的当前基线 successor。R1 的 decision snapshot
`17877a4cef3ca0a145f32ac06acf44e7fb65b49c06dec710a04a6078aca319de`
继续作为 `SCANREG-D-001～008` 的完整 Profile、JCS、环境隔离、技术表、current/history、CAS、
ownership、downgrade 与 consumer 语义来源；R2 只前向修正过期基线并批准一个具体 `fixed_test`
Profile。与 R1 冲突时以本 R2 为准。

本次要解决的唯一问题是：在不调用网络、不启用真实 Scanner、不接触 production 或真实数据的条件下，
让 `CR-005-R2/PARSE-006` 能在隔离合成数据库证明 Profile 选择、Job 冻结、Asset 血缘与扫描证据闭环。

## 2. 决策与当前 delta

- 采纳 `SCANREG-D-001～008 / recommended-forward`，核心表 `+1`，API `+0`，PermissionCode `+0`。
- 实现前基线固定为 `alembic_head=20260818_026`、`api_v1_operation_count=98`；本 R2 生成
  `20260818_027`，核心表由 57 增至 58。
- `scanner_registry_profiles` 默认空；027 migration 不安装、不激活任何 Profile，也不迁移既有业务数据。
- 只有隔离测试数据库可以由测试 fixture 显式安装和激活本文件第 3 节 Profile。普通 local 数据库、
  staging 与 production 不得复用该行或该证据。
- `asset_security_revalidation` 继续复用既有 PARSE-006，不新增 HTTP 入口；Handler Registry 前向为
  `file-handler-registry-v4`，Job input 保持 CR-005-R2 的十四键精确合同。

## 3. 获准 fixed_test Profile

规范 JCS bytes 精确为以下单行，不含 BOM、前后空白或行尾；仓库 JSON 文件末尾的单个文本传输 LF
不属于 JCS preimage，运行时和测试必须显式移除且复算：

```json
{"entries":[{"adapter_code":"fixed_test","allowed_definition_versions":["fixed-test-definition-v1"],"allowed_scan_outcomes":["clean","infected","scan_failed"],"definition_version_mode":"required_exact","scanner_version":"fixed-test-scanner-v1"}],"profile_class":"fixed_test","registry_version":"fixed-test-registry-v1","schema_version":"scanner-registry-profile-v1"}
```

身份固定为：

| 字段 | 值 |
|---|---|
| JCS bytes | `366` |
| SHA-256 | `4e53b4749ccafa9ac4812054244d8a908efdf77f7ac280b38cb6ea047e0ebc1a` |
| profile class | `fixed_test` |
| registry version | `fixed-test-registry-v1` |
| adapter | `fixed_test` |
| scanner version | `fixed-test-scanner-v1` |
| definition version | `fixed-test-definition-v1` |
| outcomes | `clean,infected,scan_failed` |
| artifact | `backend/app/security/artifacts/fixed-test-scanner-profile-v1.json` |

该 Scanner 是确定性 test double：只接受冻结身份与合成 PNG/JPEG 字节，固定 marker
`FIXED_TEST_MALWARE` 产生 `infected/MALWARE_DETECTED`，其他获准合成输入产生确定性结果；实现不得导入或
调用 socket、HTTP、Provider SDK、ClamAV endpoint 或 `fixed_test_provider`。

## 4. 环境与证据边界

- 本 Profile 只允许 `fixed_test` class 的可丢弃 PostgreSQL 数据库、内存对象存储和合成 Asset。
- 普通 local/test Profile 仍保持表空并对 PARSE-006 返回
  `503 SECURITY_REVALIDATION_CONFIGURATION_ERROR`；仅测试 fixture 显式安装时解除该次运行的阻塞。
- 默认 Worker 不构造 fixed-test Asset Scanner 或内存 Asset 存储；两者必须由隔离测试显式注入。
- 该证据不证明真实 Scanner、真实病毒库、完整图片解码、MinIO Asset copy、staging、production、
  canary、出口控制、容量、告警或真实数据迁移。
- 不允许用本 Profile 生成 staging/production Validator 可接受的行，不允许把 fixed-test Definition
  描述为真实签名库版本。

## 5. 数据库与运行时闭环

- 027 创建 R1 冻结的 `scanner_registry_profiles`、永久 class 绑定、installed/current/historical 生命周期、
  activation expected-current CAS、current/history/full/selector validators 和 fail-closed downgrade。
- current 读取持有 `FOR SHARE` 到 PARSE-006 的 Parse/Job/Outbox/幂等提交；Job 十四键冻结精确 Profile、
  Handler、Policy、Adapter、Scanner 与 Definition，不在执行时追随新的 current。
- Asset 证据约束只允许获准 history tuple；`clean/infected` 必须 `scanner_invoked=true` 且绑定
  `fixed_test|production`，pre-scanner `unsupported/OBJECT_READ_TRANSIENT` 不得伪造 Scanner 身份。
- 每次重评创建新的 `security_revalidation` 候选 Parse、Job 与新对象键，逐 Asset 保存直接
  `source_asset_id`；旧 Parse、Asset、对象键和终态不可覆盖。
- 全部 Asset clean 时 Job 与 Parse 原子收敛为 `succeeded`；存在 non-clean 时 Job succeeded、Parse
  `manual_review_required`；配置、存储、血缘或快照失败时二者原子 failed。只有 PARSE-005 可以独立激活。

## 6. 验收与 downgrade

必须覆盖：JCS/hash 正反例、无 socket、空表 fail-closed、安装/首次 activation、current/history/selector、
十四键 Handler、PARSE-006 幂等与零副作用失败、Job/Parse 状态映射、Asset 一对一血缘、旧事实不变、
clean 与 manual-review 分支、独立激活、migration upgrade/downgrade/upgrade，以及 Profile 行或消费者证据
阻断 downgrade。验证只能在可丢弃 PostgreSQL 16 与合成数据上运行。

## 7. 授权与禁止事项

YHBX 已在当前 Codex task 中选择 `fixed_test` 确定性 Profile，并授权同步 active Request 与实现
local/test；该直接授权覆盖 requirements、architecture、data、backend、AI/RAG、test、operations、security
责任。授权只限本次实现与隔离合成验证；禁止 Provider、production、真实数据迁移、部署、提交和推送。

本 R2 不授权持久安装到普通 local 数据库；测试完成后 Profile 行和测试容器必须清理。本文件第 1～7 节
任一规范修改必须提升 revision 并重签。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-010-R2` |
| selected decisions | `SCANREG-D-001～008 / fixed_test` |
| decision snapshot | `8721eb27d6bcbcfc1d3521867f3e6fcc47b93e8e00a30f850b946b0c0f9b9171 / 6069 bytes` |
| approval | `APPROVED；YHBX / direct Codex task approval / 2026-08-18` |
| Request sync | `COMPLETED；active Request 已绑定 CR-010-R2` |
| migration/runtime | `IMPLEMENTED AND VERIFIED FOR ISOLATED LOCAL_TEST；File 16 / Full 153×2 PASS` |
| Provider / production / real-data migration / commit / push | `NOT AUTHORIZED` |
