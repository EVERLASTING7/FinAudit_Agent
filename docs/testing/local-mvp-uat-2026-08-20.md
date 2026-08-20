# Local MVP 0.1.1 最小技术 UAT 记录

- 状态：`PASS / MINIMUM TECHNICAL UAT`
- 请求人：YHBX（BOSS）
- 执行人：Codex
- 执行日期：2026-08-20（Asia/Shanghai）
- 应用源码 revision：`03b6bbc41a1c330df3be538e4c46b74dfe383671`
- 持久镜像 revision：`local-mvp-0.1.1`
- 运行地址：`http://localhost:8443`
- 人工签署继承：`NO`；2026-08-18 的 `Local MVP UAT通过` 只绑定 0.1.0 历史版本

## 最小验收范围与结果

| 检查 | 结果 | 当前证据 |
|---|---|---|
| 源码可恢复 | `PASS` | `61b2c17` 冻结 027 整批变更；`03b6bbc` 追加历史备份 bootstrap 身份恢复修复；均为本地 Git commit |
| 完整离线质量 | `PASS` | Backend `3127 passed / 147 skipped / 1 warning`；Ruff 520；mypy 283；Frontend 28 files/539 tests/151 modules |
| PostgreSQL current-head | `PASS` | `20260818_027`；PostgreSQL 16.14 完整 154 项连续两轮通过 |
| 认证 UI 最小闭环 | `PASS / ISOLATED SYNTHETIC` | 当前源码的 in-app browser 完成 finance_reviewer 登录、工作台、发票列表、源票详情、精确候选与 pair；两个受保护 GET 均 200、写动作 disabled、console 0 |
| 持久 Local MVP 启动 | `PASS` | `finaudit-local` 为 027，Backend/Frontend image ID 匹配 0.1.1，权威总行数升级前后均为 7，必需依赖失败 0，Frontend 200 |
| 权威备份 | `PASS` | backup ID `0016f52d-2ac4-4b8f-842c-42a74843f80a`；PostgreSQL/MinIO 包含、Secret 排除；5 份完整备份巡检 PASS |
| 024→027 隔离演练 | `PASS` | backup `b94b77a1-1221-49bf-af87-927f97cb3300` 独立确认源 head 024、17 表 22 行；恢复到 027 后行数/MinIO 摘要、派生重建和 bootstrap 身份通过 |
| 恢复后冷启动 | `PASS` | 普通停止后重新启动仍为 027/22 行，依赖失败 0、Frontend 200；运维就绪四项 PASS；隔离资源最终为 0 |
| 持久运维就绪 | `PASS` | dependency、bounded logging、restart policy、受保护 metrics 全部 PASS |

## 失败轮与修复边界

首次历史备份恢复在 `admin-bootstrap` 以 `BOOTSTRAP_STATE_CONFLICT` 安全失败。迁移本身已完成，但恢复脚本错误复用当前 runtime marker 的管理员用户名，而 024 备份保存的是历史管理员身份。修复后脚本只从哈希和行数均已验证的恢复数据库读取唯一活动 bootstrap 身份，先校验可安全写入 Compose，再更新隔离 marker/env；不改数据库、不重置密码、不放宽首次安装门禁。相同 024 备份从清洁目标重跑后完整 PASS。

## 明确未执行与不外推

- 未读取、复用或重置持久管理员密码；持久管理员浏览器复登为 `NOT_RUN`。认证 UI 使用当前源码的一次性合成 finance_reviewer Gate，不能冒充 BOSS 人工复登。
- 本记录是技术最小 UAT，不伪造 YHBX 新的人工作业签名，不覆盖 2026-08-18 的历史 UAT 原文。
- HTTP 仍只允许 loopback，不提供传输机密性或服务器身份认证。
- 不接受局域网/公网、production、真实 OCR/Provider、业务代表性质量、正式 DAST/容量/RPO-RTO、异地恢复或完整 AC-001～016。
