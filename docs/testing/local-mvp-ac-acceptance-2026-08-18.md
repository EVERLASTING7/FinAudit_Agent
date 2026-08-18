# Local MVP AC-001/002/015/016 验收记录

- 环境：BOSS Windows 本机 + Docker Desktop
- 入口：`http://localhost:8443`，仅 `127.0.0.1`
- 当前实际使用者：1 人；系统支持多账号和五角色，不承诺多人并发容量
- Scanner：本地 ClamAV
- OCR / AI Provider：关闭
- UAT：YHBX 于 2026-08-18 签署 `Local MVP UAT通过`
- 口径来源：`CR-025-local-mvp-ac-scope`

| AC | Local MVP 状态 | 核心当前证据 |
|---|---|---|
| AC-001 登录、权限与职责分离 | `ACCEPTED` | `auth-password-v2` 的 5 字符/弱 6 字符拒绝与安全 6 字符完整会话；持久管理员换密与普通登录；用户管理授权读取；文件页 `AUTH_FORBIDDEN`；历史五角色导航/直达负例与 PostgreSQL Auth/Break-glass/SoD 门禁 |
| AC-002 文件上传与校验 | `ACCEPTED` | 当前 HTTP multipart → ClamAV → Worker → PostgreSQL/MinIO `stored/clean/succeeded` 与原件预览；批量、格式/Magic Bytes、空/超限、去重、archived 409、存储失败、扫描失败、归档/同 Job 重试及 Worker 恢复分层门禁 |
| AC-015 追踪与脱敏 | `ACCEPTED` | 当前 HTTP `LOCAL_SECURITY_BASELINE=PASS`；Origin/CSRF、锁定/防枚举、授权拒绝、Trace、审计失败回滚、操作日志不可变、Secret/日志 canary、Prompt Injection、真实 Qdrant；直接浏览器拒答与数据库/审计终审 PASS；AI 审计强杀回滚与不可采用证据 |
| AC-016 可部署运行与恢复 | `ACCEPTED` | 当前持久/一次性 HTTP `LOCAL_STACK_START=PASS` 与依赖 ready；PostgreSQL/MinIO 权威备份；HTTP 隔离恢复核对行数/对象摘要；Redis/Qdrant 重建、ClamAV 重载；恢复后冷启动、账号状态与 Frontend 200；六类 Worker/Job 恢复、AI disabled 降级及仓库 Secret 门禁 |

## AC-001 逐条结论

- 五角色授权与越权后端拒绝：PASS。
- 系统管理员业务页面直达拒绝与导航裁剪：PASS。
- 财务 high、合同管理员主合同、只读导出等负例：PASS（本地合成角色）。
- 一次性换密不得获得普通会话：PASS；换密后重新登录和授权读取：PASS。
- 同人/组合/临时授权自批负例：PASS（本地合成 Actor）；当前实际使用者 1 人不冒充真实多人组织隔离。

## AC-002 逐条结论

- 合法文件唯一标识与真实状态：PASS。
- 伪装、超限、空文件和类型不一致拒绝且无成功态：PASS。
- 内容去重、业务对象唯一和 archived 409 零副作用：PASS。
- 非 clean 文件不得解析：PASS。
- MinIO/存储失败不得返回成功：PASS。

## AC-015 逐条结论

- 同步 HTTP、异步 Worker、数据库、Adapter Trace 串联：PASS。
- 密码、Token、Key、不必要正文和 canary 不进入日志/指标/错误：PASS。
- 税务身份等敏感字段脱敏：PASS。
- 操作日志/审计失败回滚业务成功：PASS。
- AI Provider 关闭；AI 审计失败/恢复时输出不可采用：PASS。

## AC-016 逐条结论

- 仓库外受管配置启动完整本地栈：PASS。
- 必需依赖 ready 后财务审核、制度处理与本地检索链可运行：PASS。
- 重启和隔离恢复后 PostgreSQL/MinIO 权威事实可用：PASS。
- Redis/Qdrant/ClamAV 派生数据可重建并校验：PASS。
- AI disabled 时确定性规则和明确降级保留：PASS。
- 仓库、镜像和日志无真实密钥：PASS。

## 限制

四项 `ACCEPTED` 只适用于 `CR-025` 的 Local MVP 范围。HTTP 不提供传输机密性或服务器身份认证；本记录不接受多人并发容量、局域网/公网、production、正式 DAST、production Scanner/OCR、异地备份、主机断电或正式 RPO/RTO。扩大环境必须重新验收，不能沿用本记录。

`docs/testing/p0-traceability-matrix.csv` 的 86 行继续表示工作包状态；映射到其他 AC、正式容量或未来环境的任务可以保留 `partial`。AC 级结论以本记录为当前 Local MVP SSOT。
