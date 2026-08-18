# TEST-001 PARTIAL 测试策略

状态：`TEST-001 PARTIAL`。基础 S1-S9 交付测试策略、P0 追踪、固定合成资产和离线质量入口；当前 accepted head 为 `20260817_024` / 57 表。其后又增加隔离 PostgreSQL、真实 MinIO/Redis/Celery/Qdrant/ClamAV、完整 local Compose、依赖故障/恢复、权威备份/隔离恢复、完整财务浏览器闭环和受限真实 MiniMax Chat 证据。`CR-021/022` 的百炼 Embedding 已完成 Policy v2、Adapter、Backend/Worker、Event v2/CNY 持久审计和原子采用接线；首次连通性 smoke 及随后单独授权的完整知识库 E2E 均已成功。更晚一次 owner-delegated 100/50 技术集真实运行在 50 条门禁失败并安全停止；100 条与激活未运行。上述授权均已消耗。这些分层结果仍不代表业务代表性质量、`formal_release` 激活、production、UAT 或任何业务 AC 已通过。

2026-08-14 复核发现历史 Redis/Celery Gate 因 Docker Go template 的 label 参数在 Windows 命令行丢失内层引号而静默跳过清理，曾留下 4 个带独立 run-id 的测试容器及匿名 Redis 卷。修复后清理改用完整 label JSON，并核对容器 ID、用途和 run-id 后以 `--volumes` 删除；身份漂移或删除失败均使 Gate 失败。真实 Gate 重跑 `1 passed`、`CELERY_REDIS_BROKER_TRANSPORT=PASS`，同用途容器最终残留为 0。该证据只验证隔离 loopback Redis 的 Celery transport 和测试资源回收，不外推到 production、强杀/断电或完整 Compose。

2026-08-17 当前矩阵为 `2 implemented / 84 partial / 0 planned`：57 表、核心 Backend/Worker、主要 P0 Frontend、完整隔离财务浏览器闭环、五角色权限矩阵和 `local-compose-v1` 均已有分层证据。AI-001～005 已包含真实 MiniMax-M3 Chat Adapter、Gateway、严格结构修复、预算/网络策略、持久 EventSink、共享事务业务采用、合同/发票提取、RAG、风险解释、报告草稿和 OPS-005；受限真实 Chat smoke 覆盖五条生成链。`CR-021/022` 又增加百炼 Embedding、Event/Policy v2、USD/CNY/no-FX 审计和知识链原子采用；首次连通性 smoke 验证 43 input tokens、2×1024 维输出与 CNY 22 microunits，随后单独授权的完整知识库 E2E 用 7 次请求、3231 input tokens 和 CNY 1616 microunits 完成 15 个成员的 Worker/Qdrant 索引、Top-5 与 5/5 smoke，索引按 100 条 `formal_release` 门禁保持 `ready`。本轮还补齐 Redis server-time/Lua 跨进程并发、RPM/TPM 与熔断门禁，29 项聚焦测试、3 项 Redis 专项集成测试和当前 4 项 Redis/Celery wrapper 通过。DEP-006 从 planned 升为 partial，因为低基数 `/metrics`、独立 Bearer 权限与精确 Nginx 代理已实现。`partial` 仍明确保留代表性合同/发票和 50/100 条检索集、正式参考容量/性能、可访问性、DAST、production 监控告警/SLO、异地恢复和正式 AC；真实 E2E 不得写成质量验收。86 项当前实现层与正式验收层的分离审计见 `docs/testing/p0-current-completion-audit.md`。

同日新增 `synthetic-non-acceptance-v1`：纯标准库生成器从仓库 P-001、RET-001 和安全负例产生 120 条候选，以规范化问题 SHA-256 去重为 100 条并固定 50 条子集。100 条分布为 `60 answerable / 20 no_answer / 20 unauthorized`，50 条为 `30/10/10`，四个 answerable 锚点均衡覆盖；8 项来源/证据检查通过。资产显式固定零 Provider、未激活、未提交审批和空 runtime tier。按当前每题一次 Embedding 请求估算，复用 ready 索引时 50/100 条需 50/100 次请求；重建四条源分块时需 51/101 次，费用上界分别为 CNY `0.001760/0.003458`。这些只是合成非验收资产和付费前规划，不满足业务代表性审批或正式质量门禁。

同日又新增 `synthetic-policy-corpus-v1` 与 `synthetic-benchmark-candidate-v1`：纯标准库生成 6 个虚构制度族、12 个无重叠版本和 36 条证据条款，覆盖报销、供应商、发票、合同、审批权限、审计留痕；120 条候选按每领域 20 条均衡覆盖 `72 answerable / 24 no_answer / 24 unauthorized`、36 条同义改写、全部基准日期/制度版本和 24 条跨权限场景。100 条提议集为 `60/20/20`，固定 50 条 `mvp_uat` 为 `30/10/10`。重复、有效期矛盾、证据、拒答探针、权限标签和自然度共 8 项自动检查均为 0 异常。BOSS 后续委托 Agent 完成 local/test 技术语义复核：原 18 条队列为 12 条原样接受、6 条修订接受，全部 20 条 no_answer 重写复核，待处理为 0；资产明确 `human_review_claimed=false`。获批单次真实运行完成 36 条款索引并达到 `ready`，随后在 50 条门禁返回 `MVP-UAT-050_EVALUATION_FAILED`，100 条和激活未运行；精确 usage 未留存，安全上界不超过 52 请求、50000 input tokens、CNY 1 元。该失败不能改写为质量通过或正式验收。

同日新增 `representative-performance-evaluation-v1` 纯计算门禁：使用与本地性能基线一致的 nearest-rank P95，逐轮复算 §8.2 六项延迟、上传不等待长任务、至少三个审核任务并行且零丢失/零重复采用，并要求所有提交轮次通过。它拒绝缺失工作负载、非正耗时、重叠/不连续轮次和未计入的失败样本，但不会验证审批引用、Profile 或代表性真实性；正式运行仍为 `NOT_RUN`，输出固定 `formal_acceptance_status=NOT_DETERMINED`。

2026-08-17 新增 `report-artifact-compatibility-v1`。固定合成正式报告在宿主 Python 3.10.20 与当前本地 Backend 镜像 `sha256:44b77246577e3d2d8ba1877fdfe03dc05afeba5f71e8e68bfedfeb1b399d1e11` 分别生成：两份 3 页 PDF 字节相同、提取文本指纹相同且均由 Poppler 成功渲染，三页视觉复核无裁切/重叠；两份 XLSX 的 `Summary/Rules/Risks` 规范化单元格内容指纹相同，压缩包字节不同但都由 Microsoft Excel 以禁用宏、只读方式实际打开并核对关键单元格。LibreOffice `26.2.5.2` 后续已安装，但 Calc 对项目 XLSX 与最小单单元格 XLSX 的 headless 打开/转换均超过 180 秒未完成，仍明确为 `NOT_RUN`。详见 `docs/testing/report-artifact-compatibility.md`；该证据不签署 production、UAT、AC-014 或正式 AC。

同日对隔离报告页执行桌面和 390×844/375 px 窄屏自动化可访问性检查：唯一 `main`/`h1`、无重复 ID、标题层级无跳级、16 个可聚焦元素无未命名项、PDF iframe 有标题且 document 无横向溢出；主导航只在自身容器内按设计横向滚动。前端布局/报告页聚焦测试 5/5 通过。后续已在 Chrome `151.0.7922.138` 重放真实原生按键，登录页 Tab、Enter 登录、authenticated shell/dashboard Tab 与 skip-link 聚焦 `MAIN#main-content` 通过，console warning/error 为 0；Edge 控制因 URL 安全策略未形成证据，屏幕阅读器及全 P0 路由矩阵仍为 `NOT_RUN`。

同次局部增量为共享 `PageTabs` 增加 roving `tabindex`、左右方向键循环和 `Home`/`End` 聚焦切换，并为发票、知识库详情的 `tabpanel` 补齐标签关联。257 个聚焦前端用例、typecheck、build 通过；隔离报告浏览器 Gate 在真实发票详情页核对切换前后 selected/tabindex/focus/`aria-labelledby`，console warning/error 为 0，wrapper 正常清理并输出 `REPORT_BROWSER_GATE=PASS`。该证据只关闭共享标签页组件与本次页面运行路径，不外推到完整原生 `Tab` 路径、屏幕阅读器或正式可访问性验收。

Docker Scout 1.23.1 对当前 Bookworm Backend 镜像复扫仍为 `2C/2H`，四项均来自 `perl-base` 且无已修复版本；`--only-fixed` 为 `0C/0H`。使用官方锁定 digest 构建的 Python 3.10.20 Trixie 候选仍为同样 `2C/2H`，未带来门禁收益，因此 Dockerfile 恢复 Bookworm，候选镜像已删除。未签署 VEX 或风险接受，production 零严重/高危门槛仍未通过。

## 1. 目标与完成口径

本策略为后续 `TEST-002`～`TEST-007` 固定测试边界和证据口径，使每个 P0 开发任务有且仅有一条基础追踪记录，并让测试数据可以在不接触真实凭据、真实业务数据、网络或运行中服务的情况下被确定性校验。

本切片完成的证据仅限：

- 86 个非 P1 任务与测试用例、测试层、AC 的追踪映射；当前矩阵计数为 `2 implemented / 84 partial / 0 planned`。
- JSON 数据集版本为 `1.6.0`（39 条）；另含 14 个由 `binary_fixture_contract_version` 单独版本化的小型二进制样本及 SHA-256 清单。
- 账号 fixture 的五角色最小集、两名不同审计复核员、六个固定 ID 的角色/活动状态/Request 职责边界、禁用/锁定状态、合成用户名唯一性和 specification-only break-glass 语义门禁；不包含凭据或账号实建。
- 核心业务 fixture 的 SRS 固定合同/发票/制度值（含 C-001 双方名称、P-001-V2 名称与 3.1/4.2/4.3/5.1 条款）、重复元组、分块质量，七个标量安全负例的固定输入、五个结构化负例的输入不变量与十二类预期门禁；S5 新增用户直接注入和 HTML/Markdown 隐藏指令，S6 新增表格单元格角色覆盖和用户伪造 `candidate_id`，不固定模型措辞、未明确字段集或待 CR 参数。
- `RET-001-01`～`05` 固定 Request 给出的五条问题和分类；前三条同时固定 P-001-V2、3.1/4.2/4.3 锚点与 Top-5，后两条固定拒答/过滤预期，但不把正式 100 条评测集 Schema 或真实检索行为提前固结。
- 独立 `synthetic-non-acceptance-v1` 生成 120 条候选、100 条去重集和 50 条固定子集，并保存来源身份、覆盖矩阵、8 项证据核验及四种付费预算场景；它不进入固定 fixture manifest，不创建数据库评测集或任何验收状态。
- 覆盖正式测试方案 5.3/5.4 的无来源映射、空分块、超长分块构造规格，以及缺失目标字段、冲突金额和伪造候选引用六类固定负例。
- 版本为 `1.0.1` 的二进制 manifest 契约，固定场景、静态分类、业务 fixture 和 P0 任务映射；本补丁修订不改变 ID、路径、场景或映射。
- 可离线重复运行的生成器；它从受 Request 语义门禁保护的核心业务 JSON 读取 C-001 主体名称/税号和 P-001 名称，并结合资产 allowlist、路径、长度、哈希、必需 ID、最低文件包络和 JSON 敏感内容检查约束二进制内容。
- 独立临时副本中的 38 类负向门禁，覆盖 P0 矩阵任务集、manifest 固定集合、缺失/额外/哈希/结构/路径漂移、JSON/二进制版本轴、账号固定角色/状态/职责边界，以及核心业务、安全 ID/输入/预期、检索语义、JSON 数值/Boolean 与二进制 manifest 整数/数组类型漂移；版本、语义和类型篡改会同步必要的 manifest 哈希，以证明失败来自目标门禁而非哈希。文件符号链接分支在无权限环境中显式报告 `NOT_RUN`。
- `scripts/verify-local-offline.ps1` 对既有 baseline/Git/资产正负门禁、Backend 测试/静态检查和 Frontend 类型检查/测试/构建进行失败即停的顺序编排；负向自测证明缺失 Backend Python 时非零退出且不输出 PASS。
- `scripts/verify-cr011-gate-b-stage1.ps1` 在禁用外部 pytest 插件和环境注入后，仅收集 strict parser、companion、resolver、retry、response boundary、network policy、Event DTO 与 Fake Sink 的 contract/offline 测试；zero-socket audit hook、执行数等于收集数、skip/xfail/筛选防伪和独立负向 runner 均为强制条件。
- CR-011 full Gate B 使用锁定的 test-only `jsonschema 4.26.0` 与 `Ajv 8.20.0` 双引擎；离线物化、full Gate 负向自测和正式 wrapper 是三个独立且顺序固定的步骤，不进入默认 `verify-local-offline`。
- AI-002 offline repair 为 structured output 46 项 + structured repair 56 项，组合 102 项；只验证同目标、最多两次修复、安全 issue 投影、共享 attempts/Token/费用/deadline、validator deep-copy 隔离、固定异常映射与脱敏，以及 validator 原地修改/返回值均不替换严格解析对象。coroutine、同步 generator 与 async-generator validator 在 initial/repaired 路径都必须失败关闭、主体不执行并返回无 cause/context 的固定 `INTERNAL_ERROR`。
- AI-001/AI-005 持久 Port 适配为 24 个聚焦用例：精确转交持久预算与绝对 monotonic deadline、六种 reserve/complete 结果、同 scope commit-unknown 恢复、跨 scope/新实例 replay 无许可、未消费发送许可不得采用，以及 `outcome_unknown/late_completion` 永不产生采用许可。隔离 PostgreSQL `-Scope AI` 另以真实 `AiCallAuditService` 证明首次 reserve/complete 许可和重建 Sink 后 replay 无许可；它不执行 Gateway、Provider 或业务事实写入。

完整 `TEST-001` 仍需正式非生产账号交付、目标环境初始化/重建演练、业务代表性审批评测集与正式验收证据。owner-delegated 100/50 技术集不等于人类 UAT，且真实 50 条门禁当前失败；安全专用 100 条全 `no_answer` 合成集和 `synthetic-non-acceptance-v1` 也不满足业务质量条件。上述证据未通过前，状态必须保持 `partial`。

## 2. 正式测试分层

| 层级 | 主要对象 | 最低验证内容 | 所属后续任务 |
|---|---|---|---|
| static | 文档、配置、Schema、代码和追踪关系 | 格式、单一事实来源、依赖方向、敏感内容 | 各任务共同门禁 |
| unit | 领域函数、状态机、确定性规则 | 正常、边界、非法状态、Decimal 精确断言 | TEST-002 |
| component | 前端组件、路由守卫和局部交互 | 渲染、权限、状态切换、空态和错误态 | TEST-003、TEST-004 |
| database | 迁移、约束、触发器、不可变版本 | 升降级、唯一性、并发、回滚和幂等 | TEST-002、TEST-004 |
| adapter | OCR、解析、存储、模型和向量库边界 | 成功、超时、可重试失败、不可恢复失败 | TEST-004、TEST-005 |
| api | OpenAPI 中全部已实现 P0 API 与后端权限 | 成功、错误、403、冲突、幂等、`trace_id` | TEST-003 |
| integration | API、Service、Repository、Worker 与基础设施协作 | 事务、Job、Outbox、崩溃恢复和一致性 | TEST-004 |
| ai_regression | 提取、RAG、引用、拒答和检索指标 | 固定输入/版本、无答案、越权、注入和降级 | TEST-005 |
| e2e | UI 到 Backend 的 P0 主流程 | AC-001～AC-016 的代表性用户路径和失败状态 | TEST-004 |
| security | 认证、授权、上传、日志、导出和 AI 信任边界 | 越权、伪装、注入、路径、脱敏和审计 | TEST-006 |
| performance_recovery | 性能、稳定性、备份、恢复和重建 | 三轮 P95、无丢失/重复、恢复点和 Qdrant 重建 | TEST-007 |
| uat | 业务角色验收 | 固定验收数据、签字记录和遗留风险 | 发布前人工门禁 |

低层证据不能替代高层证据。例如，静态映射或构建通过不等于运行时 AC 通过。

## 3. 环境隔离

| 环境 | 用途 | 允许数据 | 模型/外部依赖 | 隔离要求 |
|---|---|---|---|---|
| local | 开发自测和本切片离线校验 | 最小合成数据 | 默认 Mock；离线 | 不读取生产配置，不依赖前次运行残留 |
| test | 自动化、数据库和集成测试 | 固定合成/批准脱敏集 | 受控 Mock 或固定测试模型 | 独立 PostgreSQL、MinIO 前缀、Qdrant Collection、Redis DB/实例 |
| staging | E2E、性能、UAT 和演示 | 固定验收数据 | 与候选版本一致的受控配置 | 独立凭据、存储、日志目的地和网络策略 |
| production | 正式运行 | 正式数据 | 正式模型和依赖 | 测试不得写入、复用凭据或发送日志到此环境 |

每个环境必须能识别 Prompt、Schema、Chunk、Embedding、规则、代码和数据集版本。测试账号不得复用生产账号或凭据；测试日志不得进入生产日志系统。测试结束后的清理或重建必须由环境专用流程完成，不能以人工保留的隐式状态为前提。

## 4. 证据等级与默认门禁

| 等级 | 定义 | 本切片状态 |
|---|---|---|
| static | 文件、矩阵、Schema、配置和 diff | 已产生；BASE-001 已补项目分支/ref、RootPath/.git、raw/effective remote URL 失败关闭门禁及项目工作流 synthetic fixture 严格验证 |
| build | lint、类型检查、单元/契约测试、构建和确定性制品 | 生成器字节复现、资产正/负向校验、CR-011 当前 Stage1 275/275 及 full Gate B 双引擎离线 PASS 仅提供此级局部证据 |
| runtime | 实际 API、Worker、数据库、存储、浏览器和代表性输入行为 | PostgreSQL 16.14 已验证当前 009/18 表及真实临时 keyfile 经 loader/应用 lifespan、零依赖覆盖的 Auth 与七条财务读链组合目录；显式本地浏览器 Gate 也已消费临时 Ed25519 keyfile、生产 keyring loader 与零 override `create_app` lifespan，验证同源七条财务只读链、refresh 深链 reload 和 logout 后匿名 reload；显式 real local MinIO Adapter Gate 验证合成 quarantine 对象和两个确定性补偿路径，独立 restart Gate 验证同一对象/身份跨一次受控冷重启；二者均不包含 FILE Router、数据库/Job/Scanner 或完整业务链 |
| external | 远程分支保护、真实扫描产品、真实模型/GPU、部署环境和人工 UAT | 未执行 |

默认门禁为离线：不得访问外网、Provider 或已有运行服务，不得启动容器、调用真实模型或读取 `.env`。后端连接配置负例允许只绑定 `127.0.0.1` 临时端口并执行预期失败的本机网络栈检查；它不访问外部服务，且必须由统一编排明确输出，不能被表述为“完全没有 socket”。CR-011 Stage1 是另一条更窄门禁，要求整个选定 pytest 进程 zero-socket attempts=0。`scripts/generate_test_documents.py --check`、`scripts/verify-test-assets.ps1` 和负向自测成功只证明固定资产可复现且静态结构自洽；失败必须阻断资产合入，成功不得被表述为 PDF/DOCX 业务解析、OCR、TEST-001、AC 或发布门禁通过。`scripts/verify-local-offline.ps1` 只编排当前已存在的 static/build 级检查；它不下载或物化 CR-011 test-only 依赖，也不运行 CR-011 full Gate B，并固定把 PostgreSQL current-head、Docker/Compose runtime、浏览器 E2E（`BROWSER_E2E=NOT_RUN`）、Provider、其他外网、远程分支保护、部署和 production 输出为 `NOT_RUN`；Provider/其他外网、真实数据、部署和 production 同时为 `NOT_AUTHORIZED`。显式本地浏览器 Gate 是默认离线编排之外的独立 runtime 证据，二者不得互相替代。

## 5. 测试账号规格

固定账号规格由 `tests/fixtures/accounts.json` 描述，不含凭据：

- 1 个 `system_admin`。
- 1 个 `finance_reviewer`。
- 2 个不同的 `audit_reviewer`，用于提交人与批准人分离。
- 1 个 `contract_admin`。
- 1 个 `read_only`。
- 1 个禁用账号和 1 个锁定账号。
- 1 个临时 break-glass 规格，要求目的、时间窗、另一名授权人员的批准记录和审计留痕；批准人身份仍由正式安全设计关闭。

账号实建、凭据发放、登录验证、禁用/锁定行为和 break-glass 批准均不在本 S1-S9 切片范围内，不得从规格文件推断这些能力已实现。

## 6. 确定性原则

- Clock：所有时间相关测试显式注入固定 UTC 时间；禁止直接依赖当前时间决定断言。
- Random：所有随机数据生成器使用记录在测试证据中的固定 seed。
- UUID：使用预先声明的测试 UUID 或由固定 namespace 与稳定名称派生的 UUID；禁止在快照断言中使用不可复现的随机 UUID。
- 排序：相同优先级结果必须指定稳定次序和 tie-breaker。
- 财务值：金额使用十进制字符串和 Decimal 断言，不使用二进制浮点比较。
- AI/RAG：输入、数据集、模型、Prompt、Schema、Embedding、Chunk、索引、Top-K 和阈值必须版本化；单次人工观感不构成通过证据。

## 7. S7～S9 本地质量门禁

### 7.1 S7/S8 默认离线编排

在已安装项目依赖且不读取 `.env` 的当前工作区运行：

```powershell
.\scripts\test-verify-local-offline.ps1
.\scripts\verify-local-offline.ps1
```

BASE-001 的 Git 治理自测使用操作系统临时目录中的真实独立仓库根，覆盖五类正式分支、Git 原生非法 ref、仓库/环境重定向、原始 remote 配置 literal CR/LF、raw/effective URL、`insteadOf/pushInsteadOf`、凭据/协议/路径负例以及精确成功 marker；写操作仅发生在该可丢弃临时仓库，对目标工作区保持只读，不执行 fetch/push 或托管平台查询。另一个固定 synthetic fixture 验证器只接收 `--stdin` 有界字节流，以纯标准库拒绝重复键、类型强转、分支/check 漂移及 marker/secret 注入，不调用文件、Git、网络或外部进程 API，并在默认离线编排中运行正负门禁。两者成功都只证明本地算法与项目工作流投影，必须继续输出 `BASELINE_TASK_STATUS=PARTIAL` 与 `REMOTE_BRANCH_PROTECTION=NOT_RUN/NOT_VERIFIED`，不得写成 Request-exact 或远程演练。离线编排器的 9000-byte 固定身份为 SHA-256 `455ba2ea80534d594dabce6869bc8bf441892ac3f36414783d1c47df90a94f43`；负向自测同时封堵动态 Ruff scope 增宽、额外 Ruff 调用和伪造失败原因。

编排器不安装或物化依赖、不启动 Docker、不访问 Provider，也不调用 CR-011 full Gate B；它主动清除子进程的 `TEST_DATABASE_URL`，避免把偶然存在的外部数据库带入“离线”证据。Backend Ruff check/format 只接受精确 scope `app`、`alembic/versions`、`tests`；`backend/alembic/recovery` 匹配 0 个 accepted files，格式检查为 `NOT_APPLICABLE`。Frontend 步骤只在子进程范围设置 `FINAUDIT_LOCAL_OFFLINE_QUALITY=1`，使 Vite `envDir=false`，因此不会加载 `frontend/.env*`；结束后恢复调用者原值。成功末尾必须输出 `LOCAL_OFFLINE_QUALITY=PASS`；任一步非零时立即失败且不得输出 PASS。输出中的 `LOOPBACK_NETWORK_STACK=RUN` 只对应隔离的预期失败连接负例；该结果仍只聚合本地 static/build 证据，所有明确的 `NOT_RUN` 均保持为未执行。

历史 checkpoint（2026-08-10）：默认 `verify-local-offline` 当时为 Backend `1625 passed, 35 skipped`、Ruff/format 126、Mypy 70、Frontend `216` 项测试、typecheck 与 build 通过并输出 `LOCAL_OFFLINE_QUALITY=PASS`。该数字已被下述当前 checkpoint 取代；由于当时进程未设置数据库授权变量，PostgreSQL current-head、Docker/Compose、浏览器 E2E、Provider、其他外网、远程、部署与 production 均未运行。

2026-08-12 请求层进一步固定 multipart 与响应身份边界：FormData 请求删除调用方 `Content-Type`，由浏览器生成含正确 boundary 的 multipart Header；`AUTH_PASSWORD_CHANGE_REQUIRED` 在所有路径使用固定消息并丢弃不可信 `details`，只有精确 `POST /api/v1/auth/login`、HTTP 403 和合法 `data` 可不可枚举地保留受限 Token。成功响应 body 与错误响应 body/header 的 `trace_id` 只接受标准小写 UUID；不可信候选不会透传，错误路径只会降级到另一个安全候选或空字符串，并排除与 Token 相同的 UUID 形态值。ApiClient 聚焦测试 28 项、Frontend typecheck、6 个 Vitest 文件共 230 项测试和 Vite `write:false` 构建均通过，独立审查未发现 Critical/High/Medium 问题；该证据不产生真实认证 runtime、浏览器业务链或 AC 证据。

2026-08-15 显式运行 `scripts/verify-file-upload-browser-gate.ps1` 并 PASS：一次真实浏览器 FormData/multipart 上传穿过生产 Auth Actor、FileIntakeService、PostgreSQL 文件/Job/Step/Outbox/operation-log 事务、应用 MinIO quarantine、Outbox Dispatcher、隔离 Redis/Celery document Worker，以及生产 ClamAV INSTREAM Adapter 对合成 loopback clamd 端点，最终文件/Job 恢复为唯一 `stored/clean/succeeded` 并保持同一安全 Trace。浏览器 reload 与详情读取恢复同一服务端事实；同一财务角色上传越权 `policy` 返回 403，事实数保持 1；页面 warning/error 日志为空，PG/Redis/MinIO 受控清理通过。该 Gate 不使用 production Scanner，不覆盖通用解析后的合同专用提取、批量上传、强杀/断电、容量、TLS/Nginx、production 或正式 AC；默认离线编排仍保持 `BROWSER_E2E=NOT_RUN`。

2026-08-12 production route config regression 已验证 `AppEnvironment.PROD` 下 `/health` 返回 200，而 `/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc` 全部返回 404；`test_app.py` 聚焦 20 项通过，独立审查为 `GO`。该证据只覆盖配置 seam，真实 production Policy、runtime 与 deploy 仍为 `NOT_RUN`。

2026-08-11 FILE-001 进一步固定空上传失败边界：`measure_upload_stream` 对无 chunk、单个空 chunk 和多个空 chunk 均复用 400 `FILE_SIGNATURE_MISMATCH`，使纯服务计量结果符合 `files.size_bytes > 0`；FILE 六文件聚焦套件 135 项通过。该证据不包含 multipart Form/API、PostgreSQL 持久化、MinIO、Scanner、Job/Worker 或业务 runtime；严格布尔字段的 multipart 文本解析仍留待获批 Form Router 边界。

较早的 2026-08-11 checkpoint 中，新增应用 PostgreSQL Engine/Session 工厂及显式安全 `TEST_DATABASE_URL` 运行探针，并将 Celery 路由收窄到七个精确 `execute_job` task name、未知 task 失败关闭、固定 `task_publish_retry=false`；当时 Backend 为 `1706 passed / 36 skipped`，Ruff、format、mypy 及 Frontend 222 项/build 通过。该数字已被下述当前 checkpoint 取代。显式调用 PostgreSQL current-head 门禁时 Docker daemon 未启动，门禁在创建容器前失败；Session 真实 PG、Docker、Redis/Broker、Repository、业务 API 和 AC 均为 `NOT_RUN`。

2026-08-11 的一轮历史 checkpoint 中，`CON-003` 聚焦测试为 `43 passed`，当时 Backend 全量为 `1726 passed / 36 skipped`，Ruff、format 和 mypy 通过。该结果只证明确认/生效筛选、协议级事实一致与整组应用、顺序无关回放、原始/有效字段分离、递归冻结、输出物化、来源归属、重复约束与同日歧义失败关闭；SAGR API、认证、Repository、PostgreSQL、过期传播、审核快照、浏览器 E2E 与 AC-004 均未运行或未实现。

当前 `CON-003` 聚焦套件为 52 项：此前 47 项已含 4 个参数化 case，覆盖顶层和嵌套 Decimal `NaN/sNaN/+Infinity/-Infinity` 的失败关闭；随后新增 5 个有限 Decimal 正向 case，确认冻结投影和隔离物化均精确保留原值。它仍是纯领域证据，不升级 SAGR API、持久化、状态机、浏览器 E2E 或 AC-004。

2026-08-12 较早的完整 `verify-local-offline` accepted-source checkpoint 纳入当时 MVP-VS-01～06、OQ-09 离线预备链、Auth 凭据响应防缓存、Frontend 会话代际保护、合同/发票列表→详情及发票当前主合同真实只读切片：Backend `2175 passed / 67 skipped / 1 Starlette deprecation warning`、Ruff check/format 186 files、mypy 101 sources、Frontend 325 Vitest/124-module build；同期此前显式 S9 PostgreSQL Gate 为两轮 81/81。该段仅保留历史 checkpoint，不再表示当前数字。

2026-08-12 最新完整 `verify-local-offline` accepted-source 质量 checkpoint 已继续纳入 TECH §6.12 `supplementary-agreement-header-list-read-v1`、§6.13 `contract-primary-invoice-list-read-v1`、authenticated financial read API 组合测试、应用启动 Service 构造失败时释放 engine 的回归及默认原生 `fetch` receiver 回归：Backend `2252 passed / 73 skipped / 1 Starlette deprecation warning`；Ruff check/format 对精确 `app + alembic/versions + tests` 范围通过（197 files），mypy 105 sources、pip check 通过；Frontend typecheck、13 files/372 Vitest 与 Vite 8.2.0 write-false build（128 modules）通过；baseline/assets/governance/runner negatives 通过。默认离线编排本身仍不运行 PostgreSQL current-head、真实 MinIO、浏览器（`BROWSER_E2E=NOT_RUN`）、Provider、远程、部署或 production。矩阵计数保持 `2 implemented / 38 partial / 46 planned`。

2026-08-13 的 `user-list-read-v1` 完整 `verify-local-offline` accepted-source checkpoint 为 Backend `2362 passed / 74 skipped / 1 Starlette deprecation warning`；Ruff check 对精确 accepted-source 范围通过，Ruff format 211 files，mypy 114 sources、pip check 通过；Frontend typecheck、14 files/398 Vitest 与 129-module write-false build通过。该历史 checkpoint 的默认门禁仍把 PostgreSQL current-head、Compose、浏览器（`BROWSER_E2E=NOT_RUN`）、Provider、远程、部署和 production 分开记录；同期独立显式 PostgreSQL 16.14 current-head Gate 为双轮 89/89，矩阵当时为 `2 implemented / 38 partial / 46 planned`。

2026-08-13 当前最新完整 `verify-local-offline` accepted-source 质量 checkpoint 已纳入 TECH §6.14 `invoice-exact-duplicate-candidates-read-v1`：Backend `2398 passed / 75 skipped / 1 Starlette deprecation warning`；Ruff check 对精确 accepted-source 范围通过，Ruff format 212 files，mypy 114 sources、pip check 通过；Frontend typecheck、14 files/412 Vitest 与 129-module write-false build通过。独立显式 PostgreSQL 16.14 current-head Gate 对同一唯一 head 连续两轮各 90/90 PASS。默认离线门禁仍把 PostgreSQL current-head、Compose、浏览器（`BROWSER_E2E=NOT_RUN`）、Provider、远程、部署和 production 分开记录；本切片没有浏览器、production、容量/性能或正式 AC 证据。`INV-004` 只因精确候选读链从 planned 升为 partial，矩阵现为 `2 implemented / 39 partial / 45 planned`，其他任务和全部 AC 状态不变。

2026-08-13 随后交付 TECH §6.15 `invoice-exact-duplicate-pair-read-v1` 的聚焦 checkpoint：Backend 重复候选/API/两个数据库文件共 `76 passed / 17 skipped / 1 Starlette deprecation warning`，其中 skipped 只因该次未注入显式 `TEST_DATABASE_URL`；相关 Ruff check、Ruff format 与四个生产源文件 mypy 均通过；Frontend `invoices.test.ts` 为 `66 passed`，typecheck 通过。该切片以单条有界 PostgreSQL 自连接点查两个已知 UUID，并在 Frontend 详情内对候选做迟到响应安全的显式核对；它不确认重复、不写 `duplicate_status`、风险、审核任务或 operation-log。随后显式 PostgreSQL 16.14 current-head Gate 对唯一 head `20260807_009` 的 91 项集成目录连续两轮 91/91 PASS，脚本 exit 0，专用标签残留容器为 0；完整 `verify-local-offline` 与浏览器没有重跑。新增路径的容量/性能、浏览器、production 和 AC-005 仍为 `NOT_RUN`。

2026-08-15 当前最新完整 `verify-local-offline` accepted-source checkpoint 已纳入 accepted head `20260814_020` 的后续 Backend 主链、单文件浏览器门禁代码、Frontend Trace 展示和 baseline 自测环境恢复修复：Backend `2668 passed / 124 skipped / 1 Starlette deprecation warning`；Ruff check 通过且 format 覆盖 382 files，mypy 218 sources、pip check 通过；Frontend typecheck、21 files/488 Vitest 与 Vite 8.2.0 build（136 modules）通过。Vitest 输出一次 `ECONNRESET socket hang up` 控制台噪声，但 21/21 文件、488/488 测试和进程退出码均为 PASS。默认门禁仍明确输出 PostgreSQL current-head、Docker Compose、浏览器 E2E、Provider、remote 与 production 为 `NOT_RUN`；本节另记的显式文件浏览器 Gate 不得并入默认门禁，也不构成任何正式 AC。

2026-08-16 较早的完整 `verify-local-offline` checkpoint 已纳入报告/知识崩溃门禁、AI-005 provider-neutral 持久审计 primitive、AI 审计 OS 级崩溃门禁、AI-003 版本化提取 Prompt primitive、持久 EventSink 适配、补充协议 Frontend/API 接线、受保护浏览器门禁 fixture 和状态中文标签回归：Backend `2895 passed / 133 skipped / 1 Starlette deprecation warning`、Ruff check/format 440 files、mypy 245 sources、pip check、Frontend typecheck/26 files/526 Vitest/147-module build 全部 PASS。相关数据库回归在未提供隔离 `TEST_DATABASE_URL` 时安全跳过；持久 Sink 与真实 Service 的独立 `-Scope AI` 当前 head 门禁另行 PASS，完整目录的最近有效证据仍见 S9 的 021/143 项双轮。baseline 负例还在 Windows PowerShell 窄 TTY 下通过，断言会折叠终端插入的空白但仍要求完整错误语义、精确相对路径和零哨兵泄漏。默认离线编排仍将 PostgreSQL current-head、Compose、浏览器、Provider、remote 和 production 分别输出为 `NOT_RUN`；下述显式运行证据不能并入离线门禁。

2026-08-17 当前最新完整 `verify-local-offline` checkpoint 已纳入真实 MiniMax Chat 链、CR-022 Event/Policy v2、百炼 Embedding 审计/采用、Redis 跨进程运行门禁、两套合成候选资产、owner-delegated 技术复核、失败运行证据和 Chrome 键盘机器证据：Backend `3046 passed / 141 skipped / 1 Starlette deprecation warning`；Ruff check/format 496 files，mypy 271 sources、pip check通过；Frontend typecheck、26 files/527 Vitest 与 Vite 8.2.0 build（147 modules）全部 PASS。baseline、Git governance、分支保护 fixture、测试资产正负门禁均由同一 wrapper 通过。该离线门禁主动不调用 Provider、不启动 PostgreSQL/Docker、不运行浏览器或 production，因此输出中的 `PROVIDER_NETWORK=NOT_RUN`、`POSTGRESQL_CURRENT_HEAD=NOT_RUN`、`BROWSER_E2E=NOT_RUN` 与 `PRODUCTION=NOT_RUN` 保持有效。另行显式运行的 PostgreSQL 16.14 current-head `20260817_024` Full wrapper连续两轮通过，Redis/Celery wrapper 4 项通过；此前单独获授权的百炼 Embedding smoke/E2E 也已通过，而更晚的 50 条技术质量门禁实际失败。Provider、PostgreSQL、Redis 与浏览器的显式结果不能并入离线 wrapper，production 仍为 `NOT_RUN`。

2026-08-16 在同一当前 checkout 另行显式运行 `scripts/verify-financial-loop-browser-gate.ps1` 并输出 `FINANCIAL_LOOP_BROWSER_GATE=PASS`。脚本以 `--pull never` 使用本地不可变 `POSTGRESQL_IMAGE_ID=sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` 与 `REDIS_IMAGE_ID=sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`；当标签 inspect 没有返回唯一完整 ID 时，只从本地 `image ls --no-trunc` 解析唯一候选、按不可变 ID 复核后运行，PostgreSQL data tmpfs 为 1 GiB。真实浏览器以合成 DOCX 完成合同/发票上传 → Scanner → Dispatcher/Celery Worker → 专用提取 → 完整事实修正 → 人工确认 → 合同来源供应商候选 → 同一原子提交修正名称并确认激活 → 发票来源按税务身份精确复用 → 主合同建议/确认 → 15 条规则审核 → 财务复核 → ready PDF/XLSX；PDF blob iframe、XLSX 下载动作、制品 hash/size 和五纯角色导航/禁止直达矩阵均实际验证，页面控制台 warning/error 为 0。首轮把供应商“保存字段”和“确认并激活”拆成两次写入，受保护 manifest 按设计以 `2 correction / 2 update` 拒绝，清理后不计通过；最终全新重跑精确收敛为 2 个文件/绑定、1 个合同/发票/供应商/主关系/任务/执行/报告、1 条聚合纠错、2 次 `supplier.resolve`、1 次 `supplier.update` 和 5 个登录 Actor，completion endpoint 返回 `accepted`。专用 PostgreSQL/Redis/MinIO 容器最终为 0，本地 MinIO 数据卷按启动器既有策略保留。该证据使用合成 clamd、确定性本地提取/答案和 loopback HTTP，不证明 production Scanner/OCR/TLS、真实 Provider、正式可访问性、UAT、production 或 AC-001～016。

2026-08-16 又在可丢弃 Report Gate 运行时会话对新补充协议 UI 做真实浏览器增量检查：财务只读角色从合同详情打开字段级补充协议，页面保持写操作不可用；基准日期 `2026-06-30` 通过真实 Backend 返回并渲染 13 项原始值/有效值/来源字段。桌面布局和 390×844 视口均检查，首次窄屏发现全局 224 px 侧栏挤压并造成 document horizontal overflow；新增 760 px 响应式规则后重测为页面级零横向溢出，宽表只在自身容器内滚动，console warning/error 为 0。该宿主命令因 `/goal` 继续边界在门禁 wrapper 正常收尾前终止，因此本次运行没有 `REPORT_BROWSER_GATE=PASS`，只采用上述逐项浏览器证据；精确归属 PostgreSQL、MinIO 容器和网络均已人工复核并清理为 0，既有 local MinIO named volume 按启动器策略保留 1 个。补充协议完整变更集合提交、确认/拒绝、409 冲突与角色矩阵只通过客户端/组件/API 测试，完整浏览器写 E2E 仍为 `NOT_RUN`。

2026-08-16 随后在当前 checkout 独立运行 `scripts/verify-supplementary-agreement-browser-gate.ps1` 并输出 `SUPPLEMENTARY_AGREEMENT_BROWSER_GATE=PASS`。门禁用全新 PostgreSQL 16.14 和临时 Ed25519 keyring 启动真实应用，不启动 MinIO/Redis/Worker；真实浏览器以 `contracts.manage` 账号从合同详情打开未确认补充协议，提交 `amount / number / 100.25 → 120.50`、第 1 页逐字引用和本次解析 block UUID，再人工确认并用 `2026-06-30` 基准日读取有效值。页面逐步渲染“未确认 → 待确认 → 已确认”、行版本 `1 → 2 → 3`、旧/新值、完整证据和生效来源，console warning/error 为 0；运行中发现通用 `StatusTag` 遗漏 `unconfirmed/pending_confirmation` 中文映射，修复后用全新数据库重跑才计入证据。受保护 manifest 逐项确认唯一 `amount` 变更、修正原因、确认 Actor、`changes_replaced/confirmed` 日志和 PUT/POST 两条成功幂等记录，completion endpoint 返回 `accepted`；专用容器最终为 0。两次诊断运行因未发放 completion 令牌或发现标签缺口而故意失败，不计为 PASS。该正向门禁不代表拒绝、409 并发冲突、五角色补充协议写矩阵、production 或正式 AC 已通过。

2026-08-17 在当前 checkout 重跑同一受保护门禁并扩展到失败路径与角色登录矩阵。系统管理员、财务审核、审计复核、只读和合同管理员五个合成 Actor 均通过真实登录页进入各自导航；合同管理员在两个浏览器标签同时加载主协议版本 1，主标签成功提交完整证据变更到版本 2，旧标签随后得到安全 `409` 与公开 Trace ID，再由主标签确认到版本 3。第二份待确认、无来源证据的协议由同一合同管理员填写原因后拒绝到版本 2。最终 manifest 精确核对 `PUT changes=200/409`、`POST decision=200/200`、三条成功幂等记录、`changes_replaced/confirmed/rejected` 三条操作日志、两个协议和全部五个登录 Actor；completion 返回 `accepted`，脚本输出 `SUPPLEMENTARY_AGREEMENT_BROWSER_GATE=PASS`，锁定 PostgreSQL 镜像的专用容器清理为 0。该合成 loopback HTTP 证据仍不构成 Chrome/Edge 正式矩阵、production、业务 UAT 或 AC 签署。

2026-08-16 另行使用 Docker Scout 1.23.1 扫描同一 revision 的本地镜像。Frontend digest `61c6cd5ad8b2` 为 `0C/0H`；Backend 原 digest `623379c95037` 为 `2C/6H`，其中 `pypdf 6.13.0` 的两个高危可由不可信 PDF 提取路径触达，另有运行时不需要的 `wheel/jaraco-context` 高危。将 `pypdf` 固定到 `6.14.2` 并在构建后删除 `pip/setuptools/wheel` 后，新 digest `18089da95f35` 为 `2C/2H`、229 packages，`--only-fixed` 为 `0C/0H`。一次性容器还确认 UID/GID `10001:10001`、`pypdf 6.14.2`、安装工具模块不存在且应用模块可导入；随后完整离线门禁按上段数字再次 PASS。剩余四项全部来自 Debian Bookworm `perl 5.36.0-7+deb12u3`，Scout 均标记 `Fixed version: not fixed`。该结果不是正式 DAST、production 镜像签署或“严重/高危为 0”验收。

2026-08-16 的 AI-003 聚焦回归为 16/16 PASS。合同 Prompt identity 为 `contract_field_extraction / contract-field-extraction / v1 / d79afad7a5654d72091a34f4c0d0e5a7123d95dde4eb24503d6634fa1ac2698a`，发票为 `invoice_field_extraction / invoice-field-extraction / v1 / 09f1c58c930c0e49d912f7052243c00e377fea11260de010cf1cb090cb91d3de`。用例覆盖输入顺序无关的 canonical JSON、同一 parse version、UUID/位置唯一、原文提示注入只保留为 user data、bbox 复制、confidence 和非法输入失败关闭。它没有运行 Gateway、EventSink、Provider、业务输出采用、数据库或代表性字段准确率；发票无证据币种与当前非空/CNY 默认运行合同仍未闭合，因此 AI-003 只为 partial。

2026-08-16 另行显式运行 `local-report-generate-crash-recovery-v1` 并 PASS。门禁先完成真实 `audit_execute` 和 medium/high 双角色复核，在 Worker 停止时排队唯一 `report_generate`，再以 `operation_logs` 排他锁把 attempt 1 稳定阻塞于最终数据库事务；此时确定性 PDF/XLSX 已写入 MinIO，但报告制品定位字段、ready 状态和生成日志仍未提交。精确 SIGKILL Worker 并终止唯一孤儿等待后端后，数据库保持零制品事实，两个对象仍以相同字节、SHA-256 和大小存在；Maintenance attempt 2 最终收敛唯一 ready 报告。客户端详情/列表/PDF 预览/XLSX 下载及响应头通过，数据库核对 `failed/LEASE_EXPIRED → succeeded`、唯一 Outbox、唯一生成日志和精确 locator/hash/size。运行中发现 Backend 与 Nginx 重复输出 `X-Content-Type-Options`，现由 API 代理隐藏上游值并在边缘统一输出一次。最终专用容器、卷、网络、helper、运行时 Secret 和端口为零；该证据不证明自动重启、主机断电、对象垃圾回收、production、正式 RPO/RTO 或 AC。

2026-08-16 另行显式运行 `local-knowledge-index-crash-recovery-v1` 并 PASS。合成制度真实经过 Nginx/ClamAV/Worker 提取与双人审批；唯一 `knowledge_index_build` attempt 1 先完成 Qdrant upsert 和逐批 PostgreSQL 成员 Hash 提交，再因 `operation_logs` 排他锁阻塞于 `ready + log + Job finish` 最终事务。强杀前逐项重算 Embedding、payload 和 float32 向量摘要，确认 Qdrant 与 PostgreSQL 一致；SIGKILL 后索引仍为 `building/row_version=1`、consistency 和 ready 日志均为空，但物化 Hash 与 Qdrant 点保持相同聚合摘要。Maintenance attempt 2 以相同 Point ID 幂等 upsert，最终只有一个 `ready/row_version=2` 索引；客户端一致性投影、`failed/LEASE_EXPIRED → succeeded`、唯一 Outbox、严格两条生命周期日志和前后不变摘要均通过。第一次包装器运行因把 UUIDv5 知识库误限定为 UUIDv4而在故障注入前安全失败；第二次旧镜像运行暴露预崩溃校验读取被锁表的自阻塞，精确释放锁并清理后修复；最终结论只采用新 revision 全新栈的完整 PASS。专用容器、卷、网络、helper、运行时 Secret 和端口为零；该证据不证明 Qdrant 节点故障/容量、真实 Embedding Provider、自动重启、主机断电、production、正式 RPO/RTO 或 AC。

PostgreSQL authenticated HTTP 组合用例写入真实临时 Ed25519 PKCS8 私钥文件与公钥 keyring JSON，经 keyring loader 和 `create_app` lifespan 构造真实 AuthService、八条财务读链所用五个 QueryService 及 UserQueryService，且 `dependency_overrides` 为空；随后真实 login/JWT 得到 Access Token，由数据库重验 Actor 与 `financial.read`，依次穿过八个已冻结 Router、Service/Repository 读取同一 PostgreSQL。该 HTTP 层对精确重复候选只验证无 cursor 的 `ready + 空 items + next_cursor = null` 与 `private, no-store`；随后 logout 并确认后续 refresh 返回 401 `AUTH_REFRESH_EXPIRED`，再以 `system_admin` 重新登录，经 Actor/`users.manage` 穿过用户 Router/Service/Repository 读取同组织用户并验证六字段与 `private, no-store`。非空候选、三页 UUID keyset、self/deleted/voided/near-mismatch 排除与 archived 保留由同一 90 项目录中的独立真实 PostgreSQL Repository→Service 用例证明；strict cursor 由 unit/service 用例证明，不能提升为本次 authenticated HTTP 非空/cursor 证据。响应同时验证凭据 `Cache-Control: no-store` 及 Refresh Cookie 的 `Secure`、`HttpOnly`、`SameSite=strict`、受限 `Path`。应用 startup 在 Service 构造失败时释放已创建 engine 的修复有独立离线回归。该门禁仅以 ASGI `https://testserver` 模拟 HTTPS，不证明真实 TLS/Nginx、production secret mount/文件 ACL、浏览器用户列表或精确重复候选、部署或任何 AC。

用户列表 Repository 当前在一个普通 PostgreSQL `READ COMMITTED` Session 中依次执行用户页、`clock_timestamp()` 和固定角色查询，各 statement 不构成单一 MVCC 快照；本轮验证不把用户 `row_version` 外推为角色投影快照版本。其 canonical base64url cursor 可逆携带用户名；单元/API 测试验证 exact JSON、分页与脱敏错误，但 operation-log、代理/access log 和 production 遥测尚未实现或检查，不能据此声称原始 query/cursor 已在全部运行层完成日志脱敏。

另行显式运行的本地 `financial-read-browser-v1` Gate 已 PASS。test-only 同源宿主 `backend/tests/manual_financial_read_browser.py` 要求精确授权 token、1024～65535 的 loopback 端口、逐字 `http://127.0.0.1:{port}` origin、存在 `frontend/dist/index.html + assets` 以及通过安全 helper 验证的显式可丢弃 PostgreSQL marker；它生成临时 Ed25519 PKCS8 私钥和 public keyring，经生产 keyring loader 与 `create_app` lifespan 构造 AuthService 和此前七条财务读链所用五个 QueryService，并断言 `dependency_overrides=0`、六个 Service state 在 lifespan 前不存在且进入后为真实类型。真实浏览器路径 `login → dashboard → invoice list/detail → primary contract → contract list/detail + supplementary raw header → contract primary invoices → invoice detail` 对应此前七条已冻结只读 API，精确命中隔离 PostgreSQL 合成事实，0 alert、0 console error；深链 reload 保持 URL 与用户，logout 后 reload 保持匿名且无远端退出状态未确认提示。该路径没有导航 `/users` 或发票精确重复候选，不能作为两者的浏览器证据。运行时发现的默认原生 `fetch` receiver 缺失已改为 `globalThis.fetch.bind(globalThis)`，并由 `frontend/tests/api.test.ts` 回归覆盖；正常 `CTRL_BREAK` 后 OwnedSyntheticRows、临时 key 目录、宿主进程和专用容器复核均为 0。该结果仅证明 loopback HTTP 下的既有 test-only 财务读链，不证明浏览器用户列表/精确重复候选、TLS/Nginx、production secret mount/文件 ACL、部署、强杀/断电清理或任何 AC，也不改变默认离线 `BROWSER_E2E=NOT_RUN`。

宿主失败边界按 Uvicorn 0.52.1 实际行为记录：端口 bind failure 发生在 lifespan startup 之后，必须显式 shutdown 才会执行清理已播种合成事实的 lifespan finally；不得将该分支描述为 bind 前无副作用。

2026-08-12 的 OQ-09 局部门禁增加 quarantine pending intake、文件类型权限范围、严格 MinIO 配置与 quarantine-only Adapter，以及 `local-minio-v1` Compose/bootstrap：FILE 精确 10 文件 185 项、bootstrap 10 项、Backend unit 2072 项、Compose `config --quiet`、`LOCAL_MINIO_LAUNCHER_TESTS=PASS`、Ruff/format、mypy 91 sources 与 pip check 均通过。该段保留切片收口时的离线/静态 checkpoint；后续已另行显式运行 real local MinIO Adapter Gate 并 PASS：使用合成 PDF 和服务端固定对象键，真实执行 quarantine PUT，核验内容、长度、Content-Type 与 SHA metadata，执行 DELETE，并验证完整 PUT 后摘要错配及合成 post-commit exception 两个确定性精确补偿路径。该 Gate 仍不包含 FILE Router、PostgreSQL 文件事实/去重事务、Job/Worker、Scanner、通用迟到 timeout reconcile、进程崩溃清理、容量、production 或 AC-002/016；完整 MVP-VS-07 仍受 files/knowledge_bases Schema、FILE Router/幂等/错误合同、Job Handler Registry/Input Schema、GAP-052 与 Scanner Profile 阻断。

2026-08-13 另行显式运行 `local-minio-restart-persistence-v1`。初始实现的一次 PASS 不作为最终可重复性结论；随后一轮因 MinIO 返回固定策略 `Action/Resource` 集合的顺序不稳定而报 `APPLICATION_POLICY_DRIFT`，该失败轮只用于定位并修复集合比较规范化。修复后连续两轮真实 Gate 均 PASS：每轮 bootstrap 七个 Bucket 与 quarantine 权限，以原应用身份把固定合成 PDF 写入精确对象键，root 核验逐字节内容、大小、Content-Type 与 SHA-256 metadata；执行不带 `-v` 的 `compose down`、`up --pull never` 并确认新容器后，原 root/应用身份仍有效，root 再次核验对象，原应用身份删除并由 root 确认不存在。start/stop/wrapper 均 PASS；最终专用容器与网络为 0，managed/root/app/gate 环境变量均不存在，named volume 保留。该证据只证明单服务本地 named volume 上一次受控冷重启的固定对象持久性和同一应用身份连续性；不证明 FILE 数据库/Router/Job/Scanner、通用迟到 timeout reconcile、崩溃恢复、一般耐久性/容量、备份恢复、完整 Compose、TLS、production 或 AC-016。`DEP-001`、`FILE-001`、`TEST-001` 及所有 AC 状态均不升级。

2026-08-13 的 `handler-registry-loader-meta-v1` 聚焦测试 45 项通过，两路独立审查均为 `GO`。`backend/tests/fixtures/handler_registry/` 内 6 份 synthetic JSON 验证严格 UTF-8/JSON、严格整数、Registry Schema 全层封闭对象、Draft 2020-12、JCS/raw SHA-256、精确 Input/Summary bundle、稳定排序、retry scope→step、summary 引用、可解析的本地 `$ref/$dynamicRef` 与 zero retrieval。证据只覆盖调用方显式传入 artifact 的通用 meta Loader；没有 Settings/package data/callable/Job/Celery/runtime import。生产 Registry/Schema/Input/Summary/Handler artifact 保持 `PENDING / NOT GENERATED / NOT APPROVED`，Job/Worker runtime 保持 `NOT AUTHORIZED`，`BASE-006/FILE-001/TEST-001` 及所有 AC 状态均不升级。

同一 checkpoint 中，`risk_summary` 仅接受精确 `UUID` 风险标识并拒绝非 UUID/UUID 子类；表格文本保护对 `= + - @` 与 TAB/CR/LF 七类公式前缀均会中和且保持幂等。两文件聚焦套件合计 54 项通过；该结果没有运行数据库、风险生成、真实 XLSX writer、MinIO/下载或浏览器。

`report-xlsx-writer-v1` 另以锁定的 `XlsxWriter==3.2.9` 从精确 `ReportPayload` 生成固定 `Summary/Rules/Risks` 三个可见工作表。Writer 关闭字符串到公式、URL 和数字的自动转换，只写显式安全类型；严格重验 15 条规则、最多 15 条风险、hit/risk/summary 一致性、canonical UUID/枚举/有序去重引用、UTC 元数据、禁用 AI 降级事实，并限制单元格和全簿文本量、引用/降级原因数量、安全整数范围与 2 MiB 输出。聚焦验证同环境字节相等、ZIP/XML 可解析、Unicode 保留、七类公式前缀中和、非法 XML/超限失败关闭，且 OOXML 中没有公式、超链接、External 关系、宏、媒体或绘图；独立审查为 `GO`。字节相等不外推到跨 Python/XlsxWriter/操作系统/镜像。

`report-pdf-writer-v1` 以锁定的 `ReportLab==5.0.0` 从同一冻结 `ReportPayload` 生成固定 A4、逐页带非正式预览警示、页码、降级/过期状态与未解析引用说明的 PDF bytes；负载字符串的控制字符、双向控制符和换行分隔符以可见字面量呈现，防止换行伪造字段，最多 128 页/8 MiB。Writer 仅使用内嵌的 AOSP `android-15.0.0_r25` DroidSans Mono/Fallback TrueType 字体，渲染前按固定 SHA-256 校验；原始 NOTICE/README 和本地 `SOURCE.txt` 一并入包。离线 wheel 构建、安装和 5 个资源入包 PASS，上游两字体、NOTICE、README 四份原始文件逐字节/哈希一致；PDF unit 9 项、PDF+XLSX 相关聚焦 80 项通过。代表性 3 页 A4 制品经 Poppler 全页渲染检查、pypdf 与 pdfplumber 文本提取，以及内嵌 TrueType、`/ToUnicode`、无主动对象的静态检查通过，两路独立审查均为 `GO`。该证据只证明冻结负载到 PDF bytes 的内部离线 primitive，不是正式报告；数据库/`report_versions`、MinIO、下载 API/Auth、浏览器 Excel/PDF viewer、跨镜像、production、`REP-001/002` 和 AC-014 均为 `NOT_RUN` 或未实现，`REP-003` 保持 partial。

`CR-014-R3` governance contract 已通过 BOSS direct approval `item-572`，绑定 snapshot `11956 bytes / e5c00e6e47081d0e7418b48957d7895fe5a4705a1d5008256a7bb291d15b7cd9`；本地 receipt 仅为 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份 `1801 bytes / 7421b7913ed31b12ba37da52f2a74d3ac28d7eab01bfeea0efc5bcde2c9bd08b`。`CR-006-R4` 与 `CR-013-R3` source snapshots 已分别生成为 `8945 bytes / 159dd1588d9366c85e8aa1ffc5f9b910ea9319732a491785ce2fdf10d8096e8c`、`9496 bytes / 6cecc269e6517bb5b30d535350cdcb7e9aa2a00cf827199c2c2cb3789eae3d1a`；`CR006_R4_SOURCE_A1` 已 `RECEIVED / VALID`，其 create-only 本地 receipt 仅为 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份 `1807 bytes / d98c2556a07deb73b6683fdc8c325498a19815acb0034cbf2ac3f7905f2aab1c`，`source_message_text_sha256=69886a5974497a981f8649f8071f476487319fe2f0abdfc9636b3618ef331695`；`CR013_R3_SOURCE_A1` 已通过 platform event `item-684` `RECEIVED / VALID`，其 create-only 本地 receipt 仅为 `NON_AUTHORITATIVE_EVIDENCE_ONLY`，身份 `2607 bytes / 1454233d212979663e26e2699b924689cb081e893b456daa30530e81a778b9c8`，`source_message_text_sha256=572c102327f313c2a6e82ad582c4369f827e62c613c74ab14aecfe6b8971a37b`；两份 A1 source approvals 已闭合。CR-013-R3 blocklist A2 仍为 `NOT GENERATED / NOT RECEIVED`，原因是获准本地目录未找到合同精确 source/license bytes；resolver 可内嵌于 A1 已冻结的两条隔离单文件脚本并由 implementation-manifest → 十键 payload 传递绑定，无需新 resolver CR，现有两份 A1 保持有效；expected-post/inverse bundle 仍为 `NOT GENERATED`，joint authorization 仍为 `NOT RECEIVED`。临时 transport drafts `CR-014-R4/CR-006-R5/CR-013-R4` 已撤回。009 → 010 → 011 和 20/58 仍是后续条件成立时的候选 lineage；010/011 migration 仍为 `NOT GENERATED / NOT AUTHORIZED / NOT RUN`，runtime 与 AC 仍为 `NOT AUTHORIZED / NOT RUN`，不升级 `TEST-001` 或任何 AC。

### 7.2 S9 显式 PostgreSQL 16 current-head 门禁

该 runtime 门禁不进入默认离线编排；运行前必须由操作者显式启动本机 Docker，并预先缓存 `postgres:16-alpine`。脚本使用 `--pull never`，不会下载镜像；它先要求标签 inspect 返回唯一完整 SHA-256 ID，若 Docker 标签查询没有给出该形态，则只从本地 `image ls --no-trunc` 解析唯一候选，再以不可变 ID inspect 复核并把同一 ID 交给 `docker run`。成功输出包含 `POSTGRESQL_IMAGE_ID`。门禁只创建随机命名、带本项目专用 label 的一次性容器，使用随机凭据、1 GiB tmpfs 和随机 `127.0.0.1` 端口，不创建 volume，不读取 `.env`。只有容器 ID 与两个 label 均匹配时才会清理，无法证明身份或清理失败时整体失败且不输出 PASS；负向自测覆盖标签 inspect 异常 fallback、Secret 参数隔离、tmpfs 下限、身份清理与伪 PASS 防护。

```powershell
.\scripts\test-verify-postgresql-current-head.ps1
.\scripts\verify-postgresql-current-head.ps1
.\scripts\verify-postgresql-current-head.ps1 -Scope AI
```

`-Scope AI` 仍先执行 current-head 往返，再运行 `test_ai_call_audit_runtime.py`。2026-08-16 的 PostgreSQL 16.14 实跑输出 `POSTGRESQL_SCOPE=AI` 与 `POSTGRESQL_CURRENT_HEAD=PASS`，覆盖持久 reserve/complete、同 ID 重放/冲突、各预算维度、并发、事务回滚、乱序、合成消费者事务中断后的新实例恢复、未知版本/坏载荷隔离、未知结果补偿、迟到证据和安全摘要。提交结果未知另由纯单测在 Repository 已返回成功后让事务退出抛出 DBAPI 错误，验证 Service 返回 `unknown`。这些证据不包含真实 Provider、业务结果采用、Redis、公开 OPS-005、OS 级 SIGKILL、production 或任何正式 AC。

2026-08-16 另在全新 `finaudit-ai-audit-*` local Compose 项目显式运行 `scripts/verify-local-stack.ps1 -AiAuditCrashRecovery` 并 PASS。门禁在 Provider 关闭时停止 Maintenance，播种同一调用的 started/completed Outbox，以 `ai_call_logs` 排他锁确认唯一真实投影事务后 SIGKILL 精确容器并确认退出码 137；释放本次锁后，精确 PostgreSQL PID 消失，恢复前仍为两条 pending/attempt-0 Outbox 和零 `ai_call_logs`。再次启动同一 Maintenance 后，两条事件按序各投影一次，只形成一条 succeeded 日志；结构化日志精确两次投影结果且不含 event/operation UUID，测试事实、容器、卷、网络、运行时 Secret 和端口最终均为零。首轮诊断暴露“加锁后再播种”导致辅助校验自阻塞，第二轮证明 PostgreSQL 在锁等待期间不会仅因客户端进程死亡立刻清理后端，第三轮发现门禁日志标识与生产常量不一致；三项均修复并由聚焦测试锁定，只有最终完整 PASS 计入证据。该本地门禁不调用 Provider，不证明 AI-001/业务采用、Redis、公开 OPS-005、Docker 自动重启、主机断电、production 或任何正式 AC。

正向门禁要求服务端 major 精确为 16，在已标记可丢弃的本机测试库上连续两次执行完整迁移集成测试。历史证据（2026-08-09）覆盖当时 head `20260807_007` / 13/57 表，两轮均为 51/51；008/15 表证据保留为 CR-003-R3 的特权授权范围 Gate；009/18 表的 81/81、87/87、88/88、89/89 与 90/90 亦为较早 checkpoint。当前有效证据（2026-08-13）采用最新干净重跑：唯一 head `20260807_009` / 18/57 表运行于 PostgreSQL 16.14、`server_version_num=160014`，集成目录 91 项、连续两轮 91/91、脚本 exit 0、`POSTGRESQL_CURRENT_HEAD=PASS`，专用标签容器最终 0 残留，并将调用者的 `TEST_DATABASE_URL` 与显式破坏确认变量恢复为 unset。除 storage-schema、Auth Repository→Service→HTTP 组合及并发调用场景外，本轮以真实临时 Ed25519 keyfile → keyring loader → `create_app` lifespan、零 dependency override 构造 AuthService、九条财务读链所用五个 QueryService 与 UserQueryService；authenticated HTTP 路径覆盖 login/JWT → Actor/`financial.read` → 九 Router → Service/Repository → 同一 PostgreSQL，其中发票精确重复候选验证无 cursor 的 `ready + 空页` 与 `private, no-store`，两票点查验证同一语句内的精确身份投影。独立真实 PostgreSQL Repository→Service 用例另行验证非空候选、三页 UUID keyset、self/deleted/voided/near-mismatch 排除、archived 保留、三元组逐字段数据库等值和两票点查的自比较/漂移失败关闭；strict cursor 证据属于 unit/service。随后 authenticated 路径 logout 后再次 refresh 返回 401 `AUTH_REFRESH_EXPIRED`，并以 `system_admin` 再登录后覆盖 Actor/`users.manage` → 用户 Router/Service/Repository → 同组织用户列表，同时校验凭据响应与 Cookie 边界。它仍只是 ASGI HTTPS 模拟，不证明真实 TLS/Nginx、production secret mount/文件 ACL、浏览器用户列表、精确重复候选或两票点查、部署、容量/性能或 AC；精确候选与点查也不等于重复确认、真实性判断、风险或状态写入，普通 `READ COMMITTED` 的候选列表源锚点与候选查询不构成单一 MVCC 快照。本门禁仍不证明其余 39 表、完整 `BASE-005/AUTH-005`、用户写管理、operation-log、Worker、真实账号交付、Redis/Broker、Provider、production 或 P0 完成。

2026-08-14 的更新证据取代上段“当前”标签：唯一 head 为 `20260814_016`，ORM/runtime catalog 为 30/57 表；PostgreSQL 16.14、`server_version_num=160014` 的完整 `integration/database` 目录连续两轮各 122 项通过并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，专用容器最终零残留，`TEST_DATABASE_URL` 与破坏确认变量为 unset。该目录覆盖当前迁移、身份/操作日志、文件/文档处理、合同/补充协议/发票/关系写链及真实应用组合，但仍不证明剩余 27 表、知识/RAG、供应商、审核/报告、容量、TLS、部署、production 或任何正式 AC。

2026-08-14 的 `20260814_020` 证据再次覆盖上方 009/016 历史 checkpoint：当前 ORM/runtime catalog 为 57/57 表，完整 `integration/database` 目录已在两个独立隔离 PostgreSQL 16 运行中全部通过，覆盖供应商、Markdown/知识/RAG、审核与报告新增数据库链。官方双轮 wrapper 在本次工具窗口内超时，故只记录两次独立完整目录运行，不把 wrapper 记为通过；TLS、部署、production 与正式 AC 仍为 `NOT_RUN`。

2026-08-15 当前 wrapper 证据取代上一段的超时状态：`scripts/verify-postgresql-current-head.ps1` 在同一隔离 PostgreSQL 16.14（`server_version_num=160014`）上连续两轮完整通过当前 139 项 `integration/database` 目录，分别输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok` 与 `POSTGRESQL_CURRENT_HEAD=PASS`。专用标签容器最终为 0，`TEST_DATABASE_URL` 和破坏确认变量恢复为未设置；该结果不证明 TLS、性能、production 或正式 AC。

2026-08-15 的 `20260815_021` 证据覆盖上一段 020/139 项 checkpoint：先在 020 上以三项失败回归真实证明索引可直接 `active`、评测集可直接 `approved`、评测运行可直接 `passed`；新增前向迁移后封锁三条旁路。随后增加上传提示注入的数据库集成回归：合成 PDF 经真实文件摄入/Worker/Markdown/Chunk、制度审批、100 用例确定性正式评测与索引激活后，直接注入问题在检索前拒绝，命中含注入内容的普通问题在 PostgreSQL 授权终审拒绝；两条查询均持久化为 `refused/PROMPT_INJECTION_DETECTED`，无答案、引用、命中计数或哨兵/系统提示泄漏，操作日志只保存安全状态。当前 Retrieval 子集 8/8、完整 `integration/database` 目录 142 项连续两轮均通过并输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok` 与 `POSTGRESQL_CURRENT_HEAD=PASS`。一次全量预跑因审核迁移测试仍把失败后 head 硬编码为 020 而失败，修正为 `CURRENT_REVISION` 后的最终双轮才计为通过证据。该门禁使用隔离 PostgreSQL 16.14、内存向量 Adapter、确定性 Embedding/答案模型和合成 Scanner，只证明服务级数据库链；不构成 HTTP/浏览器、真实 Qdrant、正式 DAST、production migration、真实 Provider、UAT 或正式 AC。

2026-08-16 在同一 head 上加入 AI-005 provider-neutral 持久审计数据库回归后，完整 `integration/database` 目录增至 143 项。首次完整预跑暴露新用例遗留 append-only `ai_call_logs/outbox_events`，使后续迁移用例按设计拒绝降级非空审计运行时；修复仅在已验证的 disposable test database 内回收该用例的 15 个固定事件 ID 与 1 个固定组织 ID，不放宽生产触发器或降级保护。AI 专项 current-head roundtrip 通过；持久 Sink 适配加入后，`-Scope AI` 又真实证明首次 reserve 发放发送许可、重建 Sink 后同记录 replay 无许可，以及 completion 采用许可。随后修复 Docker 标签 inspect 偶发无法解析已缓存镜像的门禁误报：仅在本地解析并复核唯一完整镜像 ID，绝不 pull，`docker run` 固定使用该不可变 ID。当前 checkout 的 Full wrapper 已在 PostgreSQL 16.14（`server_version_num=160014`）同一次显式调用中连续两轮 143/143 通过，输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok`、`POSTGRESQL_IMAGE_ID=sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` 与 `POSTGRESQL_CURRENT_HEAD=PASS`；因此这次双轮包含持久 Sink 适配和门禁修复，而不是沿用较早证据。该证据仍不构成 Gateway、共享事务业务 Executor 采用、真实 Provider、production migration、UAT 或正式 AC。

2026-08-16 当前 `20260816_023` 的完整 `integration/database` 目录为 146 项。首次 Full 运行在发票读锁降级用例中暴露 022 未设置 `lock_timeout`，测试会话形成长期 `ALTER TABLE waiting`；精确中断测试进程并清理专用容器后，022 upgrade/downgrade 均补齐事务级 5 秒锁超时。第二次运行进一步暴露约束名被命名约定双前缀化，以及集成夹具仍期待默认 `CNY`；迁移改用 `op.f("ck_invoices_confirmed_currency_required")`，夹具改为无证据 `None`，不放宽“已确认发票币种非空”约束。最终 Full wrapper 在同一隔离 PostgreSQL 16.14（`server_version_num=160014`）中连续两轮 146/146 PASS，输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok`、同一不可变 `POSTGRESQL_IMAGE_ID` 与 `POSTGRESQL_CURRENT_HEAD=PASS`，专用 current-head 容器最终为 0。该证据覆盖数据库迁移、持久审计与业务事实原子采用，但不构成 production migration、正式性能、UAT 或任何正式 AC。

2026-08-17 当前 head 前进到 `20260817_024`，完整 `integration/database` 目录仍为 146 项。新增迁移回归以非空 v1 历史、pending AI log/未发布 AI Outbox、v1/v2 字段混用、CNY v2 投影和 v2 downgrade 数据分别验证兼容与失败关闭；AI Repository/OPS-005 回归还验证同业务操作混币种拒绝。Full wrapper 在同一锁定 PostgreSQL 16.14 镜像上连续两轮通过，输出两次 `status=ok` 与最终 `POSTGRESQL_CURRENT_HEAD=PASS`，专用容器清理为 0。该证据仍不构成 production migration、代表性质量、UAT 或任何正式 AC。

### 7.3 CR-011 Gate B Stage1 contract/offline 门禁

该门禁独立于默认离线编排和 S9 PostgreSQL 门禁，只消费已批准并同步的 CR-011-R4 contract 与现有固定制品，不读取 `.env`，不访问 socket、数据库、Redis、Broker 或 Provider：

```powershell
.\scripts\test-verify-cr011-gate-b-stage1.ps1
.\scripts\verify-cr011-gate-b-stage1.ps1
```

2026-08-10 的封板证据为 273/273、`CR011_ZERO_SOCKET_ATTEMPTS=0`、负向 runner PASS；覆盖 strict JSON parser、Policy companion、resolver、retry、response boundary、network policy、`AiCallEventV1` DTO/JCS/hash/replay 与内存 Fake Sink 行为。2026-08-11 accepted-source 加固后，Fake Sink 在 completed/late_completion 记录或签发 permit 前复用完整事件链校验，跨事件字段不一致返回 `CONFLICT`，且不记录冲突事件、不签发 permit；events 47 项与 sink 22 项合计 69 项，当前 Stage1 重跑为 275/275、负向 runner PASS、zero-socket attempts=0。runner 必须隔离 `PYTEST_ADDOPTS`/外部 plugin，拒绝 collect-only、`-k`、deselect、skip/xfail 和 executed≠collected 的伪 PASS，并恢复调用者环境。

该结果只能写为 `CR011_GATE_B_STAGE1=PASS`；它本身不能冒充下述 full Gate B。PostgreSQL、Docker、浏览器、Provider、remote、deploy、production 在本门禁中均为 `NOT_RUN`，Gate C persistent runtime、真实数据、Provider 和 production 仍为 `NOT_AUTHORIZED`。

### 7.4 CR-011 full Gate B 双引擎 contract/offline 门禁

该门禁独立于默认 `verify-local-offline`、Stage1 和 S9 PostgreSQL 门禁。正式顺序固定为“离线物化 → full Gate 负向自测 → full Gate wrapper”，不得跳步或调换：

```powershell
.\scripts\materialize-cr011-gate-b-dependencies.ps1
.\scripts\test-verify-cr011-gate-b.ps1
.\scripts\verify-cr011-gate-b.ps1
```

第一步不带 `-AcquireFromOfficialRegistries`，只从已取得且哈希锁定的本地缓存向隔离 test-only 目录物化依赖，并必须输出 `CR011_GATE_B_DEPENDENCY_ACQUISITION=OFFLINE_CACHE_ONLY` 与 `CR011_GATE_B_TEST_DEPENDENCIES=READY`；它不做全局安装。第二步是 full Gate 防伪/失败路径自测，必须输出 `CR011_GATE_B_NEGATIVE_CASES=11/11`。第三步才运行正式 wrapper；默认 `scripts/verify-local-offline.ps1` 不下载、不物化且不运行这条 full Gate。

2026-08-10 的 R4 封板历史证据为：Stage1 273/273 且独立负向 runner PASS；Node validator self-test PASS；full harness 27/27（2 个正例、25 个负例），精确负向向量 25/25，Python/Node Schema 调用各 20 次；两个 Draft 2020-12 引擎 2/2；zero-socket guard PASS 且 attempts=0；full Gate 防伪 11/11。2026-08-11 accepted-source 事件链加固后的当前 Stage1 重跑为 275/275、独立负向 runner PASS、zero-socket attempts=0；历史封板计数不被覆盖。上述结果只证明 R4 test-only contract/offline Gate B。`CR-011-R5/R6` 后续已 9/9 批准并同步，用于本地启动采用及 evidence-boundary；最小合成 Backend/Worker 启动路径已有局部离线证据，但 R6 exact locked-subject Gate C 仍 `BLOCKED BEFORE RUN / NOT RUN`。不得把 R4 Gate B 或局部启动测试冒充 R6 Gate C、依赖健康、持久运行时、Provider、production 或 AC。

### 7.5 AI-002 structured output offline repair

`backend/app/ai/structured_repair.py` 在既有严格结构化输出校验之上增加离线 repair orchestration。只有本地清理与严格 Pydantic 校验失败后才发起修复；最多两次，且始终绑定同一实际目标。repair 请求仅携带安全 JSON Pointer/问题类别，不携带失败值或 Provider 原文，并在共享 attempts、Token、费用与 hard deadline 下做最坏情况发送前预留。修复候选必须通过完整业务事实、权限和引用 validator；validator 仅接收 `deep=True` 的 `model_copy`，其原地修改和返回值都不能替换最终采用的严格解析对象。coroutine、同步 generator 或 async-generator validator 在 initial/repaired 两条采用路径均失败关闭且主体不执行，固定映射为 `INTERNAL_ERROR` 并清除 cause/context。仅精确的 `CitationValidationError/RiskExplanationValidationError` 原样透传；其他未知 validator 异常同样固定映射为 `INTERNAL_ERROR`，repair 调用异常固定映射为 `MODEL_UNAVAILABLE`。

当前 structured output 46 项与 structured repair 56 项合计 102 项通过；覆盖零修复、首/次修复成功、无第三次、同目标、安全 issue、预算/上下文/deadline 边界、initial/repaired 两条采用路径、同步 generator、coroutine 与 async-generator validator 失败关闭、敏感异常子类、引用验证，以及 validator 原地修改或伪造返回对象均不可替换严格结果。四个 AI 相关测试文件合计 241 项是另一个汇总口径（46 + 56 + 25 + 114），不得写成 AI-002 组合数。该范围不接触 socket、数据库、Redis、EventSink 或 Provider。业务 extraction Schema、Provider Adapter、持久化、Service/API 与 AC-003/005/011 均为 `NOT_RUN`，因此 `AI-002` 保持 `partial`。

## 8. TEST-002～TEST-007 边界

- `TEST-002`：领域、确定性规则、状态机和数据库约束单元测试。
- `TEST-003`：OpenAPI 中全部已实现 P0 API 的契约、错误格式、权限、幂等和关键冲突测试；数量由 OpenAPI 自动统计，不作为产品合同。
- `TEST-004`：核心业务链路的 Adapter、集成和 E2E 测试。
- `TEST-005`：AI 提取、Markdown、检索、RAG、引用、拒答和质量指标回归。
- `TEST-006`：认证授权、文件、隐私、日志、导出、Prompt Injection 和审计安全测试。
- `TEST-007`：性能、稳定性、故障注入、备份恢复与 Qdrant 重建测试。

历史 S1-S9 只建立了基础门禁；当前矩阵已把实际补充的浏览器、完整 local Compose、依赖故障和恢复演练分别记录到对应任务。`partial` 仍只表示已有局部证据，不等于完整任务或 AC。

2026-08-15 另行显式运行 `scripts/verify-local-stack.ps1 -WorkerCrashRecovery` 并 PASS：受管 helper 先暂停官方 ClamAV，让唯一 `file_process` Job 的 scan step 进入 `running`；门禁对精确归属 Worker 执行真实 SIGKILL 并确认退出码 137，再显式启动同一容器。Maintenance 在租约过期后把同一 Job 回收为 attempt 2，完成 `scan → parse → markdown`；正常 Worker 随后完成唯一的下游 `contract_extract`。客户端核对 `stored/clean/succeeded`、逐字节 DOCX 原件预览、ETag 和 13 字段未确认合同详情；数据库核对 attempt 1 的 scan step 为 `failed/LEASE_EXPIRED`、attempt 2 的三步均成功，以及提取 Job、文件合同绑定、13 个字段/证据和唯一追加日志。恢复后依赖 ready，精确标记的 helper、专用容器/卷/网络、运行时 Secret、测试镜像和端口监听最终均为 0。该门禁只证明 `file_process` 的跨进程强杀与显式受管重启，不证明 `unless-stopped` 自动重启、其他 Job 本体、主机断电、容量、production、RPO/RTO 或 AC。

2026-08-15 又在全新专用 local Compose 项目显式运行 `scripts/verify-local-stack.ps1 -ContractExtractionCrashRecovery` 并 PASS。门禁以 run-scoped PostgreSQL 会话持有 `contracts` 表锁，让正常完成 `scan → parse → markdown` 后创建的唯一 `contract_extract` Job 在 attempt 1 的 `extract` step 内阻塞；Job/Step 已提交为 `running` 时，合同、字段、文件关联和提取日志均为 0。脚本随后对精确归属 Worker 执行真实 SIGKILL，确认退出码 137，释放精确数据库锁，再次核对零事实后显式启动同一容器。Maintenance 在 60 秒租约和 15 秒宽限后记录 `claimed_and_succeeded`；最终数据库核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`，且仅有 1 个合同、1 个文件关联、13 个证据字段和 1 条追加式提取日志。客户端合同详情与上传时 SHA-256 对应的原件/ETag 一致；依赖重新 ready，专用容器、卷、网络、运行时 Secret、helper、测试镜像、临时状态和端口监听最终均为 0。该锁只构造测试阻塞，没有向生产 Executor 加入故障分支；本结果不证明 Docker 自动重启、`invoice_extract`、知识、审核、报告 Job、主机断电、production、正式 RPO/RTO 或任何 AC。

2026-08-16 在另一全新专用 local Compose 项目显式运行 `scripts/verify-local-stack.ps1 -InvoiceExtractionCrashRecovery` 并 PASS。门禁以 run-scoped PostgreSQL 会话持有 `invoices` 表锁，让唯一 `invoice_extract` Job 在 attempt 1 的 `extract` step 内阻塞；Job/Step 已提交为 `running` 后，对精确归属 Worker 执行真实 SIGKILL 并确认退出码 137。释放精确锁后，数据库核对发票、明细、文件关联和提取日志均为 0；Maintenance 在租约和宽限到期后记录同一 Job `claimed_and_succeeded`。最终核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`，且只有 1 个发票、1 条明细、1 个文件关联、13 个字段证据、1 条明细证据和 1 条追加式提取日志；客户端详情、证据与上传时 SHA-256 对应的原件/ETag 一致。依赖重新 ready，专用容器、卷、网络、运行时 Secret、helper、测试镜像、临时状态和端口监听最终均为 0。该锁只构造测试阻塞，没有向生产 Executor 加入故障分支；本结果不证明 Docker 自动重启、知识/审核/报告 Job、主机断电、production、正式 RPO/RTO 或任何 AC。

2026-08-16 又在全新专用 local Compose 项目显式运行 `scripts/verify-local-stack.ps1 -AuditExecutionCrashRecovery` 并 PASS。门禁播种 run-scoped 已确认合同/发票和 15 规则目录，由真实财务账号经 API 创建任务，再以专用 PostgreSQL 会话持有 `rule_executions` 表锁。Job/Step 已提交为 attempt 1 `running/evaluate` 且 Worker 的业务事务形成唯一未授予锁请求后，脚本真实 SIGKILL 精确 Worker 并确认退出码 137；它在注入锁仍持有时精确终止唯一孤儿等待后端，确认事务回滚和等待锁归零，再释放注入锁。恢复前任务、执行、快照和 Job 保留，而规则、风险及 `audits.execution_evaluated` 日志均为 0。Maintenance 随后记录同一 Job `claimed_and_succeeded`；客户端审核列表、任务详情和执行详情收敛到 `pending_finance_review`，固定 15 条规则与 `RULE-002/high`、`RULE-004/medium` 两条待复核风险。PostgreSQL 最终核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`、冻结快照 Hash、15 条唯一规则、2 条唯一风险和 1 条追加式执行日志。依赖重新 ready，专用容器、卷、网络、运行时 Secret、测试镜像和端口监听最终均为 0。该门禁不证明 Docker 自动重启、知识/报告 Job、主机断电、production、正式 RPO/RTO 或任何 AC。

2026-08-15 另行在专用 `finaudit-perf-*` 项目运行 `scripts/verify-local-stack.ps1 -PerformanceBaseline`，`local-performance-baseline-v2` 在全新栈三轮 PASS，并在同一栈以新 run 再完整重跑三轮 PASS。环境记录为 Docker Server 29.6.1、20 个 Docker CPU、8,223,633,408 bytes 内存、Worker `--concurrency=2`、AI Provider disabled、OCR/production NOT_RUN。首个最终 run 的每轮 20 次真实审核列表 nearest-rank P95 为 `9.337 / 8.465 / 8.973 ms`，每轮 20 次真实 TLS multipart 单文件上传受理 P95 为 `37.419 / 35.596 / 51.112 ms`，均分别低于 800 ms 与 3 s；60 个单文件 scan-only Job 全部 `stored/clean/succeeded`。每轮另提交恰好 20 件的默认最大批次及同键重放：受理为 `415.348 / 426.256 / 464.568 ms`，重放为 `144.390 / 148.449 / 177.125 ms`，60 个批量 scan-only Job 处理 P95 为 `752.009 / 763.451 / 835.733 ms`。随后 2 件批次稳定返回 1 成功/1 `FILE_FORMAT_NOT_SUPPORTED`，同键重放保持同一文件/Job；21 件批次在 `12.695 ms` 返回 413 `BATCH_LIMIT_EXCEEDED`。PostgreSQL 对该 run 精确确认 61 个批量文件、61 个唯一 `file_scan` Job、61 个 attempt-1 scan step 与 61 个 published Outbox，超限名称零落库。第二个 run 的最大批次受理为 `421.161 / 426.826 / 422.209 ms`，同样完整通过，从而验证 run-scoped 核验不会混入旧事实。每轮 3 个审核任务仍全部进入 `pending_finance_review`，数据库逐项确认唯一执行/Job/step/Outbox/snapshot/15 规则结果；Worker concurrency=2 只证明并发受理与无丢失/重复，不证明 3 个任务物理同时执行。审核输入由脚本直接播种，合成 PDF 很小，因此这些结果不构成上传→提取→确认、清晰发票 30 s、20 页合同 120 s、Top-5 2 s、RAG 15 s、OCR、真实 Provider、正式参考环境完整容量、production 或 AC 证据。两个专用项目的容器、卷、网络、运行时 Secret、helper、精确镜像与端口监听最终均为 0。

2026-08-15 另行在专用 `finaudit-security-*` 项目运行 `scripts/verify-local-stack.ps1 -SecurityBaseline`，`local-security-baseline-v1` PASS。真实 Nginx/Backend 路径覆盖 TLS 安全头、非法 Trace 上下文拒绝反射、Refresh Origin CSRF、五次失败锁定和防枚举、角色拒绝/存在性隐藏、篡改 Bearer、Trace 到操作日志映射、审计写入失败时业务事务回滚、操作日志 UPDATE/DELETE/TRUNCATE 不可变，以及合成密码哨兵不进入 Backend 日志；Compose 检查同时确认业务容器只读根文件系统、`no-new-privileges`、最小 capabilities 和唯一 loopback Frontend 端口。门禁还实际上传含攻击文本/canary 的 PDF，经官方 ClamAV、Worker、制度提交与独立审批、安全专用 100 条全 `no_answer` 合成集、float32 向量摘要一致性、真实 Qdrant 构建/激活后，验证 HTTP 直接问题预检与授权检索后的 PostgreSQL 终审均持久化安全的 `refused/PROMPT_INJECTION_DETECTED`，响应、审计摘要和业务容器日志无 canary。该过程先发现 Python float64 摘要与 Qdrant float32 持久化精度造成正常成员误报 `INDEX_MEMBER_DRIFT`，以及 strict Pydantic DTO 拒绝合法 JSON enum/array；两项均以失败回归和全新隔离栈重跑修复。随后在全新 `finaudit-security-browser4` 项目完成独立浏览器增量：因浏览器正确拒绝短期自签名 CA，未绕过警告或修改系统信任，而由受门禁保护、仅绑定 loopback 的 HTTP 测试中继把页面/API 请求通过 TLS 转发到原 Nginx。真实浏览器使用一次性审计角色登录，从工作台导航到问答页，自动加载已激活知识库，提交带本次 run ID 的直接注入问题并可见“明确拒答”及 `PROMPT_INJECTION_DETECTED`；控制台 warning/error 为 0。PostgreSQL 终审确认该浏览器用户只有一条精确问题记录，问题 SHA-256、Trace、`refused` 状态、空答案/引用、零命中和 `knowledge.qa_queried` 追加日志一致；依赖重新 ready、业务容器日志无 canary，专用容器/卷/网络/运行时 Secret/镜像与中继最终均为 0。P0 Schema 的单组织不变量仍使真实跨组织 IDOR 主体无法构造；本地浏览器增量不证明浏览器直接信任自签名或生产 CA。代表性检索质量、完整审计链、正式 DAST、镜像漏洞扫描、production 和 AC-015 仍为 `NOT_RUN`。

### 8.1.1 `CR-023/024` 当前全局密码与 HTTP Profile

2026-08-18 当前 checkout 已完成 `auth-password-v2` 与全局 HTTP 组合验证：5 个 code point 和 `123456/letmein/qwerty` 拒绝，安全 6 个 code point 接受；最大长度、UTF-8、NUL、Argon2id、锁定和一次性换密边界保留。持久 `finaudit-local` 与全新一次性栈都以 `http://localhost:<port>` 启动，Nginx 不含 SSL 指令、运行时不生成或挂载 TLS 文件、唯一主机绑定为 `127.0.0.1`；HTTP 返回 Frontend/依赖 200，HTTPS 握手失败。

一次性栈实际通过 5 字符和弱 6 字符创建拒绝、安全 6 字符用户创建、初始登录换密挑战、6 字符新密码、普通登录、`/auth/me`、Refresh 与 Logout。Refresh Cookie 保留 HttpOnly/SameSite=Strict/Auth Path 且在 HTTP 下无 `Secure`；显式 HTTPS Origin 的单元兼容性仍要求 `Secure`。同一栈的 HTTP multipart → ClamAV → Worker → PostgreSQL/MinIO 预览门禁通过后已精确清除容器、卷、运行时 Secret 和镜像。

BOSS 随后在持久 `finaudit-local` 亲自完成 `admin` 强制换密并重新登录。数据库确认 active、未锁定、失败数 0、force-change false 和普通活动会话 1；真实浏览器确认系统管理员工作台、用户管理读取和全局 6 字符提示，文件管理直接路由进入 `AUTH_FORBIDDEN`，页面 console warning/error 为 0。恢复密码内容已清零并删除。

YHBX 于 2026-08-18 明确签署 `Local MVP UAT通过`。`docs/testing/local-mvp-uat-2026-08-18.md` 固定本次 UAT 的本机 HTTP 范围、运行证据和排除项；该签署不升级 production、正式 AC 或任何未运行的质量/安全/容量门禁。

`CR-025` 随后按 BOSS“当前只要本地运行”的决定，把 AC-001、AC-002、AC-015、AC-016 调整为 Local MVP 口径。当前 HTTP 专用安全栈重新通过 `LOCAL_SECURITY_BASELINE=PASS`，直接浏览器 Prompt Injection 可见拒答、零 console warning/error，并由数据库与审计终审输出三项 PASS；当前权威备份又在独立 HTTP 项目恢复，核对 PostgreSQL 行数、MinIO 摘要、Redis/Qdrant 重建和 ClamAV 重载，再经普通停止与恢复后冷启动通过依赖、Frontend 200 和管理员 force-change false。安全栈、恢复栈、卷、运行时 Secret 与专用镜像均已清理。四项逐条结论记录于 `docs/testing/local-mvp-ac-acceptance-2026-08-18.md`，均为 Local MVP `ACCEPTED`；任务矩阵仍按工作包和其他 AC 保留 `partial`。

这些结果证明当前 loopback Local MVP 的功能可用性，不证明传输机密性或服务器身份认证。HTTP 不得开放局域网或公网；任何非 loopback 发布必须先恢复受信任 TLS 或在受信任反向代理终止 TLS，并重跑 Cookie、Origin、DAST 和发布验收。

2026-08-18 当前 Goal 收口重跑：完整 `verify-local-offline` 为 Backend `3062 passed / 142 skipped / 1 Starlette deprecation warning`、Ruff check/format 497 files、mypy 271 sources、pip check、Frontend typecheck、26 files/527 Vitest 与 147-module build 全部 PASS；PostgreSQL 16.14 current-head `20260817_024` Full wrapper 149 项连续两轮 PASS，Redis/Celery wrapper 4 项 PASS。全新隔离财务浏览器门禁 completion 返回 `accepted` 并输出 `FINANCIAL_LOOP_BROWSER_GATE=PASS`，受保护 manifest 精确核对 2 个文件/绑定和唯一合同、发票、供应商、主关系、任务、执行、ready 报告及 5 个纯角色 Actor。

同轮全新 `finaudit-security-goal1` HTTP 栈先暴露并修复两项门禁根因：Nginx `/metrics` 隐藏 Backend 重复 `X-Content-Type-Options` 后只保留一个 `nosniff`；运行验证器改为当前 Registry 的 `finaudit_process_uptime_seconds` / `finaudit_http_requests_in_flight` 名称，并用可观察的非 detach `docker exec` 触发 Worker PID 1，使 `unless-stopped` 的 RestartCount 实际增加。清理失败运行后从空栈重跑，`LOCAL_SECURITY_BASELINE=PASS` 覆盖 metrics、bounded logging、自动重启、ClamAV、制度双人审批、安全专用 100 条集、真实 Qdrant 与直接/间接 Prompt Injection；真实浏览器随后加载活动知识库并显示“明确拒答 / PROMPT_INJECTION_DETECTED”，console warning/error 为 0，PostgreSQL/审计终审三项及依赖/日志无 canary 均 PASS。专用栈、卷和受管测试 Secret 已清理；该合成证据仍不替代业务代表性 50/100 条质量、正式 DAST、production 或其余 AC。

同日 `CR-026` 在不改变 production 默认逐题语义的前提下，只为受保护 local/test benchmark runner 启用评测批次 20；批次 completion 与批次内逐题检索结果仍在评测运行的最终 PostgreSQL 事务采用。Provider 前完整离线门禁为 Backend `3061 passed / 142 skipped / 1 warning`、Ruff 497 files、mypy 271 sources、Frontend 527 tests/147 modules，PostgreSQL 16.14 current-head 完整目录连续两轮 PASS。真实运行使用当前批准百炼模型，索引 2 批与 50 条 3 批共 5 次请求，权威 usage 为 4971 input tokens、CNY 2486 microunits；49/50 通过、授权泄露 0，唯一失败为 10 个 no-answer 用例中的 1 个假阳性，`no_answer_false_positive_rate=0.1`。runner 按设计立即停止，100 条、激活和重试均未运行；Collection、专用 PostgreSQL/Qdrant 和确认环境变量残留为 0。

本轮 13 个 TEST/DEP 工作包的命令、退出结果、失败轮边界、Local MVP 新增能力和剩余停止条件统一记录于 `docs/testing/test-operations-evidence-2026-08-18.md`；该记录不得被解释为对未运行正式质量或 production 的状态升级。

同轮 `local-performance-baseline-v2` 首次运行虽数值 PASS，但机器 JSON 暴露旧 `transport=https-nginx-backend` 标签，与 CR-024 当前 HTTP 事实不一致；该轮只用于定位证据漂移。修复为受单测固定的 `http-nginx-backend` 后，在同一专用栈以新 run 重跑三轮，列表 P95 为 `10.607/10.647/10.978 ms`，上传受理 P95 为 `36.794/41.385/38.023 ms`，默认 20 件批次/重放、部分失败、21 件 413、数据库唯一事实和三审核任务无丢失/重复均 PASS。专用栈、卷、运行时 Secret 与测试镜像清理为 0；该结果仍不是清晰发票、20 页合同、Top-5/RAG、正式参考硬件或 production 容量证据。

## 9. 停止边界与后续完成条件

以下条件当前未完成，并构成完整 `TEST-001` 的停止边界：

1. 当前 57 表、核心业务、主要 Frontend、完整隔离财务浏览器闭环和五角色浏览器导航/禁止直达矩阵已交付；`file_process` scan、`contract_extract`、`invoice_extract`、`audit_execute`、`report_generate` 与 `knowledge_index_build` 本体的跨进程 SIGKILL、事务/跨系统回滚边界、显式受管重启/租约恢复及唯一事实收敛已验证，十个长期容器的 `unless-stopped` 与 Worker 自动重启也已实跑，仍需正式无障碍、主机断电和全部 AC 逐项证据。
2. `local-compose-v1` 已从受管空项目完成初始化、冷启动、dependency-ready、官方 ClamAV 文件 smoke 和 PostgreSQL/MinIO 隔离恢复；全局 HTTP Profile 缺少传输加密，任何局域网/公网发布前仍需恢复 TLS，并补齐目标主机、Secret Manager、Scanner/OCR、网络 allowlist、监控与发布 Profile。
3. 正式性能必须在记录硬件、代表性文档规模、模型和并发的参考环境连续执行三轮；当前只验证了上述 local Profile 的小型合成默认 20 件批次和其他子集 P95，不得外推为清晰发票、20 页合同、检索/RAG、正式完整容量、production 或资源建议。
4. 本地恢复不替代异地备份、加密密钥托管、保留期、调度/告警、恢复权限和正式 RPO/RTO 演练。
5. 真实 AI Provider、代表性 50/100 条业务审批检索集、生产模型审计与费用控制仍需独立授权环境；local 安全专用 100 条全 `no_answer` 合成集不替代这些条件。

这些条件完成并经运行时验证前，不得把 `TEST-001`、`TEST-007`、AC、UAT 或 production 标记为 `implemented/accepted`。
