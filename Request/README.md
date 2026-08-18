# FinAudit Agent 开发规格入口

本目录只保留当前开发需要读取的活跃规格。目标是让开发者先选一个可交付切片，再直接进入代码、测试和验收；不需要通读历史 CR、覆盖段或旧版九件套。

## 1. 先读什么

按以下顺序读取：

1. [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md)：产品范围、角色、业务流程、业务不变量和 AC。
2. [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md)：架构边界、模块职责和各类机器事实来源。
3. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)：当前可做、阻塞项、代码锚点和最小验证。

开始一个任务时，只读取与该切片相关的章节和代码事实源。旧版文档位于 `archive/legacy-v1/`，仅用于追溯，不参与解释当前行为。

## 2. 冲突时听谁的

优先级从高到低：

1. 用户在当前任务中的明确要求。
2. `PRODUCT_REQUIREMENTS.md` 中的产品结果、业务不变量和 AC。
3. 当前模块的机器事实源。
4. `TECHNICAL_SPEC.md` 的架构边界。
5. `IMPLEMENTATION_PLAN.md` 的顺序和状态。

机器事实源：

| 事实 | 唯一来源 |
|---|---|
| 已实现 HTTP 路由、请求/响应 Schema | FastAPI/Pydantic 生成的 OpenAPI |
| 错误码、业务枚举 | Backend domain registry；再生成 OpenAPI 和前端类型 |
| 当前物理数据库 | `backend/alembic/versions/` 的 accepted 单一 head |
| ORM 对齐 | SQLAlchemy 模型和 PostgreSQL 集成测试 |
| 前端页面与路由 | `frontend/src/router/` 及实际组件 |
| AI Schema、Prompt、Policy | 版本化机器文件和对应测试 |
| 环境变量 | `infra/env/.env.example`、`Settings` 与 Policy loader |
| 任务和验收证据 | `docs/testing/p0-traceability-matrix.csv` 及真实测试输出 |

Markdown 不再复制完整 DTO、表字段、枚举、错误目录、环境变量或测试证据。机器事实和说明不一致时，先确认产品结果没有变化，再修正文档；不要增加第二套兼容字段或覆盖层。

## 3. 一个切片如何直接开工

1. 从 `IMPLEMENTATION_PLAN.md` 选择一个 `READY` 切片。
2. 记录目标、明确非目标、关联 AC 和完成标准。
3. 打开该切片列出的代码锚点和机器事实源。
4. 如需新增已批准范围内的 API、Schema、状态或表，先更新对应机器事实源，再实现代码和测试。
5. 运行切片列出的最小验证；失败就修复，不用先建立新的治理文件。
6. 更新追踪矩阵中的状态和可复现证据。

只有切片依赖的产品语义确实不唯一时，才把该切片标记为 `BLOCKED`。阻塞必须指出具体问题、受影响范围和关闭条件；不得阻塞无关模块。

## 4. 什么时候需要 CR

只有以下变化需要一份简短 CR：

- 改变 P0/P1 产品范围或用户可见行为。
- 破坏已发布外部 API 兼容性。
- 改变持久化数据含义、状态转换、权限或安全边界。
- 改变正式验收阈值。

以下工作直接更新相应事实源和文档，不需要 CR：

- 修复实现与已批准需求的偏差。
- 在已批准范围内新增缺失代码、API、Schema、迁移或测试。
- 去重、重命名内部 helper、拆分文件、导航和示例修正。
- 更新任务顺序、估算、实现状态和验证证据。

CR 只记录“为什么改变”和批准结论。批准后必须合并进活跃规格或机器事实源；不得继续使用“本节覆盖下文”的长期补丁。

### 4.1 当前已同步的前向决定

2026-08-14，BOSS 批准 `recommended-forward-v1` 并授权同步 Request 后继续实施；决定记录为 `docs/change-requests/CR-018-recommended-forward-v1.md`。当前活跃规格已经直接吸收以下结论：

- 供应商统一税务投影、三态候选、精确复用、固定锁序和聚合纠错。
- quote/坐标缺失原因、禁 raw HTML 的 CommonMark/GFM table Profile、复杂表格安全制品和单一分块 Profile。
- P0 组织级知识权限、环境+Embedding 模型+维度 Collection、PG 允许集→Qdrant must-filter→PG 终审，以及 5/50/100 评测分级。
- 应用内静态 15 规则整批发布、审核执行/high 风险与正式报告状态机。

该决定只解除当时的实现歧义，不表示代码、外部依赖运行或 AC 已完成。2026-08-16 的真实 AI 与内部 metrics 前向决定见 `docs/change-requests/CR-019-real-ai-runtime-and-internal-metrics.md`；2026-08-17 的本机仓库 dotenv 默认加载边界记录于 `docs/change-requests/CR-020-repository-dotenv-default.md`；同日 `CR-021` 批准 local/test 百炼 Embedding Profile，`CR-022 / option-A / event-policy-v2 / USD-CNY-only / no-fx` 继续批准币种中立费用审计；`CR-023` 根据 BOSS 当前明确指令把所有环境的密码最小长度调整为 6，并保留弱密码黑名单、Argon2id 与锁定控制；`CR-024` 把内置应用入口全局改为 HTTP、移除 TLS 证书配置，并明确局域网/公网发布前必须重新恢复受信任 TLS；`CR-025` 将 AC-001/002/015/016 调整为当前 Local MVP 口径并由独立 AC 验收记录裁定。

### 4.2 当前交付快照

截至 2026-08-17，核心 Backend 链路已实现到 Alembic head `20260817_024`：57/57 张核心表、用户与 Break-glass、文件/财务/供应商、Celery 恢复、Markdown/Chunk/Qdrant/检索评测/RAG、审核/报告、工作台、依赖健康、OPS-005 和内部 metrics 均已有机器事实。`021` 封锁检索状态旁路，`022` 闭合未确认发票空币种，`023` 增加风险解释与报告草稿持久事实，`024` 增加向后兼容的 Event v2 USD/CNY 费用事实。主要 P0 Frontend 页面已接同源真实 API。

当前验证分层记录包括 Backend/Frontend 离线门禁、隔离 PostgreSQL、真实 Redis/Celery/Qdrant/MinIO/ClamAV、财务浏览器闭环、故障恢复和 local 安全/性能。`minimax-m3-local-v1` 又把真实 Chat Adapter、Gateway、结构修复、预算/网络策略、持久 EventSink 和共享事务采用接到合同/发票、RAG、风险解释与报告草稿；最新受限真实 smoke 覆盖五条生成链并核对全部 Provider attempt 的持久审计。`minimax-m3-bailian-qwen37-local-v2` 已把真实 Embedding Adapter、Event v2/CNY 预留与权威实际费用、OPS-005 和事务采用接入 Backend/Worker；唯一一次受限付费 smoke 以 2 条短合成输入验证 `43` input tokens、2×1024 维输出和 `22` CNY microunits 持久审计。代表性合同/发票与 50/100 条业务检索集、99% 合法率、正式 DAST、浏览器直接 CA 信任、production OCR/Scanner/TLS/Secret Manager、正式容量/恢复/监控告警、AC/UAT 和 production 均保持 `NOT_RUN` 或 `BLOCKED`。

本地 Docker Scout 1.23.1 镜像扫描已执行：Frontend 为 `0C/0H`；Backend 通过升级 `pypdf` 到 `6.14.2` 并移除运行时安装工具，由 `2C/6H` 降为 `2C/2H`，所有可修复 C/H 已清零。剩余 Bookworm Perl `2C/2H` 均标记 `not fixed`，所以 production 镜像与“严重/高危为 0”仍未验收。

AI-003 已完成合同/发票独立 Prompt、严格输出/证据校验、真实 Provider、EventSink 和业务采用，发票空币种语义也已闭合；但代表性准确率和结构合法率尚未正式运行，因此仍为 `partial`，不是 `ACCEPTED`。

## 5. 状态必须分开

| 状态 | 含义 |
|---|---|
| `DEFINED` | 产品要求已清楚，不代表有代码 |
| `READY` | 实现输入唯一，可以开始编码 |
| `BLOCKED` | 当前切片存在会改变结果的真实歧义 |
| `IMPLEMENTED` | 代码存在，不代表已验证 |
| `VERIFIED` | 指定测试或运行检查已通过 |
| `ACCEPTED` | 正式 AC/UAT 证据完整并获接受 |
| `NOT_RUN` | 没有运行证据，不得推定通过 |

文档存在、代码实现、测试通过和正式验收是四件事。任何汇报都必须分别说明。

## 6. 不再冻结的内容

以下数字和内部形态只作历史统计，不是产品合同：

- Markdown 文件数量。
- API、表、字段、错误码和工作包总数。
- helper、trigger、migration 文件或测试用例数量。
- 人日估算和签字角色数量。

保留的约束必须能解释用户结果、数据正确性、安全性、兼容性或可恢复性。等价的内部重构不得因为旧文档中的数量或文件名而被阻断。

## 7. 历史资料

- 旧版九份文档：`archive/legacy-v1/`
- 旧版字节和 SHA-256：`../docs/baseline-manifest.md`
- 当前活跃文档字节和 SHA-256：`../docs/request-manifest.md`
- 规格瘦身审计记录：`../docs/specification-simplification.md`

历史资料可以回答“当时为什么这样决定”，不能替代当前产品需求、代码事实或测试证据。
