# Local MVP UAT 验收记录

- 状态：`ACCEPTED`
- 签署人：YHBX（BOSS）
- 签署日期：2026-08-18（Asia/Shanghai）
- 签署原文：`Local MVP UAT通过`
- 运行地址：`http://localhost:8443`

## 验收范围

- BOSS 当前 Windows 本机与 Docker Desktop；当前实际使用者 1 人，系统支持多账号与五角色，不承诺多人并发容量。
- 仅 `127.0.0.1` loopback HTTP，不开放局域网或公网。
- PostgreSQL、MinIO、Redis、Qdrant、ClamAV 与 Worker/Dispatcher/Maintenance 完整本地 Compose。
- 全局 `auth-password-v2`：密码最少 6 个 Unicode code point，弱密码黑名单、Argon2id 和锁定策略继续生效。
- OCR 与 AI Provider 关闭；确定性规则保留并明确降级。
- 仓库外受管 Secret、本机数据卷和重要操作前本地备份。

## 验收证据

- `LOCAL_STACK_START=PASS`，Alembic head `20260817_024`，10 个长期服务运行，必需依赖失败数为 0。
- Frontend HTTP 200，HTTPS 握手失败；Nginx 无 SSL 指令，新运行时不生成或挂载 TLS 文件，唯一主机绑定为 `127.0.0.1:8443`。
- 安全 6 字符密码创建、强制换密、普通登录、`/auth/me`、Refresh 和 Logout 通过；5 字符及 `123456/letmein/qwerty` 拒绝。
- BOSS 亲自完成持久 `admin` 强制换密并重新登录；数据库确认 active、未锁定、失败数 0、force-change false、普通活动会话 1。
- 真实浏览器确认系统管理员工作台和用户管理授权读取成功；文件管理直达进入 `AUTH_FORBIDDEN`，console warning/error 为 0。
- HTTP multipart → ClamAV → Worker → PostgreSQL/MinIO 文件终态与预览通过；恢复、审计、日志脱敏和 Prompt Injection 另有分层本地证据。
- 完整离线门禁：Backend `3048 passed / 142 skipped / 1 warning`，Ruff 495 files、mypy 271 sources、pip check、Frontend 26 files/527 tests/typecheck/147-module build 通过。
- PostgreSQL 16.14 current-head 完整 149 项连续两轮通过；Request manifest 与 `BASELINE_LOCAL_VERIFY=PASS`。
- 临时恢复密码已清零并删除；一次性验证栈、卷、运行时 Secret 和镜像已清理。

## 明确排除

本签署只接受当前 Local MVP，不接受或证明以下内容：

- HTTP 的传输机密性或服务器身份认证。
- 局域网、公网、production、正式域名/TLS、Secret Manager、正式 DAST 或镜像发布签署。
- OCR、真实 AI Provider、代表性业务质量、正式容量、异地备份、主机断电或正式 RPO/RTO。
- AC-003～014、production 环境下的 AC-001/002/015/016 或全量 production AC-001～016。

`CR-025` 后，`Local MVP UAT=ACCEPTED` 同时支持 AC-001、AC-002、AC-015、AC-016 的 Local MVP `ACCEPTED` 结论；AC 级证据见 `docs/testing/local-mvp-ac-acceptance-2026-08-18.md`。追踪矩阵中的工作包仍可因其他 AC 或未来环境保持 `partial`。
