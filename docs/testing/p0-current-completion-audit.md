# P0 当前完成度审计

状态：当前检出事实快照
更新日期：2026-08-18
矩阵工作包范围：86 项（`2 implemented / 84 partial / 0 accepted`）
Local MVP AC 级状态：`AC-001/002/015/016 ACCEPTED`

## 1. 结论

当前 84 个 `partial` 不是 84 个都缺代码。矩阵把“生产代码是否存在”“本地是否运行通过”“对应 AC 是否正式签署”压在同一个状态中，因此大量任务虽已达到 `TEST_PASS` 或隔离环境 `RUNTIME_PASS`，仍必须保持 `partial`。

YHBX 已选择 CR-025 Local MVP 发布收口；应用决定、回滚依据和排除项见 `docs/releases/local-mvp-0.1.0-2026-08-18.md`。该 `GO` 只适用于本机 Profile，不改变本审计的 86 行工作包状态或 production 结论。

2026-08-18，BOSS 明确把当前验收环境收窄为本机 Local MVP；`CR-025` 因此重新定义 AC-001、AC-002、AC-015、AC-016 的本地完成口径。当前 HTTP 安全基线/浏览器终审、文件链、备份/隔离恢复/冷启动和 YHBX UAT 已完成，四项 AC 级结论均为 `ACCEPTED`；86 行矩阵仍表示跨 AC 的工作包状态，不能把其 `partial` 与 AC 级结论混为一谈。

本轮在当前检出中补齐了此前明确缺失的 Redis 跨进程 AI 运行门禁、`CR-022 / option-A / event-policy-v2 / USD-CNY-only / no-fx`，以及补充协议拒绝、旧版本 409 和五角色登录的隔离浏览器证据。三类独立限流池、并发租约、RPM/TPM token bucket、按模型目标隔离的滚动窗口熔断、单 half-open 探针、Redis server time、Lua 原子状态转换和 Redis 不可用时 fail-closed 已接到 Chat/Embedding。调用顺序为“纯预算/期限预检 → Redis 许可 → durable Event v2 reserve → 最终期限检查 → 单次 Provider 请求 → Redis 完成 → durable complete/业务采用”；限流或熔断拒绝不会写 `started`，Provider 成功但 Redis 完成失败时结果不可采用。

Event v1 的 bytes/hash 与 legacy USD 回放保持兼容；Event/Policy v2、迁移 `20260817_024`、ORM、Repository 和 OPS-005 已支持 USD/CNY 通用整数 microunit，禁止 FX 和跨币种汇总。Chat 固定 USD，百炼 Embedding 固定 CNY，completion 必须与 Query、索引批次或评测事实同一 PostgreSQL 事务采用。首次获授权的连通性 smoke 已成功：2 个 1024 维向量、43 input tokens、Event v2 `succeeded`、CNY 22 microunits，未输出密钥、输入或向量。

BOSS 随后单独批准同范围完整知识库 E2E，并保持 20 请求、50000 input tokens、CNY 1 元、no-fx、local/test、no-production 的硬上限。一次性运行实际完成知识库构建 → Worker 索引 → Qdrant materialize/green → Top-5 检索 → 5 条 smoke 评测：7 次 Provider 请求、3231 个权威 input tokens、CNY 1616 microunits，15 个索引成员、1024 维、Top-5 返回 5 条、5/5 smoke 通过，并投影 7 个 completed attempt / 14 个 Event v2 事件。`formal_release` 的 100 条门禁按设计拒绝激活，索引保持 `ready`；临时 Collection、PostgreSQL 和 Qdrant 容器均已删除。

这些实现把“Redis 跨进程限流/熔断”“真实百炼知识库 E2E”和“CNY 持久费用审计”从本地代码缺口改为已验证能力，但不改变代表性质量、生产环境或正式 AC 的状态。没有经审批的业务代表性数据、目标环境和验收签署时，不能把矩阵行改成 `accepted`。

BOSS 后续把合成资产的 local/test 技术语义复核委托给 Agent。可追溯复核完成原 18 条队列（12 条原样接受、6 条修订后接受），并重写复核全部 20 条合理 `no_answer`；100/50 技术集可在可丢弃环境创建为 approved，但明确 `human_review_claimed=false`，不等于业务代表性、人类 UAT 或正式 AC。获批的单次真实 50+100 运行完成 36 条款处理、两批索引和 `ready` 状态后，在 50 条 `mvp_uat` 门禁返回 `MVP-UAT-050_EVALUATION_FAILED` 并立即停止；100 条 `formal_release` 与激活均未运行，临时 Collection 和容器已清理。失败前精确请求、Token、费用和标签级指标没有留存，只能证明不超过 52 请求、50000 input tokens 和 CNY 1 元，不能补造实际值。

2026-08-18 的 `CR-026` 另行批准 local/test 批量复核并把硬上限调整为 100 请求、50000 input tokens、CNY 10、零重试。Provider 前离线与 PostgreSQL 双轮门禁通过；真实运行随后以 5 次请求、4971 input tokens、CNY 0.002486 完成 50 条，49/50 通过且授权泄露为 0。唯一失败为 10 个 no-answer 用例中的 1 个假阳性，`no_answer_false_positive_rate=0.1`；runner 立即停止，100 条与激活未运行。Event v2 completion 已随索引/评测事实事务采用，但成功后置 `ai_call_logs` 投影核对因质量失败未运行；Collection、专用容器和确认环境变量残留为 0。

BOSS 随后再次授予同一边界的单次诊断权限。第二次运行完全复现 5 次请求、4971 input tokens、CNY 0.002486、49/50、授权泄露 0 和 1 个 no-answer 假阳性；100 条仍未运行。安全输出捕获 runtime case UUID `7623955c-d413-44be-ab26-82ab25e24301`，但该 ID 由可丢弃数据库生成，当次未保留到冻结 source case ID 的映射，清理后不能反查具体问题。Runner 已离线加固未来稳定 ID 映射，但第二次授权已消耗且未第三次调用。

DOC-002 的损坏文档边界随后完成真实修复：此前 DOCX 会接受伪造非 `w:document` 根节点，也未拒绝重复 `word/document.xml`，现已要求唯一、未加密、受支持压缩、受限大小/压缩率、精确解压长度、规范根节点和有效 XML。生成语料覆盖截断、缺主部件、坏 XML、假根、重复主部件、加密、未知压缩和压缩率上限，并直接消费目录中的损坏/加密 PDF；PDF MediaBox 另要求有限正值，提取文本必须无 NUL 且可严格 UTF-8 编码。`local-performance-baseline-v3` 又在专用 local Compose 三轮通过 20 页合成文本合同的 HTTP→ClamAV→file_process→active Parse/Markdown，耗时 `892.206/573.639/567.867 ms`，数据库逐轮确认 20 Page、3 个成功 Step、published Outbox 和无 blocking issue 的 active Markdown。代表性多格式/复杂合同、production OCR、正式容量和 AC-003/008 仍未运行。

DOC-003 随后修复 OCR Port 输出采用边界：此前 NaN confidence、零尺寸、空身份/行、负值或越界 bbox 可进入解析候选；现在图像与扫描 PDF 共用入口统一要求有限置信度、正尺寸、严格身份/行/bbox、page-text 一致性及无 NUL strict UTF-8，并以 `OCR_OUTPUT_INVALID` 非重试失败。解析器 28 项、相邻 OCR/解析/格式 79 项及 PostgreSQL File 15 项通过；真实 File Job 还固定无 bbox 文本块必须写 `extractor_not_available`。production OCR Profile、实际 Tesseract/Poppler Provider、代表性准确率/容量和正式 AC-003/008 仍未运行。

DOC-008 的来源映射证据加固继续有效；CR-005-R2 exact snapshot `c4794409…72f65` 保持不变，CR-010-R2 fixed-test snapshot 为 `8721eb27…9b9171`。025/027、三个既有 API、manual 与 asset-security Handler/Worker、幂等、Job/Parse 可延迟一致性、完整快照、Asset 新对象键/直接血缘和独立激活均已实现。隔离 PostgreSQL 16.14 `File` 范围 16 项及 current-head Full 153 项连续两轮通过；Profile 表默认空时 PARSE-006 仍 503 且零事实，只有可丢弃测试数据库显式安装 fixed_test Profile并注入无网络 Scanner/内存存储时运行。该证据不证明真实 MinIO Asset copy、真实 Scanner/Definition、production 或正式 AC。

CON-002/003 的当前事实也已重新核对：补充协议字段变更载体、完整替换、确认/拒绝、纠错与操作日志、基准日有效字段和逐字段来源均已存在，旧矩阵中“载体不存在/写链未实现”的 009 checkpoint 已删除。当前合同聚焦单元 140 项通过，PostgreSQL 16.14 current-head 完整目录 149 项连续两轮通过；既有隔离浏览器还覆盖 13 个有效字段、替换/确认/拒绝和旧版本 409。两行仍保持 `partial`，因为经审批代表性合同准确率、production、正式业务 UAT 与 AC-003/004 未运行。

INV-003/LINK-001 随后完成同类漂移核对：发票证据/历史、完整事实替换、确认/拒绝、重复候选/点查/重检/人工决定，以及合同候选解释、建议、主关系确认/替换/取消和双向读取均已接真实 API、事务与 Frontend。`local-performance-baseline-v4` 又在三轮真实 local 链从合成 DOCX 上传到 invoice_extract 候选 API 可读分别用时 `635.969/603.018/605.273 ms`，数据库逐轮确认 13 字段证据、1 明细、文件业务绑定和双 Job/Outbox；Full PostgreSQL 153×2 继续覆盖写链与关联并发。两行仍保持 `partial`，因为经审批清晰发票 95% 准确率、代表性业务 UAT、production 和正式容量/AC-005～007 未运行。

INV-004 的历史 76/17 skipped 与 91×2 checkpoint 也已删除。当前精确候选/两票点查、重复重检和人工决定覆盖组织/状态/三元组、CAS/幂等、候选重锁、纠错/日志及审核过期传播；候选页改为单个 `duplicate_source` CTE + LEFT JOIN statement，编译 SQL与真实 PostgreSQL statement 计数均为 1，Full 154×2 通过。`local-invoice-duplicate-browser-v1` 又以真实浏览器完成 login→列表→源详情→候选→显式 pair，对比 DOM 可见 source/candidate/共同身份，写动作 disabled、console 0，受保护 completion 精确接受两个 200 GET。代表性重复质量、跨页冻结 snapshot、capacity、production、正式可访问性与 AC-005 仍未运行。

AUD-005 的 API/数据库证据也已从当前 checkout 重新确认：风险汇总、非高/高风险分权复核、confirmed/dismissed/adjusted 持久化、财务/审计复核门禁、退回、取消、过期与重审均已接真实事务、纠错/操作日志及 Frontend。风险/审核/报告聚焦单元 125 项、PostgreSQL `Audit` 范围 4 项和 Frontend 页面门禁通过；同一 current-head 完整目录仍为 149×2。该行继续保持 `partial`，因为代表性风险质量、production、正式安全验收与 AC-007/010/012 未运行。

KB-004 的旧全量 `NOT_RUN` 结论随后被当前事实替换：固定分块 Profile 的版本/JCS Hash、组织级 advisory-lock 配置持久化、不可变 ChunkSet 绑定、制度批准触发分块、Auth/API、Worker、索引、评测与下游 Qdrant 链均已存在。分块/制度/知识 API 聚焦 Backend 31 项、PostgreSQL `Retrieval` 范围 8 项和 Frontend knowledge 6 项通过；同一 current-head 完整目录仍为 149×2。该行继续保持 `partial`，因为可配置多 Profile、代表性复杂文档质量、production、容量与正式 AC-008 未运行。

KB-003 的撤销/归档差异经 SSOT 核对后改为合同阻塞：当前只冻结制度创建、提交、独立批准和发布；产品要求撤销后不参与新检索，但尚无撤销/归档 URL、权限、允许起始状态、索引失效传播、幂等、历史可见性和响应合同，不能由 Frontend 单独补按钮。REP-003 则确认数据库/MinIO/API/Auth/browser 旧边界已被当前实现取代：报告聚焦 Backend 96 项、Frontend 6 项通过，PostgreSQL `Audit` 4 项与完整目录 149×2 已覆盖持久化读取链；PDF/XLSX 仍保持此前兼容性证据。REP-003 继续 `partial`，因为 LibreOffice Calc、代表性业务 UAT、production 与正式 AC-014/非本地 AC-015 未运行。

Chrome `151.0.7922.138` 已在可丢弃报告门禁中完成真实原生登录 Tab 顺序、Enter 提交、authenticated shell/dashboard Tab 顺序和 skip-link 聚焦 `MAIN#main-content`，console warning/error 为 0。Edge 已安装，但浏览器连接与 Windows 控制分别因不可用连接和 URL 安全策略未形成证据；屏幕阅读器及全 P0 路由矩阵仍未运行。LibreOffice `26.2.5.2` 已安装，但 Calc 对项目 XLSX 和最小单单元格 XLSX 的 headless 打开/转换均超过 180 秒未完成；Windows GUI 直接启动也没有暴露可见或可控窗口，未进入打开文件步骤，因此不能标记兼容性通过。

## 2. 86 项逐模块核对

| 模块 | 覆盖任务 | 当前检出已完成的最强证据 | 仍不能关闭的边界 |
|---|---|---|---|
| BASE | `BASE-001`, `BASE-002`, `BASE-003`, `BASE-004`, `BASE-005`, `BASE-006` | 本地 Git/基线门禁、生产路由配置、统一 UI 基础、严格 Settings/Policy、57/57 PostgreSQL 表和真实 Job/Outbox/Celery/恢复均有 `TEST_PASS` 或隔离 `RUNTIME_PASS` | 远程分支保护、生产 Policy/部署、生产 Secret/ACL 和正式 AC 未运行 |
| AUTH | `AUTH-001`, `AUTH-002`, `AUTH-003`, `AUTH-004`, `AUTH-005` | 登录/刷新/退出/换密、五角色与 deny-overrides、用户创建/启停/重置/角色替换、Break-glass、操作日志和 first-org/admin bootstrap 已接真实 PostgreSQL/API/Frontend，本地浏览器认证闭环通过 | 生产域名/CA/Secret Manager、生产审计保留和 AC-001 签署未运行 |
| FILE | `FILE-001`, `FILE-002`, `FILE-003`, `FILE-004`, `FILE-005` | 单件/批量上传、格式与 Magic Bytes、MinIO、ClamAV、幂等/去重、预览/归档/失败 Job 重试、Worker 强杀恢复和本地 TLS 文件链已运行 | 生产 Scanner/OCR、恶意与多格式代表性语料、正式容量和 AC-002 未运行 |
| DOC | `DOC-001`, `DOC-002`, `DOC-003`, `DOC-004`, `DOC-005`, `DOC-006`, `DOC-007`, `DOC-008` | 版本化页/块/资产、PDF/DOCX/OCR Adapter、损坏/加密 PDF 和八类畸形 DOCX fail-closed、OCR 输出边界、Markdown/source map/table asset、结构分块、不可变纠错/激活、质量门禁与 Worker 恢复已接 PostgreSQL/Job；本机三轮 20 页合成合同 full-processing 与 active Markdown 通过；纠错 Job 真实 SIGKILL 后按单次 Lease 原子失败且旧 active/原件保持 | production OCR Profile/Provider、代表性多格式/复杂合同、正式 20 页容量、真实 Asset MinIO copy、主机断电和 AC-003/008 未运行或阻塞 |
| CON | `CON-001`, `CON-002`, `CON-003`, `CON-004`, `CON-005` | 13 字段提取、人工修正/确认、补充协议字段载体与整组变更、确认/拒绝、纠错/日志、基准日有效字段、并发旧版本 409、五角色登录、供应商双来源解析和隔离浏览器写闭环已通过；当前聚焦单元 140 项和 PostgreSQL 149×2 通过 | 经审批代表性合同集的 85% 指标、production、正式业务 UAT 与 AC-003/004/007 未运行 |
| INV | `INV-001`, `INV-002`, `INV-003`, `INV-004` | 13 字段和明细提取、证据/历史、修正/确认/重复处置、纠错/日志及审核过期传播已接真实数据库/API/Frontend；本机三轮合成清晰发票 full-processing 通过；精确候选 single-statement snapshot 与真实浏览器候选/pair 对比均通过 | 经审批清晰发票集的 95% 指标、代表性重复质量、跨页冻结 snapshot、业务 UAT、production、正式可访问性与 AC-005/007 未运行 |
| LINK | `LINK-001`, `LINK-002`, `LINK-003` | 候选解释、建议、主合同确认/替换/取消、唯一主关系、历史与双向读取已接 Repository/Service/API/Frontend，并进入本地审核报告闭环；PostgreSQL 149×2 覆盖写链和并发收敛 | 代表性业务 UAT、production、容量和 AC-006/007 未运行 |
| KB | `KB-001`, `KB-002`, `KB-003`, `KB-004`, `KB-005`, `KB-006`, `KB-007`, `KB-008`, `KB-009`, `KB-010`, `KB-011`, `KB-012` | 固定分块 Profile/Hash、组织级配置和不可变 ChunkSet、制度创建/提交/双人审批/发布/两阶段撤销、索引构建/激活/重建、PG 允许集→Qdrant must-filter→PG 终审、评测、RAG/引用/拒答/反馈已运行；受限真实百炼 E2E 覆盖 Worker、15 个向量、Top-5 与 5/5 smoke；六领域 100/50 技术集完成 owner-delegated 非人类复核，批量真实复核以 5 次请求完成 50 条并得到 49/50、授权泄露 0；`local-knowledge-performance-v5` 又以真实 Qdrant、fixed_test 1024 维和 60 次完整 HTTP QA 通过本机 Top-5 保守上界/RAG P95 门禁 | 1 个 no-answer 假阳性使 50 条门禁失败；制度归档不在 P0；可配置多 Profile、代表性复杂文档、业务审批、人类 UAT、100 条 `formal_release`、Provider、正式激活/容量和 AC-008～011 未通过或未运行 |
| AUD | `AUD-001`, `AUD-002`, `AUD-003`, `AUD-004`, `AUD-005`, `AUD-006`, `AUD-007`, `AUD-008` | 15 条规则目录、静态 implementation key/hash、原子发布、任务/执行/快照/风险、非高/high 分权复核、confirmed/dismissed/adjusted 持久化、财务/审计复核门禁、退回/取消/过期/重审、报告投影、AI 解释降级和强杀恢复已运行；规则/预览/快照聚焦回归、PostgreSQL Audit 4 与完整目录 153×2 通过 | 代表性质量、production 恢复/容量、正式安全验收和 AC-007/010/012/013 未运行 |
| AI | `AI-001`, `AI-002`, `AI-003`, `AI-004`, `AI-005` | MiniMax Chat 的网络策略、预算、持久审计、原子采用和五条业务链有受限真实证据；Event/Policy v2、USD/CNY/no-FX、百炼 Embedding 完整本地知识库链、真实 CNY 费用与 Redis 跨客户端门禁均已验证 | 正式质量集、production Secret/quota/canary 与正式 AC 未运行或未决 |
| REP | `REP-001`, `REP-002`, `REP-003` | 版本化报告、MinIO 双制品、鉴权与完整性复验读取、PDF 浏览器预览、XLSX 下载动作/审计、宿主/镜像一致性和 Microsoft Excel 只读打开已验证；Backend 96、Frontend 6、PostgreSQL Audit 4 与完整目录 153×2 通过 | 2026-08-19 的 in-app Browser 与 Chrome 均未暴露 Blob native-download event，LibreOffice Calc 对项目/最小 XLSX 均挂起；代表性业务 UAT、production、正式 AC-014 与非本地 AC-015 未通过或未运行 |
| FE | `FE-001`, `FE-002`, `FE-003`, `FE-004`, `FE-005`, `FE-006`, `FE-007`, `FE-008`, `FE-009` | P0 页面均接同源 API；五角色导航/禁止直达、桌面/窄屏、loading/empty/error、roving tabs、报告页 DOM 可访问性和多个隔离浏览器闭环已验证；Chrome 原生登录/工作台 Tab 与 skip-link 局部路径通过 | Edge、屏幕阅读器、全 P0 路由原生键盘矩阵、production 与正式可访问性验收未运行 |
| TEST | `TEST-001`, `TEST-002`, `TEST-003`, `TEST-004`, `TEST-005`, `TEST-006`, `TEST-007` | 离线质量门禁、API/数据库/Compose/浏览器、真实本地依赖、Chat smoke 与完整 Embedding 知识库 E2E、安全、性能计算器、备份恢复和七类故障恢复均有分层证据；100/50 技术集复核、失败即停和 Chrome 键盘证据已固化 | 50 条真实质量门禁失败；业务代表性数据、100 条正式评测、正式 DAST、参考硬件完整性能、production/UAT 和 AC 签署未通过或未运行 |
| DEP | `DEP-001`, `DEP-002`, `DEP-003`, `DEP-004`, `DEP-005`, `DEP-006` | 固定镜像 local Compose、loopback HTTP、依赖健康、Trace/日志、权威备份/隔离恢复和受保护 `/metrics` 已运行 | HTTP 无传输加密；生产 Secret Manager、采集告警/SLO、异地备份、主机断电、RPO/RTO 与发布签署未运行 |

## 3. AC 差异

下表保留用户给出的矩阵计数。一个任务可映射多个 AC，因此各行数量不能相加为 86。

| AC | 矩阵工作包状态 | 当前 Local MVP AC | 扩大环境或其他口径仍需 |
|---|---:|---|---|
| AC-001 | 1 implemented / 12 partial | `ACCEPTED`：Auth、五角色/SoD、换密、普通会话、用户管理与越权拒绝 | 多名真实人员的组织职责分离、非本机环境重验 |
| AC-002 | 0 / 12 | `ACCEPTED`：上传、ClamAV 扫描、预览、归档、重试、去重和失败边界 | 非本机 Scanner、正式容量与新环境重验 |
| AC-003 | 0 / 19 | 合同提取、修正、确认、证据和浏览器闭环 | 经审批合同集 85% 与正式运行 |
| AC-004 | 0 / 6 | 补充协议变更、确认/拒绝、并发旧版本 409、五角色登录和基准日投影 | 正式业务 UAT、production 与签署 |
| AC-005 | 0 / 13 | 发票提取、明细、修正、确认和重复处置 | 经审批发票集 95% 与正式运行 |
| AC-006 | 0 / 8 | 合同发票候选和主关系全状态链 | production/UAT 与签署 |
| AC-007 | 0 / 12 | 供应商复用、重复处置和审核消费 | 代表性业务 UAT 与签署 |
| AC-008 | 0 / 21 | 文档、Markdown、分块和真实 Worker/Qdrant 索引链 | 代表性复杂文档、生产 OCR 与质量门禁 |
| AC-009 | 0 / 13 | 知识库、索引版本、真实百炼构建、Top-5、5 条 smoke、owner-delegated 100/50 技术集和 36 条款真实索引；批量 50 条为 49/50、授权泄露 0 | 1 个 no-answer 假阳性使 50 条门禁失败；业务代表性审批、100 条 `formal_release`、激活和正式运行 |
| AC-010 | 0 / 14 | 制度审批、真实向量检索、RAG、安全拒答和三标签合成覆盖；50 条真实指标已精确留存 | `no_answer_false_positive_rate=0.1` 使门禁失败；业务代表性 50/100 条集与正式指标 |
| AC-011 | 0 / 13 | RAG 引用、拒答、反馈、安全边界和完整本地真实 Embedding 链；50 条授权泄露为 0 | 1 个 no-answer 假阳性、正式安全/业务验收未通过 |
| AC-012 | 0 / 16 | 审核任务、规则、恢复和工作台 | 正式容量、生产恢复和 UAT |
| AC-013 | 0 / 7 | high 风险权限/SoD/完成门禁 | 正式安全验收 |
| AC-014 | 0 / 10 | PDF/XLSX、预览/下载、Excel 兼容；LibreOffice 已安装 | LibreOffice Calc 运行挂起、production 与 UAT |
| AC-015 | 1 implemented / 22 partial | `ACCEPTED`：HTTP 安全基线、Trace、审计回滚、脱敏、Prompt Injection 与 AI 不可采用 | 传输加密、正式 DAST、非本机日志/监控重验 |
| AC-016 | 0 / 12 | `ACCEPTED`：HTTP Compose、冷启动、权威备份/隔离恢复、派生重建和 Job 恢复 | 多人并发容量、异地/断电、正式 RPO/RTO 与新环境发布 |

## 4. 当前不可由代码自行补齐的项目

以下项目需要新的授权、外部环境或业务签署；继续写代码不能构成其通过证据：

1. 正式 Embedding 质量与激活：owner-delegated 100/50 技术集已可追溯批准用于 local/test，但真实 50 条门禁失败，100 条 `formal_release` 与激活未运行；它也不是业务代表性或人类 UAT。付费单次授权已经消耗，任何后续 Provider 调用都需要新的明确运行授权。
2. 正式质量数据：合同 85%、发票 95%、结构合法率 99% 和检索正式质量都需要经审批、可追溯且具有业务代表性的输入；Agent 委托复核只能解除 local/test 技术数据审批，不能代签业务代表性或人类 UAT。
3. 正式安全与可访问性：Chrome 登录/工作台局部原生键盘路径已通过；仍需要目标环境 DAST、生产证书链、Edge、全 P0 路由键盘矩阵、屏幕阅读器和正式签署。
4. 正式性能与恢复：需要参考硬件、代表性文档/模型、生产 Scanner/OCR、主机断电、异地恢复以及 RPO/RTO 签署。
5. 生产与发布：需要真实域名/CA、Secret Manager、监控采集/告警/SLO、镜像风险处置、远程仓库治理和 UAT/发布责任人。当前仓库没有 remote/upstream，也没有 production 目标、凭据或可替代签署主体，不能由本地权限自行伪造。
6. 文档资源安全重评：CR-005-R2 文本闭环、CR-029-R1 四业务类型通用纠错来源读取和 CR-010-R2 的隔离 fixed_test Asset 重评均已实现；普通 local 仍 Profile-empty/503，默认 Worker 不注入 test double。manual snapshot 不得伪造或复用 Asset 对象，真实 MinIO Asset copy、真实 Scanner/Definition 和 production 仍未闭合。

## 5. 本轮新增验证

- 当前完整离线门禁：Backend `3121 passed / 147 skipped / 1 warning`，Ruff check/format 518 files、mypy 283 sources、pip check、Frontend typecheck、28 files/539 tests 与 151-module build 全部通过；新增 skip 是需显式真实 PostgreSQL 的 INV-004 单 statement 集成门禁。baseline、Git governance、分支保护 fixture 和测试资产正负门禁也在同一 wrapper 通过；Compose、浏览器、Provider、remote 和 production 在离线 wrapper 中仍按设计为 `NOT_RUN`，PostgreSQL Full 与四项 local 运行证据为独立显式门禁。
- Redis 控制器单元与调用链聚焦测试：`29 passed`。
- 隔离真实 Redis 7.4.9（锁定 digest）专项测试：`3 passed`，覆盖独立客户端共享并发门禁、RPM/TPM、滚动熔断、并发旧成功不得误关熔断、单 half-open 探针、探针租约 TTL 和恢复；当前 Redis/Celery wrapper 合计 `4 passed`。
- 临时 Redis 容器使用唯一名称/标签和 loopback 随机端口；测试后已停止并删除。
- PostgreSQL 16.14 current head `20260818_027` 的 File 16、Audit 4、Retrieval/Policy 10 均通过；完整 `integration/database` 目录现为 154 项，并在同一次 Full wrapper 中连续两轮通过，输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok`、`POSTGRESQL_CURRENT_HEAD_RUN=2/2 status=ok`、不可变镜像 ID `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` 与 `POSTGRESQL_CURRENT_HEAD=PASS`。新增项在真实 PostgreSQL 固定 INV-004 候选读取只执行一个 CTE/LEFT JOIN statement；此前失败尝试不作为通过证据。
- `local-performance-baseline-v4` 在独立 Compose 三轮保留既有 workload，并逐轮运行 20 页合成合同与字段完整合成发票；发票处理为 `635.969/603.018/605.273 ms`，确认 13 字段证据、1 明细、业务绑定和 file_process/invoice_extract 双 Job/Outbox；同轮合同为 `1165.315/830.661/576.725 ms` 并确认 20 Page active Parse/Markdown。证据绑定 v3/v4 资产，专用容器/卷/Secret/runtime/镜像标签残留 0；这不是代表性质量、OCR、production 或正式容量证据。
- `local-knowledge-performance-v5` 在新的专用 HTTP SecurityBaseline 栈中以 Provider disabled、`fixed_test` 1024 维、真实 PostgreSQL/Qdrant 连续三轮各执行 20 次完整 QA；nearest-rank RAG P95 为 `40.774/38.884/41.064 ms`，同一端到端值作为 Top-5 子阶段保守上界，分别低于 15 s 与 2 s。PostgreSQL 精确确认 60 条 answered Query、引用、1～5 命中和 60 条追加日志；`tests/evaluation/local-knowledge-performance-v5.json` 绑定当前 runner/wrapper，专用容器/卷/网络/runtime/Secret/环境变量/镜像标签残留均为 0。它不证明代表性检索质量、50/100 门禁、Provider、正式容量、production、UAT 或 AC。
- `local-document-correction-crash-recovery-v1` 在新的专用 HTTP Compose 栈中以合成补充协议完成 ClamAV/file_process/活动 Parse，再用独占 `document_content_exclusions` 锁阻塞 `manual_correction_snapshot` 并精确 SIGKILL Worker；退出码 137、事务零候选 Page/Block/Markdown、同容器恢复、Maintenance `exhausted`、Job/step/Parse `failed/WORKER_LOST`、旧 active/来源文本 Hash/原件 SHA 不变和失败候选激活 409 全部通过。机器证据绑定 runner/wrapper/Dockerfile，专用容器/卷/网络/runtime/Secret/环境变量/镜像标签残留 0。它保持 `max_attempts=1`，不证明代表性文档、真实 Asset、主机断电、production、容量或正式 AC。
- `local-invoice-duplicate-browser-v1` 在 disposable HTTP 应用中由 Codex in-app browser 使用合成 finance_reviewer 完成工作台、发票列表、源详情、精确候选和显式 pair 对比；source/candidate ID、共同身份与两行摘要可见，未填写原因时写按钮 disabled，console warning/error 为 0。受保护 manifest 记录候选 GET/pair GET 各 200 并重新核对只读事实，completion `accepted` 后 wrapper 输出 `INVOICE_DUPLICATE_BROWSER_GATE=PASS`。运行时 PostgreSQL cleanup 与 MinIO stop 通过、既有 MinIO volume 按策略保留；Docker daemon 重启后的归属复核确认容器/卷/网络、端口与 Browser Python 进程均为 0。
- 首次授权的受限付费百炼连通性 smoke：`PASS`；固定 2 条短合成文本、单次尝试、43 input tokens、2 个 1024 维向量、Event v2 `succeeded`、CNY 22 microunits。一次性数据库已删除，该次授权已消耗。
- 单独再次授权的完整百炼知识库 E2E：`PASS`；7 次 Provider 请求、3231 个权威 input tokens（运行前 UTF-8 上界 13905）、CNY 1616 microunits，15 个 1024 维索引成员，Worker `succeeded`，Qdrant collection 验证为 green，Top-5 返回 5 条，5/5 smoke 通过，7 个 completed attempt 投影 14 个 Event v2 事件。`formal_release` 激活按 100 条门禁拒绝，索引保持 `ready`；Collection 与两个专用容器均清理。
- `synthetic-non-acceptance-v1`：确定性生成 `120` 条候选，规范化问题去重为 `100` 条并固定 `50` 条子集；100 条为 `60/20/20`，50 条为 `30/10/10`，覆盖 answerable/no_answer/unauthorized 和 P-001-V2 四个锚点。来源、去重、覆盖、证据和非验收控制共 8 项通过；生成阶段 Provider 请求为 `0`，未访问数据库、未激活索引、未提交审批。当前实现下付费预估为复用索引 `50/100` 次请求，重建四条源分块 `51/101` 次，CNY 上界 `0.001760/0.003458`。
- `synthetic-policy-corpus-v1 / synthetic-benchmark-candidate-v1`：确定性生成报销、供应商、发票、合同、审批权限、审计留痕 6 个虚构制度族、12 个无重叠版本、36 条证据条款，以及每领域 20 条的 120 条候选；100 条提议集为 `60/20/20`，固定 50 条 `mvp_uat` 为 `30/10/10`。全部用例绑定基准日期、允许制度和预期或禁止证据；重复、有效期矛盾、证据、no_answer、权限、跨权限和自然度 8 项自动检查均为 0 异常。原 18 条复核队列随后由 BOSS 委托 Agent 在 local/test 完成：12 条原样接受、6 条修订接受，全部 20 条 no_answer 重写复核，待处理为 0；机器资产明确 `human_review_claimed=false`。
- 单次真实合成 Benchmark：第一次接线检查在 Provider 前因 scanner 选择错误失败，Provider/Token/费用均为 0，随后修复为仓库多格式 clean scanner。获批付费运行完成 36 条款处理、两批索引和 `ready`，在 50 条 `mvp_uat` 返回 `MVP-UAT-050_EVALUATION_FAILED` 后停止；100 条与激活 `NOT_RUN`，无重试，Collection/容器残留 0。精确 usage 未持久化，安全上界为不超过 52 请求、50000 tokens、CNY 1 元；runner 已补安全失败遥测但不能追溯补造本次数据。
- `CR-026` 批量真实复核：production 默认仍逐题，local/test runner 固定索引 2 批、50 条 3 批、100 条 5 批。Provider 前 Backend `3061 passed / 142 skipped`、PostgreSQL current-head 完整目录双轮 PASS；付费运行以 5 次请求、4971 input tokens、CNY 2486 microunits 得到 49/50、`authorization_leak_count=0` 和 `no_answer_false_positive_rate=0.1`，随后按失败即停未运行 100 条。Event v2 completion 已事务采用，`ai_call_logs` 后置投影核对为 `NOT_RUN`；精确聚合证据为 `tests/evaluation/synthetic-benchmark-runtime-evidence-v2.json`，专用资源与确认环境变量残留为 0。
- Chrome 本地键盘路径：真实原生 Tab 验证登录表单、Enter 登录、authenticated shell/dashboard 顺序与 skip-link 聚焦主内容，console warning/error 为 0；Edge、屏幕阅读器和全路由矩阵 `NOT_RUN`。
- LibreOffice：官方 `26.2.5.2` 已安装；Calc 对项目和最小 XLSX 的 headless 打开/转换均超过 180 秒未完成，故兼容性仍为 `NOT_RUN`，没有把安装成功冒充打开通过。
- 补充协议隔离浏览器门禁：`SUPPLEMENTARY_AGREEMENT_BROWSER_GATE=PASS`。五个 Actor 依次真实登录；两个浏览器标签复现旧 `row_version=1` 的 `PUT 409` 安全冲突，主协议完成证据绑定替换与确认（版本 3），另一待确认协议完成拒绝（版本 2）。最终 manifest 核对 `PUT 200/409 + POST 200/200`、三条成功幂等记录、三条操作日志及全部 Actor；锁定 PostgreSQL 镜像运行，专用容器清理为 0。
- 当前本地复核：`LOCAL_OFFLINE_QUALITY=PASS`、`POSTGRESQL_CURRENT_HEAD=PASS`、`CELERY_REDIS_BROKER_TRANSPORT=PASS`、`FINANCIAL_LOOP_BROWSER_GATE=PASS`、`LOCAL_SECURITY_BASELINE=PASS` 与 `LOCAL_SECURITY_PROMPT_INJECTION_BROWSER=PASS`。HTTP 安全门禁覆盖精确单一 `nosniff`、受保护 metrics、bounded logging、Worker `unless-stopped` 自动恢复、CSRF、锁定与反枚举、角色/对象拒绝、Trace、审计回滚、追加式日志、ClamAV→Worker→制度双人审批→安全专用 100 条集→真实 Qdrant、直接/间接 Prompt Injection 拒答、浏览器页面、PostgreSQL 终审与日志无 canary；传输加密、正式 DAST、业务代表性质量与 production 仍为 `NOT_RUN`。
- 2026-08-18 当前 checkout 的全新财务浏览器门禁使用合成 DOCX 完成上传、ClamAV、Dispatcher/Celery Worker、合同/发票提取与人工修正确认、合同来源供应商单条聚合纠错并激活、发票来源精确复用、主合同建议/确认、15 规则审核、财务复核、ready PDF/XLSX 和五纯角色授权矩阵。受保护 manifest 精确接受 `2 files / 1 contract / 1 invoice / 1 supplier / 1 relation / 1 task / 1 execution / 1 report / 5 actors`，completion 返回 `accepted`；测试容器清理，MinIO 测试数据卷按策略保留。
- 文件能力浏览器门禁：`FILE_UPLOAD_BROWSER_GATE=PASS`。真实同源登录后一次批量上传两份 PDF；正常样本完成原文与解析预览并归档，失败一次的样本复用原文件和原 Job 重新排队至 attempt 2 后成功并预览。受保护 manifest 精确核对两份权威文件、`files.previewed/files.archived/files.retry_queued` 操作日志、扫描/Job 终态和 batch 幂等声明；专用 PostgreSQL/Redis/MinIO/Worker 已清理。
- AC-016 本地运行与恢复：权威 PostgreSQL/MinIO 备份已恢复到独立项目并校验行数、对象摘要、冷启动、Redis/Qdrant 重建；`file_process`、`audit_execute`、`report_generate`、`knowledge_index_build` 和独立 AI 审计强杀恢复均有 SIGKILL、受管重启、Lease attempt 2、回滚/孤儿保留、同 ID 重放、唯一事实与日志脱敏证据。`CR-024` 后 persistent/disposable Compose 又通过 HTTP 启动、依赖、ClamAV 文件上传与预览；TLS 证据只保留为历史，HTTP 不提供加密。
- BOSS 已冻结 Local MVP 本机 Profile：Windows + Docker Desktop、当前实际使用者 1 人但系统支持多账号/五角色、`http://localhost:8443`、仅 `127.0.0.1`、全局 HTTP、本地 ClamAV、OCR/AI 关闭、仓库外受管 Secret、本机 PostgreSQL/MinIO 数据卷、重要操作前本地备份，且不作多人并发、正式容量/RPO/RTO/DAST/异地备份承诺。当前 `finaudit-local` 与一次性栈均 `LOCAL_STACK_START=PASS`，Alembic `20260817_024`、10 个长期服务、依赖 `ok`、Scanner `ok`、AI `disabled`、Frontend HTTP 200、HTTPS 握手失败、唯一 `127.0.0.1:8443` 绑定、零 TLS mount/生成文件和真实浏览器零 console warning/error 均已核对。`CR-023`/`CR-024` 的一次性运行通过 5 字符拒绝、弱 6 字符拒绝、安全 6 字符创建/换密/登录、普通会话、授权读取、Refresh/Logout 和无 Secure 的 HttpOnly/SameSite Cookie；专用栈、卷、Secret 和镜像已清理。BOSS 随后亲自完成持久 `admin` 换密并重新登录；数据库确认 force-change false 和普通会话 1，浏览器确认系统管理员工作台/用户管理读取成功且文件管理直达为 `AUTH_FORBIDDEN`，恢复密码已清零删除。YHBX 于 2026-08-18 明确签署 `Local MVP UAT通过`，故记录 `LOCAL_RUNTIME=VERIFIED`、`LOCAL_ADMIN_RECOVERY=VERIFIED`、`LOCAL_USER_SESSION=VERIFIED`、`LOCAL_AUTHORIZATION_SOD=VERIFIED`、`LOCAL_MVP_UAT=ACCEPTED`；production 与正式 AC 保持独立。
- production、业务代表性数据、业务人类 UAT、100 条 `formal_release`、正式索引激活和其余 AC 签署：`NOT_RUN`；50 条技术质量门禁为实际 `FAILED (49/50)`，不是 `NOT_RUN` 或 `PASS`。Local MVP 的 AC-001/002/015/016 结论仍按 `CR-025` 与签署制品独立为 `ACCEPTED`。
