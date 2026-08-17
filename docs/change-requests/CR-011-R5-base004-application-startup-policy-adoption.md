# CR-011-R5：BASE-004 应用启动 Policy 离线采用治理 successor

> 状态：`GENERATED FOR REVIEW / NOT APPROVED`
>
> 日期：2026-08-10
>
> 基座：`CR-011-R3` exact contract + `CR-011-R4` active-baseline governance
>
> 目标：在不改变 `AI-D-009`～`AI-D-014` 或 R3-origin 机器制品的前提下，只授权 `BASE-004` 的本地离线应用启动 Policy 采用、失败关闭和对应依赖；不授权 Provider、持久化、部署或 production 放行

---

## 1. 不可变基座与 successor 必要性

### 1.1 R3/R4 effective identity

本 CR 逐字绑定以下不可变基座：

| 对象 | revision / identity | 状态 |
|---|---|---|
| AI exact contract | `CR-011-R3` | `AI-D-009`～`AI-D-014` 保持原样 |
| R3 decision preimage | `26563` bytes | SHA-256 `b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` |
| R3-origin artifact manifest | `5128` raw bytes | SHA-256 `f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` |
| active governance base | `CR-011-R4` | `APPROVED / ACTIVE CONTRACT` |
| R4 decision preimage | `27384` bytes | SHA-256 `cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` |

R4 已完成九角色批准、十一文件原子同步、Stage1 和完整 Gate B。完整 Gate B 的既有证据为：两个 Draft 2020-12 engine、`27/27` 用例、`25/25` 负向量、Python/Node Schema calls `20+20`、zero-socket guard PASS、attempts `0`、Node selftest PASS 与 anti-forgery `11/11`。R5 不重跑这些事实来改变合同，也不把它们解释为应用启动、Provider、持久化或 production 证据。

### 1.2 为什么必须提升 R5

R4 §4.1 只授权 test/contract-offline 的 Schema、companion、parser、resolver、算法、DTO 与 Fake/in-memory Sink 行为，并明确不得接入非测试 Settings。完整 Gate B 通过后，正式 `BASE-004` DoD 复核仍有以下独立缺口：

1. `AI_POLICY_FILE` 尚未由 FastAPI/Worker 应用启动入口消费；缺失、篡改或不完整的最终 Policy 不会在应用启动时经过完整 Schema+companion 组合验证。
2. 当前 Draft 2020-12 engine 只按 test-only 精确闭包物化，未被授权为 Backend/Worker 本地运行时依赖。
3. Settings 与最终 Policy 的 version、calls-disabled 和环境边界尚无启动期交叉绑定。
4. local/test/prod 只有配置枚举证据；尚无 `prod` 在环境批准缺失时于任何外部 I/O 前失败关闭的应用启动证据。

上述缺口不能通过继续扩写 R4 §4.1 绕过，也不能以 R4 Gate B、Fake Sink、单独 Settings 单测或 AI-005 Gate C 代替。R4 已产生有效批准和下游消费事实；改变其授权边界必须提升 successor，并重置本轮签署。

### 1.3 零语义与零产品增量

R5 对以下对象的 semantic delta 精确为零：

- `AI-D-009`～`AI-D-014`；
- R3 decision snapshot、artifact manifest 和 15 个 leaf artifacts；
- Policy/Event 字段、Schema、companion rule 顺序、JCS/hash、固定向量和错误语义；
- 57 张核心表、122 个 API path、UI-001～UI-014 和 86 个 P0 工作包；
- CR-004 R1/R2 reliability tuple、AI-005 所有权与 R4 Gate C persistent runtime 边界。

本 CR 只新增 `STARTUP-D-001`～`STARTUP-D-006` 六项治理决策。任何 R3-origin artifact byte、`AI-D-*` 语义、Policy/Event 字段或 fixed vector 的修改都不属于 R5，必须另行提升 CR 并重置审批。

---

## 2. STARTUP-D-001～006 最小决策全集

### 2.1 STARTUP-D-001：Python Draft 2020-12 runtime 精确闭包

Backend/Worker 的本地应用启动 validator 只允许把既有 Gate B Python 闭包提升为运行时依赖；版本和所选 exact wheel artifact hash 精确为：

| distribution | exact version | exact wheel filename | raw bytes | raw SHA-256 |
|---|---:|---|---:|---|
| `attrs` | `26.1.0` | `attrs-26.1.0-py3-none-any.whl` | 67548 | `c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309` |
| `jsonschema-specifications` | `2025.9.1` | `jsonschema_specifications-2025.9.1-py3-none-any.whl` | 18437 | `98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe` |
| `jsonschema` | `4.26.0` | `jsonschema-4.26.0-py3-none-any.whl` | 90630 | `d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce` |
| `referencing` | `0.37.0` | `referencing-0.37.0-py3-none-any.whl` | 26766 | `381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231` |
| `rpds-py` | `0.30.0` | `rpds_py-0.30.0-cp310-cp310-win_amd64.whl` | 235823 | `1726859cd0de969f88dc8673bdd954185b9104e05806be64bcd87badbe313169` |
| `typing-extensions` | `4.16.0` | `typing_extensions-4.16.0-py3-none-any.whl` | 45571 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |

既有 lock `scripts/requirements-cr011-gate-b.txt` 必须保持 `641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c`。R5 只允许复核并消费该既有完整传递 lock，不允许重新解析、生成或修改它。运行时安装仍使用完整传递 hash、wheel-only、隔离环境和禁止全局安装；不得把 Node Ajv 提升为应用运行时依赖，不得顺带升级任何其他依赖。

该 lock 的 Gate C 适用平台固定为 CPython 3.10 / Windows x86-64（`win_amd64`）本地验证环境，其中 `rpds-py` hash 只绑定该平台 wheel。dependency acquisition 与启动 runner 必须在安装/导入前验证 interpreter implementation、major/minor、OS 和 architecture；任一不匹配即失败关闭，不得回退到 sdist、其他 wheel 或未锁 hash。该闭包不是 Linux/container/production 的跨平台供应链批准。未来目标平台必须另行生成、审查并批准该平台的完整 transitive hash closure，不能从本地 Gate C 推导。

若本机已存在逐字匹配的已验证缓存，可以零网络复用。确需重新获取时，必须进入与 application startup 完全分离的 `dependency acquisition` 阶段；该阶段唯一网络例外是：对 lower-case exact host allowlist `pypi.org`、`files.pythonhosted.org` 执行必要 DNS resolution、经系统信任链和 hostname verification 的 TLS、以及 HTTPS `GET`，只获取官方 metadata 与上表 exact wheel artifacts。请求必须直接命中 allowlist host，禁止 IP literal、HTTP 明文、非 `GET` method、redirect、proxy、镜像/extra index、`trusted-host`、TLS verification bypass、上传或任意其他 host。

acquisition oracle 固定为顺序执行最多六个 official version-metadata `GET` 与六个 wheel `GET`，`retry=0`；metadata 只允许 `https://pypi.org/pypi/<distribution>/<exact-version>/json`，每个 response raw cap 为 `1_048_576` bytes，并只选择上表 exact filename/size/hash 且 artifact URL host 为 `files.pythonhosted.org` 的条目。每个请求固定 `connect_timeout=10s/read_timeout=30s/total_timeout=60s`，不得并发、分页或查询其他 version endpoint。wheel 必须流式写入隔离临时文件，最多读取 `expected_raw_bytes + 1`，若声明 `Content-Length` 则必须先等于 expected length，结束时必须同时匹配 exact filename、实际 raw length 和 SHA-256；short、extra byte、hash/metadata/TLS/timeout/host/method 任一失败都关闭 handle 并删除临时文件，不得 retry。六项全部验证后才可原子 materialize 到隔离 wheelhouse。进入 startup 阶段前必须终止 acquisition 进程，清除 proxy/index 环境与下载客户端，并以新净化进程切换为严格 zero-socket。Provider、GitHub release、业务网络和其他外网在两个阶段都不授权。

### 2.2 STARTUP-D-002：只读本地 Policy bundle loader

应用 loader 必须消费且只消费：

1. `AI_POLICY_FILE` 指向的最终 Policy envelope；
2. R3 manifest 已绑定的 `ai-policy-v1.schema.json`；
3. R3 manifest 已绑定的 `ai-policy-v1.companion-validator.json`；
4. R3 manifest 已绑定的 `ip-deny-cidrs-v1.json`。

为避免安装后依赖仓库相对 `docs/` 路径，Gate C 必须在 installable `app` package 内新增固定 resource namespace `app.ai.artifacts.cr011_v1`。该 namespace 只携带下表四个 byte-identical leaf；loader 使用 `importlib.resources` 或等价 package-resource API 读取，不搜索仓库根、当前工作目录或相对 `docs/change-requests`：

| runtime resource | raw bytes | raw SHA-256 | 用途 |
|---|---:|---|---|
| `ai-policy-v1.positive.json` | 9708 | `da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb` | contract/offline 唯一允许的 synthetic final envelope |
| `ai-policy-v1.schema.json` | 28811 | `8d583164b46cb2cfa6315efa86491bd6cdc17c818be79dd9c7c274903c9399e3` | Draft 2020-12 Schema |
| `ai-policy-v1.companion-validator.json` | 9071 | `10b9b67042060905ad1c7eb0dcd678724be3b01117eb3963332b51b9c626bed3` | 固定 companion 顺序/规则声明 |
| `ip-deny-cidrs-v1.json` | 5874 | `628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34` | canonical address registry |

package build、wheel 安装和 source checkout 三种形态都必须逐字复核上述四项 data leaf；`__init__.py`/package metadata 不计入 leaf 集合。四项 data leaf 缺项、额外 JSON data leaf、名字大小写漂移或 byte/hash 漂移均失败关闭。R3 `manifest.json` 仍是唯一 source identity，不复制到 runtime namespace，也不要求运行时依赖仓库文件。

`AI_POLICY_FILE` 必须是显式、drive-qualified 的 Windows 本地绝对文件路径。loader 必须先对 Settings 中的原始字符串执行纯词法 gate，且在 gate PASS 前不得调用 `stat/lstat/GetFileAttributes`、`open/read`、`resolve/realpath` 或读取 package resource。唯一可接受的根形态是 `<ASCII letter>:\...`；拒绝 UNC、extended/device/NT namespace（包括 `\\?\`、`\\.\`、`\??\`、`\Device\` 及其大小写变体）、Windows named pipe、reserved DOS device component、drive-relative、root-relative、forward-slash、空/`.`/`..` component、NUL/control/wildcard、尾随空格/句点，以及除 drive designator 外出现任何冒号的 ADS/stream 形态。上述纯词法负例必须在 filesystem I/O attempt 精确为 `0` 时失败。

纯词法 gate PASS 后、任何 package-resource read、path component metadata 或 target open 前，必须执行无网络的 `drive_root_locality`：以 Win32 `GetDriveTypeW` 与 DOS-device mapping 的等价只读查询同时确认 drive type 恰为 `DRIVE_FIXED`，且 DOS-device target 恰属本地 physical-volume device。`DRIVE_REMOTE`、redirector/MUP/UNC-backed、subst-to-UNC、非 physical-volume target、unknown/no-root 及任何非 `DRIVE_FIXED` 结果一律失败关闭；不得为分类探测 share、follow redirector 或尝试 socket/DNS。失败时 package-resource、component metadata、target `open/read` 与 network attempts 必须均为 `0`。

`drive_root_locality` PASS 后，loader 必须先从 §2.2 固定 package namespace 读取并验证四项 resource 的 exact set/name/size/raw hash；缺项、多项、漂移或解析准备失败都必须在接触 external Policy filesystem metadata 前以 `package_resource_identity` 阶段失败。Schema、companion 与 registry 不得由 HTTP、DNS、数据库、Redis、Broker、请求参数、工作目录搜索、glob、环境变量或测试注入替换。

package-resource identity PASS 后，loader 才可从 drive root 到 external Policy 目标逐 component 使用 non-following `lstat` 与 Windows file attributes 检查；目标和全部父 component 均不得是 symlink、junction、mount point 或任何带 `FILE_ATTRIBUTE_REPARSE_POINT` 的对象，目标还必须是 regular file。禁止用 `Path.resolve()`、`realpath()`、普通 follow-stat 或 glob 代替该检查。打开前必须记录每个 component 的稳定 identity/attributes；目标用 no-follow handle 打开后，必须以 handle `fstat`/等价 Win32 identity 验证与 pre-open target 相同，并在有界读取完成后重新验证目标和全部父 component identity/attributes 未变化。任何缺失、替换、reparse、类型或 before/after identity 漂移都失败关闭，不得重试到另一条路径、跟随目标或回退缓存。

external Policy 在完整验证前只允许完成路径检查、一次 no-follow 有界读取、size gate 和 before/after identity；单文件上限固定为 `1_048_576` bytes。读取阶段可以计算并保留 raw length/hash，但不得提前把它与 approved raw identity 比较。目录、缺失、超限、读取或 identity 错误在对应 path/read 阶段拒绝；读取成功后，final-envelope validation 必须严格单次执行 companion artifact 冻结的完整顺序：`POL-VAL-001 -> POL-VAL-002 -> POL-VAL-003 -> POL-VAL-004(Draft 2020-12 Schema) -> POL-VAL-005 -> POL-VAL-006(JCS/self-hash) -> POL-VAL-007 -> POL-VAL-008 -> POL-VAL-009 -> POL-VAL-010 -> POL-VAL-011 -> POL-VAL-012(accept)`。`POL-VAL-006` 必须保持在 `POL-VAL-005` 与 `POL-VAL-007` 之间；不得跳过、重排、合并或二次执行任一 rule，每个 rule 失败后不得执行下游 rule。

只有 `POL-VAL-012(accept)` 后才允许执行 `approval_identity_pin -> Settings/Policy cross-binding -> immutable adoption`。`approval_identity_pin` 此时只比较读取阶段已保留的 external raw `9708/da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb` 和 `POL-VAL-006` 已验证的 approved `policy_hash=db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d`；不得再次 JCS canonicalize 或再次计算 self-hash。任一其他即使已通过 `POL-VAL-001`～`POL-VAL-012(accept)` 的 Policy 也在 approval pin 拒绝。positive resource 只用于 expected identity 和可移植 synthetic fixture；loader 仍必须真实读取 `AI_POLICY_FILE`，不得改成 package-only Policy，也不得在文件缺失时回退到 package resource。

该 synthetic Policy 的 hostname、CIDR、model、Tokenizer、pricing、secret slot 和 capacity 都是 R3 固定测试值，不是 `fixed_test_provider` 或 production 的目标环境 Profile。R5 不批准将其用于任何真实连接、依赖健康探针、费用/性能或业务结果。应用不得维护第二套字段、Schema、companion 顺序、JCS 或 network registry 算法；可以复用已通过 Gate B 的纯实现，但必须把 Draft 2020-12 adapter 从 test-only 注入边界提升为明确的运行时 Port 实现。

loader 的成功结果必须是不可变、已验证且包含最终 `policy_version/policy_hash` identity 的只读对象。失败只返回固定安全类别、失败阶段/rule 和稳定内部错误标识；异常、日志、Trace、指标与测试报告不得包含原始 Policy bytes、路径中的敏感片段、配置值、secret sentinel 或业务正文。

### 2.3 STARTUP-D-003：Settings 与 Policy 交叉绑定

应用启动必须同时满足：

- `Settings.ai_policy_version == 1`；
- `Settings.ai_provider_policy_schema_version == 1`；
- `Settings.ai_provider_calls_enabled is False`；
- 最终 Policy 的 `policy_version == 1`；
- 最终 Policy 的 `provider_calls_enabled is false`；
- 最终 `policy_hash` 与删除且只删除顶层 `policy_hash` 后的 RFC 8785 JCS preimage 精确一致。

R5 不新增可被环境覆盖的 expected-hash 字段。运行时代码必须以不可变常量绑定 §2.2 的 `raw_sha256=da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb` 与 `policy_hash=db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d`；`AI_POLICY_FILE` 只能选择通过 §2.2 fixed-local-physical-drive/non-reparse gate 的绝对路径，不能提供或覆盖 expected hash。Settings 的 Policy 镜像字段必须按下表逐项比较，不得只比较 version/calls-disabled：

| Settings 字段 | exact synthetic Policy 投影 |
|---|---|
| `ai_policy_version` | `policy_version` |
| `ai_provider_policy_schema_version` | 值 `1` 绑定 `$id=urn:finaudit:schema:ai-policy-v1` 及 schema raw hash `8d583164b46cb2cfa6315efa86491bd6cdc17c818be79dd9c7c274903c9399e3` |
| `ai_provider_calls_enabled` | `provider_calls_enabled` |
| `ai_policy_file` | §2.2 synthetic envelope 的 raw identity 与内部 `policy_hash` 双 pin |
| `llm_base_url` | `profiles.llm_extraction_primary.base_url`；只作为旧单 URL 镜像，不得推导 generation/fallback URL |
| `llm_extraction_model` | `profiles.llm_extraction_primary.model_id` |
| `llm_generation_model` | `profiles.llm_generation_primary.model_id` |
| `llm_fallback_model` | `profiles.llm_fallback.model_id`，R5 synthetic 启动时不可为 null |
| `embedding_base_url` / `embedding_model` | `profiles.embedding_primary.base_url/model_id` |
| `qdrant_vector_size` / `embedding_vector_size` | 二者均等于 `profiles.embedding_primary.embedding_dimension` |
| `llm_connect_timeout_seconds` | 六个 `operations.*.connect_timeout_seconds` |
| `llm_max_attempts_per_generation` | 合同/发票/风险/RAG 的 `max_attempts`；报告由下一行单独派生 |
| `llm_max_same_target_attempts` | 五个 LLM operation 的 `max_same_target_attempts` |
| `ai_max_provider_attempts_per_operation` | 五个 LLM operation 的 `max_provider_attempts_per_business_operation` |
| `ai_max_model_repairs` | 五个 LLM operation 的 `max_model_repairs` |
| `llm_report_draft_use_fallback` | `operations.report_draft.report_use_fallback`；false/true 分别要求报告 `max_attempts=2/3` |
| 六个 `AI_*_DEADLINE_SECONDS` | 按同名业务语义逐一映射六个 `operations.*.deadline_seconds` |
| `ai_retry_backoff_base_seconds/multiplier/max_seconds/jitter_ratio` | `retry.backoff_base_seconds/backoff_multiplier/backoff_max_seconds/jitter_ratio` |
| `ai_breaker_failures/window_seconds/open_seconds/half_open_probes` | `breaker` 对应四字段 |
| `ai_rag_limits` / `ai_async_generation_limits` / `ai_embedding_limits` | 严格解析 `concurrency/rpm/tpm/burst` 后分别等于三个 `rate_limits` 对象；拒绝空白、符号、前导零、额外段和 boolean |
| 四个 `AI_MAX_*_BYTES` | `outbound_limits` 对应 request/header/chat/embedding 四字段 |

Policy-only 的 `adapter_id/endpoint_id/model_version/capabilities/allowed_response_model_ids/context_window/tokenizer/pricing/network/CIDR`、operation Token/费用上限和 retry 其余字段没有 Settings 镜像；它们只能由完整 final envelope、exact raw/hash pin 和 Schema+companion 验证提供，不得从旧 Settings 推导。`llm_api_key/embedding_api_key` 等 SecretStr 也不与 Policy 内容比较；loader 只验证 Policy 中的 secret slot 名，Gate C 不读取 slot 值。

任一缺失、Policy 侧类型强转、版本不一致、calls enabled、Schema/companion/registry identity 漂移或 hash 不一致都必须在启动期失败关闭。Settings 仍按 Pydantic Settings 的环境字符串解析规则产生强类型值，但不得用其 coercion 放宽 raw Policy JSON。Policy 只保存 secret slot 名；本切片不解析、读取、探测或验证 slot 对应 secret 值。

旧 `LLM_REQUEST_TIMEOUT_SECONDS/LLM_MAX_RETRIES/LLM_MAX_CONCURRENCY/EMBEDDING_REQUEST_TIMEOUT_SECONDS` 可以继续被 Settings 识别为 legacy 输入，但不得进入、补齐或改写最终 Policy；启用调用仍一律失败。R5 不重新解释旧字段，也不新增隐式默认。

环境层行为固定为：

| `APP_ENV` | R5 本地启动行为 |
|---|---|
| `local` | 只允许合成/本地只读 Policy、calls disabled、零 socket；`POL-VAL-001`～`POL-VAL-012(accept)`、approval pin 与 cross-binding 全部通过后才可启动骨架 |
| `test` | 同 local；只允许调用方显式注入临时只读 synthetic `AI_POLICY_FILE` 的 fixed-local-physical-drive 绝对路径，不读取真实 `.env`；Schema/companion/registry 始终来自固定 package resources，不可注入或替换 |
| `prod` | 由于 production 环境签署仍缺失，必须在 ASGI app 暴露、uvicorn bind、Celery app 创建及任何外部 I/O/客户端创建前固定失败关闭；R5 不提供 production bypass |

### 2.4 STARTUP-D-004：FastAPI 与 Worker pre-socket 采用

FastAPI 固定顺序必须为 `Settings validation -> local Policy preconditions/read -> §2.2 frozen single-pass POL-VAL-001～POL-VAL-012(accept) -> approval_identity_pin -> Settings/Policy cross-binding -> create_fastapi_app -> app.state 只读采用 -> expose ASGI app`。首次验证必须发生在 module import/app factory/project bootstrap，且在返回或暴露 ASGI app、调用 `uvicorn.run`、bind/listen 或创建 server socket 之前完成；lifespan 只能消费已采用的不可变 snapshot，不得作为首次验证点。R5 支持的启动入口必须先成功构造已验证 app 再交给 server，禁止绕过 bootstrap 直接启动未验证的 app。任何失败都不得产生可绑定或可接收请求的 ASGI app。

Worker 固定顺序必须为 `Settings validation -> Policy preconditions/read -> §2.2 frozen single-pass POL-VAL-001～POL-VAL-012(accept) -> approval_identity_pin -> cross-binding -> create_celery_app`。在验证成功前禁止构造 Celery application/client、访问 `broker/backend` 属性、加载 Broker transport、执行 task discovery 或进行其他可能的外部 I/O；模块级 `celery_app` 也不得先创建后补验证。Backend 与 Worker 使用同一 loader 和错误合同，不复制 validator；服务可只投影自身需要的已验证 Settings，但不得用“Worker 不发送 Provider”绕过 Policy 启动门禁。

两条入口都不得在本切片创建数据库 engine/session、Redis client、Broker connection、HTTP client、DNS resolver、socket、线程式探针或后台任务。验证成功只把不可变 Policy identity 暴露给应用内部依赖，不创建 Provider Adapter，不产生 `SendPermit/AdoptPermit`，也不采用任何 AI 业务结果。

### 2.5 STARTUP-D-005：本地 zero-socket 启动证据

R5 Gate C 必须在净化子进程中覆盖：

- FastAPI `local/test` 正向 bootstrap/app-factory 各至少一次并证明验证先于 ASGI app 暴露与 bind，Worker `local/test` 正向初始化各至少一次；
- `prod`、缺失关键 Settings、缺失 Policy、超限、BOM/非法 UTF-8/NUL、重复 key、Schema 失败、companion 失败、package resource identity 漂移、`POL-VAL-005` registry binding 失败、self-hash 漂移、合法但未批准 identity、Settings parse/calls safety、Settings/Policy mirror mismatch 和 legacy 不得迁移的负向启动；
- Windows 路径负例至少覆盖 UNC、extended/device/NT namespace、named pipe/reserved DOS device、ADS、drive-relative、root-relative；每项必须在 `GetDriveTypeW/QueryDosDeviceW/stat/lstat/GetFileAttributes/open/read/importlib.resources` 总 attempt 精确为 `0` 时拒绝；
- `drive_root_locality` 负例至少覆盖 `DRIVE_REMOTE`、redirector/MUP/UNC-backed、subst-to-UNC、unknown/no-root 和其他非 `DRIVE_FIXED`；只允许 test-only classifier seam 表达远端/重定向结果，禁止实际连接 remote drive，并至少保留一个真实本地 fixed physical-volume 正向 integration。失败时 package-resource/component/open/network attempts 均为 `0`，该 seam 不得进入 app bootstrap；
- reparse 负例至少覆盖 file symlink、parent symlink、junction 和 junction-to-UNC；使用 injected/synthetic local metadata 表达 UNC target，禁止实际创建或接触远端 share。除固定 package-resource precondition 和预期 non-following component metadata checks 外，follow-stat、reparse traversal、target `open/read` 和 network attempt 必须各为 `0`，并覆盖 before/after identity replacement；无 symlink privilege 时允许 test-only metadata seam 覆盖 file/parent symlink 分支，但至少保留一个真实本地 reparse/junction integration；该 seam 不得暴露到 app bootstrap，且本 Gate 不宣称通用并发文件系统 sandbox；
- stage oracle 必须先证明 path lexical、drive-root、path/read 或 package-resource precondition 任一失败时全部 `POL-VAL-*` attempt 为 `0`，其中 mapped/redirected root 只命中 `drive_root_locality`，package resource 漂移只命中 `package_resource_identity`；进入完整验证后必须逐项绑定 companion artifact：BOM/duplicate/非法 UTF-8 命中 `POL-VAL-001`，source integer 命中 `POL-VAL-002`，envelope context 命中 `POL-VAL-003`，Schema 命中 `POL-VAL-004`，registry binding 命中 `POL-VAL-005`，self-hash 命中且只命中一次 `POL-VAL-006`，cross-field/network fixed vectors 依次命中 `POL-VAL-007`～`POL-VAL-011`，正向完整验证最终命中 `POL-VAL-012(accept)`；每例只能出现一个首个失败 rule，全部下游 rule attempt 为 `0`；
- `POL-VAL-012(accept)` 前 `approval_identity_pin/cross-binding/adoption` attempts 必须为 `0`；accept 后，语义与 self-hash 合法但 raw/policy identity 未批准只命中 `approval_identity_pin`，通过 approval pin 后的 Settings mirror mismatch 只命中 cross-binding。全程 `POL-VAL-006` attempt 必须精确为 `1`，approval pin 不得触发第二次 JCS/self-hash；
- 原始 Policy、secret、业务正文和路径 sentinel 在 `str/repr/errors/json/log/trace/report` 中均为零出现；
- 整个被测启动进程对 TCP、UDP、numeric loopback、`localhost`/其他 hostname DNS、Unix domain/Windows named pipe 和其他本地 socket 的 attempt 精确为 `0`；
- 不读取真实 `.env`，不继承代理、Provider、数据库、Redis、Broker、secret 或 production 环境变量；调用方只可显式注入 Settings test values 与临时只读 synthetic `AI_POLICY_FILE` 的 fixed-local-physical-drive absolute path，不可注入/替换 Schema、companion 或 registry。

正向骨架启动不等于依赖健康、业务 API、Compose、Worker 消费、Provider 或 production 运行。负向 `prod` PASS 只证明拒绝启动，不证明 production readiness。

### 2.6 STARTUP-D-006：正式 DoD 重新裁定

R5 Gate C PASS 后，必须对 `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` 的 `BASE-004` 输出、开发内容、验收标准和测试要求逐条重新裁定。Gate C 只使用 R3 exact synthetic Policy，它不是目标环境 Profile，也不证明 `.env.example` 已生成可运行的完整本地 P0、按服务配置分层、真实 Secret source 或 production 配置，因此 **Gate C PASS 不自动把 BASE-004 改为 implemented**。只有 `.env.example`/Settings/Policy Schema、分层、敏感值边界、完整启动验证、legacy 不迁移、calls disabled、JCS/SHA-256、配置/脱敏/错误启动测试全部有直接证据时，才可把 `BASE-004` 记为 `implemented`；否则继续 `partial` 并列出缺项。

`BASE-004 implemented` 还必须同时满足 Request 计划 §11 全局 DoD，包括受保护分支合并、review + QA 与第三方可复现证据；R5 明禁 commit/push/PR，且当前无 remote/HEAD 证据，因此 Gate C 本身不能单独升级 implemented，缺少这些外部证据时必须继续 `partial`。

R4 Gate C 的 durable reserve/DB/Outbox/Worker/Provider runtime 和真实 Provider/network 不是 `BASE-004` 配置工作包的完成前置，必须继续由 AI-005、BASE-005/006、Provider 环境和部署合同独立治理。即使 `BASE-004` 最终记为 `implemented`，`AI-001`、TEST-001、P0、AC-015/016、部署和 production 状态也不得自动升级。

---

## 3. 依赖与实现边界

### 3.1 批准后允许的最小变更

只有九角色有效批准且 R5 Gate B 十一文件原子同步完成后，才允许：

1. 在本地 Gate C 的 Backend application 依赖声明中加入 `jsonschema==4.26.0`，并继续以 §2.1 的 CPython 3.10/Windows x86-64 完整精确闭包安装/验证；该声明不构成其他平台或 production runtime 批准；
2. 将既有 R3-origin Schema/companion/registry 只放入 §2.2 固定的 `app.ai.artifacts.cr011_v1` package resource namespace，并逐字复核；不得使用其他 bundle、仓库相对路径或可配置资源目录；
3. 实现一个共享 Policy loader/validated snapshot 类型；除 §2.2 明确的有界本地只读输入外不得产生 I/O 副作用；
4. 把该 loader 接入 FastAPI module import/app factory/project bootstrap 与 Worker bootstrap 的 pre-socket 路径；FastAPI lifespan 只消费已验证 snapshot；
5. 增加 synthetic、zero-socket 的单元/进程内启动测试和失败即停 runner；
6. Gate C PASS 后只同步 README、CHANGELOG、MEMORY、requirements map、gap、test strategy、P0 matrix 等现状型 tracking，不改写 Request 合同或 R5 snapshot。

实现必须优先复用 `backend/app/ai/policy_companion.py`、strict JSON/JCS 与现有 Settings；不得为同一合同再写第二套 parser、Schema model 或 network allowlist。新增文件和依赖必须是达到上述 Gate 的最小集合。

### 3.2 始终不由 R5 授权的范围

以下内容保持 `PENDING / NOT AUTHORIZED`：

- 任何真实 `.env`、secret slot 值、Token、API Key、密码、私钥、真实 Provider/业务 endpoint、model、Tokenizer、pricing、quota、CIDR、capacity 或业务数据；
- `dependency acquisition` 阶段超出 §2.1 唯一有界例外的任何行为，包括非 allowlist host/IP literal、HTTP、非 `GET`、redirect、proxy、镜像/extra index、`trusted-host`、TLS verification bypass、retry、并发、未设 response cap/timeout、上传、Provider 或业务网络；
- remote/redirected/mapped/UNC-backed/subst-to-UNC/unknown drive root 作为 `AI_POLICY_FILE` 来源；
- `application startup/test/runtime` 阶段的全部 TCP/UDP/DNS/TLS/HTTP/socket/Provider/内部 vLLM/其他外网/代理/redirect 或 peer 探测；
- PostgreSQL、migration、Repository、durable Sink、`ai_call_logs`、Outbox、Redis、Broker、Celery connection、Job/Worker 消费、reconciler 或跨进程恢复；
- `fixed_test_provider`、真实 Chat/Embedding、真实费用/性能、业务结果采用、`SendPermit/AdoptPermit` 发放；
- 新 API route、状态码、数据库表/列、页面、P0 工作包或 operation action；
- Docker/Compose runtime、云资源、部署、canary、production migration、production 放行；
- 全局依赖安装、提交、推送、PR、发布或远程写入。

本 CR 的 PyPI 网络例外只存在于 §2.1 独立 acquisition 阶段，并恰为 allowlist host 的 DNS + verified TLS + HTTPS `GET`。该进程退出且净化环境完成后才可开始 startup 阶段；startup 的 socket/DNS/HTTP attempts 必须重新从零计数并保持精确为 `0`。两个阶段不得共用进程、client、session、resolver cache、proxy/index 配置或证据计数。

---

## 4. R5 三层 Gate

### 4.1 R5 Gate A：审批前静态可签署性

Gate A 必须在任何 R5 审批前只读完成：

1. 机械复算 R3 `26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be`、artifact manifest `5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` 与全部 15 个 leaf identity；
2. 机械复算 R4 `27384/cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10`，确认其批准、同步和完整 Gate B evidence；
3. 验证 §5.1 当前十一文件 pre identities 全部逐字匹配，`approval_pre_meta.py::_BASELINE_IDENTITY` 精确指向当前 baseline manifest；
4. 验证 §2.1 lock 的 `641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c`，并从当前 wheelhouse 复算六项 exact filename/raw bytes/hash、无额外依赖与 Node runtime promotion；
5. 机械确认 `STARTUP-D-001`～`STARTUP-D-006` 恰好六项、`AI-D-009`～`AI-D-014` semantic/artifact delta 为零、R5 不授权 §3.2 内容；
6. 严格 UTF-8/LF、无 BOM/NUL/替换字符检查，并按 §8 复算 R5 decision snapshot；
7. material-value scan 为零：除 §2.1 明示的官方 PyPI acquisition host 外，不得出现真实 secret、Provider/业务 endpoint、CIDR、Profile、业务数据或 production 放行值。

Gate A 不安装依赖、不访问网络、不修改十一文件、不实现 loader，也不等于批准。任何 pre identity、base identity、lock、decision set、编码或范围失败都使候选不可签。

### 4.2 R5 Gate B：批准后的十一文件原子同步

只有九角色以同一 R5 decision snapshot 有效批准后，才运行 Gate B：

- 严格按 §5 先在临时区生成九份 Request post bytes、baseline manifest post bytes 和 `approval_pre_meta.py` 两 literal re-pin；
- 对九份 Request 的 R5 领域投影、文件集合、post identities、manifest 九项表、active pin、UTF-8/LF 和无自引用执行双实现/独立复核；
- 十一个目标必须全有或全无地替换；任一步失败即回滚整个集合；
- 同步完成前不得修改 runtime dependency、Backend/Worker 入口或测试；同步成功不等于 Gate C、BASE-004 或任何 AC 通过。

### 4.3 R5 Gate C：本地离线 non-provider startup adoption

Gate B PASS 后才允许 Gate C：

1. 在隔离本地环境先固定并验证 CPython 3.10/Windows x86-64 platform gate，再按 §2.1 `BOUNDED_EXACT_ACQUISITION` oracle 安装/验证六项 exact filename/bytes/hash；必要 acquisition 只能在独立进程对 `pypi.org`/`files.pythonhosted.org` 执行有界 DNS + verified TLS + HTTPS `GET`，`retry=0`，并覆盖 short/extra/hash/redirect/timeout/temp-cleanup 负例。该进程退出并净化环境后，以新进程执行 startup zero-socket；
2. 打包并在 source checkout 与 built wheel 安装形态复核 §2.2 四个 portable resources 的 name/bytes/hash；禁止运行时读取仓库相对 `docs/`；
3. 实现 §2.2～2.4 Windows fixed-local-physical-drive/non-reparse loader、single-pass `POL-VAL-001`～`POL-VAL-012(accept)` 冻结顺序、post-accept approval pin、完整 Settings 映射、FastAPI pre-exposure/pre-bind bootstrap 与 Worker pre-Celery-app 入口；
4. 执行 §2.5 全部正负向、脱敏和 zero-socket 测试；
5. 运行聚焦配置/Policy/App/Worker 回归、R4 full Gate B、Backend Ruff/format/mypy/pip consistency 和默认本地离线质量门禁；
6. 独立 reviewer 逐项核对实现只消费 R3 artifacts、未接入 Provider/DB/Redis/Broker/真实环境/部署，并复核正式 BASE-004 DoD。

Gate C 的输出必须分别记录 dependency acquisition（如有）的 request count、exact host/method/TLS/timeouts/retry、metadata cap、artifact filename/bytes/hash 与 temp cleanup，以及 startup 的 zero-socket/zero-DNS attempts；不得把 acquisition 统计、进程或客户端混入 startup evidence。Gate C PASS 只证明本地离线应用启动采用与失败关闭，不证明 Provider、durability、业务 E2E、Compose、production 或 AC。

本节的 `R5 Gate C` 与 R4 §7.3 的 persistent AI-005/runtime Gate C 是不同、带 revision 前缀的门禁。R4 persistent Gate C 继续 `PENDING / NOT AUTHORIZED`。

---

## 5. 十一文件 active-baseline 原子同步

### 5.1 精确目标与当前 pre identities

批准后的同步目标必须恰为：

1. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
2. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
5. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
7. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
8. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
9. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
10. `docs/baseline-manifest.md`
11. `backend/app/approval_pre_meta.py`

九份 Request 的 pre-sync raw identity 固定如下：

| Request path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 128874 | `0c8ece722c3935cf0fad9117db96985228ceaee864f542fc407cf5e3c8234492` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 90344 | `3074ad8e1640cd709adf0defbd40d9f3e6417ca5345276244c96c31d865ccd89` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 115654 | `4ffa09ded6c0351730070d140d4bf9709060531306bebe9dfb99c39d35512ddf` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 328001 | `fee560512e39086bc3e1340c127054623c701b6e4d92dd058efb70cb8a5cf830` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 83278 | `f6730f09f95f761af31657fe14ad80d65c11bc914de7285ba09501c611d52ac9` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 51306 | `6676a2d8cdaa5a85e8f62937292aa4530dedd456dd9a6bbc2ebd627d808b5a43` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 49975 | `63ef73a6c98c0e57b8e88271db930294cf1934f3fdc62a8f6322628adaa1bea5` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 54314 | `99ba1c5226dc104ce2d96e1c80ee935de0a117116d5a608e3047c2ca2f7232ac` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 106372 | `e52cffaa687c2460ce021a23b2565b1948673a84226552cc3460523b5bf22a3e` |

同步配套文件 pre identity 固定为：

```text
path=docs/baseline-manifest.md
raw_bytes=1647
raw_sha256=4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94

path=backend/app/approval_pre_meta.py
raw_bytes=22193
raw_sha256=67a3457c5a0958e9bd443033a6cb1654a4ef5f0ec9b04e99437a1d2331203f71
allowed_change=_BASELINE_IDENTITY.byte_length|_BASELINE_IDENTITY.sha256
```

`approval_pre_meta.py` 当前 `_BASELINE_IDENTITY` 必须精确为 manifest 的 `1_647/4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94`。本 CR 只允许把该对象的 `byte_length` 和 `sha256` 两个 literal 替换为 post-sync manifest identity；不得修改路径、Schema/snapshot identities、角色/fact-set、解析/批准逻辑、marker 或 CLI 输出。现有测试不得为同步便利而放宽。

### 5.2 九份 Request 的唯一领域投影

九份 Request 只同步以下 R5 scope：

- 需求：记录 R3/R4 语义零变化、R5 本地启动采用和 Provider/production 继续关闭；P0 数量不变。
- 架构：增加 Settings→fixed-local-physical-drive/path/package preconditions→read→single-pass `POL-VAL-001`～`POL-VAL-012(accept)`→approval pin→cross-binding→adoption 的 pre-socket 顺序；不引入外部 client 或持久 runtime。
- 数据库：明确表、列、migration、seed、Repository 和 AI-005 投影增量均为零。
- API：明确 route/status/body delta 为零，startup internal error 不成为新公开 API；不开放 Provider 能力。
- 页面：明确页面/路由 delta 为零，前端不得读取 Policy、secret 或推断 Provider/runtime readiness。
- AI/RAG：引用 R3 exact artifacts 和 R4 base，只增加 loader adoption，不复制或修改 `AI-D-*`。
- 测试：增加 R5 Gate A/B/C、synthetic local/test/prod 失败关闭与 zero-socket 证据；不冒充 R4 persistent Gate C。
- 部署：只记录 calls disabled、本地只读配置和 prod 固定拒绝；不写真实 endpoint/CIDR/secret，不部署。
- 计划：记录 BASE-004 DoD 复核入口；`AI-001`、AI-005、BASE-005/006、TEST-001、AC、部署和 production 状态不自动变化。

每份 Request 只新增一条 `CR-011-R5 / approved contract-offline startup scope` 修订记录和一处必要投影；不得把自身 post length/hash 写入正文，不得顺带修订其他 gap、任务、表/API/page 数量或候选 CR。

### 5.3 无环生成 DAG 与原子验收

生成顺序固定为：

```text
R3 snapshot/artifacts + R4 snapshot + current 11 pre identities
                              |
               R5 sections 1-8 snapshot
                              |
                    valid nine-role approval
                              v
                  nine Request post bytes
                              v
               nine Request post identities
                              v
                baseline-manifest post bytes
                              v
               baseline-manifest post identity
                              v
 approval_pre_meta._BASELINE_IDENTITY two-literal re-pin
                              v
                 R5 section 9 dynamic evidence
```

Request 不包含自身 post identity；baseline manifest 只记录九份 Request post identities，不记录自身 identity；唯一跨出 manifest 的消费例外是 `approval_pre_meta.py::_BASELINE_IDENTITY` 两个 literal 可以消费已经生成的 manifest post identity。R5 文件不属于十一文件同步集合。九份 Request post identities、manifest post identity 和 re-pin 文件 post identity 只能进入 §9 动态状态与外部 tracking，不得进入 R5 decision preimage。

实现必须先在临时区生成并验证全部 post bytes，再原子替换十一文件。任一 pre identity、领域投影、post hash、manifest 条目、两-literal diff、UTF-8/LF、baseline verifier 或独立复核失败，都必须回滚整个集合，不得保留部分同步。

---

## 6. 九角色审批与可复制记录

### 6.1 必需角色

本 CR 必须由以下九角色共同批准；一人具备多个角色权限时可以合并为一条记录，但必须显式列出全部角色：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | BASE-004 用户影响、P0 delta 为零、DoD 裁定边界与 Request 同步 |
| 架构 | pre-socket loader、共享 validator、local/test/prod 分层和零持久 runtime |
| 数据/DBA | 零数据库/migration/Repository/AI-005 delta |
| 后端/API | FastAPI/Worker startup、零 API delta、失败关闭和依赖边界 |
| 前端/UI | 零页面/路由 delta、前端不消费 Policy/secret/runtime readiness |
| AI/RAG | R3 artifacts/`AI-D-*` 零语义 delta、Policy cross-binding、Provider 非授权 |
| 测试/质量 | R5 Gate A/B/C、十一文件原子同步、negative/zero-socket/脱敏证据 |
| 运维/可靠性 | exact runtime closure、prod 固定拒绝、无部署/恢复/Provider 放行 |
| 安全 | 本地 artifact trust、路径/字节边界、secret 脱敏、零 socket 与供应链范围 |

### 6.2 可复制 approval template

以下记录只能在 R5 Gate A PASS、`decision_snapshot_sha256` 已由独立实现复算后填写。任何占位、缺失字段或不同 snapshot 都不构成有效批准：

```text
姓名=YHBX
角色=需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全
decision=APPROVED
selected_option=AI-D-009～AI-D-014_R3_EXACT_WITH_R4_BASE_AND_R5_OFFLINE_STARTUP_GOVERNANCE
selected_decisions=[STARTUP-D-001,STARTUP-D-002,STARTUP-D-003,STARTUP-D-004,STARTUP-D-005,STARTUP-D-006]
rejected_decisions=[]
cr_revision=CR-011-R5
base_revision=CR-011-R4
base_decision_preimage_bytes=27384
base_decision_snapshot_sha256=cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10
r3_decision_preimage_bytes=26563
r3_decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be
artifact_manifest_raw_bytes=5128
artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c
dependency_lock_path=scripts/requirements-cr011-gate-b.txt
dependency_lock_raw_bytes=641
dependency_lock_sha256=0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c
decision_snapshot_sha256=<R5_GATE_A_OUTPUT>
environment_scope=contract_offline_startup
policy_version=1
baseline_manifest_pre_raw_bytes=1647
baseline_manifest_pre_raw_sha256=4eb5277d8bb486240626cb7029270009fa468933cb1eb34e89026b4399b30d94
approval_pre_meta_pre_raw_bytes=22193
approval_pre_meta_pre_raw_sha256=67a3457c5a0958e9bd443033a6cb1654a4ef5f0ec9b04e99437a1d2331203f71
approval_pre_meta_repin_scope=_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY
scope=CR-011-R5_BASE004_APPLICATION_STARTUP_POLICY_ADOPTION_OFFLINE_FAIL_CLOSED
dependency_acquisition_network_scope=PYPI_OFFICIAL_REGISTRY_DNS_TLS_HTTPS_ONLY
startup_network_scope=ZERO_SOCKET
startup_socket_attempts_required=0
allowed_dependencies=PYTHON_JSONSCHEMA_4_26_0_RUNTIME_EXACT_HASHED_CLOSURE|ATTRS_26_1_0|JSONSCHEMA_SPECIFICATIONS_2025_9_1|REFERENCING_0_37_0|RPDS_PY_0_30_0|TYPING_EXTENSIONS_4_16_0
allowed_actions=VERIFY_OFFICIAL_METADATA|REUSE_OR_DOWNLOAD_EXACT_HASHED_ARTIFACTS|BOUNDED_EXACT_ACQUISITION|VERIFY_EXISTING_FULL_TRANSITIVE_HASH_LOCK|INSTALL_IN_ISOLATED_LOCAL_ENV|PROMOTE_LOCKED_PYTHON_DRAFT202012_VALIDATOR_TO_LOCAL_GATE_C_APPLICATION_RUNTIME|PACKAGE_EXACT_CR011_RUNTIME_RESOURCES|BUILD_AND_INSPECT_LOCAL_WHEEL|VALIDATE_WINDOWS_DRIVE_QUALIFIED_NON_REPARSE_POLICY_PATH|VALIDATE_FIXED_LOCAL_PHYSICAL_DRIVE_ROOT|IMPLEMENT_BOUNDED_READONLY_LOCAL_POLICY_LOADER|VALIDATE_SETTINGS_POLICY_CROSS_BINDING|INTEGRATE_FASTAPI_AND_WORKER_PRE_SOCKET_STARTUP|RUN_SYNTHETIC_LOCAL_TEST_PROD_MATRIX_ZERO_SOCKET_TESTS|SYNC_TRACKING_AFTER_PASS
forbidden_scope=ACQUISITION_NON_PYPI_HOST|ACQUISITION_IP_LITERAL|ACQUISITION_HTTP_PLAINTEXT|ACQUISITION_NON_GET|ACQUISITION_REDIRECT|ACQUISITION_PROXY|ACQUISITION_MIRROR_OR_EXTRA_INDEX|ACQUISITION_TRUSTED_HOST_OR_TLS_BYPASS|ACQUISITION_RETRY|ACQUISITION_UNBOUNDED_RESPONSE|STARTUP_TCP|STARTUP_UDP|STARTUP_DNS|STARTUP_TLS|STARTUP_HTTP|STARTUP_SOCKET|UNSAFE_POLICY_PATH|REMOTE_OR_REDIRECTED_DRIVE_ROOT|POLICY_REPARSE_TRAVERSAL|NODE_AJV_RUNTIME|PROVIDER|BUSINESS_NETWORK|DATABASE|REDIS|BROKER|CELERY_CONNECTION|REAL_ENV|SECRET_VALUES|REAL_DATA|DOCKER|DEPLOYMENT|CANARY|PRODUCTION_RELEASE|GLOBAL_INSTALL|COMMIT|PUSH|PR
authorized_scope=exact_nine_request_plus_baseline_manifest_sync|approval_pre_meta_active_baseline_identity_repin_only|base004_fixed_local_physical_drive_non_reparse_policy_loader_and_pre_socket_startup_adoption|python_jsonschema_existing_exact_runtime_closure|synthetic_zero_socket_evidence
日期=<YYYY-MM-DD>
证据链接=<本 Codex task 的批准消息>
备注=只批准十一文件原子同步、独立官方 PyPI acquisition 例外及其完成后的本地离线应用启动采用；startup 阶段严格 zero-socket，不批准 Provider、数据库、Redis/Broker、真实环境、部署或 production 放行。
```

有效 `APPROVED` 的 `selected_decisions` 必须恰为六项且顺序一致，`rejected_decisions=[]`。九角色必须绑定同一 R5 snapshot、R3/R4 identity、artifact manifest、dependency lock 和十一文件 pre state。网络权限只由两个 phase-qualified scope 与 `startup_socket_attempts_required=0` 表达，不得补回 flat `network_scope`。任何角色拒绝/缺失、修改既有 lock、允许 unbounded/retried acquisition、remote/redirected drive root、startup socket 或真实环境/secret/Provider/DB/部署/production，或备注与 `forbidden_scope` 冲突时，整体保持 `NOT APPROVED`。

这是一项 active-baseline scope successor，不能用普通实现备注或依赖下载批准代替九角色 CR 审批。R5 获批也只授权 Gate B 与随后 Gate C；不得追认批准前发生的代码、同步、网络或运行事实。

---

## 7. 失败、回滚与证据边界

### 7.1 失败关闭顺序

应用启动固定按以下先后失败：

```text
Settings parse/type/required/legacy safety
-> APP_ENV production authorization gate
-> AI_POLICY_FILE pure lexical local-path gate (failure: filesystem I/O attempts 0)
-> drive_root_locality (DRIVE_FIXED plus local physical-volume target)
-> package resource exact set/name/size/raw identity
-> external Policy component non-reparse/regular-file and pre-open identity
-> bounded no-follow read/size and post-read identity (calculate raw hash only)
-> POL-VAL-001
-> POL-VAL-002
-> POL-VAL-003
-> POL-VAL-004 (Draft 2020-12 Schema)
-> POL-VAL-005
-> POL-VAL-006 (JCS/self-hash; exactly once)
-> POL-VAL-007
-> POL-VAL-008
-> POL-VAL-009
-> POL-VAL-010
-> POL-VAL-011
-> POL-VAL-012 (accept)
-> approved raw identity/policy hash pin
-> Settings/Policy cross-binding
-> immutable adoption
-> FastAPI application construction/exposure or Worker application construction
```

前序失败不得继续后序。startup 阶段不得尝试任何网络，也不得“容错”回退到旧 Pydantic pre-hash model、默认 Policy、环境变量拼装 Policy、最后一次成功缓存或空 Policy。`approval_identity_pin` 不得在 `POL-VAL-012(accept)` 前执行；`POL-VAL-006` 必须且只能执行一次，approval pin 只复用其已验证结果，不得二次 canonicalize/hash。不存在可采用 Policy 时，Backend/Worker 必须停止启动。

### 7.2 回滚

- 十一文件同步失败：回滚全部十一文件，不进入实现。
- dependency promotion 或 Gate C 失败：保留已批准/同步合同但 `BASE-004` 继续 `partial`；回滚未通过的 runtime 变更，不回退 R3/R4 artifacts。
- loader 运行失败：进程启动失败，不打开 Provider/DB/Redis/Broker，不切换到 legacy 配置。
- R5 不定义 production rollback，因为 production 从未获准启动。

### 7.3 证据用语

允许的成功表述仅为：

`CR-011-R5 local offline application-startup Policy adoption PASS; provider calls disabled; zero-socket startup evidence.`

禁止把结果表述为 Provider available、AI runtime complete、durable、restart-safe、business-ready、Compose-ready、production-ready、AC passed 或 P0 complete。依赖安装 PASS 也不得替代 startup tests；startup skeleton PASS 不得替代业务健康或完整服务链。

---

## 8. R5 decision snapshot 算法与生命周期

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次；不得用普通 substring search 命中正文代码或反引号中的相同文本。
4. decision preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256，小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定 §1 的 R3/R4 base、§2.1 dependency lock、§5.1 十一文件 pre identities、§6 approval schema 和 §3 非授权边界。
7. 第 1～8 节不得包含 R5 自身 decision snapshot hash 值、任何九份 Request post identity、manifest post identity 或 re-pin 文件 post identity；这些值只允许进入 §9 动态状态或外部 tracking，因此 snapshot 无自引用。
8. 在首条有效 approval record、Gate B sync authorization 或下游消费事实产生前，第 1～8 节可在 review 阶段修订；每次修订必须废弃旧 unsigned hash、重算并全量复审。
9. 任一有效 approval 或下游消费事实产生后，第 1～8 节任何 byte 变化必须提升至少 `CR-011-R6` 并重置九角色审批；不得原地修复已签 R5。
10. 第 9 节动态状态更新不改变 decision snapshot；不得把动态 evidence 反向解释为规范条款。
11. 生成 snapshot 只建立可签署对象，不等于批准。有效九角色审批前不得同步十一文件；Gate B PASS 前不得实施 Gate C。

---

## 9. 当前状态

本节位于 decision snapshot 之外，只记录动态生命周期与证据；不得覆盖第 1～8 节。

| 项目 | 状态 |
|---|---|
| CR revision | `CR-011-R5` |
| lifecycle | `APPROVED / ACTIVE CONTRACT / GATE B PASS / GATE C BLOCKED` |
| R3 exact contract | `BOUND；26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` |
| R3 artifact manifest | `BOUND；5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` |
| R4 active base | `BOUND；27384/cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` |
| `AI-D-009`～`AI-D-014` semantic/artifact delta | `ZERO` |
| exact Python closure | `INDEPENDENT VERIFIED；641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c；LOCAL RUNTIME PROMOTION IMPLEMENTED / GATE C ACCEPTANCE BLOCKED` |
| eleven pre identities | `11/11 INDEPENDENT MATCH BEFORE GATE B` |
| R5 decision preimage / snapshot | `50926/fb6aa225dae67a6068e84935e4a77affe84b143de5de2908b555089f9334c5ae；APPROVED SNAPSHOT` |
| required approvals | `9/9；VALID；2026-08-10；single BOSS record covers all nine roles` |
| R5 Gate A | `PASS；TWO INDEPENDENT FINAL REVIEWS；REVIEW EXECUTION: NO NETWORK / NO WRITE` |
| R5 Gate B eleven-file sync | `PASS；11/11 ATOMIC BASELINE SYNC；verify-baseline PASS；test-assets positive/negative PASS；approval_pre_meta 21 PASS + CLI STATIC PASS` |
| R5 Gate B post identities | `SRS=129763/96ea16772efbdd23d72482a296fbf51befe562fca1bfd39d33e1e9d336538a11；Architecture=91332/62274fe303c4291483c7287e1dfd93a9f80c7eb4a70df386736d0314dd057805；Database=116243/7d30cba02cb8a66c13a797e685da0012d894beb9d1644254563519f6c6af24f8；API=328584/5412bbe64dcf9ed40c566ab51963a2b1d61644936aeb8e54f231998caf4652c8；Page=83876/6df77a47fa0a48ec76c366b4a43a9fb4b444ceb993b0eb35a619144b34a4493a；AI=52141/83741903459debffe952e532a0b564138110edbe734d7e303d2358eddc450b28；Test=50860/b073429523b96bf2562df6543245a60e74e5ecb976b8e3adb6769e74f06fd4db；Deploy=55131/3d559185005f9e8798ded422bb25dafa343ddd023637ec8e07330a8a0119e27b；Plan=107268/48e413d360eb82332a035d4fdbb604a218137f9339dce0706d734eeea9eb8dfa；manifest=1661/aa1918af6d47eb5f67d68dd84a7389f0f252c2b2a296ca06ba15547e0eb30b34；approval_pre_meta.py=22193/cf7d0f5dfe82ccb9c3ceebe914ce341be7c77a8c45f464f69933061aa7988cc6` |
| R5 Gate C local offline startup adoption | `RUN / BLOCKED_NATIVE_WINSOCK_NAMED_PIPE_EVIDENCE；a pre-freeze functionally equivalent candidate completed all offline sub-gates and exited 4；the current stable runner passed focused preflight、65/65 exact collection/execution and anti-forgery 13/13 but was not rerun end-to-end after non-semantic reason/format-only changes；native OS WinSock and Windows named-pipe attempts remain NOT_CLAIMED；no Gate C PASS` |
| R4 persistent AI-005/runtime Gate C | `PENDING / NOT AUTHORIZED` |
| Provider / DB / Redis / Broker / real env / deploy / production | `NOT AUTHORIZED / NOT RUN` |
| commit / push / PR | `NOT AUTHORIZED / NOT RUN` |
