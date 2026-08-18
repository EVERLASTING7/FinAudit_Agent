# FinAudit Agent 实施计划

状态：当前检出实施导航
更新日期：2026-08-17
适用对象：独立开发者
排序：MVP vertical slices → Beta → Production readiness

## 1. 目的

本计划把 P0 的产品结果改排为可编码、可验证的垂直切片。它不复制归档的旧九份文档，也不把历史 CR、候选 CR 或形式化回执变成全局前置。

实现一个切片时只核对：

1. `PRODUCT_REQUIREMENTS.md` 中与该切片相关的需求和 AC。
2. 当前模块的代码、Schema、迁移或机器制品单一事实来源。
3. `docs/testing/p0-traceability-matrix.csv` 中对应任务的当前状态和缺失证据。
4. `TECHNICAL_SPEC.md` 第 15 节及本文 OPEN QUESTIONS 中确实影响该最小切片的未决问题。

## 2. 当前起点

截至本计划编写时：

- 追踪矩阵当前盘点为 86 项：`2 implemented / 84 partial / 0 planned`；`partial` 表示已有可执行证据但未完成该任务全部 AC，不是任务数量合同。
- Backend 已有统一错误/Trace/Auth 边界、57 表 PostgreSQL 事实、真实 Job/Outbox/Celery Worker 恢复，以及面向文件、财务、知识、审核和报告的 Router → Service → Repository/Adapter 主链。
- `/api/v1` 当前注册 Auth、用户创建/启停/密码重置/角色替换、Break-glass、操作日志、文件、合同/补充协议、发票、合同发票关系、供应商、制度/知识索引与评测、RAG/反馈、审核执行、正式报告、工作台摘要、依赖健康和 OPS-005 AI 调用审计 Router；独立 `/metrics` 只在启用时注册。
- PostgreSQL 16 当前 accepted head 为 `20260817_024`，ORM/runtime catalog 与隔离数据库验证覆盖 57/57 张核心物理表；`021` 封锁检索初始状态旁路，`022` 闭合未确认发票空币种，`023` 增加可降级风险解释与报告草稿事实，`024` 在保留 v1 历史的同时增加 Event v2 的 USD/CNY 通用 microunit 费用列和安全升降级门禁。这仍只是当前 Schema 与集成证据，不等于生产数据迁移或 AC。
- 文件意图、字节计量、格式/Magic Bytes、DOCX 有界检查、六态扫描准入已有纯函数证据。
- 合同补充协议生效投影、合同发票匹配事实、15 条规则谓词、风险汇总、检索指标、AI 严格输出、85%/95%/99% 阈值计算和表格文本保护已有纯函数证据；阈值计算器不替代已审批代表性数据与 UAT。
- Frontend 的登录/会话、用户、Break-glass、操作日志、文件、财务、供应商、知识库/问答、审核、正式报告和工作台页面均使用同源真实 API；文件页还提供批量独立结果、原件/文本预览、归档和失败 Job 重试。合同详情已把补充协议 Header 接到字段级严格详情、整组变更替换、确认/拒绝与基准日期有效字段投影；`financial.read` 保持只读，只有 `contracts.manage` 且服务端状态允许时才显示写入口。
- `infra/compose/compose.local.yml` 已提供固定镜像、内部数据网络、loopback Nginx/HTTP、PostgreSQL/Redis/MinIO/Qdrant/官方 ClamAV、Backend/Worker/Dispatcher/Maintenance、迁移与 first-org/admin 初始化。受管 Secret mount、依赖就绪、文件 smoke、冷重启和 PostgreSQL/MinIO 权威备份/隔离恢复已有实际证据；HTTP 不提供传输加密，局域网/公网与 production 发布仍被阻断。
- 当前分层证据包括完整 Backend/Frontend 离线质量门禁、隔离 PostgreSQL 16.14、真实 Redis/Celery/Qdrant/MinIO/ClamAV、完整 local Compose，以及隔离浏览器财务闭环和五角色权限矩阵。独立故障注入已覆盖六类 Worker Job 与 AI 审计投影的事务回滚、Maintenance 恢复和唯一事实收敛。`minimax-m3-local-v1` 已把真实 Chat Adapter、Gateway、结构修复、预算/网络策略、Provider → EventSink → 业务事实原子采用接到合同/发票、RAG、风险解释和报告草稿；OPS-005 已公开为组织/权限裁剪的安全摘要，最新受限真实 smoke 覆盖五条生成链并核对每次尝试均有持久审计。`minimax-m3-bailian-qwen37-local-v2` 已按 `CR-022` 把 Chat/USD 与百炼 Embedding/CNY 接到 Event v2、持久预算/费用审计和原子业务采用；唯一一次受限付费 Embedding smoke 已验证 2 个 1024 维向量、43 input tokens 和 CNY 22 microunits 实际费用。Redis 运行门禁已用锁定 7.4.9 digest 验证跨客户端并发、RPM/TPM、熔断和 half-open 恢复；`/metrics` 已有独立凭据和精确 Nginx 代理。上述结果仍不证明代表性合同/发票与 50/100 条业务质量集、正式 DAST、浏览器直接 CA 信任、production OCR/Scanner/TLS/Secret Manager、正式参考容量、主机断电/异地恢复、完整监控告警/SLO、AC/UAT 或 production。

## 3. 状态和执行规则

### 3.1 状态

- `READY`：当前需求和模块 SSOT 足以实现；如果有技术前置，只需完成本计划中更早的切片，不需要新的业务裁决。
- `BLOCKED`：缺少会改变 API、持久化语义、状态机、权限、安全边界或验收阈值的真实决定。
- 状态描述的是“能否开始该切片”，不是任务完成度。
- 完成后更新追踪矩阵证据；不要把 `READY` 改写成 AC 通过。

### 3.2 决策边界

1. 历史 CR 只用于解释来源，不要求开发者在每个切片前重放审批链。
2. 候选、未批准或未同步 CR 不是前置；只有当前基线可复现的歧义阻断对应最小切片。
3. 内部函数、Repository 组织、测试结构和依赖注入方式不需要 CR。
4. 改变 P0/P1 范围、公开 API、持久化语义、状态/权限/安全边界或验收阈值时，才写最短 Request 修订或 CR。
5. Router 只调用 Service；Service 通过 Repository/Adapter 访问外部资源。
6. PostgreSQL 保存业务事实；MinIO 保存文件制品；Redis/Qdrant 只保存可恢复状态或派生数据。
7. AI 关闭或失败时，确定性规则和人工流程仍必须成立。
8. 未读取真实 `.env`、未运行真实服务或未调用 Provider 时，证据写 `NOT_RUN`。

### 3.3 每个切片的提交粒度

一个切片只包含：

- 一个可观察结果。
- 一个最小生产路径或可复用应用服务。
- 一组聚焦测试。
- 对追踪矩阵一行或少量关联行的证据更新。

不顺带补齐相邻模块，不创建“以后可能用”的框架，不以 Mock 页面或静态构建代替运行闭环。

## 4. MVP vertical slices

MVP 阶段先完成可立即编码的短切片，再处理需要产品或安全决定的切片。前五项提供真实可复用能力，但单独完成不等于产品 MVP。

### MVP-VS-01 单文件安全校验用例

- **状态：VERIFIED（unit/integration）**
- **目标：** 从上传意图和二进制流得到不可变的安全元数据，或返回稳定、脱敏的业务错误。
- **范围：** 严格解析业务类型、知识库目标和布尔值；一次遍历计算大小/SHA-256；校验扩展名、声明 MIME、Magic Bytes、DOCX 边界；执行 clean-only 准入。
- **非目标：** Multipart Router、PostgreSQL、去重、MinIO、真实 Scanner、Job、解析/OCR。
- **代码锚点/SSOT：** `backend/app/schemas/files.py`、`backend/app/services/file_service.py`、`backend/app/core/errors.py`；矩阵 `FILE-001/002`。
- **前置条件：** 无；只使用合成 fixture，不访问网络或真实数据。
- **完成标准：** 新应用用例复用现有纯函数，不重复读取流；所有失败走统一 `AppError`；原始文件内容不进入日志或错误。
- **最小验证：** 聚焦运行六个现有 FILE 测试文件，并新增一组“意图 → 计量 → 格式 → 扫描准入”组合测试。

### MVP-VS-02 财务只读应用视图

- **状态：VERIFIED（PostgreSQL/浏览器闭环）**
- **目标：** 从可丢弃 PostgreSQL 测试库读取合同、补充协议、发票、明细和合同发票关系，生成稳定的内部只读视图。
- **范围：** Repository 查询、组织边界、软删除过滤、Decimal/日期原样保留、稳定排序；补充协议只把已确认且在基准日期生效的事实投影为有效字段。
- **非目标：** HTTP API、认证、供应商确认、字段纠错、写操作、前端。
- **代码锚点/SSOT：** `backend/app/models/financial.py`、`backend/app/db/session.py`、`backend/app/services/contract_effectivity.py`、迁移 `20260807_006/009`；矩阵 `CON-003/INV-003/LINK-001`。
- **前置条件：** 显式 `TEST_DATABASE_URL` 指向隔离、可丢弃的 PostgreSQL 16；不得回退到开发或生产库。
- **完成标准：** Repository 不泄漏 SQLAlchemy 对象；同一输入得到相同视图；组织外、软删除和未确认协议不可进入结果。
- **最小验证：** Repository 集成测试覆盖空结果、跨组织、软删除、同日冲突和有限 Decimal；保留现有 52 项生效投影测试。
- **当前进展：** 在完整财务写闭环之前，已交付 `invoice-detail-read-v1`、keyset-cursor `invoice-list-read-v1`、`contract-detail-read-v1`、keyset-cursor `contract-list-read-v1`、`invoice-primary-contract-read-v1`、`supplementary-agreement-header-list-read-v1`、`contract-primary-invoice-list-read-v1`、`invoice-exact-duplicate-candidates-read-v1` 与 `invoice-exact-duplicate-pair-read-v1`。它们共用真实 Actor → `financial.read` → 组织隔离 PostgreSQL 边界；发票当前主合同读取复用 accepted 009 的条件唯一索引，只投影唯一已确认关系，合同当前主发票列表则复用 `(contract_id, invoice_id)` active-pair 条件索引，以 UUID keyset 提供稳定有界反向遍历。补充协议读取仅公开当前原始 Header，不包含字段级 change 或基准日有效字段投影；重复候选只按当前持久化 `invoice_code + invoice_number + seller_tax_no` 逐字段数据库等值读取，保留 archived 并排除源票、软删除及 voided 候选；两票点查用一条有界自连接语句重新核对两个已知 UUID，任何不可见、失效、自比较或不再精确匹配均统一 404。当前 PostgreSQL 16.14 current-head Gate 已在隔离数据库连续两轮各 91/91 通过且专用残留容器为 0；组合用例以真实临时 Ed25519 keyfile 经 keyring loader 和 `create_app` lifespan、零 dependency override 构造 AuthService、九条财务读链所用五个 QueryService 与 UserQueryService，覆盖 login/JWT → Actor/`financial.read` → 九 Router → Service/Repository → 同一 PostgreSQL → logout 后再次 refresh 返回 401 `AUTH_REFRESH_EXPIRED`，随后以 `system_admin` 重新登录并通过 Actor/`users.manage` 读取同组织用户列表，同时校验 `no-store` 与 Refresh Cookie 的 `Secure/HttpOnly/SameSite=strict/Path`。两票点查聚焦证据另为 Backend 76 passed/17 个未注入数据库时安全 skipped、Ruff/format/mypy PASS，以及 Frontend 66 passed/typecheck PASS；浏览器仍未覆盖新增路径。另行显式运行的 test-only 同源浏览器 Gate 仍只覆盖此前七条财务 API；它生成临时 Ed25519 PKCS8 私钥与 public keyring，经生产 keyring loader 和 `create_app` lifespan 构造六个真实 Service，且 `dependency_overrides=0`、Service state 在 lifespan 前空、进入后为真实类型；真实浏览器通过 `login → dashboard → invoice list/detail → primary contract → contract list/detail + supplementary raw header → contract primary invoices → invoice detail`，精确命中隔离 PostgreSQL 合成事实，0 alert、0 console error；深链 reload 保持 URL 与用户，logout 后 reload 保持匿名且无远端退出状态未确认提示，但未导航或验证用户列表、精确重复候选或两票点查。正常 `CTRL_BREAK` 后合成事实、临时 key 目录、宿主和容器复核为 0。精确候选与点查均不等于重复确认、真实性判断、风险或 `duplicate_status` 写入；普通 `READ COMMITTED` 的候选列表源锚点与候选查询不构成单一 MVCC 快照，UUID tie-break 与现有索引也不是容量或性能证明。上述证据不证明真实 TLS/Nginx、production secret mount/ACL、强杀/断电清理、部署或完整 AC，也不包含页码筛选/汇总、模糊候选解释、供应商、确认/纠错或审计。

### MVP-VS-03 合同发票候选解释

- **状态：VERIFIED（Backend/浏览器闭环）**
- **目标：** 对已规范化的合同和发票事实给出可解释候选，不改变主合同确认事实。
- **范围：** 税号逐字相等、名称逐字相等、日期包含关系和稳定原因代码；输入来自 MVP-VS-02 只读视图。
- **非目标：** AI 推荐、名称模糊匹配、供应商复用、数据库确认、并发唯一主合同、HTTP API。
- **代码锚点/SSOT：** `backend/app/rules/contract_invoice_matching.py`、`backend/app/schemas/business_statuses.py`；矩阵 `LINK-001`。
- **前置条件：** MVP-VS-02；上游必须明确已完成何种文本规范化，本切片不得自行新增规范化。
- **完成标准：** 每个候选包含命中/未命中的具体事实；排序和 tie-breaker 固定；无候选返回空集合而非伪结果。
- **最小验证：** 聚焦匹配测试覆盖税号、名称、日期边界、顺序无关和缺失事实。

### MVP-VS-04 离线审核预览

- **状态：VERIFIED（Backend/PostgreSQL/Worker）**
- **目标：** 用合成财务视图执行确定性规则并汇总风险，形成可复核的离线审核预览。
- **范围：** 调用现有 RULE-001～RULE-015 纯谓词；规则元数据由调用方显式传入；结果稳定排序；风险汇总使用有效等级；AI 固定为关闭/降级。
- **非目标：** 规则目录发布、审核表写入、任务状态机、人工复核、Provider、正式报告。
- **代码锚点/SSOT：** `backend/app/audit/rule_predicates.py`、`backend/app/audit/risk_summary.py`、`backend/app/rules/contract_invoice_matching.py`、`tests/fixtures/core_business.json`；矩阵 `AUD-003/005`。
- **前置条件：** MVP-VS-02/03；不得写入 `audit_rules` 或假装规则 publisher 已完成。
- **完成标准：** 缺失/不适用/命中/未命中语义分开；金额只用 Decimal；AI 不改变命中与等级；输入不可被修改。
- **最小验证：** 新增应用服务组合测试，复用全部规则谓词与风险汇总测试；至少覆盖无合同、超额、日期、重复和 high 风险。

### MVP-VS-05 报告负载与安全表格行

- **状态：VERIFIED（Backend/报告链）**
- **目标：** 把离线审核预览转换为确定性报告负载和安全的表格行，为后续 PDF/XLSX Writer 固定输入边界。
- **范围：** 固定字段顺序、Decimal 字符串、引用 ID、降级标记、过期标记；所有文本先通过公式前缀保护。
- **非目标：** PDF、XLSX 二进制、MinIO、下载 API、报告版本表、模板系统。
- **代码锚点/SSOT：** `backend/app/reports/spreadsheet_safety.py`、`backend/app/audit/risk_summary.py`；矩阵 `REP-003/AUD-005`。
- **前置条件：** MVP-VS-04。
- **完成标准：** 同一审核预览生成字节级稳定的 JSON fixture；`= + - @ TAB CR LF` 不会成为公式；空值和 Decimal 不经浮点转换。
- **最小验证：** 负载快照测试和现有 spreadsheet safety 聚焦测试；不得把结果记为 `REP-001/002` 或 AC-014 通过。

### MVP-VS-06 真实认证与当前用户

- **状态：VERIFIED（Backend/PostgreSQL/Frontend/浏览器）**
- **目标：** 实现登录、刷新、退出、`/auth/me` 和后端强制权限检查，替换 Frontend Mock Session。
- **范围：** AUTH-001～004、五固定角色、Token 会话、禁用/锁定、强制换密和统一 Actor 依赖。
- **非目标：** 自定义权限树、多租户、外部身份提供商。
- **代码锚点/SSOT：** `backend/app/models/auth.py`、`frontend/src/stores/auth.ts`、`frontend/src/services/api.ts`；矩阵 `AUTH-001～005`。
- **前置条件：** `auth-mvp-v1`、BOSS 批准的全局 `auth-password-v2` 与 `p0-permissions-v1` 已作为前向决定写入 `PRODUCT_REQUIREMENTS.md` 和 `TECHNICAL_SPEC.md`；现有 008 storage-schema 保持不变。
- **已解除阻断：** OQ-08、`GAP-038/039` 已关闭；实现必须直接消费五个 Auth API、26-code 字典、五角色映射、deny-overrides 和同人职责分离，不得读取候选 CR 或旧 API 示例补充语义。
- **当前进展：** 五个 Auth API、密码/JWT/Refresh、统一 Actor/permission、Frontend 内存会话，以及用户创建、启停、密码重置、角色替换、Break-glass 和操作日志读链均已通过 Router/Service/Repository 落地；敏感写入与日志在同一 PostgreSQL 事务，长期角色与临时授权继续执行 deny-overrides 和职责分离。`CR-023` 已把全局密码策略升级为 `auth-password-v2`，最小长度为 6，最大长度/字节上限、弱密码黑名单、Argon2id 和锁定策略保持。PostgreSQL 16.14 current-head 对当前 `20260817_024` 完整目录连续两轮通过，浏览器已验证真实登录、会话恢复、权限驱动页面与退出。`CR-024` 后 `local-compose-v1` 使用 loopback Nginx/HTTP 和受管 Secret mount，不再生成 TLS 证书；传输加密、Secret Manager/ACL、局域网/公网部署和正式 AC-001 仍未运行，因此不把本切片或 AUTH 总体标记为验收完成。
- **完成标准：** Backend 强制认证/授权，Refresh 旋转与重放处置可验证；生产路径和 Frontend 不再调用 `signInMock`。
- **最小验证：** 先做密码规范化/长度/blocklist/Argon2id、原子五次锁定与防枚举、Access claim/key rotation、Refresh 7/30 天绝对 TTL/旋转/重放/并发、强制换密一次性、Cookie Origin、五 API 包络测试；再做 26-code 精确集合、五角色、组合角色 deny、break-glass deny、组织/对象/状态和两条同人 SoD 负例，最后做 Frontend 实际会话测试。代码或单测通过仍不等于 AC-001 或 production 通过。

### MVP-VS-07 持久化单文件上传

- **状态：VERIFIED（本地隔离与完整 local Profile）**
- **目标：** 让授权用户上传一个文件，写入 PostgreSQL 事实和 MinIO quarantine，并返回真实 Job。
- **范围：** FILE-001、幂等、去重锁、对象写入补偿、扫描状态、Job/Outbox 创建和 Trace。
- **非目标：** 批量上传、解析/OCR、预览、归档恢复、生产 Scanner。
- **代码锚点/SSOT：** MVP-VS-01、`backend/app/services/file_service.py`、`backend/app/adapters/minio_quarantine.py`、`infra/compose/compose.local-minio.yml`、`scripts/bootstrap_local_minio.py`、`backend/app/models/reliability.py`、`backend/app/workers/*`；矩阵 `FILE-001/002`、`BASE-006`。
- **已满足前置：** OQ-09 已关闭；MVP-VS-06 已提供本切片需要的真实 Actor；隔离 PostgreSQL Gate 已存在；上传 intake、业务类型权限校验、MinIO 配置/Adapter 与本地 Bucket bootstrap 已独立实现并有离线测试证据。
- **已解除阻断：** `archived-reupload=conflict-v1` 固定同组织 SHA-256+大小命中 archived 时返回 409 `FILE_ARCHIVED_DUPLICATE`，不复用、不恢复、不新建文件/Job/业务对象/MinIO 副本；`GAP-050` 关闭。
- **当前进展：** 第 10.3～10.5 节的 multipart/202 DTO、24 小时幂等、同组织 SHA-256+大小去重、quarantine 补偿、`files/knowledge_bases`、Job/Step/Outbox/operation-log 同事务、真实 Dispatcher/Celery/Redis、Scanner、解析/OCR 和租约恢复均已接入；Frontend 文件列表、详情与上传表单使用真实 API。隔离浏览器 Gate 已用合成 clamd 端点验证完整单文件链；`scripts/verify-local-stack.ps1 -FileUpload` 改为通过 loopback HTTP/Nginx 和官方 ClamAV 1.5.3 验证角色边界、唯一 `stored/clean/succeeded` 文件/Job 与原件预览。
- **当前边界：** local Profile 的官方 ClamAV clean path 不是 production Scanner Profile；`file_process` 已验证 scan 中 SIGKILL 后由受管命令重启同一 Worker，并由 Maintenance 将租约过期的同一 Job 回收为 attempt 2，继续完成 parse/markdown 和下游合同提取。`contract_extract`、`invoice_extract`、`audit_execute`、`report_generate` 与 `knowledge_index_build` 本体也已分别通过 attempt-1 SIGKILL、恢复前事务或跨系统边界核验、`failed/LEASE_EXPIRED`、attempt-2 成功和唯一事实收敛。这些证据都不证明 Docker 自动重启；通用迟到 PUT reconcile、主机断电、容量、production 和 AC-002/016 仍未验证。批量上传、预览、归档与重试已在相邻 FILE 切片实现，但不改变本切片范围。
- **完成标准：** 成功响应对应唯一文件事实、quarantine 对象和真实 Job；失败原子回滚且可幂等重放。
- **最小验证：** PostgreSQL + MinIO 隔离集成测试覆盖成功、重复、对象写失败、事务失败和重放；失败不得留下伪成功事实。

### MVP-VS-08 第一个浏览器上传闭环

- **状态：VERIFIED（本地隔离与完整 local Profile）**
- **目标：** 用户真实登录，在文件页上传一个合法文件并看到持久化文件、扫描状态、Job 和 Trace。
- **范围：** UI-001、UI-003 的最小路径；loading/empty/error/forbidden；刷新后恢复服务端状态。
- **非目标：** 解析预览、合同/发票编辑、Dashboard 聚合、AI。
- **代码锚点/SSOT：** `frontend/src/views/LoginView.vue`、`FileListView.vue`、`FileDetailView.vue`、`frontend/src/services/api.ts`、`frontend/src/components/FileLifecycleStatuses.vue`；矩阵 `FE-001/003/009`。
- **前置条件：** MVP-VS-06/07。
- **当前进展：** Auth、文件上传/读取 OpenAPI 与 Frontend 文件页已使用真实链路。显式同源浏览器 Gate 已验证真实登录、multipart happy path、持久化文件/扫描/Job/Trace、reload/详情恢复，以及无权上传 403 不落第二份事实。完整 local Profile 改为通过 HTTP/Nginx → 官方 ClamAV → Worker → PostgreSQL/MinIO 原件预览 smoke。
- **完成标准：** 不再调用 `signInMock`；页面只访问同源 `/api/v1`；刷新不丢状态；无权不泄露对象存在性。
- **最小验证：** Vitest 组件/路由测试、Backend API 集成测试、一个真实浏览器 happy path 和一个 403 path。

### MVP 退出条件

MVP-VS-01～08 的本地上传生命周期已有实际运行证据。其后的隔离财务浏览器 Gate 又完成合同/发票上传、专用提取、人工确认、关联、审核和报告，因此首个完整本地财务业务闭环也已收口；两类证据都不代表 10 项 P0、AC-001～016、UAT 或 production 已接受。

## 5. Beta slices

### BETA-VS-01 批量文件与正常解析

- **状态：READY；实现状态：VERIFIED（本地正常路径）**
- **目标：** 批量上传按文件独立返回结果，并完成文本 PDF、正常 DOCX 和清晰图片的基础解析/OCR Adapter 路径。
- **范围：** FILE-002、PARSE 正常路径、页/块基础 DTO、Job 阶段和失败重试。
- **非目标：** 多业务文档自动拆分、`quote` 过滤、坐标不可得原因、Markdown。
- **代码锚点/SSOT：** `backend/app/parsers/`、`backend/app/services/file_service.py`、`backend/app/workers/*`；矩阵 `FILE-001/004`、`DOC-001～004`。
- **前置条件：** MVP-VS-07；选择必要且成熟的解析/OCR Adapter，不新增 Agent 框架。
- **当前进展：** Scanner、文本 PDF、正常 DOCX、图片 OCR Adapter、版本化页/块持久化、`scan → parse` Handler 与 Job 恢复已交付；批量上传按文件返回独立受理/拒绝结果，原件/文本预览、引用保护归档和同一失败 Job 重试也已接 Backend/Frontend。聚焦单元/API/数据库/前端证据通过；`local-performance-baseline-v2` 还在真实 local Nginx/Backend/MinIO/PostgreSQL/Redis/Celery/ClamAV 链路连续验证默认 20 件最大批次、同键重放、207 部分失败、第 21 件 413、61 组 run-scoped 文件/Job/Step/Outbox 以及超限零副作用，并在同一栈新 run 完整复跑。另有 `file_process` 在 scan 中本地 SIGKILL、受管重启、attempt-2 `scan → parse → markdown` 和下游合同提取证据，以及 `contract_extract`、`invoice_extract`、`audit_execute`、`report_generate` 与 `knowledge_index_build` attempt-1 强杀、恢复前事务/跨系统边界、attempt-2 唯一事实收敛证据。production OCR/Scanner、复杂/恶意文档全矩阵、主机断电和正式参考环境完整容量仍为 `NOT_RUN`。
- **完成标准：** 每个文件有独立 Job/结果；恶意或损坏输入 fail closed；旧解析版本不可覆盖。
- **最小验证：** 固定 PDF/DOCX/PNG fixture 的 Adapter 测试、Worker 中断/重试测试和批量部分失败 API 测试。

### BETA-VS-02 合同、补充协议、发票和关联

- **状态：READY；实现状态：VERIFIED（Backend 与隔离浏览器业务闭环）**
- **目标：** 提供真实列表、详情、候选创建、人工确认、补充协议生效、发票重复和主合同确认闭环。
- **范围：** CON、SAGR、INV、LINK 中不依赖 supplier runtime 的字段；row_version、幂等、审计和过期传播。
- **非目标：** 供应商候选确认/复用、AI Provider、完整审核任务。
- **代码锚点/SSOT：** `backend/app/models/financial.py`、MVP-VS-02/03、对应 Frontend views；矩阵 `CON-001～004`、`INV-002～004`、`LINK-001～003`。
- **前置条件：** 真实 Actor、文件来源和 PostgreSQL Repository；供应商字段保持只读/未连接。
- **当前进展：** 合同/发票列表与详情、字段级合同事实、补充协议整组变更与基准日有效投影、合同发票候选/建议/确认/替换/取消/历史，以及合同/发票提取 Job、证据/历史、事实修正、人工确认/拒绝和重复处置均已接入 Repository/Service/API/Frontend。合同详情现可从补充协议 Header 打开严格字段级详情；`contracts.manage` 可在服务端允许的状态下提交带 CAS、原因、证据和幂等键的完整变更集合并确认/拒绝，`financial.read` 只读；基准日期查询直接调用 Backend 有效字段投影，不在浏览器计算旧值。`file_process` 现在会按 business type 创建 `contract_extract` 或 `invoice_extract` Job，合同提取由专用 Registry/Executor/Worker 写入未确认候选。2026-08-16 当前 checkout 的隔离财务闭环门禁实际提交两类文件，等待 Worker 后分别修正并确认，再确认主合同关联；受保护的最终 PostgreSQL/MinIO manifest 只接受唯一绑定和确认事实。独立 `supplementary-agreement-browser-v1` 在全新 PostgreSQL 中由真实浏览器完成 `amount: 100.25 → 120.50`、完整来源证据、人工确认和基准日生效查询，受保护 manifest 逐项核对 CAS 行版本、追加式修正/操作日志和幂等结果。2026-08-17 当前 checkout 的同一门禁再以两个真实浏览器标签保留旧 `row_version=1`，先成功替换到版本 2，再由旧标签触发安全 `409`，随后确认到版本 3；另一个无来源证据的待确认协议被拒绝到版本 2。系统管理员、财务、审计、合同和只读五个 Actor 均完成真实登录，最终 manifest 核对两份协议、变更状态、三条操作日志、三条成功幂等记录以及 `PUT 200/409 + POST 200/200` HTTP 矩阵，脚本输出 `SUPPLEMENTARY_AGREEMENT_BROWSER_GATE=PASS` 且专用容器零残留。桌面与 390 px 财务只读路径也已独立核对；附件或版本替换、production、正式业务 UAT 和正式 AC 仍为 `NOT_RUN`。
- **完成标准：** 原始值和有效值分开；并发主合同确认恰一成功；修正保留原因与版本；Frontend 不使用 Mock DTO。
- **最小验证：** Repository/API/权限/并发测试，加合同与发票两个浏览器闭环。

### BETA-VS-03 供应商候选运行时

- **状态：READY；实现状态：VERIFIED（Backend、Frontend 与隔离浏览器双来源闭环）**
- **目标：** 从合同/发票生成、复用、确认和纠正供应商候选。
- **范围：** SUPP-001～003、CON-005、INV-005 及精确税务身份匹配。
- **非目标：** 别名、合并、回滚和风险画像。
- **代码锚点/SSOT：** `backend/app/models/financial.py`、`backend/app/schemas/suppliers.py`、`backend/app/services/supplier_management.py`、`backend/app/repositories/supplier_write.py`；矩阵 `SUPP-001～003`、`CON-005`、`INV-005`。
- **前置条件：** BETA-VS-02；使用当前 006/014～017 表语义，不引入 P1 supplier 能力。
- **已冻结合同：** `CR-018-R1/RFV1-D-001` 已固定统一税务投影、generic 写入、三态、精确复用、来源回填、组织→来源→supplier 锁序、聚合纠错和稳定错误码；`GAP-064/OQ-05` 关闭。
- **当前进展：** 已交付供应商列表/详情、合同/发票来源 resolver、候选修改/确认/拒绝、同组织活动身份精确复用与来源回填；写链使用 24 小时幂等、来源与候选 CAS、固定锁序、单条 `supplier_field` 纠错和脱敏 `supplier.resolve/supplier.update` 日志。独立供应商列表/详情路由、严格 decoder 和来源解析/候选修正页面已接真实 API。2026-08-16 当前 checkout 的隔离浏览器从已确认合同创建候选，以同一原子提交修正名称并确认激活，再从已确认发票按同一税务身份精确复用同一活动供应商；最终 PostgreSQL manifest 断言唯一供应商、合同/发票双来源回填、单条聚合纠错及两次 resolve/一次 update 日志。将修正与确认拆成两次写入的首轮会被 manifest 精确拒绝，不计为通过证据。production、容量和正式 AC 仍为 `NOT_RUN`。
- **完成标准：** 精确身份复用、来源回填、确认/拒绝、纠错和并发冲突均保留稳定事实与审计。
- **最小验证：** 纯映射测试、PostgreSQL 并发测试、API 权限/幂等测试和合同/发票双来源 E2E。

### BETA-VS-04 Markdown、来源映射与分块

- **状态：READY；实现状态：VERIFIED（Backend runtime）**
- **目标：** 从活动解析版本生成可验证 Markdown、来源映射、质量结果和版本化分块集合。
- **范围：** MD、CHUNK、KB-004；复用现有质量指标，并从已发布的组织级分块配置机器 SSOT 读取参数。
- **非目标：** 多策略 A/B、语义分块、人工拆分、Qdrant。
- **代码锚点/SSOT：** `backend/app/markdown/quality_metrics.py`、`backend/app/chunking/config.py`；矩阵 `DOC-005～008`、`KB-004～007`。
- **前置条件：** BETA-VS-01；正常单文档解析结果必须已经版本化并可追溯。
- **已冻结合同：** `CR-018-R1/RFV1-D-002` 已固定 quote、坐标缺失原因、CommonMark/GFM table、raw HTML 禁用、`table_asset_v1` 和单一分块 Profile；`GAP-065/OQ-07` 关闭，多业务文档拆分继续不进入本切片。
- **当前进展：** 018 迁移、Markdown/source-map/table-asset/quality 与 ChunkSet Repository、确定性 CommonMark/GFM 转换、结构分块和原子激活已接入文件 Worker；quote、坐标异或、raw HTML/XSS、复杂表格、来源映射和活动版本回滚均有单元与 PostgreSQL 证据。知识库列表/详情、索引构建与激活页面已接真实 API；多业务文档拆分、production OCR/容量和正式 AC-008 仍为 `NOT_RUN`。
- **完成标准：** Markdown、source map、质量结果和 ChunkSet 均版本化；门禁失败不替换活动版本。
- **最小验证：** AST/来源映射、XSS、质量阈值、版本激活事务和 chunk 可追溯集成测试。

### BETA-VS-05 知识库索引、检索评测与 RAG

- **状态：READY；实现状态：VERIFIED（Backend runtime，5 条 smoke）**
- **目标：** 从活动 Chunk 构建候选索引，执行权限/日期过滤、Top-K、固定集评测、引用校验和拒答。
- **范围：** KB-008～012、AI-004；默认关闭 Provider，批准的 `local/test` Profile 可使用真实 LLM 验证受引用约束的答案采用。
- **非目标：** 混合检索、Reranker、代表性百炼检索质量验收、production 容量。
- **代码锚点/SSOT：** `backend/app/evaluation/retrieval_metrics.py`、`backend/app/ai/output_validation.py`、AI Policy 机器制品；矩阵 `KB-008～012`、`AI-004`。
- **前置条件：** BETA-VS-04；Embedding 目标必须显式，真实 Chat/Embedding 只能由 `minimax-m3-bailian-qwen37-local-v2` 显式启用。
- **已冻结合同：** `CR-018-R1/RFV1-D-003～004` 已固定组织级知识权限、环境+模型+维度 Collection 身份、PG 允许集→Qdrant must-filter→PG 终审和 5/50/100 评测分级；`GAP-001/008/020` 与 `OQ-01～03` 关闭。
- **当前进展：** 018/019 迁移已提供知识、Markdown/Chunk、索引、成员、评测与问答事实；制度写链、索引构建/激活/重建、PG 允许集→Qdrant must-filter→PG 终审、5 条 smoke 评测、RAG 引用白名单/拒答和反馈 Router 已接入 Job/Outbox/Worker。calls-disabled 继续使用确定性 Hash；`CR-021/022` 已把百炼 Embedding 通过 Gateway 条件接入 Backend/Worker，并以 Adapter/模型/维度身份强制新旧索引隔离，同时以 Event v2/CNY 记录预算、实际费用和事务采用。`AiRagAnswerService` 只接收终审候选，并在最终权限/引用重验后把 Chat/Embedding 完成审计与 Query 同事务采用；同幂等键重放不会再次调用 Provider。单元、隔离 PostgreSQL、真实 Qdrant、前端、受限真实 MiniMax RAG smoke、受限付费百炼 Embedding smoke，以及单独授权的完整 local/test 知识库 E2E 均已通过；完整 E2E 以 7 次 Provider 请求、3231 input tokens 和 CNY 1616 microunits 完成 15 个成员的 Worker 索引、Qdrant green、Top-5 与 5/5 smoke，激活按 100 条 `formal_release` 门禁被正确拒绝且索引保持 `ready`。`synthetic-policy-corpus-v1` 与 `synthetic-benchmark-candidate-v1` 已生成 120 条候选；BOSS 委托的 Agent 技术复核完成原 18 条队列并形成 100/50 local/test approved 技术集，但明确 `human_review_claimed=false`。获批单次真实运行完成 36 条款两批索引并达到 `ready`，随后在 50 条 `mvp_uat` 返回 `MVP-UAT-050_EVALUATION_FAILED`；100 条 `formal_release` 与激活未运行，无重试，Collection/容器已清理。业务代表性审批、人类 UAT、正式容量、production 和 AC-008～011/016 仍未通过或未运行。
- **2026-08-18 批量复核证据：** `CR-026` 仅为 local/test runner 启用评测批次 20，production 默认逐题。Provider 前完整离线门禁为 Backend 3061 passed / 142 skipped，PostgreSQL 16.14 current-head 完整目录连续两轮通过；真实运行随后用 5 次请求、4971 input tokens、CNY 0.002486 完成 50 条，49/50 通过且授权泄露为 0，但一个 no-answer 假阳性使 `no_answer_false_positive_rate=0.1`，因此门禁失败并立即停止。100 条 `formal_release`、索引激活和自动重试均未运行，专用 Collection、容器和确认环境变量残留为 0。
- **第二次诊断复跑：** BOSS 另行授予同一边界的一次性权限后，结果完全复现为 5 次请求、4971 input tokens、CNY 0.002486、49/50 与 1 个 no-answer 假阳性。安全输出只得到可丢弃数据库 runtime UUID，因当次未保留到冻结 source case ID 的映射而无法定位问题；runner 已离线补齐该映射但没有第三次调用。第二次授权已消耗，100 条、激活和重试仍未运行，资源残留为 0。
- **完成标准：** 索引可重建且与 PG 成员一致；越权/失效证据不进入回答；引用失败稳定拒答。
- **最小验证：** Qdrant/PG 一致性、权限负例、历史日期、引用白名单、无答案和固定评测运行。

### BETA-VS-06 审核任务、规则目录和人工复核

- **状态：READY；实现状态：VERIFIED（Backend runtime）**
- **目标：** 创建冻结快照，运行规则/检索/解释，完成财务初审和审计 high 风险复核。
- **范围：** AUD-001～008、规则目录发布、风险与复核、Job/Outbox 恢复。
- **非目标：** 动态 DSL、在线规则编辑、AI 决策。
- **代码锚点/SSOT：** `backend/app/models/audit.py`、`backend/app/audit/*`、`backend/app/models/reliability.py`；矩阵 `AUD-001～008`。
- **前置条件：** BETA-VS-02/05；规则与检索失败必须按冻结降级语义落事实。
- **已冻结合同：** `CR-018-R1/RFV1-D-005～006/008` 已固定静态 15 规则目录、整批幂等发布、执行状态矩阵、取消/失败/过期、父对象一致性、有效 high gate、同人职责分离和锁序；`GAP-066/068` 与 `OQ-04/10` 关闭。
- **当前进展：** 020/023 迁移、15 规则显式整批 publisher、任务/执行/不可变快照/规则结果/风险 Repository、审核 Job Executor、财务初审、high 风险审计复核、退回/取消/过期、重审与事实变化传播均已落地。真实 LLM 风险解释只读取冻结规则事实，不能修改规则结果或等级；成功时解释 JSON/hash 与完成审计同事务采用，失败时保存 `degraded` 且规则结果不变。隔离 PostgreSQL、真实 MiniMax smoke、浏览器财务闭环和 `audit_execute` 强杀恢复已有分层证据；代表性质量、容量、production 与 AC-007/012/013/015 仍为 `NOT_RUN`。
- **完成标准：** 快照不可变、状态转换和 high 门禁由 Backend/DB 强制；失败恢复不重复业务事实。
- **最小验证：** 状态机、数据库约束、Worker 恢复、high 权限负例、快照不可变和重审 E2E。

### BETA-VS-07 PDF/XLSX 报告与下载

- **状态：READY；实现状态：VERIFIED（Backend/MinIO/报告页）**
- **目标：** 从冻结审核执行生成版本化 PDF 和 XLSX，保存 MinIO，并经鉴权下载。
- **范围：** REP-001～003、报告过期、固定列、引用/版本、公式注入保护。
- **非目标：** Word、Markdown、多模板和在线编辑。
- **代码锚点/SSOT：** MVP-VS-05、`backend/app/reports/spreadsheet_safety.py`、`backend/app/reports/xlsx_writer.py`、`frontend/src/views/AuditReportView.vue`；矩阵 `REP-001～003`。
- **前置条件：** 审核状态和报告状态矩阵已冻结；XLSX/PDF 内部 Writer 已分别锁定 `XlsxWriter==3.2.9` 与 `ReportLab==5.0.0`，正式版本化报告仍依赖 BETA-VS-06 的审核执行与状态事实。
- **当前进展：** 020/023 迁移与正式 payload 在 completed execution 后自动创建版本化报告 Job/Outbox；Worker 可先生成严格、带未审批声明的真实 LLM 报告草稿，并把草稿 JSON/hash 与完成审计原子采用，再生成正式 PDF/XLSX。草稿失败保存 `degraded`，不阻断基于确定性事实的报告。MinIO 写入、鉴权读取、篡改拒绝、浏览器 PDF 预览/XLSX 下载动作、报告强杀恢复和受限真实 MiniMax 草稿 smoke 已有分层证据。固定合成正式报告又在宿主与当前本地 Backend 镜像中通过 PDF 语义/字节一致、XLSX 规范化内容一致和 Poppler 渲染，并由 Microsoft Excel 以禁用宏、只读方式实际打开两份 XLSX。LibreOffice `26.2.5.2` 已安装，但 Calc 对项目和最小 XLSX 的 headless 打开/转换均超过 180 秒未完成，GUI 直接启动也没有暴露窗口或进入文件打开；production、UAT 与 AC-014 仍未通过或未运行，因此 `REP-*` 保持 partial 而非 accepted。
- **完成标准：** 二进制可打开；旧版本不覆盖；源事实变化后过期；下载不泄露对象键。
- **最小验证：** PDF 文本断言、XLSX XML/公式单元格检查、MinIO 集成、权限和浏览器下载测试。

### BETA-VS-08 工作台与完整前端接线

- **状态：READY；实现状态：VERIFIED（Backend/Frontend 与隔离浏览器五角色矩阵）**
- **目标：** 五角色登录后获得权限裁剪的待办、最近任务和失败 Job，并进入真实业务页面。
- **范围：** UI-002、FE-002 以及其余页面的真实 API/loading/empty/error/forbidden 接线。
- **非目标：** 趋势分析、自由看板、前端全量聚合。
- **代码锚点/SSOT：** `frontend/src/views/DashboardView.vue`、`JobStageIndicator.vue`、Backend AUDIT/OPS Router；矩阵 `FE-002～008`。
- **已解除阻断：** OQ-06/GAP-067 已关闭；`dashboard-summary-v1` 固定由 Backend 按当前 Actor 权限投影摘要、待办和最近失败 Job，Frontend 不枚举 Job ID、不全量抓取业务数据，也不显示无权限卡片。
- **当前进展：** Dashboard Router/Service/Repository、严格 Schema/decoder、五角色权限裁剪和 loading/empty/error/forbidden/刷新状态已实现并通过聚焦 Backend/Frontend 测试。其余主要 P0 页面均已接真实 API。2026-08-16 当前 checkout 的隔离浏览器使用五个纯角色账号逐一登录：财务审核、审计复核与合同管理员获得业务导航但无用户管理入口，审计复核的供应商详情不显示写入口；只读角色仅显示工作台和审核任务；系统管理员仅显示工作台、用户管理和操作日志。各角色对未授权直达路由均进入 `AUTH_FORBIDDEN`，最终登录日志 manifest 精确包含五个 Actor，页面 warning/error 为 0。共享 `PageTabs` 的 roving `tabindex`、左右方向键循环、`Home`/`End` 聚焦和发票/知识页 `tabpanel` 关联已通过 257 个聚焦前端用例、typecheck/build，以及一次隔离发票详情真实浏览器切换，页面 warning/error 为 0。后续 Chrome `151.0.7922.138` 原生按键已通过登录页 Tab、Enter 登录、authenticated shell/dashboard Tab 与 skip-link 聚焦主内容；Edge 控制因 URL 安全策略未形成证据。全 P0 路由键盘矩阵、屏幕阅读器专项、容量、production 和正式 AC 仍为 `NOT_RUN`。
- **完成标准：** 五角色只看到授权摘要和资源；刷新可恢复；所有业务页不再依赖静态 fixture/Mock DTO。
- **最小验证：** 五角色 fixture 契约测试、刷新恢复、IDOR 负例、关键页面浏览器 E2E 和可访问性检查。

### Beta 退出条件

- P0 10 项均有真实 Backend 路径，不再只有纯函数或静态页面。
- 核心合同/发票/制度/审核/报告链在隔离环境可重复运行。
- `TEST-003～006` 有实际 API、集成、AI 回归和安全证据。
- owner-delegated local/test 技术集的 50 条真实评测为 `FAILED (49/50)`，100 条因失败即停为 `NOT_RUN`；经业务人工批准的代表性 50/100 条质量、production 与正式验收继续明确标记 `NOT_RUN`。

## 6. Production readiness slices

### LOCAL-MVP-PROFILE 本机可用验证

- **Profile 状态：DEFINED / READY；运行时状态：VERIFIED；管理员恢复：VERIFIED；用户会话/授权读取/SoD：VERIFIED；YHBX Local MVP UAT：ACCEPTED（2026-08-18）**
- **目标：** 在 BOSS 当前 Windows + Docker Desktop 本机，以当前实际使用者 1 人、系统支持多账号/五角色、loopback-only、Nginx/HTTP、ClamAV、OCR/AI 关闭的边界运行当前 P0 应用；不承诺多人并发容量。
- **固定边界：** 入口 `http://localhost:8443` 且只绑定 `127.0.0.1`；全局 HTTP Profile 不生成 TLS 证书；PostgreSQL/MinIO 使用本机数据卷；Secret 只从仓库外受管文件挂载；重要操作前本地备份；无异地备份、正式容量、保留期、RPO/RTO、DAST、remote 或分支保护承诺。YHBX 同时承担本阶段 UAT 签署和发布责任。
- **当前运行证据：** 2026-08-17 从当前 checkout 冷启动既有受管 `finaudit-local` 数据，启动器输出 `LOCAL_STACK_START=PASS`；Alembic 为 `20260817_024`；10 个长期服务运行且无异常退出；`/health/dependencies` 为 `ok`、全部必需依赖失败数为 0、Scanner 为 `ok`、AI Provider 为 `disabled`；8443 只监听 `127.0.0.1`；Frontend 返回 200 并由真实浏览器渲染登录页。既有 PostgreSQL/MinIO 数据卷未清除。
- **管理员恢复证据：** BOSS 明确授权后，先执行 PostgreSQL/MinIO 权威本地备份并输出 `LOCAL_STACK_BACKUP=PASS`；随后生成仓库外 48-byte 随机恢复密码文件，通过现有 `UserManagementService.reset_password()` 完成 CAS、密码策略、幂等、审计、失败计数清零、旧会话撤销和强制换密。数据库终审确认账号 active、未锁定、活动会话为 0、`users.password_reset/succeeded` 的 actor 等于目标管理员；不读取密码的真实登录又返回预期 `AUTH_PASSWORD_CHANGE_REQUIRED`，输出 `LOCAL_ADMIN_FORCE_CHANGE_LOGIN=PASS`。未直接编辑密码 Hash，未输出密码或 Token，临时容器残留为 0。
- **最终认证证据：** BOSS 已亲自完成强制换密并重新登录。数据库确认账号 active、失败数 0、未锁定、`force_change_on_login=false` 和 1 个普通活动会话；真实浏览器显示本地管理员/系统管理员工作台，用户管理页成功读取当前用户并显示全局“密码至少 6 个字符”，直接访问文件管理安全转入 `AUTH_FORBIDDEN`，全部页面 console warning/error 为 0。恢复密码内容先清零后已删除。
- **UAT 签署：** YHBX 于 2026-08-18 明确回复 `Local MVP UAT通过`；签署范围、证据和排除项记录于 `docs/testing/local-mvp-uat-2026-08-18.md`。该结论只接受本机 loopback HTTP Local MVP，不改变 production 状态。
- **Local MVP AC 裁定：** `CR-025` 将 AC-001、AC-002、AC-015、AC-016 调整为当前本机口径；当前 HTTP 安全基线/浏览器终审、文件链、备份/隔离恢复/冷启动和既有恢复门禁已逐条绑定，四项状态均为 `ACCEPTED`。证据见 `docs/testing/local-mvp-ac-acceptance-2026-08-18.md`；扩大环境时必须重新验收。
- **Local MVP 发布决定：** YHBX 已明确选择只按 CR-025 收口；`docs/releases/local-mvp-0.1.0-2026-08-18.md` 记录应用状态 `GO / LOCAL MVP ONLY`。13 个 TEST/DEP 工作包继续保持 `partial`，production 与正式质量转入后续目标。`origin` 已配置为 BOSS 指定的 GitHub 仓库，`release/local-mvp-0.1.0` 已通过普通 push 发布且未使用 Force Push；远程核验结果为该分支 `protected=false`、Rulesets 为 0，远程治理因此保持 `partial` 并转入后续目标。
- **非目标：** production、局域网/公网开放、真实域名/CA、OCR、AI Provider、正式容量、异地恢复或正式 AC 签署。

### PROD-VS-01 可重复 Compose 环境

- **状态：VERIFIED（`local-compose-v1`）；production BLOCKED**
- **目标：** 从空主机启动 frontend/backend/worker/PostgreSQL/Redis/MinIO/Qdrant/Nginx，AI 默认关闭。
- **范围：** DEP-001～003、固定镜像、网络隔离、健康检查、初始化和 smoke。
- **非目标：** Kubernetes、自动 CI/CD、真实 Provider。
- **代码锚点/SSOT：** `infra/compose/compose.local.yml`、Backend/Frontend Dockerfile、`infra/env/.env.example`、`scripts/start-local-stack.ps1`、`scripts/stop-local-stack.ps1` 与 `docs/runbooks/local-stack.md`。
- **已解除本地阻断：** OQ-12 的 local 部分已由 `local-compose-v1` 关闭；固定 tag+digest、loopback HTTP 入口、内部 app/data 网络、ClamAV 更新网络、Qdrant 1.10 Collection、受管 Secret mount 和 first-org/admin 初始化均已有可执行 Profile。`CR-024` 进一步移除内置证书生成/挂载并批准全局 HTTP。
- **当前证据：** 从受管空项目创建完整服务、执行 020 迁移和幂等 bootstrap、等待 `/health`/依赖就绪、通过认证 smoke、普通停止后冷启动，并确认只有 Nginx 映射 `127.0.0.1` 端口。production 主机/GPU、域名/CA、Secret Manager、资源规格和发布仍为 `BLOCKED/NOT_RUN`。
- **完成标准：** 文档不再提供不存在的命令；`docker compose config`、冷启动、重启和 smoke 均有实际退出码。
- **最小验证：** 空环境启动、重启持久性、数据端口不外露和日志 secret 扫描。

### PROD-VS-02 依赖健康与业务就绪

- **状态：VERIFIED（local）；production BLOCKED**
- **目标：** 提供脱敏、可操作的依赖健康和业务 smoke，而不把进程健康冒充业务健康。
- **范围：** `/health/dependencies`、Worker、PG、Redis、MinIO、Qdrant、Scanner；AI 按 Profile 作为可选/必需依赖。
- **非目标：** 完整监控平台。
- **代码锚点/SSOT：** `backend/app/api/v1/endpoints/health.py`、`backend/app/schemas/health.py`；矩阵 `DEP-004`。
- **已解除本地阻断：** OQ-13/GAP-031 已由 `dependency-health-v1` 关闭；固定顺序、`required/status` 投影、`ok|unavailable|disabled`、必需/可选和 200/503 聚合语义已进入技术 SSOT 与 OpenAPI。
- **当前证据：** 单元测试覆盖每个探针成功、失败、超时和脱敏；完整 local 栈实际返回 200，强制停止必需 Worker 后返回 503，恢复 Worker 后重新 200。`verify-local-stack.ps1 -FileUpload` 把依赖就绪与 HTTP 文件业务 smoke 分开输出；`-OperationsReadiness` 又在持久栈核对十服务运行态、`unless-stopped`、5×10 MiB 有界日志和受管 `/metrics` 401/200。production 告警、监控和 SLO 仍未运行。
- **完成标准：** 进程健康、依赖健康和业务 smoke 三类证据分开；必需依赖失败按冻结规则返回 503。
- **最小验证：** 每个依赖成功/失败/超时测试，响应不含地址、凭据或底层异常。

### PROD-VS-03 真实 AI Provider 环境

- **状态：PARTIAL（local Chat/Embedding、完整知识库 E2E、Event/Policy v2、PostgreSQL 审计与 Redis 门禁 VERIFIED；production/代表性质量 NOT_RUN）**
- **目标：** 在隔离 fixed-test Profile 运行真实 Chat/Embedding，再独立批准 production canary。
- **范围：** AI-001/002/003/005 的 HTTP Adapter、durable event、费用/Token、超时、Trace 和回滚。
- **非目标：** 多 Provider 平台、A/B、Agent、在线 Prompt 管理。
- **代码锚点/SSOT：** `backend/app/ai/*`、`backend/app/repositories/ai_call_audit.py`、`backend/app/services/ai_call_audit.py`、`backend/app/services/ai_call_event_sink.py`、版本化 Policy/Schema 机器制品；矩阵 `AI-001～005`。
- **已完成 local Chat：** `CR-019` 首次固定 MiniMax-M3 endpoint/model/version/pricing、secret slot、网络/字节/deadline/预算和采样，其真实 smoke 证据由 `CR-021` 组合 Profile 继续沿用；OpenAI-compatible Adapter、Gateway、持久 EventSink、共享事务采用、合同/发票严格输出、RAG、风险解释、报告草稿与 OPS-005 已接线。发票无证据币种由 `022` 闭合。最新受限真实 smoke 覆盖五条生成链，7 次 Provider attempt 对应 7 条持久审计；隔离 PostgreSQL AI/Audit/Retrieval scopes 与聚焦单测通过。
- **已完成 local Embedding、完整知识库 E2E 与 v2 审计：** `CR-021/022` 与 `minimax-m3-bailian-qwen37-local-v2` 固定百炼北京兼容 endpoint、`qwen3.7-text-embedding`、1024 维、批次 20、30 秒 deadline、CNY 价格/预算、域名和 secret slot。OpenAI-compatible Adapter 经 Gateway 接入 Backend RAG 与 Worker 索引/评测；Event v2/CNY 在 Provider 前持久预留，并要求 completion 与 Query、索引批次或评测结果同一 PostgreSQL 事务采用。Hash 与百炼索引不能混用；Worker 一批只调用一次。首次获授权的付费 smoke 使用固定两条短合成文本且只尝试一次，成功返回 2 个 1024 维向量和 43 input tokens，持久终态为 `succeeded`，权威实际费用为 CNY 22 microunits。随后单独授权的完整 local/test E2E 以 7 次请求、3231 input tokens 和 CNY 1616 microunits 完成 15 个成员的 Worker 索引、Qdrant green、Top-5 与 5/5 smoke；激活按 100 条 `formal_release` 门禁被正确拒绝，索引保持 `ready`。两次授权均已消耗，运行均未输出密钥、文档原文或向量。
- **已完成 local Redis 运行门禁：** `RedisAiRuntimeControl` 使用 Redis server time 与 Lua 原子维护 `rag/async_generation/embedding` 三个独立并发、RPM、TPM 和 burst 池，并按不可逆目标哈希维护滚动失败窗口、open deadline 与单 half-open probe。Chat/Embedding 都严格在 durable reserve 前取得许可，拒绝时不写 started；Provider 成功但 Redis 完成失败时不可采用。29 项聚焦测试和锁定 Redis 7.4.9 digest 的 3 项 Redis 专项集成测试通过；当前 Redis/Celery wrapper 共 4 项通过，临时容器已清理。
- **Event/Policy v2 审计边界：** Event v1 和 legacy `reserved_cost_micro_usd` 只用于历史回放；Event v2、迁移 `20260817_024` 和 OPS-005 使用 `cost_currency`、`reserved_cost_microunits`、`actual_cost_microunits`，初始只允许 USD/CNY/内部不计费，禁止 FX 和跨币种汇总。Chat 固定 USD，百炼 Embedding 固定 CNY；任一权威实际费用缺失时 summary 实际费用为 `null`。
- **剩余前置条件：** 人工复核并批准代表性 50/100 条检索集，分别授权和运行真实质量评测，100 条正式门禁通过后才允许按既有状态机激活；另行批准 production Profile、Secret Manager、quota、canary 和回滚，并在目标环境重新验证网络、容量和监控。已消耗的两次 local/test 授权不能复用于这些操作。
- **阻塞原因：** local/test 的真实 Chat/Embedding、完整索引链、USD/CNY 审计和 Redis 门禁已有证据；候选集仍未获人工批准，代表性 50/100 条真实质量评测及 production Secret Manager/容量仍未运行或决定。
- **解阻最小决定：** local/test Provider、完整索引链与 Event/Policy v2 决策缺口已关闭；先完成 18 条人工复核并冻结 50/100 条批准集，再对两次付费评测分别授权；production canary 独立验收，不复用 local secret 或证据。
- **完成标准：** fixed-test 与 production 证据分开；API Key 不进文件/日志；持久事件失败时 AI 结果不成为业务事实。
- **最小验证：** zero-socket 套件、真实生成/Embedding、主动超时、Trace、结构合法率、费用上限、并发控制和 canary rollback 分层运行。

### PROD-VS-04 安全、性能与恢复

- **状态：PARTIAL（本地 Scanner/恢复已验证；production BLOCKED）**
- **目标：** 完成生产认证加固、恶意文件扫描、性能基线、备份恢复、Qdrant 重建和故障注入。
- **范围：** TEST-006/007、DEP-005/006、日志/指标脱敏、RPO/RTO 演练。
- **非目标：** P1 完整可观测性平台。
- **代码锚点/SSOT：** `scripts/verify-local-offline.ps1`、`scripts/verify-local-stack.ps1`、`scripts/smoke_local_security.py`、`infra/compose/compose.local.yml`、runbook 与测试证据目录；矩阵 `TEST-006/007`、`DEP-005/006`。
- **已完成的本地切片：** 官方 ClamAV 1.5.3 INSTREAM clean path、依赖故障 503/恢复、`file_process` scan 中 Worker SIGKILL（退出码 137）/同容器显式受管重启/Maintenance attempt 2/`scan → parse → markdown` 恢复/下游合同提取，以及 `contract_extract`、`invoice_extract` attempt 1 `extract` 中 Worker SIGKILL（退出码 137）/恢复前零业务事实/attempt 1 `failed/LEASE_EXPIRED`/Maintenance attempt 2/唯一事实收敛均已实际通过；发票门禁另精确核对唯一明细、13 个字段证据、1 条明细证据、绑定、追加日志与客户端详情/原件。`audit_execute` attempt 1 `evaluate` 中 Worker SIGKILL（退出码 137）、唯一孤儿数据库等待后端终止、恢复前零规则/风险/执行日志、attempt 1 `failed/LEASE_EXPIRED`、Maintenance attempt 2、15 条唯一规则、2 条唯一待复核风险、追加日志和客户端审核详情也已实际通过。`local-ai-audit-crash-recovery-v1` 另在 Provider 关闭时真实 SIGKILL Maintenance 并验证 AI 审计投影事务回滚、同容器恢复、Outbox 顺序/唯一事实、日志脱敏和零残留。PostgreSQL custom dump、MinIO 停机一致归档、SHA/行数/内容摘要核对、全新项目隔离恢复、Redis/Qdrant/ClamAV 派生状态重建和恢复后冷启动也已通过；npm production/full audit 使用官方 registry 均为 0 vulnerabilities。`local-performance-baseline-v2` 在独立 local Compose 全新栈与同栈新 run 各连续三轮运行：每轮 20 次审核列表与 20 次单文件上传受理分别满足 P95 ≤ 800 ms、≤ 3 s；每轮默认最大 20 件批次及同键重放均在 3 s 内返回，全部批量 Job 成功，207 部分失败与第 21 件 413 合同准确，PostgreSQL 对每个 run 精确确认 61 组文件/Job/attempt-1 scan step/published Outbox 且超限零副作用；每轮 3 个审核任务同时提交后也均形成唯一执行、Job、快照和 15 条规则结果。scan-only、批量与审核执行耗时只记录为本机小型合成参考，不映射到清晰发票、20 页合同、RAG 或正式容量阈值。`local-security-baseline-v1` 还实际通过 TLS/CSRF/锁定/防枚举/角色拒绝/存在性隐藏/篡改 Token/Trace 审计/审计失败回滚/操作日志不可变/日志哨兵、容器只读根文件系统、`no-new-privileges`、最小 capabilities 和唯一 loopback 主机端口检查，并通过真实 Nginx/HTTP、ClamAV、Worker、制度双人审批、安全专用 100 条合成集、Qdrant 索引激活与 PostgreSQL 审计验证直接/间接 Prompt Injection 安全拒答和日志无 canary。浏览器增量通过受门禁保护的一次性 loopback 中继访问同一 Nginx/Backend/Qdrant 链，页面拒答、控制台、数据库审计和容器日志均通过。
- **PostgreSQL current-head 证据：** 当前 `20260817_024` 的完整 `integration/database` 目录为 149 项；在既有业务事实上新增 Event v2 USD/CNY 通用费用列、v1 非空历史保留、pending/Outbox 升级封锁、v2 降级封锁和 CNY OPS-005 投影后，PostgreSQL 16.14 Full wrapper 在同一次显式调用中连续两轮通过，输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok`、`POSTGRESQL_CURRENT_HEAD_RUN=2/2 status=ok`、不可变 `POSTGRESQL_IMAGE_ID=sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` 与 `POSTGRESQL_CURRENT_HEAD=PASS`。022 的发票币种门禁仍保持，024 不进行 FX 或 CNY→USD 转换。门禁继续使用 `--pull never`，负向自测锁定 fallback、1 GiB tmpfs、Secret 不进入参数、身份清理和失败不得伪造 PASS。
- **当前浏览器完整闭环证据：** `scripts/verify-financial-loop-browser-gate.ps1` 已在 2026-08-18 当前 checkout 显式输出 `FINANCIAL_LOOP_BROWSER_GATE=PASS`。门禁固定使用本地不可变 PostgreSQL/Redis 镜像 ID 和 `--pull never`，真实浏览器完成两类 DOCX 上传、Scanner、Dispatcher/Celery Worker、合同/发票专用提取、人工确认、供应商原子修正/激活和双来源复用、主合同建议/确认、15 规则审核、财务复核、ready PDF/XLSX 与五角色矩阵；受保护 manifest 精确断言 2 个文件/绑定、1 个合同/发票/供应商/关系/任务/执行/报告、1 条聚合供应商纠错、2 次 resolve、1 次 update 和 5 个登录 Actor。一次错误上传 Actor 的运行被 manifest 409 拒绝并清理，不计通过证据；最终接受轮页面控制台 warning/error 为 0，专用 PostgreSQL/Redis 容器最终为 0，本地 MinIO 数据卷按启动器既有策略保留。该合成 loopback 证据不证明 production Scanner/OCR、真实 Provider、正式可访问性、业务代表性 UAT、production 或任何未单独签署的 AC。

- **2026-08-18 TEST/DEP 运维增量：** 持久 `finaudit-local` 已在新权威备份后原地重建并通过 `LOCAL_OPERATIONS_READINESS=PASS`；`audit_local_backups.py` 对三份完整备份输出 `LOCAL_BACKUP_AUDIT=PASS`，最新备份又在独立项目完成 PostgreSQL 行数、MinIO 摘要、Redis/Qdrant 重建、ClamAV 重载、运维门禁和停止后冷启动。当前安全栈再次输出 `LOCAL_SECURITY_BASELINE=PASS`，覆盖单一 `nosniff` metrics、5×10 MiB 日志、Worker 自动重启与真实 Qdrant Prompt Injection。完整证据和剩余边界见 `docs/testing/test-operations-evidence-2026-08-18.md`。
- **当前 HTTP 性能重跑：** 首轮数值通过但机器 JSON 仍写旧 `https-nginx-backend`，不计当前环境标签证据；修复并单测固定 `http-nginx-backend` 后，同栈新 run 三轮再次输出 `LOCAL_PERFORMANCE_BASELINE=PASS`。列表 P95 为 `10.607/10.647/10.978 ms`，上传受理 P95 为 `36.794/41.385/38.023 ms`，20 件批次/重放、部分失败、21 件 413 与三审核任务唯一结果均通过。该小型合成结果不扩展到正式参考环境完整容量。
- **报告制品兼容性证据：** `scripts/verify-report-artifact-compatibility.ps1` 已在宿主与当前本地 Backend 镜像分别生成固定正式 PDF/XLSX，并输出 `REPORT_ARTIFACT_COMPATIBILITY=PASS`。两份 3 页 PDF 字节相同且由 Poppler 渲染；两份 XLSX 规范化工作表/单元格内容相同并由 Microsoft Excel 禁用宏、只读实际打开。LibreOffice `26.2.5.2` 已安装，但 Calc 对项目和最小 XLSX 的 headless 打开/转换均超过 180 秒未完成，因此其兼容性仍为 `NOT_RUN`。该合成门禁不替代 production、UAT、AC-014 或正式 AC。报告页另在桌面和 390×844/375 px 下通过 landmark、标题、控件命名、iframe title 与页面级零横向溢出检查；Chrome 登录/工作台原生 Tab 与 skip-link 局部路径通过，但 Edge、全 P0 路由键盘矩阵和屏幕阅读器仍未验收。
- **本地镜像扫描证据：** Docker Scout 1.23.1 对当前 Bookworm Backend 镜像 `44b77246577e` 复现 `2C/2H`，`--only-fixed` 为 `0C/0H`；四项均来自 Debian `perl-base` 且无已修复版本。官方 Python 3.10.20 Trixie 锁定 digest 候选也为相同 `2C/2H`，因此没有保留无收益的基础系统迁移。既有修复仍是把直接处理不可信 PDF 的 `pypdf` 固定为 `6.14.2`，并从运行镜像删除 `pip/setuptools/wheel`。这只是本地镜像证据，不满足 production 严重/高危为 0 的签署门槛。
- **仍阻塞：** P0 单组织约束下无法构造的跨组织 IDOR、全局 HTTP Profile 缺少传输加密和服务器身份认证、Edge/屏幕阅读器/全路由键盘矩阵、LibreOffice Calc 启动挂起、代表性合同/发票与业务代表性检索质量集、正式 DAST、正式参考硬件/模型/代表性文档规模与完整容量、清晰发票与 20 页合同处理、代表性规模 Top-5/完整 RAG 质量、正式 RPO/RTO、保留期、production Scanner/OCR、生产 Secret Manager/轮换、production metrics 采集/告警/SLO、production 镜像复扫与剩余 Bookworm Perl `2C/2H` 风险处置签署、主机断电和异地恢复尚未按目标环境完成。owner-delegated 100/50 技术集的真实 50 条门禁当前失败，不能把 local/test 技术审批当成人类 UAT；已通过的真实 Provider smoke、完整 local/test 知识库 E2E、报告合成兼容性、小型合成默认批次、local HTTP/Qdrant/浏览器提示注入、本地安全、性能、恢复与镜像扫描证据也不得冒充正式基线。
- **解阻最小决定：** 为目标环境签署一份安全与恢复 Profile；本地性能探索不得冒充该正式基线。
- **完成标准：** 严重/高危为 0；三轮性能满足 `PRODUCT_REQUIREMENTS.md`；恢复演练有命令、退出码、校验和和实际 RPO/RTO。
- **最小验证：** 安全负例、性能三轮、PG/MinIO 恢复、Redis 清空、Qdrant 重建和 Worker/依赖故障注入。

### PROD-VS-05 正式验收与发布

- **状态：BLOCKED**
- **目标：** 基于真实前序证据执行 AC-001～016、UAT、回滚演练和发布决定。
- **范围：** TEST-001～007 汇总、已知限制、风险接受和发布记录。
- **非目标：** 用文档存在、Mock、静态构建或局部单元测试替代验收。
- **代码锚点/SSOT：** `PRODUCT_REQUIREMENTS.md` 的 AC-001～016、`docs/testing/p0-traceability-matrix.csv`、实际测试/运行证据和发布 runbook。
- **前置条件：** Beta 完成，PROD-VS-01～04 完成，OPEN QUESTIONS 均已裁决或明确不进入本次发布。
- **阻塞原因：** 前序运行、恢复、安全和环境证据尚未完成；当前局部离线证据不能组成正式验收。
- **解阻最小决定：** 不新增统一合同；逐项完成前序证据，对不进入本次发布的问题明确排除范围，再执行 AC/UAT。
- **完成标准：** 每个 AC 有可复现命令/步骤、环境、输入、退出码和结果；未通过项不能隐藏在总 PASS 中。
- **最小验证：** 独立重跑关键证据；发布、回滚、备份恢复和 UAT 分别签署结果，不混成一个状态。

## 7. OPEN QUESTIONS

| 编号 | 真实未决问题 | 推荐最小决定 | 只阻断 |
|---|---|---|---|
| OQ-01（CLOSED 2026-08-14） | 检索评测 50/100 条如何分层 | `CR-018-R1`：5 条 smoke、至少 50 条 MVP/UAT、至少 100 条正式发布门禁 | CLOSED；真实 5 条 smoke 已运行；`synthetic-benchmark-candidate-v1` 已生成 120/100/50 候选，owner-delegated 非人类技术复核已关闭 18 条队列并允许 local/test 可丢弃 approved 数据集；单次真实运行完成 36 条款索引后在 50 条门禁失败，100 条与激活未运行。安全专用 100 条全 `no_answer` 集只用于 local Prompt Injection；业务代表性质量与正式验收未通过 |
| OQ-02（CLOSED 2026-08-14） | Qdrant Collection 按知识库还是环境+模型/维度 | `CR-018-R1`：环境+Embedding 模型身份+向量维度，名称显式注入 | CLOSED；Backend 与真实 Qdrant Gate 已验证，production 未运行 |
| OQ-03（CLOSED 2026-08-14） | 检索顺序是 Qdrant 初筛还是 PG 允许集先行 | `CR-018-R1`：PG 允许集 → Qdrant must-filter → PG 终审 | CLOSED；Repository/Service 与安全负例已验证 |
| OQ-04（CLOSED 2026-08-14） | 审核 failed/cancel、终态字段、high gate 和报告迁移 | `CR-018-R1` 已冻结执行/报告状态矩阵、有效 high gate、SoD、父对象约束与锁序 | CLOSED；Schema/runtime/Frontend 与隔离财务浏览器闭环已验证，正式 AC/production 未运行 |
| OQ-05（CLOSED 2026-08-14） | Supplier generic tax、复用、来源回填和纠错 | `CR-018-R1` 已冻结统一投影、三态、精确复用、锁序、纠错与稳定错误码 | CLOSED；Backend/PostgreSQL/Frontend 与合同/发票双来源供应商浏览器写 E2E 已验证，正式 AC/production 未运行 |
| OQ-06（CLOSED 2026-08-15） | Dashboard/失败 Job 如何安全发现 | `dashboard-summary-v1`：Backend 按 Actor 权限投影摘要、待办与有界最近失败 Job；Frontend 不枚举 ID、不全量聚合 | CLOSED；Router/Service/Repository、五角色 Backend/Frontend 契约测试及浏览器导航/禁止直达矩阵已通过，可访问性专项、正式 AC/production 未运行 |
| OQ-07（CLOSED 2026-08-14） | 文档链 quote、坐标原因、Markdown parser/HTML/table | `CR-018-R1` 已冻结 quote、两类原因、CommonMark/GFM table、禁 raw HTML 与 `table_asset_v1` | CLOSED；Backend runtime 与知识库/问答 Frontend 已验证，多业务文档拆分仍不进入本切片 |
| OQ-08（CLOSED 2026-08-12；HTTP/PASSWORD UPDATE 2026-08-17） | Auth 密码/JWT/Refresh/锁定/remember_me 与权限字典 | 已冻结 `auth-mvp-v1` + `p0-permissions-v1`；`CR-023` 全局密码最小 6，`CR-024` 全局 HTTP 与 scheme-derived Cookie Secure；五 Auth API、26 code、五角色映射、deny-overrides 与 SoD 见产品/技术 SSOT | CLOSED；Auth、用户写、Break-glass、操作日志、local first-org/admin bootstrap 与 Nginx/HTTP 认证 smoke 需按新 Profile 重跑；production 与 AC-001 未运行 |
| OQ-09（CLOSED 2026-08-12） | archived 文件重复上传语义 | 已冻结 `archived-reupload=conflict-v1` + `local-minio-v1`：同组织 SHA-256+大小命中 archived 时稳定 409 `FILE_ARCHIVED_DUPLICATE`，不得复用、恢复、新建事实/Job/对象；local MinIO 使用 tag+digest、内部 HTTP、七 Bucket和运行时非机密变量注入 | CLOSED；批量/预览/归档/重试已实现，隔离浏览器与完整 local TLS/官方 ClamAV 文件 smoke 已通过；production Scanner、容量与 AC 仍未运行 |
| OQ-10（CLOSED 2026-08-14） | 规则目录元数据、稳定实现绑定和原子发布 | `CR-018-R1`：应用内静态 15 规则、release/manifest hash、整批发布、历史版本不可改 | CLOSED；publisher、执行器与 PostgreSQL 不可变约束已验证 |
| OQ-11（LOCAL PROFILE CLOSED 2026-08-17） | AI fixed-test/production endpoint、模型、维度、费用、CIDR | `CR-019` 冻结 MiniMax Chat；`CR-021/022` 冻结百炼 local/test Profile 与 Event/Policy v2 USD/CNY/no-FX 审计；默认 calls-disabled | local 决策、受限 smoke 与完整知识库索引链 CLOSED；代表性 50/100 条真实质量评测和 production 继续留在 PROD-VS-03 |
| OQ-12（LOCAL CLOSED 2026-08-15；HTTP UPDATE 2026-08-17） | Compose 其余镜像、主机/GPU、Scanner、传输协议、RPO/RTO | `local-compose-v1` 固定镜像、loopback HTTP、官方 ClamAV、Secret mount、初始化和本地恢复；`CR-024` 移除内置 TLS 证书并全局使用 HTTP | CLOSED for local；HTTP 不允许扩展到局域网/公网，production Secret Manager、RPO/RTO、容量与重新恢复 TLS 的发布决定仍阻断 PROD-VS-04/05 |
| OQ-13（CLOSED 2026-08-15） | `/health/dependencies` 的字段和聚合语义 | `dependency-health-v1` 固定脱敏依赖集合、required/status 和 200/503 聚合 | CLOSED；单元、完整 local 200、必需 Worker 失败 503 与恢复 200 已验证 |

## 8. 决策规则

1. 每个 OPEN QUESTION 使用一页以内的前向决定；不要恢复不可得的历史签署链。
2. 决定必须写清：选择、原因、用户影响、兼容性、受影响 SSOT、最小测试和回滚方式。
3. 如果不决定也能安全完成正常路径，就只禁用未决分支，不阻断整个模块。
4. 如果决定会改变公开 API、数据库语义、状态/权限/安全或验收阈值，先更新唯一契约；否则直接编码。
5. 环境值进入 `.env.example`/Policy/Profile，产品行为进入代码和 API，测试状态进入证据文件；三者不得互相替代。
6. 示例、Mock、Demo 数据和候选 CR 不得成为运行时事实。
7. 优先采用标准库、平台能力和现有依赖；只有 PDF/XLSX/解析/OCR 等必要能力缺失时增加一个成熟依赖，并锁定版本。

## 9. 每个切片的完成记录

完成切片后只记录以下内容：

```text
slice_id:
changed_files:
ssot_changed: yes/no
tests_run:
runtime_run:
result:
not_run:
traceability_rows_updated:
remaining_risks:
```

状态必须分开表达：

- 代码已实现。
- 静态检查已通过。
- 测试已通过。
- 实际运行已完成。
- 端到端流程已通过。
- 正式 AC/UAT/production 是否通过。

任何较低层证据都不能自动提升较高层状态。
