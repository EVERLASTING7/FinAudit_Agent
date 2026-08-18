# CR-021：百炼 Embedding 本地批准 Profile 与知识链接入

状态：`APPROVED BY CURRENT TASK / SYNCHRONIZED`

日期：2026-08-17

对应差异：`OQ-11`、`PROD-VS-03`、真实 Embedding Provider

## 1. 原因与授权

BOSS YHBX 在当前任务中明确指定使用已配置的阿里云百炼 Embedding，并要求新增批准 Policy、接入 Backend 与 Worker。本 CR 取代 `CR-019` 中“真实 Embedding 未批准”的 local/test 限制；production、部署和真实付费验收仍不在本次授权内。

## 2. 已批准 Profile

- Policy ID 固定为 `minimax-m3-bailian-qwen37-local-v1`，环境范围仅为 `local/test`，并继续包含既有 `MiniMax-M3` Chat Profile。
- Embedding 仅允许 OpenAI-compatible `POST /embeddings`，Base URL 固定为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型固定为 `qwen3.7-text-embedding`，Secret slot 固定为 `EMBEDDING_API_KEY`。
- 输出维度固定为 `1024`，请求必须显式发送 `dimensions=1024` 与 `encoding_format=float`；单批最多 `20` 条，单条由 Provider 限制为最多 `128000` Token。
- 出站只允许 HTTPS 与 `dashscope.aliyuncs.com`，继续执行 DNS 完整解析、保留地址拒绝、连接 peer 复核、禁系统代理、禁重定向和有界请求/响应；总 deadline 为 `30` 秒，单次调用不做 Adapter 内重试，Worker Job 只按既有 transient recovery 边界重试。
- 百炼北京地域公开价格快照按每百万输入 Token `500000 micro_cny` 记录，版本为 `bailian-qwen37-embedding-cny-2026-08-17`。模型名是 Provider 管理的 alias，不声称固定了 Provider 内部权重 revision。
- Policy 原始字节 SHA-256 与 canonical hash 由启动门禁固定；endpoint、模型、Secret 是否存在、维度、批次、deadline 和响应字节上限必须与 Settings 精确一致，否则 Backend/Worker 启动失败。
- 资料快照（2026-08-17）：[百炼文本向量模型规格与计费](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)、[OpenAI 兼容 Embedding 请求/响应](https://help.aliyun.com/en/model-studio/embedding-interfaces-compatible-with-openai)、[百炼服务地址](https://help.aliyun.com/en/model-studio/base-url)。

## 3. Backend/Worker 行为

- `AI_PROVIDER_CALLS_ENABLED=false` 时继续使用 `deterministic_hash_v1`；启用本 Profile 时，Backend RAG 查询、Worker 索引构建和检索评测统一通过 `AiGateway` 调用 `openai_embeddings_v1`。
- 新索引持久化实际 `adapter_id/model_id/vector_dimension/distance`。旧 Hash 索引不能被真实 Embedding 查询或原地覆盖，必须建立、验证并激活新索引版本。
- Worker 对同一批文本只调用 Provider 一次，并复用返回向量写入 Qdrant 和 PostgreSQL hash 事实；一致性复核读取已持久化向量 hash，不重复调用 Provider。
- Provider/网络错误只投影为稳定、脱敏错误码。RAG 返回 `service_degraded/RETRIEVAL_UNAVAILABLE`；Worker 按错误 disposition 决定既有 Job 是否可恢复。

## 4. 费用与审计边界

- 现有 AI EventSink、OPS-005 和预算字段以 `micro_usd` 为唯一货币语义，不能无汇率依据承载百炼 CNY 费用。本切片不得把 CNY 价格转换或伪报为 USD。
- 因此，本次实现提供 Policy 身份、Gateway 分派、网络/字节/deadline/批次门禁和 Provider usage 响应校验，但不宣称已完成 Embedding 的持久逐次费用审计或 currency-neutral 预算。若该能力进入正式验收，必须先扩展事件/数据库/API 的货币契约并迁移。

## 5. 验证与证据边界

- 零网络单元测试必须覆盖 Policy 防篡改、Settings 精确绑定、兼容路径、`dimensions` 请求字段、响应模型/维度/usage 校验、Gateway 错误映射和索引身份。
- `scripts/smoke_live_bailian_embedding.py` 是后续真实连通性验证的唯一有界入口：必须设置精确的一次性确认值并提供非占位 `EMBEDDING_API_KEY`，固定两条短合成文本、单次 Provider attempt、1024 维与 30 秒总 deadline；输出只包含模型/Policy 身份、向量数量与维度、Token、响应摘要和估算 `micro_cny`，不得输出密钥、向量或原始 Provider 响应。默认与“已确认但空密钥”负例已经零网络通过。
- 本任务未运行该真实 smoke，不产生费用，不证明 API Key 权限、余额、限流、DNS/TLS、Provider 返回兼容性、真实向量质量、Backend/Worker/Qdrant 实链、50/100 条检索质量、production 容量或正式 AC/UAT；这些均保持 `NOT_RUN`。

## 6. 回滚

- 将 `AI_PROVIDER_CALLS_ENABLED=false` 并恢复离线批准 Policy，即恢复确定性 Hash Embedding；不得让真实模型名与 Hash Adapter 混用。
- 已用真实 Embedding 构建的索引保留追溯，但在 Hash 模式下不会通过身份校验；切换模型、维度或 endpoint 必须新建索引版本，不能原地改写。

## 7. 后续验证说明

第 5 节记录的是 CR-021 落地当时的证据边界。BOSS 后续先单独授权首次 Provider 连通性 smoke，再另行授权一次同范围完整知识库 E2E；最新实跑事实记录在 `CR-022` 第 8～9 节。后续授权没有改变本 CR 的 local/test、no-fx、no-production 或正式质量门禁。
