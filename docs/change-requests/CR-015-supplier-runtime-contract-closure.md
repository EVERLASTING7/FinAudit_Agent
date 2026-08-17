# CR-015-R2：供应商候选、精确复用与纠错运行时合同闭合

状态说明：动态审批与授权状态只记录在第 8 节；第 1～7 节是待签署的静态合同。

日期：2026-08-09

对应差异：GAP-064

## 1. 变更原因

正式 Request 已要求从合同乙方和发票销售方生成供应商候选、按税号精确匹配、由用户确认或修正，并把确认后的供应商回填至合同/发票；但现有文档仍不能唯一实现这条链路：`suppliers` 有 `unified_social_credit_code/tax_number` 两个来源列，SUPP-001～003 只有一个 `tax_number`；AI 只输出未分型的 `party_b_tax_id/seller_tax_id`；SUPP-003 可在一次请求中修改名称、税号和确认状态，却只返回一个 `correction_id`，而 `correction_type` 没有 supplier 类型。`confirmation_status/status` 的合法组合、精确复用时路径候选和来源对象如何变化、并发输家如何处理、数据库约束如何映射为业务错误也没有闭合。

未批准的 CR-012-R3 已把上述运行时事实明确排除，只推荐三表 DDL/存储合同。本 CR 因此独立冻结 GAP-064，不回写或扩大 CR-012-R3；它只有在 CR-012-R3 先获批并同步后才可生效。R2 取代未签署的 R1 review snapshot，并补齐人工确认证据、候选生命周期、跨组织闭包、版本/确认元数据、拒绝审计和依赖证据。当前代码尚无供应商 Router/Service/Repository，本 CR 是合同候选，不是实现或验收证据。

## 2. 范围、依赖与 delta

### 2.1 依赖绑定

本 CR 的唯一财务主数据依赖固定为：

```text
dependency_revision=CR-012-R3
dependency_snapshot_sha256=b9d789568dd5b813c5fff4da03a823b922fc263245aeb01e53655b51ba1179c0
```

若 CR-012-R3 未获批、获批文本不是该 snapshot，或九份 Request 尚未完成对应 DDL/存储事实同步，本 CR 即使单独获批也不得启动供应商运行时实现。CR-013/014、DEP-005-R2 及其 package-external signer registry/pin 均未获批准，不构成本 CR 的审批或实现前置。

### 2.2 固定 delta

| 项目 | 固定值 |
|---|---:|
| `api_path_delta` | `0` |
| `core_table_delta` | `0` |
| `alembic_migration_delta` | `0` |
| `operation_log_action_delta` | `0` |
| `p0_work_item_delta` | `0` |
| `api_error_code_delta` | `+3` |
| `correction_type_delta` | `+1`：`supplier_field` |
| API 总数 | `122` |
| 核心物理表总数 | `57` |
| P0 工作包总数 | `86` |

本 CR 不新增 endpoint、表或 Alembic revision。`supplier.update` 只是为 SUPP-003 已要求的 operation log 固定现有字符串语义；`security.authorization.denied` 只是固定正式 Request 已要求的通用权限拒绝类别。二者不引入 action registry、事件类或数量 delta；任何后续操作日志注册表必须兼容这些值，但未批准的 CR-008 不是本 CR 的事实来源。

### 2.3 不在本 CR 范围

- 不实现 Router、Service、Repository、ORM、migration、前端页面或 AC。
- 不支持供应商别名、自动名称合并、拆分、活动供应商停用/改写、inactive 重新激活、历史回滚或风险画像；这些仍是 P1 或后续显式合同。
- 不新增 typed USCC 写入/纠正接口；generic `tax_number` 不得充当清除或替换已有 typed USCC 的暗门。
- 不定义税务标识行政真实性、校验位、外部企业查询或模糊名称匹配。
- 不改变合同/发票字段确认、`critical_fact_hash` 或过期传播的既有职责；若来源 `supplier_id` 变化触发已批准的通用过期规则，相关写入仍必须同事务提交。
- 不批准真实数据清理、Provider/fixed_test_provider/内部 vLLM 网络、部署、canary 或 production。

## 3. 推荐运行时合同

### 3.1 FINR-D-001：统一税务身份投影

SUPP-001～003 保持正式 Request 各 endpoint 已有 DTO；本 CR 只统一其中 `tax_number` 的值语义，不把三个响应改成相同字段集合。SUPP-001 item 继续包含 `id/standard_name/tax_number/source_type/confirmation_status/status/row_version`；SUPP-002 保持其详情 DTO；SUPP-003 的嵌套 `supplier` 精确保持 `id/standard_name/tax_number/confirmation_status/status`，不得在该嵌套对象新增 `source_type` 或 `row_version`。

所有 Supplier DTO 的 `tax_number` 都是唯一公开税务身份字段，逐字等于：

```text
COALESCE(unified_social_credit_code, tax_number)
```

两个来源列同时非空时必须先验证其按 CR-012-R3/FIN-D-001 保存的规范值逐字相同；若不相同，API 返回脱敏 `INTERNAL_ERROR` 并写内部一致性告警，不得任选一列或回显原值。SUPP-001 的 keyword 税号过滤与所有精确复用都使用同一投影、同组织、`COLLATE "C"` 的已保存字节比较；名称永不参与硬身份、唯一性或自动复用。

generic `tax_number` 不做大小写折叠、Unicode normalization、内部字符删除或形状推断；只接受 CR-012-R3/FIN-D-001 已冻结的非空、无首尾 ASCII space、无 C0/C1 control、最多 32 个 Unicode scalar 的保存形式。`standard_name` 必须是通过项目文本信任边界的非空字符串且不超过数据库上限，但本 CR 不用名称相等作任何身份决定。

SUPP-002 的合同/发票摘要继续按调用者对每个业务对象的可见范围裁剪；列表、详情、错误、日志或 breadcrumb 不得借统一值语义扩大现有权限。

### 3.2 FINR-D-002：AI 与 generic tax 写入投影

AI 输出只允许以下确定映射：

```text
contract.party_b_tax_id.value
  -> contracts.party_b_tax_no
  -> suppliers.tax_number

invoice.seller_tax_id.value
  -> invoices.seller_tax_no
  -> suppliers.tax_number
```

AI 来源 supplier candidate 固定写 `unified_social_credit_code=null`。即使 generic 值为 18 位或外观类似统一社会信用代码，也不得按长度、字符集、名称、来源、其他文档、置信度或模型解释推断并写入 USCC；甲方/购买方税号也不得误投影到供应商。generic 值为 null 时两列都保持 null，不从名称或关系补值。只有已经通过严格 Schema、引用/证据和后端字符校验且完成 CR-002 审计接受的字段才能进入业务事务；AI 不得确认、激活或决定复用供应商。

“来源税号已人工确认”只由以下两个锁内谓词建立；endpoint 名称、请求 actor、AI confidence、`field_evidence_json`、`user_corrections` 或 operation log 均不得单独替代它：

```text
ContractTaxConfirmed(contract) :=
  contracts.party_b_tax_no IS NOT NULL
  AND EXISTS contract_fields row WHERE
      contract_id = contracts.id
      AND field_code = 'party_b_tax_no'
      AND confirmation_status = 'confirmed'
      AND confirmed_value_json is JSON string
      AND decoded(confirmed_value_json) COLLATE "C"
          = contracts.party_b_tax_no COLLATE "C"
      AND confirmed_by IS NOT NULL
      AND confirmed_at IS NOT NULL

InvoiceTaxConfirmed(invoice) :=
  invoices.seller_tax_no IS NOT NULL
  AND invoices.confirmation_status = 'confirmed'
  AND invoices.confirmed_by IS NOT NULL
  AND invoices.confirmed_at IS NOT NULL
```

只有 CON-005 可建立 `ContractTaxConfirmed`。CON-004 改变 `party_b_tax_no` 时，若对应 `contract_fields` 行存在，必须同事务把它设为 `unconfirmed` 并清空 `confirmed_value_json/confirmed_by/confirmed_at`；不存在时不得创建伪 confirmed 行。新值重新经 CON-005 确认前禁止直接复用。只有 INV-005 可建立 `InvoiceTaxConfirmed`；INV-004 改变 `seller_tax_no` 时，必须同事务把发票设为 `confirmation_status='unconfirmed'` 并清空 `confirmed_by/confirmed_at`，随后重新经 INV-005 确认。resolver 必须在来源行锁内、应用本次写入后计算谓词。

CON-004/INV-004 改变已绑定来源的税号为 null 或与被绑定活动供应商统一身份不同的值时，必须同事务清空来源 `supplier_id` 并触发既有通用过期规则；相同保存值或修改无关字段不得清空。未确认的 AI 或普通 PATCH 税号即使精确命中活动供应商，也不能直接回填，只能在名称存在时产生 `unconfirmed/candidate` 并等待人工处理。

来源名称为 null/空白时不得用税号、文件名或占位文本填充 `standard_name`。来源合同/发票仍可保存，但在没有可直接复用的活动供应商时保持 `supplier_id=null` 且不创建 supplier；后续补名后 resolver 在来源行锁内重新评估。同一来源发现两个以上未删除 `unconfirmed/candidate` 时是权威数据不一致，返回脱敏 `INTERNAL_ERROR`，不得任选或继续写入。

### 3.3 FINR-D-003：候选状态机与 SUPP-003 请求边界

供应商 P0 只允许三种组合：

| `confirmation_status` | `status` | 含义 |
|---|---|---|
| `unconfirmed` | `candidate` | 待人工确认候选 |
| `confirmed` | `active` | 可被精确复用的活动供应商 |
| `rejected` | `inactive` | 未采用或因复用既有活动供应商而退役的候选 |

其他组合全部非法。确认元数据必须同时满足：

```text
confirmed/active
  => confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL

unconfirmed/candidate OR rejected/inactive
  => confirmed_by IS NULL AND confirmed_at IS NULL
```

创建候选显式写 `unconfirmed/candidate`、`confirmed_by=null`、`confirmed_at=null` 和 M1 `row_version=1`。SUPP-003 只接受路径目标当前仍为该组合。`status`、来源字段、USCC、`confirmed_by/confirmed_at` 都是服务端字段，客户端提交一律 `422 VALIDATION_ERROR`。活动或失活供应商通过 SUPP-003 修改、停用、恢复或重新激活一律 `409 SUPPLIER_STATE_CONFLICT`；P0 不以该接口实现 P1 回滚。

SUPP-003 请求继续只有：必填 `row_version/reason`，以及可选 `standard_name/tax_number/confirmation_status`；`confirmation_status` 只允许 `confirmed/rejected`。三个可变字段至少提供一个，额外字段失败关闭，`tax_number=null` 不表示清空。所有输入在任何状态短路前完成严格 Schema 校验。若规范化后的实际持久值均未改变，返回 `422 VALIDATION_ERROR`，不增加版本、不写 correction 或 success log。

`confirmation_status=confirmed` 时，最终名称和统一税务身份都必须非空，最终税务身份还必须逐字等于锁内来源对象当前已人工确认的税号；来源谓词未成立或值不相同均返回 `409 SUPPLIER_TAX_IDENTITY_CONFLICT`。`rejected` 不要求税务身份。

若候选已有非空 `unified_social_credit_code`，SUPP-003 的 generic `tax_number` 采用下列封闭规则：

```text
requested tax_number != unified_social_credit_code -> 409 SUPPLIER_TAX_IDENTITY_CONFLICT
requested tax_number == unified_social_credit_code -> 只做等价校验，不写 suppliers.tax_number
```

因此 only-USCC 行单独提交同值 generic tax 是 `422 VALIDATION_ERROR` no-op；与名称或状态变化同时提交时只执行其他实际变化，`tax_number` 不进入 correction、summary、hash 或 mask。没有 USCC 时，generic 值只有与现有 `tax_number` 不同时才写入。不得为了补齐双列写冗余 generic 值，也不得清除或改写 USCC；需要纠正 typed USCC 时必须另提显式字段、权限和审计合同。

SUPP-003 无复用激活时，路径候选固定写 `confirmed_by=当前 actor_id`、`confirmed_at=transaction_timestamp()`；这两个值分别等于同一事务 correction 的 `actor_id/created_at`。显式拒绝或确认后复用既有 active 时，路径候选固定为 `rejected/inactive` 且确认元数据仍为 null；操作者和时间只进入 correction。任何复用都不得改写既有 active 的确认元数据、`updated_*` 或 `row_version`。

### 3.4 FINR-D-004：精确复用、来源回填与响应

精确复用只查询同组织、未删除、`confirmed/active` 且统一税务身份逐字相同的供应商。resolver 在来源行锁内先查询该来源当前未删除的唯一 `unconfirmed/candidate`，记为 `C`，再查询精确活动匹配集合 `M`；只允许下列结果：

| 条件 | 固定结果 |
|---|---|
| `|M| > 1` | 脱敏 `INTERNAL_ERROR`，完整回滚 |
| `C` 存在且 `|M|=0 或 1` | CON/INV endpoint 不绑定、不修改或退役 `C`；来源 `supplier_id` 保持 null，交由 SUPP-003 显式处理 |
| `C` 不存在且 `|M|=1` | 原子回填既有 active supplier；不创建候选，也不修改 active |
| `C` 不存在、`|M|=0` 且名称非空 | 创建一个 `unconfirmed/candidate`；来源 `supplier_id` 保持 null |
| `C` 不存在、`|M|=0` 且名称缺失 | 不建候选；来源 `supplier_id` 保持 null |

既有 `C` 是该来源唯一的人工供应商处理对象；CON-004/005、INV-004/005 不得静默覆盖其名称、税号、状态、确认元数据或 `row_version`。`C` 的字段就是当前待人工确认值；SUPP-003 未提交 `standard_name/tax_number` 时沿用该 candidate 的当前持久值，不扫描来源或纠错历史，也不因来源曾变化而要求重复提交同值。确认只按第 3.3 节校验最终名称非空、最终统一税务身份非空且逐字等于锁内来源当前人工确认税号；名称无需等于来源名称，标准名称仍由用户显式决定。即使 `C` 已精确命中 active，也只能由 SUPP-003 执行退役和复用。发现两个以上 `C` 时返回脱敏 `INTERNAL_ERROR`，不得任选。

SUPP-003 对 candidate 提交 `confirmation_status=confirmed` 时：

- 没有其他活动精确匹配：路径候选变为 `confirmed/active`，来源对象的 `supplier_id` 回填为该候选。
- 恰有一个其他活动精确匹配：该人工确认动作选择 P0 精确复用；路径候选变为 `rejected/inactive`，来源对象回填为既有活动供应商，不复制候选名称或税号到活动行。
- 来源对象已经引用同一解析结果时允许按实际差异收敛；若已引用不同身份供应商，返回 `409 SUPPLIER_STATE_CONFLICT`，不得静默覆盖。

SUPP-003 响应保留现有 `supplier/row_version/correction_id`，只新增必填布尔 `reused`：

- `supplier` 的字段集合固定为 `id/standard_name/tax_number/confirmation_status/status`。
- 顶层 `row_version` 始终等于 URL path candidate 在本事务提交后的新版本，即 `request.row_version + 1`；它不因 `reused` 改变所属对象。
- `reused=false`：`supplier.id` 等于路径 ID，可能仍是 candidate、已 active 或已 inactive。
- `reused=true`：`supplier` 属于实际生效的既有 active，`supplier.id` 与路径 ID 不同；顶层 `row_version` 仍属于已经退役的路径 candidate，既有 active 的未递增版本不在本响应返回。
- `correction_id` 始终属于路径 candidate 的唯一聚合纠错记录。客户端使用已知路径 ID 移除退役候选，再按返回的 `supplier.id` 刷新 SUPP-002。

不返回冲突原始税号。接口总数仍为 122；当前没有实现，因此不增加旧/新双字段兼容层，九份 Request、OpenAPI、前端类型和实现必须同一变更窗口原子采用 `reused`。

### 3.5 FINR-D-005：并发、锁序与错误映射

`auth_organization_id` 只能来自服务端当前认证上下文，客户端不得提交或覆盖。SUPP-003 必须先完成认证和 endpoint capability 判定；角色不足时不得查询资源。随后以 `id + organization_id=auth_organization_id + deleted_at IS NULL + source_in_current_data_scope` 做路径可见性查询；零行与随机不存在 ID 对外同为 404，并走本 CR 第 3.7 节 denied 审计，禁止再用无组织谓词探测真实存在性。

所有会运行 supplier resolver 或 SUPP-003 的事务固定使用同一锁序：

1. `organizations` 的 `auth_organization_id` 行 `FOR UPDATE`。
2. 在组织锁内重读路径 candidate 的 source 标识；再以 `id + organization_id=auth_organization_id + deleted_at IS NULL` 锁当前 contract/invoice 来源行。
3. 从已锁来源收集其当前 `supplier_id`，所有 supplier 查询都附带同一组织和未删除谓词。
4. 路径 candidate、来源已引用 supplier 和精确匹配 supplier 按 UUID bytes 升序 `FOR UPDATE`。
5. 再验证 candidate source 标识未变化，并逐项证明 candidate、source、source 已引用 supplier、精确匹配 supplier 的 `organization_id` 全部等于 `auth_organization_id`。
6. 按 CAS 校验版本、状态、来源关系和身份后，写 candidate、来源 `supplier_id`、correction、success operation log，以及既有通用过期规则要求的 outbox/过期事实。
7. 单一 PostgreSQL 事务提交。

来源或 supplier 的 scoped lock 查询零行、组织不一致或脏跨租户关系一律脱敏 `INTERNAL_ERROR`、完整回滚并写只含安全错误码和 `trace_id` 的内部安全告警；不得锁定、读取正文或修改其他组织行。所有入口必须先锁组织行，禁止反序。

版本与确认 provenance 固定为：

- candidate 创建时 `row_version=1`；每个成功 SUPP-003 都对路径 candidate 恰好 `+1`，包括仅修改、拒绝、激活和复用。
- candidate 更新 SQL 必须包含 `id/organization_id/deleted_at IS NULL/row_version=:expected`；锁后检查不能替代 CAS。
- source 的 `supplier_id` 真正改变时，source `row_version` 恰好 `+1`；若 resolver 属于同一 CON/INV PATCH/确认事务，整行总共只增加一次，不得因字段写入和 resolver 重复增加。
- SUPP-003 修改 source 时使用锁内读到的 source 版本做 CAS，受影响行必须恰好 1；被复用 active 不执行任何 UPDATE，包括 `updated_at/updated_by/row_version/confirmed_by/confirmed_at`。
- 同一 candidate 的第二个旧版本请求必须先得到 `RESOURCE_VERSION_CONFLICT`，再考虑状态或身份错误。

唯一索引仍是最终保护，但符合本合同的两个不同候选并发确认同一税号时，组织锁使一个变为 active，后一个在锁后观察到唯一活动匹配并以 `200 reused=true` 收敛；同一候选相同旧 `row_version` 的并发请求最多一个成功。业务失败必须回滚所有 candidate/source 状态、correction、success log 和 outbox；授权拒绝的独立 denied log 不属于该业务事务。

精确错误映射为：

| 错误码 | HTTP | 触发条件 |
|---|---:|---|
| `CONTRACT_NUMBER_CONFLICT` | 409 | CON-002/004/005 的非空合同编号命中 `uq_contracts_organization_contract_no` |
| `SUPPLIER_STATE_CONFLICT` | 409 | 非 candidate 目标、非法状态转换或来源已绑定不同身份 supplier |
| `SUPPLIER_TAX_IDENTITY_CONFLICT` | 409 | generic tax 与同一 supplier 的 typed USCC 不同，或 candidate 最终身份与来源当前人工确认税号不相同/未形成确认谓词 |
| `SUPPLIER_TAX_NUMBER_CONFLICT` | 409 | `uq_suppliers_organization_tax_identity` 的并发唯一冲突在锁后仍无法按精确 active supplier 收敛；沿用现有错误码，不计 delta |
| `RESOURCE_VERSION_CONFLICT` | 409 | SUPP-003 的目标 row_version 已变化 |
| `VALIDATION_ERROR` | 422 | Schema、空名称、confirmed 缺名称/税务身份或 no-op 不合法 |

PostgreSQL driver/SQLAlchemy 原始异常是敏感内存对象。Repository 只允许读取 `sqlstate` 和 `diag.constraint_name`，回滚后仅按 `23505 + uq_contracts_organization_contract_no` 或 `23505 + uq_suppliers_organization_tax_identity` 精确映射；不得读取、保存或输出 `str/repr/params/statement/DETAIL/HINT/CONTEXT`，不得附带 `exc_info` 或异常链。其他 SQLSTATE、空/未知 constraint name 均返回脱敏 `INTERNAL_ERROR`，等价于 `raise ... from None`。SUPP-003 的固定优先级为鉴权/可见性 → 严格 Schema → `row_version` → state/source → tax identity；旧版本与身份冲突同时存在时只返回 `RESOURCE_VERSION_CONFLICT`。

### 3.6 FINR-D-006：单条纠错、操作日志与脱敏

`correction_type` 新增唯一值 `supplier_field`。每个成功 SUPP-003 事务恰好创建一条 append-only `user_corrections`：

```text
correction_type = supplier_field
organization_id = auth_organization_id
object_type = supplier
object_id = URL path supplier_id
field_path = $
related_execution_id = null
```

`before_value_json/after_value_json` 必须都是非空 object、键集合完全相同，并只包含本次真正改变的逻辑事实。封闭键集合为：

```text
standard_name
tax_number
confirmation_status
status
source_supplier_id
```

值是事务前后真实持久事实，null 必须显式保存；未变化字段不得进入对象。`tax_number` 使用第 3.1 节公开 `COALESCE` 投影的事务前后值，不使用物理列名；`source_supplier_id` 是来源 contract/invoice 的实际 `supplier_id`，激活或复用导致回填时必须记录。来源 `supplier_id` 只允许为 null 或指向同组织 `confirmed/active` supplier，不得指向 candidate/inactive。`row_version/updated_at/updated_by/confirmed_by/confirmed_at` 不属于逻辑 before/after。一次请求同时改名称、税号和确认状态仍只写一行；返回 `correction_id` 必须逐字等于该行 ID。AI/系统候选投影不是人工修正，不伪造 actor 或 supplier correction。

`related_execution_id` 固定为 null；`caused_outdated=true` 当且仅当本事务按通用过期规则实际把至少一个 execution/report 标记为 outdated，否则为 false。`actor_id/created_at/trace_id/reason` 使用当前 actor、`transaction_timestamp()`、当前 trace 和请求原始 reason。`actor_role_code` 只能由服务端事务内有效角色决定：有 `finance_reviewer` 时固定为该值，否则有 `contract_admin` 时为该值，否则拒绝；客户端 Body/Header/UI 不得自报。operation log 的 `actor_role_codes` 保存服务端计算的全部有效角色快照。

SUPP-003 的 operation log 固定：

```text
action_code = supplier.update
resource_type = supplier
resource_id = URL path supplier_id
before_hash = null
after_hash = null
reason = null
result = success
error_code = null
```

用户原始 `reason` 和完整 before/after 只保存在受控 `user_corrections`。`change_summary_json` 根对象及字段变化项采用以下封闭形状，禁止额外键：

```json
{
  "schema": "supplier-update-summary-v1",
  "correction_id": "lowercase-uuid",
  "reused": false,
  "changed_fields": ["tax_number"],
  "field_changes": {
    "tax_number": {
      "before_sha256": "lowercase-64-hex",
      "after_sha256": "lowercase-64-hex",
      "before_masked": null,
      "after_masked": "9131****02X2"
    }
  }
}
```

`changed_fields` 必须非空、去重并按 Unicode code point 排序；`field_changes` 键集合与其完全相同。非 `tax_number` 项只允许 `before_sha256/after_sha256`；`tax_number` 项必须另有 `before_masked/after_masked`。null mask 是 JSON null；税号长度按 Unicode scalar 计，1～8 个 scalar 输出等长全 `*`，大于 8 输出前 4、固定 `****`、后 4。不得保存原值。

每个值的 hash preimage 是无空白 JSON array：

```text
["supplier-field-value-v1",correction_id,field_name,"before"|"after",value]
```

编码固定为 UTF-8 无 BOM、无尾随换行；`value` 只允许 JSON null 或 string，UUID 使用小写带连字符形式。`"` 编码为 `\"`，`\` 编码为 `\\`，U+0000～U+001F 编码为小写 `\u00xx`，其他 Unicode scalar 直接编码为 UTF-8，`/` 不转义；拒绝 surrogate/非法 Unicode且不做 Unicode normalization。固定向量为：

```text
correction_id=64000000-0000-0000-0000-000000000030
before_preimage=["supplier-field-value-v1","64000000-0000-0000-0000-000000000030","tax_number","before",null]
before_bytes=93
before_sha256=6af42b245c869152a5d6df170c6832dd7d3f0e64ac8502205e1f783e4a3b88ca
after_preimage=["supplier-field-value-v1","64000000-0000-0000-0000-000000000030","tax_number","after","91310000MA000002X2"]
after_bytes=108
after_sha256=d2947c0b4c4d4f31a29163631212fe3327a0e2b661604c3977b381971d53d1c6
after_masked=9131****02X2
```

原始 PostgreSQL exception 可在受控内存 fixture 中含合成 sentinel，但不得被 stringify 或进入任何输出。HTTP、应用错误、stdout/stderr、Trace、指标、operation log、Outbox、AiCallEventV1、ai_call_logs 和测试报告不得包含完整税号、USCC、用户 reason、供应商正文或原始模型输入/输出；受控 fixture、业务表和 `user_corrections` 不属于输出扫描范围。

supplier/source 更新、版本递增、单条 correction、operation log，以及既有通用规则实际触发的过期/outbox 写入必须同事务提交；任一步失败全部回滚。`user_corrections` 继续禁止 UPDATE/DELETE。

### 3.7 FINR-D-007：权限与用户可见行为

- 已解析可信组织和 actor 后，角色不足、数据范围/IDOR/跨组织拒绝必须在独立受控安全审计事务恰好写一条 `security.authorization.denied/api_request/denied`；它复用正式 Request 已要求的“权限拒绝”审计类别，不增加 action 数量。固定字段为 `resource_id/before_hash/after_hash/reason=null`、`change_summary_json={}`、`error_code=AUTH_FORBIDDEN` 和当前 `trace_id`；组织、actor 与全部有效角色只来自认证上下文。路径 UUID、请求体、用户 reason、税号、资源正文和资源是否存在不得进入记录。
- scoped supplier lookup 零行与随机不存在 ID 对外同为 404，并按潜在 IDOR 写上述 denied 记录；禁止额外无组织查询。无法建立可信 actor/organization 的预认证失败由全局认证审计处理，SUPP-003 不重复写。denied 审计失败时返回脱敏 `INTERNAL_ERROR`，业务效果保持零。
- `supplier.update/success` 只与成功业务写同事务；业务回滚不得留下该 success log。安全拒绝只写 `security.authorization.denied`，不得再为目标 supplier 写第二条 denied/failure 日志。
- SUPP-001 保持 finance_reviewer、contract_admin 可维护视图，audit_reviewer 只读；system_admin 默认无业务维护权。
- SUPP-002 按每个关联合同/发票的数据范围裁剪；不得因知道 supplier ID 读取无权业务对象。
- SUPP-003 仅 finance_reviewer、contract_admin；后端必须独立校验，前端隐藏按钮不是授权证据。
- `reused=true` 明确告诉用户本次人工确认复用了既有活动供应商；UI 移除退役候选并刷新最终 supplier，不得把它渲染为静默自动合并。
- 同名不同税号继续作为不同候选；相同税号不同名称可在人工确认时复用，但绝不覆盖活动供应商标准名称。

### 3.8 FINR-D-008：兼容与授权边界

CR-015 获批只授权九份 Request 原子同步以及在全部运行依赖就绪后的离线实现/专用合成 PostgreSQL 16 验证。它不授权提前创建 CR-012 三表、user_corrections、operation_logs、Auth/RBAC 或 Outbox，也不把任何静态/Mock 证据升级为业务 AC。

未配置安全专用测试库、前置表或有效本地 Auth/operation-log port 时，对应 PostgreSQL/API/E2E 证据必须写 `NOT_RUN`；不得通过放宽鉴权、临时内存表、Mock 数据库或忽略审计失败来制造成功路径。

## 4. 已冻结且不变的合同

- PostgreSQL 仍是供应商、合同、发票和纠错事实唯一来源；Redis/Qdrant/模型输出不得充当业务真相。
- `suppliers` 仍只有 CR-012-R3 的两个税务来源列，不增加 `identity_kind` 或隐藏表。
- SUPP-003 URL、HTTP 方法、成功状态、现有请求字段、单一 `correction_id` 和角色不变；只增加响应 `reused` 与本 CR 的约束。
- P0 不自动按名称合并，不实现供应商别名、拆分、复杂合并或回滚。
- AI 不决定审批、状态转换或确定性业务规则；失败和未知值保持 fail closed。

## 5. 九份 Request 原子同步

CR-015 只允许严格串行生效，不允许同一审批批次、条件批准、追认或占位证据。固定顺序是：`CR-012-R3 批准 → CR-012-R3 九 Request 原子同步并生成 post-sync 证据 → CR-015-R2 批准 → CR-015-R2 九 Request 原子同步 → 实现/测试`。CR-015 获批后，必须对以下九个精确路径生成临时副本、记录 pre/post SHA-256，并在全部验证成功后一次性替换；禁止 glob、部分同步或先改正式文件：

1. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
2. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
5. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
7. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
8. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
9. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`

同步至少覆盖 CON-002/004/005、INV-002/004/005、SUPP-001～003、Supplier DTO、三个新增错误码、`supplier_field`、状态机、精确复用/回填、AI generic tax、页面 `reused` 行为、锁序、事务、脱敏和测试。任何文件失败时必须保留九份原始 bytes；完成后再更新 Request baseline manifest。同步不得夹带未批准 CR 的 action registry、认证、安全 Profile、Provider 或 production 事实。

## 6. 验收 Gate

### 6.1 离线合同与单元 Gate

- OpenAPI/DTO 精确验证各 endpoint 保持自身 Supplier 字段集合、统一 `tax_number` 值语义、SUPP-003 额外字段拒绝、`reused` 必填布尔和三个新增错误码；`reused=true` 的嵌套 active 与顶层 candidate 版本归属不得混淆，路由数仍为 122。
- 覆盖三个合法状态组合、确认元数据不变量和全部非法组合；active/inactive 目标、客户端 status/source/USCC/confirmed metadata、confirmed 缺名称或税务身份、null 清空及 no-op 全部失败关闭。
- `ContractTaxConfirmed/InvoiceTaxConfirmed` 覆盖 AI/PATCH 不成立、CON-005/INV-005 成立、JSON 类型/值/confirmed metadata 不匹配、税号后续改变即失效；只有锁内当前持久证据可触发复用。
- 覆盖 only-USCC、only-tax、双列相同、双列不同、generic 与 typed USCC 冲突；generic 值大小写/Unicode 按保存 bytes 精确，不做推断。
- AI 固定 JSON fixture 覆盖合同乙方、发票销售方、甲方/购买方误用、18 位 USCC 外观、null、无名称、无证据/非法/冲突值；全程不得打开 socket。
- 单条/多字段/激活/拒绝/复用各自恰一条 `supplier_field`；before/after 同键、实际差异、返回 ID、source_supplier_id、`caused_outdated` 和 no-op 零记录全部精确；双角色 actor 使用服务端固定优先级。
- `supplier-update-summary-v1` 封闭键、field/hash/mask 等式和本文固定向量逐字通过；任何原值、extra key、数组乱序或 hash/mask 漂移失败关闭。
- 约束名到错误码映射只接受两个精确 constraint name；未知 IntegrityError 脱敏 fail closed。
- 权限矩阵、关联对象裁剪、404/随机不存在等价、每次授权拒绝恰一条独立 denied log、业务回滚无 success log，以及错误/日志/Trace/测试报告 secret scan 通过。

### 6.2 专用 PostgreSQL 16 Gate

- 仅使用显式、安全、可丢弃、全合成数据的 PostgreSQL 16；不得读取真实 `.env` 或生产数据。
- 同一来源 resolver 重复/并发执行最多保留一个未删除 candidate；不同来源同税号候选允许并存，名称不触发合并。
- 来源已存在 candidate 时，后续 CON/INV 确认不得静默覆盖、退役或直接复用；必须经 SUPP-003 显式处理。
- candidate 已预先改成最终税号、来源随后确认同值时，status-only 确认成功；candidate 与来源当前确认税号不同时，status-only 确认为 `SUPPLIER_TAX_IDENTITY_CONFLICT`；省略名称时沿用 candidate 当前值，不扫描历史变化。
- 两个不同候选并发确认同一税号：一个 `confirmed/active`，另一个 `rejected/inactive` 且 `200 reused=true`；两个来源都绑定同一活动供应商。
- 同一候选两个旧 row_version 请求最多一个成功；输家 `RESOURCE_VERSION_CONFLICT`，无部分写入。
- 名称缺失不建占位候选；补名后可建候选；人工确认税号命中活动 supplier 时可直接回填。
- candidate/source/active/确认元数据的版本矩阵逐行断言；source 在同一 CON/INV PATCH 中总共只增一次，复用 active 零 UPDATE。
- generic tax 与 typed USCC 不同、来源已绑定不同身份、跨组织脏关系、未知约束、correction/log/outbox 故障全部原子回滚；A 组织请求 B 资源与随机不存在 ID 对外等价，两组织业务表均零写入。
- supplier、source_supplier_id、版本、correction、success/denied operation log 和实际触发的 outbox/过期事实事务边界逐项检查。
- raw PostgreSQL exception 只作为敏感内存 fixture；HTTP、应用错误、stdout/stderr、operation log、Trace、指标、Outbox 和测试报告中搜索完整合成税号/USCC必须零命中，不把 fixture/业务表/user_corrections 误计为泄漏。

### 6.3 工程 Gate 与未运行边界

- Ruff、格式、mypy、Backend 全量 pytest、Frontend test/typecheck/build、静态资产和本地离线门全部通过。
- 若 CR-012 三表、user_corrections、operation_logs、Auth/RBAC 或安全 TEST_DATABASE_URL 任一缺失，相关集成/API/E2E 必须为 `NOT_RUN`，不能用 SQLite/Mock 冒充 PostgreSQL 16 或真实鉴权。
- Browser、Docker、Provider、remote CI、production、真实数据迁移均需各自证据；本 CR 审批不替代。

## 7. 审批与生效边界

### 7.1 严格依赖证据

CR-015-R2 只能在 CR-012-R3 已完成以下全部步骤后批准，不允许同一审批批次、条件批准、追认或占位证据：

1. CR-012-R3 已以 `decision_snapshot_sha256=b9d789568dd5b813c5fff4da03a823b922fc263245aeb01e53655b51ba1179c0` 明确批准。
2. 该批准已授权并完成九份精确 Request 文件的原子同步。
3. 同步证据包含九个路径各自的 pre/post raw SHA-256、成功结果和同步后的 baseline manifest SHA-256。
4. CR-012 批准证据、同步证据和 post-sync manifest 均已存在且可复核，时间顺序严格满足 `CR-012 approved_at < CR-012 synced_at < CR-015 approved_at`。

任一证据缺失、使用占位符、revision/hash 不同、文件数不是 9、部分同步、同步失败或时间顺序不满足时，CR-015 保持 `NOT APPROVED`。本 CR 必须由需求/产品、架构、数据/数据库、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性和安全角色共同批准 FINR-D-001～008；同一自然人具备多个角色权限时可沿用已生效 CR-001/002 先例合并一条 Markdown 记录，但仍须逐项列出全部角色、决策、依赖证据和 delta，不引入未批准的 cryptographic registry/pin。

### 7.2 规范性审批模板

下列字段名、固定值和顺序属于本 CR 的静态审批合同。占位符必须在批准前替换为真实值；含任一占位符、角色/决策缺失或固定值不同的文本不构成批准。实际批准消息及其逐字记录只能写入第 8 节动态状态，不进入 decision preimage。

```text
我，YHBX（BOSS），以需求/产品、架构、数据/数据库、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全全部必需审批角色，APPROVED CR-015-R2。

decision=APPROVED；
selected_decisions=FINR-D-001,FINR-D-002,FINR-D-003,FINR-D-004,FINR-D-005,FINR-D-006,FINR-D-007,FINR-D-008；
cr_revision=CR-015-R2；
decision_snapshot_sha256=<CR-015-R2冻结后复算的64位小写SHA-256>；

dependency_revision=CR-012-R3；
dependency_snapshot_sha256=b9d789568dd5b813c5fff4da03a823b922fc263245aeb01e53655b51ba1179c0；
dependency_approval_result=APPROVED；
dependency_approval_evidence_link=<CR-012-R3批准记录链接>；
dependency_request_sync_result=APPLIED_AND_VERIFIED；
dependency_request_file_count=9；
dependency_request_sync_evidence_link=<CR-012-R3九份Request原子同步证据链接>；
dependency_post_sync_baseline_manifest_sha256=<同步后baseline manifest的64位小写SHA-256>；

api_path_delta=0；
core_table_delta=0；
alembic_migration_delta=0；
operation_log_action_delta=0；
p0_work_item_delta=0；
api_error_code_delta=+3；
correction_type_delta=+1:supplier_field；

environment_scope=contract；
network_scope=none；
production_release_scope=none；
request_sync_scope=exact_nine_Request_files；
approved_at=<晚于CR-012 synced_at的RFC3339 UTC时间>；
日期=<YYYY-MM-DD>；
证据链接=本 Codex task 当前批准消息；
备注=批准 FINR-D-001～FINR-D-008，并授权按本 CR 原子同步九份 Request，以及在全部前置依赖就绪后实施离线代码和专用全合成 PostgreSQL 16 验证；不授权提前创建 CR-012 三表或其他未批准 migration，不授权真实数据导入或清理、Provider、fixed_test_provider、内部 vLLM 或其他网络调用，不授权部署、canary 或 production 放行。
```

### 7.3 快照与授权边界

`decision_snapshot_sha256` 计算规则：严格 UTF-8 解码并拒绝 BOM、非法序列、NUL 或替换字符；把 CRLF 与孤立 CR 规范化为 LF；定位内容完全等于 `## 8. 当前状态` 的唯一标题行；取其前全部内容，移除末尾全部 LF 后追加恰好一个 LF；编码为 UTF-8 无 BOM并计算 SHA-256 小写 64 hex。不做 Unicode normalization、trim 或 Markdown 重排。

生成 review snapshot 只建立可签署对象，不等于批准。CR-012 的批准、同步与 post-sync 证据全部验证后才可签署 CR-015；CR-015 获批后还须原子同步九份 Request，只有这些事实和实际代码依赖都完成后，才可启动本地离线实现/专用 PG16 验证。任何 Provider 网络、真实数据、部署或 production 仍需独立授权。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| GAP-064 推荐合同 | `PROPOSED` |
| decision snapshot | `GENERATED FOR REVIEW；preimage_bytes=37953；decision_snapshot_sha256=9682e039971c0e922b847b370f64b961af382d7be1b8f31a59e8f1c8733fff77；NOT APPROVED` |
| CR-012-R3 依赖 | `APPROVED / SYNCED` |
| CR-012-R3 批准证据 | `APR-20260809-YHBX-CR012；见 CR-012-R3 第 8.1～8.2 节` |
| CR-012-R3 九 Request 同步证据 | `CR-012-R3 第 8.3 节九份 raw identity；docs/baseline-manifest.md` |
| CR-015-R2 approval | `NOT APPROVED` |
| Request 同步 | `NOT AUTHORIZED` |
| SUPP-003/CON-005 runtime | `BLOCKED UNTIL APPROVAL AND DEPENDENCIES` |
| Provider/fixed_test_provider/internal vLLM network | `NOT AUTHORIZED` |
| 真实数据、部署、canary、production | `NOT AUTHORIZED` |
