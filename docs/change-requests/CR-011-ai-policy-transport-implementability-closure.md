# CR-011-R3：AI Policy 与 Transport 可实施性合同闭合

状态：**DRAFT / PROPOSED / NOT APPROVED**

日期：2026-08-08

对应差异：GAP-057～GAP-062

上游基线：已批准并同步的 `CR-002-R4` contract 范围

## 1. 变更原因

`CR-002-R4` 已冻结 P0 Provider 包络、逐调用预算、retry/fallback、熔断/限流、审计所有权、模型修复和出站安全原则。离线实现复核进一步确认：这些原则仍有六类字段投影或线级算法不能唯一生成代码、JSON Schema、固定测试向量或持久事件。

本 CR 不撤销或放宽 CR-002-R4。它只为 CR-002 已批准语义选择一个可执行表示；在本 CR 获批并同步受影响 `Request/` 前，代码必须保持 `AI_PROVIDER_CALLS_ENABLED=false`，不得自行选择另一种哈希、路由、等待、解析、网络或事件语义。

## 2. 范围与非授权边界

### 2.1 本 CR 推荐冻结

1. `ai-policy-v1` 的 pre-hash 投影、最终 envelope、完整嵌套字段和数组顺序。
2. Profile 身份、operation 到主/备 Profile 的引用，以及熔断目标身份。
3. read idle timeout、最小处理余量和 retry/`Retry-After` 的精确算法。
4. 成功响应未知字段、重复 JSON key、请求/响应/header/gzip 的字节计数。
5. external/internal 出站目标的 Policy 字段结构；实际环境值仍另行审批。
6. `AiCallEventV1` 与 `AiCallEventSink` 的版本化 DTO、结果枚举和调用顺序。

### 2.2 本 CR 不授权

- 不批准任何真实 `base_url`、model、Tokenizer、价格、secret slot 的值、IP/CIDR、Provider 配额或生产容量。
- 不授权 `fixed_test_provider`、内部 vLLM HTTP、真实 Chat/Embedding、DNS/TLS 探测、canary 或 production 放行。
- 不实现 AI-005 数据库表、Outbox、Redis 熔断/限流或 Worker；这些仍受 BASE-005/006、CR-004 和对应任务约束。
- 不把离线 Mock、Schema 校验或固定向量描述为真实 Provider、性能、费用、AC 或 production 通过。

## 3. 推荐合同

### 3.1 AI-D-009：Policy pre-hash 与最终 envelope

最终 `ai-policy-v1.json` 是一个封闭 JSON object，顶层恰有以下九个键：

~~~json
{
  "policy_version": 1,
  "policy_hash": "<64 lowercase hex>",
  "provider_calls_enabled": false,
  "profiles": {},
  "operations": {},
  "retry": {},
  "breaker": {},
  "rate_limits": {},
  "outbound_limits": {}
}
~~~

哈希算法固定为：

~~~text
pre_hash_payload = final_policy_object with the policy_hash member removed
canonical_bytes = RFC8785_JCS(pre_hash_payload)
policy_hash = lowercase_hex(SHA256(canonical_bytes))
~~~

`policy_hash` 不以空字符串、`null`、零哈希或占位值参与 preimage。验证方必须删除且只删除顶层 `policy_hash`，重算后做逐字比较。最终文件缺少或多出任一键、出现重复 object key、非 I-JSON 字符串/数字、错误 JSON 类型或未知嵌套字段时启动失败。

Policy integer 字段的原始 JSON token 必须匹配 `0|[1-9][0-9]*`，不得出现负号、`-0`、小数点或指数；解析后范围固定为 `0..9007199254740991`，要求正整数的字段再拒绝 0。验证器必须在丢失词法信息前执行该检查；JSON Schema 的 `type=integer` 不能单独证明 `1.0` 合法。布尔值不得当作 `0/1`，字符串数字也不得转换为 number。

`allowed_response_model_ids`、`capabilities` 与 `approved_hostnames` 均须非空、唯一，并在生成制品前按 UTF-16 code unit 升序排列。`allowed_cidrs` 使用第 3.5 节的 canonical network 顺序。验证方只接受已经规范化和排序的数组，不静默重排；数组顺序进入 hash。

规范机器制品固定放在 `docs/change-requests/artifacts/CR-011/`，文件集合必须精确为：

- Policy：`ai-policy-v1.schema.json`、`ai-policy-v1.companion-validator.json`、`ai-policy-v1.positive.json`、`ai-policy-v1.prehash.jcs.json`、`ai-policy-v1.negative-vectors.json`；
- Event：`ai-call-event-v1.schema.json`、`ai-call-event-v1.started.json`、`ai-call-event-v1.started-outcome-unknown.json`、`ai-call-event-v1.completed.json`、`ai-call-event-v1.completed-failed.json`、`ai-call-event-v1.completed-degraded.json`、`ai-call-event-v1.completed-rejected.json`、`ai-call-event-v1.completed-outcome-unknown.json`、`ai-call-event-v1.late.json`；
- Registry 与清单：`ip-deny-cidrs-v1.json`、`manifest.json`。

标准 Draft 2020-12 JSON Schema 只负责可由 Schema 表达的封闭结构、类型与 conditional 分支；原始整数词法、envelope/pre-hash 上下文、RFC 8785 hash、数组规范顺序、Profile/operation 引用图、hostname/URL、CIDR/registry 和环境零网络门禁由 `ai-policy-v1.companion-validator.json` 的固定执行顺序负责。完整 Policy 验证必须同时通过 Schema 与全部 companion rules，任何一方都不能单独冒充完整验证。

`manifest.json` 必须记录其自身之外每个制品的相对路径、用途、byte length 和 SHA-256；审批快照还要记录 manifest bytes 的 SHA-256。缺少任一制品或 hash 漂移时本 CR 不可批准。

负向 Policy 向量至少覆盖：自引用/置空 hash、重复 key、布尔整数混用、`1.0/1e0/-0` 词法整数、超安全整数、未知字段、数组乱序/重复、secret 值进入 Policy、篡改一字节和 hash 大小写漂移。

### 3.2 AI-D-010：Profile 身份与 operation 路由

`profiles` 是以 `profile_id` 为 key 的 object。`profile_id` 是 1～100 个小写 ASCII 字母、数字、`_` 或 `-`，同一 Policy 内唯一。每个 Profile 在 CR-002-R4 已批准字段之外新增且必须包含：

| 字段 | 类型与约束 |
|---|---|
| `adapter_id` | `openai_chat_completions_v1` 或 `openai_embeddings_v1`；与 `profile_type` 使用下述唯一映射 |
| `endpoint_id` | 非空稳定 ASCII 标识；同一 endpoint 的 URL 更新必须发布新 Policy |
| `model_version` | 环境签署的非空 string 或 null；Provider 无独立版本事实时必须为 null，不能复制 model_id 伪造 |
| `capabilities` | 已排序唯一的封闭数组；只允许 `llm_extraction/llm_generation/embedding` |
| `network_scope` | `external_public` 或 `internal_service` |
| `approved_hostnames` | 已排序唯一字符串数组；必须包含 `base_url` 的规范 ASCII hostname |
| `allowed_cidrs` | 已排序唯一 CIDR 字符串数组；不得为空或使用通配网络 |
| `address_policy_version` | 精确为机器制品中的 `ip-deny-cidrs-v1` 版本 |

Profile map key 即 `profile_id`，对象内不重复保存该字段。映射固定为 `openai-chat-completions-v1 -> openai_chat_completions_v1`、`openai-embeddings-v1 -> openai_embeddings_v1`，不存在第三个 P0 Adapter；扩展必须新 CR。Chat Profile 的 capabilities 只能包含一个或两个 LLM 值，Embedding Profile 必须恰为 `["embedding"]`。共用 fallback 可以同时声明 `llm_extraction` 和 `llm_generation`。`adapter_id + endpoint_id + model_id` 是 CR-002-R4 的熔断身份；Redis key 另含 `policy_version`，任何字段不得从 URL、model 名或 `profile_type` 临时推导。

每个 operation 在 CR-002-R4 已批准字段之外增加：

| 字段 | 类型与约束 |
|---|---|
| `primary_profile_id` | 必填；必须引用同一 Policy 中能力匹配的 Profile |
| `fallback_profile_id` | string 或 null；前四类 LLM 必填且不得等于 primary，Embedding 必须为 null，报告与 `report_use_fallback` 一致 |

合同/发票引用的主备 Profile 必须声明 `llm_extraction`，风险/RAG/报告必须声明 `llm_generation`，Embedding 必须声明 `embedding`。具体 Profile 数量不固定为“一 Chat + 一 Embedding”；缺少路由所引用的 Profile、存在未被任何 operation 使用的 Profile、目标身份重复或 capability 不匹配均启动失败。

### 3.3 AI-D-011：timeout、backoff 与 Retry-After

Policy v1 新增全局严格字段：

- `retry.read_idle_timeout_seconds = 30`
- `retry.min_processing_margin_seconds = 1`
- `retry.jitter_algorithm = "symmetric-uniform-cap-v1"`

`read_idle_timeout_seconds` 是相邻响应字节之间允许的最大空闲时间，不是整个响应总时长；业务总 deadline 始终覆盖连接、排队、门禁、等待、读取、解压和解析。开始任一连接前必须满足：

~~~text
remaining_deadline_seconds > connect_timeout_seconds + min_processing_margin_seconds
~~~

第一个请求不计算 backoff。`retry_ordinal` 在**每个逻辑生成、每个实际目标**的同目标技术 retry 序列内从 1 开始；切换 fallback 或开始新的 model repair 时，对新逻辑生成/目标重新从 1 开始，但业务操作总请求计数不重置。注入的随机源返回 `u`，要求 `0 <= u < 1`：

~~~text
base = min(30, 1 * 2 ** (retry_ordinal - 1))
jittered_local = min(30, base * (0.8 + 0.4 * u))
effective_wait = max(jittered_local, parsed_retry_after_or_zero)
~~~

`Retry-After` 只在 HTTP 429 读取，且只接受单个 Header；其他状态即使携带也忽略。重复字段、逗号列表、空白内容均视为非法并忽略。值在去除两端 OWS 后只接受最多 16 位 ASCII `1*DIGIT` 非负整数秒，或严格 IMF-fixdate；更长数字采用安全饱和结果 `>30`，不得交给语言整数无限解析。墙钟只用于把 IMF-fixdate 转为 delay：`max(0, ceil(provider_date_epoch_seconds - wall_clock_epoch_seconds))`，精度为整秒；不得解析小数、符号、自由文本或其他日期格式。原值不得写日志，只可保留安全解析后的非负整数秒。

业务开始时以 monotonic clock 固定 `deadline_monotonic`；所有 remaining/deadline 比较和等待均只使用同一 monotonic clock，墙钟调整不得延长预算。如果 `effective_wait > 30`，或 `monotonic_now + effective_wait + min_processing_margin_seconds >= deadline_monotonic`，不得提前重试同一目标，只能按 CR-002-R4 判断 fallback 或确定性降级。测试必须分别注入 monotonic clock、UTC 墙钟和随机源，不真实 sleep。

### 3.4 AI-D-012：JSON 包络与线级字节边界

- 应用构造的请求对象禁止未知字段，按 RFC 8785 JCS 输出无 BOM 的 UTF-8 bytes；字节上限作用于最终发送的 body bytes。
- Provider 成功响应在顶层、`choice/message/usage/data item` 可携带未知字段；Adapter 必须忽略且绝不使用、转发或记录它们。已批准字段仍按严格类型和基数校验。任何层级重复 JSON key 都拒绝为 `invalid_response`。
- 非 2xx 可选错误包络继续沿用 CR-002-R4 的“未知字段不参与决策”；重复 key 仍拒绝正文诊断并只保留 HTTP 状态分类。
- 响应 Header 限额按接收顺序对原始字段计算：每项为 `len(name_ascii) + 2 + len(value_bytes) + 2`，最后再加 2 个 bytes；不含 HTTP 状态行或 HTTP/2 pseudo-header。合并后的 convenience mapping 不能作为计数来源。字段名非 ASCII、单个值无法取得原始 bytes 或总计超过 65536 时停止读取；HTTP 200 映射 `invalid_response`，非 2xx 仍保留 CR-002 的状态优先分类且丢弃全部诊断 Header/body。
- identity 响应的原始 body 和解析输入使用同一 Chat/Embedding 上限。gzip 响应同时限制原始压缩 bytes 和解压 bytes，二者各不得超过对应 body 上限；只允许单个 gzip member。HTTP 200 的 CRC/ISIZE 错误、尾随非空 bytes、多 member、未完整结束或超限映射 `invalid_response`；非 2xx 的同类错误只使诊断正文不可用，429 和已批准/未批准 5xx 的状态分类不得被覆盖。
- 恰好命中上限允许，超过一字节拒绝；停止读取后不得把已读正文写入错误、日志、Trace、指标或事件。

### 3.5 AI-D-013：出站网络字段结构

hostname 只接受小写 ASCII DNS 名：总长 1～253，无尾点，每个 label 长 1～63，匹配 `[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?`；禁止空 label、IP literal、非 ASCII、`xn--` IDNA label 和运行时大小写/Unicode 规范化。`base_url` 的 hostname 必须已经是该规范形式。

CIDR 必须由严格网络解析器以 `strict=true` 接受（输入不得带 host bits），再序列化为小写 RFC 5952 IPv6 或标准 IPv4 network/prefix；输入必须逐字等于序列化结果。排序键固定为 `(ip_version, unsigned_network_integer, prefix_length)`，IPv4 在 IPv6 前。重复字符串、语义重复/重叠网络和 `0.0.0.0/0`、`::/0` 均拒绝。`address_policy_version` 必须命中 `ip-deny-cidrs-v1.json` 的版本与 hash，应用启动、新建连接和 peer 复核都使用同一只读制品。

`network_scope='external_public'` 时：

- `base_url` 必须是 HTTPS；hostname 必须在 `approved_hostnames`；每次解析得到的全部 A/AAAA 和实际 peer IP 必须落在 `allowed_cidrs`。
- Schema/启动 validator 必须逐项拒绝与 `ip-deny-cidrs-v1.json` 任一网络相交的 allowlist；该机器制品冻结 CR-002 列举的 loopback、link-local、private、CGNAT、multicast、unspecified、reserved、documentation、transition 和 metadata 范围，不能只依赖审批备注或语言运行库随版本变化的 `is_global`。环境审批还要证明余下 CIDR 属于目标 Provider。

`network_scope='internal_service'` 时：

- HTTP 或 HTTPS 均可，但 hostname、port 和应用网络 CIDR 必须逐项环境签署；`allowed_cidrs` 必须全部落在 `ip-deny-cidrs-v1.json` 中明确标记为 private/app-network-eligible 的 RFC1918 或 ULA 范围，不接受 loopback、link-local、metadata、任意 Docker service 名或通配网络。
- 只有 `billing_mode='internal_unmetered'` 可以使用 internal scope；外部计费 Profile 不得借 internal 标记绕过 TLS。

Resolver、连接绑定和 peer 校验必须通过注入式 Port 与 HTTP Transport 解耦。contract/offline 测试只使用合成 DNS 集合和 peer IP，不创建 socket；这只能证明判断逻辑，不能证明真实 DNS、TLS 或连接绑定完成。

### 3.6 AI-D-014：AiCallEventV1 与 Sink Port

`ai-call-event-v1.schema.json` 使用 `event_type` 判别联合，顶层 `additionalProperties=false`；started、completed 和 late 是三套不同的 required/nullability 集合，不使用一张“全部可空”表。

#### 3.6.1 共同 envelope

三类事件共同包含 `event_id: uuid`、`event_version: 1`、`event_type`、`event_sequence`、`aggregate_type='ai_call'`、`aggregate_id=event_id`。`ai.call.started/completed/late_completion` 的 sequence 分别固定为 1/2/3；同一 `(event_id,event_type)` 相同 JCS payload 重放 no-op，不同 payload 冲突隔离。

Event 的所有 integer 字段采用 I-JSON safe mathematical integer 值语义，范围固定为 `0..9007199254740991`，要求正整数的字段再拒绝 0。原始 JSON number token 的词法形式不属于 Event 事实，不保留也不据此拒绝数学值等价的表示；DTO 构造必须拒绝 boolean 和数字字符串，DTO/JCS 输出必须使用 `0|[1-9][0-9]*` 的规范非负整数表示。该裁决不修改第 3.1 节 Policy raw source 的严格整数词法合同。

#### 3.6.2 sequence 1 started

started 必填并冻结以下字段：

- `organization_id/business_operation_id/trace_id` 为 UUID；`job_id/request_id/resource_id` 为 UUID 或 null，`resource_type` 为非空 ASCII string 或 null。
- `policy_version` 为正整数，`policy_hash` 为小写 SHA-256；`pricing_version/adapter_id/endpoint_id/model_id` 非空，`model_version` string 或 null。
- `call_type` 为六类 operation enum，`logical_generation_no/provider_attempt_no/attempt_count` 为正整数，`is_fallback` 为 boolean。
- LLM 的 `prompt_id/prompt_version/prompt_hash` 必填；Embedding 三者必须为 null。`schema_version` 为 string 或 null。
- `input_hash`、三项非负 `reserved_*`、`breaker_state: closed|open|half_open|null`、`started_at` 和 `status='pending'` 必填。started 不包含 output hash、实际 usage、completed time、HTTP/error/citation 终态字段。

#### 3.6.3 sequence 2 completed

completed 只携带关联与终态 delta：`organization_id/business_operation_id/job_id/request_id/trace_id/policy_version/policy_hash` 必须与 sequence 1 一致；另含 `status`、`completed_at`、`duration_ms`、`output_hash`、`input_tokens/output_tokens/vector_count/http_status/error_category/safe_error_code/citation_validation_status`。`status` 只允许 `succeeded/failed/degraded/rejected/outcome_unknown`。

- `completed_at` 为 UTC RFC3339 microseconds，`duration_ms` 为非负整数。
- usage、HTTP、output hash 和三类错误/引用字段均为显式 nullable，不能省略；各状态的精确 nullability 由机器 Schema 的 conditional 分支冻结。
- `outcome_unknown` 是 reconciler 的权威 sequence 2；不得携带伪造成功 usage/output，也不得触发 Provider 重放。

#### 3.6.4 sequence 3 late completion

除第 3.6.1 节共同 envelope 外，late payload 的 delta 字段集合由本 CR 自包含冻结，只允许：`organization_id/business_operation_id/job_id/request_id/trace_id/policy_version/policy_hash/observed_status/provider_completed_at/duration_ms/output_hash/input_tokens/output_tokens/vector_count/http_status/error_category/safe_error_code`。`observed_status` 只允许 `succeeded/failed/degraded/rejected`；可选字段按 Schema 显式为 null 或省略。它只在权威 sequence 2 已为 `outcome_unknown` 时追加，绝不更新 `ai_call_logs` 终态或允许业务采用。该 DTO、Schema 与固定向量不以 CR-004 批准为前置；CR-004 只负责后续 Outbox/late-completion runtime 与本合同的兼容，不能反向定义或覆盖字段。

#### 3.6.5 hash preimage 与数据库投影

- `input_hash = SHA256(exact JCS request body bytes)`；不含 Authorization、traceparent 或其他 Header。
- `output_hash = SHA256(exact decompressed response body bytes)`，仅在 body 已完整读取且通过对应字节门禁时存在；hash 不代表业务 Schema/引用已通过。
- Prompt source 文件统一为 UTF-8 无 BOM、LF 行尾且不做 Unicode normalization。`prompt_hash` 的 preimage 固定为 JCS：`prompt_id/prompt_version/system_template_sha256/user_template_sha256/schema_version/schema_sha256`；无 Schema 时后二者为 null。单文件 hash 直接对规范 bytes 计算 SHA-256。

AI-005 投影字段名与 Request 数据库保持一致：`logical_generation_no/provider_attempt_no/status/citation_validation_status/completed_at/safe_error_code/http_status` 不重命名。`policy_version` 从 Policy 的正整数以无前导零十进制转换为 `VARCHAR(80)`；其他 started 字段插入 `ai_call_logs`，sequence 2 只更新数据库已批准的终态白名单。`model_version`、Prompt/Schema、request/resource 和实际 usage 按数据库现有可空性保持 null，禁止伪造。sequence 3 只进入 Outbox/迟到证据，不投影覆盖表。

#### 3.6.6 Sink 结果与发送顺序

`AiCallEventSink` 是异步 Port，不暴露 Repository。安全顺序固定为：生成 event ID → 纯预算/deadline preflight → 取得 breaker/half-open 与限流许可 → durable reserve 内原子重复全部预算/deadline断言 → 最终 monotonic deadline 检查 → 单次 HTTP → durable complete → 业务采用。熔断已开、限流/许可超时或 preflight 失败时不写 started、不消耗持久预留。

`reserve_attempt(event)` 的持久结果为 `reserved_new|replayed_same|conflict|unknown|budget_exhausted|deadline_exhausted`。只有 `reserved_new` 自动产生不可序列化、不可持久化、绑定当前调用栈和 event ID 的一次性 `SendPermit`。数据库 commit 结果未知时，同一活跃调用栈可以用同一 event ID 查询；仅当本地状态证明尚未进入 send 且 AI-005 确认相同 started 时，才把 `replayed_same` 升格为新的进程内 `SendPermit`。进程重启、Job/Worker 恢复或无法证明未发送时，`replayed_same` 不产生 permit，必须进入 unknown/人工或确定性降级，禁止再次调用 Provider。HTTP Transport 必须要求并消费 permit；不能仅凭 event ID 发送。

`complete_attempt(event)` 返回 `completed_new|replayed_same|late_recorded|conflict|unknown|audit_unavailable`。只有当前调用栈持有 Provider 结果且获得 `completed_new/replayed_same` 的一次性 `AdoptPermit` 时可以采用 AI 输出；`late_recorded` 永不产生 permit。权威 sequence 2 已为 `outcome_unknown` 时，complete 只能按 3.6.4 追加 sequence 3 并返回 `late_recorded`。

发送前对 `provider_attempts_used + 1 + future_model_repair_slots <= max_provider_attempts_per_business_operation` 做同一断言；`future_model_repair_slots` 等于尚未开始但仍允许的模型修复次数。纯 preflight 与 AI-005 advisory-lock 事务必须使用相同公式。预留成功后不释放最坏预算，任何 unknown 均不得换 ID 或自动重放。

## 4. 已批准合同可直接修复的事项

以下事项不需要等待本 CR，因为它们已由 CR-002-R4 或 RFC 8785/I-JSON 唯一决定；实现和测试仍不等于完整 AI-001：

- 校验错误的所有字符串、结构化和 JSON 表示均移除原始输入。
- 原始 Policy JSON 在解析前拒绝重复 object key，布尔与整数不互换。
- `billing_mode='external_usd'` 的 Profile 必须使用 HTTPS。
- 增加已批准的 `invalid_response/content_rejected/provider_configuration_error/output_truncated` 分类；只有 `500/502/503/504` server error 可 retry，其他 5xx 和 context limit 不 retry。
- preflight 显式校验未来 repair 请求格数；持久 reserve 仍等待 AI-D-014 和 AI-005。

## 5. 同步与兼容策略

本 CR 获批后，必须原子同步需求、架构、AI/RAG、测试、部署和开发计划；API/数据库仅在 `AiCallEventV1` 或 AI-005 合同受影响时同步。已签署 `CR-002-R4` 的页首和第 1～7 节不得原地改写；以新 CR 的审批记录建立兼容补充关系。

现有 `AiPolicyPayloadV1` 只能标记为 pre-hash/offline 过渡对象。迁移到最终 Schema 时必须：

1. 保持 Provider 调用关闭。
2. 发布 Schema、合成固定向量和独立实现 hash 对照。
3. 将旧 route/Profile 配置显式转换为带 ID/引用/网络范围的新对象；缺值 fail closed，不用默认值补齐。
4. 先完成纯解析、路由、等待算法、响应 parser、Resolver seam 和事件 DTO 契约测试。
5. 再等待 fixed-test Provider 的完整环境审批；contract 批准不得替代该审批。

回滚只允许回到上一份可验证 Policy 并保持 Provider 调用关闭；不得重新启用旧 timeout/retry 字段或接受无 hash/错误 hash 的文件。

## 6. 验收 Gate

- 两个独立实现按标准 Draft 2020-12 Schema 与 companion validator 的固定执行顺序校验同一完整正向 Policy，并得到相同 pre-hash bytes 和最终 hash；只运行 Schema 或只重算 hash 都不算通过。
- 对 hash 自引用、重复 key、类型混用、数组乱序、路由悬空、能力不匹配和 unknown field 全部 fail closed。
- 注入时钟/随机源验证 retry ordinal、jitter 边界、合法/非法/重复 `Retry-After`、恰好 deadline 和不足处理余量。
- Chat/Embedding 响应 unknown field 被忽略但不记录；重复 key、gzip 多 member、CRC 错误和四类字节上限恰好命中/超一字节均有固定测试。
- 合成 DNS/peer 测试覆盖 external/internal、禁止地址、全部 A/AAAA、peer 漂移和跨 scope 重放；不打开 socket。
- `AiCallEventV1` Schema 与固定向量覆盖两个 started 链、`succeeded/failed/degraded/rejected/outcome_unknown` 五类 completed 分支及 late 分支，逐项验证结构、nullability 与 hash 投影；这些静态制品不冒充 Sink 行为状态机证据。
- 注入式离线 `AiCallEventSink` 行为测试必须分别覆盖 `reserve_attempt` 的六种结果、`complete_attempt` 的六种结果、commit-before-return/return-before-call-site/crash-before-send/crash-after-send 等边界，以及 SendPermit/AdoptPermit 的单次消费；行为证据未齐前本 Gate 保持 pending，未知/冲突不得发送或采用结果。
- `manifest.json` 必须精确覆盖自身之外的 15 个 JSON，逐文件 byte length 与 SHA-256 全部匹配，并由审批记录固定 manifest 原始 bytes 的 SHA-256。
- secret 与业务正文 sentinel 不出现在异常 `str/errors/json`、日志、Trace、指标、Policy、事件或测试报告。

## 7. 依赖与审批边界

- AI-D-009～013 可独立评审和生成离线证据，但只能与 AI-D-014 及机器制品原子批准生效。
- AI-D-014 的 DTO、Schema 与固定向量在本 CR 内自包含冻结；AI-005、CR-004 只构成后续持久化、Outbox/late-completion runtime 的兼容与实现依赖。只审批 DTO 不授权建表或 Worker。
- fixed-test/production Profile 的具体值继续使用 CR-002-R4 的独立环境审批矩阵，本 CR 不复用或放宽它。

合同批准必须由需求、架构、数据、后端/API、AI、测试、运维和安全角色逐项签署 AI-D-009～014；一人具备多个角色权限时可以合并记录，但必须明确列出全部角色。任一项拒绝、留空或条件互相冲突时，本 CR 整体保持 `NOT APPROVED`，不得只挑选会造成不兼容 Policy/Event 的子集生效。

每条审批记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_option / cr_revision / decision_snapshot_sha256 / artifact_manifest_sha256 / environment_scope=contract / policy_version / 日期 / 证据链接 / 备注`。contract 范围不批准真实 Profile 值；`fixed_test_provider/production` 必须继续使用 CR-002-R4 的独立环境记录。

`decision_snapshot_sha256` 计算规则：全文行尾规范化为 LF，定位内容完全等于 `## 8. 当前状态` 的标题行，取该行之前的全部行并在末尾保留恰好一个 LF，对 UTF-8 bytes 计算 SHA-256 小写十六进制。因此第 1～7 节全部纳入签署。`artifact_manifest_sha256` 对 `docs/change-requests/artifacts/CR-011/manifest.json` 的原始 UTF-8 bytes 计算；manifest 内再固定其他全部机器制品。两个 hash 任一变化都必须提升 CR revision 并重置签署。

首次 `decision_snapshot_sha256` 与 `artifact_manifest_sha256` 生成后，本 CR 任一规范性内容或机器制品修改都必须提升 revision、重新生成两个 hash 并重置全部签署。生成初始 hash 只建立可签署对象，不等于批准；当前没有审批记录，状态仍只能保持 DRAFT。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| CR revision | `CR-011-R3；DRAFT / PROPOSED / NOT APPROVED` |
| GAP-057～GAP-062 推荐合同 | `PROPOSED` |
| CR-002-R4 兼容性 | `PROPOSED；不撤销、不放宽` |
| Request 同步 | `NOT AUTHORIZED` |
| 完整 ai-policy-v1 Schema/companion/hash | `GENERATED / STRICTLY VERIFIED / NOT APPROVED` |
| AiCallEventSink 行为证据 | `PENDING；STATIC ARTIFACTS DO NOT PROVE STATE MACHINE` |
| decision snapshot / artifact manifest hash | `CR-011-R3 GENERATED FOR REVIEW；decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be；artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c；NOT APPROVED` |
| fixed_test_provider 网络 | `NOT AUTHORIZED` |
| production | `NOT AUTHORIZED` |
