# CR-010-R1：Scanner Registry Profile 合同闭合

合同修订：`CR-010-R1`；权威生命周期状态仅见第 8 节。

日期：2026-08-07

对应差异：GAP-055

## 1. 变更原因

CR-005-R1 与 CR-007-R1 都要求数据库独立验证 Scanner Profile、Registry、Adapter、Scanner、Definition 和 outcome，不能信任 Worker 自报、应用常量或环境变量。现行草案却把共享 `validate_scanner_registry_v1` 的 ownership 交给 CR-007，同时 CR-005 已把同名函数冻结为第二个消费者；此外，单个只校验调用方 tuple 的函数无法区分“本数据库当前环境 Profile”与“曾经激活、仅供历史复核的 Profile”。

如果把每份历史 Profile 直接硬编码进环境专属函数，每次轮换都要改函数体和迁移，容易误删历史分支，也无法用数据库行锁把 Profile 切换与新 Job 输入冻结串行化。因此本 CR 推荐一张最小技术表作为当前/历史 Profile 的数据库事实来源，由 CR-010 唯一拥有共享 validator；CR-005/007 只拥有各自 consumer trigger。

本文件只提出可评审合同，不批准任何 Scanner 产品、版本、签名库、地址、路径、镜像、凭据、真实 Profile bytes 或 production 配置，也不授权 Request 同步、migration、网络调用或 production 放行。

## 2. 范围、delta 与非范围

本 CR 推荐冻结：

- `scanner-registry-profile-v1` 的精确 JSON、排序、JCS/hash 和环境隔离。
- 当前 Profile 与已激活历史 Profile 的不同验证语义。
- `public.scanner_registry_profiles` 技术表、共享函数、生命周期、所有权和 downgrade。
- CR-005/007 consumer 的兼容边界和 Profile 轮换时的长任务语义。

决策编号固定为：

| 决策 | 推荐合同 |
|---|---|
| `SCANREG-D-001` | Profile 封闭 Schema、排序、JCS 与 hash |
| `SCANREG-D-002` | 五类环境隔离与永久数据库 class 绑定 |
| `SCANREG-D-003` | 具体 Profile 独立批准 artifact 与外部记录 |
| `SCANREG-D-004` | 技术表、installed/current/historical 生命周期与不可变性 |
| `SCANREG-D-005` | current/history、兼容 wrapper 与 Asset 唯一 selector validator |
| `SCANREG-D-006` | activation 全局串行锁、expected-current CAS 与 Job 锁顺序 |
| `SCANREG-D-007` | revision ownership、权限与 fail-closed downgrade |
| `SCANREG-D-008` | CR-005/007 consumer 兼容与无环实施边界 |

本 CR 的 `core_table_delta=+1`、`api_delta=0`，锚定 2026-08-07 已同步 CR-001-R2/CR-002-R4 后的 57 张核心表、122 个 API，以及 `docs/baseline-manifest.md` SHA-256 `717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41`。只应用本 CR 时核心表为 58；最终总数必须以同步时有效基线加全部已批准 CR delta 累加，禁止与 CR-006 或其他 CR 各自硬编码“第 58 张表”。

本 CR 不决定或授权：

- 真实 Scanner 产品、adapter、版本、签名库版本、endpoint、可执行文件、镜像、license、Token、密码、私钥或 secret。
- `fixed_test_provider` 的任何网络调用；本 CR 的 `fixed_test` 只表示不打开 socket 的确定性 Scanner test double。
- 任一环境 Profile 的具体 JCS bytes/hash、安装、激活或轮换。
- production 启用、部署、数据迁移、Request 改写、CR-005/007 批准或业务 runtime。

## 3. `scanner-registry-profile-v1`

### 3.1 顶层对象

JCS 输入对象只允许四个顶层键，全部必填，禁止未知键：

```json
{
  "entries": [],
  "profile_class": "local_offline",
  "registry_version": "<APPROVAL_REQUIRED>",
  "schema_version": "scanner-registry-profile-v1"
}
```

示例只说明形状；`<APPROVAL_REQUIRED>` 不是合法运行值。字段合同为：

| 字段 | 精确合同 |
|---|---|
| `schema_version` | 精确为 `scanner-registry-profile-v1` |
| `registry_version` | 匹配 `[a-z0-9][a-z0-9._-]{0,99}`；不得使用 `current/latest/default/unknown` 或占位符；同一值只能对应一份 JCS bytes |
| `profile_class` | 精确为 `contract/local_offline/fixed_test/staging/production` 之一 |
| `entries` | 0 个或多个第 3.2 节对象；按固定 comparator 排序且不得重复 |

Profile 必须满足 I-JSON；字符串不得含控制字符，不做 Unicode normalization。Profile 中禁止 endpoint、URL、文件路径、镜像凭据、license、secret、原始签名数据或 Scanner 原始输出。

### 3.2 条目、outcome 与排序

每个条目只允许以下五个键，全部必填，禁止未知键：

```json
{
  "adapter_code": "<APPROVAL_REQUIRED>",
  "allowed_definition_versions": [],
  "allowed_scan_outcomes": ["not_configured"],
  "definition_version_mode": "null_only",
  "scanner_version": "<APPROVAL_REQUIRED>"
}
```

- `adapter_code` 匹配 `[a-z][a-z0-9_.-]{0,63}`；禁止 `unknown/default/current/latest`。
- `scanner_version` 是 1～100 个可打印 ASCII 字符的精确非空值，首尾无空白；禁止范围、通配符、`latest` 或环境变量替代。
- `definition_version_mode` 只允许 `required_exact/null_only`。
- `required_exact` 要求 `allowed_definition_versions` 至少一项；每项是 1～200 个可打印 ASCII 字符的精确非空值，首尾无空白、无范围或通配符；实际 Definition 必须逐字命中。
- `null_only` 要求 `allowed_definition_versions=[]`，实际 Definition 必须是 JSON null；不得伪造为 `unknown`。
- `allowed_scan_outcomes` 只能从 `clean/infected/scan_failed/unsupported/not_configured` 选择，按该固定枚举顺序排列且无重复；不得包含 `pending`。
- 字符串 comparator 固定为 Unicode scalar-value 序列升序，不做 normalization。对合法 I-JSON 字符串，PostgreSQL 实现使用 `convert_to(value,'UTF8')` 的 `bytea` 字典序，禁止默认 locale/collation。Definition 数组按该 comparator 排序；entries 先比较 `adapter_code`，相等时再比较 `scanner_version`；outcome 数组只用固定枚举顺序。
- `(adapter_code,scanner_version)` 在一个 Profile 内唯一。

### 3.3 JCS 与 hash

`scanner_registry_hash = lowercase_hex(SHA-256(UTF8(RFC8785_JCS(profile_object))))`。hash 不放回对象，避免自引用；数组必须先按第 3.2 节验证，JCS 不替数组重排。任一字段、条目、outcome 或 Definition 变化都必须创建新的 `registry_version` 和 hash，禁止既有 version 指向新 bytes。

本 meta-contract 不包含任何具体 Profile。每个 Profile artifact 必须同时保存原始无 BOM UTF-8 JCS bytes、bytes 长度、SHA-256 和 Schema 校验结果，并由两个独立实现复算；未取得第 4 节独立批准前，不得安装、激活或公布为可用 Registry。

## 4. 环境隔离与 Profile 审批

| Profile class | 允许用途 | 必须拒绝 |
|---|---|---|
| `contract` | Schema/JCS/hash/validator 合成向量 | 写业务 scan Step/Asset/evidence、解析或证明 Scanner 可用 |
| `local_offline` | 无网络本地开发；缺 Scanner 只能产生受控 `not_configured` | `clean/infected`、进入解析、冒充 fixed-test/staging/production |
| `fixed_test` | 无网络确定性 Scanner test double；只在隔离测试数据库生成脚本化证据 | `fixed_test_provider` 网络、staging/production validator 接受、证明真实供应商能力 |
| `staging` | 单独审批的预发布真实/候选 Scanner Profile | 使用 fixed-test 证据、替代 production 审批或 production canary |
| `production` | 单独审批的精确正式 Profile 和已验证 Scanner | 空 Registry、本地占位、contract/fixed-test/staging 证据或未批准轮换 |

一个数据库在首次 Profile 安装时永久绑定该 `profile_class`；后续只能安装和激活同 class 的新 version/hash。安装 INSERT 与 activation 使用第 5.1 节同一事务级串行锁，空表并发安装不同 class 时最多一个 class 成功，败者以 SQLSTATE `55000` 和 `SCANNER_REGISTRY_CLASS_CONFLICT` 失败。跨 `fixed_test/staging/production` 切换必须使用独立数据库或新 CR，不能原地重解释历史证据。调用方不能提交“环境 class”来覆盖数据库绑定事实。

Meta-contract 的批准只批准本文件的对象形状、表和验证语义，不批准任何具体 Profile。每个待安装 Profile 必须另有封闭的 `scanner-registry-profile-approval-v1` JCS artifact，精确且仅含 `schema_version/profile_class/registry_version/profile_jcs_sha256/allowed_environments/forbidden_environments/scanner_product/scanner_product_version/approvals/approved_at/evidence_refs` 十一个键，`additionalProperties=false`，并禁止包含 `approval_artifact_sha256` 自身。字段合同如下：

- `schema_version` 精确为 `scanner-registry-profile-approval-v1`；Profile 身份和 hash 必须逐字等于待安装 Profile。
- 环境数组按 `contract/local_offline/fixed_test/staging/production` 固定枚举顺序，`allowed_environments` 必须恰为单项 `[profile_class]`，`forbidden_environments` 必须恰为其余四项，禁止重复、交叉或缺项。
- `scanner_product/scanner_product_version` 必须同时为 JSON null 或同时为 1..200 位首尾无空白的可打印 ASCII string；staging/production 必须非空，其他 class 可空。
- `approvals` 必须恰含 `requirements/architecture/data/backend/ai/test/operations/security` 八个 role 各一项并按该顺序排列；每项精确为 `approver_id/decided_at/decision/role` 四键，`approver_id` 为 1..128 位可打印 ASCII、`decision='APPROVED'`，时间为 UTC 六位微秒 RFC 3339。`approved_at` 必须等于八项 `decided_at` 的最大值。
- `evidence_refs` 为 1..64 个 1..512 位非 secret string，按 Unicode scalar-value 升序且无重复。重复键、未知键、错误类型、非规范时间、未全批准或数组乱序全部拒绝，不由 JCS 静默修复。

外部批准清单使用封闭 `scanner-registry-profile-approval-record-v1` 对象，精确包含 `schema_version/profile_class/registry_version/profile_jcs_sha256/approval_artifact_object_key/approval_artifact_object_version_id/approval_artifact_sha256/approval_artifact_size_bytes/recorded_at` 九键；`schema_version` 必须等于该 literal，Profile 三项身份必须分别逐字等于 Profile 与 approval artifact。object key 为 1..1024 位无控制字符且不得含 secret 的 string，version ID 为 1..1024 位非空 string，hash 为小写 64 位十六进制，size 为 1..9007199254740991 的 JSON integer且必须等于 approval artifact JCS byte length，`recorded_at` 为 UTC 六位微秒 RFC 3339 且不得早于 `approved_at`。它不包含自身 hash。

发布 package manifest `P` 是封闭 `scanner-registry-profile-package-v1` JCS 对象，只含 `schema_version/profile/approval_artifact/approval_record/created_at` 五键，`schema_version` 精确等于该 literal；后三个 artifact ref 各精确包含 `object_key/object_version_id/sha256/size_bytes`，字段类型/长度沿用 approval record，并分别绑定 Profile JCS、approval artifact JCS 和上述 approval record `R` 的原始 bytes，`created_at` 使用同一 UTC 格式且不早于 `R.recorded_at`。`P` 不包含自身 hash，也不引用下述顶层签署记录。

顶层签署记录 `E` 是不进入 `P` 的封闭 `scanner-registry-profile-signature-v1` JCS 对象，只含 `schema_version/profile_class/registry_version/profile_jcs_sha256/package_object_key/package_object_version_id/package_manifest_sha256/package_manifest_size_bytes/decision/signed_at` 十键；schema 和 Profile 身份逐字匹配，package ref 字段沿用 `R` 的类型/长度，`decision='APPROVED'`，`signed_at` 使用同一 UTC 格式且不早于 `P.created_at`。`E` 的原始 bytes/hash 由外部审批系统作为签署证据保存，不写回 `P`，从而形成唯一单向链 `Profile + approval artifact -> R -> P -> E`，没有 R/P 自引用。安装流程必须从 `E` 开始验证 `P` 和三项 ref，再验证 Profile/approval/`R`/数据库列。`approval_artifact_sha256` 仍精确等于 approval artifact JCS bytes 的 SHA-256 并写入数据库同名列；任一身份、长度、hash、对象版本或顺序不一致即拒绝安装。没有完整 `E/P/R` package 时表保持空，所有 current validation fail closed。

CR-005 已冻结的 Asset consumer 只允许 `fixed_test/production` 产生其 Scanner 终态；增加 `staging` 不静默扩大该范围。未来若需 staging 写 document asset 终态，必须提升 CR-005 revision。CR-007 的文件扫描范围按第 6 节冻结。

## 5. 数据库事实载体

### 5.1 表与生命周期

`public.scanner_registry_profiles` 精确包含：

| 列 | PostgreSQL 16 合同 |
|---|---|
| `profile_class` | VARCHAR(20) COLLATE "C" NOT NULL |
| `registry_version` | VARCHAR(100) COLLATE "C" NOT NULL |
| `scanner_registry_hash` | CHAR(64) COLLATE "C" NOT NULL |
| `profile_jcs_bytes` | BYTEA NOT NULL |
| `approval_artifact_sha256` | CHAR(64) COLLATE "C" NOT NULL |
| `installed_at` | TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() |
| `activated_at` | TIMESTAMPTZ NULL |
| `retired_at` | TIMESTAMPTZ NULL |

主键为 `(profile_class,registry_version,scanner_registry_hash)`；`registry_version` 和 `scanner_registry_hash` 还分别全表唯一。Profile/approval hash 必须匹配小写 64 位十六进制；`profile_jcs_bytes` 非空，严格 UTF-8/JCS/Schema 校验通过，且 `encode(digest(profile_jcs_bytes,'sha256'),'hex') = scanner_registry_hash`。bytes 内的 `profile_class/registry_version` 必须与列逐字一致。

生命周期只允许：

```text
installed  : activated_at IS NULL AND retired_at IS NULL
current    : activated_at IS NOT NULL AND retired_at IS NULL
historical : activated_at IS NOT NULL AND retired_at IS NOT NULL AND retired_at >= activated_at
```

生命周期 CHECK 还必须要求 `activated_at IS NULL OR activated_at >= installed_at`。`BEFORE INSERT` trigger 先取得与 activation 相同的 `pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('scanner_registry_profile_activation_v1',0))`，要求表为空或所有既有行的 `profile_class` 与新行相同；跨 class 返回 `SCANNER_REGISTRY_CLASS_CONFLICT`。随后强制新行的 `activated_at/retired_at` 都为 NULL，`installed_at` 必须等于本事务 `transaction_timestamp()`；列默认只为合法省略提供该值，调用方不能选择过去/未来时间或直接插入 current/historical。只有 activate 函数可以写 `activated_at/retired_at`。

部分唯一索引保证全库最多一个 current。每次激活首先取得固定事务级锁 `pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('scanner_registry_profile_activation_v1',0))`，再重读并以 `FOR UPDATE` 锁定 current 与目标 installed 行，以同一数据库事务时间把旧 current 变 historical、目标变 current；锁碰撞只增加串行，不改变语义。激活必须携带调用方读取到的 `expected_current_registry_hash` 做 compare-and-swap：首次激活必须为 SQL NULL 且串行锁内数据库不得存在任何曾激活行；后续激活必须是当前行的 64 位小写 hash。锁后重读的 current 与 expected 不一致时以 SQLSTATE `55000` 和稳定错误标识 `SCANNER_REGISTRY_CURRENT_CONFLICT` 失败，目标保持 installed、旧 current 不变。新 Job 的 current validator 对 current 行取得 `FOR SHARE` 并把锁持有到 Job 输入与事务一起提交；因此 activation 的 `FOR UPDATE` 要么先提交并迫使 Job 使用新 tuple，要么等待旧 tuple 的 Job 先提交。身份列、bytes、approval hash、installed_at、activated_at 一经非空都不可覆盖；只允许 current 的一次 `retired_at: NULL -> transaction_timestamp()` 与 installed 的一次 `activated_at: NULL -> transaction_timestamp()`。禁止 DELETE/TRUNCATE、恢复 historical 或让未激活 Profile 充当历史证据。

Profile 只由另行获批的环境 migration 安装；不开放 HTTP/API，不接受请求方 JSON。应用、Worker、只读、备份和日常运维角色没有本表 INSERT/UPDATE/DELETE/TRUNCATE 权限。

### 5.2 共享函数与 current/history 语义

CR-010 唯一拥有以下函数：

| 函数 | 语义 |
|---|---|
| `public.validate_scanner_registry_profile_current_v1(text,text,text)` | 匹配唯一 current tuple 并对该行 `FOR SHARE`；供新 Job 输入冻结 |
| `public.validate_scanner_registry_profile_history_v1(text,text,text)` | 只匹配曾激活的 current/historical tuple；拒绝 installed-only |
| `public.validate_scanner_registry_current_v1(text,text,text,text,text,text,text)` | current tuple + entry + Definition + outcome 全量校验并对 current 行 `FOR SHARE` |
| `public.validate_scanner_registry_history_v1(text,text,text,text,text,text,text)` | 已激活历史/current Profile 的全量校验 |
| `public.validate_scanner_registry_v1(text,text,text,text,text,text,text)` | 为兼容 CR-005 已冻结调用名，严格委托 `history`，不得改成 current-only |
| `public.validate_asset_security_revalidation_target_current_v1(text,text,text,text,text,text)` | current tuple + 候选 Adapter/Scanner/Definition；仅当 CR-005 唯一 target selector 恰好命中该候选时返回 true，并对 current 行 `FOR SHARE` |
| `public.activate_scanner_registry_profile_v1(text,text,text,text)` | 仅部署迁移调用；target tuple + expected-current CAS、原子 retired/current 转换和永久 class 校验 |
| `public.enforce_scanner_registry_profiles_v1()` | trigger function；Schema/hash/不可变/生命周期边界 |
| `public.reject_scanner_registry_profiles_delete_truncate_v1()` | trigger function；拒绝 DELETE/TRUNCATE |

七参数顺序固定为 `profile_class,registry_version,scanner_registry_hash,adapter_code,scanner_version,scanner_definition_version,scan_outcome`，其中 Definition 是可空 text，其余非空。Asset selector 六参数顺序固定为 `profile_class,registry_version,scanner_registry_hash,adapter_code,scanner_version,scanner_definition_version`，全部非空；它只在 current Profile 中恰好一个条目满足 `definition_version_mode='required_exact'`、Definition allowlist 恰一项且 outcomes 同时包含 `clean/infected/scan_failed`，并且该条目三项身份与候选逐字相等时返回 true，零个/多个命中或候选不等均返回 false，不回显 Profile bytes。activate 四参数顺序固定为 `target_profile_class,target_registry_version,target_scanner_registry_hash,expected_current_registry_hash`，返回 `void`；前三项非空，expected 仅首次激活为 SQL NULL。四个基础 validate 函数、Asset selector 及兼容 wrapper 返回 boolean 并严格校验：未知/畸形/跨 class/未激活/不允许组合返回 false；consumer trigger 统一映射为稳定约束错误。上述函数及 activate 均不得声明 SQL `STRICT`，否则会把合法的 null-only Definition 或首次 activation NULL 在函数体校验前短路为 NULL。

新 Job 创建事务调用 `profile_current`（需要验证已选 entry/outcome 时调用全量 current）并把 tuple 冻结进不可变 Job input。Job 运行或历史查询时调用 history，并额外证明 Step/Asset tuple 等于 Job input；因此合法长任务在 Profile 轮换后仍可提交已 pin 的结果，而轮换后的新 Job 只能使用新 current。installed-but-never-activated Profile 永远不能为业务证据背书。

### 5.3 Revision ownership、upgrade 与 downgrade

批准与生成 migration 时必须记录并校验第 2 节 baseline hash 所锚定的实现前 Alembic head；该绑定 head 不得含本表或本 revision 的任一命名对象。预检通过后，CR-010 获批的单一 revision 才是完整表的唯一创建者；若不满足，CR-010-R1 不可签署或实施，必须重新评估并提升 revision。精确对象 allowlist 为：

| 类型 | 精确对象 |
|---|---|
| 表 | `public.scanner_registry_profiles` |
| 约束 | `pk_scanner_registry_profiles`、`uq_scanner_registry_profiles_version`、`uq_scanner_registry_profiles_hash`、`ck_scanner_registry_profiles_class`、`ck_scanner_registry_profiles_version`、`ck_scanner_registry_profiles_hashes`、`ck_scanner_registry_profiles_bytes`、`ck_scanner_registry_profiles_lifecycle` |
| 索引 | `uq_scanner_registry_profiles_current` |
| 普通函数 | 第 5.2 节前七个 validate/selector/activate 函数及其精确签名；selector 为 `public.validate_asset_security_revalidation_target_current_v1(text,text,text,text,text,text)`，activate 为 `public.activate_scanner_registry_profile_v1(text,text,text,text)` |
| trigger functions | `public.enforce_scanner_registry_profiles_v1()`、`public.reject_scanner_registry_profiles_delete_truncate_v1()` |
| triggers | `trg_scanner_registry_profiles_state_v1`、`trg_scanner_registry_profiles_delete_v1`、`trg_scanner_registry_profiles_truncate_v1` |

表与九个函数归 `finaudit_migrator` 所有，trigger 随表控制且不声称独立 owner。两个通用 `*_current_v1` validate 与 Asset selector 因取得 `FOR SHARE` 行锁固定为 `SECURITY DEFINER VOLATILE`；两个 history validate 与兼容 wrapper 为 `SECURITY DEFINER STABLE`；activate 为 `SECURITY INVOKER VOLATILE`，enforce/reject 为 `SECURITY INVOKER`。全部声明 `SET search_path = pg_catalog, public, pg_temp`，函数体仍完全限定 relation/function/type，不使用动态 SQL、文件、网络、Session GUC 或 secret。迁移对全部函数 `REVOKE ALL FROM PUBLIC`；app/worker 只获各自 consumer 所需的 current/history/wrapper EXECUTE，Asset selector 只授予 `finaudit_app_rw`，不授予 activate 或 trigger function 的直接 EXECUTE，也不授予表 DML。`finaudit_migrator` 只能在受控部署会话安装 artifact 或调用 activate。

Upgrade 固定按“确认 allowlist 对象均不存在 → 创建空表/命名约束/部分唯一索引 → 创建函数 → 创建 triggers → REVOKE/GRANT → catalog 与空表验证”执行；不得写默认、local、test 或 production Profile。环境 artifact 安装和 activation 是批准后的后续 migration，不得伪装成 BASE-005 种子。

Downgrade 前必须先按 Alembic 逆序删除 CR-005/007 consumer triggers/functions；仍存在依赖时失败，不使用 CASCADE。数据库事务先 `SET LOCAL lock_timeout='5s'` 并取得本表 ACCESS EXCLUSIVE 锁；锁超时保持 SQLSTATE `55P03`。只要本表存在任一 installed/current/historical 行，或 catalog 仍有外部 consumer 依赖，就在任何 DDL 前以 SQLSTATE `55000` 原子失败，历史 Profile 只能前向保留。仅空表且无 consumer 时，逐名删除三个 triggers，再按反向调用依赖依次删除 Asset selector、兼容 wrapper、full history/current validators、profile history/current validators、activate 和两个 trigger functions共九个函数，最后 `DROP TABLE public.scanner_registry_profiles`；函数必须先于其引用的 relation 删除，独立函数不得误称为随表删除。全程禁止 CASCADE/TRUNCATE/自动删除 artifact/动态发现其他对象。

## 6. Consumer 集成与无环依赖

依赖方向固定为：

```text
CR-001-R2 已批准扫描追踪边界 -> CR-010-R1 meta-contract/table/functions
CR-010-R1 获批并同步 ------------┬-> CR-005 Asset consumer trigger/runtime
CR-004-R1 获批并落地 ------------+-> CR-007 File Job/Step/evidence runtime
CR-006/008 获批并落地 -----------┘
```

- CR-005 已冻结的 `validate_scanner_registry_v1` 保留为七参数 history wrapper。PARSE-006 Job 创建 consumer 先调用 `validate_scanner_registry_profile_current_v1` 冻结 current tuple，再把候选 Adapter/Scanner/Definition 交给 `validate_asset_security_revalidation_target_current_v1`，只有唯一 selector 返回 true 才能创建 Job；Service 无需也不得获得 Profile 表 SELECT 或依赖未验证的本地副本。Asset 终态仅在 Scanner 身份组合非空时调用七参数 history wrapper并证明 tuple 等于 Job input，`not_configured` 只调用三参数 `profile_history` 并匹配 Job input，pre-Scanner `scan_failed` 与 `unsupported` 的全 NULL 分支不调用七参数函数。此兼容层闭合 CR-005 对 CR-010 的外部依赖，不改写其已生成 snapshot。
- CR-007 的 `file_scan/file_process` Job input、实际 outcome Step 与 `file-scan-evidence-v1` 必须都冻结 `scanner_profile_class/scanner_registry_version/scanner_registry_hash`。初始扫描 Job 创建调用 current；scan-only clean 派生的 full Job引用 source evidence 的历史 tuple；终态 Step/evidence 调 history并与 Job input逐字一致。
- CR-005/007 各自拥有并在 downgrade 删除本领域 consumer trigger/function；不得拥有、覆盖或删除本表和共享 validator。
- CR-010 不依赖 CR-005/007 获批，所以不存在循环；具体 consumer runtime 仍等待各自合同、CR-004、CR-006/008 和 Handler Registry 闭合。

## 7. 验收、审批与 snapshot

### 7.1 必须验收

- 两个独立实现得到相同 JCS bytes/hash；键顺序变化不改变 hash，数组次序非法时拒绝而非静默重排。覆盖 Unicode scalar/UTF-8 comparator、无 normalization、重复条目和固定 outcome 顺序。
- 缺键、额外键、占位/通配版本、非法 class、Definition mode/list 不一致、未知 outcome、bytes/hash/列不一致全部 fail closed。
- INSERT 只能形成 installed，调用方提供 activated/retired 或非事务时间 installed_at 均拒绝；`activated_at >= installed_at`。覆盖空表并发安装相同/不同 class，证明同一固定锁下永久 class 绑定且跨 class 固定为 `SCANNER_REGISTRY_CLASS_CONFLICT`。空表时全部 current/history validation 失败；installed-only 只可安装不可背书；首次 activation 必须 expected NULL。固定 advisory lock 使两个不同 target 的首次并发和同一 expected current 的后续并发都最多一个成功，败者固定为 `SCANNER_REGISTRY_CURRENT_CONFLICT`；Job validator 的 `FOR SHARE` 与 activation 的 `FOR UPDATE` 必须覆盖“Job 验证后未提交、同时轮换”并得到先 Job 后轮换或先轮换后新 tuple 的可串行结果。
- current 只接受唯一当前 tuple，history 只接受曾激活 tuple；兼容 `validate_scanner_registry_v1` 等价 history。Asset selector 覆盖零个、一个、多个命中、Definition 列表不唯一、outcome 缺项和候选不等；只有唯一合法候选返回 true。Profile 轮换后，旧 pinned 长任务可按历史 tuple 提交，新 Job 不能使用旧 tuple。
- `local_offline` 不生成 clean/infected；`fixed_test` 完全无 socket，且被 staging/production 数据库拒绝；staging 不替代 production；CR-005 不因新增 staging 被扩权。
- app/worker 无表 DML、无 activate 权限；未知函数/trigger/owner/grant、PUBLIC EXECUTE、动态 SQL 或 secret 泄漏均使 catalog Gate 失败。
- 空表 upgrade/downgrade/upgrade 不遗留 allowlist 对象；锁超时 55P03；任一 Profile 行或 consumer 依赖使 downgrade 在 DDL 前以 55000 失败且数据/Schema/head 不变。

这些检查只证明 meta-contract 或指定离线环境实现，不证明 production Scanner 已配置、网络可达、真实扫描成功、CR-005/007 runtime 或 production 放行。

### 7.2 审批输入与生命周期

Meta-contract 批准记录必须包含：`姓名 / 角色 / APPROVED|REJECTED / selected_decisions=ALL_RECOMMENDED_SCANREG_D_001_TO_008 / cr_revision=CR-010-R1 / decision_snapshot_sha256 / baseline_manifest_sha256=717c040569c536a13f4d770ad81414f86da7fc13c2ac6940c8df5ccfd1222f41 / core_table_delta=+1 / api_delta=0 / environment_scope=contract / 日期 / 证据链接 / 备注`，并覆盖需求、架构、数据、后端、AI/RAG、测试、运维和安全责任；不接受部分选择、别名或自由文本替代。它不包含具体 Profile artifact。

每个具体 Profile 另需第 4 节精确 Schema 的 approval artifact、外部批准清单与 package manifest；fixed_test、staging、production 互不替代。是否存在当期获批 Profile 只记录在第 8 节，不进入本规范性前像。

生命周期固定为：

```text
DRAFT -> GENERATED_FOR_REVIEW -> APPROVED_CONTRACT -> REQUEST_SYNCED -> IMPLEMENTABLE
```

`APPROVED_CONTRACT` 不等于任何具体 Profile 获批；`REQUEST_SYNCED` 之前不得建表；表/函数 implementable 不等于 consumer runtime 可启动；consumer runtime 还必须有本环境已批准并 current 的 Profile、所有依赖和离线/真实环境验收。任何阶段都不自动授权 production。

### 7.3 Decision snapshot

`decision_snapshot_sha256` 计算规则：全文行尾规范化为 LF，内容完全等于 `## 8. 当前状态` 的标题必须恰好出现一次；取该行之前全部行，去除已有尾随 LF 后再保留恰好一个 LF，以无 BOM UTF-8 编码并计算 SHA-256 小写十六进制。标记缺失/重复、UTF-8/BOM/行尾规则不满足或 hash 非小写 64 位十六进制时不可签署。

首次生成 snapshot 只建立可签署对象，不等于批准。生成后第 1～7 节任一规范性修改都必须提升 revision、重算 hash 并清空签署；第 8 节只记录状态，不进入 preimage。

## 8. 当前状态

| 项目 | 状态 |
|---|---|
| GAP-055 / meta-contract | SUPERSEDED BY `CR-010-R2` |
| `scanner_registry_profiles` / shared validators | PROPOSED / NOT AUTHORIZED |
| core/API delta | PROPOSED：`+1 / 0`；最终总数按有效 CR 累加 |
| concrete Profile artifacts/JCS/hash | NONE / NOT GENERATED / NOT APPROVED |
| Request 同步 | HISTORICAL R1；CURRENT AUTHORITY IS `CR-010-R2` |
| decision snapshot | `17877a4cef3ca0a145f32ac06acf44e7fb65b49c06dec710a04a6078aca319de` / GENERATED_FOR_REVIEW / NOT APPROVED |
| 批准记录 | NONE |
| migration / consumer runtime | NOT AUTHORIZED / BLOCKED BY APPROVAL AND DEPENDENCIES |
| `fixed_test_provider` / 内部 vLLM / 真实 Provider 网络 | NOT AUTHORIZED |
| production/canary/部署 | NOT AUTHORIZED |
