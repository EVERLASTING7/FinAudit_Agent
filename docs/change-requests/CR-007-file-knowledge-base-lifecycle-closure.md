# CR-007-R1：文件与知识库生命周期合同闭合

合同修订：`CR-007-R1`；权威生命周期状态仅见第 8 节。

日期：2026-08-07

## 1. 变更原因

`CR-001-R2/D-003/D-005` 已批准上传意图、内容去重和文件安全扫描六态，但准备实现 `files`、`knowledge_bases` 及 FILE/KB 接口时，现行 Request 仍留下无法由代码安全推断的合同缺口：

1. `knowledge_bases` 写成 `UNIQUE(organization_id, code)（活动记录）`，却未给出“活动”的数据库谓词；普通 UNIQUE 也无法表达条件唯一。
2. `knowledge_bases.status/default_*` 的空值、默认值、归档后可否恢复及归档对象能否继续写入没有冻结。
3. API 多次使用“授权知识库”，但 P0 的 PostgreSQL 权限事实来源未指定，也没有 `knowledge_base_permissions` 表。
4. FILE-006 返回 `files.archived_at`，`files` 表却没有该列；M1 的 `deleted_at` 不能同时充当归档时间。
5. 内容去重索引仍覆盖 `archived` 文件，但 Request 未说明相同内容再次上传时是复用、恢复、创建新事实还是拒绝。
6. `file_status` 与 `security_scan_status` 是两套独立状态机；当前“扫描失败将文件 rejected”与“`scan_failed` 可重试”无法同时成立。
7. `auto_process_requested=false` 不得跳过安全扫描，但架构又只在“需要自动处理”时创建 Job；FILE-001 的 `job_id` 却是非空响应字段。
8. policy 上传只要求目标知识库存在，尚未冻结“同组织且 active”的数据库约束和竞态处理。
9. `files/knowledge_bases` 引用 M1 模板，但实现时是否展开全部字段、归档是否写 `deleted_*`、非空表能否降级均不明确。
10. FILE-001/002 在 scan-only 与 full Job 之间缺少可执行的响应投影；该问题与全局 `GAP-018` 相交，但本 CR 只冻结 FILE 接口子集，不冒充关闭其余异步接口。

本 CR 只提出关闭上述缺口的最小合同，不增加 P0 表，不预占 Alembic revision，也不改变已批准的六态安全口径。未获批准前，不得据此修改 Request、迁移或运行时代码。

## 2. 推荐决策摘要

| 决策 | 推荐合同 | 直接影响 |
|---|---|---|
| `FILEKB-D-001` | 知识库 code 以 `status='active' AND deleted_at IS NULL` 条件唯一 | PostgreSQL 条件唯一索引 |
| `FILEKB-D-002` | 知识库默认 active；P0 固定 Top-5/NULL 阈值；参数变化待单独 Gate；归档不可逆且不等于软删除 | KB-002/004、状态触发器、GAP-001 |
| `FILEKB-D-003` | P0 不新增知识库 ACL 表；冻结有效角色、KB/POL/RET/QA 的 SQL 等价授权谓词 | KB/POL/RET/QA 权限查询 |
| `FILEKB-D-004` | `files` 显式增加 `archived_at`；仅 clean/stored 可归档；归档重复内容稳定拒绝 | FILE-001/002/006、去重索引、MinIO 保留 |
| `FILEKB-D-005` | 文件状态与扫描状态分离；冻结扫描结果码与 failed→queued 重试事务 | FILE-007、Worker、数据库触发器 |
| `FILEKB-D-006` | `auto_process_requested=false` 仍创建并返回 `scan_only` Job | FILE-001/002、Job 输入与响应 |
| `FILEKB-D-007` | policy 的目标知识库必须同组织且 active，并在锁内复验 | 文件写入触发器与 Service |
| `FILEKB-D-008` | 两表完整展开 M1；非空 downgrade 原子 fail closed | Schema、迁移与回滚测试 |

## 3. 推荐合同

### 3.1 FILEKB-D-001：知识库 code 的活动唯一谓词

推荐使用 PostgreSQL 条件唯一索引：

```sql
CREATE UNIQUE INDEX uq_knowledge_bases_active_code
ON knowledge_bases (organization_id, code)
WHERE status = 'active' AND deleted_at IS NULL;
```

- `code` 创建后不可修改；KB-004 不得把它加入 `changes` 白名单。
- 比较沿用数据库列的精确字符串语义；本 CR 不新增大小写折叠、trim 或 Unicode 规范化规则。API 只负责既有长度和非空校验，不能用“先查后写”替代唯一索引。
- 同组织允许保留多个相同 code 的已归档历史行，但最多一个未软删除的 active 行。
- 归档和创建同 code 新知识库必须分别持有目标行锁和同组织/code 的事务级 advisory lock，最终仍以条件唯一索引为裁决者。
- `deleted_at` 仅用于 M1 软删除语义；P0 知识库归档不会设置它。

不采用：

1. 普通 `UNIQUE(organization_id, code)`：它表达的是终身唯一，与 API 的“活动唯一”不一致。
2. 仅检查 `deleted_at IS NULL`：已归档但未软删除的知识库会错误占用活动 code。
3. 仅在 Service 查询重复：并发创建会穿透检查。

### 3.2 FILEKB-D-002：知识库状态、默认值和不可逆归档

`knowledge_bases` 的 P0 合同固定为：

- `status VARCHAR(20) NOT NULL DEFAULT 'active'`，CHECK 只允许 `active/archived`。
- `default_top_k INTEGER NOT NULL DEFAULT 5`，P0 数据库 CHECK 固定为 `default_top_k = 5`。KB-002 中该字段必须省略或精确为 5；其他值返回 `422 RETRIEVAL_CONFIG_NOT_APPROVED`，不得把“任意正数”作为未评测旁路。
- `default_score_threshold NUMERIC(8,6) NULL DEFAULT NULL`，P0 数据库 CHECK 固定为 `default_score_threshold IS NULL`。NULL 的唯一语义是“不向向量检索传递 score cutoff，只按获准的 Top-5 取候选”，不得转换成数值 `0`、示例值 `0.650000` 或环境默认；它不绕过后续权限、状态、日期、引用或证据充分性门禁。
- KB-002 创建时 `default_top_k` 必须省略或精确为 5，`default_score_threshold` 必须省略或为 NULL；当前 API 中 `0.650000` 仅为未获批准的示例，不能成为种子。由于当前正式门禁只冻结 Hit@5，且 GAP-001 尚未裁决正式评测集数量层级，KB-004 的 `changes` 在 P0 只允许 `name/description/status`，提交任一检索参数固定返回 `409 RETRIEVAL_CONFIG_CHANGE_REQUIRES_CR`，不改行、不增版本、不写“已变更”日志。未来允许参数变化必须另行批准版本化评测 Gate、精确 `status='succeeded'`、Run 参数的 NULL-safe 相等、approved 数据集、同知识库活动索引及可重算指标谓词；不得只凭自由文本理由或私有 `metrics_json` 字段写入。
- KB-002 创建后为 active。唯一允许的状态变化是 `active -> archived`；`archived` 为 P0 终态。
- KB-004 没有 `Idempotency-Key`，因此不伪造动作幂等：归档必须携带当前 `row_version`、非空 reason、操作者和 trace_id，在同一事务中只执行一次 `active -> archived`、递增 `row_version` 并写 operation log；相同旧请求重放按当前事实返回 `409 RESOURCE_VERSION_CONFLICT`，对 archived 行使用新版本发起任何 PATCH 返回 `409 KNOWLEDGE_BASE_NOT_ACTIVE`，均不再次写日志或递增版本。
- 归档后禁止修改名称、描述、默认检索参数，禁止新上传到该库、创建/修改制度、构建或激活索引、运行新检索或把它作为新业务对象目标；历史任务、评测和审计证据仍可按原权限读取。
- 归档不会级联改写制度、索引、文件，不设置 M1 `deleted_at/deleted_by/delete_reason`，也不自动释放、复制或重建任何派生数据。
- P0 不提供 `archived -> active`、restore、unarchive 或复用旧 ID 的动作。确需恢复时走新的 CR；当前可创建新的知识库事实，条件唯一索引允许它在旧记录归档后复用 code，但不会自动继承旧制度或索引。

替代方案：

1. **增加恢复动作**：需要恢复权限、并发、code 冲突、子对象恢复和审计合同，超出最小 P0，暂不采用。
2. **归档即写 `deleted_at`**：会混淆可审计生命周期和软删除，并改变权限、去重及条件唯一语义，不采用。
3. **归档级联子对象**：可能破坏历史检索和任务快照，不采用。

### 3.3 FILEKB-D-003：P0 知识库授权事实来源

P0 不新增 `knowledge_base_permissions`、用户级 grant 或 JSON ACL。Backend 每次授权只使用 PostgreSQL 中的用户、有效角色、知识库和制度事实；前端、Redis、Qdrant payload、`scope_json` 和自由文本都不能授予权限。

**有效角色谓词**固定在数据库事务时间 `auth_time=transaction_timestamp()` 求值：用户必须 `status='active' AND deleted_at IS NULL` 且与资源同组织；角色必须 `is_enabled=TRUE`；`user_roles.assigned_at <= auth_time`、`revoked_at IS NULL`、`expires_at IS NULL OR auth_time < expires_at`。`assignment_source='break_glass'` 时还必须存在匹配的已批准请求，满足 `effective_from <= auth_time < expires_at` 且未撤销；后台尚未把超时行写成 expired 不能延长授权。未知角色码和关系不完整一律 fail closed。

**可供普通读取或检索的制度谓词**固定为：同组织、所属 KB `status='active' AND deleted_at IS NULL`；制度 `deleted_at IS NULL`、`status IN ('published','superseded')`、`access_scope='internal'`、`effective_from <= baseline_date`、`effective_to IS NULL OR baseline_date < effective_to`，并且调用者至少一个有效角色精确出现在 `allowed_role_codes`。空数组是 deny-all；客户端不能提交额外角色。`revoked/archived/draft/pending_business_review/approved` 不参与新普通读取、RET 或 QA。

端点投影固定如下：

| 端点/动作 | SQL 等价授权口径 |
|---|---|
| KB-001/KB-003 管理读取 | 有效 `system_admin` 或 `audit_reviewer` 可读取同组织、未软删除的 active/archived KB；`system_admin` 只得到技术配置、索引状态和必要汇总，不能借此获得制度业务审批权；`audit_reviewer` 的制度正文/流程能力仍受 POL 端点矩阵约束 |
| KB-001/KB-003 普通读取 | `finance_reviewer/contract_admin/read_only` 只可读取 active KB，且以 PostgreSQL `CURRENT_DATE` 作为固定 `baseline_date`，至少存在一条满足上述普通制度谓词的制度；制度计数和摘要只统计该允许集合，未授权存在性不得泄露 |
| KB-002/KB-004 | 仅同组织有效 `system_admin`；archived KB 只读且所有 PATCH 失败关闭；状态归档、参数证据和职责边界按本 CR 3.2 执行 |
| POL 管理流程 | 先满足各 POL 接口既有角色矩阵，再强制同组织和 KB 非软删除；`audit_reviewer` 处理业务审批，`system_admin` 只执行明确列出的技术上传/发布动作，任何一个角色都不能代替双角色流程 |
| POL 普通列表/详情 | `finance_reviewer/contract_admin/read_only` 采用请求明确的业务基准日；若端点没有该参数则使用 PostgreSQL `CURRENT_DATE`，并逐制度应用上述普通谓词 |
| RET-001/QA-001 | 使用请求必填的 `baseline_date`，逐制度应用上述普通谓词；接口角色矩阵只是入口条件，不产生 allowlist bypass。RET 的受控 `permission_context` 只能由服务端从有效角色生成，管理测试最多选择其有效角色的子集，不能增加角色、组织、状态或日期权限 |

知识库可见不等于其中所有制度可见。RET/QA 的每个最终命中和每条引用在返回或采用前都必须重新按同一 PostgreSQL 谓词校验；Qdrant payload 只能承载派生过滤字段，不能授权。本 CR 只冻结授权集合，不裁决 `GAP-020` 中“PostgreSQL 先生成允许 ID”与“Qdrant 初筛”的执行顺序；RET/QA 的完整实现仍须等待该 Gap 的单独批准，但无论顺序如何都不得省略最终 PostgreSQL 校验。

archived 或软删除知识库不得用于新检索。历史任务、评测和审计只能通过已冻结快照、当时的权限上下文及专用历史读取端点访问，不能因当前列表不可见而篡改历史事实。需要用户级、部门级、属性级或跨组织授权时必须新增 CR 和明确数据模型。

替代方案：

1. **新增知识库 ACL 表**：可以支持细粒度授权，但会新增 P0 表、接口和管理 UI，当前没有批准需求，暂不采用。
2. **所有登录用户可见 active 知识库**：会泄露未授权制度存在性，不采用。
3. **只信任 Qdrant `allowed_role_codes`**：派生数据可能过期且不是业务事实来源，不采用。

### 3.4 FILEKB-D-004：文件归档时间和归档重复上传

在 `files` 显式增加：

```sql
archived_at TIMESTAMPTZ NULL
```

并建立状态一致性约束/触发器：

- `status='archived'` 当且仅当 `archived_at IS NOT NULL`；其他状态的 `archived_at` 必须为 NULL。
- FILE-006 只允许 `status='stored' AND security_scan_status='clean' AND deleted_at IS NULL` 的文件归档；`uploaded/validating/rejected/archived` 均返回稳定 `409 FILE_STATE_CONFLICT`。`rejected` 是 P0 终态，不允许再转 archived。
- FILE-006 使用 PostgreSQL 当前时间原子写入 `status='archived'`、`archived_at`、M1 更新字段和新 `row_version`；API 返回该持久化时间。相同 Idempotency-Key 与相同规范化请求重放返回第一次结果；不同请求命中 archived 行返回状态冲突，不改写时间或版本。
- 文件归档不设置 M1 `deleted_at`，不物理删除或移动 MinIO 历史证据；clean/stored 对象已经位于 originals，归档后继续受 originals 的保留、备份和不可覆盖策略保护，不受 quarantine 短期生命周期删除。reason 保存在不可变 operation log，不新增重复自由文本列。
- P0 文件归档同样不可恢复。归档事务锁定文件，并拒绝任何 `queued/running/cancel_requested` 的关联 Job；历史解析、Markdown、业务对象、报告或快照引用不阻止归档，也不得被覆盖或级联改写，它们只阻止软删/物理删。`RESOURCE_IN_USE` 仅用于仍会写该文件事实的活动 Job 或正在提交的版本激活事务，不能把已有历史引用误报为“不可归档”。

现有内容去重索引继续把 archived 行视为已存在事实：

```sql
CREATE UNIQUE INDEX uq_files_content_active
ON files (organization_id, sha256, size_bytes)
WHERE deleted_at IS NULL;
```

相同组织、SHA-256 和大小命中 archived 文件时使用稳定错误 `FILE_ARCHIVED_DUPLICATE`：

- 不返回可被误认为已恢复的 `reused=true` 成功；
- 不修改分类、目标知识库或 `auto_process_requested`；
- 不创建新文件、Job、业务对象或 MinIO 副本；
- 单文件接口返回 HTTP 409；批量接口总体仍返回 202，把该项放入 `rejected`，逐项携带 `code='FILE_ARCHIVED_DUPLICATE'` 与 `http_status=409`，其余合法项继续处理；
- 错误响应只返回调用方已获授权的稳定错误和 trace_id，不回显旧文件敏感元数据。

相同键命中 `rejected` 文件时同样不得穿透唯一性创建第二行，固定返回 `FILE_REJECTED_DUPLICATE`：单文件为 HTTP 409；批量总体 202 且该项进入 `rejected[]`、`http_status=409`。它不复用旧 Job、不允许 false→true 意图提升、不写 MinIO 副本，也不重新运行相同字节；初始扩展名/大小/MIME/文件头预校验失败因从未创建 `files` 行，不属于此分支。上传事务必须持有组织+SHA-256+size 的 advisory lock 并以该唯一索引作最终并发裁决，Service “先查后写”不能替代约束。

替代方案：

1. **自动恢复归档文件**：缺少恢复权限、引用影响和状态回滚合同，不采用。
2. **把 archived 排除在去重索引外并创建新行**：会为同一内容创建第二个文件事实并分裂证据链，不采用。
3. **返回成功但保持 archived**：会让客户端误以为上传可处理，不采用。

### 3.5 FILEKB-D-005：文件状态、扫描状态与重试

两套状态机分别冻结，API/UI 不得合并：

```text
file_status:
uploaded -> validating -> stored -> archived
                    \-> rejected（终态）

security_scan_status:
pending -> clean
        -> infected
        -> scan_failed -> pending（受控重试）
        -> unsupported
        -> not_configured -> pending（仅 local_offline/fixed_test 且扫描依赖已恢复）
```

状态联动固定为：

| 扫描结果 | 文件状态 | Job/当前 scan Step | 自动后续 | 重试 |
|---|---|---|---|---|
| 初始 `pending` | `uploaded` | Job `queued`；尚无 Step | 仅允许已提交的扫描 Job；禁止解析 | FILE-001/002 成功返回的合法初始组合 |
| Worker claim 后 `pending` | `validating` | Job `running,stage='scan'`；唯一 scan Step `running` | 禁止解析 | 已有活动扫描时返回 `ACTIVE_JOB_EXISTS` |
| `clean` + scan-only | `stored` | scan Step `succeeded`；Job `succeeded` | 不创建解析；若有效意图已升为 true，则同事务创建唯一 full Job | P0 不重扫 |
| `clean` + full | `stored` | scan Step `succeeded`；Job 保持 `running`，同事务切换到冻结 Handler 的下一 Step/stage | 进入获准业务流水线 | P0 不重扫 |
| `infected` | `rejected` | scan Step/Job 均 `failed`，写 `ACTIVE_CONTENT_DETECTED` 或 `MALWARE_DETECTED` | 隔离、拒绝 | 不可重试 |
| `scan_failed` | 保持 `validating` | scan Step/Job 均 `failed`，写对应可重试 Job 错误码 | 禁止解析 | 仅稳定可恢复错误码可重试 |
| `unsupported` | `rejected` | scan Step/Job 均 `failed`，写对应确定性拒绝码 | 确定性拒绝 | 不可重试 |
| `not_configured` | 仅 local_offline/fixed_test 保持 `validating` | scan Step/Job 均 `failed`；Step 摘要保存 `SCANNER_NOT_CONFIGURED`，Job/Step `error_code='DEPENDENCY_UNAVAILABLE'` | 禁止解析 | 仅上述两类 Profile、依赖健康后可重试；staging/production 不得产生该值 |

- `uploaded,pending` 只能由接受上传与创建扫描 Job 的同一事务产生；文件 Handler 的 Worker claim 必须把 CR-004 的 Job `queued -> running`、attempt/Lease 写入、唯一 running scan Step 创建和文件 `uploaded -> validating` 放在同一 fencing/CAS 事务，文件条件更新 0 行时整次 claim 回滚。除此之外，跨列触发器拒绝 `uploaded` 与任何非 pending 扫描态、`stored` 与任何非 clean 扫描态、`rejected` 与任何非 infected/unsupported 扫描态，以及 `archived` 与任何非 clean 扫描态。
- `file_scan/file_process` 在 scan 阶段（含尚未 claim 的 queued scan stage）不得进入 CR-004 的通用取消终态；取消入口必须在改变 Job 状态前固定返回 `409 JOB_NOT_CANCELLABLE_IN_SCAN_STAGE`。扫描取得确定性结果或 clean 后进入后续阶段，才可按该 Handler 明确声明的安全检查点使用 CR-004 取消合同。不得以取消留下 `uploaded|validating + pending` 且终身唯一 Job 已终结的孤儿文件。
- `rejected` 只用于确定性内容拒绝，不能表示可恢复扫描故障，也不能归档。上传前扩展名、大小、MIME/文件头校验失败时不创建 `files` 行；API 直接返回既有 4xx 错误。
- 文件扫描结果码字典固定为 `file-scan-outcome-v1`：

```json
{"terminal_error_codes":{"clean":[],"infected":["ACTIVE_CONTENT_DETECTED","MALWARE_DETECTED"],"not_configured":["SCANNER_NOT_CONFIGURED"],"scan_failed":["DEPENDENCY_TIMEOUT","DEPENDENCY_UNAVAILABLE","RATE_LIMITED","STORAGE_TRANSIENT"],"unsupported":["FILE_DECODE_INVALID","MAGIC_BYTES_MISMATCH","MEDIA_TYPE_UNSUPPORTED"]},"version":"file-scan-outcome-v1"}
```

上述 UTF-8 JCS bytes 的 SHA-256 固定为 `5bbab9c230bfb08774d97af12919da74009201dd865afac1d0a56bab4e63cc1f`，版本/hash 随 Job 输入冻结。终态 Scanner 事实使用唯一 `file-scan-step-outcome-v1`；`summary_json` 的全部键始终存在且精确为 `version/scan_outcome/scan_outcome_code/scan_policy_version/scan_policy_hash/scanner_profile_class/scanner_registry_version/scanner_registry_hash/scanner_adapter_code/scanner_version/scanner_definition_version/scanner_invoked`。`version='file-scan-step-outcome-v1'`；clean 的 code 为 JSON null，其余终态 code 必须来自上表；`scanner_invoked` 是严格 boolean，表示调用已经交给获准 Adapter，不要求取得正常结果。

NULL/call 矩阵固定为：

| outcome/code | Registry 三元组 | Adapter/Scanner/Definition | `scanner_invoked` |
|---|---|---|---:|
| `clean` 或 `infected` | 全部非空 | Adapter/Scanner 非空；Definition 按 Registry entry 的 required_exact/null_only | true |
| `scan_failed + STORAGE_TRANSIENT` | 全部 JSON null | 全部 JSON null | false |
| `scan_failed + DEPENDENCY_TIMEOUT/DEPENDENCY_UNAVAILABLE/RATE_LIMITED` | 全部非空 | Adapter/Scanner 非空；Definition 按 entry mode | true |
| `unsupported` | 全部 JSON null | 全部 JSON null | false |
| `not_configured` | 等于当前 Job 冻结的非空三元组 | 全部 JSON null | false |

`DEPENDENCY_UNAVAILABLE` 只有在配置完备且调用已交给 Adapter 后才可作为 scan_failed；未配置必须走 not_configured。not_configured 只允许 `local_offline/fixed_test`；staging/production 缺 current Profile 或 Scanner 时启动/Job 创建失败关闭，不得写业务终态。所有非空 Scanner 组合调用 CR-010 的 history validator，并逐字等于不可变 Job input 三元组；Profile 轮换不得改变已开始 Job 的合法终态。Job/Step `error_code` 仍服从 CR-004 retry Policy；确定性拒绝码同时写 `files.rejection_code`。扫描器原始输出、路径、自由文本异常和凭据不得入库；必要 operation log 依赖获批并落地的 CR-006。

- 没有 Scanner outcome 的基础设施终结不得使用上述 Schema。Lease recovery 把旧 Step 终结为 `LEASE_EXPIRED` 时，`summary_json` 必须改用独立 `file-scan-attempt-termination-v1`，精确 JCS 对象为 `{"termination_code":"LEASE_EXPIRED","version":"file-scan-attempt-termination-v1"}`；不得加入 outcome、Registry 或 scanner_invoked 字段。同一 Step 不得同时携带两类摘要。若 scan 阶段 Lease recovery 在 `attempt_no=max_attempts` 时写入 Job `WORKER_LOST`，同一 fencing/CAS 事务还必须把文件从 `uploaded|validating + pending` 归一为 `validating + scan_failed`，不得留下无恢复语义的 pending 文件。此时 FILE-007 是否仍可用户重试只按冻结的 retry Policy 与 `attempt_no < max_attempts` 判断；次数已耗尽时派生 `retryable=false`，`follow_up_processing_pending=false`。
- FILE-007 `stage=scan` 依赖获批的 `CR-004/REL-D-001～003`。同一事务必须锁定文件、原 Job 和幂等记录，仅在文件为 `validating + scan_failed`（或 local_offline/fixed_test 的 `validating + not_configured`）、Job 为 failed、冻结的 retry Policy 版本/hash 有效、Job `error_code` 属于该 Policy、次数未耗尽且不存在第二个同 scope Job 时，执行原 Job `failed -> queued`，清空 `stage/started_at/finished_at/worker_id/lease_owner/lease_expires_at/heartbeat_at/next_retry_at/error_code/error_message`，保持当前 `attempt_no` 不变，把扫描态改回 pending，并追加下一条 Job Outbox。`not_configured` 的 Job 错误码固定映射为 CR-004 已批准白名单中的 `DEPENDENCY_UNAVAILABLE`；`SCANNER_NOT_CONFIGURED` 只作为文件扫描结果码保存在不可变 Step 摘要，因此两套字典不互相冒充。Worker 下一次成功 claim 是 queued 流程中 `attempt_no` 的唯一递增点并创建新的 running Step；重试 API 返回 `scheduled_attempt_no=旧 attempt_no+1`，不再声称已经递增。
- FILE-007 的本 CR scan 分支请求 Body 精确为 `reason/row_version/stage`：`stage` 必须为 `scan`，`reason=btrim(reason)` 且长度 1..500，`row_version` 是原 Job 当前正整数版本而不是 file row version。Idempotency hash 对固定 `POST/FILE-007/path file_id/规范化 Body` 计算；同组织、用户、Key/hash 的完成重放必须在文件、Job、次数、错误和当前 Profile 等可变门禁前返回首次完整 202 响应，即使 Job 后来已 claim/终结；同 Key 不同 hash 返回 `IDEMPOTENCY_CONFLICT`。新 Key 才执行单条 Job/file CAS，影响零行时不可见资源为 404，非可重试状态为 `JOB_NOT_RETRYABLE`，其余版本竞争为 `JOB_VERSION_CONFLICT`。
- FILE-007 成功响应的 `data` 精确为 `attempt_no/job_id/job_url/row_version/scheduled_attempt_no/stage/status`：`attempt_no` 是重试事务前的当前值，`scheduled_attempt_no=attempt_no+1`，`row_version` 是本次 Job `failed -> queued` 后的新值，`status='queued'`，`stage=null`；真正 claim 时才写 `stage='scan'` 并递增 attempt。首次成功的 Job/file 状态、Outbox、幂等完整响应和 `file.processing.retry` operation log 同事务提交；重放不新增任一事实。本 CR 只闭合 `stage=scan`；`parse/extraction/markdown/all` 仍不得据此宣称合同已闭合。
- 旧 failed Step 和尝试证据保持不可变；重试请求本身不预建 running Step。Job、文件、幂等结果与 Outbox 任一步失败全部回滚。不得原地把失败扫描结果改成 clean，也不得创建第二个同 scope Job。
- `clean/infected/unsupported`、未知状态、未知版本/hash/error code、staging/production `not_configured` 和次数耗尽一律 `409 JOB_NOT_RETRYABLE`。`WORKER_LOST/LEASE_EXPIRED` 走 CR-004 的 Lease fencing 恢复，不通过 FILE-007 伪装成一次新的用户重试。
- 扫描成功提交 `security_scan_status='clean'`、`file_status='stored'`、scan Step 终态与上表规定的 Job 终态/下一阶段必须在匹配最新 fencing tuple 的同一事务原子完成；解析 Worker 还要在读取输入时复验 clean、stored、未归档。
- 感染/不支持的拒绝提交扫描状态、文件状态、稳定 rejection code、failed Step/Job 和审计记录必须原子；任何失败不得把对象移动到 originals。

### 3.6 FILEKB-D-006：`auto_process_requested=false` 的 scan-only Job

每个首次接受的新文件都必须创建一个异步 Job，并立即返回非空 `job_id/job_url/job_status`：

- `auto_process_requested=true`：创建 `job_type='file_process'`，冻结 `processing_scope='full'`。首次上传时安全扫描是第一道强制步骤；只有同一 Job 成功写入 clean/stored 后才继续解析及其后续允许阶段。
- `auto_process_requested=false`：创建 `job_type='file_scan'`，冻结 `processing_scope='scan_only'`；Job 只完成隔离对象扫描和 stored/rejected 裁决，不创建解析、Markdown、分块、索引或业务对象。
- 两类 Job 的权威整数列 `async_jobs.input_schema_version` 均固定为 `1`，不在 JSON 中保存第二份版本。`file_scan.input_json` 只允许且始终包含 `auto_process_requested/file_id/intended_business_type/processing_scope/scan_policy_hash/scan_policy_version/scanner_profile_class/scanner_registry_hash/scanner_registry_version/target_knowledge_base_id` 十个键；意图固定 false、scope 固定 scan_only。`file_process.input_json` 只允许且始终包含上述十键及 `source_scan_evidence_hash/source_scan_job_id/source_scan_step_id` 三键；意图固定 true、scope 固定 full。会实际扫描的初始 Job 在创建事务中调用 CR-010 current profile validator，冻结非空 Registry 三元组；首次 full 的三个 source 字段全为 null。从 scan-only clean 派生的 full Job 三个 source 字段全非空，其 Registry 三元组必须来自 source evidence 的已激活历史 tuple，不强制替换成此刻 current，也不再次调用 Scanner。目标 KB 不适用时显式为 JSON null；UUID 小写带连字符，hash 小写 64 位十六进制；未知键、缺键、混合 null 组或不一致值均拒绝。`input_hash=SHA256(JCS(input_json))`，Worker 不读取原 HTTP 请求、前端状态或环境默认补全输入。两份更新后的 input Schema bytes/hash 必须进入 CR-004 Handler Registry 批准包；缺失时 runtime 继续阻塞。
- `source_scan_evidence_hash` 使用唯一 `file-scan-evidence-v1`：精确 JCS 对象只含 `file_id/file_sha256/file_size_bytes/scan_job_id/scan_policy_hash/scan_policy_version/scan_step_id/scanner_adapter_code/scanner_definition_version/scanner_invoked/scanner_profile_class/scanner_registry_hash/scanner_registry_version/scanner_version/security_scan_status/version`。其中状态固定 clean、版本固定 `file-scan-evidence-v1`、`scanner_invoked=true`，大小是非负安全整数；Registry 三元组必须同时与 source Job input 和 source Step 逐字相等，Adapter/Scanner、按 entry mode 可空的 Definition 与 `scanner_invoked` 只与 source Step 逐字相等，Policy version/hash 同时与 source Job input 和 source Step 相等，file_id/hash/size 与 PostgreSQL 文件事实相等。身份关系还必须显式满足 `evidence.scan_job_id = full Job.input_json.source_scan_job_id = source Job.id`、`evidence.scan_step_id = full Job.input_json.source_scan_step_id = source Step.id`、`evidence.security_scan_status = source Step.summary_json.scan_outcome = files.security_scan_status = 'clean'`；hash 为该 JCS bytes 的 SHA-256。提交 full Job 前，deferred consumer trigger 必须证明上述全部等式、source Job 与目标文件同组织、`job_type='file_scan'`、`resource_type='file'`、`resource_id=file_id`、`status='succeeded'`，source Step 属于该 Job、`step_code='scan'`、`status='succeeded'`，文件当前为 clean/stored；用 CR-010 history validator 验证该已激活 tuple/entry/outcome，并重算文件 hash/size、Policy、Step 和 evidence hash。跨文件、失败/旧 Step、installed-only/未知/跨 class Profile、错误 Policy、伪造 hash、任一 ID/状态关系不等或 Profile 轮换后擅自替换 tuple 均拒绝。
- 为保证跨终态的“最多一个”，PostgreSQL 在 `async_jobs` 上精确创建 `CREATE UNIQUE INDEX uq_async_jobs_file_job_type_lifetime ON async_jobs(resource_type, resource_id, job_type) WHERE resource_type='file' AND job_type IN ('file_scan','file_process')`；同一文件终身最多一个 scan-only Job 和一个 full Job，技术重试只复用原 Job。上传/意图提升事务先锁文件行，再创建候选 Job，最终以该索引裁决并发；现有只覆盖活动 Job 的通用索引不能代替本约束。该索引及校验 source Job/Step/evidence 的 trigger/function 明确属于本 CR revision，不得作为 CR-004 的既有对象遗漏于回滚。
- FILE-001/002 响应增加只读派生字段 `job_scope='full|scan_only'` 与 `follow_up_processing_pending:boolean`，二者不是 `files` 或 `async_jobs` 新列。`job_id` 表示本次立即接受或复用的 Job，不得把 scan-only 伪装为全链路处理。
- 相同内容、相同分类/目标和相同有效意图的重复上传只复用既有对应 Job，不创建第二个同 scope Job；archived/rejected 重复分别按 3.4 的两个稳定 409 分支处理，不进入复用或意图提升。
- 既有 false 被新请求原子提升为 true 时，不修改已存在 scan-only Job 的不可变输入：若扫描已 clean，则创建最多一个新的 `file_process` Job 并返回它；该 full Job 的首个步骤是本地 `security_scan_evidence_check`，只校验并引用冻结的 scan-only 成功证据，不再次调用 Scanner。若扫描仍 pending/running，则返回现有 scan-only Job、`auto_process_requested=true` 和 `follow_up_processing_pending=true`，在扫描 clean 的提交事务中幂等创建唯一 full Job；若扫描失败或确定性拒绝，不隐式重试或创建 full Job。其后只有 `scan_failed/not_configured` 按 FILE-007 合法重试并最终 clean 时，才按已生效的 true 意图幂等创建 full Job。
- 因此，批准后须把旧文案“不创建第二个 Job”收窄为“不为相同 scope/输入创建第二个 Job”；一次 false→true 提升允许一条已留痕的 scan-only Job 和最多一条 full Job。这是解决安全扫描不可跳过与 Job 输入不可变冲突的必要合同修正，不增加新的手工启动 API。

FILE-001 的 `data` 精确为 `file_id/status/reused/intended_business_type/target_knowledge_base_id/auto_process_requested/job_id/job_url/job_status/stage/job_scope/follow_up_processing_pending`。FILE-002 的 `data` 精确为 `batch_id/accepted/rejected/summary`；每个 `accepted[]` 项精确为 `item_index/file_name/file_id/status/reused/intended_business_type/target_knowledge_base_id/auto_process_requested/job_id/job_url/job_status/stage/job_scope/follow_up_processing_pending`，其中 `file_name` 是服务端消毒后的显示名；每个 `rejected[]` 项精确为 `item_index/file_name/code/http_status`，不得返回局部 `job_id` 或旧文件元数据。`stage` 来自 Job 当前权威 stage；新 full/scan-only 均为 `scan`，从 clean scan-only 创建的 follow-up full 为 `security_scan_evidence_check`。

`follow_up_processing_pending` 真值固定为：返回 full Job 时 false；有效意图为 false 的 scan-only 为 false；有效意图已为 true 且当前只存在 pending/running，或仍满足冻结 retry/Lease Policy、次数和状态门禁的 scan_failed 或仅 `local_offline/fixed_test` 的 not_configured scan-only 时 true；scan-only clean 后创建并返回 full Job时 false；次数耗尽的 `WORKER_LOST`、infected/unsupported/rejected 或任何不会自动产生 full Job 的终态为 false。返回哪个 Job 也固定：存在 full Job就返回它，否则返回唯一 scan-only Job。FILE-002 `summary` 只按 accepted/rejected 数组长度计算，不把逐项 409 算作 accepted。本段只关闭 FILE 子集；其他异步接口继续由 `GAP-018` 的统一 `AcceptedJobResponse` CR 处理，不能据此宣称全局 Gap 已关闭。

替代方案：

1. **false 时不建 Job**：无法执行或追踪强制安全扫描，与非空 `job_id` 响应冲突，不采用。
2. **把 scan-only Job 原地改成 full**：会改写不可变 Job 输入和 input_hash，不采用。
3. **同步 HTTP 扫描**：会把长任务放回同步 API，并破坏 202/P95 合同，不采用。

### 3.7 FILEKB-D-007：目标知识库同组织且 active

当 `intended_business_type='policy'` 时，`target_knowledge_base_id` 必须满足：

- 非空并引用存在的 `knowledge_bases.id`；
- `knowledge_bases.organization_id = files.organization_id`；
- `knowledge_bases.status='active' AND deleted_at IS NULL`。

其他业务类型的目标知识库必须为 NULL。该规则同时在 API Schema、Service 和 PostgreSQL 约束触发器执行：

- `files` INSERT 后，`id/organization_id/original_name/extension/mime_type/detected_mime_type/size_bytes/sha256/minio_bucket/minio_object_key/intended_business_type/target_knowledge_base_id/uploaded_by/created_at/created_by` 永久不可修改；任一实际 UPDATE 由 PostgreSQL 直接拒绝，不能通过“改完再复验”漂移文件身份。唯一业务意图变化是 `auto_process_requested: false -> true`，禁止 true -> false。P0 的 `deleted_at/deleted_by/delete_reason` 始终为 NULL；只允许第 3.5 节状态矩阵原子修改 `status/security_scan_status` 及配套 `rejection_code/rejection_message/stored_at/archived_at/row_version/updated_at/updated_by`。
- Service 在上传/去重提升事务中锁定目标知识库行并复验状态；consumer trigger 只在 `files` INSERT 和合法 false -> true 意图提升时复验既有不可变目标关系仍为同组织 active，阻断直接 SQL 和竞态。文件的归档、扫描状态或 M1 更新时间不重新要求 KB active，因此 KB 后续归档不会阻断合法历史文件归档或状态留痕。
- 不存在、跨组织或不可见目标统一返回 404 `RESOURCE_NOT_FOUND`，避免泄露；调用方可见但已归档的目标返回 409 `KNOWLEDGE_BASE_NOT_ACTIVE`。
- 去重命中后若旧目标知识库已归档，不得修改意图或创建/提升 Job；返回 `KNOWLEDGE_BASE_NOT_ACTIVE`。历史文件关联保持不变。
- 知识库归档与文件上传/制度创建使用同一锁顺序：先组织/code advisory lock（需要时），再知识库行，再文件行；归档提交后任何新写入必须失败，先提交的合法上传保留历史关联但后续创建制度前仍需复验 active。

不采用：仅使用普通 FK（不能校验组织和状态）、根据文件名猜测知识库、把跨组织错误区分返回给未授权调用方。

### 3.8 FILEKB-D-008：M1 展开、迁移和 fail-closed downgrade

`files` 与 `knowledge_bases` 都必须把 M1 占位符展开为真实列。已单独声明的 `id/organization_id` 不重复创建，其余至少包含：

```text
row_version, created_at, created_by, updated_at, updated_by,
deleted_at, deleted_by, delete_reason
```

- 类型、默认值和外键严格沿用数据库设计的 M1 模板；`files.archived_at` 是本 CR 额外生命周期列，不属于 M1 `deleted_at` 的别名。
- 本 CR 的 P0 `deleted_at/deleted_by/delete_reason` 必须始终同时为 NULL，任何 INSERT/UPDATE 非空值都由数据库触发器拒绝；P0 FILE/KB 公共 API 不提供软删除动作。未来若要启用 M1 软删除，必须新建 CR/revision，冻结动作、权限、状态与历史数据合同，不能复用本 revision 的占位列绕过审批。
- `status='archived'` 与 `deleted_at IS NOT NULL` 是不同事实；归档不得触发 M1 软删除，软删除也不得被客户端伪装为归档响应。
- 本 CR 不预占 revision。批准与生成 migration 时必须记录并校验实现前 Alembic head；该绑定 head 不得含 `knowledge_bases/files` 或本 revision 的任一命名对象。预检通过后，获批 revision 必须直接创建带最终 M1/生命周期列、CHECK、条件唯一索引和触发器的两表，不先制造弱 Schema；若预检不满足，CR-007-R1 不可签署或实施，必须重新评估并提升 revision，禁止在运行时猜测“首次建表”还是“增量修改”。
- 该首次建表 revision 不执行已有数据 backfill，也不存在恢复旧列定义的分支；`archived_at`、M1 列/default/CHECK 都随表一次创建。未来对非空旧表的增量改造必须另立 CR，明确冲突扫描、权威回填和前向修复，不复用本 revision。
- 本 revision 的独立对象 allowlist 固定为三个索引 `uq_knowledge_bases_active_code/uq_files_content_active/uq_async_jobs_file_job_type_lifetime`，七个 trigger function `enforce_knowledge_bases_state_v1()/reject_knowledge_bases_delete_truncate_v1()/enforce_files_state_v1()/validate_file_target_knowledge_base_v1()/validate_file_job_integrity_v1()/validate_file_scan_evidence_v1()/reject_files_delete_truncate_v1()`，以及十个 trigger `trg_knowledge_bases_state_v1/trg_knowledge_bases_delete_v1/trg_knowledge_bases_truncate_v1/trg_files_state_v1/trg_files_target_kb_v1/trg_files_job_integrity_v1/trg_files_delete_v1/trg_files_truncate_v1/trg_async_jobs_file_integrity_v1/trg_async_job_steps_file_evidence_v1`。表内 PK/FK/CHECK 和前两个索引随本 revision 完整创建的表所有；禁止生成未登记 helper。
- 上述函数位于 `public`、归 `finaudit_migrator` 所有，固定 `SECURITY INVOKER` 与 `SET search_path = pg_catalog, public, pg_temp`，函数体仍完全限定 relation/function/type、无动态 SQL/网络/文件/secret；全部 `REVOKE ALL FROM PUBLIC`，不向登录角色授予 trigger function 的直接 EXECUTE。本 revision 只调用 CR-010 的共享 current/history validator，不拥有、覆盖或在 downgrade 删除 `scanner_registry_profiles` 或任何 `validate_scanner_registry*_v1`。
- downgrade 在单一事务先 `SET LOCAL lock_timeout='5s'`，再按 `knowledge_bases -> files -> async_jobs -> async_job_steps` 固定顺序取得 `ACCESS EXCLUSIVE` 锁；锁超时保持 SQLSTATE `55P03`。锁后检查两业务表均为空，且 `async_jobs` 不存在 `resource_type='file' AND job_type IN ('file_scan','file_process')` 的任何历史或活动 Job；任一条件不满足时在任何 DDL 前以 SQLSTATE `55000` 原子失败并保持 Schema/数据/head 不变。
- 只有全部门禁通过，才逐名删除 async_job_steps/async_jobs/files/knowledge_bases 上述十个 triggers，按反向调用依赖逐签名 `DROP FUNCTION` 七个本 revision 函数，再删除 `uq_async_jobs_file_job_type_lifetime`，最后按外键依赖顺序 `DROP TABLE files`、`DROP TABLE knowledge_bases`。函数必须在其引用的 relation 之前删除，避免无 `CASCADE` downgrade 受 catalog 依赖阻断；全程禁止 `CASCADE`、`TRUNCATE`、自动解归档、只删除部分列、动态发现对象或降格约束。
- 空库 upgrade/downgrade 可重入；非空环境优先前向兼容修复。真实 PostgreSQL 16 验证前不得把离线 SQL 或 ORM 元数据测试描述为迁移验收通过。

## 4. 实施影响与同步范围

本 CR 固有 `core_table_delta=0`、`api_delta=0`，锚定 2026-08-07 当前 57 表/122 API 和 `docs/baseline-manifest.md` SHA-256 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`；它不增加 ACL 表、恢复 API 或新核心表。最终表/API 总数必须按同步时有效基线加全部已批准 CR delta 累加；CR-010 与 CR-006 都可能各自增加一张表，任何文件不得各自把结果硬编码为“第 58 张表”。

Job/Outbox/Lease 实现依赖获批并落地的 CR-004，所有要求原子留痕的上传、配置、归档、重试和拒绝动作依赖获批并落地的 CR-006/008；Scanner evidence trigger、共享 current/history validator 与相关运行时代码硬依赖获批并同步的 CR-010-R1/GAP-055。在 CR-010 meta-contract、具体环境 Profile、更新后的两个 input Schema/Handler Registry hash 全部获批前，不得创建 consumer trigger 或启动 Scanner runtime；具体 Profile 的当期状态只记录在第 8 节，不进入本规范性前像。全部获批后至少同步：需求规格、系统架构、数据库设计、API 设计、页面与交互、AI/RAG/Prompt、测试与验收、部署运维、开发任务计划及追踪材料，并重新生成 Request 基线哈希。

同步时必须特别删除或改写以下冲突文案：

- `UNIQUE(organization_id, code)（活动记录）` 改为精确条件索引；
- 扫描失败直接把文件设为 rejected 的笼统流程；
- 仅“需要自动处理”才创建 Job 的架构步骤；
- 重复上传“永不创建第二个 Job”的无 scope 表述；
- FILE-006 返回数据库未承载的 `archived_at`；
- “授权知识库”但无 PostgreSQL 事实来源的泛化描述。

## 5. 必须验收

- **Schema**：PostgreSQL 16 证明 M1 全列、`files.archived_at`、状态 CHECK、条件唯一索引和跨表触发器与本合同一致。
- **知识库并发与配置边界**：并发创建同组织/code 只有一个 active 成功；归档后可创建新 ID；旧 archived 不能恢复、修改或接受新写入。KB-002 只接受 Top-5 与 NULL 阈值；KB-004 参数变化在 GAP-001 与版本化评测 Gate 另行获批前固定失败关闭，不能借任意正数、示例阈值或私有 Run 字段绕过。
- **授权**：覆盖五角色、禁用/锁定用户、长期/过期/撤销/break-glass 角色、CURRENT_DATE 与显式 baseline_date、空 allowlist、未知角色、未授权计数探测、跨组织、archived KB、历史快照和 Qdrant 过期 payload；最终结果逐制度以 PostgreSQL 谓词校验。另行证明本 CR 未静默裁决 GAP-020。
- **文件状态**：逐条验证初始 `(uploaded,pending,Job queued)`、claim 同事务后的 `(validating,pending,Job/Step running)`、全部允许/拒绝边、scan-only 与 full clean 的不同 Job 结果、原子 clean/stored、infected/unsupported→rejected+failed Job、rejected 终态、仅 stored/clean 可归档、scan_failed 与仅 local_offline/fixed_test not_configured 的错误码映射/重试，以及未知状态/版本/hash/code fail closed。scan 阶段 queued/running 取消均在状态变化前返回固定 409；Lease 未耗尽只追加 termination Step 并恢复，耗尽则在同一 fencing 事务写 `WORKER_LOST` 与 `validating/scan_failed`，不留下 pending 孤儿文件。逐列证明文件身份不可变、仅意图 false→true 及批准状态矩阵可更新。
- **scan-only 与 Scanner 证据**：false 上传也返回可查询 Job并完成扫描；不产生解析；精确校验增加 Registry 三元组后的两类 input Schema/version/JCS hash、命名为 `uq_async_jobs_file_job_type_lifetime` 的跨终态唯一索引、两类互斥 Step summary Schema 及 `file-scan-evidence-v1` 关系。逐格覆盖 `file-scan-step-outcome-v1` 的 outcome/code、三元组、Adapter/Scanner/Definition、scanner_invoked NULL/call 矩阵；Job 创建使用 current，终态/evidence 使用 history 且逐字等于 Job input。Profile 轮换、installed-only、跨 class 和 staging/production not_configured 全部失败关闭；基础设施终结不得伪造扫描结果。false→true 在 pending/clean/failed/rejected 四种场景不改写旧 Job 输入，且 full Job 终身最多一个；clean 后 follow-up full 只校验冻结历史证据，不重复调用 Scanner。FILE-001 平铺 data、FILE-002 accepted/rejected 及 follow-up 真值逐字段契约测试。
- **FILE-007 scan**：请求 reason/Job row_version/stage、同键同请求在所有状态变化后的首次 202 重放、同键异请求冲突、CAS 0 行的 404/state/version 优先级、原 Job failed→queued 与 file pending/Outbox/log/幂等同事务；响应逐字段证明 attempt_no 保持、scheduled_attempt_no 预告下一次、queued stage=null、新 row_version 正确。parse/extraction/markdown/all 继续标为未闭合。
- **去重与归档**：归档同内容单/批量上传稳定返回 `FILE_ARCHIVED_DUPLICATE`，rejected 同内容稳定返回 `FILE_REJECTED_DUPLICATE`；并发时均不新增文件、对象、Job 或 MinIO 副本，也不执行 false→true 提升。归档时间来自数据库且幂等重放不变化。
- **目标知识库竞态**：上传与 KB 归档并发时只能出现可解释的串行结果；跨组织/归档目标不能落库，历史关联不被改写。
- **迁移往返**：批准记录所绑定的实现前 head 只接受两表均不存在的首次创建；同名表预存在时 upgrade 失败。空库 upgrade/downgrade 通过；按 `knowledge_bases -> files -> async_jobs -> async_job_steps` 固定顺序独占锁，锁超时 55P03；两表任一非空或任一 file Job 存在时以 55000 原子失败。门禁通过后逐名删除十个 consumer triggers，再按反向依赖删除七个本 revision 函数、async_jobs 索引和两表，不使用 CASCADE，不删除 CR-010 表/shared validators，往返后 catalog 无残留。

## 6. 审批边界

本合同只有在第 8 节记录匹配本 snapshot 的完整 `APPROVED_CONTRACT` 批准后才生效。对 `CR-001-R2`、`CR-002-R4` 的既有批准不自动批准本 CR；在该条件满足前，不授权：

- 修改或同步任何 `Request/` 文档；
- 创建、编号或执行 Alembic revision；
- 实现 FILE/KB API、Worker、MinIO 迁移、权限查询或前端行为；
- 自动处理、恢复、删除或改写任何现有业务数据；
- 调用 `fixed_test_provider`、内部 vLLM、真实模型或其他外部网络；
- production 放行、canary、部署、提交、推送或创建 PR。

批准记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_decisions=FILEKB-D-001..008 / cr_revision=CR-007-R1 / decision_snapshot_sha256 / baseline_manifest_sha256=717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41 / core_table_delta=0 / api_delta=0 / environment_scope=contract / 日期 / 证据链接 / 备注`，逐项记录所选替代方案并覆盖需求、架构、数据库、后端、AI/RAG、测试、运维和安全责任。

`FILEKB-D-005/006` 依赖获批并落地的 CR-004 Job/Outbox 合同；所有要求原子审计留痕的 FILE/KB 动作依赖获批并落地的 CR-006/008；Scanner consumer 与 runtime 硬依赖获批并同步的 CR-010-R1 meta-contract、具体环境 Profile 和 shared validators；KB 检索参数变化继续受 GAP-001 与版本化评测 Gate 阻塞；RET/QA 执行顺序继续依赖 GAP-020；全局 AcceptedJobResponse 继续依赖 GAP-018。未获得完整批准及依赖闭合时，`files/knowledge_bases` migration 与相关 FILE/KB/RET/QA runtime 保持阻塞，不得自行选择隐含解释。

## 7. 生命周期与 decision snapshot

生命周期固定为：

```text
DRAFT -> GENERATED_FOR_REVIEW -> APPROVED_CONTRACT -> REQUEST_SYNCED -> IMPLEMENTABLE
```

`APPROVED_CONTRACT` 只批准本文语义，不等于 CR-004/006/008/010、Handler Registry、Scanner Profile、GAP-001/018/020 已闭合；`REQUEST_SYNCED` 前不得建表；依赖全部落地后才可进入 IMPLEMENTABLE，且仍不等于 production 放行。

`decision_snapshot_sha256` 计算规则：将全文行尾规范化为 LF，内容完全等于 `## 8. 当前状态` 的标题必须恰好出现一次；取该行之前全部行，去除已有尾随 LF 后再保留恰好一个 LF，以无 BOM UTF-8 编码并计算 SHA-256 小写十六进制。标记缺失/重复、UTF-8/BOM/行尾规则不满足或 hash 非小写 64 位十六进制时不可签署。

首次生成 snapshot 只建立可签署对象，不等于批准。生成后第 1～7 节任一规范性修改都必须提升 revision、重算 hash 并清空全部签署；第 8 节只记录状态，不进入 preimage。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| FILEKB-D-001～008 | PROPOSED / NOT APPROVED |
| Scanner Job/Step/evidence 三元组与 NULL/call matrix | PROPOSED / DEPENDS ON CR-010 |
| core/API delta | PROPOSED：`0 / 0`；最终总数按有效 CR 累加 |
| CR-010 meta-contract/Profile | DRAFT / NO PROFILE ARTIFACT APPROVED |
| Handler Registry input Schema bytes/hash | PENDING / NOT GENERATED |
| Request 同步 | NOT AUTHORIZED |
| decision snapshot | `40a38d45aeab262c2b54d65b1b95e7e6bbcbcdf3d892900d9b4150fefcf2b98e` / GENERATED_FOR_REVIEW / NOT APPROVED |
| 批准记录 | NONE |
| migration/runtime | NOT AUTHORIZED / BLOCKED BY APPROVAL AND DEPENDENCIES |
| `fixed_test_provider` / 内部 vLLM / 真实 Provider 网络 | NOT AUTHORIZED |
| production/canary/部署 | NOT AUTHORIZED |
