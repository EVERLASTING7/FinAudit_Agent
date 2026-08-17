# CR-002：关闭 AI-001 传输、降级与日志契约阻断项

状态：`DRAFT`（未批准）  
决策状态：`PROPOSED`（以下内容仅为待审批推荐方案）  
CR 版本：`CR-002-R4`  
提出日期：2026-08-06  
影响范围：需求、架构、AI/RAG、部署、测试、数据库与开发任务计划

> 本 CR 不修改正式需求基线，不代表任何推荐方案已经生效。只有需求、架构、AI、运维和安全负责人逐项批准、完成 `Request/` 内受影响事实来源同步，并对目标环境的 Profile/Policy 值另行签署后，才允许在该环境范围内实现或启用真实 Provider 调用、自动重试、fallback、熔断或 AI 调用日志持久化。

## 1. 背景与当前边界

`AI-001` 要求统一 LLM/Embedding 接口、模型路由、超时、重试、熔断、限流、Trace 传播和外部适配器。当前文档对以下内容存在冲突或缺失：

- AI 详细设计与系统架构对每类调用的总超时、最大尝试次数和 Embedding 超时定义不同。
- AI 详细设计只写“部分 5xx”，系统架构明确列出 `500/502/503/504`。
- 系统架构允许上下文过长时条件重试并截断或压缩，AI 详细设计要求拒绝调用且不得静默截断关键证据。
- 需求、架构与 AI 详细设计对结构化输出的模型修复次数口径不一致。
- `AI-001` 与 `AI-005` 同时指向 `ai_call_logs` 和 OPS-005，但 `AI-001` 没有 `BASE-005` 前置依赖。
- 文档只写“OpenAI 兼容”，未冻结具体端点、请求/响应包络、认证、重定向、代理、TLS 和响应大小边界。
- AI 详细设计为合同、发票、风险解释和 RAG 明确列出 `LLM_FALLBACK_MODEL`，部署样例却允许该值为空，未定义启动时是拒绝还是降级为单候选。
- 文档没有定义主备切换、transport retry 和最多两次结构修复共享的总 Provider 请求、Token 与费用预算。

当前工作区已经存在 provider-neutral 内存契约、调用方显式注入的无默认值策略、显式目标单次分派、不触发网络或 fallback 的纯路由配置映射、system/user 内容分离的 LLM 请求边界、有序批量 Embedding 的输入输出边界，以及携带 `trace_id` 的脱敏 Gateway 边界错误。本段只记录当前快照，不授予实施、保留或扩展权限；这些切片只有在逐项证明属于既有已批准基线、且不采纳 AI-D-001～AI-D-008 任一待批决策时，才能作为非 CR 变更继续。否则必须停止在设计或测试阶段并按正式变更流程处理。禁止把这些静态或离线切片描述为真实模型可用、完整 `AI-001` 或任何 AC 已通过；当前快照不冻结 HTTP 包络、向量维度、批量或 Token 上限、网络传输、重试或持久化。

本 CR 区分协议合同值、测试环境初始候选值和生产容量值。策略必须形成不可变的 `policy_version + policy_hash`，调用事件必须记录二者；`policy_hash` 固定为规范化 Policy 按 RFC 8785 JSON Canonicalization Scheme 生成 UTF-8 bytes 后计算的 SHA-256 小写十六进制，只包含 secret slot 标识，绝不包含或读取 secret 值。初始配置固定为 `AI_POLICY_VERSION=1`、`AI_PROVIDER_CALLS_ENABLED=false`。合同级签署并同步 `Request/` 后只允许实现和执行离线 Mock；另有 `environment_scope='fixed_test_provider'` 的完整值与审批记录后，才允许在隔离测试环境启用网络；固定测试 Provider 通过且生产值以 `environment_scope='production'` 逐项签署前，不得在生产启用。CR 获批、`Request/` 同步、代码实现、真实 Provider 验证和生产放行是五项不同证据。

## 2. 决策摘要

| 决策 | Gap | 待审批推荐方案 | 直接影响 |
|---|---|---|---|
| AI-D-001 | GAP-032 | P0 Provider Profile 固定为非流式 Chat Completions 与 Embeddings 两个兼容端点 | Adapter 有唯一可测试的 HTTP 契约 |
| AI-D-002 | GAP-022/GAP-033 | 按调用类型配置连接超时、总超时、跨主备逻辑尝试上限和业务操作总预算，不再使用单一 LLM 总值覆盖全部场景 | 合同、发票、RAG、Embedding 不互相污染策略或形成乘法调用 |
| AI-D-003 | GAP-022 | 网络错误、429、`500/502/503/504` 可有限重试；上下文超限不得由 Adapter 静默截断 | 失败分类和证据完整性可验证 |
| AI-D-004 | GAP-022 | fallback 只在允许的技术失败耗尽后执行；Embedding 禁止自动跨模型或跨维度 fallback | 避免业务错误被错误掩盖 |
| AI-D-005 | GAP-022 | 熔断按 endpoint + model 隔离；Redis 不可用时外部计费 Profile fail closed，仅批准的内部/测试 Profile 可进入进程内受限模式 | 避免单模型故障拖垮全部调用或失去分布式保护后继续付费调用 |
| AI-D-006 | GAP-029 | `AI-001` 定义脱敏事件并只依赖 Sink Port；`AI-005` 独占发送前 durable reserve、完成投递、持久化、补偿、查询和 OPS-005 | 消除所有权重叠并避免不可审计的成功结果 |
| AI-D-007 | GAP-030 | 首次生成不计为“修复”；确定性清理不调用模型；最多允许两次模型修复调用 | 统一三份文档的次数口径 |
| AI-D-008 | GAP-032 | 固定出站安全边界、响应上限、Trace 和脱敏规则 | 降低 SSRF、代理泄漏和超大响应风险 |

## 3. 待审批推荐合同

### 3.1 AI-D-001：P0 Provider Profile

P0 采用两个明确的非流式 Provider Profile：LLM 使用 `openai-chat-completions-v1`，Embedding 使用 `openai-embeddings-v1`。每个目标必须显式配置 `base_url`、`model_id`、`allowed_response_model_ids`、`auth_scheme='bearer'`、运行时 secret 引用、`context_window_tokens`；Embedding 目标还必须配置 `embedding_dimension`。任何字段缺失、空白或与路由配置不一致均启动失败。

| 能力 | 方法与相对路径 | HTTP 成功条件 |
|---|---|---|
| LLM | `POST /chat/completions` | `200 application/json`，且严格满足下述 Chat 响应包络 |
| Embedding | `POST /embeddings` | `200 application/json`，且严格满足下述 Embedding 响应包络 |

本节的 `application/json` 按 MIME media type 判断，大小写不敏感并允许合法参数（例如 `charset=utf-8`）；其他 media type 一律拒绝。

`base_url` 只表示版本根，例如 `https://provider.example/v1` 或受控内部 `http://vllm:8000/v1`；Adapter 只能追加上表固定相对路径。请求 Header 固定为 `Authorization: Bearer <runtime-secret>`、`Content-Type: application/json`、`Accept: application/json`，以及第 3.8 节允许的 `traceparent`。内部 vLLM Profile 同样必须通过 `--api-key` 启用 Bearer 认证；P0 不提供 `auth_scheme='none'`。

Chat 请求结构固定如下；以下 JSON 是“合同字段提取”的具体示例，其他调用类型只替换已批准的参数值和消息正文，不改变字段集合或类型：

```json
{
  "model": "configured-model-id",
  "messages": [
    {"role": "system", "content": "non-empty string"},
    {"role": "user", "content": "non-empty string"}
  ],
  "temperature": 0.0,
  "top_p": 0.1,
  "max_tokens": 2500,
  "n": 1,
  "stream": false
}
```

- 调用参数映射固定为：合同字段提取 `temperature=0.0/top_p=0.1/max_tokens=2500`，发票字段提取 `0.0/0.1/2500`，风险解释 `0.1/0.8/1600`，RAG 回答 `0.1/0.8/1800`，报告草稿 `0.2/0.9/3000`。
- `messages` 必须非空；`role` 只允许 `system/user`，`content` 只允许非空字符串，不接受历史 assistant 消息、多模态数组、工具消息或任意扩展字段。
- `temperature/top_p/max_tokens` 必须取对应调用类型的已批准值；`n` 必须为 `1`，`stream` 必须为 `false`。
- 成功响应必须存在且只存在一个 `choices[0]`；其 `index=0`、`message.role='assistant'`、`message.content` 为非空字符串，响应 `model` 必须位于 `allowed_response_model_ids`。只有 `finish_reason='stop'` 可进入后续校验；`length` 映射为 `output_truncated`，`content_filter` 映射为 `content_rejected`，其余值均为 `invalid_response`。
- 成功响应必须包含非负整数 `usage.prompt_tokens`、`usage.completion_tokens` 和 `usage.total_tokens`，且总数与前两者之和一致；缺失或不一致按 `invalid_response` 处理，不能绕过预算门禁。

Embedding 请求的唯一包络为：

```json
{
  "model": "configured-embedding-model-id",
  "input": ["first non-empty string", "second non-empty string"],
  "encoding_format": "float"
}
```

- `input` 必须是有序、非空字符串数组；P0 不接受单字符串、Token ID 数组、Base64 或 Provider 扩展输入。
- 成功响应的 `model` 必须位于 `allowed_response_model_ids`，`data` 数量必须等于输入数量；每项必须包含唯一整数 `index` 和 `embedding`，索引集合必须恰好为 `0..N-1`，Adapter 按 `index` 恢复输入顺序。
- 每个向量只允许有限 JSON number，长度必须等于 Profile 的 `embedding_dimension`；`NaN/Infinity`、布尔值、缺项、重复/越界索引或维度漂移均按 `invalid_response` 处理。
- 成功响应必须包含非负整数 `usage.prompt_tokens` 和 `usage.total_tokens`，二者必须相等。

HTTP 分类优先级固定如下：只有 HTTP 200 可以进入成功包络校验；201/202/204 或其他非 200 的 2xx 统一为不可重试 `invalid_response`。非 2xx 始终先按状态码执行第 3.3 节的重试分类，错误正文不得把 429 或 `500/502/503/504` 降成不可重试，也不得把其他状态升级为可重试。

非 2xx 的可选诊断包络为 OpenAI 兼容 `{"error":{"message":"...","type":"...","param":null,"code":"..."}}`：`message` 为必需非空字符串，`type/code` 为可选字符串，`param` 为可选字符串或 `null`；其他字段不参与决策。正文为空、非 JSON、Content-Type 错误、字段缺失或超限时，只丢弃诊断正文并保留 HTTP 状态分类。Adapter 不得记录 `message` 原文，只能按下列精确规则产生安全子分类，禁止解析自由文本猜测：

- HTTP 400 且 `error.type` 或 `error.code` 精确为 `context_length_exceeded/context_window_exceeded/max_context_length_exceeded` 时映射 `context_limit`；
- HTTP 400 或 403 且 `error.type` 或 `error.code` 精确为 `content_policy_violation/content_filter/safety_violation` 时映射 `content_rejected`；
- 其他 4xx 保持 `client_error`，其他非 2xx 保持状态码对应分类。

HTTP 200 的无效 JSON、错误 Content-Type、缺失字段、模型 ID 漂移或超限响应才统一按 `invalid_response` 处理。

P0 不实现流式响应、Responses API、`response_format`、工具调用、浏览器工具或任意 Provider 自定义扩展；结构化输出只通过版本化 Prompt 约束并由 AI-002 本地校验。不同协议必须新增 Adapter/Profile 和独立契约测试，不得在同一解析器中猜测多种响应形态。API Key 只进入运行时 Authorization Header，不进入请求 DTO、异常、日志、指标、Trace 属性或持久化事件。

备选方案：

- 若目标 Provider 只支持 Responses API，则新增独立 `responses-compatible` Profile，并提供独立请求、响应、错误与安全契约；不得把它冒充 Chat Completions。
- 若锁定的 vLLM/Provider 版本不能返回本节必需字段，则该目标不得启用；只能通过后续 CR 修改共同子集，不能按 Provider 名称散布条件分支或宽松解析。

### 3.2 AI-D-002：每类调用的 Transport Policy

以下均为**待审批的精确初始值**，只用于批准后的测试环境和首个受控 Provider 基线，不是性能或成本验收结论：

| 调用类型 | 连接超时 | 业务操作总截止时间 | 单次逻辑生成的固定尝试序列 | 业务操作 Provider 请求总上限 | 主模型配置 | 备用模型 |
|---|---:|---:|---|---:|---|---|
| 合同字段提取 | 5 秒 | 120 秒 | 主目标 1 次 → 同目标 retry 1 次 → 备用目标 1 次 | 6 | `LLM_EXTRACTION_MODEL` | `LLM_FALLBACK_MODEL`（必填） |
| 发票字段提取 | 5 秒 | 60 秒 | 主目标 1 次 → 同目标 retry 1 次 → 备用目标 1 次 | 6 | `LLM_EXTRACTION_MODEL` | `LLM_FALLBACK_MODEL`（必填） |
| 风险解释 | 5 秒 | 60 秒 | 主目标 1 次 → 同目标 retry 1 次 → 备用目标 1 次 | 6 | `LLM_GENERATION_MODEL` | `LLM_FALLBACK_MODEL`（必填） |
| RAG 回答 | 5 秒 | 90 秒 | 主目标 1 次 → 同目标 retry 1 次 → 备用目标 1 次 | 6 | `LLM_GENERATION_MODEL` | `LLM_FALLBACK_MODEL`（必填） |
| 报告草稿 | 5 秒 | 90 秒 | 默认主目标 1 次 → 同目标 retry 1 次；显式启用 fallback 时再追加备用目标 1 次 | 6 | `LLM_GENERATION_MODEL` | 由独立严格布尔配置显式决定 |
| Embedding 单批 | 5 秒 | 30 秒 | 同一目标最多 3 次；无 fallback | 3 | `EMBEDDING_MODEL` | 无 |

尝试顺序合同：

- LLM 的 `max_attempts=3`、`max_same_target_attempts=2`；未启用 fallback 的报告草稿为 `max_attempts=2`。Embedding 为 `max_attempts=max_same_target_attempts=3`。`max_attempts` 包含首次请求，禁止再使用语义相反的 `max_retries`。
- 只有第 3.3 节标记为可重试的结果才能进入下一步；主目标出现不可重试错误时立即停止，不消费为 fallback 预留的格数，也不尝试备用目标。
- 主目标熔断器在发送前已打开时，跳过两个主目标步骤且不计 HTTP 请求，最多调用备用目标一次；不得把跳过的格数转成备用目标 retry。
- 主目标第一次调用成功后立即停止；第一次调用为可重试错误时最多再调用同一目标一次；仍为可重试错误或等待会超过截止时间时，才允许调用备用目标一次。备用目标失败后不再 retry 或回切主目标。
- `max_provider_attempts_per_business_operation` 覆盖首次生成、全部 transport retry、主备目标和最多两次模型修复；任何 HTTP 请求在发送前消耗一格。结构化调用在决定是否执行 retry/fallback 前，必须为每个尚未开始但仍允许的模型修复各保留一格，避免前序重试耗尽第二次修复预算。
- 前四类 LLM 的 `LLM_FALLBACK_MODEL` 为构建 P0 路由的必需配置，缺失、空白或与对应主模型相同均启动失败；报告草稿是否携带该候选必须由独立严格布尔配置显式决定。
- 总截止时间从业务操作开始计时，覆盖排队、熔断/限流判断、退避、全部 HTTP 请求、响应读取与解析；剩余时间不足以完成连接超时和最小处理余量时不得开始下一次尝试。

首个预算 Profile 的待审批值如下；Token 为所有实际 HTTP 请求的累计值，费用使用整数 `micro_usd`（百万分之一美元）计算，禁止二进制浮点：

| 调用类型 | 单请求输入 Token 上限 | 单请求输出 Token 上限 | 业务操作总 Token 上限 | 外部计费 Provider 单操作费用上限 |
|---|---:|---:|---:|---:|
| 合同字段提取 | 32768 | 2500 | 212000 | `500000 micro_usd`（0.50 USD） |
| 发票字段提取 | 16384 | 2500 | 114000 | `250000 micro_usd`（0.25 USD） |
| 风险解释 | 16384 | 1600 | 108000 | `250000 micro_usd`（0.25 USD） |
| RAG 回答 | 16384 | 1800 | 110000 | `250000 micro_usd`（0.25 USD） |
| 报告草稿 | 16384 | 3000 | 117000 | `250000 micro_usd`（0.25 USD） |
| Embedding 单批 | 16384 | 0 | 50000 | `50000 micro_usd`（0.05 USD） |

预算执行合同：

- 每个模型目标必须配置版本化的 `context_window_tokens`、Tokenizer 标识和哈希；外部计费目标还必须配置 `pricing_version`、每百万输入/输出 Token 的整数 `micro_usd` 单价。内部不计费目标显式配置 `billing_mode='internal_unmetered'` 和零价格，不得用缺失价格伪装免费。
- 发送前使用锁定 Tokenizer 计算完整请求输入，并按本次 `max_tokens` 做最坏情况预留；必须同时满足单请求上限、`input + max_tokens <= context_window_tokens`、业务操作剩余总 Token 和费用上限。Tokenizer、价格或任一上限未知时 fail closed。
- 响应后以第 3.1 节强制返回的 `usage` 对账并累计实际 Token/费用；Provider 报告值异常时把响应视为无效，后续请求不得继续消耗预算。
- 两个请求计数器、总截止时间、Token 和费用上限同时生效，以先耗尽者为准；没有剩余预算时不得开始 retry、fallback 或 Schema repair。
- 五类 LLM 输出上限沿用 AI 详细设计 3.2 的建议值；Embedding 输出 Token 上限 0、输入、总 Token 和费用上限是本 CR 新增的保守候选值，必须在审批记录中逐表签署。任何一项被拒绝或留空时 AI-D-002 保持未决，真实调用继续 fail closed。
- 外部 USD 计费 Profile 的单请求费用固定按 `ceil((input_tokens × input_price_micro_usd_per_million + output_tokens × output_price_micro_usd_per_million) / 1000000)` 计算，再把每个物理请求已向上取整的整数相加；发送前以输入估算和最大输出 Token 使用同一公式做最坏预留。非 USD 计费、阶梯价、缓存价或其他公式在 P0 不受支持，必须保持禁用并通过后续 CR 新增独立价格 Profile，不能进行隐式汇率转换。
- 最终值必须通过固定模型、固定数据集、锁定价格版本和参考硬件验证后以新版本配置发布；不得在代码中硬编码为不可变常量或无审计地调高。

### 3.3 AI-D-003：错误分类与重试

| 类别 | Adapter 结果 | 是否允许同目标重试 | 说明 |
|---|---|---:|---|
| 连接失败、连接超时、读取超时 | `transient` | 是 | 受总截止时间限制 |
| HTTP 429 | `rate_limited` | 是 | 优先使用合法 `Retry-After`，再与本地退避取较大值 |
| HTTP 500/502/503/504 | `server_error` | 是 | 其他 5xx 默认不重试，需单独 CR |
| HTTP 400/401/403/404 | `client_error` | 否 | 请求、凭据、权限或配置错误 |
| TLS/证书失败、被禁止 DNS/IP、代理或重定向 | `provider_configuration_error` | 否 | 安全边界失败，不通过重试绕过 |
| 上下文超限 | `context_limit` | 否 | Adapter 不截断、不压缩、不改变证据 |
| 响应非 JSON、结构缺失或向量非法 | `invalid_response` | 否 | 由 AI-002 或上层业务决定是否生成新请求 |
| 内容安全拒绝 | `content_rejected` | 否 | 不改写为“无答案”或普通 4xx |

每次真实 HTTP 发送前必须依次检查业务操作请求余量、当前逻辑生成余量、总截止时间、Token/费用余量、熔断器和限流器；任一门禁失败均不得发送。

本地退避固定为 `base=1 秒`、`multiplier=2`、`max=30 秒`、`jitter_ratio=0.2`。`Retry-After` 同时支持非负十进制秒数和 HTTP-date；过去日期按 0 秒处理，非法值忽略。等待时间取合法 `Retry-After` 与本地退避的较大值；如果该值超过 30 秒或剩余总截止时间，不得提前重试同一目标，只能按第 3.4 节评估 fallback 或业务降级。抖动不得把合法 `Retry-After` 缩短。测试必须注入时钟和随机源，不执行真实等待。

上下文超限只能由上层基于业务证据规则创建一个新的、可审计请求。任何压缩、裁剪或分批策略必须证明不会删除关键证据，并记录新请求与原请求的关联；Adapter 不得静默修改输入。

### 3.4 AI-D-004：fallback 与业务降级

- 主目标的允许技术重试全部耗尽，或对应熔断器已打开时，才可尝试备用目标。
- fallback 不获得新的 transport 尝试预算；主目标、同目标 retry 和备用目标共同消耗本次逻辑生成及业务操作的两个计数器。
- 主目标熔断器已打开时直接评估一次备用目标；备用目标熔断、预算不足或失败时立即进入业务降级，不回切主目标。
- `client_error`、`context_limit`、结构化 Schema 错误、内容安全拒绝、权限过滤失败和引用校验失败不得触发自动 fallback。
- 备用目标必须属于相同调用类型，拥有独立 endpoint/model 身份和独立熔断状态。
- 主、备模型必须使用同一输出契约；切换模型不得改变业务 DTO。
- 报告草稿只有在路由配置显式启用时才携带备用候选；未启用或备用模型为空时直接使用确定性报告模板，不从全局备用模型设置推断行为。
- Embedding 不允许自动跨模型、跨版本或跨维度 fallback。候选索引构建失败时保留旧活动索引。
- fallback 失败后的业务降级由调用方显式处理：字段提取进入人工确认，风险解释保留规则结果，RAG 返回不可用或证据式拒答，报告使用确定性模板。
- 每次结果必须携带实际目标、是否 fallback、尝试次数和脱敏失败分类；不得把备用成功记录成主模型成功。
- AI-002 的修复请求固定使用产生非法结构的实际目标；Schema 错误本身不触发 fallback。修复请求遇到可重试技术错误时最多同目标 retry 一次，不在修复内部再次跨目标 fallback。

备选方案：若审批方把单次逻辑生成上限改为 2，必须在“主目标 → 同目标 retry（无 fallback）”与“主目标 → 备用目标（无同目标 retry）”中明确选择一种；不得同时宣称两种能力可用。

### 3.5 AI-D-005：熔断与限流所有权

- 熔断键固定为 `adapter_id + endpoint_id + model_id`，不得按整个 AI Gateway 使用一个全局熔断器；调用类型不进入熔断键，因为这里记录目标 transport 健康，调用类型隔离由独立限流池承担。
- 只把连接/读取超时、429 和批准的 `500/502/503/504` 计入技术失败；业务拒答、Schema 校验失败、上下文超限、引用失败和客户端配置错误不计入。
- 待审批初始值固定为：60 秒滚动窗口内累计 5 次技术失败即打开，打开 30 秒后进入半开；半开每个键全局最多 1 个探测。探测得到通过 AI-D-001 HTTP 200 与协议包络校验的结果时清零并关闭，即使后续业务 Schema/引用校验失败也不重新打开 transport 熔断器；探测得到计入熔断的技术失败或 `invalid_response/provider_configuration_error` 时立即重新打开 30 秒；明确 `client_error/context_limit/content_rejected` 证明端点可达，关闭 transport 熔断器但仍按本次业务错误失败。窗口、状态和半开租约保存在 Redis，并按 `policy_version` 隔离 key。
- 限流按调用类型使用独立池，同时受目标级熔断约束。受控测试环境初始候选为：同步 RAG 每目标并发 2、12 RPM、100000 TPM、burst 2；异步提取/解释/报告每目标并发 4、30 RPM、250000 TPM、burst 4；Embedding 每目标并发 2、30 RPM、500000 TPM、burst 2。实际生效值取本地批准值与 Provider 合同配额的较小者。
- 获取限流许可的等待也计入业务总截止时间；剩余时间不足时快速失败，不形成无界内存队列。
- Redis 保存跨进程/跨 Worker 的短期熔断与限流状态，业务事实仍不写 Redis。Redis 不可用时，已在途请求允许完成，但不得丢弃其审计事件。
- 外部计费 Profile 的 `redis_unavailable_mode` 固定为 `fail_closed`：不得开始新的 Provider 请求，字段提取进入人工确认、风险解释保留规则结果、RAG 明确不可用/拒答、报告使用确定性模板、Embedding 候选构建失败且旧活动索引保持不变。
- 只有经批准的内部不计费 vLLM 或本地测试 Profile 可以使用 `process_local_restricted`：每进程并发降为 1，本地失败阈值降为 1，冷却 30 秒；此模式不得宣称跨 Worker 熔断或分布式限流已验证。
- `5/30/1` 同时见于系统架构和 AI 详细设计的建议，60 秒窗口只见于系统架构；容量候选是本 CR 新增值。以上均须在审批记录中逐项签署并通过故障注入/容量测试；任一生产值留空时 `AI_PROVIDER_CALLS_ENABLED` 必须保持 `false`。

### 3.6 AI-D-006：调用日志所有权

`AI-001` 只产生不可变、脱敏的 `AiCallEventV1`，允许字段限定为：

- `event_id/event_version/event_sequence/policy_version/policy_hash`
- `organization_id/business_operation_id/job_id/request_id/resource_type/resource_id/trace_id`
- 调用类型、逻辑生成序号和物理 Provider 尝试序号
- 实际 `adapter_id/endpoint_id/model_id/model_version`
- Prompt ID、版本与内容哈希，以及 Schema 版本（存在时）
- 开始/结束时间和耗时
- 输入/输出哈希、输入/输出 Token、向量数量摘要、`pricing_version`
- `reserved_input_tokens/reserved_output_tokens/reserved_cost_micro_usd`
- 尝试次数、fallback 标志、熔断状态、引用校验结果、结果状态、标准错误分类和安全错误码

禁止字段：API Key、Authorization Header、完整 Prompt、完整模型输入/输出、合同/发票正文、制度 Chunk 原文、Provider 原始异常和未脱敏响应。`organization_id` 是写入现有非空字段的必需值；任何不存在的可选业务关联使用 `null`，不得伪造 ID。

可靠交付合同：

1. 每个物理 HTTP 请求使用一个在首次 reserve 前生成的 `event_id`，同一业务操作共享 `business_operation_id`。reserve 调用超时或结果未知时必须复用同一 `event_id` 查询 PostgreSQL 权威状态：已存在且内容相同则视为成功，不存在则只可用同一 ID 幂等重试，内容不同则冲突；持续无法判定时不得发送。禁止换新 ID 盲重试 reserve。`AI-001` 只依赖 AI-005 提供的 Port，不导入 Repository。
2. `reserve_attempt()` 在单一事务内按 `(organization_id, business_operation_id, policy_version)` 获取 PostgreSQL transaction advisory lock，汇总该键下已经提交的 `ai.call.started` 预留，再同时校验请求数、Token、费用和 deadline 余量并追加事件。`ai.call.started` 固定为 `aggregate_type='ai_call'`、`aggregate_id=event_id`、`event_version=1`、`event_sequence=1`，必须携带三项 `reserved_*` 和 `pricing_version`；`(event_id,event_type)` 唯一，相同内容重放 no-op、不同内容冲突。预留成功后最坏预算不释放，防止并发超支和崩溃后无界重放。
3. Provider 返回后，模型输出在被业务采用前必须通过 `complete_attempt()` 验证已提交的同 ID reservation，并追加 `ai.call.completed`（`event_sequence=2`）；异步业务写入时，完成事件与业务结果在同一 PostgreSQL 事务提交。完成事件持久化失败时，确定性规则结果保留，但 AI 生成结果不得写入业务事实或作为成功答案返回，统一进入 `AI_AUDIT_EVENT_UNAVAILABLE` 降级。
4. AI-005 消费 Outbox，以 `ai_call_logs.id=event_id` 幂等投影，并按同一 aggregate 的 `event_sequence` 排序。消费者先看到 sequence 2 时必须暂存并重试，等 sequence 1 可见后再投影；这不是非法状态转换。重复事件内容完全一致时 no-op；相同 ID 内容不同或未知事件版本必须隔离并报警，不得覆盖旧证据。
5. `ai_call_logs.status` 增加 `pending/outcome_unknown`。若 started 到达“对应调用类型总截止时间 + 30 秒”，reconciler 必须在持有同一 aggregate 锁时先查询权威 Outbox：存在 completed 则先按序投影；确认不存在才写 `outcome_unknown`。不得自动重放可能已产生费用或副作用的 Provider 请求。终态后迟到的 completed 只能追加 `late_completion` 关联证据并报警，不能把未知结果改成成功。
6. 每个物理请求最多执行一次 `pending -> succeeded/failed/degraded/rejected/outcome_unknown` 终态转换；OPS-005 通过 `business_operation_id` 聚合同一业务操作的 retry、fallback 和 repair，不把多次物理请求伪装成一次。

`AI-005` 是 `AiCallEventSink`、Outbox 消费、`ai_call_logs`、OPS-005 查询、失败补偿和访问权限的唯一任务所有者；其正式前置依赖改为 `AI-001、BASE-002、BASE-005、BASE-006`。真实 Provider 调用必须等待 BASE-006 可恢复 Outbox/Worker 框架和 AI-005 reserve/complete/reconcile 故障注入测试通过；`AI-001` 本身不直接访问数据库。

本 CR 不关闭 `TBD-007` 的日志保留周期。该期限获批前禁止物理删除或到期清理 `outbox_events/ai_call_logs`，生产发布仍由 `TBD-007` 阻断；不得用 Docker 日志轮转值替代数据库审计保留策略。

### 3.7 AI-D-007：结构化输出修复计数

统一口径：

1. 首次模型生成。
2. 本地确定性清理：去除单一代码围栏、提取唯一 JSON 对象、JSON 解析和 Schema 校验；不调用模型，不计修复次数。
3. 第一次模型修复：附带脱敏、结构化校验错误。
4. 第二次模型修复：允许缩小输出范围并强化 JSON 约束，但不得删除必需证据字段或改变业务事实。
5. 仍失败则返回 `AI_SCHEMA_VALIDATION_FAILED` 并进入人工确认或明确降级。

本地确定性清理只能去除最外层单一 Markdown 代码围栏、在全文恰有一个 JSON 对象时提取该对象、执行 JSON 解析和 Schema 校验；禁止补字段、猜值或修改金额、日期、引用和业务状态。修复 Prompt 只携带 JSON Pointer 及 `required/type/enum` 等安全错误类别，不携带失败字段实际值或完整 Provider 原文。两次修复都必须重新执行完整 Schema、证据、权限和引用校验；内容安全拒绝、引用失败或业务事实冲突不属于格式修复。

因此一次业务调用最多产生 1 次首次生成和 2 次模型修复，共 3 次逻辑生成。每个真实 HTTP 请求都同时消耗逻辑生成尝试预算和 `max_provider_attempts_per_business_operation`；repair、retry 或 fallback 均不重置业务操作总计数。按本 CR 推荐值，结构化 LLM 业务操作的 HTTP Provider 请求硬上限为 6，而不是 `3 次逻辑生成 × 主备 × 各自 retry` 的乘积。总截止时间、输入/输出 Token、总 Token 与外部 Provider 费用上限继续独立生效，任一耗尽即停止并返回明确失败或人工处理。

### 3.8 AI-D-008：出站安全与响应边界

- 运行时配置必须把 endpoint 标识映射到经批准的固定 URL；业务请求、上传内容、数据库字段和模型输出不得提供或覆盖 URL。`base_url` 只允许 scheme、host、port 和固定 `/v1` 路径，禁止 userinfo、query、fragment、路径穿越和百分号编码歧义。
- 生产外部 endpoint 只允许 HTTPS并启用证书/主机名验证；禁止按请求关闭 TLS。受控 Compose 内部服务只允许审批清单中的固定服务名、端口和应用网络 CIDR 使用 HTTP。
- HTTP 客户端固定 `trust_env=false`，不继承 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`，也不自动跟随重定向；所有 3xx 均映射为不可重试的 `provider_configuration_error`。
- 启动时以及每次新建连接前解析目标；外部 Profile 的全部 A/AAAA 结果必须位于显式批准的公网 IP allowlist，并拒绝 loopback、link-local、RFC1918/private、CGNAT、multicast、unspecified、reserved 和云 metadata 地址。内部 Profile 只接受已批准服务名及 CIDR。连接必须绑定一个已验证地址并校验实际 peer IP，DNS 变化后重新验证，禁止“校验一个地址、连接另一个地址”。
- 待审批字节上限固定为：序列化请求体 4 MiB（4194304 bytes）、响应头总计 64 KiB（65536 bytes）、Chat 解压后响应体 2 MiB（2097152 bytes）、Embedding 解压后响应体 4 MiB（4194304 bytes）。限制作用于流式读取的实际字节，不信任 `Content-Length`；超过上限立即停止读取且不在错误中回显内容。
- P0 只接受 `identity` 或 `gzip` Content-Encoding；其他编码拒绝。解压过程必须同时受解压后字节上限控制，防止压缩炸弹。
- 出站关联 Header allowlist 只有经过 Backend 校验或新建的 W3C `traceparent`。不转发客户端 `X-Request-ID`、`tracestate`、`baggage`、用户 Authorization、Cookie、任意自定义 Header 或数据库凭据；Provider `Authorization` 由第 3.1 节的 secret slot 独立生成。
- Provider 原始响应与异常均视为不可信数据；错误映射只保留标准分类、HTTP 状态码和解析后的安全 `Retry-After`，原始错误正文不得进入日志、Trace、指标或持久事件。
- 固定测试必须覆盖 DNS 重绑定、禁止地址、重定向、代理环境变量、TLS 失败、压缩后超限、无效 Content-Type 和包含敏感正文的错误响应。字节上限是本 CR 新增安全候选值，必须逐项签署；任一生产值留空时真实调用 fail closed。

### 3.9 逐项备选、兼容、迁移与回滚

| 决策 | 不采用推荐方案时的唯一安全备选 | 兼容/迁移要求 | 回滚与批准后验收 |
|---|---|---|---|
| AI-D-001 | 为 Responses API 或其他协议新增独立 Profile/Adapter；不能宽松解析 | 现有 `base_url/model/api_key` 可迁移为显式 Profile 字段，协议、认证和能力不得推断 | 禁用该 Profile；契约测试须逐字段覆盖请求、成功、错误和模型 ID 漂移 |
| AI-D-002 | 若每逻辑生成只允许 2 次，必须在“同目标 retry”与“fallback”中二选一 | 旧全局 timeout/retry 变量不得自动换算；逐调用 Policy 缺失即启动失败 | 回滚到上一份已批准 Policy 或关闭真实调用；预算边界逐一做恰好命中/超一格测试 |
| AI-D-003 | 完全禁用自动 retry，直接进入 fallback/业务降级 | 未列出的 HTTP/安全错误默认不可重试，后续扩展必须新 CR | 可把 retry 次数降为 0，不能通过回滚扩大错误集合；验证 429 秒数/HTTP-date 和等待上限 |
| AI-D-004 | 禁用 fallback 并直接使用确定性业务降级 | 前四类是否必须 fallback、报告是否使用 fallback 都必须显式配置，不能由空值猜测 | 关闭备用候选不改变业务 DTO；验证主失败、主熔断、备用熔断和预算不足 |
| AI-D-005 | 完全禁用真实 Provider；不得在缺少 Redis 时用无协调的正常并发继续调用 | Redis key 带 `policy_version` 前缀和 TTL；旧版 key 不被新版读取 | 关闭真实调用或回滚上一 Policy；验证 Redis 丢失、半开逐类结果、跨 Worker 并发和状态恢复 |
| AI-D-006 | 若不接受 durable reserve/complete，则真实 Provider 调用保持禁用 | 等待 BASE-006 可恢复 Outbox/Worker 框架；`outbox_events` 与 `ai_call_logs` 只做前向 Schema 迁移，消费者至少兼容当前及前一事件版本 | 停止调用后排空兼容事件；不删除审计证据；验证 reserve 不确定结果、并发预算、崩溃点、重复、乱序、未知版本和永久失败 |
| AI-D-007 | 把 `max_model_repairs` 明确降为 1 或 0；不得超过需求上限 2 | 修复次数属于 Policy 版本；旧运行继续引用其原 Policy，不被新值改写 | 回滚只允许降低次数；验证本地清理、两次修复、预算耗尽及禁止业务事实改写 |
| AI-D-008 | 不存在关闭 TLS/DNS/大小/脱敏门禁的生产备选 | 旧 endpoint 只有通过固定 URL、认证、DNS/IP 与字节门禁后才能迁移 | 回滚只能禁用 Provider，不能恢复代理继承、重定向或宽松解析；执行 SSRF/压缩/泄漏测试 |

配置迁移规则：

- 可保留并显式映射 `LLM_BASE_URL/LLM_API_KEY/LLM_EXTRACTION_MODEL/LLM_GENERATION_MODEL/LLM_FALLBACK_MODEL/EMBEDDING_BASE_URL/EMBEDDING_API_KEY/EMBEDDING_MODEL/LLM_CONNECT_TIMEOUT_SECONDS`；API Key 只映射到 secret slot，不进入 Policy 序列化结果。
- `LLM_REQUEST_TIMEOUT_SECONDS`、`LLM_MAX_RETRIES` 和 `EMBEDDING_REQUEST_TIMEOUT_SECONDS` 无法表达逐调用 deadline、主备共享尝试和业务总预算，不得静默转换。启用真实调用时若仍只提供旧字段，启动失败并返回不含原值的配置错误。
- 新策略至少显式提供逐调用总 deadline、`LLM_MAX_ATTEMPTS_PER_GENERATION=3`、`LLM_MAX_SAME_TARGET_ATTEMPTS=2`、`AI_MAX_PROVIDER_ATTEMPTS_PER_OPERATION=6`、`AI_MAX_MODEL_REPAIRS=2` 和 `LLM_REPORT_DRAFT_USE_FALLBACK=false`，以及本节各 Token、费用、熔断、容量和字节限制。
- `LLM_FALLBACK_MODEL` 在真实调用启用时对前四类必须非空且与对应主模型不同；报告是否使用它只由 `LLM_REPORT_DRAFT_USE_FALLBACK` 决定。

发布顺序：

1. 上线 Profile/Policy 解析和安全校验，保持 `AI_PROVIDER_CALLS_ENABLED=false`。
2. 通过离线 Mock 的协议、错误、预算、重试顺序和敏感信息扫描。
3. 完成 AI-005 Outbox/日志持久化、补偿与崩溃恢复。
4. 对固定测试 Provider 执行真实 Chat 与 Embedding 请求、主动超时和 Trace 验证。
5. 在 Redis/Worker 环境验证分布式熔断、限流和 Redis 失效策略。
6. 逐项签署生产 Token、费用、容量、IP allowlist 和字节上限，并以最小 canary 启用。

回滚首选把 `AI_PROVIDER_CALLS_ENABLED=false` 并进入确定性业务降级；也可回到上一份已批准 `policy_version`，但不得重新解释旧模糊 timeout/retry 变量。回滚前必须确认旧消费者可以读取积压事件；否则先停止 Provider 调用并排空到兼容边界。Outbox、`ai_call_logs` 和未知结果只保留或前向修复，不删除审计证据。

## 4. 当前工作区 AI-001-S1-S6 与本 CR 的边界

当前工作区的 `AI-001-S1-S6` 只构建以下 provider-neutral 内存边界；本节是事实记录，不是未批准 CR 的实施授权：

- S1～S3 定义不可变调用契约、显式目标单次 Gateway 分派和以下纯路由配置；Gateway 不自动选择或遍历候选：
  - 合同字段提取、发票字段提取 → extraction 主模型；
  - 风险解释、RAG 回答、报告草稿 → generation 主模型；
  - 合同字段提取、发票字段提取、风险解释和 RAG 回答必须携带显式、非空且不同于主目标的第二候选；缺失时路由配置失败关闭；
  - 报告草稿是否携带备用候选必须由独立布尔配置显式决定，不从全局 fallback 的存在性推断；
  - Embedding 只有一个显式候选，不自动 fallback；
- S4 的 LLM 请求只强制非空 `system_instruction` 与 `user_content` 分离，不把它们映射为 HTTP roles 或任一 Provider 包络；
- S5 的 Embedding 请求/结果只强制有序、不可变的非空批次和输入/输出数量一致，不冻结 HTTP `index`、向量维度、单批条数、Token 或字节上限；
- S6 把未知 Adapter、Gateway 契约错误和未规范化 Adapter 异常统一为携带调用 `trace_id` 的固定脱敏边界错误，不定义日志、事件、Sink 或数据库持久化。

上述切片不得读取环境、发起网络、自动遍历候选、解释 HTTP 错误、等待、重试、fallback、熔断、限流或写日志。S1～S6 通过只证明这些离线内存边界自洽，不等于 AI-D-001～AI-D-008 已批准、真实 Provider 可用或完整 `AI-001` 完成。后续保留或变更必须独立引用既有正式基线；只要需要采用本 CR 任一待批决策，就必须停止实施并等待审批和 `Request/` 同步，不能把本节作为替代授权。

## 5. 必须同步的事实来源

批准后至少同步以下正式文档：

- 需求规格：模型降级、费用/截止时间、结构化修复次数和业务降级边界。
- 系统架构：Provider Profile、错误表、上下文超限、熔断键、Redis 降级和日志所有权。
- AI/RAG/Prompt 详细设计：逐调用 Transport Policy、具体 5xx、fallback 条件和两次修复口径。
- 部署与运维：逐调用环境变量、endpoint/TLS/代理/重定向约束、熔断与限流参数。
- 数据库设计：Outbox 事件、`ai_call_logs` 字段/状态/幂等投影、脱敏约束、`TBD-007` 保留边界和 AI-005 所有权。
- 测试与验收：HTTP 包络、认证、超时预算、429、5xx、上下文、fallback、熔断/Redis 失效、DNS/IP、压缩后响应上限、日志崩溃恢复和泄漏用例。
- 开发任务计划：AI-001/002/005 与 BASE-006 的输出、前置依赖、Outbox/Worker 所有权和完成标准。

`Request/` 同步前，本 CR 不产生实现授权；同步后必须重新运行基线哈希和跨文档追踪检查。

## 6. 实施顺序

1. 逐项批准或拒绝 AI-D-001～AI-D-008。
2. 同步受影响 `Request/` 事实来源并重新生成基线证据。
3. 更新 Settings 与 `.env.example`，只增加已批准的字段名和安全占位；真实调用开关保持关闭。
4. 实现 Provider Adapter 的离线单次调用、严格包络解析、出站安全和标准错误映射。
5. 先完成 BASE-006 可恢复 Outbox/Worker 框架，再由 AI-005 实现原子预算 reserve、complete、顺序/幂等日志投影、`outcome_unknown` 补偿与 OPS-005 查询。
6. 实现截止时间内的固定 retry/fallback 序列和统一预算；通过确定性时钟/传输测试。
7. 在 Redis/Worker 条件具备后实现分布式熔断、限流和 Redis 失效恢复测试。
8. 由 AI-002 实现结构化输出修复并验证与总预算、日志事件的组合边界。
9. 依次完成固定测试 Provider 的真实 Chat/Embedding、固定数据集、故障注入、费用上限、安全和降级验收；生产 Profile 另行签署并 canary 后，才可评估 `AI-001` 完成状态。

## 7. CR 验收门槛

- AI-D-001～AI-D-008 每项形成单一、可执行、可测试的批准合同。
- 所有审批记录包含人员、角色、日期、决策版本、所选方案、`policy_version/policy_hash`、环境范围、批准值和证据链接。
- `Request/` 中超时、尝试、5xx、上下文、修复次数、日志所有权和 Provider Profile 不再冲突。
- 离线 HTTP Mock 覆盖精确 Chat/Embedding 请求与成功/错误包络、连接失败、读超时、429 秒数/HTTP-date、批准的 5xx、其他 5xx、4xx、模型 ID 漂移、重定向、代理、TLS/DNS/IP、压缩后超大响应、无效 JSON、usage 异常、向量非法和敏感错误。
- 确定性预算测试证明 retry、fallback 和两次 repair 共用单一业务操作计数器；任何组合都不能超过批准的 Provider 请求、截止时间、Token 或费用上限。
- 熔断/限流测试证明 `5/60/30/1`、三个独立容量池、半开单探测、Redis 外部调用 fail-closed 与内部受限降级均符合批准合同。
- 日志故障注入覆盖 reserve 提交结果未知、同 ID 查询/重试、并发预算、Provider 后 complete 失败、进程崩溃、重复/乱序/冲突事件、未知版本、`outcome_unknown/late_completion` 和消费者恢复；未持久接受的 AI 结果不得成为成功业务事实。
- 固定测试 Provider 覆盖 LLM 与 Embedding 的真实请求、主动超时、Trace 传播和关闭模型后的业务降级；配置/模型列表探针不得替代真实生成。
- 任何测试输出、日志、异常、指标和持久化事件均不含 API Key 或完整敏感正文。
- CR 获批只表示契约可实施，不等于 `AI-001`、AI 稳定性、成本门禁或 AC 已通过。

### 7.1 规范性审批要求（纳入决策快照）

- `environment_scope='contract'`：AI-D-001～AI-D-008 每项都必须由需求、架构、AI、运维和安全负责人签署；只授权同步 `Request/` 与离线 Mock，不授权网络调用。
- `environment_scope='fixed_test_provider'`：完整 Profile/Policy 值必须由上述五方另行签署，才允许在隔离测试环境启用网络。
- `environment_scope='production'`：固定测试 Provider 通过后，生产 Token、费用、容量、IP allowlist、字节上限和证据必须由上述五方再次签署，才允许最小 canary；测试环境签署不得替代生产签署。
- 每条审批记录必须包含：`姓名 / 角色 / 决策编号或环境范围 / APPROVED 或 REJECTED / selected_option / cr_revision / decision_snapshot_sha256 / policy_version / policy_hash / environment_scope(contract|fixed_test_provider|production) / approved_values / 日期 / 证据链接 / 备注`。合同范围的 `policy_version/policy_hash` 可记 `N/A`，其他必需字段不得空白或默认同意。

每条审批必须绑定 `cr_revision='CR-002-R4'` 和 `decision_snapshot_sha256`。计算时先把全文行尾规范化为 LF，定位内容完全等于 `## 8. 审批矩阵` 的 Markdown 标题行，取该行之前的全部行并在末尾保留恰好一个 LF，再对其 UTF-8 bytes 计算 SHA-256 小写十六进制；因此快照包含本节规范性审批要求但不含第 8 节可变记录。不同 revision/hash 的审批不得混合聚合；第 1～7 节或本节审批要求任一修改都必须提升 CR 版本并把合同与环境签署重置为 `PENDING`。

## 8. 审批矩阵

下表只记录 `environment_scope='contract'` 的决策合同审批；全部必需项已由 `APR-20260807-YHBX-CR002` 明确批准。合同审批只授权同步 `Request/` 与离线 Mock，不授权网络调用。

| 决策 | 需求负责人 | 架构负责人 | AI 负责人 | 运维负责人 | 安全负责人 |
|---|---|---|---|---|---|
| AI-D-001 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-002 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-003 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-004 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-005 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-006 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-007 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |
| AI-D-008 | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] | APPROVED [APR-CR002] |

目标环境激活必须另行逐项签署完整 Profile/Policy 值：

| 环境范围 | Profile/Policy 值与证据 | 需求负责人 | 架构负责人 | AI 负责人 | 运维负责人 | 安全负责人 |
|---|---|---|---|---|---|---|
| `fixed_test_provider` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| `production` | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

本节只保存依据第 7.1 节生成的可变签署记录；第 7.1 节是角色、环境、字段和快照规则的唯一规范来源，本节不得降低其要求。

### 8.1 APR-20260807-YHBX-CR002

| 字段 | 批准记录 |
|---|---|
| 姓名 | YHBX（BOSS） |
| 角色 | 需求负责人、架构负责人、AI 负责人、运维负责人、安全负责人；审批人已明确声明具备全部必需审批权限 |
| 决策编号或环境范围 | AI-D-001～AI-D-008；`environment_scope='contract'` |
| 决策 | APPROVED |
| selected_option | 批准第 3.1～3.9 节及第 6～7 节的全部推荐 contract 和精确初始候选值，不采用各节列出的安全备选 |
| cr_revision | `CR-002-R4` |
| decision_snapshot_sha256 | `970eca0fffa2f88eb3e74ccc84adf042b38ac4cb9803d3d53d9d989057bb38a0` |
| policy_version | N/A（contract 范围） |
| policy_hash | N/A（contract 范围） |
| environment_scope | `contract` |
| approved_values | AI-D-001～AI-D-008 在第 3.1～3.9 节列出的全部包络、认证、逐调用 deadline/尝试/Token/费用、错误与 fallback、`5/60/30/1` 熔断、限流容量、Outbox 日志所有权、最多两次模型修复、出站安全、迁移和回滚值；初始配置固定 `AI_POLICY_VERSION=1`、`AI_PROVIDER_CALLS_ENABLED=false` |
| 日期 | 2026-08-07 |
| 证据链接 | Codex task `019fd61e-c0e0-76a1-ad69-7283325be591` 中用户明确审批声明 |
| 备注 | 授权同步受影响 `Request/` 并实施离线 Mock；`fixed_test_provider` 与 `production` 仍为 PENDING，禁止网络调用或生产放行；批准不等于 AI-001 或任何 AC 通过 |

### 8.2 合同生效记录

- 生效日期：2026-08-07。
- `CR-002-R4` 的 AI-D-001～AI-D-008 已按 `environment_scope='contract'` 同步至受影响的 `Request/` 事实来源；初始状态固定为 `AI_POLICY_VERSION=1`、`AI_PROVIDER_CALLS_ENABLED=false`。
- 页首 `DRAFT / PROPOSED` 与第 1～7 节中的待审批措辞属于已签署决策快照，不得在不提升 revision、使原签署失效的情况下改写；当前 contract 有效状态以本节的审批与生效记录为准。
- `fixed_test_provider` 与 `production` 继续 `PENDING`；不得调用 `/v1/models`、真实 Chat、真实 Embedding、内部 vLLM HTTP，也不得执行 canary 或 production 放行。
- 本次生效只授权 contract 同步与离线 Mock，实现、真实 Provider 验证、性能/费用门禁和 AC 验收仍须独立证据。
