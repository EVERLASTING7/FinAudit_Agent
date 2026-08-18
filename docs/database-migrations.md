# 数据库迁移运行手册

本手册只说明当前 checkout 的可执行迁移方式。产品语义见 [`Request/PRODUCT_REQUIREMENTS.md`](../Request/PRODUCT_REQUIREMENTS.md)，数据库边界与阻塞见 [`Request/TECHNICAL_SPEC.md`](../Request/TECHNICAL_SPEC.md)，实施顺序见 [`Request/IMPLEMENTATION_PLAN.md`](../Request/IMPLEMENTATION_PLAN.md)。旧版全表账本已归档到 `docs/archive/legacy-v1/database-migrations.md`，不参与当前实现。

## 当前事实

- 当前 accepted Alembic head：`20260817_024`。
- 当前 ORM 与运行时 catalog 覆盖 57/57 张核心物理表；`021` 封锁检索状态旁路，`022` 闭合未确认发票空币种，`023` 增加风险解释与报告草稿持久事实，`024` 增加 Event v2 的 USD/CNY 通用 microunit 费用列；四者均不增加表。
- 当前物理 Schema 的唯一来源：`backend/alembic/versions/` 的单一线性历史。
- 当前 ORM 投影：`backend/app/models/`。
- 当前 head 覆盖的对象只是已实现切片；目标业务对象或历史表清单不代表表已存在。
- PostgreSQL 是业务事实来源。Redis、Qdrant、日志和内存状态不得代替迁移或约束。
- 应用启动不会自动执行迁移，也不会自动加载 `.env`。

检查当前 revision 图：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic history
```

必须只有一个 head。发现分支、merge 或断链时先修正 revision 图，不得用 `stamp head` 掩盖。

## 新增迁移的最短流程

1. 从 `IMPLEMENTATION_PLAN.md` 选择一个 `READY` 切片。
2. 明确该切片的用户结果、数据语义、权限、状态和回滚方式。
3. 如该切片命中 `TECHNICAL_SPEC.md` 的 `BLOCKED` 条目，只解决该最小歧义；不要停掉无关开发。
4. 新增一个线性 Alembic revision，并同步 SQLAlchemy 模型。
5. 为约束、并发竞争、升级和安全回退写聚焦测试。
6. 在隔离的可丢弃 PostgreSQL 16 测试库运行验证。
7. 更新追踪矩阵中的实际状态和证据。

不需要因为新增已批准范围内的表、列、约束或索引，再同步历史九份文档或创建形式化回执。只有改变产品范围、外部兼容性、持久化业务语义、状态、权限、安全边界或验收阈值时，才需要简短决定或 CR。

## 迁移实现规则

- 只从当前进程环境读取 `DATABASE_URL`；不得读取或打印真实 `.env`。
- URL 必须使用 `postgresql+psycopg`，并通过项目现有安全解析器。
- 禁止用 query 参数覆盖 host、port、database、service 或其他连接目标。
- Session 使用 UTC 和 UTF-8；日志隐藏 SQL 参数和凭据。
- Schema 变化只通过新的 Alembic revision完成，不在应用启动时临时建表。
- 一个 revision 只服务一个可解释切片；不要为了满足历史表数合并无关对象。
- PostgreSQL 约束负责可可靠表达的唯一性、引用完整性、排斥和状态不变量。
- Service 负责权限、跨资源业务规则和事务边界；不得用应用内存绕过数据库竞争。
- 条件唯一、状态转换或追加写行为需要并发测试，不能只检查生成 SQL。
- 已有业务数据的破坏性变化必须有兼容窗口、数据迁移和回滚结论。
- 降级不得使用 `CASCADE` 静默丢失依赖；无法安全回退时应明确失败关闭。
- 不创建默认组织、管理员、密码、真实规则或真实业务数据。

`20260815_021` 在建触发器前检查既有活动索引是否有已通过的正式评测、已批准评测集是否满足 5/50/100 用例门槛、已结束评测运行是否与逐案结果一致；任一不一致均以 `23514` 原子失败。随后三个 `BEFORE INSERT` 触发器分别强制 `building`、`draft`、`running` 初始状态，防止直接写入 `active`、`approved` 或 `passed` 绕过既有转换约束。

`20260816_022` 移除 invoices.currency 的无证据 `CNY` 默认并允许未确认发票为空，同时增加 confirmed 发票 currency 必须非空的检查约束。upgrade/downgrade 都先设置事务级 5 秒 `lock_timeout`，避免现有读锁使 DDL 无限等待；downgrade 会把遗留空值回填为 CNY，只能在已确认该语义回退可接受的受控环境执行。

`20260816_023` 为 `audit_risks` 和 `audit_reports` 增加 AI `status/json/sha256` 三元组及一致性约束；报告触发器只允许 `generating` 内部从 `disabled` 原子转到 `succeeded|degraded`，其他报告状态转换要求 AI payload 不变，ready/outdated 制品不可变规则继续生效。downgrade 先恢复 v1 报告触发器，再删除新增列。

`20260817_024` 保留可空 legacy `reserved_cost_micro_usd` 供 Event v1 历史回放，并为 `ai_call_logs` 增加 `cost_currency`、`reserved_cost_microunits`、`actual_cost_microunits`。Event v2 外部计费只允许 USD/CNY，内部不计费必须使用空币种和零金额；禁止 v1/v2 字段混填、隐式汇率换算或跨币种汇总。upgrade 在存在未完成 AI 审计行或未发布 AI Outbox 时以 `55000` 失败关闭；downgrade 在存在任何 v2 Event/日志时失败关闭，不把 CNY 数据转换为 USD。

## 安全执行

迁移只允许在受信任进程显式注入 DSN 后执行：

```powershell
Set-Location .\backend
$env:DATABASE_URL = '<由受信任环境注入，不写入仓库或日志>'
.\.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:DATABASE_URL
```

不要把示例占位符当成可运行配置。执行前确认实际目标不是开发共享库或生产库。

需要执行破坏性往返测试时，必须同时满足：

- `TEST_DATABASE_URL` 指向 loopback 上的专用可丢弃数据库。
- 数据库名符合项目测试命名门禁。
- URL 没有可覆盖目标的 query 参数。
- 显式重置确认值已设置。
- 数据库带有可丢弃标记。

缺少任一条件就停止；不得退回普通 `DATABASE_URL`。

## 验证

静态和单元检查：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest tests\unit\test_migration_config.py tests\unit\test_migration_graph.py -q
.\.venv\Scripts\python.exe -m ruff check app alembic\versions tests
.\.venv\Scripts\python.exe -m ruff format --check app alembic\versions tests
```

显式 PostgreSQL current-head 门禁：

```powershell
Set-Location ..
.\scripts\test-verify-postgresql-current-head.ps1
.\scripts\verify-postgresql-current-head.ps1
```

2026-08-17 当前 checkout 的唯一 head `20260817_024` 已在 PostgreSQL 16.14 上完成 Full wrapper 双轮验证：完整 `integration/database` 目录每轮 146 项，分别输出 `POSTGRESQL_CURRENT_HEAD_RUN=1/2 status=ok`、`POSTGRESQL_CURRENT_HEAD_RUN=2/2 status=ok` 与 `POSTGRESQL_CURRENT_HEAD=PASS`，专用 current-head 容器最终为 0。验证包含非空 v1 历史保留、pending/Outbox 升级阻断、v1/v2 字段混用阻断、CNY v2 投影和 v2 downgrade 阻断；该结果不等于 production migration、备份恢复、容量或正式 AC 通过。

验证至少覆盖：

- `base → head → base → head` 可重复执行。
- ORM、迁移和运行时 catalog 对齐。
- 约束和关键触发器行为正确。
- 并发竞争只有允许的事务成功。
- 升级或降级失败不留下半表、半约束或错误 revision。
- 输出不包含 DSN、secret 或真实业务数据。

只有实际运行过的检查才能记为通过。迁移测试通过只证明 storage-schema 范围，不证明 Repository、Service、API、Worker、真实 ACL、业务流程或 AC 完成。

## 当前停止边界

以下情况停止对应迁移，不扩大为全项目停工：

- 字段或状态会改变用户可见行为，但 `PRODUCT_REQUIREMENTS.md` 没有唯一结论。
- `TECHNICAL_SPEC.md` 明确标记该持久化语义为 `BLOCKED`。
- 目标需要父表或权限事实，但 accepted head 中尚不存在且本切片未包含。
- 无法证明升级原子性、数据保留或安全回退。
- 只能依赖历史覆盖段、候选 CR、固定表数或不可得签署材料才能解释设计。

关闭阻断时只产出一个前向决定、对应 SSOT 更新和可执行测试；不恢复历史补丁栈。
