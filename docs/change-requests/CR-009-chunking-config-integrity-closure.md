# CR-009-R1：分块配置版本、哈希与归档完整性闭合

合同修订：`CR-009-R1`；权威生命周期状态仅见第 10 节。

日期：2026-08-07

对应差异：GAP-054

## 1. 变更原因

CR-001-R2 的 D-009 已批准以下边界：BASE-005 只创建 chunking_configs 表和约束，不写组织级配置；首组织 bootstrap 完成后，由 KB-004 工作包通过 CHUNK-001/CHUNK-002 创建并发布首个组织级配置；首版参数固定为 markdown_ast_structural/700/1200/50/100，并采用完整标题路径、表格整体保留/拆分重复表头和只排除已批准噪声的策略。

九份 Request 已同步上述边界，但仍不能唯一生成 PostgreSQL 16 DDL、状态触发器或 config_hash：

1. 数据库把 chunking_configs 声明为 I1 不可变版本表，同时给出 draft/published/archived、I1 archived_at 和“发布后不可覆盖”，却没有说明 published -> archived 是否属于允许的生命周期更新。
2. CHUNK-001 响应包含 row_version，数据库 I1 模板和 chunking_configs 字段表却没有 row_version；CHUNK-002 也不接收预期版本。
3. config_hash 没有版本化 Schema、字段投影、JCS bytes 或测试向量；直接对 JSONB 文本、请求原文或整行计算会产生不同事实。
4. draft 是否可编辑、可改哪些字段、如何分配 version、相同 hash 并发创建如何返回，均未冻结。
5. archived 没有可达 API；让 DBA 或内部代码直接改状态会绕过权限、幂等、reason 和 operation log。
6. “由 KB-004 创建并发布”中的 KB-004 是开发工作包；API 中同名 KB-004 是修改 knowledge_bases 的 PATCH，不能据此推导它可以代替 CHUNK-001/CHUNK-002。

GAP-054 关闭前，BASE-005 不得创建 chunking_configs migration；文档中的 API 示例不能作为隐式 Schema、哈希或状态机。

## 2. 九份 Request 交叉核对结论

| 事实来源 | 已明确事实 | 仍缺少的唯一合同 |
|---|---|---|
| 需求规格 | 首版参数固定；发布后配置不可覆盖；变化创建新版本；无已发布配置时 fail closed；配置由版本化数据库记录管理 | archive 是否是不可变例外、归档入口、hash 投影、draft 可变范围 |
| 系统架构 | 分块配置属于制度知识库域；分块前要求配置已发布；BASE-005 不写组织配置；启动后由 KB-004 发布 | 发布/归档并发、已受理 Job 遇到随后归档的处理 |
| 数据库设计 | 现有字段、draft/published/archived、I1、两项唯一约束、BASE-005 空表 | row_version、archive actor/reason、字段一致性、触发器和精确 hash |
| API 设计 | CHUNK-001 创建、CHUNK-002 发布，均仅 system_admin 且要求 Idempotency-Key；CHUNK-003 显式提交 chunking_config_id | CHUNK-001 的 row_version 落表、发布/归档 CAS、配置读取入口、状态冲突语义 |
| 页面与交互 | UI-009 中 system_admin 可创建/发布配置 | 可重载的配置列表、archive 操作、终态展示和按钮门禁 |
| AI/RAG 设计 | 首版五项参数和三个处理策略；无隐式默认；变化后重新分块、建索引和评测 | 处理对象的封闭 Schema、JCS/hash 版本 |
| 测试与验收 | BASE-005 后表为空；配置变化触发 AI 回归；需验证长度、重叠和分块质量 | 固定 hash 向量、并发、状态触发器、归档和 downgrade 用例 |
| 部署与运维 | 禁止 CHUNK_* 环境变量充当组织默认；迁移不写配置；KB-004 独立发布 | 非空 downgrade 门禁、升级已有未知行的失败策略 |
| 开发任务计划 | KB-004 工作包拥有 CHUNK-001/CHUNK-002、chunking_configs 和 operation_logs | 工作包与同名 API 的边界、归档接口是否增加到基线 |

## 3. 推荐合同

本节给出一个内部闭合、可直接实现和测试的最小推荐方案。它在获批并同步 Request 前不生效。

### 3.1 对象分类与精确字段

chunking_configs 保持 **I1 不可变版本表**，不改为 M1，不使用 deleted_at/deleted_by/delete_reason，也不允许软删除或物理删除。I1 只表示业务内容不可覆盖；第 3.4 节列出的受控生命周期转换是唯一 UPDATE 例外。

建议物理列固定为：

| 字段 | PostgreSQL 16 合同 |
|---|---|
| id | UUID PRIMARY KEY DEFAULT gen_random_uuid() |
| organization_id | UUID NOT NULL，FK organizations(id)，ON DELETE RESTRICT |
| name | VARCHAR(150) COLLATE "C" NOT NULL |
| version | INTEGER NOT NULL，CHECK version > 0 |
| config_schema_version | VARCHAR(50) NOT NULL，当前只允许 chunking-config-v1 |
| strategy | VARCHAR(50) NOT NULL，当前只允许 markdown_ast_structural |
| target_length | INTEGER NOT NULL |
| max_length | INTEGER NOT NULL |
| min_length | INTEGER NOT NULL |
| overlap_length | INTEGER NOT NULL |
| title_handling_json | JSONB NOT NULL |
| table_handling_json | JSONB NOT NULL |
| noise_handling_json | JSONB NOT NULL |
| config_hash | CHAR(64) NOT NULL |
| status | VARCHAR(20) NOT NULL DEFAULT draft，CHECK 为 draft/published/archived |
| publish_reason | TEXT NULL |
| published_at | TIMESTAMPTZ NULL |
| published_by | UUID NULL，FK users(id)，ON DELETE RESTRICT |
| archive_reason | TEXT NULL |
| archived_at | TIMESTAMPTZ NULL；承接 I1 archived_at，不再重复建列 |
| archived_by | UUID NULL，FK users(id)，ON DELETE RESTRICT |
| row_version | BIGINT NOT NULL DEFAULT 1，CHECK row_version > 0 |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() |
| created_by | UUID NOT NULL，FK users(id)，ON DELETE RESTRICT |
| trace_id | UUID NOT NULL；表示 CHUNK-001 创建请求的 Trace ID |

本表不含 updated_at/updated_by。发布和归档的 actor/time/reason 分别由专用字段表达；对应动作 Trace ID 进入同事务 operation log。created_by、published_by、archived_by 必须与 organization_id 同组织，不能只靠普通 users(id) 外键。

名称必须满足 char_length(name) 为 1..150、name = btrim(name)；按 COLLATE "C" 的精确字符串参与版本序列和唯一约束，不做大小写折叠、Unicode 规范化或别名映射。

长度合同固定为：

~~~text
0 < min_length <= target_length <= max_length <= 2147483647
0 <= overlap_length < max_length
~~~

上述关系保持 API 现有“重叠小于最大长度”口径，不把 overlap 擅自收紧为小于 min_length。首个组织配置仍必须精确为 50/700/1200/100；后续数值变化必须创建新版本，并按现行要求重新分块、建候选索引和评测，不能原地更新。

三个 JSONB 字段在 chunking-config-v1 中使用封闭对象，拒绝缺字段、额外字段、NULL、字符串布尔或其他类型：

~~~json
{
  "title_handling": {
    "inherit_title_path": true
  },
  "table_handling": {
    "keep_whole_if_under_max": true,
    "repeat_header_on_split": true
  },
  "noise_handling": {
    "exclude_approved_noise": true
  }
}
~~~

exclude_approved_noise=true 只授权读取已经存在且 review_status=approved 的 document_content_exclusions；它不允许把任意字符串、正则表达式、脚本、Prompt 或代码塞入配置。改变上述对象形状或布尔语义必须提升 config_schema_version 并走新 CR。

### 3.2 config_hash 的唯一事实

config_hash 由服务端从经过严格类型校验的字段重建；客户端不能提交或覆盖。哈希输入只包含会改变分块语义的字段：

~~~json
{
  "schema_version": "chunking-config-v1",
  "strategy": "markdown_ast_structural",
  "target_length": 700,
  "max_length": 1200,
  "min_length": 50,
  "overlap_length": 100,
  "title_handling": {
    "inherit_title_path": true
  },
  "table_handling": {
    "keep_whole_if_under_max": true,
    "repeat_header_on_split": true
  },
  "noise_handling": {
    "exclude_approved_noise": true
  }
}
~~~

id、organization_id、name、version、status、row_version、创建/发布/归档字段和 trace_id 不进入哈希。organization_id 由 UNIQUE(organization_id, config_hash) 提供作用域；name/version 是人类可读版本身份，不应使相同语义得到不同 hash。

算法固定为 RFC 8785 JCS，对 UTF-8 bytes 执行 SHA-256，输出 64 位小写十六进制。禁止对请求原文、jsonb::text、带缩进 JSON、数据库整行或语言默认 map 顺序计算。

首版固定测试向量的 JCS bytes 为 325 字节：

~~~json
{"max_length":1200,"min_length":50,"noise_handling":{"exclude_approved_noise":true},"overlap_length":100,"schema_version":"chunking-config-v1","strategy":"markdown_ast_structural","table_handling":{"keep_whole_if_under_max":true,"repeat_header_on_split":true},"target_length":700,"title_handling":{"inherit_title_path":true}}
~~~

对应 SHA-256：

~~~text
aa49a319efa82ad1c6cc90fb5708e85fa692454d8854cad3f4ae0db90d2c9ae8
~~~

数据库必须使用同一投影独立重算并校验 config_hash，至少满足：

- config_hash 匹配正则 ^[0-9a-f]{64}$。
- INSERT 时传入 hash 与数据库重算值不一致则失败。
- 函数只接受本版本的严格 INTEGER/BOOLEAN/ASCII 常量，不依赖 jsonb 文本排序。
- 未知 config_schema_version fail closed，不以 v1 解释。

应用 JCS 实现、数据库重算函数和固定向量三者任一不一致都属于启动/迁移门禁失败。

### 3.3 版本分配、唯一性与创建幂等

保留并精确化两个唯一约束：

~~~text
UNIQUE (organization_id, name, version)
UNIQUE (organization_id, config_hash)
~~~

CHUNK-001 不接收 version。服务端按同一 organization_id/name 分配 COALESCE(MAX(version), 0) + 1，并在 PostgreSQL 16 事务内先取得：

~~~sql
pg_advisory_xact_lock(
  hashtextextended(
    'chunking_config_version' || chr(31) ||
    organization_id::text || chr(31) || name,
    0
  )
)
~~~

该锁只负责串行化版本分配；唯一约束仍是最终裁决者。hashtextextended 碰撞最多造成额外串行，不改变正确性。

CHUNK-001 的幂等语义固定为：

1. 相同 organization、actor、Idempotency-Key 和规范化请求 hash 重放，返回首次保存的 201 响应，不新增 row、version 或 operation log。
2. 相同 Idempotency-Key 对应不同请求，返回现有 409 IDEMPOTENCY_CONFLICT。
3. 不同 Idempotency-Key 但得到相同 organization_id/config_hash，返回 409 CHUNKING_CONFIG_ALREADY_EXISTS；不得返回另一个 name/version 的伪成功。
4. 并发相同语义请求只能有一个 INSERT 成功；其余按上述幂等键或 config_hash 唯一结果收敛。

同组织可以同时存在多个 published 配置；本合同不创造 active/default 指针，也不自动归档旧 published 配置。CHUNK-003 必须继续显式提交一个同组织 published chunking_config_id。

“首版固定”以**同组织第一次成功发布**为裁决点：若该组织不存在 published_at 非 NULL 的当前或历史行（包括后来从 published 归档的行），CHUNK-002 只允许发布第 3.2 节固定 hash。发布事务必须先取得以 organization_id 为作用域的 first-publish advisory lock，再在锁内重查历史；两个不同 draft 并发争夺首发时，最多一个能按固定向量发布。仅创建或归档未发布 draft 不消耗首发资格。

### 3.4 不可变白名单与状态机

业务内容在 INSERT 后始终不可修改，包括 organization_id、name、version、config_schema_version、strategy、四个长度、三个 JSON、config_hash、created_at、created_by 和 trace_id。

本合同不增加 draft PATCH。所谓“draft 更新白名单”固定为空：草稿内容有误时，先归档该 draft，再用 CHUNK-001 创建下一 version。唯一允许的 UPDATE 是以下三条状态边：

~~~text
draft     -> published
draft     -> archived
published -> archived
~~~

archived 是终态；禁止 archived -> draft/published、published -> draft、DELETE、TRUNCATE 和 no-op UPDATE。

每条边允许修改的列固定为：

| 状态边 | 唯一允许变化 |
|---|---|
| draft -> published | status、publish_reason、published_at、published_by、row_version |
| draft -> archived | status、archive_reason、archived_at、archived_by、row_version |
| published -> archived | status、archive_reason、archived_at、archived_by、row_version；原 publish_* 必须逐字节保持 |

所有转换必须满足 row_version = OLD.row_version + 1；时间由数据库 transaction_timestamp() 生成，actor 由认证上下文生成，客户端只能提交 expected row_version 和 reason。reason 必须原样保存，同时要求 reason = btrim(reason) 且 char_length(reason) 为 1..2000。

行状态一致性固定为：

| status | publish_* | archive_* |
|---|---|---|
| draft | 全部 NULL | 全部 NULL |
| published | reason/at/by 全部非 NULL | 全部 NULL |
| archived（来自 draft） | 全部 NULL | reason/at/by 全部非 NULL |
| archived（来自 published） | reason/at/by 全部非 NULL并保持原值 | reason/at/by 全部非 NULL |

因此，“发布后不可覆盖”应在 Request 同步时精确改写为：“发布后业务内容和发布证据不可修改；唯一允许的后续 UPDATE 是受控 published -> archived，它只写 archive_*、status 和 row_version。”

### 3.5 CHUNK-001、CHUNK-002、归档与读取接口

CHUNK-001 保持 POST /api/v1/chunking-configs、201、Idempotency-Key 必填和 system_admin。响应中的 row_version 保留，并由第 3.1 节新增物理列承载；同时返回 config_schema_version。

CHUNK-001/002/008 复用现有 `UNIQUE(organization_id,user_id,idempotency_key)`，不新增 endpoint 维度的第二唯一键。完成认证、同组织权限检查、请求 Schema 校验和规范化后，权威请求 hash 固定为 `SHA-256(UTF8(JCS(chunking-config-idempotency-v1)))`。Envelope 只允许且始终包含 `api_id/body/method/path/schema` 五键：`schema='chunking-config-idempotency-v1'`、`method='POST'`；`api_id` 为 CHUNK-001/002/008 之一；CHUNK-001 的 `path={}`，Body 精确为 `name/strategy/target_length/max_length/min_length/overlap_length/title_handling/table_handling/noise_handling`；CHUNK-002/008 的 `path` 精确为单键规范小写 UUID `config_id`，Body 精确为 `reason/row_version`。禁止加入 organization/user/key、trace/timestamp 或当前状态。三个固定 UTF-8 JCS 向量分别为：

```text
CHUNK-001 bytes=402 sha256=fbeb0825c66f123a94ae7a6a2f9c6b6d63d32502a327b2573a00921dc65113d2
{"api_id":"CHUNK-001","body":{"max_length":1200,"min_length":50,"name":"default","noise_handling":{"exclude_approved_noise":true},"overlap_length":100,"strategy":"markdown_ast_structural","table_handling":{"keep_whole_if_under_max":true,"repeat_header_on_split":true},"target_length":700,"title_handling":{"inherit_title_path":true}},"method":"POST","path":{},"schema":"chunking-config-idempotency-v1"}
CHUNK-002 bytes=213 sha256=62ed55c3b1f386028eeafc8e748bcdd9356e1bcc1a45802bc16ed235f3ce5cbb
{"api_id":"CHUNK-002","body":{"reason":"通过固定制度样本结构测试","row_version":1},"method":"POST","path":{"config_id":"52200000-0000-0000-0000-000000000001"},"schema":"chunking-config-idempotency-v1"}
CHUNK-008 bytes=204 sha256=9bedf31f8d1cb931854458d5f76261d6bb106d844cd1af2dfb8c81477872d6cb
{"api_id":"CHUNK-008","body":{"reason":"配置已由新版本替代","row_version":2},"method":"POST","path":{"config_id":"52200000-0000-0000-0000-000000000001"},"schema":"chunking-config-idempotency-v1"}
```

解析器必须拒绝 envelope/body/path 的额外键、缺键、重复键、非规范 UUID、非整数 `row_version` 或未先执行本节业务规范化的输入；不得把 JSON 数组、拼接字符串或 HTTP 原文当作同一请求 hash 的替代 preimage。

因此同一键跨 endpoint、方法、目标 ID 或 Body 复用必然得到不同 hash 并返回 `409 IDEMPOTENCY_CONFLICT`，不得泄漏为数据库唯一冲突。已有同 hash 完成记录必须在任何可变资源状态/版本门禁前返回首次完整响应；进行中记录按唯一行串行等待首次事务提交或回滚后重判；只有首次保留的新键可继续业务检查。首次成功的配置事实、幂等完整响应和 CR-008 注册的唯一 operation log 必须同事务提交；重放不新增日志、配置或版本。

CHUNK-002 保持 POST /api/v1/chunking-configs/{config_id}/publish，但请求体改为：

~~~json
{
  "row_version": 1,
  "reason": "通过固定制度样本结构测试"
}
~~~

发布使用单条 CAS UPDATE，谓词精确包含 `id/organization_id/status='draft'/row_version`。成功响应返回 `id/status='published'/published_at/row_version`。CAS 影响零行时在同一事务重查并固定优先级：同组织不可见或不存在为 404 `RESOURCE_NOT_FOUND`；状态非 draft 为 409 `CHUNKING_CONFIG_STATE_CONFLICT`；仍为 draft 但版本不同为 409 `RESOURCE_VERSION_CONFLICT`。相同 Idempotency-Key/同请求重放返回首次响应，即使配置后来已 archived；新键对非 draft 行按上述优先级失败，不写业务日志或递增版本。

首次发布还必须执行第 3.3 节的组织级锁与固定 hash 检查；该检查和 CAS、operation log、idempotency_records 必须在同一事务内提交。

为使 archived 在 P0 可达且不绕过审计，本 CR 推荐新增唯一最小接口：

| 项目 | 推荐合同 |
|---|---|
| 接口编号 | CHUNK-008 |
| 方法与 URL | POST /api/v1/chunking-configs/{config_id}/archive |
| Header | Idempotency-Key 必填 |
| Body | row_version integer 必填；reason string 必填 |
| 角色 | 同组织有效 system_admin |
| 成功 | 200，返回 id/status=archived/archived_at/row_version |
| 状态边 | draft/published -> archived |
| 失败 | 404 RESOURCE_NOT_FOUND；409 RESOURCE_VERSION_CONFLICT；409 CHUNKING_CONFIG_STATE_CONFLICT |

CHUNK-008 使用单条 CAS `UPDATE public.chunking_configs ... WHERE id=? AND organization_id=? AND status IN ('draft','published') AND row_version=?`。CAS 影响零行时按“不可见/不存在 404 → 已 archived 或其他非法源状态 `CHUNKING_CONFIG_STATE_CONFLICT` → 合法源状态但版本不同 `RESOURCE_VERSION_CONFLICT`”重查裁决。相同键/hash 在归档后仍重放首次 200；新键请求已 archived 行不是重放，只能返回状态冲突。两个不同键携带相同旧版本并发时最多一个提交，败者不递增版本、不写第二条业务日志或成功幂等结果。

为使 UI-009 在页面刷新后能够发现 draft/published/archived 配置并取得发布/归档所需 `config_id/row_version`，本 CR 同时新增一个只读入口；它用单个完整列表响应代替另增详情接口：

| 项目 | 推荐合同 |
|---|---|
| 接口编号 | CHUNK-009 |
| 方法与 URL | GET /api/v1/chunking-configs |
| Query | `status` 可选且只允许 draft/published/archived；`page_size` 默认 20、范围 1..100；`cursor` 可选 |
| 角色/租户 | 仅有效 system_admin；organization_id 只从认证主体派生，不接受客户端组织参数；每页重新鉴权并强制同组织 |
| 排序 | `(created_at DESC,id DESC)`；首屏冻结最大可见 upper tuple，后续使用严格 `< after tuple` 的 keyset |
| 成功 | 200；`items` 每项完整返回第 3.1 节全部字段；`pagination` 精确为 `page_size/next_cursor/has_more`；`has_more=true` 当且仅当 next_cursor 非空，false 当且仅当为 null；空集合返回空数组 |
| 失败 | 无效/过期/篡改 cursor 为 400 `CURSOR_INVALID`；无效状态或 page_size 为 422；认证/角色失败沿用全局 401/403，不接受可探测其他组织的资源 ID |

CHUNK-009 cursor 使用 `base64url(payload_jcs_bytes) + '.' + base64url(HMAC-SHA256(key[kid],payload_jcs_bytes))`，两段无 padding。Payload 是封闭 JCS 对象，全部值均为 JSON string，精确包含：`v='chunking-config-cursor-v1'`、匹配 `^[A-Za-z0-9._-]{1,64}$` 的 `kid`、UTC 六位微秒且以 `Z` 结尾的 RFC 3339 `issued_at/expires_at/upper_created_at/after_created_at`、规范小写 UUID `upper_id/after_id`、小写 64 位 `filters_hash`；next_cursor 存在时 upper/after 四项都非空，TTL 固定 30 分钟。原始 cursor 最长 4096 个 ASCII 字符、解码 payload 最长 2048 bytes，签名段解码后必须恰好 32 bytes，并使用 constant-time 比较；超长/字段/类型/base64/JCS/签名/时间/kid 错误在查询或读取任何配置行前返回 `CURSOR_INVALID`。

`filters_hash` 对封闭全键对象 `schema='chunking-config-filters-v1'/requester_user_id/organization_id/effective_role_codes/data_scope_version/status` 做 JCS + SHA-256；requester/organization 是规范小写 UUID string，角色是去重后按 Unicode code point 升序的非空 string 数组，data_scope_version 是 1..128 位服务端授权事实 string，status 是三个枚举 string 或未提供时的 JSON null。Cursor 不返回或记录密钥，每页先重新认证/授权：主体已经不再是有效 system_admin 时返回全局 403；仍有权但 requester、organization、角色集合、data scope 或 status 变化时返回 409 `CURSOR_SCOPE_CHANGED`。密钥来自受限 secret 配置，新签发只用 active key，previous key 至少保留 30 分钟；本合同不记录 secret 值。

CHUNK-009 是 live read，不持有跨请求 MVCC snapshot。冻结 upper tuple 与 keyset 可防止并发新建导致身份重复/翻页漂移，但 status、row_version、publish/archive 字段可在页间合法变化；使用 status filter 时，一条配置可能因并发状态转换在本次遍历中出现或遗漏。接口不声称 point-in-time 完整性，UI 在发布/归档后必须从首屏刷新；需要审计快照时使用后续专用导出合同，不能把该管理列表当证据清单。CHUNK-009 不写成功 operation log，也不进入 CR-008 的敏感 GET allowlist。

若 CHUNK-008/009 获批，本 CR 固有 `api_delta=+2`，锚定 2026-08-07 已同步 CR-001-R2/CR-002-R4 后的 122 API 基线和 `docs/baseline-manifest.md` SHA-256 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`。只应用本 CR 时为 124 API、74 个非 GET、50 个 GET；真正最终 P0 总数必须以同步时的有效基线加所有已获批 CR delta 机械累加，禁止与 CR-005 或其他 CR 各自硬编码最终总数。同步范围包含 API 清单、UI-009、测试矩阵和开发计划。若不接受增加归档接口，替代决策必须是从 P0 Schema 删除 archived 状态并强制 archived_at 永远为 NULL；不得保留一个只能由 DBA 或未登记内部调用到达的 archived。若不接受 CHUNK-009，则 UI-009 必须同步删除配置恢复/浏览/发布/归档能力；不得保留无法从 API 重载的管理页面。

### 3.6 CHUNK-003 与归档并发

新分块构建只接受同组织且 status='published' 的配置。CHUNK-003 在同一事务中锁定配置行、验证状态和 hash，然后把 config_id/config_schema_version/config_hash 冻结进 Job 输入并创建 Job/Outbox。

与归档并发时采用可串行解释：

1. archive 先锁定并提交：随后 CHUNK-003 失败为 CHUNKING_CONFIG_STATE_CONFLICT，不创建 Job。
2. CHUNK-003 先锁定并提交：Job 已合法受理；随后 archive 可以成功。Worker 允许为该已受理 Job 读取不可变 archived 行，但必须验证冻结的 id/schema/hash 完全一致。
3. archived 配置不能被任何新 CHUNK-003 请求使用；既有 document_chunk_sets、历史 Job、评测、索引和引用不被改写。

具体 Job/Outbox 原子提交、input_schema_version 和 lease 行为仍依赖获批的 CR-004；本 CR 不重复定义它们。

### 3.7 权限、职责和 KB-004 所有权

- CHUNK-001、CHUNK-002、CHUNK-008、CHUNK-009 仅允许当前认证 organization 内的有效 system_admin。认证时间使用数据库事务时间；用户、角色和分配必须有效，跨组织或无效角色一律 fail closed；CHUNK-009 不接受客户端 organization_id。
- 若角色来自 break-glass，必须满足最终获批的 AUTH/CR-003 双人控制和有效期合同；在该合同未批准前，不得凭本 CR 自行实现临时 system_admin。
- 创建、发布和归档是技术配置动作，不授予制度业务审批、索引批准或检索评测审批能力。
- 写 API/Service 必须在同一事务写配置状态、idempotency_records 和第 8 节要求的对应 operation log；CHUNK-009 只读且不写成功访问日志。
- 数据库应用角色不得 DELETE/TRUNCATE，也不得绕过状态触发器直接覆盖内容或 actor。

“KB-004 owner”固定解释为开发计划中的 **KB-004 工作包**拥有 chunking_configs、CHUNK-001、CHUNK-002 和获批后的 CHUNK-008/009 实现。API 编号 KB-004 只 PATCH knowledge_bases 的已批准 changes 白名单，不得创建、读取、发布、归档或选择分块配置。

BASE-005 只创建空表、约束、hash 函数和不可变/状态触发器。迁移、bootstrap、应用启动、环境变量和只读配置文件都不得写首个配置。首管理员完成 bootstrap 和强制换密后，才由显式 system_admin 会话调用 CHUNK-001/CHUNK-002。

## 4. 不采用的方案

1. **把 chunking_configs 改成 M1。** 会引入软删除和任意 row_version 更新，与版本化不可变事实冲突。
2. **保留 archived 但不给 API。** 只能靠 DBA、迁移或私有调用改状态，无法证明权限、reason、幂等和审计。
3. **发布新版本时自动归档所有旧 published。** Request 没有默认/活动配置指针，CHUNK-003 又显式选择 config_id；自动归档会无依据地改变旧配置的新建可用性。
4. **允许 draft 原地编辑。** 当前没有 PATCH 接口或字段白名单；这会使版本/hash/幂等和审计不可验证。
5. **从 API 示例直接序列化哈希。** 示例不是 Schema，map 顺序和 JSONB 文本不是 RFC 8785 JCS。
6. **把 name/version/status/actor 加入 config_hash。** 会让相同分块语义产生不同 hash，破坏 organization_id/config_hash 唯一的设计意图。
7. **让 KB-004 PATCH 顺带创建配置。** 同名接口与工作包混淆，并绕过 CHUNK-001/CHUNK-002 的幂等和权限合同。
8. **在 BASE-005、bootstrap、代码或 CHUNK_* 环境变量写首版配置。** 已被 CR-001-R2 D-009 明确排除。
9. **非空 downgrade 直接删除或 CASCADE。** 会破坏历史分块、索引、评测和审计引用。

## 5. 迁移与回滚合同

### 5.1 Revision ownership 与 Upgrade

本 CR 的 `core_table_delta=0`：`public.chunking_configs` 已在 57 张正式基线名称集合中。批准与生成 migration 时必须记录并校验实现前 Alembic head；该绑定 head 不得含 `public.chunking_configs` 或本 revision 的任一命名对象。预检通过后，单一 revision 才能作为该表完整 Schema 的唯一创建者，不允许先建弱表再增量修补；若预检不满足，CR-009-R1 不可签署或实施，必须重新评估并提升 revision。本 CR 不预占具体 Alembic revision 编号，由上述绑定 head 分配。

该 revision 只拥有下列命名对象，禁止生成未登记 helper：

| 类型 | 精确对象 |
|---|---|
| 表 | `public.chunking_configs` |
| PK/FK | `pk_chunking_configs`、`fk_chunking_configs_organization`、`fk_chunking_configs_created_by`、`fk_chunking_configs_published_by`、`fk_chunking_configs_archived_by` |
| CHECK | `ck_chunking_configs_name`、`ck_chunking_configs_version`、`ck_chunking_configs_schema`、`ck_chunking_configs_strategy`、`ck_chunking_configs_lengths`、`ck_chunking_configs_hash`、`ck_chunking_configs_status`、`ck_chunking_configs_reason_matrix`、`ck_chunking_configs_row_version` |
| UNIQUE | `uq_chunking_configs_org_name_version`、`uq_chunking_configs_org_hash` |
| 普通函数 | `public.compute_chunking_config_hash_v1(text,text,integer,integer,integer,integer,jsonb,jsonb,jsonb)` |
| trigger functions | `public.enforce_chunking_configs_insert_v1()`、`public.enforce_chunking_configs_update_v1()`、`public.validate_chunking_config_actors_v1()`、`public.reject_chunking_configs_delete_truncate_v1()` |
| triggers | `trg_chunking_configs_insert_v1`、`trg_chunking_configs_update_v1`、`trg_chunking_configs_actors_v1`、`trg_chunking_configs_delete_v1`、`trg_chunking_configs_truncate_v1` |

五个 trigger 的映射固定为：

| trigger | timing / event / level | function |
|---|---|---|
| `trg_chunking_configs_insert_v1` | BEFORE INSERT / FOR EACH ROW | `enforce_chunking_configs_insert_v1()` |
| `trg_chunking_configs_update_v1` | BEFORE UPDATE / FOR EACH ROW | `enforce_chunking_configs_update_v1()` |
| `trg_chunking_configs_actors_v1` | CONSTRAINT AFTER INSERT OR UPDATE / DEFERRABLE INITIALLY DEFERRED / FOR EACH ROW | `validate_chunking_config_actors_v1()` |
| `trg_chunking_configs_delete_v1` | BEFORE DELETE / FOR EACH ROW | `reject_chunking_configs_delete_truncate_v1()` |
| `trg_chunking_configs_truncate_v1` | BEFORE TRUNCATE / FOR EACH STATEMENT | `reject_chunking_configs_delete_truncate_v1()` |

`compute_chunking_config_hash_v1` 是 `IMMUTABLE STRICT SECURITY INVOKER`；四个 trigger function 也是 `SECURITY INVOKER`。全部函数归 `finaudit_migrator` 所有，固定 `SET search_path = pg_catalog, public, pg_temp`，函数体仍完全限定 relation/extension function/type，不使用动态 SQL、Session GUC、网络、文件或 secret。迁移对全部函数先 `REVOKE ALL ... FROM PUBLIC`；只向 `finaudit_app_rw` 授予普通 hash 函数的 EXECUTE，trigger function 不向登录角色授予直接 EXECUTE。

本 revision 不创建 sequence。表与五个函数的 owner 固定为 `finaudit_migrator`；PostgreSQL trigger 没有独立 owner，其控制权随所属表。表权限固定为：先对 `PUBLIC/finaudit_app_rw/finaudit_worker_rw/finaudit_readonly/finaudit_audit_ro` 执行精确 `REVOKE ALL`；再令 `finaudit_app_rw` 获得全表 SELECT，列级 INSERT 仅限 `organization_id/name/version/config_schema_version/strategy/target_length/max_length/min_length/overlap_length/title_handling_json/table_handling_json/noise_handling_json/config_hash/created_by/trace_id`，列级 UPDATE 仅限 `status/publish_reason/published_at/published_by/archive_reason/archived_at/archived_by/row_version`，不授予 DELETE/TRUNCATE；`finaudit_worker_rw` 只获全表 SELECT；`finaudit_readonly/finaudit_audit_ro` 无任何表权限，若未来要读必须另行批准数据范围。除 owner 外其他登录角色均不得取得未列明权限；`finaudit_migrator` 仅部署使用的 owner 权限不作为应用旁路。INSERT/UPDATE trigger 仍对默认值、状态边、数据库时间和 actor 做最终校验，列级 GRANT 不能替代状态机。

`created_by/published_by/archived_by` 保留普通 `users(id)` FK；同组织事实由命名的 deferred constraint trigger `trg_chunking_configs_actors_v1` 调用 `validate_chunking_config_actors_v1()` 校验。INSERT 必须证明 created actor 是同组织有效 system_admin；发布/归档转换只校验本次新增 actor 是同组织有效 system_admin，同时保持历史 actor 原值。这样不需要偷偷给 `users` 增加本 revision 不拥有的复合 UNIQUE，也不能只靠 Service 先查后写。

Upgrade 固定按“确认表、上述五个函数、五个 trigger 名均不存在 → 创建表及命名约束/UNIQUE → 创建普通函数和四个 trigger function → 创建五个 triggers → REVOKE/GRANT → catalog 验证空表与精确对象集合”的顺序执行。发现任一同名未知对象、扩展不满足或 catalog 集合多/少一项即失败，不自动收编未知 Schema。migration 完成后表必须为空；只要出现组织配置种子，BASE-005 验收立即失败。如果真实环境存在 legacy 表或未知行，必须另行盘点和签署前向迁移，不由本 revision 猜测 JCS、版本或状态。

### 5.2 Downgrade

1. 部署侧先停止 CHUNK 写入生产者；数据库 downgrade 在一个 PostgreSQL 16 事务开始时执行 `SET LOCAL lock_timeout='5s'`，再对 `public.chunking_configs` 取得 ACCESS EXCLUSIVE 锁。锁超时保持 SQLSTATE `55P03`，不得转成无界等待。
2. 锁后重新检查行数；非空时在任何 DDL 前以 SQLSTATE `55000` 原子失败，Schema、数据和 alembic_version 保持不变。已发布、已归档或被历史对象引用的配置只允许前向修复。
3. 后续 migration 若已建立 FK 或 consumer trigger，必须先按 Alembic 反向依赖顺序降级；仍存在依赖时本 downgrade 失败，不使用 CASCADE。
4. 空表时按精确反向顺序逐名 `DROP TRIGGER trg_chunking_configs_truncate_v1/delete_v1/actors_v1/update_v1/insert_v1 ON public.chunking_configs`，再无 `CASCADE` 地依次 `DROP FUNCTION public.reject_chunking_configs_delete_truncate_v1()`、`public.validate_chunking_config_actors_v1()`、`public.enforce_chunking_configs_update_v1()`、`public.enforce_chunking_configs_insert_v1()`、`public.compute_chunking_config_hash_v1(text,text,integer,integer,integer,integer,jsonb,jsonb,jsonb)`；函数必须先于其引用的 relation 删除。
5. 最后 `DROP TABLE public.chunking_configs`；表拥有的命名 PK/FK/CHECK/UNIQUE 随表删除，不把独立函数误称为随表删除。任一对象缺失、owner/signature 不符或存在未知依赖时整事务失败，不动态发现或删除其他对象。

## 6. PostgreSQL 16、并发与哈希验收

### 6.1 Schema 与空表

- 空库 upgrade 到 head 后精确存在第 3.1 节列、类型、NULL 语义及第 5.1 节逐名列出的表、约束、UNIQUE、五个函数和五个 triggers；catalog 不得出现额外 helper。
- BASE-005 后 SELECT count(*) FROM chunking_configs = 0；bootstrap 和应用启动后仍为 0，直到显式 CHUNK-001。
- 证明本表是 I1 加专用 row_version，而不是偷偷继承 M1 的 updated/deleted 字段。
- 插入、发布、归档分别覆盖同组织有效 actor、跨组织 actor、禁用/删除 actor 和普通 FK 存在但组织不匹配；deferred actor trigger 必须失败关闭，且不得给 `users` 留下本 revision 未登记的复合约束。

### 6.2 JCS/hash

- 使用第 3.2 节 325-byte 向量得到 aa49a319efa82ad1c6cc90fb5708e85fa692454d8854cad3f4ae0db90d2c9ae8。
- API 请求键顺序、空白和 JSON 格式不同但语义相同，得到相同 hash。
- 额外字段、缺字段、错误类型、未知 schema、错误大小写 hash、请求 hash 和数据库重算不一致全部 fail closed。
- name/version/status/publish/archive 变化不改变重算 hash；任何真正的语义字段变化必须改变 hash。

### 6.3 生命周期与不可变

- draft 业务字段、name/version/hash、创建证据的 UPDATE 全部被数据库拒绝。
- draft -> published、draft -> archived、published -> archived 逐字段精确通过；每次只递增一次 row_version。
- publish_*、archive_* 的 NULL/非 NULL 组合不合法时失败。
- published 内容或 publish_* 覆盖、archived 任意 UPDATE、DELETE、TRUNCATE 和 no-op UPDATE 全部失败。
- archived 配置不能受理新 CHUNK-003；历史集合和已受理 Job 仍可验证同一 id/schema/hash。

### 6.4 并发与幂等

- 同组织/name、不同 semantic hash 的并发 CHUNK-001 为已提交行分配互不重复且单调递增的 version；失败事务不产生配置行，不得产生重复或覆盖。
- CHUNK-001/002/008 对相同 Idempotency-Key/hash 并发只提交一次业务事实、一条业务 operation log 和一个完整幂等结果；对象状态后续变化时仍逐字重放首次响应。相同键跨 endpoint、method、path ID 或 Body 稳定返回 IDEMPOTENCY_CONFLICT。
- 不同键、相同 semantic hash 并发只有一行成功，其余返回 CHUNKING_CONFIG_ALREADY_EXISTS。
- 同一 draft 并发发布只有一个 CAS 改行；同一幂等请求重放返回首次响应，其他请求不重复写发布证据。
- CHUNK-008 覆盖同键同 hash、同键不同 hash、新键请求已 archived 行、两个不同键携带相同旧 row_version，以及 CAS 零行的 404→state→version 固定重查优先级；败者不写第二条业务日志、成功幂等结果或版本。
- 两个不同 draft 并发争夺组织首发时，只允许第 3.2 节固定 hash 成功；未发布 draft 的创建/归档不会绕过该门禁。
- CHUNK-003 与 archive 的两个锁顺序场景均符合第 3.6 节，不产生“已归档后新受理”或“合法旧 Job 无法重放”的中间态。
- CHUNK-009 覆盖首屏 upper tuple、同微秒多个 UUID、并发新增配置、最后一页、状态过滤、主体/组织/角色/过滤器变化、过期/篡改/错 kid/超长 cursor 和密钥轮换；无并发状态转换的 keyset 场景必须同组织且无重复/漏项。并发发布/归档且使用 status 过滤时按第 3.5 节允许项目出现或遗漏，但不得跨组织、不得把管理列表称为审计快照，UI 完成写操作后必须从首屏重载；普通成功读取不写 operation log。

### 6.5 权限与回滚

- 覆盖普通/过期/撤销/禁用 system_admin、跨组织、无角色、未批准 break-glass 和 direct SQL 越权。
- 非空 downgrade 在锁后以 SQLSTATE 55000 原子失败，锁超时为 55P03，行和 head 保持；空表 upgrade/downgrade/upgrade 往返按第 5.1 节 catalog allowlist 证明不遗留表、trigger 或独立函数。
- 用两个连接证明 downgrade 锁与并发 CHUNK-001/发布/归档不存在检查后插入或更新的 TOCTOU。

上述检查通过只证明合同实现和离线 PostgreSQL 16 行为，不等于 KB-004 工作包、AC-008、fixed_test_provider、真实 Provider、production 或整套 P0 已通过。

## 7. 批准后同步范围

若批准本推荐，必须在实现前同步九份 Request：

| 文档 | 必须同步 |
|---|---|
| 需求规格 | 不可变的精确 archive 例外、无 default/active 指针、CHUNK-008/009、`api_delta=+2` 与按有效 CR 累加后的 API 总数 |
| 系统架构 | 生命周期状态机、CHUNK-003/归档锁与已受理 Job 的冻结语义、KB-004 工作包边界 |
| 数据库设计 | 第 3.1～3.4 节列、命名约束/UNIQUE、hash、actor/生命周期触发器、I1 + row_version 与精确 revision ownership |
| API 设计 | CHUNK-001/002/008 幂等与 CAS、CHUNK-009 完整列表/cursor、错误优先级；明确 KB-004 PATCH 不管理配置 |
| 页面与交互 | 从 CHUNK-009 可重载 draft/published/archived、system_admin 发布/归档按钮及禁用原因 |
| AI/RAG 设计 | chunking-config-v1 封闭对象、JCS 投影与首版 hash 向量 |
| 测试与验收 | 第 6 节 PostgreSQL 16、并发、哈希、权限和 downgrade 用例 |
| 部署与运维 | 空表门禁、无 CHUNK_* 默认、显式发布顺序、非空 downgrade |
| 开发任务计划 | KB-004 的精确输入/输出、CHUNK-008/009、依赖 CR 和验收；P0 工作包总数不变 |

同步后必须重新生成九份 Request 的基线 hash，并把所有 API 计数更新为“同步前有效总数 + 本 CR 的 2 + 同批其他获批 CR delta”；本草案本身不授权这些改动。

## 8. 外部依赖与仍不能由正式基线唯一推导的点

本推荐合同已为 GAP-054 选择一个确定方案，但以下事实仍不能从现行正式基线直接推导，必须通过本 CR 或依赖 CR 审批：

1. **archive 产品能力。** 正式基线既有 archived 状态又无入口；本 CR 推荐 CHUNK-008。审批人也可以选择删除 P0 archived，但不能维持现状。
2. **精确 JCS Schema。** schema_version、hash 投影、325-byte 向量和数据库重算是本 CR 新推荐，不是 CR-001-R2 已批准值。
3. **I1 并发字段。** 保留 API row_version 并为 I1 增加专用列、CHUNK-002 CAS，是本 CR 的选择；正式基线也可能通过删除 API row_version 选择另一合同。
4. **后续配置范围。** 正式基线只批准首版 700/1200/50/100；本 CR只冻结基本 INTEGER 关系和三个 P0 处理对象。未来新策略、新对象字段或不同处理语义仍需新 config_schema_version 和 CR。
5. **operation log 注册表。** CHUNK-001/002/008 的最终 action tuple 固定要求 CR-008 至少包含 `chunk.config.create/publish/archive | chunking_config | finaudit_app_rw | actor_nullable=false | ["success"]`；CHUNK-008 的配置事实、幂等记录和 `chunk.config.archive` 必须同事务，重放复用首次日志。CR-008 未纳入该精确条目并形成最终注册表制品前，写接口 runtime 保持阻塞。CHUNK-009 是普通 GET，不新增成功 action。
6. **临时 system_admin。** break-glass 的有效角色证明依赖 CR-003；未批准前只能使用普通有效 system_admin。
7. **Job/Outbox 细节。** CHUNK-003 受理快照、事件序列和 lease/retry 依赖 CR-004；本 CR只冻结配置与归档的可串行结果。
8. **配置管理读取入口。** 现有 CHUNK-001～007 没有分块配置列表/详情 API；本 CR 已明确选择 CHUNK-009 以一个返回完整记录的列表入口闭合 UI-009 重载，不再另增详情接口。该选择、cursor 和 `api_delta=+2` 仍须随本 CR 审批，不能由现有基线自动生效。

## 9. 审批边界

本合同只有在第 10 节记录匹配本 snapshot 的完整批准后才生效。CR-001-R2 与 CR-002-R4 的既有批准不自动批准本 CR；在该条件满足前，不授权：

- 修改或同步 Request。
- 创建 chunking_configs migration、模型、Repository、Service、API、UI、触发器或测试。
- 增加 CHUNK-008/009、应用 `api_delta=+2` 或改写 API 总数。
- 生成正式 Alembic revision、执行数据迁移、回填或 production downgrade。
- 调用 fixed_test_provider、/v1/models、真实 Chat/Embedding、内部 vLLM HTTP 或其他网络。
- production、canary、部署、提交、推送或 PR。

建议审批矩阵：

| 决策 | 需求 | 架构 | 数据库 | 后端/API | AI/RAG | 测试 | 运维 | 安全 |
|---|---|---|---|---|---|---|---|---|
| 字段、I1 + row_version、状态机 | 必需 | 必需 | 必需 | 必需 | 必需 | 必需 | N/A | 必需 |
| chunking-config-v1 与 JCS/hash | 必需 | 必需 | 必需 | 必需 | 必需 | 必需 | N/A | 必需 |
| CHUNK-008/009、cursor、`api_delta=+2` 与累计总数规则 | 必需 | 必需 | N/A | 必需 | N/A | 必需 | 必需 | 必需 |
| 权限、KB-004 owner、依赖边界 | 必需 | 必需 | 必需 | 必需 | 必需 | 必需 | N/A | 必需 |
| upgrade/downgrade 与 PostgreSQL 16 演练 | N/A | 必需 | 必需 | 必需 | N/A | 必需 | 必需 | 必需 |

每条批准记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_decisions / cr_revision=CR-009-R1 / decision_snapshot_sha256 / baseline_manifest_sha256=717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41 / api_delta=+2 / environment_scope=contract / 日期 / 证据链接 / 备注`。`selected_decisions` 必须逐项覆盖字段/JCS、状态机、CHUNK-008/009、幂等/CAS、cursor、revision ownership 与 downgrade；任一必需角色留空、拒绝、基线漂移或选择互相冲突时整体保持 NOT APPROVED。

`decision_snapshot_sha256` 计算规则：将全文行尾规范化为 LF，定位内容完全等于 `## 10. 当前状态` 的行，该标记必须恰好出现一次；取该行之前的全部行，去除已有的尾随 LF 后再保留恰好一个 LF，以无 BOM UTF-8 编码，对所得 bytes 计算 SHA-256 小写十六进制。标记缺失/重复、UTF-8 解码失败、BOM/行尾规则不满足或 hash 不是小写 64 位十六进制时不可签署。该 preimage 覆盖第 1～9 节，包括审批、网络和 production 禁止边界。

首次生成 decision snapshot 只建立可签署对象，不等于批准。生成后第 1～9 节任一规范性修改都必须提升 CR revision、重算 hash 并清空全部签署；第 10 节只记录状态，不进入 preimage。

## 10. 当前状态

| 项目 | 状态 |
|---|---|
| GAP-054 推荐合同 | PROPOSED |
| archive 方案 | PROPOSED：新增 CHUNK-008 |
| 配置读取方案 | PROPOSED：新增 CHUNK-009 完整列表；无第二个详情 API |
| API delta | PROPOSED：`+2`；最终总数按有效 CR 累加 |
| chunking-config-v1 JCS/hash | PROPOSED；测试向量已离线复算，不是批准制品 |
| CR-008 action 依赖 | BLOCKED UNTIL `chunk.config.archive` 纳入最终 registry |
| Request 同步 | NOT AUTHORIZED |
| decision snapshot | `68d002c6f851c7d18a670b992dc4c03026c4d08a67e02797735a048e44e8a597` / GENERATED_FOR_REVIEW / NOT APPROVED |
| 批准记录 | NONE |
| migration/代码/测试实现 | NOT AUTHORIZED |
| PostgreSQL 16 运行演练 | NOT RUN |
| fixed_test_provider/真实 Provider | OUT OF SCOPE / NOT AUTHORIZED |
| production | OUT OF SCOPE / NOT AUTHORIZED |
