# 需求入口

活跃开发规格已迁移到 [Request/README.md](../Request/README.md)。本页只保留兼容导航，不再维护另一套规则。

- [产品需求](../Request/PRODUCT_REQUIREMENTS.md)：范围、角色、业务流程、业务不变量和 AC。
- [技术规格](../Request/TECHNICAL_SPEC.md)：架构边界和机器事实来源。
- [实施计划](../Request/IMPLEMENTATION_PLAN.md)：`READY/BLOCKED` 切片、代码锚点和最小验证。
- [规格瘦身审计](specification-simplification.md)：历史问题和迁移依据，仅供追溯。

已实现 HTTP 以 OpenAPI 为准，当前物理数据库以 accepted Alembic head 为准，配置以 `.env.example`、`Settings` 和 Policy loader 为准，测试状态以追踪矩阵和可复现输出为准。文档不得复制这些机器事实形成第二套合同。
