# CR-025：AC-001/002/015/016 调整为 Local MVP 验收口径

- 状态：APPROVED
- 批准人：BOSS（YHBX）
- 批准日期：2026-08-18
- 当前交付阶段：Local MVP

## 决定

BOSS 当前只要求本机运行。AC-001、AC-002、AC-015、AC-016 从 production 环境验收调整为 Local MVP 环境验收：

- 环境固定为 BOSS Windows 本机 + Docker Desktop、当前实际使用者 1 人、仅 `127.0.0.1`、`http://localhost:8443`；系统继续支持多账号和五角色，但不承诺多人并发容量。
- 允许使用当前 checkout、一次性本地 Compose 项目和合成/公开测试凭据形成运行证据。
- Scanner 固定为本地 ClamAV；OCR 和 AI Provider 关闭，必须保留确定性规则和明确降级。
- Secret 固定为仓库外受管文件；数据使用本机 PostgreSQL/MinIO 卷，重要操作前本地备份。
- 不要求 production 主机、局域网/公网、TLS、正式 DAST、正式容量、异地备份或正式 RPO/RTO。
- YHBX 的 `Local MVP UAT通过` 作为当前阶段业务接受结论。

## 四项 AC 的本地完成标准

### AC-001 Local MVP

- 五种固定角色、后端拒绝、导航裁剪和系统管理员职责分离由一次性多角色数据验证。
- 持久本地管理员完成恢复、一次性换密、普通登录和授权读取；系统管理员直达业务文件页必须 `AUTH_FORBIDDEN`。
- 全局密码策略为 `auth-password-v2`，安全 6 字符允许，5 字符与版本化弱密码拒绝。
- Local MVP 不要求真实多人长期任职；同人/组合/临时授权负例可用本地合成 Actor 验证。

### AC-002 Local MVP

- 支持文件在本地 PostgreSQL/MinIO/ClamAV/Worker 链获得唯一事实和真实状态。
- 伪装、空、超限、类型不一致、恶意/扫描失败、存储失败、重复与 archived 重传按冻结错误和零副作用规则处理。
- 合成 PDF/DOCX/图片和一次性本地 Scanner 测试数据可以作为验收输入；不要求 production Scanner 产品或正式容量。

### AC-015 Local MVP

- Trace 串联本地 HTTP、异步 Worker、数据库和 Adapter；日志、指标、错误和操作日志保持脱敏。
- 审计失败必须回滚业务成功；操作日志保持追加不可变。
- AI Provider 关闭；provider-neutral AI 审计失败或恢复门禁必须证明输出不可采用。
- Prompt Injection、Origin/CSRF、锁定、防枚举、权限拒绝和日志 canary 在独立本地安全栈验证；不要求正式 DAST 或传输加密。

### AC-016 Local MVP

- 受管 Compose 在 loopback HTTP 启动，全部必需依赖 ready，AI 明确 disabled，仓库/镜像无真实密钥。
- 本地完整财务审核、制度处理、Qdrant 检索和报告链已有可重复合成运行证据。
- PostgreSQL/MinIO 权威备份、隔离恢复、冷启动、Redis/Qdrant/ClamAV 重建和 Worker/Job 恢复通过。
- 本阶段不承诺正式容量、异地恢复、主机断电或 RPO/RTO。

## 证据与状态

四项 AC 只有在 `docs/testing/local-mvp-ac-acceptance-2026-08-18.md` 逐项绑定当前运行命令、结果与限制后才可标记 `ACCEPTED`。`docs/testing/p0-traceability-matrix.csv` 的 86 行仍跟踪工作包状态；任务跨越其他 AC 或未来环境时可以继续为 `partial`，不能用任务状态反向否定或伪造 AC 级结论。

本 CR 不接受 production 或公网发布。未来扩大范围必须重新定义环境与安全门禁，不能复用 Local MVP `ACCEPTED` 结论。
