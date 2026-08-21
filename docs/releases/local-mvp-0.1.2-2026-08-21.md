# FinAudit Agent Local MVP 0.1.2 发布记录

## 1. 当前结论

| 项目 | 结论 |
|---|---|
| 应用发布决定 | `GO / CR-025 LOCAL MVP ONLY` |
| production ready | `NO` |
| 应用源码 revision | `140c31156412360ecc7f48ae5a26f3112d050763` |
| 持久镜像 revision | `local-mvp-0.1.2` |
| Alembic head / 表数 | `20260818_027` / 58 |
| 技术门禁 | `PASS` |
| 持久管理员复登 | `PASS / YHBX ATTESTED` |
| 独立人工 UAT | `PASS / YHBX HUMAN UAT`；不继承 0.1.0/0.1.1 结论 |
| 远程发布 | `AUTHORIZED / PENDING NORMAL PUSH`；禁止 Force Push |
| 记录日期 | 2026-08-21（Asia/Shanghai） |

0.1.2 是 0.1.1 的后继，不覆盖历史记录。本记录只绑定 Windows 本机、Docker Desktop、`127.0.0.1` HTTP、ClamAV、OCR/AI disabled 与本机 PostgreSQL/MinIO/备份边界。YHBX 已在当前任务中按约定文本签署持久管理员复登和独立人工 UAT，并授权对当前 release 分支执行普通 push；人工步骤记为 `YHBX ATTESTED`，不是 Codex 代替输入密码或独立观察所得。

## 2. 已通过的当前证据

- 源码与证据已经冻结在 Git revision `140c31156412360ecc7f48ae5a26f3112d050763`；该 revision 包含 2026-08-21 的运行代码、测试、CR、浏览器脚本、机器证据，以及 head 027、58 表和 remote/upstream 文档纠偏。
- 完整离线门禁：Backend `3165 passed / 147 skipped / 1 warning`；Ruff 528 files；mypy 283 sources；Frontend 28 files/539 tests/151 modules；最终 `LOCAL_OFFLINE_QUALITY=PASS`。Vitest 受控网络负例输出过 localhost:3000 `ECONNREFUSED/ECONNRESET`，但 28 个文件、539 项测试和进程退出码均通过。
- PostgreSQL：16.14、固定镜像 ID `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`，Full 154 项连续两轮通过，`POSTGRESQL_CURRENT_HEAD=PASS`。
- 受保护浏览器 Gate：`DOCUMENT_CORRECTION_BROWSER_GATE=PASS`、`POLICY_REVOCATION_BROWSER_GATE=PASS`、`INVOICE_DUPLICATE_BROWSER_GATE=PASS`、`REPORT_BROWSER_GATE=PASS`；授权角色、失败路径、刷新恢复、PostgreSQL 终态、原生 XLSX 下载和 console warning/error 0 均由各 Gate 覆盖。
- 报告兼容性：Microsoft Excel、LibreOffice Calc、PDF/XLSX 跨镜像语义与 Poppler 渲染全部通过，`REPORT_ARTIFACT_COMPATIBILITY=PASS`。
- 持久项目：Backend image ID `sha256:86127b8348c93bb46a2e52dd2d32452f36e9ef635221cef533400063e0401387`，Frontend image ID `sha256:7d4ec725964bd69f0d114a385ae1e0b1492aa45bb90b8a8bbc22eb2d6eda9e1d`；运行容器与 0.1.2 tags 一致。head 027、58 表、权威行数 7→7、必需依赖失败 0、Frontend 200，依赖、bounded logging、restart policy 和受保护 metrics 均 PASS。
- 当前权威备份 ID `9b5acc63-bcc5-471e-98b2-83ee4099a426`；PostgreSQL/MinIO 包含，Secrets 排除，旧备份未覆盖。

机器可读事实见 `local-mvp-0.1.2-2026-08-21.manifest.json`；YHBX 人工 UAT 结果见 `docs/testing/local-mvp-uat-2026-08-21.md`。

## 3. 回滚依据

- 代码回滚使用明确 Git revision 创建新实例；不得使用 Force Push、`git reset --hard` 或直接改写数据库事实。
- 数据恢复使用仓库外 backup ID `9b5acc63-bcc5-471e-98b2-83ee4099a426`，必须先在新隔离项目核验，禁止原地覆盖持久卷。
- 0.1.1 镜像与发布记录保持不可变；0.1.2 不复用或重置持久管理员密码。

## 4. 保留限制

- OCR 默认关闭。扫描 PDF、JPG、PNG 仍不能承诺识别成功。
- 公开发票代理指标 `46.15%`、本机 Qwen pilot `78.85%` 均低于 95%；默认支持格式只解析通过 34/65。CR-031 仅将代表性业务质量标为 `OUT_OF_SCOPE_KNOWN_LIMITATION`，没有把失败改成通过。
- AC-001/002/015/016 仅按 CR-025 Local MVP 口径接受；AC-003～014 仍缺代表性数据、业务 UAT、正式指标或签署。
- 当前发布没有调用真实 Provider；AI 默认 disabled，历史 local/test Provider 证据不构成常驻或 production 能力。
- 受信任 TLS、Secret Manager、production Scanner/OCR、正式 DAST、监控告警/SLO、正式容量、异地备份、主机断电、RPO/RTO、Backend `2C/2H` 风险签署、远程分支保护和正式发布流程仍未闭合。
