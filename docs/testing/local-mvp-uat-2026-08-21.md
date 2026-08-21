# Local MVP 0.1.2 独立 UAT 记录

- 当前状态：`PASS / YHBX HUMAN UAT`
- 请求人：YHBX（BOSS）
- 技术执行人：Codex
- 人工执行人：YHBX（BOSS）
- 执行日期：2026-08-21（Asia/Shanghai）
- 应用源码 revision：`140c31156412360ecc7f48ae5a26f3112d050763`
- 持久镜像 revision：`local-mvp-0.1.2`
- 运行地址：`http://localhost:8443`
- 人工签署继承：`NO`；0.1.0 的历史签署和 0.1.1 的最小技术 UAT 均不转移
- YHBX 签署：`Local MVP 0.1.2 UAT通过`
- 普通 push 授权：`AUTHORIZED`；当前 release 分支，禁止 Force Push
- 远程 UAT 证据：`PASS / NORMAL PUSH`；revision `85b65c7ca9bd2d53202990767655baabb7932510`，远端 SHA 一致，Force Push 未使用
- 签署记录时间：2026-08-21T10:23:23+08:00
- 签署文本绑定：UTF-8 87 bytes；SHA-256 `24F56175644C59F3E7A0167A65BE5EEFFC218EAD52314A023DDDB4BF6601E245`

## 技术前置与结果

| 检查 | 结果 | 当前证据 |
|---|---|---|
| 源码与证据可恢复 | `PASS` | revision `140c311…` 包含本轮 66 个源码、测试、CR、脚本、证据和规格纠偏文件 |
| 完整离线质量 | `PASS` | Backend `3165/147/1`；Ruff 528；mypy 283；Frontend 28 files/539 tests/151 modules |
| PostgreSQL current-head | `PASS` | `20260818_027`、58 表；PostgreSQL 16.14 Full 154 项连续两轮通过 |
| P1 受保护浏览器链 | `PASS / ISOLATED SYNTHETIC` | 文档纠错、制度撤销、发票重复均覆盖角色、失败路径、刷新恢复、数据库终态、console 0 和清理 |
| 报告下载与兼容性 | `PASS / LOCAL TEST` | 原生 XLSX 下载与数据库 SHA 对账；Excel、LibreOffice、PDF/XLSX 跨镜像语义通过 |
| 持久 Local MVP 启动 | `PASS` | 0.1.2 image IDs 匹配，head 027、58 表、权威行数 7→7、依赖失败 0、Frontend 200 |
| 权威备份 | `PASS` | backup ID `9b5acc63-bcc5-471e-98b2-83ee4099a426`；PostgreSQL/MinIO 包含，Secrets 排除 |
| 持久运维就绪 | `PASS` | dependency、bounded logging、restart policy、受保护 metrics 全部 PASS |

## YHBX 人工 UAT 清单

以下步骤必须由 YHBX 在持久 `finaudit-local` 上完成，Codex 不读取、复用、重置或回显管理员密码：

1. 打开 `http://localhost:8443`；若浏览器已有会话，先正常退出。
2. 由 YHBX 亲自输入持久 `local-admin` 凭据并登录，确认进入系统管理员工作台。
3. 打开用户管理，确认页面可读；刷新整页后仍能恢复同一管理员会话。
4. 直接进入文件管理，确认系统管理员因职责分离看到 `AUTH_FORBIDDEN`，而不是获得财务文件权限。
5. 正常退出，再次回到登录页；确认没有把 0.1.0/0.1.1 的旧会话冒充本轮复登。
6. YHBX 根据上述实际结果，在当前任务中明确签署：`Local MVP 0.1.2 UAT通过`；任何其他表述不自动视为签署。

| 人工检查 | 当前结果 |
|---|---|
| 持久管理员浏览器复登 | `PASS / YHBX ATTESTED` |
| 工作台与用户管理 | `PASS / YHBX ATTESTED` |
| 刷新恢复 | `PASS / YHBX ATTESTED` |
| 文件管理职责分离拒绝 | `PASS / YHBX ATTESTED` |
| 正常退出 | `PASS / YHBX ATTESTED` |
| YHBX 独立签署 | `PASS` |

## 明确不外推

- 本 UAT 只接受 CR-025 Windows 本机、loopback HTTP、ClamAV、OCR/AI disabled 与本机数据/备份边界。
- OCR 扫描件、代表性合同/发票/重复/风险质量、AC-003～014、真实常驻 AI、production、受信任 TLS、正式 DAST/容量/RPO-RTO、异地恢复、镜像风险签署和远程治理均不在本次通过范围。
- 本记录的人工步骤依据 YHBX 当前任务中的明确签署记为 `PASS / YHBX ATTESTED`，不是 Codex 代替输入密码或独立观察所得；不得外推到 production 或未列入本 UAT 的正式业务验收。
