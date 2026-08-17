# CR-016-R1：P0 审核规则目录与确定性发布合同闭合

状态：**DRAFT / PROPOSED / NOT APPROVED**

日期：2026-08-09

对应差异：GAP-066

## 1. 变更原因

正式 Request 已冻结 RULE-001～RULE-015 的业务判断、`audit_rules` 不可变表和 RULE-001 只读目录，也要求 AUD-003 在真实纯函数、输入 Schema 与测试完成后显式发布规则版本。当前 15 条纯离线谓词已经存在，但 Request 尚未逐条冻结 `category`、`input_schema_json`、`explanation_template`、`requires_policy_citation`、实现键、实现哈希前像、应用发布绑定、整批幂等语义，以及 RULE-001 在多版本数据上的选择和响应投影。

这些空白会让两个实现对同一 P0 规则生成不同数据库事实，或者用只覆盖单函数文本的哈希漏掉共享 helper 行为。它们也会让重跑、并发发布、停用和规则目录查询产生不同结果。本 CR 只闭合现有 15 条规则的静态元数据、输入传输 Schema、代码身份、显式发布和现有 RULE-001 投影；不新增 endpoint、表、migration、P0 工作包或规则执行语义。

本 CR 是候选合同，不是规则已发布、AUD-003 已完成或 AC-007 已通过的证据。实施计划仍要求 `BASE-005、AUD-002` 先完成；当前 BASE-005 仅实现 7/57 张核心表，AUD-002 仍未完成，因此即使本 CR 获批，也只能先同步 Request。静态 catalog/registry/publisher、数据库发布和 RULE-001 runtime 都必须等待同步完成且正式前置满足。

## 2. 范围、依赖与 delta

### 2.1 推荐冻结

1. 15 条首版规则的名称、分类、风险、引用标志、解释模板和实现键。
2. `input_schema_json` 的 Draft 2020-12 封闭对象 Profile、字段和传输到 Python 值的确定映射。
3. 应用发布版本、静态 callable registry 和整模块实现哈希前像。
4. 显式发布命令的事务、并发、no-op、冲突和日志边界。
5. 现有 RULE-001 对全版本目录、current 标记、过滤、排序和响应字段的投影。

### 2.2 固定 delta

| 项目 | 固定值 |
|---|---:|
| `api_path_delta` | `0` |
| `core_table_delta` | `0` |
| `alembic_migration_delta` | `0` |
| `operation_log_action_delta` | `0` |
| `p0_work_item_delta` | `0` |
| API 总数 | `122` |
| 核心物理表总数 | `57` |
| P0 工作包总数 | `86` |

本 CR 只澄清既有 `/api/v1/audit-rules` 和既有 `audit_rules` 字段，不创建新的 API、表、列、索引、HTTP/API 业务错误码或在线规则编辑能力。

### 2.3 依赖与非目标

- AUD-003 的正式前置仍逐字为 `BASE-005、AUD-002`；CR 获批不等于前置完成。
- 不实现规则执行器、上下文聚合、`rule_executions`、风险生成、引用检索、报告、页面、Auth/RBAC 或 AC-007。
- 不把谓词收到的预计算事实冒充上游查询、规范化、快照或授权已完成；调用方事实的来源仍由各业务任务负责。
- 不引入动态 import、在线 DSL、P1 规则编辑、数据 migration 或应用启动自动补种。
- 不授权读取或写入真实业务数据，不授权 fixed_test_provider、Provider、内部 vLLM 或其他外部网络，不授权部署、canary 或 production。

## 3. 推荐合同

### 3.1 REG-D-001：首批规则元数据

七个 `category` 值固定为：

| category | 含义 |
|---|---|
| `identity` | 主体名称或税务身份一致性 |
| `amount` | 金额、累计值和算术关系 |
| `date` | 业务日期及有效期 |
| `duplicate` | 精确业务身份重复 |
| `completeness` | 必需字段、关系或确认状态完整性 |
| `currency` | 币种一致性 |
| `policy` | 制度引用可用性 |

首批全部使用 `version=1`、`is_enabled=true`。`implementation_key` 只绑定规则身份和规则版本，格式固定为 `^finaudit\.audit\.rule-[0-9]{3}\.v[1-9][0-9]*$`，并只能由后端静态 allowlist 解析；禁止把数据库字符串交给通用 import/反射执行。应用发布身份独立绑定在 canonical `change_reason` 中，避免仅因应用 patch release 改写规则键。

| rule_code | name | category | default_risk_level | requires_policy_citation | implementation_key | explanation_template |
|---|---|---|---|---:|---|---|
| `RULE-001` | 发票销售方与合同乙方税号一致 | `identity` | `high` | `false` | `finaudit.audit.rule-001.v1` | 发票销售方税号与已确认主合同乙方税号不一致。 |
| `RULE-002` | 发票购买方与本企业税号一致 | `identity` | `high` | `false` | `finaudit.audit.rule-002.v1` | 发票购买方税号与本企业税号不一致。 |
| `RULE-003` | 累计开票金额不超过合同金额 | `amount` | `high` | `true` | `finaudit.audit.rule-003.v1` | 纳入计算的累计发票价税合计超过基准日期有效合同金额。 |
| `RULE-004` | 开票日期处于合同有效期 | `date` | `medium` | `false` | `finaudit.audit.rule-004.v1` | 发票开票日期不在已确认主合同有效期内。 |
| `RULE-005` | 发票重复 | `duplicate` | `high` | `false` | `finaudit.audit.rule-005.v1` | 发票代码、号码与销售方税号组合已存在。 |
| `RULE-006` | 合同核心字段完整 | `completeness` | `medium` | `false` | `finaudit.audit.rule-006.v1` | 已确认主合同缺少主体、金额、币种或生效日期中的至少一项。 |
| `RULE-007` | 发票核心字段完整 | `completeness` | `medium` | `false` | `finaudit.audit.rule-007.v1` | 发票缺少代码/号码、买卖方税号、日期或总额中的至少一项。 |
| `RULE-008` | 合同和发票币种一致 | `currency` | `medium` | `false` | `finaudit.audit.rule-008.v1` | 发票币种与已确认主合同币种不一致。 |
| `RULE-009` | 发票明细与总额一致 | `amount` | `medium` | `false` | `finaudit.audit.rule-009.v1` | 发票明细不含税额与税额之和与价税合计的差值超过 0.01。 |
| `RULE-010` | 主合同已确认 | `completeness` | `medium` | `false` | `finaudit.audit.rule-010.v1` | 审核任务未关联已确认主合同。 |
| `RULE-011` | 合同编号缺失 | `completeness` | `notice` | `false` | `finaudit.audit.rule-011.v1` | 已确认主合同缺少合同编号。 |
| `RULE-012` | 补充协议影响审核事实 | `completeness` | `medium` | `false` | `finaudit.audit.rule-012.v1` | 存在基准日期已生效但尚未确认的补充协议。 |
| `RULE-013` | 制度依据缺失 | `policy` | `notice` | `false` | `finaudit.audit.rule-013.v1` | 正常完成制度检索后，仍缺少基准日期适用的已发布或历史有效制度证据。 |
| `RULE-014` | 名称相同但税号冲突 | `identity` | `high` | `false` | `finaudit.audit.rule-014.v1` | 标准化名称相同但税务身份不一致。 |
| `RULE-015` | 普通发票金额必须为正 | `amount` | `medium` | `false` | `finaudit.audit.rule-015.v1` | 非红字发票价税合计小于等于零。 |

`change_reason` 不是自由文本；首批 15 行逐字等于以下 RFC 8259 canonical JSON 文本（UTF-8、键按 ASCII 顺序、无额外空白）：

```json
{"application_release":"finaudit-backend@0.1.0","reason":"initial-p0-built-in-rules"}
```

`requires_policy_citation=true` 的集合精确等于 `{RULE-003}`：API 现有示例明确冻结该值，其余规则没有逐条 true 的正式事实且数据库默认 false。RULE-013 自身为 false，避免元规则递归要求自己的制度引用。任何 citation、模板、名称、分类、风险或实现键变化都必须发布新规则版本，不能 UPDATE 已发布行。

解释模板必须逐字等于上表静态中文，不允许插值占位符、表达式、实际值、文件名、用户输入或模型输出；结构化实际值和计算过程属于未来规则执行结果，不拼入模板。

### 3.2 REG-D-002：输入 Schema Profile

每条 `input_schema_json` 都是手写、独立、无外部引用的 JSON Schema Draft 2020-12 对象；禁止用 Pydantic 或依赖版本自动生成。根键精确为 `$schema/$id/type/additionalProperties/properties/required/x-finaudit-applicability`，不允许 `title/description/default/examples/$defs` 或其他键：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:finaudit:audit-rule:rule-001:input:v1",
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": [],
  "x-finaudit-applicability": "requires_confirmed_primary_contract"
}
```

`$id` 按 `urn:finaudit:audit-rule:rule-NNN:input:vN` 从 code/version 双向推导。`properties` 与 `required` 包含相同的全部字段，静态制品中的属性与 required 数组都按字段名 ASCII 升序。所有输入都必须显式出现；“可空”表示值可为 JSON `null`，不表示字段可省略。禁止默认值、数值/布尔字符串转换、额外字段、非有限数、指数 Decimal、时区日期时间或猜测缺失事实。catalog 以确定性 source/JCS identity 固定 Schema；数据库中的 `JSONB` 幂等比较按解析后的结构等值，不依赖对象键顺序或空白。

字段类型缩写固定为：

| 缩写 | 精确 JSON Schema | Python 适配 |
|---|---|---|
| `B` | `{"type":"boolean"}` | 原样传递 exact `bool` |
| `BN` | `{"type":["boolean","null"]}` | `bool` 或 `None` |
| `S` | `{"type":"string","pattern":"\\S"}` | 原样传递；谓词仍拒绝 blank |
| `SN` | `{"type":["string","null"],"pattern":"\\S"}` | `str` 或 `None` |
| `D` | `{"type":"string","pattern":"^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$"}` | 以 plain 十进制字符串构造 exact finite `Decimal` |
| `DN` | `{"type":["string","null"],"pattern":"^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$"}` | `Decimal` 或 `None` |
| `T` | `{"type":"string","format":"date","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}` | 严格 RFC 3339 full-date 转 exact `date` |
| `TN` | `{"type":["string","null"],"format":"date","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}` | `date` 或 `None` |

Schema validator 必须真正验证 RFC 3339 日历日，不能把 `format=date` 仅当注释。适配器只执行上表机械转换，随后仍调用谓词自己的严格类型、有限值、空白和业务边界校验；任一转换或谓词校验失败都形成未来执行器的受控 `error`，不能改成 `passed`、`failed` 或自行补值。本 CR 不定义该错误的持久化或 HTTP 映射。

| rule_code | applicability | 字段与类型（表内顺序仅便于阅读；制品按 ASCII 排序） |
|---|---|---|
| `RULE-001` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, contract_party_b_tax_no:SN, invoice_seller_tax_no:SN` |
| `RULE-002` | `independent` | `organization_tax_number:S, invoice_buyer_tax_no:SN` |
| `RULE-003` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, cumulative_invoice_total:DN, effective_contract_amount:DN` |
| `RULE-004` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, invoice_date:TN, contract_effective_date:TN, contract_expiry_date:TN` |
| `RULE-005` | `independent` | `has_existing_exact_invoice_identity:BN` |
| `RULE-006` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, contract_subjects_present:B, contract_amount_present:B, contract_currency_present:B, contract_effective_date_present:B` |
| `RULE-007` | `independent` | `invoice_code:SN, invoice_number:SN, buyer_tax_no:SN, seller_tax_no:SN, invoice_date:TN, total_amount:DN` |
| `RULE-008` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, contract_currency:SN, invoice_currency:SN` |
| `RULE-009` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, line_net_amount:DN, tax_amount:DN, total_amount:DN` |
| `RULE-010` | `independent` | `has_confirmed_primary_contract:B` |
| `RULE-011` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, contract_no:SN` |
| `RULE-012` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, has_effective_unconfirmed_supplementary_agreement:B` |
| `RULE-013` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, requires_policy_citation:B, retrieval_completed_successfully:B, has_applicable_policy_citation:B` |
| `RULE-014` | `requires_confirmed_primary_contract` | `has_confirmed_primary_contract:B, standard_name_a:SN, standard_name_b:SN, tax_identity_a:SN, tax_identity_b:SN` |
| `RULE-015` | `independent` | `total_amount:DN, is_red_invoice:BN` |

这张适用性矩阵逐字落实需求的无主合同规则：没有已确认主合同时只执行 RULE-002/005/007/010/015，其余十条返回 `not_applicable`。registry adapter 必须先完成整份 Schema 校验，再对 `requires_confirmed_primary_contract` 检查 context；为 false 时直接返回 `not_applicable`。RULE-004/009/013/014 的底层谓词不接收该 context，adapter 调用它们时只移除 `has_confirmed_primary_contract`；其他规则按字段名调用。所有调用都用显式 keyword，不能依赖 JSON 属性顺序。

### 3.3 REG-D-003：实现身份与哈希

首版应用发布身份固定为 `finaudit-backend@0.1.0`，必须同时逐字等于 catalog 和 CLI `--expected-release`。运行制品另要求 `importlib.metadata.metadata("finaudit-backend")["Name"] == "finaudit-backend"`、`importlib.metadata.version("finaudit-backend") == "0.1.0"`，再将二者拼成 `finaudit-backend@0.1.0` 与前两项比较；不得把只返回 `0.1.0` 的 version 值直接同 release identity 比较。15 个稳定 `implementation_key` 必须与 REG-D-001 相等，由 `backend/app/audit/rule_registry.py` 中静态、封闭且无重复值的 allowlist 按下表映射；数据库内容不能选择任意 module、attribute 或表达式。

adapter mode 固定为：`direct_keywords` 按 Schema 字段名调用谓词；`require_contract_direct` 在完整 Schema 校验后，若 `has_confirmed_primary_contract=false` 返回 `not_applicable`，否则保留全部字段调用；`require_contract_drop_context` 执行同一短路，但调用谓词前只移除 context 字段。RULE-015 的 `is_red_invoice` 始终以 keyword 传递。

| implementation_key | predicate | adapter mode |
|---|---|---|
| `finaudit.audit.rule-001.v1` | `evaluate_rule_001` | `require_contract_direct` |
| `finaudit.audit.rule-002.v1` | `evaluate_rule_002` | `direct_keywords` |
| `finaudit.audit.rule-003.v1` | `evaluate_rule_003` | `require_contract_direct` |
| `finaudit.audit.rule-004.v1` | `evaluate_rule_004` | `require_contract_drop_context` |
| `finaudit.audit.rule-005.v1` | `evaluate_rule_005` | `direct_keywords` |
| `finaudit.audit.rule-006.v1` | `evaluate_rule_006` | `require_contract_direct` |
| `finaudit.audit.rule-007.v1` | `evaluate_rule_007` | `direct_keywords` |
| `finaudit.audit.rule-008.v1` | `evaluate_rule_008_currency_pair` | `require_contract_direct` |
| `finaudit.audit.rule-009.v1` | `evaluate_rule_009` | `require_contract_drop_context` |
| `finaudit.audit.rule-010.v1` | `evaluate_rule_010` | `direct_keywords` |
| `finaudit.audit.rule-011.v1` | `evaluate_rule_011` | `require_contract_direct` |
| `finaudit.audit.rule-012.v1` | `evaluate_rule_012` | `require_contract_direct` |
| `finaudit.audit.rule-013.v1` | `evaluate_rule_013` | `require_contract_drop_context` |
| `finaudit.audit.rule-014.v1` | `evaluate_rule_014_identity_pair` | `require_contract_drop_context` |
| `finaudit.audit.rule-015.v1` | `evaluate_rule_015` | `direct_keywords` |

`implementation_hash` 为小写 64 hex SHA-256，每条规则因 key 不同而有自己的值，但全部覆盖同一组共享源码。规范前像固定为：

```text
UTF8("finaudit-audit-rule-implementation-v1") || NUL
|| ASCII(implementation_key) || NUL
|| frame("app/audit/rule_predicates.py", normalized_predicates_bytes)
|| frame("app/audit/rule_registry.py", normalized_registry_bytes)

frame(path, bytes) := UTF8(path) || NUL || ASCII(decimal(len(bytes))) || NUL || bytes
```

两个源文件都从实际发布制品读取，必须 strict UTF-8、无 BOM/NUL/U+FFFD；仅把 CRLF 和孤立 CR 规范化为 LF，不做 Unicode normalization、trim、格式化、AST 重排、注释剥离或 bytecode hash。文件路径顺序逐字固定为上式。`rule_registry.py` 必须包含 allowlist、输入校验/适配和适用性短路；`rule_predicates.py` 包含共享 validator、返回 DTO、状态枚举和 15 个谓词。

静态 catalog/manifest 和 publisher 不进入前像，避免把期望 hash 写入自身形成自引用。实现文件固定为 `backend/app/audit/rule_registry.py`（allowlist/adapter）、`backend/app/audit/builtin_rule_catalog.py`（版本、release、15 行元数据/Schema/期望 hash）和 `backend/app/audit/publish_rules.py`（CLI）。catalog 保存 15 个期望 hash；dry-run 和 publisher 必须从实际文件独立复算，不能信任 catalog 自报值。当前三文件尚未获准实现，因此本 CR 不伪造 15 个最终 hash；实现完成后，任一 hash 未由上述前像生成都禁止发布。

该策略会让任一谓词、共享 helper、输入 adapter、适用性 wrapper、`RulePredicateResult` 或 `RuleExecutionStatus` 行为变化触发全部 15 条规则一起升版。P0 只有 15 条规则，该保守代价小于函数级 AST/transitive-dependency hash 漏掉共享行为的风险。

### 3.4 REG-D-004：显式整批发布

发布所有权只属于 AUD-003 的显式离线命令：

```text
python -m app.audit.publish_rules --apply --expected-release finaudit-backend@0.1.0
```

省略 `--apply` 时只能执行不连接数据库的 dry-run。命令只从进程环境读取数据库连接，不读 `.env`，连接 URL/凭据不得进入参数、控制台、日志或异常。Alembic migration、bootstrap、应用启动、HTTP 请求和 Worker 启动都不得自动发布或修复规则行。

首版合法数据库前态只有两种：整张 `audit_rules` 表为 0 行；或者整表恰好是与首版 catalog 相等的 15 行。1～14 行、超过 15 行、未知 code/version、混合版本或任一内容漂移都失败关闭，不能被首版 publisher 忽略。未来 v2 必须用新获批 catalog 明确允许的完整历史集合和新增批次，不能让 v1 命令猜测兼容。

数据库事务固定为：

1. 开始事务，先执行 `SET LOCAL lock_timeout='10s'` 和 `SET LOCAL statement_timeout='30s'`，再执行 `pg_advisory_xact_lock(5207210267357843480)`，最后执行 `LOCK TABLE audit_rules IN SHARE ROW EXCLUSIVE MODE`；该 advisory key 是 `SHA256("finaudit:audit-rules:publish:v1")` 前 8 字节按 signed big-endian 解码。任一超时返回固定脱敏 CLI result category `RULE_PUBLISH_LOCK_TIMEOUT` 并回滚。
2. 读取并锁定整表。0 行时用一条 multi-values INSERT 一次插入 15 行；禁止 `ON CONFLICT`、UPDATE 或逐行补齐。
3. 15 行时，代码/版本集合和 semantic projection 全部相等才 no-op；1～14、>15 或任一不同都整批失败。
4. semantic projection 精确包含 `rule_code/version/name/category/input_schema_json/implementation_key/implementation_hash/default_risk_level/explanation_template/requires_policy_citation/is_enabled/change_reason`；`id/published_at/created_at` 是服务器事实，不参与 payload 等值比较。
5. 首发 15 行的 `published_at` 必须全部由同一事务的 `transaction_timestamp()` 赋值；no-op 时仍要求现有 15 行的 `published_at` 非空且逐值相同，但不重算、不改写。
6. 插入后在同一事务重读并比较整表；COMMIT 前的任一错误、唯一冲突或进程异常都回滚整批，不留下部分版本。

并发首发只能一个事务插入；后到官方 publisher 在 advisory/table lock 后必须落入 exact no-op 或 mismatch fail。绕过 advisory lock 的直接并发由表锁和唯一约束使整批回滚，不能把唯一冲突当成功。发布器没有 `--force`、UPDATE、DELETE、TRUNCATE 或自动修复模式；提交后的修正只能形成新的完整版本 catalog。控制台和错误只输出规则数量、catalog version 和固定结果/错误类别，不输出数据库 URL、凭据、规则输入或业务数据。

客户端发送 COMMIT 后、收到确认前连接中断属于 CLI result category `PUBLISH_OUTCOME_UNKNOWN`，不能声称已回滚，也不能盲目重发 INSERT。发布器必须用新连接重新读取权威整表：0 行表示可安全重跑；exact 15 表示首发已经提交，按幂等成功/no-op 收敛；任何其他状态失败关闭并要求人工调查。若新连接也不可用，则只返回固定 unknown 结果，不能报告成功或回滚。COMMIT 后控制台/普通日志失败不改写数据库；核心故障不变量是“0 行或 exact 15 行”，不是“所有异常都回滚”。

`RULE_PUBLISH_LOCK_TIMEOUT` 与 `PUBLISH_OUTCOME_UNKNOWN` 只属于离线 CLI 的固定 result categories/进程退出分类，不进入 HTTP `ErrorResponse`、OpenAPI、API 错误码清单、operation action registry、数据库枚举或 API 数量 delta。

### 3.5 REG-D-005：RULE-001 版本目录投影

RULE-001 仍是既有 `GET /api/v1/audit-rules`，不新增路径或 query。默认返回所有已发布不可变版本；每个 `rule_code` 的 `is_current` 由全量行上的 `version=MAX(version)` 计算，最新版本即使 `is_enabled=false` 仍是 current，不能错误回退到旧 enabled 版。

先在未过滤集合上计算 `is_current`，再对每一版本行应用现有 `enabled/category/rule_code` 过滤；缺省 `enabled` 返回 enabled 与 disabled 版本，`enabled=true|false` 精确比较该行的 `is_enabled`。结果固定按 `rule_code COLLATE "C" ASC, version DESC` 排序。P0 不新增分页；未来在线规则中心若需要分页或 current-only query，必须走独立 API 变更。

每个 item 精确返回：

```text
id
rule_code
version
name
category
input_schema_json
default_risk_level
explanation_template
requires_policy_citation
is_enabled
is_current
published_at
change_reason
```

不返回内部 `implementation_key/implementation_hash/created_at`。这满足需求对规则名称、分类、输入、风险、解释、启用、引用、发布时间和变更原因的完整只读目录，也保留现有示例中的字段。停用通过发布更高版本且 `is_enabled=false` 的完整 catalog 实现，旧版本保留供历史快照追溯。

Service 返回前必须按 code/version 找到对应版本化 catalog，并核对 row 的 semantic projection、key 与 hash；未知版本、缺 catalog 或任一漂移时整次请求返回现有 `INTERNAL_ERROR` 与 `trace_id`，不得部分返回或把内部值写入错误。该核对不要求旧版本 hash 等于当前源码，只要求等于其历史 catalog 固定的 hash。

本节只冻结响应事实，不授权在 Auth/RBAC、Service/Repository 和 AUD-002 前置缺失时提前上线 Router。

### 3.6 REG-D-006：版本与兼容边界

- `version` 是每个 rule_code 从 1 开始的正整数；新版本必须恰好等于该代码当前最大版本加 1。
- P0 整模块 hash 策略要求 15 条 lockstep 升版；同一 catalog 的 15 条 version 必须相同。
- 已发布行永久不可 UPDATE/DELETE/TRUNCATE；停用、模板、citation、Schema、实现或风险变化都发布新版本。
- 历史审核任务继续引用其快照中的原版本；RULE-001 展示全部已发布版本并标记 current，不改变历史结果。
- 在线编辑、审批工作流、用户 DSL 和非内置 rule_code 属 P1，不能借本 CR 进入 P0。

## 4. 九份 Request 原子同步

本 CR 只有在明确批准后，才允许把以下既有事实原子同步到九份 Request；同步前不得实现发布器或写入 `audit_rules`：

1. 需求规格：7.1～7.4 增加七类元数据、citation 真值集合、输入 Profile、代码身份和 lockstep 版本语义。
2. 系统架构：规则 registry/adapter/publisher 边界、静态 allowlist、整模块 hash 和 API→Service→Repository 依赖。
3. 数据库：只澄清 15 个既有字段的内容投影、批发布比较投影和全版本/current 查询；不改表结构。
4. API：RULE-001 全版本选择、current 标记、过滤、排序和十三字段 item。
5. 页面：只读目录显示字段；不增加编辑动作。
6. AI/RAG：明确规则确定性结果仍由后端谓词产生，AI/检索不决定发布或规则命中。
7. 测试：Schema、registry、hash、批发布、并发、no-op、API 全版本/current 和脱敏 Gate。
8. 部署：显式离线发布顺序、dry-run 和无启动自动发布。
9. 实施计划：AUD-003 输出细化，但保留 `BASE-005、AUD-002` 前置和原 6 人日/P0 边界。

同步必须在一个可审查变更集中完成，逐份复核 baseline 后才能实现；禁止只改数据库或 API 单份文档造成新漂移。

## 5. 验收 Gate

### 5.1 静态与单元 Gate

1. catalog 恰含 RULE-001～RULE-015，按代码顺序，无缺失、额外或重复；全部元数据逐字等于 REG-D-001。
2. 15 个 Schema 均通过本 CR 受限 Profile 的确定性结构校验和真实 date assertion；根封闭、字段全 required，类型、null、extra、Decimal/date 正反例闭合，不为此引入通用 Schema 运行时依赖。
3. 静态 allowlist 的 15 个键和值唯一；稳定键与 code/version 可双向推导，catalog release 与已安装包一致，adapter/callable 输入和返回与 Schema/谓词一致，动态 import 路径不可达。
4. 两个源码的 strict UTF-8/换行规范化、path/length frame 和 15 个 key-bound hash 均有 golden vector；改动任一函数、共享 helper、adapter、状态或返回 DTO 都使全部 15 个 hash 变化。
5. 解释模板无插值，citation true 集合恰为 `{RULE-003}`；日志/错误不含输入或环境秘密。
6. 启动、migration、bootstrap 和普通测试导入均不产生数据库写入。

### 5.2 专用 PostgreSQL 16 Gate

在一次性、无真实数据的 PostgreSQL 16 数据库中验证：空表首发 15 条且 `published_at` 逐值相同；同 payload 重跑 no-op 且时间不变；部分预置、额外未知行、单字段/JSONB 漂移、错 hash、错 release、不同 published_at、重复 key 全部整批回滚；两个并发首发恰一 insert 且另一 exact no-op；advisory/table 持锁超时在上限内脱敏失败；COMMIT 前故障为 0 行、COMMIT 后日志故障为 exact 15、提交结果未知可按 0/exact-15 重查收敛且永不产生部分行；已发布行仍拒绝 UPDATE/DELETE/TRUNCATE。

该 Gate 只能在 CR 获批、九份 Request 同步和 AUD-003 正式前置满足后执行。当前 PostgreSQL、Docker、真实账号、Browser E2E、Provider、远程 CI 与 production 均不由本 CR 授权。

### 5.3 API 与工程 Gate

在 Auth/RBAC、AUD-002 和 Service/Repository 具备后，验证 RULE-001 返回全部版本、`is_current` 只标记每代码 MAX(version)、停用不回退、过滤顺序、C/版本排序、十三字段闭包、catalog 完整性拒绝、角色权限、五字段 ErrorResponse/trace_id 和加载/空/错误/无权状态。统一离线门禁必须继续通过，且测试不得打开 Provider 或外部网络。

## 6. 审批、生效与授权边界

### 6.1 推荐决策集合

批准时 `selected_decisions` 必须按以下顺序精确为全集，`rejected_decisions=[]`：

```text
REG-D-001=FIRST_P0_RULE_METADATA_MATRIX
REG-D-002=CLOSED_DRAFT_2020_12_INPUT_SCHEMAS
REG-D-003=STABLE_REGISTRY_RELEASE_BINDING_AND_FRAMED_SOURCE_HASH
REG-D-004=EXPLICIT_ATOMIC_IDEMPOTENT_PUBLISHER
REG-D-005=VERSIONED_RULE_DIRECTORY_WITH_CURRENT_MARKER
REG-D-006=IMMUTABLE_LOCKSTEP_VERSIONING
```

### 6.2 规范性审批模板

```text
审批人姓名：YHBX（BOSS）
审批角色：需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全
审批结论：APPROVED
selected_decisions：REG-D-001～REG-D-006（按 6.1 声明顺序逐字列出）
rejected_decisions：[]
cr_revision：CR-016-R1
decision_snapshot_marker：## 8. 当前状态
decision_preimage_byte_length：见第 8 节已生成值
decision_snapshot_sha256：见第 8 节已生成值
environment_scope：contract/offline
network_scope：none
production_release_scope：none
批准日期：YYYY-MM-DD
证据链接：本 Codex task 中明确批准 CR-016-R1 的消息
备注：仅批准九份 Request 原子同步；同步完成且 BASE-005/AUD-002 正式前置满足后，才可按同步合同实现和在一次性 PG16 环境验收 catalog/registry/publisher/RULE-001。不批准真实数据、Provider/fixed_test_provider/内部 vLLM 网络、部署、canary 或 production。
```

当前用户“具备全部角色”的声明只说明具备签署资格，不等于已对本 CR 给出 `APPROVED` 结论。没有明确批准文本时，本 CR 始终只是候选。

### 6.3 快照算法

`decision_snapshot_sha256` 计算规则：严格 UTF-8 解码并拒绝 BOM、非法序列、NUL 或替换字符；把 CRLF 与孤立 CR 规范化为 LF；定位内容完全等于 `## 8. 当前状态` 的唯一标题行；取其前全部内容，移除末尾全部 LF 后追加恰好一个 LF；编码为 UTF-8 无 BOM并计算 SHA-256 小写 64 hex。不做 Unicode normalization、trim 或 Markdown 重排。

批准只授权先同步九份 Request。同步完成并逐份复核后，仍须满足 AUD-003 的 BASE-005/AUD-002 前置才能实现或发布。任何 Provider/网络、真实数据或 production 行为始终需要独立授权。

## 7. 回滚与失败关闭

- 批准前删除候选只删除本 CR/追踪记录，不改变 Request 或运行时。
- Request 同步必须是原子且可审查的单一变更；任一文档失败时整体回滚到批准前 baseline。
- 发布器实现可在无数据写入的 dry-run 后停止；数据库写入只允许一次性隔离 PG16 验收环境。
- 已发布规则行不可回滚删除；错误发布必须按新版本纠正并保留历史，因此真实发布前必须完成全部 Gate。
- 任一依赖、hash、release、Schema、元数据或批准证据不一致都失败关闭，不做局部补齐或隐式兼容。

## 8. 当前状态

- CR 状态：`DRAFT / PROPOSED / NOT APPROVED`。
- Review snapshot：`GENERATED FOR REVIEW / NOT APPROVED`。
- `decision_preimage_byte_length`：`30095`。
- `decision_snapshot_sha256`：`be30da8109e140dcac558abb3dab1871ef6228cf09d09bd9762fb430618fe8b1`。
- 审批记录：`NONE`。
- 九份 Request 同步：`NOT AUTHORIZED / NOT STARTED`。
- catalog/publisher/RULE-001 runtime：`NOT AUTHORIZED / NOT IMPLEMENTED`。
- BASE-005/AUD-002 前置：`NOT SATISFIED`。
- Provider/fixed_test_provider/内部 vLLM 网络：`NOT AUTHORIZED / NOT CALLED`。
- 真实数据、部署、canary、production：`NOT AUTHORIZED / NOT RUN`。
