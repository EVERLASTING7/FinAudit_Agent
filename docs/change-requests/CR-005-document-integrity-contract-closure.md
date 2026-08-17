# CR-005-R1：文档核心完整性合同闭合

文档类型：合同候选；可变生命周期状态只记录在第 8 节。

日期：2026-08-07

## 1. 变更原因

文档核心表尚未进入正式迁移。准备 `document_block_corrections`、`document_assets` 和 `markdown_source_mappings` 时，发现三项不能从现有 Request 唯一实现：

1. `GAP-043`：纠错记录声明禁止 UPDATE，但 `result_parse_version_id` 又允许先空置、再回填。
2. `GAP-044`：`document_assets.security_status` 没有允许值、初始值、放行条件或与原文件扫描状态的关系。
3. `GAP-045`：现有五列普通 UNIQUE 包含可空 `block_id`；PostgreSQL 会把多个 NULL 视为不同值，不能保证文档声称的真实唯一性。

本 CR 只提出最小合同，不改变 57 张核心表总数，不关闭 CommonMark/GFM 解析器、HTML 白名单和复杂表格结构化资源格式的 `TBD-013`。

## 2. 推荐决策摘要

| 决策 | Gap | 推荐方案 |
|---|---|---|
| DOC-D-001 | GAP-043 | 同一事务创建 queued 候选 Parse、单条纠错记录与 Job/Outbox；`result_parse_version_id` 改为 NOT NULL，激活仍只走 PARSE-005 |
| DOC-D-002 | GAP-044 | 使用可哈希的 `asset-security-v1` Profile；统一六态、精确资源上限与重建式重评，只有 `clean` 可以被引用、预览或导出 |
| DOC-D-003 | GAP-045 | PostgreSQL 16 使用 `UNIQUE NULLS NOT DISTINCT` 实现包含 NULL 的真实唯一性 |

## 3. 待审批推荐合同

### 3.1 DOC-D-001：纠错与结果 Parse 原子创建

- `document_block_corrections.result_parse_version_id` 为 `UUID NOT NULL` 外键，不允许先写 NULL 后回填。
- 一次 PARSE-004 纠错事务必须锁定所属文件的当前 Parse 版本，创建一个 `status='queued'` 的候选 `document_parse_versions` 行、恰好一条指向该候选版本的纠错记录、一个重建 Job 及其 Outbox 事件。任一步失败则全部回滚；事务不得同步复制完整页面/块/资源，也不得等待 Worker。`document_block_corrections.result_parse_version_id` 必须 UNIQUE，保证一个 manual-correction 候选只对应本次单块单字段纠错。
- 候选 Parse 必须满足：`source_type='manual_correction'`、`parent_version_id=source_parse_version_id`、与来源 Parse 属于同一 `file_id`，且结果版本不得等于来源版本。`parser_name/parser_version/ocr_name/ocr_version` 在创建时逐字段复制来源 Parse，`code_version` 固定为 `manual-correction-snapshot-v1`；同一值同时冻结进 Job `input_json`，Worker 版本不匹配时失败关闭，禁止事后回填 Parse 来源字段。Worker 只从 PostgreSQL 权威纠错记录重建完整快照，并按 CR-004 获批后的 Job 状态机流转。
- PARSE-004 的 Job 身份固定为 `job_type='manual_correction_snapshot'`、`resource_type='document_parse_version'`、`resource_id=result_parse_version_id`。权威整数列 `async_jobs.input_schema_version` 固定为 `1`，Handler Registry 使用 `(job_type, input_schema_version)` 识别 Schema；`input_json` 只允许且始终包含 `file_id/source_parse_version_id/result_parse_version_id/correction_id/handler_code_version/handler_registry_version/handler_registry_hash` 七个键。前四项为非空、规范小写带连字符 UUID string，`handler_code_version` 精确为 `manual-correction-snapshot-v1`，Registry version 为非空小写 ASCII token，Registry hash 为小写 64 位十六进制。未知键、缺键、NULL、错误类型、非规范 UUID 或版本/hash 不匹配全部失败关闭；`input_hash` 只对这份精确 JSON 做 RFC 8785 JCS 后计算，不在 JSON 内保存第二份 Schema 版本。不得把正文、before/after 内容或自由文本理由复制进 Job。提交时的 deferred constraint trigger 必须证明该候选恰有一条纠错、一个上述 Job，以及该 Job 恰有一条 sequence 1 的 `job.dispatch.requested` Outbox。
- `source_block_id` 必须属于 `source_parse_version_id`；每次 P0 API 调用只允许修改一个来源块的一个获准字段，并创建一条纠错记录。批量纠错不是当前 P0 合同，不得由 Service 私自扩展。
- PARSE-004 不改变当前活动版本。候选快照完整且质量门禁通过后，仍必须由独立 PARSE-005 权限、幂等和行锁事务执行激活与旧版 supersede。该事务锁定文件后先判断 `target.id == current_active_parse.id`：成立时按既有合同直接返回当前幂等成功；只有目标尚未 active 时，才要求 `target.parent_version_id = current_active_parse.id`。并发 sibling 中后激活的旧分支返回 `409 PARSE_PARENT_STALE`，必须基于新的活动版本重新生成候选，不能覆盖先前已激活纠错；该规则同样适用于 `security_revalidation`。任何 Worker、纠错事务或后台补偿均不得绕过该动作。
- `document_block_corrections` 继续禁止 UPDATE/DELETE。上述跨表关系使用可延迟约束触发器在事务提交前校验，不能只依赖 Service 层检查。

本 CR 冻结两个 Handler 候选条目；只有在 CR-004 获批并同步、最终只读 Handler Registry 将它们连同其他条目一并发布 version/hash 后，才可进入 Job/Worker 实现：

| job_type | input_schema_version | handler_code_version | first_step_code |
|---|---:|---|---|
| `manual_correction_snapshot` | 1 | `manual-correction-snapshot-v1` | `snapshot_rebuild` |
| `asset_security_revalidation` | 1 | `asset-security-revalidation-v1` | `asset_security_revalidation` |

Registry 条目还必须满足 CR-004 批准的 Schema、排序、唯一性和历史保留规则；本表不自行定义第二份 Registry，也不能用两个候选条目推导完整 Registry hash。

不采用仅允许一次 `NULL → 非空` 更新的方案，因为它仍会产生可观察的半成品状态，并扩大不可变触发器的更新白名单。

### 3.2 DOC-D-002：文档资源安全状态与版本化 allowlist

#### 3.2.1 最小字段与版本

- `document_assets.security_status` 为 `VARCHAR(20) NOT NULL DEFAULT 'pending'`，数据库 CHECK 只允许下表六态。
- 新增 `security_policy_version VARCHAR(50) NOT NULL` 与 `security_policy_hash CHAR(64) NOT NULL`。首版版本固定为 `asset-security-v1`；hash 为下述 Profile 按 RFC 8785 规范化 JSON 后计算的 SHA-256 小写十六进制。版本、hash 或 Profile 不匹配时失败关闭，不得用空值、环境默认或自由文本代替。
- 新增 `security_checked_at TIMESTAMPTZ NULL` 与 `security_error_code VARCHAR(80) NULL`。创建时两者为空；唯一一次 `pending -> 终态` 更新必须写检查时间。`clean` 时错误码为空，其他终态只允许版本化 Profile 中的固定安全错误码。
- 新增可空扫描证据列 `security_scanner_profile_class VARCHAR(20)`、`security_scanner_registry_version VARCHAR(100)`、`security_scanner_registry_hash CHAR(64)`、`security_scanner_adapter_code VARCHAR(64)`、`security_scanner_version VARCHAR(100)`、`security_scanner_definition_version TEXT` 与 `security_scanner_invoked BOOLEAN`。命名、长度和空值语义复用 CR-010-R1 的唯一 `scanner-registry-profile-v1`；不创建 Asset 专用第二 Registry。`definition_version` 只在实际观察且通过获准 Profile 校验时保存，不能把 Registry 允许值伪装成已观察值。创建 `pending` 行时这些列全部为 NULL；唯一一次终态转换按下述矩阵原子写入，之后不可更新。
- 新增 `source_asset_id UUID NULL REFERENCES document_assets(id)` 保存重建式安全重评的直接来源，并建立 `UNIQUE(parse_version_id, source_asset_id) WHERE source_asset_id IS NOT NULL`。P0 不新增模糊的资产槽位字段：被显式引用的旧 Asset ID 本身就是稳定槽位，一个目标 Parse 对同一旧 Asset 最多生成一行。
- deferred constraint trigger 必须验证：目标 Parse 的 `source_type='security_revalidation'` 时每个 Asset 的 `source_asset_id` 必填，来源 Asset 所属 Parse 恰为目标 Parse 的直接 `parent_version_id`，两者 `file_id/page_no/asset_type` 一致，目标/来源 `id` 与 `minio_object_key` 均不同；其他 `parser/ocr/manual_correction` Parse 的 `source_asset_id` 必须为 NULL。自身、旁支、祖先非父代、跨文件、跨页、类型变化和一源多目标全部由 PostgreSQL 拒绝。
- `mime_type` 保存服务端检测并规范化后的 media type，不信任解析器、上传者或文件扩展名声明。
- 安全状态、策略版本、对象键和内容哈希必须共同对应同一份不可变对象。重新检测不得把新字节结果覆盖到旧对象键；策略升级按新策略重新生成或重新验证，并保留可审计历史。
- `document_assets` 禁止 DELETE；除一次 `pending -> clean|infected|scan_failed|unsupported|not_configured` 可同时修改 `security_status/security_checked_at/security_error_code` 与上述七个扫描证据列外，所有既有列禁止 UPDATE。空 UPDATE、分两次回填证据和同时改对象键/hash/血缘同样被触发器拒绝。

#### 3.2.2 状态语义

| 状态 | 精确语义 | 是否允许下游使用 |
|---|---|---:|
| `pending` | 尚未完成 `security_policy_version` 指定的全部检查；创建时默认值 | 否 |
| `clean` | MIME、Magic Bytes、完整解码、资源上限和恶意内容检查全部通过 | 是 |
| `infected` | 检出恶意内容或禁止的活动载荷；隔离且不自动重试 | 否 |
| `scan_failed` | 扫描、读取、传输或解码发生可恢复技术失败 | 否 |
| `unsupported` | MIME、文件头、编码或资源类型不在该策略 allowlist，属于确定性拒绝 | 否 |
| `not_configured` | 必需扫描能力未配置；仅允许本地/测试记录，生产必须 fail closed | 否 |

`asset-security-v1` 的规范化 Profile 固定包含以下值：

```json
{
  "allowed_media_types": ["image/jpeg", "image/png"],
  "max_decoded_bytes": 268435456,
  "max_encoded_bytes": 20971520,
  "max_height": 8192,
  "max_pixels": 40000000,
  "max_width": 8192,
  "scanner_deadline_ms": 10000,
  "terminal_error_codes": {
    "clean": [],
    "infected": ["ACTIVE_CONTENT_DETECTED", "MALWARE_DETECTED"],
    "not_configured": ["SCANNER_NOT_CONFIGURED"],
    "scan_failed": ["OBJECT_READ_TRANSIENT", "SCANNER_TIMEOUT", "SCANNER_UNAVAILABLE"],
    "unsupported": ["IMAGE_DECODE_INVALID", "IMAGE_LIMIT_EXCEEDED", "MAGIC_BYTES_MISMATCH", "MEDIA_TYPE_UNSUPPORTED"]
  },
  "version": "asset-security-v1"
}
```

上述 UTF-8 JCS bytes 的固定 SHA-256 为 `b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0`；任何字段、数组顺序语义或数值变化必须发布新版本，不能沿用该 hash。`pending/clean` 必须写 NULL 错误码；其余四个非 clean 终态必须写且只能写各自数组中的一个代码，状态与错误码不匹配由数据库 CHECK 拒绝。

扫描证据矩阵固定如下：

| security_status / error | Profile、Registry、Adapter、Scanner、Definition 五项身份 | profile_class | scanner_invoked |
|---|---|---|---|
| `pending` | 全部 NULL | NULL | NULL |
| `clean`、`infected` | Profile/Registry hash、Adapter、Scanner 与实际 Definition 全部非空；条目必须为 CR-010 `required_exact` 且 outcome 获准 | `fixed_test/production` 之一并等于运行环境；`contract/local_offline` 禁止产生这两态 | `true` |
| `scan_failed + OBJECT_READ_TRANSIENT` | 全部 NULL；失败发生在 Scanner 调用前 | NULL | `false` |
| `scan_failed + SCANNER_TIMEOUT|SCANNER_UNAVAILABLE` | 前四项非空；Definition 按 CR-010 条目的 `required_exact/null_only` 写实际值或 NULL，完整组合与 outcome 必须获准 | `fixed_test/production` 之一并等于运行环境 | `true` |
| `unsupported` | 全部 NULL；拒绝只来自上述 Policy 的 MIME/Magic/解码/资源上限 | NULL | `false` |
| `not_configured` | 只写本环境获准的 Profile class、Registry version/hash；Adapter/Scanner/Definition 为 NULL | `local_offline/fixed_test` 之一；production 禁止形成业务行并启动失败 | `false` |

其中“五项身份”是 `security_scanner_registry_version/hash/adapter_code/scanner_version/definition_version`，Profile class 单列展示。所有非空 Scanner 组合必须通过 CR-010 最终批准的 `validate_scanner_registry_v1`；数据库触发器另外强制上表 NULL 矩阵。`clean` 不得只凭状态和 Policy hash 成立，且不得使用 CR-010 的 `null_only` 条目；缺少、未知、跨 class 或与获准 Profile 不一致的任一实际身份都失败关闭。`scan_failed` 的 NULL 分支只记录失败，不伪造未观察的 Scanner/签名事实，也永不允许下游使用。

CR-010-R1 的 `scanner-registry-profile-v1` 是文件扫描与文档资源扫描共享的唯一 Scanner Registry Schema、JCS/hash、环境 class、历史载体和数据库 validator 事实来源。本 CR 只增加文档 Asset 对该载体的字段投影与状态矩阵；CR-010 未获批准并同步、目标环境精确 Profile 未另行批准时，不得生成 Scanner 终态证据或相关 runtime。`fixed_test` 仍是无网络确定性 Scanner double，绝不等于或调用 `fixed_test_provider`。

PARSE-006 不增加第二份 target selector 或“当前 Scanner”配置。一个已批准的 `fixed_test` 或 `production` Profile 只有在恰好一个条目同时满足以下全部条件时，才是 `asset_security_revalidation` 的可用目标：条目 `definition_version_mode='required_exact'`，`allowed_definition_versions` 恰含一个非空精确字符串，且 `allowed_scan_outcomes` 至少包含 `clean/infected/scan_failed`。Service 只能从该 Profile 的规范 bytes 按此谓词选中唯一条目，并把条目的 Adapter、Scanner 与唯一 Definition 逐字冻结进 Job；零个或多个命中都返回 `SECURITY_REVALIDATION_CONFIGURATION_ERROR`，不创建候选或 Job。Adapter 必须在处理第一个 Asset 前 pin 并实际验证该唯一 Definition；不能验证、观察值不一致或运行时切换时，Job 与候选 Parse 按下述原子映射失败关闭，不得把 Registry 允许值写成 Asset 的已观察证据。该限制是 CR-010 共享 Registry 上的 P0 消费规则，不改变 CR-010 对其他扫描场景允许多个 Definition 的元合同。

安全推荐如下：

- `asset-security-v1` 只允许规范化后的 `image/png` 和 `image/jpeg` 进入 `clean`；二者都必须通过匹配的 Magic Bytes、完整解码、上表字节/宽高/像素/解码内存上限及恶意内容扫描。Scanner 通过 provider-neutral Adapter 接收不可变对象标识和预校验摘要，只返回六态之一与固定安全错误码；不得把扫描器原始响应、异常、堆栈或凭据写入数据库。
- `image/svg+xml`、HTML/XML、PDF、Office、压缩包、可执行内容、带外部引用或活动内容的资源一律不得进入 `clean`。复杂表格的结构化资源格式仍由 `TBD-013` 冻结；在此之前只能生成符合上述 allowlist 的安全栅格预览，不能把任意 JSON、HTML 或 XML 伪装成已批准资源格式。
- 原文件 `files.security_scan_status='clean'` 是开始提取的必要条件，但不是派生资源自动变为 `clean` 的充分条件；每个资源均从 `pending` 开始独立检查。
- 只有 `security_status='clean'` 的资源可以被活动 Markdown 的 `asset://<id>` 引用、解析为预览、签发访问 URL 或进入报告/导出。解析 `asset://` 时仍必须执行组织、文件和角色鉴权。
- 生产环境扫描能力未配置或策略版本未知时，应用启动/依赖健康检查失败；不得把 `not_configured`、未知状态或未知策略当作 `clean`。
- 状态只允许 `pending → clean/infected/scan_failed/unsupported/not_configured`，终态不得原地改写。重试、Policy/Scanner Registry/Adapter/Definition 升级或受控重新检测必须创建 `source_type='security_revalidation'`、`parent_version_id=<当前活动源 Parse>` 的新候选 Parse；失败候选本身永不作为下一候选父版本，重试仍通过唯一入口解析回其仍活动的直接父版本。
- 重评 Job 固定为 `job_type='asset_security_revalidation'`、`resource_type='document_parse_version'`、`resource_id=result_parse_version_id`，并固定 `max_attempts=1`。候选 Parse 的 `parser_name/parser_version/ocr_name/ocr_version` 逐字段复制直接父 Parse，`code_version='asset-security-revalidation-v1'`。权威 `async_jobs.input_schema_version=1`；`input_json` 只允许且始终包含十四键：`file_id/source_parse_version_id/result_parse_version_id/security_policy_version/security_policy_hash/handler_code_version/handler_registry_version/handler_registry_hash/scanner_profile_class/scanner_registry_version/scanner_registry_hash/scanner_adapter_code/scanner_version/scanner_definition_version`。前三项是非空规范 UUID string；Policy 与两个 Registry 的 version/hash 必须是服务端获准精确配对；Handler version 精确为 `asset-security-revalidation-v1`；Scanner 六元目标必须逐字段等于上文从 CR-010 环境 Profile 唯一推导的 `required_exact` 条目及其唯一 Definition。调用方不能提交或覆盖这些冻结字段；环境存在零个或多个可选目标、class 为 `contract/local_offline`、Definition 列表不是单值、或缺任一批准时都返回配置错误，不创建 Job。
- 未知键、缺键、错误类型、非规范 UUID、错误 Policy/Handler/Scanner 身份或不获准的 null 全部失败关闭。`input_hash` 只对上述十四键精确 JSON 做 RFC 8785 JCS 后计算，因此 Scanner Registry、Adapter 或 Definition 变化必然改变输入 hash。Worker 只能使用冻结六元 Scanner 目标；实际结果仍按上表和 CR-010 validator 写证据，不能在排队后切换到“当前”配置。
- 同一活动源 Parse 同时最多存在一个 `source_type='security_revalidation' AND status IN ('queued','running')` 的在途候选，由 PostgreSQL 部分唯一约束最终裁决；`succeeded/manual_review_required/failed` 均为本次构建终态，不进入在途谓词。已成功的 sibling 仍只能通过 PARSE-005 的 parent/current CAS 激活；后续 sibling 先激活时，旧成功候选稳定返回 `PARSE_PARENT_STALE`，所以终态候选不会形成永久活性锁。候选 Parse、唯一 Job、该 Job 唯一 sequence 1 `job.dispatch.requested` Outbox 必须同事务创建，并由 deferred constraint trigger 校验一一对应及父版本在锁定文件上仍为当前活动版本。该 job_type 的 Job/Parse 状态必须按同一事务、同一 fencing/CAS 原子映射：创建时两者均为 `queued`；若首次投递在 claim 前由 CR-004 Job-aware finalizer 终结，Job `queued -> failed` 与 Parse `queued -> failed` 必须在同一 finalizer 事务提交；Worker claim 时 Job `queued -> running` 与 Parse `queued -> running` 同时成功；技术 Lease heartbeat/recovery 不改变 Parse 的 `running`；快照完整且全部 Asset 可安全下游使用时 Job `running -> succeeded` 与 Parse `running -> succeeded` 同时成功，快照完整但存在需人工处置的 non-clean 资源时同一 Job 成功与 Parse `running -> manual_review_required` 同时成功，且 PARSE-005 必须拒绝激活该候选；任何 Worker/配置/快照失败都把 Job `running -> failed` 与 Parse `running -> failed` 同时提交。P0 禁止该 job_type 进入 `cancel_requested/cancelled`，也不开放取消入口；`max_attempts=1` 使其失败后不得走同 Job `failed -> queued` 或用户 retryable 路径，`failed/manual_review_required` 都只能由 PARSE-006 基于仍活动的直接父 Parse 创建新候选和新 Job。deferred trigger 必须拒绝 Job/Parse 不一致及“Parse 已 failed 但旧 Job 仍可运行”的提交，因此部分唯一门禁不会提前释放或永久滞留。
- Worker 必须重建父 Parse 的完整 pages、blocks 与 exclusions 快照，并按冻结 Policy/Scanner 目标为每个父资源生成新对象键和新 `document_assets` 行、逐行写 `source_asset_id`；目标 blocks 的任何非空 `asset_id` 必须指向同一目标 Parse 中由其父块原资源映射得到的新 Asset。可延迟触发器与 PARSE-005 质量门禁共同拒绝缺页、缺块、缺 exclusion、缺资源映射、跨 Parse Asset 引用或快照数量/身份不一致。旧 Parse/Asset 保持可审计，禁止复用旧对象键覆盖字节或在同一行重置为 `pending`。本 CR 相应把 Parse `source_type` 从 `VARCHAR(20)` 扩为 `VARCHAR(30)`，允许值从三种扩为 `parser/ocr/manual_correction/security_revalidation`；不增加第 58 张表。

#### 3.2.3 安全重评唯一受理入口

- 新增 `PARSE-006 POST /api/v1/document-parse-versions/{parse_version_id}/security-revalidations`，其 `api_delta=+1`，基线锚定 2026-08-07 已同步 CR-001-R2/CR-002-R4、122 API 且 `docs/baseline-manifest.md` SHA-256 为 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`。最终同步按届时已生效 CR 的 delta 累加，禁止与 CR-009 各自把最终总数硬编码为 123；本接口归入既有 `DOC-001` 工作包，P0 工作包总数保持 86。不得同时保留未登记的内部 HTTP、运维脚本或第二个公开入口。
- 仅 `system_admin` 可调用并必须携带 `Idempotency-Key`。请求 JSON 只允许 `reason/security_policy_version/force_recheck`：reason 去首尾空白后 1～500 个字符并写脱敏 operation log，Policy version 必须受支持且获准，`force_recheck` 为严格 boolean、默认 false。调用方不能提交结果 Parse、Job、Policy hash、Handler/Scanner Registry 或 Scanner 条目。
- 完成认证、`system_admin` 权限检查、请求 Schema 校验与规范化后，Service 先按现有唯一键 `organization_id/user_id/Idempotency-Key` 锁定或保留权威幂等记录；现有 `request_method/request_path` 仍逐字保存但不扩展唯一键。请求 hash 对固定方法 `POST`、固定接口标识 `PARSE-006`、path 中的 `parse_version_id` 与规范化后三个 Body 字段共同计算，不包含会随时间变化的当前 Policy/Scanner 选择；因此同一 Key 被复用于其他 endpoint、方法、Path ID 或 Body 时必定形成不同 hash。已有记录且 hash 不同立即返回 `IDEMPOTENCY_CONFLICT`；相同 hash 且已完成时，在任何文件、Parse、候选或当前配置门禁前返回首次保存的完整响应；相同 hash 且进行中时由唯一记录行/唯一约束串行等待创建事务提交，再按完成或回滚后的权威记录重判，不得越过它先返回业务状态冲突。只有新保留的 Key 才继续执行以下可变资源检查。
- 新 Key 的事务按固定顺序锁定文件行和其当前活动 Parse，再验证 Path ID；不存在、已删除或无查看权限统一 404，锁后已非活动返回 409 `PARSE_VERSION_NOT_ACTIVE`。创建前再次验证父版本仍是锁定文件的 current active；PARSE-005 使用同一文件锁，不能在检查与提交之间 supersede。若已有上文未终结候选则返回 409 `ASSET_REVALIDATION_IN_PROGRESS`，数据库部分唯一约束处理最终竞争。
- 受理条件是以下至少一项：来源存在 `scan_failed/not_configured` Asset；服务端选定的 Policy version/hash 与来源不同；服务端选定的 CR-010 Scanner 六元目标与来源非空证据或最近不可激活重评 Job 的冻结目标不同；最近 `failed/manual_review_required` 重评候选需要用同一冻结目标重试；或 `force_recheck=true` 明确要求同 Policy/Scanner 重新检测。这里“最近不可激活候选”固定为同一直接父 Parse 下 `status IN ('failed','manual_review_required')` 且 `source_type='security_revalidation'` 的最大 `document_parse_versions.version_no`；`(file_id,version_no)` 必须唯一，再通过该候选与 Job 的一一关系读取十四键冻结目标，禁止按时间戳、无 ORDER BY 或任一候选行选择。上述候选的 UI 重试动作必须解析到其仍活动的直接父 Parse 并调用本端点，禁止以不可激活候选为父。均不满足时返回 409 `ASSET_REVALIDATION_NOT_REQUIRED`。
- Service 在保留幂等记录的同一事务创建候选 Parse、Job、sequence 1 Outbox、首次完整幂等结果和 action `document_parse.security_revalidation.requested` 的 operation log；提交后相同 Key/hash 始终返回该首次结果，即使原 Parse 后续不再 active 或已有候选。CR-008 必须把 action 纳入最终注册表。未知 Policy/Handler/Scanner 配置返回脱敏 503 `SECURITY_REVALIDATION_CONFIGURATION_ERROR`，不回显 Registry、对象键、Scanner 响应或异常。
- PARSE-006 成功响应必须复用 GAP-018 最终批准的统一 `AcceptedJobResponse`，包含 Job ID、结果 Parse 资源 ID、权威 `stage` 和 Job URL；本 CR 不自造字段集合。GAP-018 未关闭并同步前不得注册或开放该路由。
- 本入口只创建候选，不激活。完成重评后仍按 PARSE-005 权限、质量门禁和 sibling CAS 激活；P0 不自动批量重评全部历史版本，也不新增定时扫描器。

### 3.3 DOC-D-003：NULL 参与真实唯一性

PostgreSQL 16 直接使用以下约束语义：

```sql
UNIQUE NULLS NOT DISTINCT (
  markdown_version_id,
  ast_node_id,
  md_char_start,
  md_char_end,
  block_id
)
```

它保持现有五列业务键不变，但把相同键上的两个 `block_id=NULL` 视为冲突。不得以应用层“先查后写”替代数据库唯一约束。

若迁移工具不能稳定生成该约束，可使用等价的两个唯一索引：非空分支唯一五列，`block_id IS NULL` 分支唯一前四列。两种实现只能选择一种，不能同时维护两套事实；PostgreSQL 16 首选 `NULLS NOT DISTINCT`。

### 3.4 上游依赖与实施门禁

- 本 CR 可以单独审批文档领域语义、两个 Handler 候选条目、PARSE-006 contract 和 CR-010 Scanner 证据投影，但审批本身不授权创建 Job/Outbox migration、开放 API 或启动对应 Worker。
- `async_jobs/async_job_steps/outbox_events` 的 DDL、deferred trigger、Dispatcher、Handler 加载和 Worker runtime 必须等待 CR-004 获批并同步，且同一发布的最终 Handler Registry 必须包含 3.1 的两个精确条目及可验证 version/hash。缺任一条件时，DOC-D-001/002 的 Job 路径保持阻塞。
- PARSE-004 与 PARSE-006 的幂等/operation log/API runtime 都必须等待 CR-006、CR-008 的 wrapper/action registry 获批并同步；文档表 DDL 可按本 CR 与其数据库依赖分阶段实施，但不能据此提前开放任一 API。
- PARSE-006 还硬依赖 GAP-018 的统一 `AcceptedJobResponse` 获批并同步；在此之前只可保留合同候选，不得注册路由或为它创建私有 DTO。
- 任何 Asset 写入 Scanner 参与的终态前，必须先批准并同步 CR-010-R1，并存在与当前环境匹配且经过独立环境审批的精确 `scanner-registry-profile-v1` 与数据库 validator。contract 审批不批准具体 Scanner、凭据、外联或 production；缺少环境批准时按 3.2 的精确分支失败关闭，production 必须启动失败。
- 上述依赖只阻塞依赖它们的 migration/runtime，不反向改变本 CR 已审批后的文档语义；禁止用临时常量、环境默认或未哈希配置跨越门禁。

## 4. 迁移与回滚

### 4.1 升级

- 文档核心表尚未创建时，应在创建表的同一线性 Alembic revision 中直接采用本 CR 的最终列、`document_parse_versions.source_type VARCHAR(30)`、CHECK、触发器和唯一约束，不先制造可空、字段过短或弱唯一的过渡 Schema。
- 若未来需要对非空数据库补做本变更，升级必须先检查：NULL 的 `result_parse_version_id`、无法证明策略版本的资源、以及按 `NULLS NOT DISTINCT` 分组后的重复映射。任一项存在时迁移失败并输出仅含计数/ID 的脱敏诊断；禁止猜测结果版本、把旧资源自动标记 `clean`、删除映射或静默去重。
- 新增约束前应在单一事务中锁定目标表并重复执行冲突检查，避免预检与建索引之间插入新冲突。

### 4.2 回滚

- downgrade 的数据库门禁按 `document_parse_versions -> document_block_corrections -> document_assets -> markdown_source_mappings -> async_jobs -> async_job_steps -> outbox_events` 的固定顺序取得 `ACCESS EXCLUSIVE` 锁，再执行任何检查或 DDL。若四张受本 CR 直接约束的文档表由同一尚未发布的文档核心 revision 首次创建，任一表非空均在任何 DDL 前以稳定 SQLSTATE `55000` 原子失败；不得删除先前 revision 的扩展、身份表或其他业务表。
- 增量迁移除检查任一纠错、资源或映射行外，还必须拒绝存在 `source_type IN ('manual_correction','security_revalidation')` 的 Parse、对应 `manual_correction_snapshot/asset_security_revalidation` Job、Step 或 Outbox 证据。只要任一事实存在，就不得收窄 `source_type VARCHAR(30)`、移除本 CR 新增的安全 Profile/检查时间/错误码/血缘列、约束、触发器或 `NULLS NOT DISTINCT` 语义；旧应用无法解释新证据时停止回滚并采用经审查的前向修复。
- 空表增量 downgrade 可以恢复迁移前的普通 UNIQUE 并移除本 CR 自己新增的列与对象，但必须与旧应用版本一起回滚。禁止自动改写、删除、导出后清理或静默去重任何业务/审计证据。

## 5. 必须验收

- **纠错原子性**：分别在创建 queued 候选 Parse、写唯一纠错、创建固定身份 Job 和写 sequence 1 Outbox 处注入失败，确认事务完全回滚；提交后 `result_parse_version_id` 永不为空且 UNIQUE，Job resource/input 白名单与 JCS hash 精确，来源块/来源 Parse/结果 Parse/Job/Outbox 的关系由 PostgreSQL 拒绝错误组合。
- **纠错并发与激活隔离**：相同 Idempotency-Key/内容并发只产生一个候选版本；不同请求获得不同 queued sibling 且都不能改变活动版本。未通过质量门禁或未调用 PARSE-005 时激活/supersede 均不发生；第一个 sibling 激活后，其余候选因 `parent_version_id != current_active_parse.id` 返回 `PARSE_PARENT_STALE`，不能覆盖已激活纠错。
- **资源安全矩阵**：固定 Profile JSON 与期望 SHA-256 测试向量，覆盖六态及完整状态—错误码矩阵、未知状态/版本/hash/code、PNG/JPEG 正负样本、精确字节/宽高/像素/解码内存/deadline 边界、MIME/Magic 欺骗、截断图片、解压/像素炸弹、SVG/HTML/XML/外部引用和扫描器不可用；断言只有 `clean + NULL error + asset-security-v1 + 正确 hash` 可被引用或签发访问。
- **Scanner 身份与环境门禁**：复用 CR-010 的 Profile、条目、排序、JCS/hash、环境隔离、validator 和历史保留；证明 Asset 重评只从 Profile 唯一选出一个 `required_exact` 且单 Definition 的条目，零个/多个条目、多 Definition、无法 pin 或实际 Definition 不一致均在创建前或 Job 内失败关闭。覆盖 pending/五终态及各错误码的证据 NULL 矩阵、错误 class/version/hash/Adapter/Scanner/Definition、伪造 `scanner_invoked`、调用前失败不得伪造实际签名、以及 contract 审批未带环境批准的反例。断言 `clean` 必须绑定 `required_exact` 的实际获准 Scanner 身份，production 缺 Registry 时启动失败。
- **安全继承反例**：即使原文件为 `clean`，派生资源为 `pending/infected/scan_failed/unsupported/not_configured` 时也必须阻断。
- **重评血缘与不可变性**：安全重试与策略升级只通过 `security_revalidation` 候选 Parse 和 `asset_security_revalidation` Job 执行；验证 `VARCHAR(30)` 可写完整枚举。每个新 Asset 一对一指向直接父 Parse 的唯一旧 Asset，新的对象键不能覆盖旧对象，缺失/重复、跨页/跨文件/跨类型/错误代际来源均由 PostgreSQL 拒绝；DELETE、终态更新和获准终态证据列之外的 UPDATE 均失败。
- **Handler 与输入合同**：两个候选 Handler 的 job_type/schema/code version/first step 精确匹配，两个 `input_json` 分别只接受七键和十四键对象；覆盖缺键、未知键、NULL、非规范 UUID、错误 Handler/Scanner Registry version/hash/entry 与 JCS/input_hash 漂移，并验证 Registry/Adapter/Definition 升级一定改变重评输入 hash。CR-004、CR-010 或最终 Registry 未获批准时，相关 runtime 保持阻塞。
- **PARSE-006 唯一入口**：覆盖 system_admin 权限、404 不泄露、幂等记录先于可变资源门禁、相同 Key/hash 在候选运行及激活后仍返回首次响应、不同 hash 冲突与并发同 Key 串行化；覆盖文件/活动 Parse 固定锁顺序、与 PARSE-005 并发、仅限制 queued/running 的部分唯一约束、Policy/Scanner 升级、按最大 `version_no` 唯一选择最近不可激活候选（`failed/manual_review_required`）并覆盖两态同目标重评、强制复检、无需重评和未知配置。原子创建 Parse/Job/Outbox/log，并证明 claim、成功、人工处置、失败的 Job/Parse 状态同事务映射，禁止取消和同 Job 重排，sibling 激活 CAS 正确。确认无第二公开/内部 HTTP 入口，`api_delta=+1` 按有效 CR 累加、工作包仍为 86；GAP-018 未闭合时路由保持阻塞。
- **映射唯一性**：同一五列键分别以相同非空 `block_id` 和两个 NULL 重复插入，均由数据库拒绝；不同字符范围或不同非空 Block 可正常插入。
- **映射并发**：两个 PostgreSQL 16 事务并发插入相同 NULL 键，最终只能一个成功；不能只测试 ORM 或离线 SQL 文本。
- **迁移往返**：在真实 PostgreSQL 16 上完成空库 upgrade/downgrade；按固定顺序锁定全部七张受影响/证据表，任一文档行、manual/security Parse、对应 Job/Step/Outbox 存在时 downgrade 均在 DDL 前原子失败且所有行、列和约束保持不变。确认不影响先前 revision，并以前向修复处理非空环境。

## 6. 审批后需同步的事实来源

批准后必须同步九份 Request 事实来源：需求规格、系统架构、数据库设计、API 设计、页面与交互、AI/RAG/Prompt、测试与验收、部署运维、开发任务计划；同时更新追踪材料，将本 CR 记录为 `api_delta=+1` 并与届时所有已生效、尚未同步的 CR delta 累加，P0 工作包仍为 86，再生成新的 Request 基线哈希。同步完成只能解除本 CR 自身的合同门禁，3.4 的上游与环境门禁仍分别生效。

## 7. 审批边界

在第 8 节记录首次 snapshot 且全部必需签署完成前，本文件不授权：

- 修改 `Request/`；
- 创建或执行 migration、实现文档服务或开放 API；
- 自动处置既有业务数据；

即使完成 contract 签署，本 CR 也始终不授权：

- 调用 `fixed_test_provider`、任何真实模型/外部网络或进行 production 放行。

审批角色矩阵如下；同一人具备多个权限时可以合并记录，但必须逐项列出承担的角色：

| 范围 | 必需审批角色 |
|---|---|
| DOC-D-001 | 需求、架构、数据、后端/API、安全、测试 |
| DOC-D-002、CR-010 Scanner 证据投影与 PARSE-006 contract | 需求、架构、数据、后端/API、AI/RAG、测试、运维、安全 |
| DOC-D-003 | 需求、数据、后端/API、测试 |
| migration/downgrade 可实施性 | 架构、数据、运维、安全 |

每条审批记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_option / cr_revision / decision_snapshot_sha256 / baseline_manifest_sha256 / api_delta / environment_scope=contract / 日期 / 证据链接 / 备注`。`selected_option` 必须逐项覆盖 DOC-D-001～DOC-D-003、两个 Handler 候选、CR-010 Scanner 证据投影、PARSE-006 和 migration/downgrade；`baseline_manifest_sha256` 必须是第 3.2.3 节锚定值，`api_delta` 必须为 `+1`。任一必需角色留空、拒绝、基线漂移或选项互相冲突时整体保持 `NOT APPROVED` 并先提升 revision。contract 范围不批准具体 Scanner、网络、真实数据迁移或 production。

`decision_snapshot_sha256` 计算规则：全文行尾规范化为 LF，定位内容完全等于 `## 8. 当前状态` 的唯一标题行，取该行之前的全部行并在末尾保留恰好一个 LF，对 UTF-8 bytes 计算 SHA-256 小写十六进制。首次快照生成后，第 1～7 节任一规范性修改都必须提升 CR revision、重新计算 hash 并重置全部签署。生成初始 hash 只建立可签署对象，不等于批准、Request 同步、migration/runtime 授权或环境放行。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| DOC-D-001～DOC-D-003 推荐合同 | `PROPOSED` |
| decision snapshot | `GENERATED FOR REVIEW；decision_snapshot_sha256=739f2004bd6cc785d0a06a69445af2c35a373bbe1746d9ed1b194cb3f94dd029；NOT APPROVED` |
| Request 同步 | `NOT AUTHORIZED` |
| CR-004/006/008、GAP-018 与最终 Handler Registry | `BLOCKING DEPENDENCIES` |
| CR-010 / Scanner 环境 Profile | `NOT APPROVED / NOT CONFIGURED` |
| migration / PARSE-006 / Worker runtime | `BLOCKED UNTIL APPROVAL AND DEPENDENCIES` |
| fixed_test_provider 网络 | `NOT AUTHORIZED` |
| production | `NOT AUTHORIZED` |
