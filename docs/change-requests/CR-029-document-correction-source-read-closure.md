# CR-029-R1：通用文档纠错来源读取闭合

状态：`PENDING APPROVAL / BLOCKED-DOCUMENT-CORRECTION-SOURCE-READ`

日期：2026-08-19

## 1. 变更原因

`CR-005-R2` 已开放 PARSE-004/005，并按合同、发票现有字段证据接入纠错 UI；补充协议和制度虽然已在业务类型角色矩阵中获准纠错，却没有可复用的活动 Parse/Block 读取投影。Frontend 不能从 Markdown 文本反推 Block UUID，也不能枚举数据库或复制业务详情 DTO，因此这两类文件仍无法形成可操作闭环。

本 CR 只补一个文件范围、只读、分页的纠错来源投影，并复用 CR-005 的权限、角色和文件状态边界；不改变纠错/激活写合同，不新增 PermissionCode、表、迁移或 Provider 能力。

## 2. 推荐决策摘要

| 决策 | 推荐方案 |
|---|---|
| DOCREAD-D-001 | 新增文件范围的活动 Block 分页读取，Frontend 不推导内部 ID |
| DOCREAD-D-002 | 复用 `files.manage OR system.configure` 与 CR-005 四业务角色矩阵 |
| DOCREAD-D-003 | Cursor 绑定活动 Parse；翻页期间版本变化稳定失败并要求刷新 |
| DOCREAD-D-004 | 仅返回文本纠错所需最小字段，不返回 Asset、哈希、对象键或组织字段 |
| DOCREAD-D-005 | FileDetail 作为四类文件的通用纠错入口，继续独立调用 PARSE-004/005 |

推荐选择：`recommended-forward-v1 / DOCREAD-D-001～005`。

## 3. 精确 API 与权限合同

### 3.1 只读入口

新增：

```text
GET /api/v1/files/{file_id}/document-correction-blocks
```

- `file_id` 只接受 canonical lowercase UUID。
- Query 精确为 `page_size` 与可空 `cursor`；`page_size` 默认 50，范围 1～100，未知 Query 固定 422。
- 请求必须先得到数据库重验 Actor，再要求 `files.manage OR system.configure`；随后按文件 `intended_business_type` 复用 CR-005 角色矩阵：invoice=`finance_reviewer|system_admin`，contract=`finance_reviewer|contract_admin|system_admin`，supplementary_agreement=`contract_admin|system_admin`，policy=`audit_reviewer|system_admin`。`read_only` deny-overrides 继续优先。
- 不存在、跨组织或软删除统一 404 `RESOURCE_NOT_FOUND`。文件必须为 `stored+clean`；archived、validating、rejected 或其他组合返回 409 `FILE_STATE_CONFLICT`。文件尚无活动 Parse 时返回 409 `DOCUMENT_PARSE_NOT_READY`。
- 本接口无副作用，不接受 `Idempotency-Key`，成功固定 `Cache-Control: private, no-store`。

### 3.2 响应与分页

成功 HTTP 200 的 `data` 精确为：

```text
file_id
business_type              # contract|supplementary_agreement|invoice|policy
parse_version_id           # 本页绑定的当前 active Parse
items[]
  block_id
  page_no                  # 正整数
  block_index              # 非负整数
  block_type
  text_content
  reading_order
  bbox                     # null 或 left/top/width/height 四整数
page_size
next_cursor
```

- Repository 只能读取同一文件当前 `status='active' AND archived_at IS NULL` 的 Parse，联查其 Page/Block，并只投影 `is_effective_content=true AND text_content IS NOT NULL` 的文本来源；按 `page_no ASC, block_index ASC, block_id ASC` 使用 keyset 分页，禁止 OFFSET、全量物化或 Python 排序。
- Cursor 为版本化 opaque base64url 值，至少绑定 `parse_version_id/page_no/block_index/block_id`。解码失败、非 canonical 值或锚点不属于该 Parse 固定 422 `VALIDATION_ERROR`；Cursor 的 Parse 已不再是文件当前 active 时返回 409 `PARSE_VERSION_CHANGED`，不得静默切到新版本继续翻页。
- `next_cursor` 非空时本页必须恰有 `page_size` 项；末页为 null。页内身份和排序必须严格递增且无重复。
- `text_content` 复用数据库既有 NUL-free UTF-8 与长度约束；bbox 复用现有 Page 边界语义。响应不返回 `organization_id`、文件名、解析器/OCR 身份、置信度、Asset ID、对象键、哈希、来源映射、纠错历史、Actor 或自由文本原因。

## 4. Frontend 闭环

- `frontend/src/services/documentCorrections.ts` 增加严格 decoder 与分页 API；拒绝未知字段、非 canonical UUID、错误排序、跨页 Parse 漂移和非法 bbox。
- `DocumentCorrectionPanel` 的 `businessType` 扩展到四类，并逐字复用 Backend 角色矩阵；这只控制可见性，Backend 仍是权威门禁。
- `FileDetailView` 在 Actor 符合纠错权限/角色且文件 `stored+clean` 时读取第一页，提供加载更多、loading/empty/error/retry/Abort/stale-response 状态，并把响应投影为现有 `DocumentCorrectionEvidence`。不得自动提交纠错、自动激活或在客户端推导 Block/Parse ID。
- PARSE-004 成功后仍只显示 queued 候选；用户必须等待 Worker 完成并显式调用 PARSE-005。激活成功后重新加载第一页，旧 Cursor 和旧证据不得继续使用。
- 合同/发票现有业务详情纠错入口保持兼容；实现可复用通用读取，但本 CR 不要求删除既有字段证据投影。

## 5. API、数据与兼容性 delta

- 当前 checkout 基线为 98 个唯一 `/api/v1` operationId；本 CR `api_delta=+1`，operationId 固定为 `list_document_correction_blocks_v1`。
- `core_table_delta=0`、`alembic_migration_delta=0`、`permission_code_delta=0`、`operation_log_action_delta=0`。
- 不改变 PARSE-004/005/006 请求或响应，不改变 `DocumentBlock`、Parse、File 的持久化语义。
- 本 CR 与其他未批准 CR 的 delta 不互相吸收；若多个 CR 同批批准，最终绝对 operation 数由同步时的当前 OpenAPI 重新核对。

## 6. 必须验收

1. 四类业务角色、`files.manage OR system.configure`、read_only deny、跨组织 IDOR 和 404/403 顺序均有 API 负例。
2. stored+clean 正常读取；archived、非 clean 和无 active Parse 稳定失败且零业务副作用。
3. 真实 PostgreSQL 覆盖多页 keyset、相同 page/block index 的 UUID tie-break、非法 Cursor、活动 Parse 在翻页间切换和旧 Cursor 拒绝。
4. 响应字段严格最小化，不泄露 Asset、对象键、哈希、组织、原因或未授权正文；日志和错误不保存 `text_content`/cursor 原文。
5. Frontend 四类型权限可见性、分页、Abort、迟到响应、409 刷新、queued 候选和独立激活均通过；不得出现自动写入。
6. OpenAPI operation 唯一性和显式契约测试通过；Backend unit、PostgreSQL File 范围、Frontend typecheck/Vitest/build 通过。
7. Provider、外部网络、production、真实数据迁移、部署、提交和推送保持 `NOT_AUTHORIZED/NOT_RUN`。

## 7. 审批与同步边界

批准角色：产品、架构、Backend/API、Frontend、安全、测试。批准记录必须绑定：

```text
selected_option=DOCREAD-D-001,DOCREAD-D-002,DOCREAD-D-003,DOCREAD-D-004,DOCREAD-D-005
cr_revision=CR-029-R1
api_delta=+1
alembic_migration_delta=0
core_table_delta=0
environment_scope=contract+local_test
baseline_manifest_path=docs/request-manifest.md
baseline_manifest_raw_bytes=1281
baseline_manifest_sha256=64a86ad8af13bc1a906e856e325b29feeca738c3515ff6cc3c92582b275ddd2c
baseline_api_v1_operation_count=98
baseline_alembic_head=20260818_027
```

批准前不得修改 active Request、注册 Router、实现 Service/Repository/Frontend 或把本草案视为当前产品行为。批准后必须先同步 `Request/PRODUCT_REQUIREMENTS.md`、`Request/TECHNICAL_SPEC.md`、`Request/IMPLEMENTATION_PLAN.md` 与追踪材料，再实现 local/test。无论是否批准，本 CR 都不授权 Provider、production、真实数据迁移、部署、提交或推送。

`decision_snapshot_sha256`：全文行尾规范化为 LF，定位唯一精确标题 `## 8. 当前状态`，取其前全部行，去除多余尾随空行后保留一个 LF，对 UTF-8 bytes 计算 SHA-256。第 1～7 节任一规范修改必须提升 revision并重新批准。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-029-R1` |
| recommended option | `recommended-forward-v1 / DOCREAD-D-001～005` |
| decision snapshot | `c2f1f094dbd76575c3028665dc93e44fb1e8724d9937b0a711524120cb80f698 / 7910 bytes` |
| approval | `APPROVED；YHBX / product、architecture、backend_api、frontend、security、test / DOCREAD-D-001～005 / 2026-08-19 / direct Codex task approval` |
| Request sync | `COMPLETED；current manifest 8b953ca1d8f82b36ccd856f2db7d166f5709709f368d437f247e170e61812c56 / 1501 bytes` |
| runtime | `IMPLEMENTED AND VERIFIED FOR LOCAL/TEST；File 16 / Full 154×2 / Frontend 539 / full OpenAPI 100 PASS` |
| Provider / production / real-data migration | `NOT AUTHORIZED` |
| implementation count note | `signed baseline 98 counted 95 /api/v1 + 3 non-api operations；post-delta expected 97 /api/v1 and 100 full OpenAPI；delta +1 remains exact` |
