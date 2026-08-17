# FinAudit Agent

企业财务文档智能审核与风险分析平台。系统用于辅助财务、审计和合同人员，不替代有权限的人员作出付款、税务、法律或合规决定。

## 开发入口

从 [Request/README.md](Request/README.md) 开始。当前活跃规格只有四份：

- [产品需求](Request/PRODUCT_REQUIREMENTS.md)：做什么、谁使用、业务不变量和 AC。
- [技术规格](Request/TECHNICAL_SPEC.md)：按什么架构和机器事实源实现。
- [实施计划](Request/IMPLEMENTATION_PLAN.md)：下一步选择哪个 `READY` 垂直切片。
- [开发规格入口](Request/README.md)：优先级、CR 触发条件和状态词典。

旧版九份文档保存在 `Request/archive/legacy-v1/`，只用于追溯，不参与解释当前行为。实现任务不需要通读 CR、历史 Gate、哈希或旧 DTO。

## 当前检出状态

以下是代码事实，不是完成率：

| 层级 | 当前状态 |
|---|---|
| Backend | Auth、用户/Break-glass、文件、财务、供应商、知识、审核、报告、工作台、依赖健康、OPS-005 与内部 metrics 均已有 Router → Service → Repository/Adapter 运行路径 |
| Database | accepted Alembic 单一 head 为 `20260816_023`，当前核心 Schema 与 ORM 覆盖 57/57 张表；这不等于生产迁移已执行 |
| Worker | Celery Dispatcher/Worker 已承载文件、合同/发票提取、知识索引/评测、审核与 PDF/XLSX 报告任务，并有恢复与真实依赖证据 |
| Frontend | 主要 P0 页面已接同源真实 API；文件、合同/发票、关联、供应商、知识/问答、审核与报告操作均有实现，不再以静态演示冒充业务状态 |
| AI | 默认关闭；批准的 local/test Profile 已接真实 MiniMax-M3 Chat、持久审计和合同/发票/RAG/风险解释/报告草稿原子采用；Embedding 仍为确定性 Hash |
| Infrastructure | 完整 local Compose、固定镜像、Nginx 自签名 TLS、first-org/admin、ClamAV、依赖健康、容器最小权限和 PG/MinIO 隔离备份恢复已实现并实跑；production Profile 仍未批准 |
| Acceptance | 隔离浏览器业务闭环、本地 Compose/安全/性能与受限真实 LLM smoke 已通过；固定正式报告已通过宿主/Backend 镜像语义一致、Poppler 渲染和 Microsoft Excel 实际只读打开；LibreOffice、屏幕阅读器/完整键盘、AC-001～AC-016、代表性 AI/检索集、真实 Embedding、正式 DAST、正式参考容量及 production 仍未执行 |

任务状态和证据以 `docs/testing/p0-traceability-matrix.csv` 及实际测试输出为准。旧表/API/工作包数量只作历史盘点，不是产品数量合同。

## 架构边界

- Frontend 只通过同源 `/api/v1` 访问 Backend。
- 依赖方向为 `Router → Service → Repository/Adapter`；Router 不直接访问数据库或模型。
- PostgreSQL 保存业务事实；MinIO 保存文件制品；Redis 与 Qdrant 只保存可恢复或派生数据。
- 长任务进入 Job/Worker；同步 API 只做短事务、鉴权、状态校验和任务受理。
- 已激活、发布或完成的版本不可原地覆盖。
- AI 不决定审批、权限、状态转换或确定性财务规则结果。

## 技术栈

- Backend：Python 3.10、FastAPI、Pydantic、SQLAlchemy 2、Alembic、Celery 5。
- Frontend：Vue 3、TypeScript、Vite、Pinia、Vue Router。
- Data/Infra：PostgreSQL、Redis、MinIO、Qdrant、Nginx、Docker Compose。

## 目录

```text
backend/   FastAPI Backend、领域代码、迁移和 Worker
frontend/  Vue 3 前端
  infra/     环境变量模板、最小 MinIO 与完整 local Compose
Request/   当前产品需求、技术规格和实施计划
docs/      工程运行手册、测试策略、追踪矩阵和历史资料
scripts/   可重复执行的本地验证脚本
tests/     合成测试资产
Demo/      静态视觉参考，不是生产代码或验收证据
```

## 安全配置

变量名和注入顺序以 [infra/env/.env.example](infra/env/.env.example) 为准。从源码仓库在主机直接运行 Backend/Worker 时，应用默认读取 `infra/env/.env`；显式参数、进程环境变量和运行时 Secret 文件依次优先于该文件。路径由源码位置解析，不依赖当前工作目录。Docker 镜像排除 `.env`，Compose/部署环境仍由启动器、环境变量或 Secret 机制注入。

完整本地栈的启动、停止、备份、隔离恢复与限制见 [完整本地栈运行手册](docs/runbooks/local-stack.md)；受保护指标的边界见 [内部 Metrics 运行手册](docs/runbooks/internal-metrics.md)。最短启动命令：

```powershell
.\scripts\start-local-stack.ps1 `
  -OrganizationName '本地测试组织' `
  -OrganizationUscc '91310000MA1K123456' `
  -OrganizationTaxNumber '91310000MA1K123456' `
  -AdminUsername 'local-admin' `
  -AdminDisplayName '本地管理员'
```

普通停止保留数据，`-Purge` 才会不可恢复地删除该项目卷和运行时 Secret：

```powershell
.\scripts\stop-local-stack.ps1
```

最小 local MinIO 以当前 PowerShell 进程为 secret 边界，不写 `.env` 或命令参数：

```powershell
. .\scripts\start-local-minio.ps1
# 在同一 PowerShell 进程中运行需要 MINIO_* 的本地服务或检查
. .\scripts\stop-local-minio.ps1
```

启动器只使用本机已缓存的批准镜像（`--pull never`），创建七个 Bucket，但应用身份当前仅获得 quarantine 写入与补偿删除权限；停止时保留数据卷并清除当前进程中的应用凭据。

启动器状态机可在不访问 Docker daemon 的情况下回归：

```powershell
.\scripts\test-local-minio-launchers.ps1
.\backend\.venv\Scripts\python.exe -m unittest discover -s .\scripts\tests -p test_bootstrap_local_minio.py
```

- 除上述 Backend/Worker 默认配置入口外，不读取真实 `.env`；任何组件都不得提交、打印或记录 `.env`、密码、Token、API Key、私钥或生产数据。
- 示例占位符故意不可运行；不要将它们改成看似真实的假值。
- 真实 Provider、生产环境、外网、真实数据和部署需要独立环境授权与验证。

## 本地验证

仓库与当前 Request 基线：

```powershell
.\scripts\setup-git-governance.ps1
.\scripts\verify-baseline.ps1
.\scripts\test-verify-baseline.ps1
```

测试资产：

```powershell
python scripts/generate_test_documents.py --check
.\scripts\verify-test-assets.ps1
.\scripts\test-verify-test-assets.ps1
```

Backend：

```powershell
Set-Location .\backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check app alembic\versions tests
.\.venv\Scripts\python.exe -m ruff format --check app alembic\versions tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

Frontend：

```powershell
Set-Location .\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
```

完整本地离线质量编排：

```powershell
.\scripts\test-verify-local-offline.ps1
.\scripts\verify-local-offline.ps1
```

这些命令不自动证明 Docker、真实 PostgreSQL 业务链、浏览器 E2E、Provider、远程分支保护、production 或 AC 通过。完整 local Compose、Worker 故障注入和三轮性能子集见 [本地栈运行手册](docs/runbooks/local-stack.md)；未运行的层级必须记录为 `NOT_RUN`。

## 数据库迁移

当前物理 Schema 以 accepted Alembic head 为准。安全执行、隔离测试库门禁和验证步骤见 [数据库迁移运行手册](docs/database-migrations.md)。

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
```

迁移只读取当前进程的 `DATABASE_URL`，不会自动加载 `.env`。破坏性往返测试必须使用明确标记为可丢弃的隔离 PostgreSQL 数据库。

## 结果表达

汇报时分别说明：

- 文档是否已定义。
- 代码是否已实现。
- 静态检查或测试是否实际通过。
- 运行时或端到端流程是否实际执行。
- AC、UAT 或 production 是否正式通过。

构建成功、静态页面、Mock、存活探针或离线测试都不能自动提升为业务闭环或正式验收。
