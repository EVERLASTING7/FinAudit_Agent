# TEST/DEP 验收与运维证据记录（2026-08-18）

## 1. 结论

本轮补齐并实跑了 Local MVP 的持续运维入口、OpenAPI 全操作身份门禁、当前代码财务浏览器闭环、安全基线、权威备份巡检与隔离恢复。当前本机 Profile 的发布与持续运行证据明显增强，但 13 个工作包仍跨越业务代表性质量、正式安全/性能、production 和其他 AC；这些外部边界未完成前，追踪矩阵不得把对应 `partial` 静默改成 `implemented`。

YHBX 已据此选择 CR-025 Local MVP 路线；应用发布决定记录于 `docs/releases/local-mvp-0.1.0-2026-08-18.md`，状态为 `GO / LOCAL MVP ONLY`。这不是对 production 或正式全量 TEST/DEP 的状态升级。

本轮运维门禁本身未调用任何真实 AI/Embedding Provider，也未读取或输出真实密钥。后续两次另行授权的 `CR-026` local/test 评测均已消耗并失败停止；常驻 Local MVP 仍关闭 Provider。BOSS 随后明确授权配置指定 GitHub remote、普通 push 发布分支并读取远程治理状态；未使用 Force Push，也未部署应用运行环境。

## 2. 新增或修复的可执行能力

- `infra/compose/compose.local.yml`：十个长期服务统一使用 Docker `local` 日志驱动，单容器固定 `5 × 10 MiB`；继续使用 `unless-stopped`。
- `scripts/verify-local-stack.ps1 -OperationsReadiness`：只读核对依赖健康、十服务运行态、restart policy、有界日志和受管 `/metrics` 401/200 双路径。
- `scripts/verify-local-stack.ps1 -SecurityBaseline`：在既有安全门禁上新增受管 metrics、日志策略和 Worker PID 1 `SIGTERM → RestartCount + 1 → dependency-ready` 自动重启证据。
- `frontend/docker/nginx.conf`：metrics 精确 location 隐藏 Backend 的 `X-Content-Type-Options`，由 Nginx 统一输出单一 `nosniff`；真实运行先复现重复头，再以失败回归修复。
- `scripts/audit_local_backups.py`：纯标准库、只读核验备份 manifest、UTC 时间、唯一 ID、Secret 排除、文件闭集、字节数、SHA-256、新鲜度、最小份数与保留期候选；固定输出 `LOCAL_BACKUP_MUTATION=NONE`。
- `backend/tests/unit/test_openapi_operation_coverage.py`：当前 92 个 `/api/v1` operationId 必须唯一，且每个都由至少一份 Backend 测试源码显式冻结；CR-005-R2 新增的纠错、独立激活和安全重评三个 identity 均已纳入。

## 3. 当前命令与结果

| 门禁 | 当前结果 | 证据边界 |
|---|---|---|
| `scripts/verify-local-offline.ps1` | `LOCAL_OFFLINE_QUALITY=PASS`；Backend `3093 passed / 146 skipped / 1 warning`；Ruff `516 files`；mypy `283 sources`；Frontend `28 files / 536 tests / 151 modules` | PostgreSQL、Compose、浏览器、Provider、remote、production 在该离线包装器中按设计 `NOT_RUN` |
| GitHub remote 发布核验 | `origin` 指向 `EVERLASTING7/FinAudit_Agent`；`release/local-mvp-0.1.0` 已普通 push；核验基准提交 `ccf2fa09a77d9d3697b3dcc47cb18d6c84ace7a8` 的本地/远程 SHA 一致；当时为唯一/default 分支，`protected=false`、Rulesets 为 0 | 证明源码分支已发布并完成只读状态核验；不代表保护规则、远程 CI、tag、GitHub Release 或 production 已完成 |
| `scripts/verify-postgresql-current-head.ps1 -Scope Full` | current head `20260818_027`、PostgreSQL `16.14` 完整 `153/153 × 2`，两轮 `status=ok`，`POSTGRESQL_CURRENT_HEAD=PASS` | 覆盖 025/026/027、历史迁移、并发和故障注入；专用可丢弃数据库不等于 production migration |
| `scripts/verify-postgresql-current-head.ps1 -Scope File/Audit/Retrieval` | current head 027 分别 `16 / 4 / 10 passed`；覆盖 fixed_test Asset 重评、CR-027 retry/cancel 和 CR-028 policy revoke | fixed_test 仅隔离合成；Provider、真实 Scanner/MinIO Asset、production 和真实数据迁移未运行 |
| `scripts/verify-local-celery-redis.ps1` | `4 passed`，`CELERY_REDIS_BROKER_TRANSPORT=PASS` | 锁定 Redis 7.4.9；残留容器 0 |
| `verify-local-stack.ps1 -ProjectName finaudit-local -OperationsReadiness` | dependency、bounded logging、restart policy、metrics runtime 全部 PASS | 当前持久 Local MVP；非 production 监控平台 |
| `audit_local_backups.py` | 完整备份 `4`，发布前最新备份目录 `20260818T052018Z`、ID `b94b77a1-1221-49bf-af87-927f97cb3300`，`LOCAL_BACKUP_AUDIT=PASS` | 只读巡检；不自动删除或调度 |
| `restore-local-stack.ps1` | PostgreSQL 行数、MinIO 卷摘要、Redis/Qdrant 重建、ClamAV 重载 PASS；恢复后运维门禁、普通停止后冷启动再次 PASS | 独立 `finaudit-restore-ops1`；目标容器/网络/卷/运行时最终 0 |
| `verify-local-stack.ps1 -PerformanceBaseline` | 修复旧 transport 标签后同栈新 run 三轮 PASS；列表 P95 `10.607/10.647/10.978 ms`，上传受理 P95 `36.794/41.385/38.023 ms`，机器 JSON 固定 `transport=http-nginx-backend` | 小型合成 local Profile；AI/OCR/production 为 `NOT_RUN`，不代表正式参考环境完整容量 |
| `verify-financial-loop-browser-gate.ps1` | 最终 `FINANCIAL_LOOP_BROWSER_GATE=PASS` | 当前代码、合成 DOCX、本地依赖、真实浏览器；不等于代表性业务质量或 production |
| `verify-local-stack.ps1 -SecurityBaseline` | metrics、HTTP/CSRF/锁定、权限、审计回滚、追加日志、真实 Qdrant Prompt Injection、bounded logging、自动重启全部 PASS | 浏览器增量、正式 DAST、production 明确 `NOT_RUN`；专用栈与镜像最终 0 |

财务浏览器门禁的第一轮因上传 Actor 不符合受保护 manifest 的精确归属而返回 409；该轮已关闭并清理，不计通过证据。第二轮统一使用固定 `financial.read.integration` 业务 Actor，服务端 manifest 复算后接受：精确两文件/两绑定、唯一合同/发票/供应商/主关系/任务/执行/报告、单条聚合供应商纠错、两次 `supplier.resolve`、一次 `supplier.update`、五个纯角色登录、ready PDF/XLSX 与零浏览器 console warning/error。

## 4. 13 个工作包当前判定

| 工作包 | 本轮新增最强证据 | 仍未关闭的边界 |
|---|---|---|
| TEST-001 | 当前离线、PostgreSQL 双轮、Redis/Celery、浏览器、Compose/恢复和远程分支发布证据已重新绑定 | 业务代表性审批集、全量正式 AC、production、远程分支保护与 CI |
| TEST-002 | 全量 Backend 单元套件与确定性指标继续 PASS | 经审批代表性合同/发票输入未提供，正式指标未运行 |
| TEST-003 | 98 个 `/api/v1` operationId 全覆盖 meta-gate，唯一数 98、遗漏数 0；CR-005/027/028 delta 为 `+3/+1/+2` | CR-027/028 R1 的绝对 pre-count 92 遗漏三个已授权 CR-005 operation，已记录为签署历史漂移；正式 AC API 验收仍未签署 |
| TEST-004 | 当前代码完整财务浏览器闭环与五角色矩阵 PASS | 代表性业务 UAT、全路由无障碍、production |
| TEST-005 | `CR-026` 新授权的 local/test 批量复核以 5 次请求、4971 input tokens、CNY 0.002486 得到 49/50 与授权泄露 0；Event v2 completion 事务采用、失败即停和零残留通过 | `ai_call_logs` 后置投影核对因质量失败未运行；1 个 no-answer 假阳性使 50 条门禁 FAILED，100 条与激活未运行，业务代表性 50/100 集未批准 |
| TEST-006 | 当前 HTTP 安全基线、metrics、Prompt Injection、审计回滚和容器策略 PASS | 正式 DAST、非 loopback 传输、production |
| TEST-007 | Worker 自动重启、权威备份巡检、隔离恢复/冷启动和当前 HTTP 三轮本地性能新增 PASS | 代表性完整性能、主机断电、异地恢复、正式 RPO/RTO |
| DEP-001 | 持久完整 Compose 原地重建后运维门禁 PASS | 非本机目标主机、production 发布 |
| DEP-002 | loopback HTTP/Nginx 当前运行；metrics 重复安全头根因修复并实跑 | 非 loopback 必须恢复受信任 TLS/反向代理并重验 |
| DEP-003 | Docker 日志有界轮转、Trace/追加式操作日志与日志 canary PASS | 集中采集、访问/保留策略和 production 审计平台 |
| DEP-004 | dependency health 与 OperationsReadiness 当前持久栈 PASS | production SLO、通知通道和告警演练 |
| DEP-005 | 四份备份新鲜度/完整性 PASS；最新备份隔离恢复与冷启动 PASS | 加密异地备份、自动调度/通知、正式 RPO/RTO |
| DEP-006 | 受管 `/metrics` 无凭据 401、正确凭据 200、固定低基数指标和安全响应头 PASS | 长期采集器、告警规则、SLO/留存与 production |

## 5. 发布停止边界

下列项目不能由继续写本地代码或重跑既有合成门禁自动变成通过：

1. TEST-005 的最新 50 条真实 Embedding 技术门禁是 `FAILED (49/50)`，不是 `NOT_RUN`；其后 100 条与激活未运行。`CR-026` 单次授权已经消耗，再次 Provider 调用必须获得新的明确授权。
2. 合同 85%、发票 95%、结构合法率 99% 需要经业务审批的代表性输入；仓库当前只有计算器和合成/链路证据。
3. 正式 DAST、生产 CA/TLS、Secret Manager、集中监控告警、异地备份、主机断电和 RPO/RTO 需要目标环境与责任人。
4. `release/local-mvp-0.1.0` 已按 BOSS 授权推送，但远程没有 `main`/`develop`，当前分支未保护且 Rulesets 为 0；其余并行未提交改动不属于本次发布，不得静默提交或推送。

因此，本记录证明 Local MVP 的可运行性/持续性增量已经实装并通过，但不把正式全量 TEST/DEP 或 production 发布状态伪造为完成。
