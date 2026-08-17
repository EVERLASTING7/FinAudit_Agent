# 数据库迁移运行手册

状态：`BASE-005 PARTIAL`  
更新日期：2026-08-11

## 当前交付范围

`CR-001-R2`、`CR-003-R3`、`CR-004-R2` 与 `CR-012-R3` 已批准并同步；当前源码按已冻结的 Request 表合同实现迁移基础设施、身份核心、特权授权两张空表、API 幂等记录、空的审核规则版本表、稳定审核任务主表、空的财务主数据三表、财务关系三表，以及 Job/Step/Outbox 可靠性核心空表切片：

- SQLAlchemy 2、Alembic 和 psycopg 运行依赖。
- 只从当前进程 `DATABASE_URL` 读取迁移连接信息的 Alembic 环境。
- 缺失、空白、`CHANGE_ME`、`REPLACE_` 连接信息的 fail-closed 校验。
- Settings 与迁移入口共享 PostgreSQL URL 解析；拒绝可覆盖 authority 目标的 `host`、`hostaddr`、`port`、`dbname`、`service`、`servicefile` query 参数。
- 隐藏 SQL 参数、禁用连接池、使用 10 秒连接超时并将在线迁移会话固定为 UTC。
- 首个 revision `20260806_001`，仅启用 `pgcrypto`、`btree_gist`、`citext`。
- 第二个 revision `20260807_002` 创建 `organizations/users/roles/token_sessions`，并幂等写入五个固定角色。
- 第三个 revision `20260807_003` 只创建 `idempotency_records`，保存组织/用户级幂等键、请求哈希与脱敏响应快照，不写入种子数据。
- 第四个 revision `20260807_004` 只创建空的 `audit_rules` 规则版本表、唯一/风险约束与禁止 UPDATE/DELETE/TRUNCATE 的不可变触发器；不写真实规则，downgrade 先取得 `ACCESS EXCLUSIVE` 表锁，任一规则存在时失败关闭。
- 第五个 revision `20260807_005` 只创建空的 `audit_tasks` 稳定案件主表、16 列 M1 字段、组织内任务号唯一、三态状态、软删除理由和五个即时外键；`current_execution_id` 按 Request 延迟到执行版本表迁移再加外键，downgrade 先取得 `ACCESS EXCLUSIVE` 表锁，任一任务存在时失败关闭。
- 第六个 revision `20260807_006` 要求 PostgreSQL `server_encoding=UTF8`，原子创建空的 `contracts/invoices/suppliers` 后再添加四个循环外键，并落实合同编号、发票重复查询和 active 供应商税务身份索引；不写任何财务主数据。Downgrade 在同一事务设置 5 秒锁超时，按 `contracts → invoices → suppliers` 固定顺序取得 `ACCESS EXCLUSIVE` 锁，任一表非空时以 SQLSTATE `55000` 失败关闭，全部为空时先删循环外键再删三表，禁止 `CASCADE`。
- 第七个 revision `20260807_007` 原子创建空的 `async_jobs/async_job_steps/outbox_events`，冻结 Job/Step/Outbox 列、状态约束、索引、触发器、Lease/CAS 与安全降级合同，不创建 Handler Registry、Input/Summary Schema Bundle，也不写 Job 或 Outbox 数据。Downgrade 在同一事务设置 5 秒锁超时，按 `async_jobs → async_job_steps → outbox_events` 固定顺序取得 `ACCESS EXCLUSIVE` 锁，任一表非空时以 SQLSTATE `55000` 失败关闭，禁止 `CASCADE`。
- 第八个 revision `20260807_008` 创建空的 `break_glass_requests/user_roles`，并以 revision-owned 约束、触发器和内部函数落实特权授权 storage-schema；不创建 Repository、Service、Router、Worker 或真实 ACL 数据。该 revision 已通过 PostgreSQL 16.14 catalog、行为、并发、降级与往返 Gate。
- 第九个 revision `20260807_009` 创建空的 `supplementary_agreements/invoice_items/contract_invoices`，落实补充协议确认状态、发票明细精度及单发票唯一主合同条件索引；不创建存在 `change_seq` 歧义的 `supplementary_agreement_changes`，也不开放供应商或关系 API。Downgrade 先按 `contract_invoices → invoice_items → supplementary_agreements` 固定顺序独占锁表，任一表非空时以 SQLSTATE `55000` 失败关闭。
- SQLAlchemy 元数据实现单组织、CITEXT 活动用户名/邮箱唯一、强制换密、失败次数、软删除理由、Refresh Token 哈希/有效期、特权授权两表，以及合同、补充协议、发票、发票明细、供应商、合同发票关系和 Job/Step/Outbox 的列、约束、索引与外键合同。
- 使用 Alembic 原生 revision map 自动要求单一 base、单一 head、完整线性链，拒绝分支、merge、跨分支依赖和不可遍历历史。
- 本机隔离 PostgreSQL 的升级、降级、重升级和 secret 泄漏测试门禁。

当前 PostgreSQL storage-schema 为 **18/57 张核心表**，尚缺 39 表。2026-08-11 已在 PostgreSQL 16.14（`server_version_num=160014`）对唯一 head `20260807_009` 连续两轮执行 71/71 项并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，专用标签容器最终 0 残留，测试连接和确认变量已恢复。该结果验证了 009 及其前序迁移的 storage-schema 范围；`BASE-005`、`AUTH-005` 和 `BASE-006` 仍为 `PARTIAL`，因为其余 39 表、Repository/Service/API/Worker、真实 ACL/数据、业务运行时、Provider、浏览器与 AC 均未完成。

应用运行时数据库基础位于 `backend/app/db/session.py`：它只从已校验的 `Settings` 创建惰性 PostgreSQL Engine 和 Session 工厂，复用同一 `postgresql+psycopg` URL 解析，启用隐藏参数、连接池 pre-ping、配置化池大小及 10 秒连接超时；模块导入和工厂构造均不打开连接，提交/回滚继续由 Application Service 显式控制。`backend/tests/integration/database/test_runtime_session.py` 在显式安全 `TEST_DATABASE_URL` 下执行真实 `SELECT 1`，未配置时只记为 skip。该基础不创建 Repository、业务事务、Job/Outbox 写入或任何受保护 API，不能作为业务 runtime、`BASE-005/006` 或 AC 完成证据。

## BASE-005 57 表实施就绪账本

### 机械基线

正式表集合以需求规格 11.1 的 57 行清单和数据库设计第 5 章的 57 个 `### 5.x.x` 表定义共同约束；两者表名集合完全相等且无重复。当前 SQLAlchemy metadata、Alembic `001～009` 的 `create_table` 集合和 PostgreSQL 16.14 Gate 均对应下表 18 张 current 表。任何后续迁移都必须同时更新 ORM、migration、聚焦测试和本账本，且不得引入 57 表集合之外的物理表，除非先取得明确 CR 批准并原子同步九份 Request。

| 正式分组 | 总数 | current | missing |
|---|---:|---|---|
| 5.1 组织、用户与权限 | 6 | `organizations`、`users`、`roles`、`token_sessions`、`user_roles`、`break_glass_requests` | — |
| 5.2 文件、解析、Markdown 与异步任务 | 13 | `async_jobs`、`async_job_steps` | `files`、`file_primary_business_objects`、`document_assets`、`document_parse_versions`、`document_pages`、`document_blocks`、`document_block_corrections`、`document_content_exclusions`、`document_markdown_versions`、`markdown_source_mappings`、`markdown_validation_results` |
| 5.3 合同、补充协议、发票与供应商 | 9 | `contracts`、`invoices`、`suppliers`、`supplementary_agreements`、`invoice_items`、`contract_invoices` | `contract_fields`、`supplementary_agreement_changes`、`contract_documents` |
| 5.4 制度、分块、索引和检索评测 | 15 | — | `knowledge_bases`、`policy_documents`、`policy_approval_records`、`chunking_configs`、`document_chunk_sets`、`document_chunks`、`document_chunk_sources`、`document_index_versions`、`document_index_items`、`retrieval_eval_datasets`、`retrieval_eval_cases`、`retrieval_eval_runs`、`retrieval_eval_results`、`qa_queries`、`qa_feedback` |
| 5.5 审核任务、风险、报告与审计 | 12 | `audit_tasks`、`audit_rules` | `audit_task_items`、`audit_task_executions`、`audit_task_snapshots`、`rule_executions`、`audit_risks`、`risk_citations`、`audit_reports`、`user_corrections`、`ai_call_logs`、`operation_logs` |
| 5.6 技术支撑表 | 2 | `idempotency_records`、`outbox_events` | — |
| **合计** | **57** | **18** | **39** |

数据库设计 2.1 的对象推导总览当前只列出 56 张表，遗漏了该文档 5.3.5 和需求规格 11.1 均明确列出的 `contract_documents`。这不改变 57 表正式集合，也不得被解释为删除该表；下次获授权同步 Request 时应修正该总览。修正前，本账本只记录差异，不据此创建或省略迁移。

### 剩余 39 表依赖簇与已交付 A/B/D-root 簇

下表是依赖核对簇，不是 migration 编号或已授权实施顺序。所有未交付簇共同继承开发计划的正式前置 `BASE-002、BASE-004`；其中 `BASE-002` 已完成，`BASE-004` 仍为 `partial`。A 簇已由 `CR-003-R3` 有限授权并通过 PostgreSQL 16 storage-schema Gate；B 簇由 `CR-004-R2` 有限授权并有既有 007 Gate；D-root 三表已由 009 按 Request 既有精确表合同交付并完成当前 head Gate。上述交付均不包含业务 Repository、Service/API 或 Worker 运行时。`CR-011-R4/R5/R6` 的 R6 startup Gate C 仍是另一条独立的 `BLOCKED BEFORE RUN / NOT RUN` 边界。

| 簇 | 精确表集合 | DDL/ORM owner；后续 runtime owner | 直接依赖与当前阻断 | 获批后的首要数据库 Gate |
|---|---|---|---|---|
| A 特权授权（2，storage-schema Gate PASS） | `user_roles`、`break_glass_requests` | 每表均为 `BASE-005`；`user_roles` runtime 为 `AUTH-001～005`，`break_glass_requests` 为 work package `AUTH-005`（API AUTH-011～015） | `CR-003-R3` 9/9 批准，Gate A/B/C 与十一文件同步 PASS；008 已在 PostgreSQL 16.14 两轮 71/71，Repository/Service/API/Worker 与真实 ACL 未实现 | 已验证 catalog、时间区间排斥、职责分离、决定/撤销证据、数据库 time owner、并发与安全降级；业务授权链仍待实现 |
| B Job/Step/Outbox（3，已交付 DDL/ORM） | `async_jobs`、`async_job_steps`、`outbox_events` | 每表 DDL/ORM 均为 `BASE-005`；runtime 为 `BASE-006` | `CR-004-R2` 已批准并完成 11 文件原子同步，007 空表 DDL/ORM 与专项 Gate 已交付；GAP-040～042 仅在 contract/schema/DDL 层闭合。Handler Registry、Input/Summary Schema Bundle、Repository/Dispatcher/Worker/runtime 均待后续批准与实现 | 51/51×2 专项 Gate 已通过；运行时、Redis/Broker、真实数据、Provider 网络、部署与 production 未授权且未运行 |
| C 文件/解析/Markdown（11） | `files`、`file_primary_business_objects`、`document_assets`、`document_parse_versions`、`document_pages`、`document_blocks`、`document_block_corrections`、`document_content_exclusions`、`document_markdown_versions`、`markdown_source_mappings`、`markdown_validation_results` | 每表均为 `BASE-005`；`files` runtime 为 `FILE-001～005`，`file_primary_business_objects` 为 `FILE-003/005、CON-001、INV-001`；解析/页/块/资源/排除为 `DOC-001`，纠错为 `DOC-005`，Markdown 为 `DOC-007～008` | 物理 FK 父表来自 D/E：`files.target_knowledge_base_id` 指向 E，`file_primary_business_objects` 指向 D/E；B 是处理 Job runtime 前置。GAP-043～045、047～052、055、065 与 `CR-005/007/010` 均未闭合，父表存在前不得添加跨簇 FK | 六态扫描与归档约束、纠错不可变、资源安全、NULL 唯一、块枚举/坐标原因、跨表主对象唯一、循环/延迟 FK、并发去重 |
| D 财务明细与关系（6；D-root 3 已交付） | `contract_fields`、`supplementary_agreements`、`supplementary_agreement_changes`、`contract_documents`、`invoice_items`、`contract_invoices` | 每表均为 `BASE-005`；依次由 `CON-001/002`、`CON-003`、`CON-003`、`CON-004`、`INV-001/002`、`LINK-001～003` 消费 | 009 已创建 `supplementary_agreements/invoice_items/contract_invoices`；其余 `contract_fields/supplementary_agreement_changes/contract_documents` 通过证据/文件 FK 依赖 C，其中 `supplementary_agreement_changes` 的 `change_seq` 仍有歧义。GAP-064 不阻断本簇空表本身，但仍阻断正式 Gap 所列合同/供应商 API、CON-005/SUPP-003、`supplier_field` 纠错与供应商 AI 投影，获批 successor 同步前均不得实现，也不得改 006 或提前创建 `user_corrections` | 009 已验证 ORM/catalog 等价、金额精度、主合同条件唯一和安全降级；其余三表仍需证据 FK、变更确认及附件关系 Gate |
| E 知识库与制度（3） | `knowledge_bases`、`policy_documents`、`policy_approval_records` | 每表均为 `BASE-005`；`knowledge_bases` runtime 为 `KB-001`，`policy_documents` 为 `KB-002～003`，`policy_approval_records` 为 `KB-002～003、AUTH-005` | 现有 `organizations/users`；GAP-047～048 与 `CR-007-R1` 未批准。C 中的文件 FK 指向本簇，不构成本簇对 C 的物理 FK；`policy_approval_records.related_index_version_id` 与制度发布条件依赖 F，必须在 F 父表存在后延迟补 FK/trigger | 活动 code 唯一、有效期排斥、职责分离、审批记录追加写、发布前活动 Markdown/ChunkSet/Index 交叉约束 |
| F 分块与索引（6） | `chunking_configs`、`document_chunk_sets`、`document_chunks`、`document_chunk_sources`、`document_index_versions`、`document_index_items` | 每表均为 `BASE-005`；runtime 为 `KB-004～009` | `chunking_configs` 只依赖现有 `organizations/users`，是下述物理 root，但仍由 GAP-054 与 `CR-009-R1` 阻断合同；其余五表依赖 C/E。GAP-008/056 继续阻断 Collection/runtime 与配置发现流程，但不能被误报为空表 DDL 已获授权；`document_index_versions.evaluation_run_id` 对 G 形成延迟 FK | 配置版本/JCS hash、active 唯一、来源完整性、成员清单 hash、索引切换并发、Qdrant 仅作可重建派生事实 |
| G 检索评测与 QA（6） | `retrieval_eval_datasets`、`retrieval_eval_cases`、`retrieval_eval_runs`、`retrieval_eval_results`、`qa_queries`、`qa_feedback` | 每表均为 `BASE-005`；datasets/cases/runs/results runtime 为 `KB-011`，其中 `retrieval_eval_datasets` 还由 `AUTH-005` 约束，QA 两表为 `KB-012` | `retrieval_eval_datasets/cases` 只依赖现有组织/用户及彼此，是下述物理 root；runs/results 与 QA 链依赖 C/E/F。评测结果可引用 Chunk/制度/Markdown，QA 查询引用知识库和索引版本；不能用 fixture 或 Qdrant 状态代替 PostgreSQL FK | 数据集版本/职责分离、用例与结果唯一、汇总/排名行 CHECK、运行与索引双向延迟 FK、问答引用摘要与反馈状态 |
| H 审核结果、纠错与审计（10） | `audit_task_items`、`audit_task_executions`、`audit_task_snapshots`、`rule_executions`、`audit_risks`、`risk_citations`、`audit_reports`、`user_corrections`、`ai_call_logs`、`operation_logs` | 每表均为 `BASE-005`；items/executions 为 `AUD-001`，snapshots 为 `AUD-002`，rule executions 为 `AUD-004`，risks/citations 为 `AUD-005`，reports 为 `REP-001`，corrections 为 `DOC-005` 及对应 `CON/INV/LINK/AUD` 修正任务，AI logs 为 `AI-005`，operation logs 为 `DEP-003` | GAP-068 阻断六张 root 表的执行状态机、终态白名单、跨父对象一致性、high gate、报告迁移与降级锁序；`risk_citations` 另依赖 C/E/F 全链。`user_corrections` 等待 GAP-064 的获批 successor，`ai_call_logs` 等待 B 与获批的 CR-011 successor，`operation_logs` 等待 `CR-006/008` 与恢复合同 | 任务项提交时约束、执行状态机/不可变快照、规则结果与引用全链 FK、报告版本、纠错/AI/操作日志追加写与脱敏、分区和非空降级 |

剩余表计数不变量为 `11 + 3 + 3 + 6 + 6 + 10 = 39`；A/B 两簇五表与 D-root 三表已计入当前已验证 18 表，不再计入 missing。跨簇循环或延迟 FK 必须先创建全部父表，再以显式 `ALTER TABLE` 添加并在 PostgreSQL catalog 中逐项核对；不得用 `CASCADE`、禁用约束、Redis、Qdrant 或应用内存绕开 PostgreSQL 事实。

### 共同前置满足后的物理 root 子集

下列原 12 张物理 root 中，D-root 三表已由 009 交付；其余九表仍不得仅因同属 F/G/H 领域簇而继承整个下游链的 blocker。它们只是在各自合同唯一、共同前置完成之后具备独立排期资格；本表不批准未交付代码、不预占 migration 编号，也不代表可以绕过自己的状态、触发器、并发或降级 Gate。

| root 子集 | 表 | 直接父表 |
|---|---|---|
| D-root（3，009 已交付） | `supplementary_agreements`、`invoice_items`、`contract_invoices` | 009 已按既有父表创建并通过 PostgreSQL 16 current-head Gate；不代表对应 API/业务运行时已交付 |
| F-root（1） | `chunking_configs` | 现有 `organizations/users`；GAP-054/`CR-009-R1` 仍阻断合同，不因物理 root 身份而放行 |
| G-root（2） | `retrieval_eval_datasets`、`retrieval_eval_cases` | 当前 `organizations/users`；cases 再引用 datasets |
| H-root（6） | `audit_task_items`、`audit_task_executions`、`audit_task_snapshots`、`rule_executions`、`audit_risks`、`audit_reports` | `audit_task_items` 独立引用现有 `audit_tasks/contracts/invoices/users`；`audit_task_executions` → 现有 `audit_tasks/users`，并作为 snapshots/rule executions/risks/reports 的父表；`rule_executions` 另依赖现有 `audit_rules`，并可作为 risks 的父表 |

### 每个未来表簇的最低验收

1. **合同门禁**：对应 Request 字段、枚举、状态、索引、触发器和降级语义必须唯一；涉及 GAP/CR 时先取得明确批准并原子同步九份 Request。
2. **静态一致性**：ORM 与 migration 的表、列、类型、默认、CHECK、索引、FK、触发器集合精确相等；离线 upgrade/downgrade SQL 可生成且不含 DSN、secret、真实数据或越界种子。
3. **真实 PostgreSQL 16**：在专用可丢弃 loopback 数据库执行 `base → candidate head → base → candidate head`，逐项比较 catalog，并证明失败不会留下半表、半 FK、半触发器或错误 revision。
4. **并发与回滚**：对条件唯一、排斥、状态切换和追加写约束使用至少两个连接复现竞争；downgrade 必须使用获批锁序和超时，非空或锁失败时整事务回滚，禁止 `CASCADE`。
5. **种子与安全**：除已批准的五个固定角色和明确由业务任务拥有的版本化种子外保持空表；异常、日志、测试报告和命令输出不得回显 DSN、税号、正文、Prompt 或其他敏感值。
6. **状态边界**：只有表簇专项 Gate、全量离线门禁和独立审查均通过后才可更新本账本；单一 migration 通过不得把 `BASE-005`、`TEST-001`、P0 或任何 AC 标记完成。

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/alembic.ini` | Alembic 脚本位置；不保存 DSN |
| `backend/alembic/env.py` | offline/online 执行入口和 UTC 会话设置 |
| `backend/app/db/migration.py` | 读取、校验、脱敏 DSN 并创建迁移 Engine |
| `backend/app/models/base.py`、`backend/app/models/auth.py`、`backend/app/models/reliability.py`、`backend/app/models/audit.py`、`backend/app/models/financial.py` | 命名约定、身份核心、API 幂等记录、Job/Step/Outbox 可靠性核心、审核规则版本、稳定审核任务与财务主数据 SQLAlchemy 元数据 |
| `backend/alembic/versions/20260806_001_enable_postgresql_extensions.py` | 启用三个 PostgreSQL 必需扩展 |
| `backend/alembic/versions/20260807_002_create_identity_core.py` | 创建四张身份核心表并写入五角色 |
| `backend/alembic/versions/20260807_003_create_idempotency_records.py` | 创建 API 幂等记录表，不写种子 |
| `backend/alembic/versions/20260807_004_create_audit_rules.py` | 创建空的不可变审核规则版本表，非空降级失败关闭 |
| `backend/alembic/versions/20260807_005_create_audit_tasks.py` | 创建空的稳定审核任务主表，延迟执行版本外键，非空降级失败关闭 |
| `backend/alembic/versions/20260807_006_create_financial_master_data.py` | 原子创建空的合同、发票和供应商表，冻结身份索引与安全降级 |
| `backend/alembic/versions/20260807_007_create_reliability_core.py` | 原子创建空的 Job、Step 与 Outbox 表，冻结可靠性约束、触发器、索引与安全降级 |
| `backend/tests/unit/test_auth_models.py` | 身份元数据、固定角色、CITEXT、单组织和会话约束测试 |
| `backend/tests/unit/test_reliability_models.py`、`backend/tests/unit/test_audit_models.py`、`backend/tests/unit/test_financial_models.py` | 幂等记录、Job/Step/Outbox、审核规则版本、稳定审核任务与财务主数据的列、类型、约束和索引测试 |
| `backend/tests/unit/test_migration_config.py` | 配置脱敏、Engine 安全属性、扩展与身份切片离线升降级 SQL 测试 |
| `backend/tests/unit/test_migration_graph.py` | 单一完整线性 revision 图的离线防回归门禁 |
| `backend/tests/integration/database/test_migrations.py` | 真实 PostgreSQL `base → head → base → head` 往返测试 |

## 执行迁移

迁移命令必须由受信任的部署或运维进程显式执行。应用启动不自动迁移，仓库也不读取真实 `.env`。先通过进程环境或 Secret 机制注入 `DATABASE_URL`；目标 host、port 和 database 必须写在 URL authority/path 中，不得使用 libpq query 覆盖，再运行：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

只生成 SQL、不连接数据库：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

单元门禁分别断言 001～007 的扩展、身份、幂等、规则、任务、财务与可靠性边界，008 只创建空的 `break_glass_requests/user_roles` 及 revision-owned 对象，009 只创建空的 `supplementary_agreements/invoice_items/contract_invoices`；003～009 均不写业务种子，不得回显 DSN 或合成测试值。静态 SQL 回归与本次 PostgreSQL Gate 是独立证据，两者都不等于完整 `BASE-005/AUTH-005`。

迁移图门禁会使用 Alembic 自身的 revision map 检查单一 base/head、无分支或 merge、无跨分支依赖且 head 到 base 连续。它不硬编码当前 revision ID 或 revision 数量，因此后续合法线性迁移可直接追加；通过只证明历史可确定遍历，不证明迁移 SQL、业务表或数据升级正确。

当前有九个线性 revision。回退 009 会按 `contract_invoices → invoice_items → supplementary_agreements` 固定顺序独占锁定三表，任一表非空时以 SQLSTATE `55000` 原子失败；回退 008 会安全移除特权授权 revision-owned 对象。回退 007 会在同一事务设置 5 秒锁超时，按 `async_jobs → async_job_steps → outbox_events` 固定顺序独占锁定三表；任一表非空时以 SQLSTATE `55000` 原子失败，全部为空时按依赖逆序删除三表及四个专用函数。回退 006 会按固定顺序独占锁定 `contracts/invoices/suppliers`；任一表非空时以 SQLSTATE `55000` 原子失败，全部为空时先删除四个循环外键再删除三表。回退 005 会先独占锁定 `audit_tasks`，只在表为空时删除该表；回退 004 会先独占锁定 `audit_rules`，只在表为空时删除其表和专用不可变触发器/函数；004～009 在非空或并发写入已提交时均失败关闭。回退 003 只删除空的幂等记录表，回退 002 会删除四张身份表；继续回退到 `base` 会删除 Alembic revision 记录，但不会删除可能被同库其他对象使用的扩展：

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade base
```

离线降级门禁分别验证 009 包含财务关系三表固定锁序、5 秒超时和 SQLSTATE `55000` 非空阻断，008 只删除其 revision-owned 特权授权对象，007 包含 Job→Step→Outbox 固定锁序、5 秒超时、SQLSTATE `55000` 非空阻断与逆序删除，006 包含固定锁序、5 秒超时、SQLSTATE `55000` 非空阻断、四个循环外键先删且只删除财务三表，005 包含非空阻断且只删除审核任务表、004 包含非空阻断且只删除审核规则对象、003 只删除幂等记录表、002 只删除其四张表、001 只回退 revision 记录；九者都禁止 `DROP EXTENSION`、`CASCADE` 和 DSN 泄露。

扩展安装通常需要高于运行时应用账号的权限。生产环境应使用受控 migration 身份显式执行，运行时应用账号不得获得 DDL 权限。

## 隔离测试门禁

数据库集成测试只有在显式设置 `TEST_DATABASE_URL` 时运行。破坏性操作前必须同时通过五层门禁：

- URL 必须使用 `postgresql+psycopg`，host 必须是 `localhost` 或 `127.0.0.1`；
- 数据库名必须匹配 `^finaudit_[a-z0-9_]+_test$`；
- URL 不得包含 query 参数；`host`、`hostaddr`、`dbname`、`service` 等 libpq 参数可能覆盖实际连接目标，因此全部 fail-closed；
- 进程变量 `FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS` 必须精确等于 `RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE`；
- 目标数据库注释必须精确等于 `finaudit:disposable-migration-test`。

测试会对目标数据库执行 `downgrade base`，因此只能指向可丢弃的本机测试库，绝不能指向开发共享库、预发布库或生产库。数据库管理员需先对专用测试库建立可丢弃标记（数据库名按实际专用测试库替换）：

```sql
COMMENT ON DATABASE finaudit_base005_test IS 'finaudit:disposable-migration-test';
```

安全注入测试 DSN 和上述显式确认变量后，再执行：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest .\tests\integration\database -q
```

本次 009 PostgreSQL 16 Gate 验证内容包括：

1. `base → head` 后 revision 等于当前唯一 Alembic head，服务端 major 精确为 16 且编码为 UTF8。
2. `pgcrypto`、`btree_gist`、`citext` 均存在，当前 BASE-005 表集合精确为十八张。
3. 固定角色精确为五条，十八张业务表均为空；审核规则、可靠性和特权授权 revision-owned 对象已安装。
4. 财务主数据三表、财务关系三表、Job/Step/Outbox 及 `break_glass_requests/user_roles` 的列、约束、索引、外键、触发器、并发/时间边界和安全降级路径符合当前已冻结合同。
5. `head → base` 后十八张业务表删除且共享扩展保留。
6. 再次 `base → head` 后表、角色和 revision 结果一致。

## 已验证基线

历史运行证据（2026-08-09）：已用 Python 3.10.20 和本机缓存的 `postgres:16-alpine`（PostgreSQL 16.14，`server_version_num=160014`）验证到当时的 head `20260807_007`。两轮均为 51/51 项数据库测试通过并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，覆盖三项扩展、精确十三表、五角色、空业务种子、既有审核/财务约束，以及 Job/Step/Outbox 的 catalog、ORM 对齐、状态/不可变触发器、Lease/CAS、并发/时钟边界、降级阻断和重建一致性；容器残留数为 0。该结果是 007/13 表历史证据，不能继承为当前 009/18 表 Gate。

当前运行证据（2026-08-11）：`scripts/verify-postgresql-current-head.ps1` exit 0；PostgreSQL 16.14、`server_version_num=160014`，唯一 head `20260807_009`；`backend/tests/integration/database` 共 71 项并连续两轮 71/71，输出 `POSTGRESQL_CURRENT_HEAD=PASS`。专用标签容器最终 0 残留，调用者原有 `TEST_DATABASE_URL` 与显式确认变量均恢复。该结果允许记录 `18/57 storage-schema runtime verified`；其中 CR-003-R3 仍只拥有 008 特权授权范围的 Gate，不得把 009 扩写为认证批准，也禁止表述为真实 ACL、业务 API/Worker、完整 `BASE-005/AUTH-005` 或 AC 通过。

首轮真实 PG16 失败暴露测试查询缺陷：PostgreSQL `information_schema.triggers` 不列出 `TRUNCATE` trigger，但 `pg_trigger` 中两个不可变触发器均存在。集成测试已改为查询 `pg_trigger/pg_class/pg_namespace` 并排除内部 trigger；历史 004 migration 字节与数据库 DDL 均无需修改。

2026-08-06 已实际验证：

- Python 3.10.20：Ruff、格式、严格 mypy、依赖一致性、全量 pytest 和 Alembic head 通过。
- PostgreSQL 16.14：隔离空库往返迁移通过，三个扩展和 head revision 正确。
- 哨兵密码未出现在成功迁移输出或不可达数据库失败输出。
- 两个一次性验证容器均在测试后删除。

当前 PG16 证据证明迁移基础设施与 009 的 18/57 storage-schema catalog/行为/往返范围；历史 007/13 与 008/15 证据仍保留用于旧 head 追溯。它不证明其余 39 表、Handler Registry、Input/Summary Schema Bundle、Repository/Service/API/Dispatcher/Worker、Redis/Broker、真实 ACL/数据、bootstrap、Compose、最小权限生产迁移或完整 `BASE-005/006/AUTH-005`。Provider、浏览器、部署、production 与所有 AC 仍未获授权或未运行。

## 后续实施边界

- 按依赖分批补齐其余 39 表，不增加第 58 张“种子版本”表；Alembic revision 本身作为种子版本。
- 不创建默认组织、管理员或密码，不写入真实规则或组织级分块配置。
- `CR-003-R3` 已 9/9 批准并完成 Gate A/B/C 与十一文件同步；`20260807_008/down=20260807_007` 的 `user_roles/break_glass_requests` 两空表已通过 PostgreSQL 16.14 两轮 71/71 storage-schema Gate。Repository/Service/API/Worker runtime、真实 ACL/数据、Provider、浏览器、部署、production 与 AC 均未授权、未运行或未实现。
- `20260807_009/down=20260807_008` 已按 Request 的既有表合同交付 `supplementary_agreements/invoice_items/contract_invoices` 三张空表及 ORM，并通过 PostgreSQL 16.14 两轮 71/71 current-head Gate。该切片不包含 `supplementary_agreement_changes`、Repository/Service/API/Worker、供应商运行时或任何 AC。
- Job/Step/Outbox 的 retry/lease、串行 Step、sequence、CAS 与降级边界来自已批准并完成 11 文件原子同步的 `CR-004-R2` effective contract；其有限授权的 `20260807_007` 空表 DDL/ORM 与专项 Gate 已交付。该批准不授权 Handler Registry、Input/Summary Schema Bundle、Repository/Dispatcher/Worker、Redis/Broker 或任何生产运行时。
- 文档纠错、资源安全重评和 Markdown NULL 唯一性记录在未批准的 `CR-005-R1`；不得先建缺少跨表约束的文档迁移。
- 操作日志分区、受控 definer、封账水位、稳定清单和备份恢复记录在未批准的 `CR-006-R1`；草案提议新增第 58 张 `operation_log_chain_state` 且依赖 CR-004 Outbox、CR-008 动作注册表和 DEP-005，当前 57 表基线不变。
- `CR-008-R1` 只有经机械核对的候选动作集合，没有最终 emission 合同或 JCS/hash；不得据此生成数据库 wrapper allowlist 或 `operation_logs` 迁移。
- 文件/知识库生命周期记录在未批准的 `CR-007-R1`；其 Job 子合同仍依赖 CR-004，Scanner evidence/trigger 还依赖未批准的 `CR-010-R1` 精确 Registry Profile，批准前不得创建 `files/knowledge_bases` 迁移。
- 分块配置状态、I1+row_version、JCS/hash 和归档入口记录在未批准的 `CR-009-R1`；批准前不得创建 `chunking_configs` 迁移、触发器或默认配置。
- `AiCallEventV1`/Sink 的精确事件合同来自 R3 immutable base，并已由 `CR-011-R4` 批准、同步及通过 contract/offline Gate B；`CR-011-R5/R6` 对该事件与持久化语义 delta 为零。R6 只收窄 startup evidence-boundary，Gate C 仍未运行；这些批准与离线证据均不授权或证明 `ai_call_logs`/Outbox 持久投影、DB/Worker runtime、Provider 网络、真实数据、部署和 production。
- `CR-012-R3` 已批准并原子同步九份 Request，`contracts/invoices/suppliers` 三表 migration/ORM 已由 006 实现并完成本地/合成 PostgreSQL 16 验证。R3 不授权 API 错误/读写投影或 SUPP-003/CON-005 运行时；GAP-064 继续阻断合同/供应商业务 API、确认/复用、纠错与 AI generic tax 投影。
- `CR-015-R2` 只推荐 GAP-064 的运行时/API/纠错投影，固定 `alembic_migration_delta=0`。CR-012 当前批准和九份 Request post-state 可验证，但 CR-015-R2 §7.1 还要求当前 checkout 不具备的九份 pre identity 与可比较 `approved_at < synced_at` 时间证据，因此 R2 本身并非可签执行包。权威历史证据若可恢复，successor 必须原样验证；若不可恢复则不得追认或伪造历史事实，successor 必须明确用当前 post-state 加新的前向 baseline attestation 替代旧 §7.1 前置并重新审批/同步。不得借它增加 migration 或扩展 006；`supplier_field` 只能在未来创建 `user_corrections` 的获批 migration 中进入枚举，而不是为尚不存在的表单独建 migration。
- 不用 `stamp head`、占位字段、Redis 或日志文本冒充持久化合同。
- BASE-006 已实现与数据库无关的严格消息包络与七队列 Celery 路由，并完成离线单元测试；Job/Step/Outbox 空表 DDL/ORM 已落地，但 Handler Registry、Input/Summary Schema Bundle、Repository/Dispatcher/Worker、Redis/Broker、真实 Task 和恢复集成仍未授权、未实现，因此 BASE-006 保持 `PARTIAL`。
