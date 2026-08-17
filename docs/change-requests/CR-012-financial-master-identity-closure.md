# CR-012-R3：合同、发票与供应商主数据身份合同闭合

状态：**DRAFT / PROPOSED / NOT APPROVED**

日期：2026-08-08

对应差异：GAP-063

## 1. 变更原因

`contracts`、`invoices` 与 `suppliers` 形成循环外键，是 `20260807_005` 之后最接近可独立交付的 BASE-005 切片。三表的大部分列、枚举和父表依赖已经明确，但当前 Request 仍不能唯一生成合同编号与供应商税务身份的唯一索引：条件是否包含软删除/状态、两个税号列是否互斥或跨列去重、输入如何规范化，以及 `suppliers.source_type/status` 是否允许 NULL 均未冻结。

这些选择会直接改变并发写入、候选供应商去重、历史身份复用和用户看到的冲突结果，不能由 migration 或 Repository 私自决定。本 CR 只闭合三表 DDL 身份边界以及唯一约束必需的存储投影，不批准文件解析、AI 提取、供应商确认/复用流程、合同发票匹配、业务 API 运行时或 AC 通过。正式 Request 中数据库冲突到 API 错误的映射、供应商读模型、`SUPP-003` 纠错记录、状态转换、精确身份复用与 AI 双来源列投影仍存在独立运行时差异，记录为 GAP-064，不构成 `20260807_006` 的前置条件，也不得被本 CR 冒充为已冻结。

## 2. 范围与非目标

### 2.1 推荐冻结

1. 合同编号的空值、规范化、唯一范围和软删除语义。
2. 供应商统一社会信用代码/税号的单一身份表示、候选缺值边界、唯一范围和规范化。
3. `suppliers.source_type/status` 的 NOT NULL/default 与来源引用矩阵。
4. 三表循环外键的创建/回退顺序和非空降级保护。

### 2.2 不在本 CR 范围

- 不新增第 58 张或更多身份表，不改变 CR-001-R2 的 57 表正式基线。
- 不冻结税务标识的行政真实性、校验位或外部核验；P0 只做存储和确定性相等比较。
- 不创建默认合同、发票、供应商或任何业务种子。
- 不实现 CON-001、INV-001、CON-005、文件链、AI、操作日志或任何 AC。
- 不冻结 `SUPP-003` 的纠错记录形状、`confirmation_status/status` 状态转换、来源对象回填、并发冲突人工解决或现有 AI generic tax 字段到双来源列的映射；这些边界由 GAP-064 跟踪。
- 不授权 production migration 或数据清洗；历史真实数据迁移需独立评估。

## 3. 推荐合同

### 3.1 FIN-D-001：规范字符串与空值

PostgreSQL `server_encoding` 必须为 `UTF8`。三个字段只接受 `null` 或已经规范化的非空字符串，规范形式固定为：

1. `contract_no` 与 generic `tax_number` 允许任意有效 UTF-8 scalar value，但禁止 U+0000～U+001F、U+007F～U+009F；去除两端 ASCII space 后必须非空，存储值不得含首尾 ASCII space。不做 Unicode normalization、音译、大小写转换或字符替换。
2. `unified_social_credit_code` 只允许非空 ASCII `0-9/A-Z`；可信输入边界只把该字段的 ASCII 小写转换为 uppercase，不把 generic `tax_number` 强制改写为中国境内格式。
3. 数据库 CHECK 使用 `value = btrim(value, ' ')` 和显式 Unicode code-point control range；PostgreSQL 本身拒绝 NUL 与 surrogate。合同编号、generic 税号及双列相等判断都使用显式 `COLLATE "C"` 按保存值精确比较。
4. Migration 不静默改写已有值；未来导入发现非规范值时必须拒绝并进入显式纠错流程。

数据库使用等价于下式的 CHECK 保证已存 generic 值符合规范；`unified_social_credit_code` 另加 `(value COLLATE "C") ~ '^[0-9A-Z]+$'`：

~~~sql
value IS NULL OR (
  (value COLLATE "C") <> ('' COLLATE "C")
  AND (value COLLATE "C") = (btrim(value, ' ') COLLATE "C")
  AND (value COLLATE "C") !~ U&'[\0001-\001F\007F-\009F]'
)
~~~

这里的规范化只为稳定相等比较，不声明税务标识在行政上有效。

### 3.2 FIN-D-002：合同编号唯一性

合同编号为空时允许多个合同；非空时在组织内跨全部业务状态、仅对未删除记录保持唯一：

~~~sql
CREATE UNIQUE INDEX uq_contracts_organization_contract_no
ON contracts (organization_id, (contract_no COLLATE "C"))
WHERE contract_no IS NOT NULL
  AND deleted_at IS NULL;
~~~

`draft/active/expired/terminated/archived` 的未删除合同都占用编号；软删除释放编号，因为当前 P0 没有 restore/unarchive/merge 入口。数据库必须以固定索引名识别唯一冲突，但 API 状态码、业务错误码和响应投影由 GAP-064 另行冻结。该规则是组织内未删除合同的业务身份政策，不以 UUID 外键完整性作为理由。

### 3.3 FIN-D-003：供应商单一税务身份

P0 选择“单一规范税务身份值、两个来源字段”表示：`unified_social_credit_code` 与 `tax_number` 可以任一非空，也可以同时非空，但同时非空时规范值必须逐字相同。这与 SRS 模拟供应商同时给出相同统一社会信用代码和税号兼容，不把同一法定身份误当成两个标识。允许尚未提取到税务身份的 `candidate/inactive` 暂时两者都为空；`active` 至少一个非空。若未来确需在同一供应商保存两个不同标识，应另提 CR 并评估规范化子表及正式表数，不能在本切片内增加隐藏表。

~~~text
candidate/inactive: zero, one, or two equal source values
active: one value, or two equal source values
never: both columns non-null with different normalized values
~~~

数据库必须用 C collation 冻结双列同值约束：

~~~sql
CHECK (
  unified_social_credit_code IS NULL
  OR tax_number IS NULL
  OR (unified_social_credit_code COLLATE "C") = (tax_number COLLATE "C")
)
~~~

数据库唯一索引使用的统一身份表达式固定为 `COALESCE(unified_social_credit_code, tax_number)`。只有已批准的输入合同能够明确区分统一社会信用代码时才允许同时或单独写 `unified_social_credit_code`；当前 AI 的 generic `party_b_tax_id/seller_tax_id` 不得按长度、字符形状或模型文字猜测字段类型，具体写入与读取投影由 GAP-064 关闭后才能实现。本 CR 不冻结 SUPP-001～003 输出，也不增加未批准的 `identity_kind` 字段。

本 CR 只要求任何未来写路径原子保持“双列同时非空时逐字相同”和“active 至少一个身份值”两项数据库不变量，不定义 `SUPP-003` 如何把 generic `tax_number` 投影到两列，也不定义 `user_corrections` 的 `correction_type/field_path/before_value_json/after_value_json`。正式 Request 当前缺少 supplier correction 类型且响应只有单一 `correction_id`；在 GAP-064 获批并同步前，不得实现或声称验收 `SUPP-003`，但该缺口不阻断空表三表 DDL。

唯一约束只覆盖未软删除的 `active` 供应商，与 SUPP-003 已冻结的“其他活动供应商”冲突语义一致：

~~~sql
CREATE UNIQUE INDEX uq_suppliers_organization_tax_identity
ON suppliers (
  organization_id,
  (COALESCE(unified_social_credit_code, tax_number) COLLATE "C")
)
WHERE status = 'active'
  AND deleted_at IS NULL
  AND COALESCE(unified_social_credit_code, tax_number) IS NOT NULL;
~~~

数据库层只冻结：第二个候选激活时若已有同身份活动供应商，唯一约束必须原子拒绝，任何部分字段更新均回滚。该行为不得覆盖正式 Request 已有的“税号精确匹配可复用供应商”要求；创建前复用、来源对象回填、并发输家处理和人工解决入口属于 GAP-064/CON-005 的运行时合同，本 CR 既不把 409 冒充完整解决路径，也不批准自动合并或历史改写。inactive 或软删除行不占用活动身份；任何重新激活都必须重新通过同一唯一约束。名称不参与硬唯一，避免同名不同主体被错误合并。

### 3.4 FIN-D-004：供应商状态与来源

- `source_type VARCHAR(30) NOT NULL`，无数据库默认，只允许 `contract/invoice/manual`。
- `status VARCHAR(20) NOT NULL`，无数据库默认，只允许 `candidate/active/inactive`；服务创建候选时显式写 `candidate`。
- `source_type='contract'`：`source_contract_id` 必填且 `source_invoice_id` 为空。
- `source_type='invoice'`：`source_invoice_id` 必填且 `source_contract_id` 为空。
- `source_type='manual'`：两个来源外键都为空。
- 来源外键使用默认 `NO ACTION`，不得 `CASCADE` 删除供应商或来源事实。

本 CR 不新增或冻结自动状态转换。候选确认/拒绝所需的状态组合、操作日志和完整决策证据必须按当前 Request 及对应业务任务另行闭合；任何 action registry 变化须独立批准并同步，不构成本 CR 或 `20260807_006` 的前置条件。

### 3.5 FIN-D-005：三表同一 revision

`contracts`、`invoices`、`suppliers` 必须在同一线性 revision 创建：先创建三张表和指向既有 `organizations/users` 的外键，再以 `ALTER TABLE` 添加循环外键：

~~~text
contracts.supplier_id          -> suppliers.id
invoices.supplier_id           -> suppliers.id
suppliers.source_contract_id   -> contracts.id
suppliers.source_invoice_id    -> invoices.id
~~~

全部外键使用 `NO ACTION`。不得为绕过循环而省略正式外键、使用占位父表、`CASCADE`、禁用约束或把 PostgreSQL 事实转移到 Redis/应用内存。

### 3.6 FIN-D-006：降级安全

执行任何真实环境 downgrade 前，部署流程必须先进入维护模式、停止 Backend 新写入、排空 Worker 写任务并确认无活跃业务写事务；这仍不替代独立 production 放行。Downgrade 在同一事务先执行 `SET LOCAL lock_timeout = '5s'`，再按固定字典序取得 `contracts`、`invoices`、`suppliers` 的 `ACCESS EXCLUSIVE` 锁；任一锁超时即完整失败退出。取得全部锁后，任一表非空时以 SQLSTATE `55000` 原子拒绝，保留三表、全部数据和 Alembic revision；全部为空时先删除四个循环外键，再按依赖安全顺序删除三表。禁止 `CASCADE`。

## 4. 已冻结且不变的合同

- 三表的字段类型、M1 公共字段以及合同/发票 `confirmation_status`、业务状态和发票重复状态枚举继续以 Request 数据库设计第 4.2、5.3 节为准。
- 合同金额非负、到期日不早于生效日；发票号不建硬唯一，重复事实必须保留。
- 发票重复检索索引继续使用 Request 已定义的活动谓词。
- 本 CR 不改变 PostgreSQL 是业务事实唯一来源，也不改变 57 表正式基线。

## 5. 同步与兼容策略

获批后必须原子同步九份 Request：需求、架构、数据库、API、页面、AI/RAG、测试、部署和开发计划。同步只写入本 CR 已冻结的 DDL/存储事实，并明确 GAP-064 仍阻断所有 API 错误映射、供应商读写投影和业务运行时；不得顺带猜测候选确认、纠错、复用或 AI 输入投影。部署必须同步三表锁顺序、非空回退阻断与恢复手册。同步时要明确：

1. `supplier_identity_kind` 不新增为数据库列；数据库只保存 `unified_social_credit_code/tax_number` 两个来源列并允许同时保存同一规范值，任何 API 统一投影继续由 GAP-064 阻断。
2. 本 CR 不改变“税号精确匹配可复用供应商”，但 GAP-064 关闭前不得实现候选复用、来源回填或 `SUPP-003`；数据库唯一冲突不是完整业务解决路径。
3. 合同编号和供应商身份的数据库唯一冲突不得在本 CR 中映射为具体 HTTP 状态、业务错误码或响应字段；这些运行时事实由 GAP-064 另行冻结。
4. 现有非规范或重复真实数据不得由 migration 自动合并；先出只读报告并由数据负责人批准清理方案。
5. 未获 production migration 批准前，只允许空库/合成数据验证。

回滚保持三表同时存在或同时为空，不允许留下缺失循环外键的半升级状态；部署文档必须包含维护模式、Backend/Worker drain、5 秒锁超时、失败观察和恢复步骤。

## 6. 验收 Gate

### 6.1 `20260807_006` migration/ORM Gate

- ORM、migration 与 PostgreSQL catalog 精确核对三表列、nullable/default、枚举 CHECK、M1、索引和全部 FK。
- 合同编号覆盖 null、空字符串拒绝、首尾空格、Unicode control、大小写/Unicode exactness、并发重复、archived 仍冲突和 soft-delete 后允许复用。
- 供应商覆盖无身份 candidate、active 缺身份、双列 C-collation 同值/异值、generic Unicode 税号、USCC ASCII uppercase、candidate/inactive/soft-delete 不占用活动身份、重新激活冲突和同名不同身份。
- 两个事务以同一规范身份并发激活供应商时必须恰一提交；另一事务因唯一约束失败且不得留下字段、状态或来源关系的部分更新。数据库异常、迁移输出和测试日志不得回显原始税号或冲突供应商内容。
- 来源矩阵按三种 `source_type` × 无来源/仅合同/仅发票/双来源共 12 种组合覆盖；contract/invoice 缺来源或双来源失败，manual 只有双来源为空时通过。
- 发票重复号可保存，活动重复检索索引可命中，不能误建唯一约束。
- Migration 启动先执行 `SHOW server_encoding;` 并断言结果精确为 `UTF8`；静态配置与专用数据库分别覆盖 UTF8 通过和非 UTF8 fail closed。
- Upgrade 在创建三表以及添加四个循环 FK 的各阶段执行故障注入；任一异常后事务必须完整回滚，Alembic revision 仍为 `20260807_005`，三表和四个循环 FK 均不存在。
- 空表 `head -> previous -> head` 可重复；任一表非空时 downgrade 原子失败并保留 revision。
- 第二连接分别持有三表中任一冲突锁超过 5 秒时，downgrade 必须因 `lock_timeout` 原子失败，三表、循环外键和 Alembic revision 全部保留；不得无限等待或继续删除剩余对象。
- Ruff、格式、mypy、全量 pytest、Alembic 单一 head 和安全 PostgreSQL 16 往返通过。
- 未配置安全 `TEST_DATABASE_URL` 时 PostgreSQL 运行证据必须为 `NOT_RUN`，不得用离线 SQL 替代。

### 6.2 后续供应商运行时 Gate（不阻断 `20260807_006`）

- 在 GAP-064 获批并同步前，`SUPP-003`、CON-005 的供应商确认/复用路径和 AI generic tax 输入投影全部为 `NOT_RUN`。
- 后续合同必须唯一冻结 supplier correction 枚举、单一 `correction_id` 对应的字段路径和 before/after JSON 形状，以及同一请求同时修改名称与税务身份时的记录语义。
- 后续合同必须唯一冻结候选创建、确认、拒绝、停用与重新激活的 `confirmation_status/status` 组合，并明确 `status` 是否可由客户端直接写入。
- 后续合同必须覆盖精确身份预复用、来源对象回填、并发输家人工处理、旧 `row_version` 无部分写入，以及响应、异常、日志不回显原始税号或其他供应商内容。

## 7. 依赖与审批边界

本 CR 必须由需求、架构、数据、后端/API、前端/UI、AI、测试、运维和安全角色共同批准；运维在 contract 范围签署 FIN-D-006 的锁、回退和恢复可实施性，但这不构成 production 放行。涉及真实历史数据清理或 production migration 时，还需独立的数据迁移专项与 production 审批。合同签署授权九份 Request 同步、空表 DDL 与离线/专用测试库验证，不授权 `SUPP-003`/CON-005 业务运行时、真实数据导入或 production，也不批准任何未生效的 action registry 候选。

审批记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_option / cr_revision / decision_snapshot_sha256 / environment_scope=contract / 日期 / 证据链接 / 备注`。任一角色留空或选择互不兼容时保持 `NOT APPROVED`。

`decision_snapshot_sha256` 计算规则：全文行尾规范化为 LF，定位内容完全等于 `## 8. 当前状态` 的标题行，取该行之前的全部行并在末尾保留恰好一个 LF，对 UTF-8 bytes 计算 SHA-256 小写十六进制。首次快照生成后，任何规范性修改都必须提升 revision、重新计算 hash 并重置签署。

生成初始 decision snapshot 只建立可签署对象，不等于批准。当前没有审批记录，不得把推荐合同写入 Request 或生成 006 migration。

## 8. 当前状态

全部必需签署项已由 `APR-20260809-YHBX-CR012` 在 `environment_scope='contract'` 范围明确批准。以下记录只位于决策快照之外的可变区；第 1～7 节及其 `decision_snapshot_sha256` 保持不变。

| 决策 | 需求负责人 | 架构负责人 | 数据负责人 | 后端/API 负责人 | 前端/UI 负责人 | AI 负责人 | 测试负责人 | 运维负责人 | 安全负责人 |
|---|---|---|---|---|---|---|---|---|---|
| FIN-D-001 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |
| FIN-D-002 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |
| FIN-D-003 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |
| FIN-D-004 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |
| FIN-D-005 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |
| FIN-D-006 | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] | APPROVED [APR-CR012] |

### 8.1 APR-20260809-YHBX-CR012

| 字段 | 批准记录 |
|---|---|
| 姓名 | YHBX（BOSS） |
| 角色 | 需求负责人、架构负责人、数据负责人、后端/API 负责人、前端/UI 负责人、AI 负责人、测试负责人、运维负责人、安全负责人；审批人已明确声明具备全部必需审批权限 |
| 决策 | APPROVED |
| selected_option | 批准 FIN-D-001～FIN-D-006，以及第 5～7 节规定的同步、Gate 和审批边界；采用 CR-012-R3 的推荐合同，不采用未列明备选 |
| cr_revision | `CR-012-R3` |
| decision_snapshot_sha256 | `b9d789568dd5b813c5fff4da03a823b922fc263245aeb01e53655b51ba1179c0` |
| environment_scope | `contract` |
| 日期 | 2026-08-09 |
| 证据链接 | 当前 Codex task 中用户对上述 revision、snapshot、九角色、决策范围和环境边界的明确审批声明 |
| 备注 | 只授权九份 Request 原子同步、`20260807_006` 空表 DDL/ORM 实施，以及离线/专用合成 PostgreSQL 16 验证；不授权 `SUPP-003`/CON-005 运行时、真实数据导入或清理、Provider 或其他网络调用、部署/production 放行，也不批准任何未生效 action registry 候选 |

### 8.2 批准生效与同步边界

- 批准日期：2026-08-09。
- `CR-012-R3` 的 FIN-D-001～FIN-D-006 已在 `contract` 范围获批；页首 `DRAFT / PROPOSED / NOT APPROVED` 与第 1～7 节中的待审批措辞属于已签署决策快照，不得在不提升 revision 并使本批准失效的情况下改写，当前动态状态以本节为准。
- 九份 Request 已按第 5 节完成全有或全无的原子同步；逐文件 raw identity 见第 8.3 节。`20260807_006` 空表 DDL/ORM 已实现，并在本地一次性合成 PostgreSQL 16.14 上连续两轮以 26/26 项通过 current-head Gate；实施证据见第 8.4 节。该结果只覆盖当前 10/57 表，不表示完整 BASE-005、P0 或任何 AC 已完成，也不授权 GAP-064 运行时、真实数据、Provider/其他外网、部署或 production。
- GAP-064 继续独立阻断数据库冲突到 API 错误的映射、供应商读写投影、`SUPP-003`、CON-005 确认/复用、来源回填和 AI generic tax 输入投影；本批准不缩小该阻断。

| 项目 | 状态 |
|---|---|
| GAP-063 合同 | `CLOSED；APPROVED；APR-20260809-YHBX-CR012` |
| decision snapshot | `APPROVED；decision_snapshot_sha256=b9d789568dd5b813c5fff4da03a823b922fc263245aeb01e53655b51ba1179c0` |
| Request 同步 | `COMPLETED / POST-SYNC IDENTITIES RECORDED` |
| BASE-005 `20260807_006` 三表 migration/ORM | `IMPLEMENTED / LOCAL-SYNTHETIC PG16 GATE PASS` |
| BASE-005 总体 | `PARTIAL / 10 OF 57 TABLES` |
| 供应商运行时 / GAP-064 | `OUT OF SCOPE / BLOCKED / NOT AUTHORIZED` |
| 真实数据清理 | `NOT AUTHORIZED` |
| production migration | `NOT AUTHORIZED` |
| Provider / 其他网络调用 / 部署 | `NOT AUTHORIZED` |
| 未生效 action registry 候选 | `NOT AUTHORIZED` |

### 8.3 Request 原子同步证据

下列 identity 是 2026-08-09 同步完成后的 strict UTF-8、无 BOM、LF-only raw bytes；九份文件全部存在且各自只含一条 `CR-012-R3 / 2026-08-09` 修订记录。后续任一文件变化都必须重新核对其领域投影，不得继续复用本表宣称同步完成。

| Request 文档 | byte length | raw SHA-256 |
|---|---:|---|
| `FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 124040 | `4a4f431a421a89b72c9586b5eb0e4b154856713dbb38f83e42456e568bf5e308` |
| `FinAudit_Agent_系统架构设计说明书_V1.0.md` | 85605 | `5965ac96480919a3d5ac46c4a20e3fbeda5fbdc39fc6fb36cab06359c27352dc` |
| `FinAudit_Agent_数据库设计说明书_V1.0.md` | 109489 | `4e3d540fc345ce2b155e84fd862d9a3d3d98f119c80180c693df4367efb1942d` |
| `FinAudit_Agent_API接口设计说明书_V1.0.md` | 324511 | `fa277147a8af6f5d5d0f96bd34170440f2b55be8450aa1f49a845b13e69ac4d0` |
| `FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 80792 | `d5c53be941ce45652111f7a75dcca93426dbc5d915a64a14fbdd37f5c5d96e89` |
| `FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 48655 | `f83e4e41ed1a3a51909a745f4726a16243295c3164879143b7ef0e04c9d270fe` |
| `FinAudit_Agent_测试与验收方案_V1.0.md` | 46602 | `5471739020734eb1fad0c9c4e493d46ac5d4f6a372b23b1b46ae691342fa91c3` |
| `FinAudit_Agent_部署与运维说明书_V1.0.md` | 51144 | `c3526c75899dd136db1369a2b420972b5a2f70f8640b977ca22d9502c8193e2f` |
| `FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 103607 | `7a032de9a6fefdb01877d865746715ccb8ef39c449b6d69b14cb403be2be8bae` |

同步机械复核结果：`REQUEST_SYNC_STATIC=PASS files=9`。该结果不授权 GAP-064 运行时、真实数据、Provider/其他网络、部署或 production。

### 8.4 `20260807_006` 实施与验证证据

- 实施文件：`backend/alembic/versions/20260807_006_create_financial_master_data.py`、`backend/app/models/financial.py` 及对应单元/集成测试；migration 只创建空的 `contracts/invoices/suppliers` 且不播种业务行，集成测试仅在可丢弃数据库中写入专用合成行并随重建清除。
- 显式验证入口：`scripts/verify-postgresql-current-head.ps1`；使用本机缓存 `postgres:16-alpine`、随机 loopback 端口、一次性随机凭据、tmpfs 和可丢弃合成数据库，不读取 `.env`、不拉取镜像。
- 实测服务端：PostgreSQL 16.14，`server_version_num=160014`；连续两轮完成 `base → head → base → head`，两轮均为 26/26 项通过并输出 `POSTGRESQL_CURRENT_HEAD=PASS`，标记容器残留数为 0。
- 证据边界：`BASE-005` 仍为 `PARTIAL / 10 OF 57 TABLES`，`TEST-001` 仍为 `PARTIAL / S1-S9`，GAP-064 保持开放；默认离线编排仍将 PostgreSQL current-head 标为 `NOT_RUN`。真实数据、Provider/其他外网、部署和 production 均为 `NOT_AUTHORIZED / NOT_RUN`，没有任何 AC 因本次实施完成。
