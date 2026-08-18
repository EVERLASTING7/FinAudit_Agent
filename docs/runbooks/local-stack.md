# 完整本地栈运行手册

本手册只适用于单机开发与隔离验收。它提供可重复的 Backend、Frontend、Worker、PostgreSQL、Redis、MinIO、Qdrant、ClamAV 与 Nginx/HTTP 环境，但不等同于 production 部署。

## 1. 边界与前置

- 需要可用的 Docker Engine 与 PowerShell 7。
- ClamAV 官方镜像加载病毒库需要较多内存；Docker 资源不足时 Scanner 会保持未就绪，整个业务就绪探针返回 503。
- 入口只绑定 `127.0.0.1`。按 BOSS 批准的全局 HTTP Profile，内置入口不生成或配置 TLS 证书。
- AI Provider 默认关闭；合同、发票、知识问答与报告草稿继续使用当前本地确定性实现。
- ClamAV 只有 `scanner_updates` 网络可访问外部病毒库，其他数据服务保持内部网络。production 必须另行实施域名出口控制、代理、告警与定义版本审计。
- PostgreSQL 与 MinIO 是权威数据；Redis、Qdrant 和 ClamAV 定义数据可重建，不进入权威备份。

### 1.1 当前 BOSS Local MVP Profile

2026-08-17 起，当前交付目标固定为 BOSS Windows 本机上的 Local MVP；当前实际使用者 1 人，系统仍支持多账号和五角色，但不承诺多人并发容量：

- 使用 Docker Desktop 和本机现有资源，不形成正式容量基线。
- 唯一入口为 `http://localhost:8443`，只能监听 `127.0.0.1`；不开放局域网或公网。
- 使用 Nginx/HTTP 与本地 ClamAV；OCR 和 AI Provider 关闭，扫描件/纯图片不得声明 OCR 成功，AI 不可用时保留确定性规则并显示降级。
- Secret 位于仓库外的受管文件并通过只读挂载注入；真实密钥不得进入仓库。
- PostgreSQL/MinIO 使用本机数据卷；重要操作前运行本地备份。异地备份、保留期、正式 RPO/RTO、正式容量和 DAST 暂不进入本阶段承诺。
- YHBX 是本阶段 UAT 签署人与发布责任人；remote 和分支保护在公网部署前配置。

这个 Profile 的“可运行”要求不仅是容器启动：迁移、依赖健康、loopback 监听、Frontend 渲染和至少一个授权用户真实登录/授权读取都必须通过。production 与正式 AC 继续独立验收。

## 2. 首次启动

在仓库根目录运行；示例组织信息必须替换为本地测试身份，不要使用生产数据：

```powershell
.\scripts\start-local-stack.ps1 `
  -OrganizationName '本地测试组织' `
  -OrganizationUscc '91310000MA1K123456' `
  -OrganizationTaxNumber '91310000MA1K123456' `
  -AdminUsername 'local-admin' `
  -AdminDisplayName '本地管理员'
```

启动器会：

1. 构建固定基础镜像的 Backend/Frontend。
2. 在 `%LOCALAPPDATA%\FinAuditAgent\runtime\<project>` 生成运行时 Secret 与 JWT Key；HTTP Profile 不生成 TLS 证书。
3. 执行 Alembic、七 Bucket、Qdrant Collection 和 first-org/admin 幂等初始化。
4. 等待 `/health` 与 `/health/dependencies`，只有全部必需依赖为 `ok` 才返回 PASS。

脚本只输出初始密码文件路径，不打印密码。首次登录必须立即完成强制改密。该文件只保存初始化密码；用户换密后不会被改写，也不能被当作当前密码。再次以同一项目名启动时，组织与管理员身份参数必须逐字一致；不同值会失败关闭。若当前密码遗失，不得直接编辑数据库密码 Hash；必须由 BOSS 明确授权受审计的本地恢复操作，并在恢复后撤销旧会话、强制再次换密。

## 3. 健康与文件链验证

默认入口为 `http://localhost:8443`。可用以下命令检查本地就绪响应：

```powershell
curl.exe http://localhost:8443/health
curl.exe http://localhost:8443/health/dependencies
```

`/health` 仅表示 Backend 进程存活。`/health/dependencies` 才检查 PostgreSQL、Redis、MinIO、Qdrant、Worker 与 ClamAV；AI 在当前 Profile 中明确为 `disabled`。

以下只读门禁进一步检查十个长期容器均为运行态、使用 `unless-stopped` 和 5×10 MiB 的 Docker `local` 日志轮转，并以受管凭据验证 `/metrics` 的 401/200 双路径；凭据和指标正文不会输出：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -OperationsReadiness
```

成功固定输出 `LOCAL_OPERATIONS_READINESS=PASS`。它适合日常巡检，但不替代本节后续业务 smoke、备份恢复、自动重启故障注入或 production 监控平台。

`scripts/smoke_local_file_upload.py` 由隔离容器运行，读取挂载的初始密码文件但不会回显密码。它验证 HTTP/Nginx multipart、最小业务角色、真实 ClamAV INSTREAM、Celery Worker、PostgreSQL 文件终态与 MinIO 原件预览。该脚本面向验收自动化，不作为生产账号初始化工具。

通过受管包装器运行健康门禁与文件烟测：

```powershell
.\scripts\verify-local-stack.ps1 -ProjectName 'finaudit-local' -FileUpload
```

### 3.1 Worker 崩溃恢复故障注入

只在可丢弃的本地项目上运行以下门禁；它会短暂停止扫描处理，并真实终止 Worker 进程：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -WorkerCrashRecovery
```

门禁先验证完整依赖就绪，再暂停精确归属的 ClamAV，使唯一 `file_process` Job 的 `scan` step 保持 `running`；随后对精确归属 Worker 执行 SIGKILL，确认退出码 137，并显式启动同一容器。Maintenance 必须在租约过期后把同一 Job 回收为 attempt 2，并继续完成 `scan → parse → markdown`；随后正常 Worker 还必须完成唯一的下游 `contract_extract`。客户端核对文件终态、逐字节 DOCX 预览、ETag 和提取后的合同详情，数据库核对 `LEASE_EXPIRED`、两次 attempt 的完整 step 历史、13 个合同字段、文件绑定及追加式提取日志；最后再次检查依赖健康。脚本在成功或失败时都会按精确身份恢复 Scanner，并清理 helper 与临时状态。

这是破坏性的本地受管故障注入，运行期间不要并行提交真实工作。Docker 对手工 `docker kill` 视作显式停止，因此此门禁验证的是“`file_process` 在 scan 中 SIGKILL 后显式受管重启与应用租约恢复”，不是 `unless-stopped` 自动重启；下游 `contract_extract` 只验证恢复后正常执行，其自身未被强杀。其他业务 Job 的独立本体门禁见下文；本门禁不证明主机断电、production 或正式 RPO/RTO。

### 3.2 合同提取本体崩溃恢复故障注入

只在可丢弃且没有并行业务写入的本地项目运行：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -ContractExtractionCrashRecovery
```

门禁以专用 PostgreSQL 会话持有 `contracts` 表锁，使正常完成 `scan → parse → markdown` 后创建的唯一 `contract_extract` Job 在 attempt 1 的 `extract` step 内稳定阻塞。脚本确认 Job/Step 已提交为 `running` 且合同、字段、文件关联和提取日志仍为 0 后，对精确归属 Worker 执行 SIGKILL 并确认退出码 137；随后释放精确归属锁、再次核对零业务事实，并显式启动同一 Worker。Maintenance 必须在 60 秒租约和 15 秒宽限后把同一 Job 回收为 attempt 2。客户端核对恢复后的 13 字段合同详情及上传时 SHA-256 对应的原件/ETag；数据库核对 attempt 1 为 `failed/LEASE_EXPIRED`、attempt 2 为 `succeeded`，且最终只能有 1 个合同、1 个文件关联、13 个证据字段和 1 条追加式提取日志。

该门禁使用数据库锁构造可重复阻塞，不向生产 Executor 添加故障测试分支。成功或失败都会按 run-scoped 应用名释放锁、恢复精确 Worker 并删除临时状态。它只证明本地合成 DOCX 的 `contract_extract` 跨进程强杀与租约恢复，不证明 Docker 自动重启、`invoice_extract`、知识、审核、报告 Job、主机断电、production 或正式 RPO/RTO。

### 3.3 发票提取本体崩溃恢复故障注入

合同与发票门禁必须分开运行。只在可丢弃且没有并行业务写入的本地项目运行：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -InvoiceExtractionCrashRecovery
```

门禁以专用 PostgreSQL 会话持有 `invoices` 表锁，使正常完成 `scan → parse → markdown` 后创建的唯一 `invoice_extract` Job 在 attempt 1 的 `extract` step 内稳定阻塞。脚本确认 Job/Step 已提交为 `running`，再对精确归属 Worker 执行 SIGKILL 并确认退出码 137；释放锁后，数据库必须仍为零发票、零明细、零文件关联和零提取日志。Maintenance 在 60 秒租约和 15 秒宽限后把同一 Job 回收为 attempt 2。客户端核对恢复后的精确发票详情、13 个字段证据、1 条明细证据及上传时 SHA-256 对应的原件/ETag；数据库核对 attempt 1 为 `failed/LEASE_EXPIRED`、attempt 2 为 `succeeded`，且最终只能有 1 个发票、1 条明细、1 个文件关联和 1 条追加式提取日志。

该门禁与合同门禁复用相同的受管编排，但使用独立 Python 验证器与 run-scoped 锁身份；它同样不向生产 Executor 添加故障测试分支。成功或失败都会释放精确锁、恢复精确 Worker 并删除临时状态。它只证明本地合成 DOCX 的 `invoice_extract` 跨进程强杀、事务回滚和租约恢复，不证明 Docker 自动重启、知识/审核/报告 Job、主机断电、production 或正式 RPO/RTO。

### 3.4 审核执行本体崩溃恢复故障注入

只在可丢弃且没有并行业务写入的本地项目运行：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -AuditExecutionCrashRecovery
```

门禁先播种 run-scoped 已确认合同、发票和完整 15 规则目录，再由真实财务角色通过 `/api/v1/audit-tasks` 创建审核任务。专用 PostgreSQL 会话持有 `rule_executions` 表锁；脚本同时确认 Job/Step 已提交为 attempt 1 `running/evaluate`，且 Worker 在业务事务内形成唯一未授予锁请求，随后才对精确归属 Worker 执行 SIGKILL 并确认退出码 137。由于 PostgreSQL 的阻塞后端不会保证立刻感知客户端进程消失，门禁在仍持有注入锁时精确终止唯一孤儿等待后端，确认事务回滚与等待锁归零，再释放注入锁。恢复前数据库必须保留任务、执行、不可变快照和运行中 Job，但规则结果、风险和 `audits.execution_evaluated` 日志全部为 0。

Maintenance 在租约和宽限到期后把同一 Job 回收为 attempt 2。客户端核对审核列表、任务详情和执行详情均收敛到 `pending_finance_review`，规则固定为 `RULE-001～RULE-015`，本门禁合成事实只产生 `RULE-002/high` 与 `RULE-004/medium` 两条待复核风险。数据库再核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`、15 条唯一规则、2 条唯一风险、单条追加式执行日志和冻结快照 Hash；依赖必须重新 ready。

该门禁没有向生产 Executor 增加故障分支，也不会把测试锁或强杀冒充 Docker 自动重启。它只证明 local PostgreSQL 事务中的 `audit_execute` 本体强杀、孤儿会话回滚和租约恢复；知识索引与报告生成见下述独立门禁。所有这些本地证据仍不证明主机断电、production、正式 RPO/RTO 或任何 AC。

### 3.5 报告生成本体崩溃恢复故障注入

只在可丢弃且没有并行业务写入的本地项目运行：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -ReportGenerationCrashRecovery
```

门禁先创建并执行真实审核任务，使用相互独立的财务与审计角色完成 medium/high 风险复核，再在 Worker 停止时排队唯一 `report_generate` Job。专用 PostgreSQL 会话持有 `operation_logs` 排他锁，使 attempt 1 在确定性 PDF/XLSX 已逐字节写入 MinIO、但报告对象键、摘要、大小和 ready 状态尚未提交数据库时阻塞于最终事务。脚本核对两个对象的 SHA-256 与大小后，对精确归属 Worker 执行 SIGKILL 并确认退出码 137，终止唯一孤儿数据库等待后端并释放注入锁。恢复前报告仍为 `generating`，全部数据库制品定位字段和 `reports.generated` 日志为零，但两个孤儿对象必须保持原字节可读。

Maintenance 在租约与宽限到期后以 attempt 2 重放；确定性 Writer 必须生成相同 PDF/XLSX，并把唯一报告收敛为 `ready`。客户端核对报告详情、列表、PDF inline 预览、XLSX 下载、Content-Type、ETag、Content-Disposition 与单一 `X-Content-Type-Options`；数据库核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`、唯一 published Outbox、唯一生成日志及精确 MinIO locator/hash/size。该门禁同时修复并回归了 Nginx 与 Backend 重复输出 `X-Content-Type-Options` 的问题：API 代理隐藏上游值后由边缘统一输出一次。

该门禁不向生产 Executor 增加故障分支，成功或失败都会释放精确锁并恢复同一 Worker。它只证明 local 合成审核报告在 MinIO/PostgreSQL 边界的强杀、孤儿对象保留与幂等恢复，不证明 Docker 自动重启、主机断电、对象垃圾回收、production、正式 RPO/RTO 或任何 AC。

### 3.6 知识索引本体崩溃恢复故障注入

只在可丢弃且没有并行业务写入的本地项目运行：

```powershell
.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-local' `
  -KnowledgeIndexCrashRecovery
```

门禁创建 run-scoped 知识库，上传含安全测试文本的合成 PDF，经真实 ClamAV/Worker 提取后由两个独立审核角色完成制度提交与批准。脚本停止 Worker 后排队唯一 `knowledge_index_build` Job，再持有 `operation_logs` 排他锁；Worker 必须先把确定性向量写入真实 Qdrant，并逐批提交 PostgreSQL `document_index_items` 的 vector/payload Hash，最后在同一数据库事务中尝试把索引改为 `ready`、追加日志并完成 Job，此时稳定阻塞。门禁逐项重算 Embedding、最小 payload 和 float32 向量摘要，确认 Qdrant 点与 PostgreSQL 物化 Hash 完全一致后，对精确归属 Worker 执行 SIGKILL 并确认退出码 137。

释放锁后，索引必须仍为 `building/row_version=1`、consistency 为空、`knowledge.index_ready` 日志为零，而已提交的物化 Hash 和 Qdrant 点保持同一聚合摘要。Maintenance attempt 2 以相同 Point ID 幂等 upsert，并接受完全相同的既有 Hash，最终只生成一个 `ready/row_version=2` 索引。客户端核对一致性四字段和成功 Job；数据库核对 attempt 1 `failed/LEASE_EXPIRED`、attempt 2 `succeeded`、唯一 published Outbox、严格两条索引生命周期日志、唯一成员事实及恢复前后不变的 Qdrant/PG 摘要。

该门禁不证明 Qdrant 全库容量、节点重启/丢盘、Collection 迁移、真实 Embedding Provider、Docker 自动重启、主机断电、production、正式 RPO/RTO 或任何 AC。

### 3.6.1 AI 调用持久审计 PostgreSQL 门禁

该门禁只创建带本项目专用标签、随机凭据、随机 loopback 端口和 tmpfs 的可丢弃 PostgreSQL 16 容器；不读取 `.env`，不连接 Provider、Redis 或其他网络服务：

```powershell
.\scripts\verify-postgresql-current-head.ps1 -Scope AI
```

脚本先执行 current-head 往返，再验证 provider-neutral AI-005 的 durable reserve/complete、同 ID 重放与冲突、并发尝试和 Token/费用/deadline 上限、业务事务回滚、Outbox 乱序等待、投影事务中断后的新服务实例恢复、未知版本/坏载荷 dead-letter、`outcome_unknown/late_completion` 和内部安全摘要。成功必须同时输出 `POSTGRESQL_SCOPE=AI` 与 `POSTGRESQL_CURRENT_HEAD=PASS`；成功或失败都会按精确容器身份清理。

消费者故障使用 PostgreSQL 投影事务内的合成异常，证明 claim、日志写入和 published 标记整体回滚后可重放；它不是 OS 级 SIGKILL。该门禁也不证明 AI-001/业务采用接线、公共 OPS-005 权限、真实 Provider、Redis 限流/熔断、production 或任何正式 AC。

### 3.6.2 AI 审计投影器 OS 级崩溃恢复门禁

该门禁只允许专用 `finaudit-ai-audit-*` local Compose 项目，并要求 `AI_PROVIDER_CALLS_ENABLED=false`。先创建可清除的独立栈，再运行故障注入；结束后按精确项目名清除该栈：

```powershell
.\scripts\start-local-stack.ps1 `
  -OrganizationName '本地 AI 审计故障测试组织' `
  -OrganizationUscc '91310000AIAUDIT001' `
  -OrganizationTaxNumber 'LOCAL-AI-AUDIT-001' `
  -AdminUsername 'ai-audit-admin' `
  -AdminDisplayName '本地 AI 审计管理员' `
  -ProjectName 'finaudit-ai-audit-local1' `
  -HttpPort 9445 `
  -ImageRevision 'ai-audit-local1'

.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-ai-audit-local1' `
  -AiAuditCrashRecovery

.\scripts\stop-local-stack.ps1 `
  -ProjectName 'finaudit-ai-audit-local1' `
  -Purge
```

脚本停止精确归属的 Maintenance，播种同一 AI 调用的 provider-neutral started/completed Outbox，再持有 `ai_call_logs` 排他锁并启动同一容器。唯一投影事务形成未授予锁请求后，脚本记录其 PostgreSQL PID，对 Maintenance 执行 SIGKILL 并确认退出码 137；随后只释放本次门禁持有的锁，等待该 PID 消失，证明服务端已观察到断连并回滚事务。恢复前必须仍有两条 pending/attempt-0 Outbox 且没有 `ai_call_logs`；再次启动同一容器后，两条事件必须按序各投影一次，只形成一条 succeeded 审计日志。结构化日志必须恰有两次安全投影结果且不得包含事件或业务操作 UUID；最后删除精确 run-scoped 事实、确认零残留并重新通过完整依赖健康检查。

成功或失败路径都会释放本门禁的唯一数据库锁、按确定性事件身份清理测试事实并恢复同一 Maintenance 容器。该结果只证明 local Compose 中 AI-005 投影器的 OS 级强杀、数据库事务回滚和受管重启；它不调用 Provider，也不证明 AI-001/业务采用、Redis 限流/熔断、公共 OPS-005、Docker 自动重启、主机断电、production 或任何正式 AC。

### 3.7 本地三轮性能基线

性能门禁会创建财务复核账号、合成合同/发票，并在每个 run 中创建 60 个单文件上传、3 组各 20 件的默认最大批次、1 个部分失败批次的有效文件和 9 个审核任务；同键重放不得新增事实，21 件超限批次必须整体返回 413 且零数据库副作用。门禁只能在独立且可清除的 `finaudit-perf-*` 项目运行；包装器会拒绝默认项目名，避免污染日常本地数据。先按第 2 节启动独立项目，并显式使用不同端口和镜像 revision：

```powershell
.\scripts\start-local-stack.ps1 `
  -OrganizationName '本地性能测试组织' `
  -OrganizationUscc '91310000PERF000001' `
  -OrganizationTaxNumber 'LOCALPERF000001' `
  -AdminUsername 'perf-admin' `
  -AdminDisplayName '本地性能管理员' `
  -ProjectName 'finaudit-perf-local1' `
  -HttpPort 9444 `
  -ImageRevision 'perf-local1'

.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-perf-local1' `
  -PerformanceBaseline
```

门禁固定连续运行 3 轮：每轮 20 次审核列表、20 次单文件上传受理、1 次 20 件最大批次及其同键重放，以及 3 个同时提交的审核任务。列表与单文件上传受理分别以 nearest-rank P95 对照 800 ms、3 s 阈值；每个最大批次请求及其重放也必须各自在 3 s 内受理。三轮后再运行一次 1 成功/1 格式拒绝的 207 部分失败批次及重放，并提交 21 件超限批次。所有受理的 scan-only Job 必须成功；PostgreSQL 必须对当前 run 精确存在 61 个批量文件、61 个唯一 Job、61 个 attempt-1 scan step 和 61 个 published Outbox，且超限名称零落库。审核数据库必须存在唯一 task/execution/job、成功 step、published Outbox、snapshot 和 15 条规则结果。Worker 当前并发为 2，因此三任务证据是并发受理与无丢失/重复，不是三个任务物理同时执行。

完成后必须按精确项目名清除测试卷和运行时 Secret：

```powershell
.\scripts\stop-local-stack.ps1 `
  -ProjectName 'finaudit-perf-local1' `
  -Purge
```

该门禁不读取或输出 Secret 值。它只覆盖小型合成 PDF 在 local ClamAV scan-only 下的默认 20 件批量受理/重放/逐项失败/超限边界，以及审核列表与数据库播种事实后的审核 Worker；它不是正式参考环境完整容量证明。清晰发票、20 页合同、Top-5、RAG、OCR、真实 Provider、production 和 AC 均未运行。

### 3.8 本地安全基线

安全门禁会创建合成账号与合同、执行锁定和权限负例，并短暂安装一个只针对合成 `users.created` 日志的数据库失败触发器；只能在独立且可清除的 `finaudit-security-*` 项目运行。包装器会拒绝其他项目名，并在成功或失败时移除该触发器：

```powershell
.\scripts\start-local-stack.ps1 `
  -OrganizationName '本地安全测试组织' `
  -OrganizationUscc '91310000SEC0000001' `
  -OrganizationTaxNumber 'LOCALSEC000001' `
  -AdminUsername 'security-admin' `
  -AdminDisplayName '本地安全管理员' `
  -ProjectName 'finaudit-security-local1' `
  -HttpPort 9445 `
  -ImageRevision 'security-local1'

.\scripts\verify-local-stack.ps1 `
  -ProjectName 'finaudit-security-local1' `
  -SecurityBaseline
```

门禁验证 loopback HTTP 与安全响应头、非法 Trace 上下文不反射、Refresh Origin CSRF、五次失败锁定与防枚举、角色拒绝和存在性隐藏、篡改 Bearer、Trace 到操作日志映射、审计写入失败时业务事务回滚、操作日志 UPDATE/DELETE/TRUNCATE 不可变，以及合成密码哨兵不进入 Backend 日志。它还上传含攻击文本和 canary 的 PDF，经官方 ClamAV、Worker、制度提交/独立审批、安全专用 100 条全 `no_answer` 合成集、float32 向量摘要一致性和真实 Qdrant 索引激活后，分别验证直接注入问题在检索前拒绝、普通问题命中不可信制度正文后由 PostgreSQL 终审拒绝；两条 HTTP 响应和持久化审计均不得包含答案、引用、命中计数或 canary。该合成集只服务于安全链路，不代表 50/100 条业务检索质量集。

门禁同时核对业务容器只读根文件系统、`no-new-privileges`、Backend/Worker/Dispatcher/Maintenance 丢弃全部 capabilities，Frontend/Nginx 只保留官方镜像启动所需的 `CHOWN/SETGID/SETUID`，且主机仅暴露 `127.0.0.1` 的 Frontend HTTP 端口。十个长期服务还必须使用 `unless-stopped` 与 Docker `local` 日志驱动，每个容器最多保留 5 个 10 MiB 日志文件；该上限防止本地 stdout/stderr 无界占盘，但不是业务操作日志、合规留存或集中日志平台。门禁会用可丢弃受管凭据验证 `/metrics` 的 401/200 双路径和固定低基数指标，再让 Worker 的 PID 1 自行异常退出并确认同一容器的 `RestartCount` 增加、自动恢复和依赖重新 ready；不读取或输出凭据。

若不执行下一节浏览器增量，完成后清除专用栈；若要执行下一节，则暂不清除，待浏览器数据库终审后再运行同一命令：

```powershell
.\scripts\stop-local-stack.ps1 `
  -ProjectName 'finaudit-security-local1' `
  -Purge
```

P0 Schema 强制单组织，因此本门禁不能构造真实跨组织 IDOR 主体；完整审计链、正式 DAST、镜像漏洞扫描、production 与 AC-015 仍不在本门禁证据范围内。`-SecurityBaseline` 本身只完成非浏览器阶段，所以仍会先输出 `LOCAL_SECURITY_PROMPT_INJECTION_HTTP_QDRANT=PASS` 与 `LOCAL_SECURITY_PROMPT_INJECTION_BROWSER=NOT_RUN`；同时输出一次性的 browser origin、username、run ID 和 `LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_READY=PASS`，供下述独立浏览器阶段使用。

### 3.9 本地浏览器 Prompt Injection 增量

保持上一节专用栈运行，浏览器直接打开 `-SecurityBaseline` 输出的 loopback HTTP origin。使用门禁输出的合成 username 登录；口令只能使用 `scripts/smoke_local_security.py` 中明确标记为 public/disposable 的 `_prompt_browser_password()` 返回值，禁止读取或输出 bootstrap Secret。进入“AI 问答”，提交由 `_prompt_browser_question(run_id)` 生成的直接注入问题，必须同时看到：

- 当前活动知识库由 Backend 成功加载；
- “明确拒答”和 `PROMPT_INJECTION_DETECTED`；
- 回答、引用和检索命中数均为空/零；
- 浏览器 warning/error 为零。

完成页面动作后，以基线输出的 run ID 运行数据库终审；下面命令中的项目名、管理员名和 run ID 必须与本次专用栈一致：

```powershell
$runtime = Join-Path `
  ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) `
  'FinAuditAgent\runtime\finaudit-security-local1'

docker compose `
  --project-name finaudit-security-local1 `
  --env-file (Join-Path $runtime 'compose.env') `
  --file .\infra\compose\compose.local.yml `
  exec --no-TTY `
  --env FINAUDIT_SECURITY_RUN_ID='<本次 32 位 run ID>' `
  --env BOOTSTRAP_ADMIN_USERNAME='security-admin' `
  maintenance python /app/scripts/smoke_local_security.py `
  prompt-injection-browser-database
```

只有数据库命令同时输出 `LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_DATABASE_GATE=PASS`、`LOCAL_SECURITY_PROMPT_INJECTION_BROWSER_AUDIT_GATE=PASS` 和 `LOCAL_SECURITY_PROMPT_INJECTION_BROWSER=PASS`，且再次检查依赖 ready 与业务容器日志无 canary 后，才可记录本地浏览器增量通过。该结果不提供传输加密证据，也不证明真实 Provider、正式 DAST、AC-015、UAT 或 production。完成后按上一节执行专用栈 `-Purge`。

## 4. 停止与清除

普通停止保留数据卷和运行时 Secret：

```powershell
.\scripts\stop-local-stack.ps1
```

再次执行第 2 节的启动命令可冷启动同一数据。

显式清除会不可恢复地删除该项目的 Compose 数据卷与运行时 Secret：

```powershell
.\scripts\stop-local-stack.ps1 -Purge
```

`-Purge` 只接受启动器创建、带精确归属标记且位于受管本地目录下的目标，仍应在执行前确认项目名。

## 5. 权威备份

备份会先停止 Frontend、Backend、Worker、Dispatcher 与 Maintenance 的写入，再生成 PostgreSQL custom dump 和停机一致的 MinIO 整卷快照，随后恢复原栈并重新等待业务就绪：

```powershell
.\scripts\backup-local-stack.ps1 -ProjectName 'finaudit-local'
```

也可以用 `-BackupDirectory` 指定一个尚不存在、且位于仓库外的绝对目录。备份目录包含 `manifest.json`、文件大小、SHA-256、核心表行数与 MinIO 卷摘要；不包含任何 Secret。

因此，恢复仍需要源项目运行目录中的 Secret，或由受控 Secret Manager 提供等价值。仅复制备份目录并不能绕过凭据恢复责任。

### 5.1 备份新鲜度与完整性巡检

下列只读检查要求至少两份完整备份、最新备份不超过 24 小时，并报告超过 30 天的保留期候选；它会重算 PostgreSQL dump 与 MinIO 归档的 SHA-256 和字节数，拒绝不完整、篡改、越界、重复 ID、包含额外文件或宣称包含 Secret 的备份，但不会删除或改写任何文件：

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\audit_local_backups.py `
  --backup-root "$env:LOCALAPPDATA\FinAuditAgent\backups" `
  --project-name 'finaudit-local' `
  --max-age-hours 24 `
  --minimum-complete 2 `
  --retention-days 30
```

成功固定输出 `LOCAL_BACKUP_MUTATION=NONE` 与 `LOCAL_BACKUP_AUDIT=PASS`；失败返回非零退出码，适合由 Windows 任务计划程序或外部监控定期调用。仓库不自动注册宿主机任务，也不自动删除超期候选；调度身份、通知通道和删除审批仍由目标环境运维策略决定。

## 6. 隔离恢复

恢复必须使用一个从未存在过、且不同于源项目的项目名；脚本拒绝原地覆盖：

```powershell
.\scripts\restore-local-stack.ps1 `
  -BackupDirectory 'C:\absolute\path\to\backup' `
  -TargetProjectName 'finaudit-restore-check' `
  -HttpPort 9443
```

恢复流程会先核对 Compose 和备份文件摘要，再创建隔离卷、恢复 MinIO、恢复 PostgreSQL、逐表比较核心事实行数，最后重建 Redis/Qdrant、重新加载 ClamAV 定义并等待 dependency-ready。恢复目标继续使用源管理员当前密码；源初始密码文件不再被描述为有效登录密码。

本地恢复通过不等于正式 RPO/RTO。production 还需要异地主备份、保留期、加密密钥托管、定时任务、恢复权限、目标硬件和三轮实际计时。

## 7. 已知限制

- 全局 HTTP Profile 不提供传输机密性或服务器身份认证；当前只允许 loopback Local MVP。局域网或公网发布前必须恢复受信任 TLS 或由受信任反向代理终止 TLS，并重新验收 Cookie、Origin、证书与 DAST。
- Secret 是受管本地文件挂载，不证明生产 Secret Manager、轮换、吊销或最小主机 ACL。
- Qdrant local Profile 仍固定在已验证的 `1.10.0`；直接把现有 1.10 数据卷跳到 1.18 已验证会因段格式不兼容而失败。升级必须采用显式快照/重建方案，不能由启动器静默删除派生数据。
- OCR 仍为 `not_configured`；扫描图片和无文本 PDF 不会被伪装成 OCR 成功。
- 真实 AI Provider、AI-001 到业务采用的完整持久审计链、正式参考环境的完整容量/性能目标、生产 Scanner Profile、异地备份、正式 DAST、正式 AC/UAT 与发布仍为 `NOT_RUN`；AI-005 仅有第 3.6.1 节的 provider-neutral PostgreSQL primitive 证据，提示注入另有独立 PostgreSQL 服务级回归和 Nginx/HTTP + 真实 Qdrant/浏览器 local 证据，均不得外推为加密传输、正式环境或真实 Provider 结论。
