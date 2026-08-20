# FinAudit Agent Local MVP 0.1.1 发布记录

## 1. 发布结论

| 项目 | 结论 |
|---|---|
| 应用发布决定 | `GO / CR-025 LOCAL MVP ONLY` |
| production ready | `NO` |
| 源码 revision | `03b6bbc41a1c330df3be538e4c46b74dfe383671` |
| 整批 027 冻结 revision | `61b2c17039d08205afe7cc2ac4114aeda05dbad4` |
| 持久镜像 revision | `local-mvp-0.1.1` |
| Alembic head | `20260818_027` |
| UAT | `PASS / MINIMUM TECHNICAL UAT`；没有转移 0.1.0 的人工签署 |
| 远程发布 | `NOT_RUN`；本地分支相对 origin ahead，未 push/tag/GitHub Release |
| 发布日期 | 2026-08-20（Asia/Shanghai） |

0.1.0 的远程发布和 2026-08-18 UAT 保持历史不可变。本记录只绑定 Windows 本机、Docker Desktop、`127.0.0.1` HTTP、ClamAV、OCR/AI disabled 与本机数据/备份边界。

## 2. 当前证据

- 完整离线门禁：Backend `3127 passed / 147 skipped / 1 warning`；Ruff 520 files；mypy 283 sources；Frontend 28 files/539 tests/151 modules；`LOCAL_OFFLINE_QUALITY=PASS`。
- PostgreSQL：current head 027，完整数据库目录 154 项连续两轮 PASS。
- 发票重复候选浏览器 Gate：当前源码自动刷新四项 bytes/SHA-256 后 PASS；两个只读 GET 为 200、DOM source/candidate/common identity 可见、写动作禁用、console 0。
- 持久项目：0.1.1 Backend/Frontend image ID 匹配，head 027，权威总行数 7→7，依赖失败 0、Frontend 200、Operations Readiness PASS。
- 当前备份：ID `0016f52d-2ac4-4b8f-842c-42a74843f80a`，PostgreSQL/MinIO 包含、Secret 排除；完整备份总数 5，巡检 PASS。
- 真实数据演练：旧 backup ID `b94b77a1-1221-49bf-af87-927f97cb3300` 的源 head 024、17 表 22 行与 MinIO 哈希先被独立确认；隔离恢复到 027 后行数/卷摘要、Redis/Qdrant/ClamAV、运维和冷启动 PASS，目标容器/卷/网络/runtime 清理为 0。

机器可读事实见 `local-mvp-0.1.1-2026-08-20.manifest.json`；UAT 范围和未运行项见 `docs/testing/local-mvp-uat-2026-08-20.md`。

## 3. 回滚依据

- 当前 027 权威备份位于仓库外，backup ID 为 `0016f52d-2ac4-4b8f-842c-42a74843f80a`。任何恢复必须先进入新的隔离项目并验证，不得原地覆盖持久卷。
- 0.1.0 的 024 备份仍可用于历史恢复；其管理员凭据属于备份时数据库状态，不能假定当前密码可用。
- 代码回退使用明确 Git revision 创建新运行实例；不使用 Force Push、`git reset --hard` 或直接改写数据库事实。

## 4. 限制

- 持久管理员真实浏览器复登未运行，因为本次不读取或复用凭据；当前认证浏览器证据来自隔离合成账号。
- 现有持久数据库在本次开始时已经是 027，因此本次证明的是“历史 024 备份→027 隔离演练”和“现有 027 实例按 0.1.1 镜像重建”，不是伪造一次此前未发生的首次升级。
- 不声明 production、正式代表性质量、正式 DAST/容量/RPO-RTO、异地备份、真实 OCR/Provider、远程治理或完整 AC-001～016 通过。
