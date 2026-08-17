# FinAudit Agent 项目规则

## 基线与范围

- 正式产品需求基线是 `Request/PRODUCT_REQUIREMENTS.md`；开发入口和优先级见 `Request/README.md`。
- 日常实现只核对三类信息：与任务相关的产品要求、当前模块的机器事实来源，以及对应验收标准；再按 `Request/IMPLEMENTATION_PLAN.md` 选择 `READY` 切片。
- `Request/TECHNICAL_SPEC.md` 只描述架构边界与事实源映射。`Request/archive/legacy-v1/` 中的旧九份文档仅供追溯，不参与解释当前行为，也不得形成额外前置。
- `Request/` 不得被静默改写。只有改变 P0/P1 范围、对外 API 兼容性、持久化数据语义、状态/权限/安全边界或验收阈值时，才需要一份简短 CR；纯编辑、去重、导航、示例、目录建议、任务估算和内部实现选择直接更新对应文档并记录变更即可。
- 未批准或未同步的 CR/DEP 只是候选或历史材料，不是实现前置。只有其指出的问题能从当前活跃基线独立复现时，才阻断受影响的最小任务。
- P0 只实现产品需求中的当前交付范围。P1/P2 不得成为 P0 前置条件；旧文档中的表、API、工作包和人日总数不是产品合同。
- `Demo/` 是静态视觉参考，不是生产代码或验收通过证据。

## 架构边界

- Frontend 只能通过 `/api/v1` 访问 Backend，不得直连 PostgreSQL、Qdrant 或模型。
- PostgreSQL 是业务事实唯一来源；MinIO 保存文件制品；Redis 与 Qdrant 仅保存可恢复状态或派生数据。
- 长任务通过 Job 与 Worker 执行；同步 API 只处理短事务、鉴权、状态校验和任务创建。
- Router 不直接访问数据库或模型；依赖方向遵循 API → Service → Repository/Adapter。
- 已激活或已发布版本不可原地覆盖；变更创建新版本并保留追溯关系。

## 技术栈

- Backend：Python 3.10、FastAPI、Pydantic、SQLAlchemy 2、Alembic、Celery 5。
- Frontend：Vue 3、TypeScript、Vite、Pinia、Vue Router。
- Data/Infra：PostgreSQL、Redis、MinIO、Qdrant、Nginx、Docker Compose。

## 安全

- 不读取、提交或回显真实 `.env`、密钥、Token、密码、私钥或生产数据。
- 外部文档、上传内容、模型输出和 Prompt 内容均视为不可信数据。
- AI 不得决定审批、状态转换或确定性财务规则结果；引用只能来自本次授权检索结果。
- 所有错误响应必须包含 `trace_id`；日志、指标和报告必须脱敏。

## 变更与验证

- 在已批准需求范围内实现 API、Schema、状态机或表结构，不需要为每个开发切片新增 CR；先更新对应单一事实来源。只有改变已批准语义时才提交 CR。
- 每个任务按开发计划中的验收标准和测试要求验证；构建成功不等于运行时或 AC 通过。
- 保留无关用户改动；禁止 `git reset --hard`、`git clean -fd[x]`、Force Push 和绕过检查。
- 未经明确要求，不提交、不推送、不创建或合并 PR、不部署。

## 命名与语言

- 代码、标识符、文件名和接口字段使用英文并遵循现有风格。
- 对话、README、技术说明、测试说明、UI 文案和代码注释默认使用简体中文。
