# FinAudit Agent Local MVP 0.1.0 发布记录

## 1. 发布结论

| 项目 | 结论 |
|---|---|
| 应用发布决定 | `GO / CR-025 LOCAL MVP ONLY` |
| production ready | `NO` |
| 源码远程发布 | `PENDING_REMOTE_URL` |
| 发布责任人 | YHBX |
| UAT | `ACCEPTED`，签署原文为 `Local MVP UAT通过` |
| 发布日期 | 2026-08-18（Asia/Shanghai） |
| 发布分支 | `release/local-mvp-0.1.0` |
| 应用源码提交 | `3449aa5de8cabe1e55201cfcfb4d5705d4098ce1` |
| 发布记录修订 | 包含本文件最终状态的后续 Git commit |
| 持久运行镜像修订 | `local-mvp-0.1.0` |

本决定只接受当前 BOSS Windows 本机、Docker Desktop、loopback HTTP Local MVP。13 个 `TEST-001～007`、`DEP-001～006` 工作包继续保持 `partial`，不声明 production、正式代表性质量或完整 AC-001～016 已通过。

## 2. 固定运行范围

- 唯一入口：`http://localhost:8443`，只绑定 `127.0.0.1`。
- 当前实际使用者为 1 人；系统仍支持多账号与五种固定角色，不承诺多人并发容量。
- PostgreSQL 与 MinIO 使用本机 Docker 数据卷；Redis、Qdrant 与 ClamAV 数据可重建。
- Scanner 使用本地 ClamAV；OCR 为 `not_configured`。
- AI Provider 关闭，`AI_PROVIDER_CALLS_ENABLED=false`；确定性规则继续运行并明确显示 AI 降级。
- Secret 位于仓库外受管目录，通过只读挂载注入；发布记录、仓库、日志和构建产物不保存真实 Secret。
- 十个长期容器使用 `unless-stopped`，Docker `local` 日志驱动固定为每容器 `5 × 10 MiB`。

## 3. 接受的 AC

依据 `CR-025-local-mvp-ac-scope` 与独立验收制品，本次仅接受：

- AC-001：登录、五角色权限、职责分离、强制换密与越权拒绝。
- AC-002：文件上传、类型/内容校验、ClamAV、去重、失败边界与 MinIO 可用性。
- AC-015：Trace、脱敏、审计失败回滚、Prompt Injection 和 AI 结果不可误采用。
- AC-016：完整本地栈、依赖健康、权威备份/隔离恢复、派生重建、冷启动与 AI disabled 降级。

其余 AC 只保留已有工程证据，不在本次发布中签署为 `ACCEPTED`。

## 4. 发布证据

| 门禁 | 结果 |
|---|---|
| 完整离线质量门禁 | `LOCAL_OFFLINE_QUALITY=PASS`；Backend `3063 passed / 142 skipped / 1 warning`；Ruff 497 files；mypy 271 sources；Frontend 527 tests / 147 modules |
| PostgreSQL current-head | PostgreSQL 16.14，完整目录 `149/149 × 2`；两轮 `status=ok`，`POSTGRESQL_CURRENT_HEAD=PASS` |
| Redis/Celery | `4 passed`，`CELERY_REDIS_BROKER_TRANSPORT=PASS` |
| 持久核运维 | dependency、bounded logging、restart policy、受管 metrics 全部 PASS |
| 财务浏览器闭环 | `FINANCIAL_LOOP_BROWSER_GATE=PASS`；两文件、合同、发票、供应商、主关系、15 规则、财务复核、PDF/XLSX 与五角色 manifest accepted |
| HTTP 安全基线 | `LOCAL_SECURITY_BASELINE=PASS`；metrics、CSRF/锁定/权限、审计回滚、真实 Qdrant Prompt Injection、自动重启与日志 canary PASS |
| 本地性能 | `LOCAL_PERFORMANCE_BASELINE=PASS`；机器事实固定 `transport=http-nginx-backend`；仅代表本机小型合成负载 |
| 备份巡检 | 4 份完整备份通过 manifest/bytes/SHA-256/Secret 排除/新鲜度检查；发布前最新备份约 1 分钟 |
| 隔离恢复 | PostgreSQL 行数、MinIO 摘要、Redis/Qdrant 重建、ClamAV 重载、运维门禁与停止后冷启动 PASS |

完整命令、失败轮排除和边界见 `docs/testing/test-operations-evidence-2026-08-18.md`。

## 5. 权威回滚依据

- 当前发布前备份目录名：`20260818T052018Z`。
- 备份 ID：`b94b77a1-1221-49bf-af87-927f97cb3300`。
- 创建时间：`2026-08-18T05:20:29.1066278Z`。
- PostgreSQL custom dump 与 MinIO 停机一致归档均包含；Secret 明确排除。
- 回滚必须先恢复到新的隔离项目并校验，不允许覆盖持久源项目。
- 应用代码回滚使用前一 Git commit 重新构建；不得使用 Force Push、`git reset --hard` 或直接修改数据库事实。

## 6. 明确排除与已知风险

- HTTP 不提供传输机密性或服务器身份认证；不得开放到局域网或公网。
- 不接受 production、正式域名/CA、Secret Manager、正式 DAST、异地备份、主机断电或正式 RPO/RTO。
- 不接受业务代表性合同/发票质量、50/100 条正式检索质量、真实 OCR、正式容量或生产 Provider。
- Edge、全 P0 路由键盘、屏幕阅读器和 LibreOffice Calc 兼容性尚未完成。
- Backend 本地镜像剩余 Docker Scout `2C/2H` 均无已修复版本；本记录不签署 production VEX 或风险接受。
- 仓库尚无指定 remote；远程分支保护、远程 CI、push、tag 和 release 均未运行。

## 7. Provider 与候选能力边界

- `CR-026` 的两次独立 local/test 百炼授权均已消耗；两次都使用 5 次请求、4971 input tokens、CNY 0.002486，50 条结果同为 49/50，并因一个 no-answer 假阳性失败停止。100 条、激活和重试均未运行；第二次 runtime UUID 未保留到冻结 source case ID 的映射，不能反查具体问题。
- 批量评测能力不属于常驻 Local MVP 运行路径，当前仍为 `AI_PROVIDER_CALLS_ENABLED=false`；本次发布决定不产生任何新的 MiniMax/百炼密钥复用或付费请求授权。
- 未来真实评测必须由 BOSS 重新明确数据集、环境、密钥复用、请求/Token/费用上限与失败停止条件。

## 8. 发布与回滚检查清单

- [x] Local MVP UAT 已签署。
- [x] AC-001/002/015/016 Local MVP 证据已绑定。
- [x] 当前持久栈 `OperationsReadiness` 通过。
- [x] 持久栈已按当前工作树重建为镜像修订 `local-mvp-0.1.0`。
- [x] 权威备份存在且只读巡检通过。
- [x] 发布范围和 production 排除项已记录。
- [x] 当前发布快照的 PostgreSQL Full 双轮结果已回写。
- [x] 发布分支 `release/local-mvp-0.1.0` 已创建。
- [x] 当前发布快照已提交：`3449aa5de8cabe1e55201cfcfb4d5705d4098ce1`。
- [ ] 用户指定 remote 已配置。
- [ ] 发布分支已推送且远程分支保护已验证。

在最后四项完成前，应用的 Local MVP `GO` 已成立，但源码远程发布状态保持 `PENDING_REMOTE_URL`。
