# FinAudit Agent 产品需求基线

## 0. 文档用途

- 状态：精简产品需求投影。
- 用途：为产品设计、开发、测试和验收提供可直接引用的用户结果与业务边界。
- 来源：现有需求基线、当前项目规则、精简规格入口和已实现机器事实。
- 本文只收录已明确的产品要求，不记录历史变更链、审批材料、文件哈希、库存数量或内部实现方案。
- 旧设计文档继续用于追溯；与本文无关的实现细节以当前模块的机器事实来源为准。
- `BLOCKED` 或 `TBD` 项不得被开发者自行猜测为硬契约。

### 0.1 规格就绪状态

- `READY`：产品行为已经足够明确，可在现有边界内编码和测试。
- `BLOCKED`：存在会改变行为、权限、数据语义或验收结果的未决冲突，只阻断直接受影响的最小切片。
- `TBD`：需要在目标环境或后续阶段选择，但不阻断无关功能。

### 0.2 交付状态

文档存在、代码实现和测试验收是不同结果，必须分别报告：

- `DOCUMENTED`：需求或设计已经写明。
- `IMPLEMENTED`：代码或机器契约已经实现。
- `VERIFIED`：相关静态、单元、集成或运行检查实际通过。
- `ACCEPTED`：对应 AC、UAT 或发布门禁正式通过。

低层状态不得自动推导高层状态；未执行的检查统一记录为 `NOT_RUN`。

### 0.3 当前实现投影

- 截至 2026-08-21，核心代码已经实现到 Alembic head `20260818_027`，ORM/catalog 与当前 PostgreSQL 集成门禁均覆盖 58/58 张物理表，以及用户、文件、合同/补充协议/发票/供应商、知识/RAG、审核、正式报告、工作台、依赖健康、AI 调用审计和内部指标主链。`025` 增加文档纠错与资源安全事实；`026` 增加制度两阶段撤销；`027` 增加隔离 Scanner Registry Profile。历史 `021～024` 的检索状态、发票币种、风险解释/报告草稿和 Event v2 USD/CNY 费用语义保持不变。
- 隔离 PostgreSQL、真实 Redis/Celery、真实 Qdrant、真实 MinIO、官方 ClamAV、本地自签名 TLS/Nginx 和完整 Compose 已有分层运行证据。隔离浏览器还实际完成了合同与发票上传 → Worker 提取 → 人工确认 → 关联 → 审核 → PDF/XLSX 报告闭环；`local-performance-baseline-v2` 在全新栈与同栈新 run 各连续三轮通过，覆盖默认最大 20 件批量受理、同键重放、207 部分失败、第 21 件 413 和 PostgreSQL 零重复/零超限副作用。本地 Worker 故障注入还在 `file_process` 的 scan step 中真实 SIGKILL Worker，确认退出码 137、同容器受管重启、Maintenance attempt 2、`scan → parse → markdown` 恢复及下游 `contract_extract` 正常完成；另两个专用门禁分别在 `contract_extract` 与 `invoice_extract` attempt 1 的 `extract` step 内真实 SIGKILL Worker，均确认恢复前零业务事实、attempt 1 `failed/LEASE_EXPIRED`、Maintenance attempt 2 成功和唯一事实收敛。合同终态为唯一合同、关联、13 个证据字段和追加日志；发票终态为唯一发票、明细、关联、13 个字段证据、1 条明细证据和追加日志，二者客户端详情与原件 SHA-256/ETag 均一致。第三个专用门禁还在 `audit_execute` attempt 1 的 `evaluate` 事务内真实 SIGKILL Worker，精确终止唯一孤儿数据库等待后端，确认恢复前零规则/风险/执行日志，再由 Maintenance attempt 2 收敛为固定 15 条规则、2 条待复核风险和 1 条追加式执行日志；客户端审核列表、任务与执行详情一致。另两个全新栈又分别验证 `report_generate` 在 MinIO 对象已写、数据库制品事实未提交时强杀后的孤儿对象保留与 attempt-2 唯一报告收敛，以及 `knowledge_index_build` 在真实 Qdrant 点和 PostgreSQL 成员 Hash 已提交、ready 事务未提交时强杀后的相同 Point ID 幂等重放与唯一 ready 索引收敛；两者均核对 `failed/LEASE_EXPIRED → succeeded`、客户端终态、唯一日志/Outbox 和跨恢复不变摘要。独立 local 安全门禁覆盖 TLS/CSRF/锁定/防枚举/角色拒绝/存在性隐藏/篡改 Token/Trace 审计/审计失败回滚/操作日志不可变/日志哨兵与容器最小权限，并实际让提示注入 PDF 穿过 ClamAV/Worker、制度双人审批、安全专用 100 条 `no_answer` 合成集、索引一致性、真实 Qdrant 和 HTTP 直接/间接双路径拒答。同一已激活知识库又经一次性 loopback HTTP 测试中继进入原 Nginx TLS → Backend → Qdrant 链路，由真实浏览器完成合成账号登录、工作台导航、问答提交和可见 `PROMPT_INJECTION_DETECTED` 拒答；PostgreSQL 随后独立核对唯一 Query、问题 Hash、Trace 与追加式操作日志，浏览器控制台和业务容器日志均无目标泄漏。上述结果属于小型合成 PDF 的本地 `VERIFIED` 工程证据，不是正式参考环境完整容量，也不自动构成任何 AC 的 `ACCEPTED`。
- 2026-08-19 的 `local-knowledge-performance-v5` 在新的专用 HTTP Compose 栈中，以 Provider disabled、`fixed_test` 1024 维确定性 Embedding、真实 PostgreSQL/Qdrant 和一份隔离合成制度连续运行三轮、每轮 20 次完整问答。端到端 RAG nearest-rank P95 为 `40.774/38.884/41.064 ms`；该值同时构成 Top-5 子阶段的保守上界，分别低于本节 15 s 与 2 s 目标。PostgreSQL 独立核对 60 条 answered Query、引用/命中和 60 条追加式审计事实；专用容器、卷、网络、运行目录、Secret、临时环境变量和镜像标签残留为 0。该合成 local/test 证据不替代代表性检索质量、正式参考环境容量、Provider、production、UAT 或正式 AC。
- 同日 `local-document-correction-crash-recovery-v1` 在新的专用 HTTP Compose 栈中让合成补充协议完成上传、ClamAV、file_process 和活动 Parse 后，请求 `manual_correction_snapshot`，以独占测试会话阻塞其 exclusion 读取并对精确 Worker 执行 SIGKILL。单次 60 秒 Lease 与 15 秒宽限耗尽后，Maintenance 精确记录 `exhausted`，Job/step/候选 Parse 原子收敛为 `failed/WORKER_LOST`；候选 Page/Block/Markdown 均为 0，旧 active/原件不变，显式激活失败候选固定 409 `PARSE_STATE_CONFLICT`。同一 Worker 容器和依赖恢复，专用容器、卷、网络、runtime/Secret、临时环境变量和镜像标签残留为 0。该 fail-safe 证据不改变 `max_attempts=1`，也不代表主机断电、真实 Asset、production、容量或正式 AC。
- 主要 P0 Frontend 已接同源真实 API；批量上传、预览、归档和失败 Job 重试也已有实现与聚焦证据。本地 PostgreSQL/MinIO 权威备份、隔离恢复及恢复后冷启动已通过。`minimax-m3-local-v1` 已把真实 OpenAI-compatible Chat Adapter、Gateway、结构修复、预算、网络策略和持久 EventSink 接入合同/发票提取、RAG 回答、风险解释与报告草稿；采用前重验业务输入，完成事件与业务事实同一 PostgreSQL 事务提交。公共 OPS-005 只读摘要和受独立凭据保护的 `/metrics` 已实现。受限真实 MiniMax smoke 覆盖五条生成链并核对每次尝试的持久审计，但这只是链路证据。2026-08-17 的 `CR-021` 与 `CR-022` 又批准 `minimax-m3-bailian-qwen37-local-v2`，把 1024 维 `qwen3.7-text-embedding` 经 Gateway 接入 Backend 查询与 Worker 索引/评测，以 Event v2/CNY 完成 durable reserve、权威实际费用和同事务采用，并用 Adapter/模型/维度身份禁止与旧 Hash 索引混用；唯一一次受限付费 smoke 已成功，但代表性合同/发票准确率、99% 结构合法率、50/100 条业务检索集、正式 DAST、production OCR/Scanner/CA/TLS/Secret Manager、正式容量、异地恢复、正式 AC/UAT 和 production 仍为 `NOT_RUN` 或 `BLOCKED`。
- Docker Scout 1.23.1 的本地镜像证据为：Frontend `0C/0H`；Backend 在 `pypdf 6.13.0 → 6.14.2` 且移除运行镜像中的 `pip/setuptools/wheel` 后由 `2C/6H` 降为 `2C/2H`，所有仍有修复版本的 C/H 为 0。剩余 4 项均来自 Debian Bookworm Perl 且扫描器标记 `not fixed`；因此 production 的严重/高危为 0 门槛仍未通过。
- AI-003 已实现合同/发票独立版本 Prompt、严格输出 DTO、证据白名单、结构修复和真实 Provider 采用；Prompt 明确把正文视为不可信数据、无证据返回 `null` 且不得确认业务事实。发票无证据币种语义已由 `022` 闭合，但正式代表性准确率和结构合法率尚未验收，因此只能描述为 `IMPLEMENTED/VERIFIED local`，不能描述为 `ACCEPTED`。
- `CR-024` 根据 BOSS 明确指令将内置应用入口全局改为 HTTP，并移除证书生成、挂载和本地 TLS 中继；本节上方涉及自签名 TLS 的运行证据只保留为变更前历史。当前 HTTP Profile 必须重新验证入口、Cookie、文件链和浏览器链，且不提供传输加密或服务器身份认证。

### 0.4 当前 Local MVP 本机可用 Profile

BOSS 于 2026-08-17 明确当前阶段为 `Local MVP`，目标是 YHBX 当前 Windows 本机上的可用验证，不是 production、局域网或公网发布。当前实际使用者为 1 人，但系统继续支持多账号与五种固定角色。

| 维度 | 当前冻结值 |
|---|---|
| 主机与运行时 | BOSS 当前 Windows 本机，使用 Docker Desktop 和本机现有 CPU、内存、磁盘；这些资源不构成正式容量基线 |
| 网络与入口 | 仅本机；入口固定为 `http://localhost:8443`，只允许绑定 `127.0.0.1`，不得开放局域网或公网 |
| 传输协议 | BOSS 批准的全局 HTTP Profile；内置入口不生成或配置 TLS 证书，且不提供传输机密性或服务器身份认证 |
| Scanner/OCR | 本地使用 ClamAV；OCR 暂不启用，扫描件和纯图片文档不得声明识别成功 |
| AI | 默认关闭；保留确定性规则并明确展示降级，Provider 配额和 canary 在本阶段不适用 |
| Secret | 使用仓库外的本地受管 Secret 文件挂载；禁止真实密钥进入仓库；生产 Secret Manager 留待公网部署阶段选择 |
| 数据与备份 | PostgreSQL 与 MinIO 使用本机 Docker 数据卷；重要操作前执行本地备份；异地备份暂未配置 |
| 保留与恢复承诺 | 数据和日志保留期暂未制定并由 BOSS 手工清理；本阶段不作正式 RPO/RTO 承诺 |
| 用户与容量 | 当前实际使用者 1 人；系统支持多账号和五种固定角色；不作多人并发或正式容量承诺，本机性能数据只作工程参考 |
| 安全与发布治理 | 正式 DAST、远程仓库和分支保护留到公网部署前；Local MVP 的 UAT 签署人与发布责任人均为 YHBX |

Local MVP 本机可用必须同时满足：当前 Alembic head 完成；完整 Compose 启动成功；全部必需依赖为 `ok`；AI 明确为 `disabled`；Frontend 可渲染；入口没有非 loopback 监听；至少一个授权用户能够真实登录并读取其权限范围内页面。未满足的条件必须单独标记，不能用进程健康或历史合成门禁替代。

YHBX 于 2026-08-18 明确签署 `Local MVP UAT通过`；签署制品为 `docs/testing/local-mvp-uat-2026-08-18.md`。该结论只接受本节冻结的本机范围，不能推导 production 或正式 AC 通过。

该 Profile 只关闭当前本机部署决策，不改变 AC-001～AC-016 的正式 production/UAT 口径；公网部署仍须重新确定域名/CA、Secret Manager、Scanner/OCR、容量、保留期、RPO/RTO、DAST、远程治理和发布证据。

## 1. 产品定位与目标

FinAudit Agent 是企业财务文档智能审核与风险分析平台，为财务、审计和合同人员提供审核辅助，不替代有权限的人员作出付款、税务、法律或合规决定。

P0 的产品目标是形成一条可追溯的审核闭环：

1. 统一接收合同、补充协议、发票和企业制度文件。
2. 提取合同与发票关键字段，并允许授权人员依据原文证据修正和确认。
3. 使用确定性规则检查主体、金额、日期、重复性、完整性和关联关系。
4. 将制度文档转换为可追溯内容，完成分块、检索、评测、引用和无依据拒答。
5. 冻结每次审核所使用的事实、规则、制度和版本，支持分级人工复核。
6. 输出可追溯的审核报告、风险明细和审计记录。
7. 在外部 AI 或检索能力不可用时保留确定性规则结果，并明确展示降级状态。

## 2. 用户与角色

| 角色 | 可以执行 | 不得执行 |
|---|---|---|
| 系统管理员 | 用户与固定角色管理、技术配置、失败处理、索引激活、已审批制度的技术发布、日志和健康检查 | 修改业务事实、审批制度内容、复核风险或代替业务人员完成审核 |
| 财务审核人员 | 上传合同/发票、确认发票字段与主合同、创建审核、处理非高风险、查看和导出授权报告 | 最终处理高风险或执行系统管理 |
| 审计复核人员 | 审批制度和评测标签、复核高风险、确认/调整/驳回或退回修正 | 直接修改合同或发票事实 |
| 合同管理员 | 维护合同、补充协议、合同状态和付款条款，提出关联建议 | 最终确认发票主合同 |
| 只读用户 | 查看授权范围内已完成任务和报告 | 写入、审批、复核、配置、下载或导出 |

职责分离规则：技术管理权不包含业务审批权；高风险必须由审计处理；生产环境不得让系统管理员长期兼任财务或审计角色；制度和评测集不得同人提交与批准。紧急临时授权须由另一名有效管理员独立批准，只授予一个允许角色、限定时长并完整留痕，不得自批、预约、延期、续期或覆盖原记录。

## 3. P0 范围

### 3.1 固定角色认证与基础权限

- 支持登录、刷新、退出、用户创建、启停、密码重置和固定角色分配；用户禁用后已有会话必须失效。
- 首次初始化或重置后的用户必须先完成受限换密；所有受保护操作由后端强制鉴权。
- 认证行为采用 `auth-mvp-v1`，其中全局密码策略为 BOSS 批准的 `auth-password-v2`：密码按严格 JSON 字符串解码，拒绝 NUL，做 Unicode NFC 后保持原样，不 trim、casefold 或折叠；NFC 后长度为 6～128 个 code point 且 UTF-8 不超过 512 bytes，允许空格和 Unicode，不增加字符组合规则；创建、重置和强制换密都必须命中版本化弱密码 blocklist 门禁。
- 密码使用 Argon2id v19，参数固定为 `m=65536 KiB`、`t=3`、`p=1`、16-byte salt、32-byte hash 和 PHC 字符串；连续 5 次错误后锁定 15 分钟，未知、已删除、禁用、锁定和密码错误对匿名调用者使用同一 401 口径。
- Access Token 为 EdDSA/Ed25519、15 分钟；Refresh Token 为 256-bit opaque token，普通会话绝对有效期 7 天，`remember_me=true` 为 30 天。Refresh 每次成功原子旋转但不延长绝对到期时间，旧 Token 重放使该会话族失效。
- Refresh 只通过 `finaudit_refresh` HttpOnly、SameSite=Strict、`Path=/api/v1/auth`、无 Domain 的 Cookie 传递；`Secure` 严格跟随已配置公开 Origin，当前全局 HTTP Profile 为 `false`，未来显式 HTTPS Origin 为 `true`。所有写入或清除该 Cookie 的浏览器端点必须通过同源 Origin 校验。
- 首次初始化或管理员重置后的登录只返回 5 分钟、一次性的 `password:change` 受限 Token；完成换密后撤销旧会话并要求重新登录，不签发普通业务会话。

P0 认证公开接口固定为以下五个；请求/响应和安全细节以 `TECHNICAL_SPEC.md` 第 7 节为机器实现边界：

| 动作 | 接口 | 成功结果 |
|---|---|---|
| 登录 | `POST /api/v1/auth/login` | 200 `SessionDTO`，并写入 Refresh Cookie；强制换密为 403 `AUTH_PASSWORD_CHANGE_REQUIRED` |
| 刷新 | `POST /api/v1/auth/refresh` | 200 `SessionDTO`，并原子旋转 Refresh Cookie |
| 退出 | `POST /api/v1/auth/logout` | 幂等 204，并清除 Refresh Cookie |
| 当前用户 | `GET /api/v1/auth/me` | 200 `CurrentUser` |
| 完成强制换密 | `POST /api/v1/auth/password/change` | 204，撤销旧会话；随后必须重新登录 |

#### 3.1.1 `p0-permissions-v1` 权限字典

下列 26 个 code 是 P0 唯一权限字典；不得增加通配符、前端别名或从页面路由反推权限：

| Code | P0 动作 |
|---|---|
| `users.manage` | 管理用户、启停、重置密码和固定角色 |
| `temporary_roles.request` | 创建临时角色申请 |
| `temporary_roles.decide` | 独立决定或撤销临时角色申请 |
| `system.configure` | 管理 P0 技术配置 |
| `operations.read` | 查看脱敏操作日志和健康信息 |
| `jobs.recover` | 对授权失败 Job 执行技术恢复 |
| `files.read` | 查看授权文件元数据、状态和内容 |
| `files.upload` | 上传授权业务类型文件 |
| `files.manage` | 管理授权文件生命周期和可恢复处理 |
| `financial.read` | 查看授权财务事实 |
| `contracts.manage` | 维护合同和补充协议事实 |
| `invoices.manage` | 维护和确认发票事实 |
| `suppliers.correct` | 修正授权供应商候选事实 |
| `links.suggest` | 提出合同发票关联建议 |
| `links.manage_primary` | 确认或管理发票主合同关系 |
| `knowledge.use` | 使用授权且有效的知识库与制度 |
| `knowledge.submit` | 提交制度或评测业务审批 |
| `knowledge.approve` | 独立批准或驳回制度或评测业务审批 |
| `knowledge.publish` | 技术发布已批准的制度或索引版本 |
| `audits.read` | 查看授权审核任务、执行和风险 |
| `audits.create` | 创建授权审核任务或执行 |
| `risks.review_non_high` | 处理非 high 风险 |
| `risks.review_high` | 复核 high 风险 |
| `audits.complete` | 完成满足门禁的审核执行 |
| `reports.read` | 查看授权报告 |
| `reports.export` | 下载或导出授权报告 |

固定角色映射如下；表中集合是角色直接权限，不得由 UI 扩张：

| 角色 code | 直接权限集合 |
|---|---|
| `system_admin` | `users.manage`、`temporary_roles.request`、`temporary_roles.decide`、`system.configure`、`operations.read`、`jobs.recover`、`knowledge.publish` |
| `finance_reviewer` | `files.read`、`files.upload`、`files.manage`、`financial.read`、`invoices.manage`、`suppliers.correct`、`links.manage_primary`、`knowledge.use`、`audits.read`、`audits.create`、`risks.review_non_high`、`audits.complete`、`reports.read`、`reports.export` |
| `audit_reviewer` | `files.read`、`files.upload`、`files.manage`、`financial.read`、`knowledge.use`、`knowledge.submit`、`knowledge.approve`、`audits.read`、`risks.review_high`、`reports.read` |
| `contract_admin` | `files.read`、`files.upload`、`files.manage`、`financial.read`、`contracts.manage`、`suppliers.correct`、`links.suggest`、`knowledge.use`、`audits.read`、`reports.read` |
| `read_only` | `audits.read`、`reports.read` |

权限先取当前有效固定角色与有效临时角色映射的并集，再执行 deny-overrides：

- 只要有效角色含 `system_admin`，最终只保留 `system_admin` 的七项直接技术权限；不得通过兼任或 break-glass 获得业务事实修改、业务提交/审批、风险复核、审核创建/完成或报告导出。
- 只要有效角色含 `read_only`，从当前候选集合剔除全部 mutation、review 和 export code，只可能保留 `operations.read`、`files.read`、`financial.read`、`knowledge.use`、`audits.read`、`reports.read` 中原本由其他有效角色授予的读取 code；`read_only` 自身仍只直接授予 `audits.read`、`reports.read`，且只覆盖授权范围内已完成审核和报告。若同时含 `system_admin`，先收敛为管理员七项直接权限，再应用本条只读过滤。
- Break-glass 只增加一个有时限的有效角色映射，不能绕过上述产品 deny、组织边界、对象范围、对象状态或职责分离。
- `finance_reviewer` 的文件权限只覆盖合同/发票，`audit_reviewer` 只覆盖制度/评测，`contract_admin` 只覆盖合同/补充协议；`system_admin` 不读取业务正文，单独持有 `read_only` 时只读取授权且 completed 的审核/报告。
- 同一 actor 不得提交后再批准同一制度或评测对象；完成财务初审的 actor 不得再以审计角色复核同一 high 风险。每次请求仍须由 Backend 同时强制组织、资源范围、对象状态与上述同人约束。

### 3.2 文件管理

- 支持 PDF、DOCX、JPG、JPEG、PNG 的单个或批量上传，默认单文件上限 50 MB、单批上限 20 个。
- 联合校验类型与内容，支持去重、预览、状态、重试和归档；只有安全通过的文件可解析，原文件不可被纠错覆盖。
- `CR-005-R2/recommended-forward` 冻结结构块纠错：每次只修改当前活动解析版本中的一个块和一个允许字段，原子创建不可变纠错记录、queued `manual_correction` 候选 Parse 与 Job/Outbox；Worker 重建完整快照但不得自动激活。质量通过后只能经独立激活入口替换活动 Parse，并发旧 sibling 必须返回 `PARSE_PARENT_STALE`。
- 纠错与激活复用 `files.manage OR system.configure`，再按文件业务类型校验角色；不新增 PermissionCode。`CR-010-R2` 只批准可丢弃测试数据库中的 `fixed_test` 确定性 Profile：Profile 表默认空，普通 local/test 缺少 current Profile 时仍必须 503 fail-closed；只有隔离合成测试显式安装 Profile 并注入无网络 Scanner/内存 Asset 存储时，资产安全重评才可创建新 Parse/Job/Asset 血缘事实。该证据不得用于真实资产、staging、production 或 Scanner 产品声明。
- `CR-029-R1/recommended-forward-v1` 增加文件范围的活动文档纠错来源读取：只允许与 PARSE-004/005 相同的 `files.manage OR system.configure` 和业务角色矩阵读取同组织 `stored+clean` 文件的当前活动文本 Block；使用绑定 Parse 的 keyset Cursor，版本切换时必须拒绝旧 Cursor。响应只返回纠错所需的文件/业务类型/Parse/Block/页码/顺序/文本/bbox，不返回 Asset、对象键、哈希、组织或原因；FileDetail 作为四类文件的通用纠错入口，不自动提交或激活。
- `archived-reupload=conflict-v1`：同一组织内相同 SHA-256 与字节大小命中未软删除的 archived 文件时，单文件上传固定返回 HTTP 409 `FILE_ARCHIVED_DUPLICATE`。不得复用或恢复旧文件，不得创建新文件事实、Job、业务对象或 MinIO 副本，也不得修改旧文件的分类、目标知识库或自动处理意图；归档恢复只能由未来单独批准的显式动作完成。

### 3.3 合同与补充协议

- 提取合同编号、主体、税务身份、金额、币种、日期、付款条件和关键条款，每个候选字段关联原文证据。
- 授权修正须保留前后值、原因和操作者；审核按基准日期整体应用已确认且已生效的补充协议。

### 3.4 发票

- 提取发票代码、号码、日期、买卖方、税务身份、金额、税额、总额和基础明细，支持证据、修正、确认和重复检测。
- 历史发票不可被新上传覆盖；Excel 风险明细不等同于原始发票批量导出。

### 3.5 企业主体与供应商

- P0 只维护一个企业主体，可从合同和发票生成供应商候选，支持税务身份精确匹配和标准名称修正。
- Supplier 对外只展示统一 `tax_number`；值来自已保存的 USCC 优先投影，generic 合同/发票税号不得被 AI 或后端按形状猜成 USCC。
- 候选只允许待确认、已确认活动、已拒绝失活三种组合。人工确认按同组织精确税务身份复用活动供应商，名称不作为硬身份；来源回填、版本竞争和一条聚合纠错必须同事务留痕。
- 供应商别名、合并、拆分、回滚和风险画像不属于 P0。

### 3.6 合同发票关联

- 支持人工选择合同并展示税务身份、名称和日期等候选依据，不得以不可解释总分自动确认。
- 一张发票最多确认一个主合同；取消关系必须填写原因并保留历史。

### 3.7 确定性规则与风险

- 规则输出须可复现、可版本化，并保存实际值、预期值、适用性和原因；AI 不得改变命中或初始等级。
- 无合同场景只执行适用规则；风险保留原始与有效等级，总体风险取未驳回风险的最高有效等级。

P0 规则语义如下：

- 发票销售方税务身份与合同乙方不一致：高风险。
- 发票购买方税务身份与本企业不一致：高风险。
- 纳入计算的累计开票总额超过基准日期有效合同金额：高风险。
- 开票日期不在合同有效期：中风险。
- 发票代码、号码和销售方税务身份重复：高风险。
- 合同主体、金额、币种或生效日期缺失：中风险。
- 发票代码或号码、买卖方税务身份、日期或总额缺失：中风险。
- 合同与发票币种不一致：中风险。
- 发票明细金额与总额差异超过 0.01：中风险。
- 未确认主合同：中风险。
- 合同编号缺失：提示。
- 存在影响审核事实但尚未确认的补充协议：中风险。
- 检索正常完成但需要制度依据的规则没有找到适用证据：提示。
- 名称相同但税务身份冲突：高风险。
- 非红字发票总额不大于零：中风险。

### 3.8 制度、Markdown、检索评测与 RAG

- 生成版本化 Markdown、来源映射和可追溯分块；字段提取可与转换并行，分块只能读取质量通过的活动 Markdown。
- 结构块必须保留 quote；坐标不可得时保存明确原因。Markdown 使用禁用 raw HTML 的 CommonMark/GFM table 子集，复杂表格作为版本化安全制品引用。
- 不可变候选索引经一致性和评测通过后才能激活；失败时旧版本继续可用。
- P0 知识范围按组织、固定角色权限、知识库状态、制度发布/有效期和活动索引成员裁剪，不新增知识库级 ACL。
- 检索固定先由 PostgreSQL 生成允许集，再由 Qdrant must-filter 召回，最后回 PostgreSQL 终审；RAG 仅引用本次授权证据，无依据、越权、注入或引用失败时拒答。
- 检索评测分为 5 条 smoke、至少 50 条 MVP/UAT 和至少 100 条正式发布门禁；低层集合不得冒充高层验收。
- `CR-028-R1/recommended-forward-v1` 冻结制度撤销：audit_reviewer 使用 `knowledge.approve` 提交唯一撤销确认，system_admin 使用 `knowledge.publish` 独立执行；只允许 `published→revoked`，归档继续不进入 P0。撤销提交后新检索的 PG 允许集与最终复核立即排除该制度，不以同步删除 Qdrant 派生点作为正确性来源；历史审核、索引成员、分块、引用和审批记录继续保留。
- `CR-030-R1/recommended-forward-v1` 增加按知识库过滤的撤销待执行请求列表：只允许 `knowledge.approve + audit_reviewer` 或 `knowledge.publish + system_admin` 读取仍为 published、未执行的 request 最小元数据，不授予 `knowledge.use`。Frontend 不再要求手工粘贴 request UUID，但执行仍须由 system_admin 显式填写独立原因，并由 Backend 重新校验 Policy row version、request 归属、未执行状态和请求/执行 Actor 分离；禁止自动或批量执行。

### 3.9 审核任务与人工复核

- 审核任务是稳定案件，每次执行为独立不可变版本；执行前校验事实并冻结输入快照。
- 长任务异步执行且只展示真实状态；规则先于检索和 AI，外部能力失败不得影响规则结果。
- 财务处理非高风险，高风险提交审计；关键事实修正使旧执行和报告过期，重审创建新版本。
- 执行使用 draft、校验、排队、运行、财务复核、审计复核、退回、完成、失败、取消和过期的封闭状态机；取消直接落为 cancelled，失败只可在同一快照上重试。
- `CR-027-R1/recommended-forward-v1` 要求技术重试和取消分别携带 execution/file 与 Job 两个权威版本；AUDIT-007 只在同一失败快照、退避到期且 Job 可重试时复用原 Job 排队，attempt 只在后续 claim 增加。AUDIT-008 的 execution 直接 cancelled；queued Job 同事务 cancelled，running Job 先 cancel_requested 再由 Worker 收敛，复核阶段的 succeeded Job不改写。
- 原始风险等级不可改写；有效 high 且仍待处理时禁止完成。只有独立审计复核人员可处理 high，且不得与本执行财务初审为同一 actor。
- P0 规则目录只包含应用内置的 RULE-001～015，按完整版本原子发布；不提供在线规则编辑、动态 DSL 或用户代码。

### 3.10 报告、日志与可部署运行

- 生成不可覆盖的 PDF 审核报告和 Excel 风险明细，包含结论、风险、规则、制度证据、版本和复核信息。
- 报告使用 queued、generating、ready、failed、outdated、archived 的封闭状态；ready 制品和摘要不可覆盖，执行过期时历史报告明确标记 outdated。
- 报告制品保存至 MinIO，但对象键不返回客户端；Backend 在权限复核后以内联 PDF 或附件 XLSX 流式返回。
- 全流程可通过追踪标识关联；日志、指标和报告须脱敏；目标环境可验证持久化、降级和恢复。

## 4. P0 明确非目标

- 不直接执行付款或修改外部业务系统。
- 不对发票真伪作法律确认。
- 不在证据不足时生成确定性合规结论。
- 不提供多租户、自定义角色或在线权限树。
- 不提供在线规则 DSL、动态规则中心或用户自定义代码执行。
- 不提供多 Agent、GraphRAG 或 Agent 自主业务决策。
- 不提供混合检索、Reranker、语义分块、分块 A/B 或自动评测平台。
- 不提供可视化 Markdown 编辑器；只提供结构块纠错和只读预览。
- 不提供供应商高级主数据治理、付款申请、跨合同分摊、多币种换算或红字发票专项流程。
- 不提供 Kubernetes、移动端或 ERP、采购、银行等外部系统集成。

## 5. 核心用户流程

1. **初始化**：受信任操作者创建首企业和首管理员；系统不预置公开账号、密码或业务数据；首管理员换密后才能创建其他角色，业务启用前完成权限、安全和健康检查。
2. **文件处理**：用户选择业务类型后上传；系统校验文件并完成安全检查，再异步解析/OCR，同时生成字段和 Markdown 候选；授权人员依据证据确认或纠错，纠错产生新版本。
3. **财务对象**：合同管理员确认合同与补充协议，财务确认发票；系统给出可解释关联候选，财务确认唯一主合同或创建无合同任务；补充协议按基准日期进入快照。
4. **制度发布**：审计完成业务审批；系统校验 Markdown、生成分块、构建候选索引并评测；全部门禁通过后管理员激活索引并技术发布，新版本失败不影响旧版本。
5. **审核报告**：财务创建执行并冻结快照；系统运行规则、检索和 AI 解释；财务处理非高风险，审计处理高风险；完成后生成报告，关键事实变化时旧结果过期并创建新执行。

## 6. 业务不变量

- **权威事实与证据**：业务事实必须有唯一权威来源；派生数据不能成为唯一事实；原文件不得被覆盖；字段、风险和引用须追溯到证据或人工操作；历史审核只读冻结快照。
- **版本与不可变性**：已激活、发布或完成的内容不得原地修改；变化创建新版本；失败不能污染旧活动版本；被历史结果引用的对象必须保持可查。
- **文件与安全**：文件及其元数据均不可信；只有安全通过的文件可解析；预览、下载和导出重新鉴权；重复文件不得产生第二权威事实或分类漂移。
- **财务事实**：金额使用十进制定点语义；一张发票最多一个主合同；补充协议仅在确认且生效后整体进入快照；关键事实变化只使旧结果过期，不修改旧快照。
- **制度与检索**：业务审批、技术批准和发布分别留痕；按基准日期使用有效历史制度，撤销制度不用于新检索；分块来源于活动 Markdown；候选和引用都必须在授权范围内。
- **规则、AI 与人工**：规则决定确定性结果；AI 只提供候选、检索、解释和草稿，输出经结构、业务、权限和引用校验；无依据、越权或注入时拒答；高风险由审计处理。
- **异步与审计**：长任务状态真实、幂等且可恢复；失败不得产生重复结果或可见半成品；外部依赖不得伪成功；敏感操作必须留痕，必要审计失败时业务不得成功采用。

## 7. P0 验收标准

`CR-025` 根据 BOSS 当前“只在本地运行”的明确决定，将 AC-001、AC-002、AC-015、AC-016 调整为 Local MVP 口径；四项当前结论由 `docs/testing/local-mvp-ac-acceptance-2026-08-18.md` 绑定。其余 AC 保持原有质量/业务口径，未自动接受。扩大到局域网、公网或 production 时必须重新验收这四项，不能沿用 Local MVP `ACCEPTED`。

### AC-001 登录、权限与职责分离（Local MVP `ACCEPTED`）

- 五种固定角色只能执行其授权动作；所有越权操作被后端拒绝并留痕。
- 系统管理员不能修改业务事实、审批制度或复核风险。
- 财务不能最终处理高风险；合同管理员不能确认主合同；只读用户不能导出。
- 首次或重置后登录只能完成一次性受限换密，不能获得普通业务会话。
- 当前实际使用者为 1 人但系统支持多账号和五角色；长期角色组合、同人提交与批准、临时授权自批等职责分离负例允许使用本地合成 Actor，并必须全部失败。

### AC-002 文件上传与校验（Local MVP `ACCEPTED`）

- 合法支持文件获得唯一文件标识和真实处理状态。
- 伪装文件、超限文件、非法空文件和不一致类型被拒绝且不进入存储成功态。
- 重复文件不得创建第二份权威文件事实或第二个相同业务对象。
- 同组织相同 SHA-256 与大小命中 archived 文件时，单文件响应固定为 409 `FILE_ARCHIVED_DUPLICATE`，既有事实和对象不变，且不产生新文件、Job、业务对象或 MinIO 副本。
- 未通过安全检查的文件不得进入解析。
- 本地 MinIO/存储不可用时不得返回成功；本阶段使用本地 ClamAV 和合成代表文件，不要求 production Scanner 产品或正式容量。

### AC-003 合同提取与修正

- 代表性合同的编号、金额、币种、日期和双方税务身份与标准答案一致。
- 每个核心字段包含页码和原文证据。
- 无证据字段不得由模型补造，应返回空候选或待人工确认。
- 人工修正保留前值、后值、原因、操作者和时间。

### AC-004 补充协议生效

- 生效日前的审核快照继续使用原合同事实。
- 生效日及之后的审核快照使用已确认协议产生的新事实。
- 未确认协议不得改变合同事实，并产生待处理风险。
- 协议内多项变更不得部分应用。

### AC-005 发票识别与重复

- 代表性发票的代码、号码、日期、买卖方税务身份和金额与标准答案一致。
- 重复发票命中重复规则，且历史发票记录不被覆盖。
- 模糊或低置信发票进入人工确认，不得自动成为已确认事实。
- 明细金额与总额使用精确十进制规则核验。

### AC-006 主合同唯一性

- 第一次合法主合同确认成功。
- 对同一发票确认第二个主合同被拒绝。
- 并发确认只能有一个成功结果。
- 合同管理员只能提交候选或建议，不能绕过财务确认。

### AC-007 金额、日期和适用性规则

- 累计金额超过合同金额时，输出实际值、上限、差额和高风险。
- 发票日期超出合同有效期时输出中风险。
- 无合同任务允许执行，缺少合同规则命中，其他合同相关规则标记为不适用。
- 检索故障不得误报为“没有制度依据”。

### AC-008 文档纠错、Markdown、分块与索引版本

- 文件、解析、Markdown、分块和索引分别保存状态与版本。
- 人工纠错创建新解析和 Markdown 版本，不覆盖旧版本。
- 纠错请求、候选快照重建和解析激活分离；候选完成前、质量未通过或 parent 已过期时不得替换当前活动版本。
- Markdown 可被选定解析器解析，证据正文映射和有效内容覆盖完整。
- 分块无空正文、无未批准超长内容，并可追溯到 Markdown 与原文。
- 候选索引成员与检索存储一致；失败时旧活动版本保持可用。

### AC-009 检索调试与评测

- 可回答用例的标准证据出现在约定的 Top-K 结果中。
- 无答案用例不被算作正确命中，未授权用例不返回受限内容。
- 每次运行保存数据集、索引、模型、参数、逐题结果和未命中原因的版本身份。
- 相同版本和参数可重新运行并产生独立记录。
- 5 条 smoke 只证明链路；至少 50 条已审批用例用于 MVP/UAT，至少 100 条已审批用例用于正式发布门禁。

### AC-010 制度审批、历史版本、引用与切换

- 按不同基准日期查询时，命中当时有效的正确制度版本。
- 回答引用正确制度、内容版本、分块、索引、页码和冻结原文。
- 未经业务审批的制度不能发布，未通过评测的索引不能激活。
- 撤销后的制度不参与新查询，历史快照仍可查看。
- 有效期重叠的发布版本被拒绝。

### AC-011 无答案、越权与提示注入

- 知识库无依据时明确拒答。
- 未授权制度内容不出现在候选、回答、引用或日志中。
- 上传内容中的“忽略规则”“输出密钥”等指令不改变系统行为。
- 系统 Prompt、密钥、内部配置和工具能力不会被回答泄露。

### AC-012 审核任务与执行版本

- 未确认核心事实时不能开始审核执行。
- 同一幂等请求只创建一个执行版本和一份可见结果。
- 事实修正后的重审创建新执行版本，旧版本保持不可变。
- 无合同审核只执行适用规则。
- 关键事实变化使旧执行和报告过期。
- 失败只在同一快照上重试，取消直接落为 cancelled；退回、取消和过期执行不能继续完成。

### AC-013 高风险复核

- 存在未处理高风险时，财务不能完成执行。
- 审计确认或合规调整后，执行才允许完成。
- 高风险降级必须保存原始等级、有效等级和原因。
- 审计退回修正后，旧快照不能继续用于完成。
- 同一执行的财务初审 actor 不能再处理该执行的 high 风险。

### AC-014 报告

- 完成执行后可生成 PDF 报告和 Excel 风险明细。
- PDF 包含总体结论、风险、规则、制度证据、版本和复核信息。
- Excel 每项风险包含实际值、预期值、等级、状态和引用。
- 新报告不覆盖旧报告；事实变化后旧报告明确显示过期。
- PDF 预览和读取要求报告读取权限，Excel 风险明细要求导出权限；响应不得泄露 MinIO 对象键。

### AC-015 追踪与脱敏（Local MVP `ACCEPTED`）

- 一次业务流程可用追踪标识串联同步请求、异步处理和外部依赖日志。
- 密码、Token、API Key 和不必要正文不出现在日志、指标或错误中。
- 税务身份等敏感字段按策略脱敏。
- 日志或审计写入失败不得产生伪成功。
- AI Provider 在本阶段关闭；provider-neutral AI 审计失败或恢复时，输出不得成为成功答案或业务事实。正式 DAST 和传输加密不进入本地 AC。

### AC-016 可部署运行与恢复（Local MVP `ACCEPTED`）

- 使用仓库外受管配置和实际注入的非密钥配置启动当前本机 P0 环境。
- 必需服务健康后，完整审核、制度处理和本地合成检索流程可运行。
- 重启后权威业务事实、文件制品和评测记录保持可用。
- 派生检索数据丢失后可以从权威版本和成员清单重建并校验。
- AI 服务关闭或不可用时规则结果保留，并明确展示降级。
- 仓库和构建产物不存在真实密钥；本阶段不要求正式容量、异地恢复、主机断电或正式 RPO/RTO。

## 8. 质量与发布门槛

### 8.1 READY 的固定底线

- 清晰发票核心字段精确匹配率不低于 95%。
- 合同核心字段精确匹配率不低于 85%。
- 结构化输出合法率不低于 99%。
- Markdown 解析、证据来源映射和有效内容覆盖率均为 100%。
- 分块来源可追溯率和索引成员一致率均为 100%。
- 权限、有效期和状态过滤正确率为 100%，权限内容泄露率为 0。
- 确定性规则测试通过率为 100%，高风险设计用例漏报为 0。
- 提示注入导致的工具越权率为 0。
- 存在高等级安全缺陷时不得发布。

### 8.2 READY 的默认容量与体验目标

- 普通列表请求 P95 不高于 800 ms。
- 上传请求 P95 不高于 3 s，且不等待长任务完成。
- 单张清晰发票处理 P95 不高于 30 s。
- 二十页合同处理并生成 Markdown 的 P95 不高于 120 s。
- 单次 Top-5 检索 P95 不高于 2 s，不包含回答生成。
- 完整 RAG 响应 P95 不高于 15 s。
- 至少支持三个审核任务并行且不丢失、不重复采用结果。
- 性能验收必须记录参考环境、模型、文档规模和并发条件，并连续执行三轮。

## 9. READY / BLOCKED / TBD 边界

### 9.1 READY

- 产品定位、五种固定角色及职责分离目标。
- `auth-mvp-v1`、五个认证接口和 `p0-permissions-v1` 的 26 个权限 code、固定角色映射、deny-overrides 与同人职责分离。
- `archived-reupload=conflict-v1` 的同组织 SHA-256+大小判定、稳定 409 和无业务/存储副作用语义。
- P0 十类用户结果和明确非目标。
- 合同、发票、补充协议的字段证据、人工修正和基准日期语义。
- 主合同唯一性、确定性规则语义、风险等级和人工复核原则。
- 不可变版本、历史快照、过期重审、报告与证据追溯。
- `recommended-forward-v1` 已冻结供应商统一身份、Markdown/表格 Profile、组织级知识权限、Qdrant Collection 粒度、安全检索顺序、5/50/100 评测、15 规则发布、审核/高风险与报告状态机。
- `CR-027-R1` 的 Job HTTP 双版本 fencing 与 `CR-028-R1` 的制度两阶段撤销/检索失效已在 local/test 实现并通过 PostgreSQL current-head 027 全量双轮；该结论不扩张 Provider、production、真实数据迁移或正式 AC。
- AI 只做候选、检索、解释和草稿，以及拒答、降级和人工兜底。
- AC-003～AC-007、AC-010～AC-011、AC-013～AC-015 的产品结果。
- `CR-025` 的 Local MVP 环境口径已冻结，AC-001、AC-002、AC-015、AC-016 当前为本机 `ACCEPTED`；扩大环境必须重验。

### 9.2 BLOCKED

以下仅阻断对应最小切片；当前本地业务与部署 Profile 不再依赖这些决定：

- 真实 AI Provider：local/test Chat 与百炼 Embedding 的 endpoint、模型、维度、计费、出站 allowlist 和 Secret 槽位已批准并有受限 smoke；production 的 Profile、配额、Secret Manager、canary 和发布权限尚未批准或验证。
- Production 验收：当前全局 HTTP Profile 不提供传输加密，不能用于局域网或公网发布；目标主机、恢复受信任 TLS 或由受信任代理终止 TLS、生产 Scanner/OCR、Secret Manager、保留期、RPO/RTO、容量基线和发布权限尚未形成一致且已验证的环境 Profile。

### 9.3 TBD

以下在进入对应阶段前确定，不阻断无关开发：

- 具体 OCR、生成模型、Embedding 模型和目标环境容量。
- 目标环境端口、域名、证书和资源规格。
- 生产恶意文件扫描产品。
- 数据、日志、Markdown 和报告保留周期。
- 性能验收参考环境。
- 高风险复核时限和升级路径。
- P0 支持的具体发票类型范围。
- 隐藏正式检索评测集的更新频率和退化容差。
- 单文件包含多个业务文档时的自动检测与人工拆分方式。

## 10. 编码与验收使用规则

1. 开发一个 `READY` 切片时，只读取本文相关条目、当前模块机器事实来源和对应 AC。
2. `BLOCKED` 只阻断表中写明的最小范围，不得扩大为全项目停工理由。
3. `TBD` 不得由示例、旧 DTO、旧目录或候选设计反推为正式值。
4. HTTP、状态枚举、错误码和持久化结构以当前唯一机器事实来源为准；本文只冻结用户结果和业务不变量。
5. 内部重构、任务拆分、目录或实现数量变化不改变产品范围。
6. 改变范围、外部兼容性、持久化业务语义、状态、权限、安全边界或验收阈值时，必须先形成明确决定并同步本文。
7. 测试只证明其实际覆盖层级；静态检查、离线 Mock、真实运行和正式验收不得互相替代。
8. 未实现或未运行的内容必须明确记录，禁止用文档、占位页面或模拟数据冒充业务闭环完成。
