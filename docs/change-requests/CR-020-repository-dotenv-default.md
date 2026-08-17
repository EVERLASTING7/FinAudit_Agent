# CR-020：本机源码仓库 dotenv 默认加载边界

状态：`APPROVED BY CURRENT TASK / SYNCHRONIZED`

日期：2026-08-17

## 1. 原因与授权

BOSS YHBX 在当前任务中明确要求 Backend/Worker 自动且默认加载仓库内的 `infra/env/.env`。本 CR 记录该配置与 Secret 边界变化，并把决定同步到活跃技术规格和机器事实源。

## 2. 已批准决定

- 仅当 `config.py` 能验证自己位于源码仓库的 `backend/app/core/` 布局时，`Settings` 默认加载由模块绝对定位的 `infra/env/.env`；行为不依赖当前工作目录。
- 配置优先级固定为显式初始化参数 → 进程环境变量 → 运行时 Secret 文件 → 仓库 `.env` → 字段默认值；`.env` 为空的值继续忽略。
- `.env` 保持 Git 忽略，禁止提交、回显或写入日志。Docker 构建继续通过 `.dockerignore` 排除 `.env`，Compose/production 保持运行时环境变量与只读 Secret mount 注入。
- 本决定只改变本机源码运行的配置来源，不修改 AI Policy，不设置 `AI_PROVIDER_CALLS_ENABLED=true`，也不批准真实 Embedding、部署或 production。

## 3. 验证

- 单元测试必须固定默认路径，并证明进程环境变量和运行时 Secret 文件优先于 dotenv。
- 需要纯环境或纯 Secret 来源的负例测试必须显式传入 `_env_file=None`，避免受开发者本机配置污染。
- Ruff、聚焦 Pytest 和 mypy 必须通过；检查输出不得包含真实 `.env` 内容或 Secret 值。

## 4. 回滚

- 回滚时将 `Settings.model_config.env_file` 恢复为 `None`，删除自定义来源顺序，并同步恢复 README、技术规格和测试。
- 回滚不删除或改写用户现有 `.env`，不改变 Docker/production Secret。
