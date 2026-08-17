# CR-011-R7：BASE-004 同次运行三样本启动证据

> 状态：Gate A 候选；未批准；0/9；Gate B 未授权、未运行；Gate C 未授权、未运行  
> 负责人：YHBX  
> 日期：2026-08-11  
> 基座：CR-011-R6  
> 唯一增量：把 R6 无法静态物化的 expected membership 改为可信锁定工具链下的同次 C1/C2 校准、冻结 manifest、C3 精确复核  
> 非目标：应用行为、Policy、Provider、数据库、Redis、Broker、真实环境、部署、production、P0 或 AC 状态升级

## 1. 决策基座、目的与证据边界

### 1.1 不可变基座

R7 逐字绑定以下已批准或已冻结事实：

| 基座 | raw identity | decision identity |
|---|---|---|
| CR-011-R3 | 27376 / e89320fc4eed9bfa51b289fc8decc9b344bc78cf0391c0bc22bf9156a563db7f | 26563 / b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be |
| CR-011-R4 | 30944 / 5e7afd94bb2dfef22fa3d9d6d6341fa140d890a1df5753e0f87bcaee1dd756bd | 27384 / cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10 |
| CR-011-R5 | 53927 / 089cbb5c88659dc7076df191af6d4c84492aa30e081878c1bfc232596a8407a7 | 50926 / fb6aa225dae67a6068e84935e4a77affe84b143de5de2908b555089f9334c5ae |
| CR-011-R6 | 65121 / 54a42ade8b20846504e56c6a004503216462f6c71807d0d21c94e74efd087ede | 60493 / 113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815 |

另绑定R3 manifest 5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c（15/15）与lock 641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c。除§1.2明确替代项外，R6 CPython 3.10.20、direct/clean/same-process、Toolhelp/guard/path/identity/cleanup、行为禁令及NOT_CLAIMED继续；失败即R7失败。

### 1.2 真正要解决的问题

R6因loaded-subject membership无法静态推导而在child前阻断。R7唯一选择STARTUP-D-005-R7-MINIMAL-SAME-RUN-REPEATABILITY并supersede STARTUP-D-005-R6：static expected allowlist/pin owner/expected-observed diff由C1/C2/freeze/C3替代；R6 child ledger/projection及其他决策保留。

R7只授权exact12场景各C1/C2校准；projection byte-equal后冻结manifest并持不可继承读lease；运行fresh C3且diff=0；runner仅输出CR011_R7_EVIDENCE_READY_PENDING_TWO_REVIEWS，双review PASS后才更新§9。

### 1.3 唯一允许的成功 claim

唯一claim为`TRUSTED_LOCKED_TOOLCHAIN_SAME_RUN_SAME_SCENARIO_C1_C2_FREEZE_C3_EXACT_REPEATABILITY`：只证明保留的同次本地evidence中，相同declared-input的三个样本在R6可见边界内一致。STATIC_TRUTH_OR_MEMBERSHIP_COMPLETENESS、HOSTILE_OR_COLLUDING_TOOLCHAIN、ORDER_OR_TIME_ADAPTIVE_SUBJECT_DETECTION、CROSS_RUN_UNIQUENESS_RETRY_OR_SELECTION_RESISTANCE、NATIVE_DESCENDANT_COMPLETENESS、NATIVE_OS_WINSOCK_OR_WINDOWS_NAMED_PIPE_ZERO、NATIVE_EXTENSION_DELAY_LOAD_OR_ARBITRARY_NATIVE_NEW_MODULE_ZERO、LOCAL_ADMIN_TAMPER_DELETE_REWRITE_OR_REPLAY_RESISTANCE全部为NOT_CLAIMED。toolchain honesty是明确假设；不冒充静态真值、sandbox、跨机器或production evidence。

## 2. 固定 scenario、declared input 与三样本协议

### 2.1 exact 12 scenario 单一事实来源

Gate B 必须创建 scripts/cr011-r7-scenarios.json，且其 raw bytes 必须精确等于下列 RFC 8785 JCS，无 trailing LF：

~~~json
{"record_type":"CR011_R7_SCENARIO_MANIFEST","scenarios":[{"artifact_form":"SOURCE","entrypoint":"FACTORY","environment":"LOCAL","expected_outcome":"ADOPTED","ordinal":1,"scenario_id":"SOURCE_LOCAL_FASTAPI_FACTORY","service":"FASTAPI"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"LOCAL","expected_outcome":"ADOPTED","ordinal":2,"scenario_id":"SOURCE_LOCAL_FASTAPI_MODULE","service":"FASTAPI"},{"artifact_form":"SOURCE","entrypoint":"FACTORY","environment":"LOCAL","expected_outcome":"ADOPTED","ordinal":3,"scenario_id":"SOURCE_LOCAL_WORKER_FACTORY","service":"WORKER"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"LOCAL","expected_outcome":"ADOPTED","ordinal":4,"scenario_id":"SOURCE_LOCAL_WORKER_MODULE","service":"WORKER"},{"artifact_form":"SOURCE","entrypoint":"FACTORY","environment":"TEST","expected_outcome":"ADOPTED","ordinal":5,"scenario_id":"SOURCE_TEST_FASTAPI_FACTORY","service":"FASTAPI"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"TEST","expected_outcome":"ADOPTED","ordinal":6,"scenario_id":"SOURCE_TEST_FASTAPI_MODULE","service":"FASTAPI"},{"artifact_form":"SOURCE","entrypoint":"FACTORY","environment":"TEST","expected_outcome":"ADOPTED","ordinal":7,"scenario_id":"SOURCE_TEST_WORKER_FACTORY","service":"WORKER"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"TEST","expected_outcome":"ADOPTED","ordinal":8,"scenario_id":"SOURCE_TEST_WORKER_MODULE","service":"WORKER"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"PROD","expected_outcome":"REJECTED_PRE_EXPOSURE","ordinal":9,"scenario_id":"SOURCE_PROD_FASTAPI_MODULE","service":"FASTAPI"},{"artifact_form":"SOURCE","entrypoint":"MODULE","environment":"PROD","expected_outcome":"REJECTED_PRE_EXPOSURE","ordinal":10,"scenario_id":"SOURCE_PROD_WORKER_MODULE","service":"WORKER"},{"artifact_form":"INSTALLED","entrypoint":"MODULE","environment":"TEST","expected_outcome":"ADOPTED","ordinal":11,"scenario_id":"INSTALLED_TEST_FASTAPI_MODULE","service":"FASTAPI"},{"artifact_form":"INSTALLED","entrypoint":"MODULE","environment":"TEST","expected_outcome":"ADOPTED","ordinal":12,"scenario_id":"INSTALLED_TEST_WORKER_MODULE","service":"WORKER"}],"version":1}
~~~

该 payload identity 固定为：

- raw bytes：2205；
- raw SHA-256：9405b63188ffd4082307dc7600485ffcb72fcc0a3b4fc8b3182b0cebb6b3995b；
- count：12；
- ordinals：1..12；
- expected outcome vector：8×ADOPTED、2×REJECTED_PRE_EXPOSURE、2×ADOPTED。

expected_outcome只属于parent-only expectation。child execution projection恰为scenario_id/artifact_form/environment/service/entrypoint五字段JCS，不含expected_outcome与ordinal。missing、extra、duplicate、alias、reorder、tuple mutation 或 outcome mutation 均失败；不得只跑稳定子集。

### 2.2 固定工具与输入

Gate B只允许新增：`scripts/cr011-r7-scenarios.json`、`scripts/cr011-r7-same-run-evidence.schema.json`、`scripts/cr011-r7-toolchain-pins.json`、`scripts/verify-cr011-r7-gate-c.py`、`scripts/verify-cr011-r7-gate-c.ps1`、`scripts/test-verify-cr011-r7-gate-c.ps1`、`scripts/review-cr011-r7-evidence.py`。不得改application runtime/Policy/Provider/DB/Redis/Broker/frontend/deploy/production或新增依赖。

首个Gate C child前，两名Gate B reviewer独立重算pins：R7/R6、scenario/Schema/core/top-level/negative/reviewer、direct runtime/venvlauncher拒绝集、source/resources/R6 support、root/argv/env/site/immutable inputs、guard-selftest result。pins不得源自observed/history；Gate C及每child前后重算immutable set。`child_runtime_pin_projection`仅含child所需R7/R6、Schema/core/runtime/source/resources/R6 support/root/argv/env/site/inputs，排除scenario/expected/selftest/top-level/negative/reviewer。

R6 guard selftest固定在Gate B：exact 1个隔离dedicated child，不计入Gate C 36 children。唯一root=`build/cr011-r7-gate-b`；创建前、写后均验证project/build/root及其文件在repo内canonical fixed-local-drive、逐component non-reparse、regular single-link、无UNC/device/alias，并记录project/build/root的path+FileId。closed root只允许`launch-intent.jcs`与`r6-guard-selftest.jcs`；extra即fail且不删除。

定义RAW_BLOB closed object=`base64/raw_bytes/sha256`、RAW_IDENTITY=`raw_bytes/sha256`。GUARD_INPUT_PINSET是exact JCS root，record_type=CR011_R7_GUARD_INPUT_PINSET、version=1，keys恰为record_type/version/r7_decision_snapshot/r6_decision_snapshot/project_root/build_root/selftest_root/executable/argv/env/guard_seam_source；三root项closed keys恰为relative_path/canonical_path/file_id，executable/source恰为canonical_path/file_id/raw_bytes/sha256，argv/env为RAW_IDENTITY。child前与result写后重建的projection bytes必须相同。

首次运行只在root不存在时创建root并冻结`launch-intent.jcs`；CR011_R7_GUARD_SELFTEST_LAUNCH_INTENT record_type/version固定为同名/1，exact keys为record_type/version/guard_input_pinset/process_create_call_ordinal，guard_input_pinset为projection RAW_IDENTITY且process_create_call_ordinal=1。intent以CreateNew/WriteThrough/Flush/close/ReadOnly/reread在CreateProcess前冻结。重启状态唯一：(a) root不存在则开始；(b) root只含empty/invalid intent且result缺失时，因CreateProcess严格晚于valid intent，可复验path后逐文件、非递归清空并重跑；(c) valid intent+valid result时全量复算后只复用结果且不得再建child；(d) valid intent+missing/invalid result、result无valid intent或任何extra均为本R7永久Gate-B FAIL，root保留且禁止清理/重跑。

`scripts/cr011-r7-toolchain-pins.json`就是final CR011_R7_TOOLCHAIN_PIN_MANIFEST：绑定其余固定input identities及guard projection/intent/result RAW_IDENTITY，明确排除自身raw identity；只允许run-inputs与两名Gate-B reviewer外部证据绑定该manifest raw identity。单向DAG为projection→intent→result→toolchain-pins→run-inputs/reviews，不得反向回填。

CR011_R7_GUARD_SELFTEST_RESULT record_type/version固定为同名/1，keys恰为record_type/version/r7_decision_snapshot/r6_decision_snapshot/guard_input_pinset_pre/guard_input_pinset_post/launch_intent/invocation_spec/process_created/stdout/stderr/stdout_eof/stderr_eof/exit_code/ordered_vectors/vector_count/unexpected_io_count/cleanup_failure_count；intent/pinset为RAW_IDENTITY，invocation/process/stdout/stderr为RAW_BLOB。intent与pre/post projection必须逐byte重建匹配；invocation解码JCS closed keys恰为selftest_root/executable/argv/env且逐值等于projection；process解码JCS必须是§2.5 exact CR011_R7_PROCESS_CREATED，scenario_id=GATE_B_GUARD_SELFTEST、create_call_ordinal=1。root禁PASS/verdict；exit=0、EOF=true、stderr必须`base64=""/raw_bytes=0/sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

stdout decoded bytes必须是无trailing LF的RFC 8785 JCS，record_type=CR011_R7_GUARD_SELFTEST_STDOUT、version=1，closed keys恰为record_type/version/ordered_vectors/vector_count/unexpected_io_count/cleanup_failure_count，且后四项与result root byte/value-exact。vector keys恰为ordinal/vector_id/call_id/expected_error/actual_error/counter_name/counter_delta_uint32/blocked_before_io；ERROR=`stage/code`且stage=R6_GUARD_SELFTEST，actual=expected、delta=1、blocked=true。ordered tuples为：1/TCP/AF_INET_STREAM/ERR_GUARD_TCP/python_visible_socket_attempts；2/UDP/AF_INET_DGRAM/ERR_GUARD_UDP/python_visible_socket_attempts；3/DNS/GETADDRINFO/ERR_GUARD_DNS/python_visible_dns_attempts；4/LOCAL_SOCKET/AF_UNIX/ERR_GUARD_LOCAL_SOCKET/python_visible_local_socket_attempts；5/EXTRA_GETHOSTNAME/GETHOSTNAME_AFTER_ALLOWED_1/ERR_GUARD_EXTRA_GETHOSTNAME/local_hostname_reads。vector_count=5、unexpected_io/cleanup=0；reviewer只从raw process/stdio重建vectors/counters并比较root。

### 2.3 role-blind declared input

同一scenario的C1/C2/C3使用byte-identical declared input；closed digest绑定五字段execution projection JCS、R6 snapshot、child_runtime_pin_projection、direct executable、argv JCS、working-directory identity、case-insensitive duplicate-free env、site activation与immutable inputs。

C1/C2/C3只存在于parent的external_sample_role。child input与toolchain source禁止读取/查找：role/ordinal/candidate marker；其他样本PID/time/ledger/projection/identity；scenario manifest path/hash/content/ordinal/expected；calibration manifest；attempt/evidence path；expected projection/diff/verdict；retry/history/prior result。

child只接收五字段execution projection及相同runtime inputs，只输出actual primitive outcome和R6 ledger；parent独立读取scenario manifest并比较expected_outcome。该隔离是locked non-hostile toolchain合同，不声称OS sandbox或hostile-code inaccessibility。证据 stdout/stderr 是受控匿名 stdio transport，不授权 application Windows named-pipe。

### 2.4 单 scenario 固定顺序

每scenario固定顺序：recalc inputs→fresh C1 terminal/EOF/ledger→recalc→byte-identical fresh C2→验证不同process、保留R6 gates及parent outcome→P1=P2 JCS→从共同projection CreateNew/WriteThrough/Flush/close/ReadOnly/reread manifest→取得non-inheritable read/no-delete-share lease并记录pre-C3 identity/handle-list→recalc→确认不继承lease后fresh C3 terminal/EOF/ledger及parent outcome/P3→持lease验证post identity与四类diff=0→close process/stdio/lease/handles（lease close=1、cleanup=0）→scenario evidence。任一步失败立即停止attempt。

成功数学：process=12×3=36，calibration=24，candidate=12，retry=0，extra process=0。

不得使用 majority、union、intersection、rolling calibration、第三个 calibration、跨scenario或跨run manifest、历史 ledger 或失败后补账。

### 2.5 process freshness 与 R6 stable projection

trusted parent为每次CreateProcess生成closed PROCESS_CREATED raw record，字段恰为record_type/version/create_call_ordinal/scenario_id/process_id_uint32/thread_id_uint32/creation_time_filetime_hex16/create_process_result；record_type=CR011_R7_PROCESS_CREATED、version=1、create_process_result=true，creation time由同一live process handle的GetProcessTimes取得。ProcessResult嵌入其base64/decoded bytes/SHA-256。每scenario三个ordinal连续唯一且三个(pid, creation time) tuple distinct；不得用fresh=true或numeric PID不复用替代。

PROCESS_RESULT exact keys为record_type/version/scenario_id/external_sample_role/invocation_spec/immutable_input_digest/process_created/exit_time_filetime_hex16/wait_result/exit_code/stdout/stderr/stdout_eof/stderr_eof/child_ledger/stable_projection/timeout_state/termination_state/owned_handle_cleanup_counters/r6_retained_gate_results/actual_outcome；六份raw evidence均为RAW_BLOB，actual仅ADOPTED或REJECTED_PRE_EXPOSURE。

child不接收expected outcome。evidence protocol与R6 guard完整时child exit code为0并报告actual outcome；协议、guard、timeout或child-owned cleanup失败时nonzero。actual与expected不等由parent在外层fail closed。

R6 stable projection按R6 decision identity继承。它保留每个R6 subject entry必需的role，只排除parent-only external_sample_role、sample ordinal、PID、time、handle、ASLR/base address、evidence path、manifest、diff和verdict。

## 3. 最小 evidence artifacts、Schema 与独立复核

### 3.1 artifact集合与引用DAG

成功attempt恰有26个attempt artifacts：

| artifact | count | 说明 |
|---|---:|---|
| run-inputs.jcs | 1 | 首个child前冻结decision、scenario、toolchain、guard-selftest、root与immutable inputs |
| scenario-NN/calibration-manifest.jcs | 12 | C1=C2后、C3前冻结共同projection |
| scenario-NN/evidence.jcs | 12 | 嵌入C1/C2/C3 ProcessResult、manifest bytes、freeze/lease/diff与cleanup |
| run-summary.jcs | 1 | 按scenario ordinal绑定12组manifest/evidence identity并输出固定ready marker |

两份review record在runner退出后生成，不计入26；失败至多另写attempt-failure.jcs。DAG固定为run inputs→C1/C2 raw→manifest→C3 raw→scenario evidence→summary→two reviews→§9。artifact禁止self/forward reference或回填；均CreateNew/WriteThrough/Flush(true)/close/ReadOnly/reread。freeze facts只进后置evidence。

正式evidence root唯一为repo-relative `build/CR011_R7_MIN_ATTEMPT_001`，禁止CLI/env覆盖。创建前验证project root与既存`build` parent均为canonical fixed-local-drive、位于project内、逐component无reparse/UNC/device/alias；target须不存在，创建后记录project/build/root canonical path与FileId。run-inputs、run-summary及两review绑定同一root relative path和三组identity。

### 3.2 minimal Schema

Draft 2020-12 Schema closed、strict UTF-8、duplicate-key reject且使用pinned RFC 8785 JCS。independent `record_type` exact literals为CR011_R7_TOOLCHAIN_PIN_MANIFEST、CR011_R7_GUARD_INPUT_PINSET、CR011_R7_GUARD_SELFTEST_LAUNCH_INTENT、CR011_R7_GUARD_SELFTEST_RESULT、CR011_R7_SCENARIO_MANIFEST、CR011_R7_RUN_INPUTS、CR011_R7_CALIBRATION_MANIFEST、CR011_R7_SCENARIO_EVIDENCE、CR011_R7_RUN_SUMMARY、CR011_R7_ATTEMPT_FAILURE、CR011_R7_REVIEW_RECORD、CR011_R7_SYNC_PREPARED、CR011_R7_SYNC_COMMITTED；nested literals为CR011_R7_GUARD_SELFTEST_STDOUT、CR011_R7_PROCESS_CREATED、CR011_R7_PROCESS_RESULT、CR011_R7_CANDIDATE_DIFF、CR011_R7_MANIFEST_FREEZE_EVIDENCE。所有FILETIME用lowercase fixed-width `[0-9a-f]{16}` string；FileId为closed object `{"file_id_hex32":"[0-9a-f]{32}","volume_serial_hex16":"[0-9a-f]{16}"}`，两者禁止JSON number。unknown/missing/extra/duplicate、wrong discriminator/order/width/case、noncanonical、self/forward reference均失败。

calibration manifest只绑定type/version/attempt/scenario、R7/R6/run-inputs、declared-input/invocation、C1/C2 ProcessResult、common projection base64/bytes/hash/count、sample count=2、mismatch=0；禁止C3/diff/future/self/freeze声明。

MANIFEST_FREEZE_EVIDENCE keys恰为record_type/version/scenario_id/manifest_relative_path/write_result/lease_result/pre_c3_identity/post_c3_identity/ordinals。WRITE_RESULT=`create_disposition/write_through/written_raw_bytes/written_sha256/flush/writer_close_count/file_attributes_uint32/read_only_present`；LEASE_RESULT=`desired_access_uint32/share_mode_uint32/creation_disposition_uint32/inheritable/child_handle_list_count/close_count`；FILE_IDENTITY=`file_id/raw_bytes/sha256`；ORDINALS=`freeze_complete/lease_acquired/c3_created/c3_exited/diff_complete/lease_closed`。固定值为CR011_R7_MANIFEST_FREEZE_EVIDENCE/v1/CREATE_NEW/true/true/1/true/2147483648/1/3/false/0/1；ordinals递增且pre=post。只记录trusted-parent primitive，不声称抵抗local admin。

scenario evidence嵌入C1/C2/C3 ProcessResult、manifest raw bytes与MANIFEST_FREEZE_EVIDENCE，并保存parent重算的C1=C2、manifest=C3、四类diff arrays、immutable-input pre/post与cleanup counters。reviewer从embedded raw bytes重算，不得信summary boolean/verdict。

run summary只绑定attempt、decision、scenario count=12及ordered十二组scenario_id/manifest identity/evidence identity，不含自身hash。runner唯一成功输出为：

CR011_R7_EVIDENCE_READY_PENDING_TWO_REVIEWS

runner不得输出PASS、ACCEPTED、production-ready、P0 complete或tracking已完成。

### 3.3 两份独立post-review

每名reviewer不得读另一record；须从disk复算R7/R6/scenario/pins、JSON/JCS/base64/identity/DAG、12项invocation/freshness/C1=C2/manifest=C3/four diffs、R6 Toolhelp/guards、freeze/order/cleanup、36/26/retry=0/no reuse；不得信summary/verdict。

review record必须绑定reviewer role、R7 snapshot、attempt label、run-summary identity、ordered十二项recalculated result digest及PASS/FAIL。两份均PASS且绑定同一run bytes后，root才可更新第9节为local same-run evidence accepted。

## 4. Gate A、Gate B、Gate C 与15个负例

### 4.1 Gate A

Gate A只读复算R3–R6/manifest/lock/current11、本CR、scenario 2205/9405b631.../12项、40-field approval/9 roles/placeholder/NOT_CLAIMED、13+5 record types并双review。不得实现tooling、启动child/校准、创建root、访问network/secret；无High/Medium才请求批准。

### 4.2 Gate B

九角色批准后Gate B才可同步11文件、建七tooling/Schema/pins/15 negatives/reviewer，运行offline tests与exact 1个R6 guard-selftest child，复跑R4/R5 Gate B、R6其余no-app-child preflight/default offline，并双review source/tests/result/reverse projection/边界。

Gate B不得运行正式36-child attempt，不得创建正式attempt root，不得访问Provider、数据库、Redis、Broker、真实环境、secret value、部署或production。

### 4.3 R7专属negative matrix

R6 negatives继续按R6 decision identity继承；R7只新增以下15个exact stage/code：

| ordinal | stage | code |
|---:|---|---|
| 1 | SCENARIO_SET | ERR_SCENARIO_SET_DRIFT |
| 2 | DECLARED_INPUT | ERR_DECLARED_INPUT_DRIFT |
| 3 | ROLE_BLINDNESS | ERR_CHILD_ROLE_OR_EXPECTED_INPUT |
| 4 | PROCESS_FRESHNESS | ERR_PROCESS_NOT_FRESH |
| 5 | CALIBRATION | ERR_C1_C2_PROJECTION_MISMATCH |
| 6 | MANIFEST_FREEZE | ERR_MANIFEST_ORDER_OR_IDENTITY |
| 7 | MANIFEST_LEASE | ERR_MANIFEST_LEASE_INHERITED_OR_BROKEN |
| 8 | CANDIDATE_ORDER | ERR_C3_BEFORE_FROZEN_LEASE |
| 9 | CANDIDATE_DIFF | ERR_C3_DIFF_NONZERO |
| 10 | SCENARIO_BINDING | ERR_CROSS_SCENARIO_REUSE |
| 11 | ATTEMPT_CONTROL | ERR_RETRY_OR_EXTRA_SAMPLE |
| 12 | R6_INHERITED_GATE | ERR_R6_GATE_FAILURE |
| 13 | ARTIFACT_INTEGRITY | ERR_ARTIFACT_IDENTITY_OR_ORDER |
| 14 | SCHEMA | ERR_UNKNOWN_MISSING_DUPLICATE_OR_SELF_IDENTITY |
| 15 | CLAIM_BOUNDARY | ERR_FAILURE_OR_SCOPE_OVERCLAIM |

每个case必须有positive control、exact fixture、expected stage/code、nonzero exit与cleanup=0；SCHEMA覆盖FILETIME/FileId numeric/width/case及sync prepared/committed漂移，R6_INHERITED_GATE覆盖selftest root/intent crash states、reparse/extra、vector missing/reorder、stdout/root mismatch、pin/stage/code/counter/exit/cleanup drift，ARTIFACT_INTEGRITY覆盖partial/extra staging、third live identity、wrong temp、逆序清理与completed-only恢复。错误stage/code不得算PASS；删除/漏跑/skip/xfail/reorder/只验count均失败。

### 4.4 Gate C

Gate C只在Gate B及两review PASS后授权；唯一label=CR011_R7_MIN_ATTEMPT_001，唯一root=`build/CR011_R7_MIN_ATTEMPT_001`且预先不存在。顺序执行12项C1→C2→manifest→C3→diff，失败即停。成功要求12/36/26、retry=0、R6保留的child gates PASS、C1/C2 mismatch=0、C3四类diff=0、freeze/cleanup PASS；runner只输出CR011_R7_EVIDENCE_READY_PENDING_TWO_REVIEWS，双post-review前不得ACCEPTED或更新tracking。

## 5. 十一文件Gate B协调可恢复同步

### 5.1 pre-state identity

批准后的同步目标必须恰为九份Request、docs/baseline-manifest.md与backend/app/approval_pre_meta.py。pre-state固定如下：

| path | raw bytes | raw SHA-256 |
|---|---:|---|
| Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md | 130357 | b0f7b4422f3bd32d8fb0b3ace4417a63da3a48b9b931c3fbd48239399eb3c511 |
| Request/FinAudit_Agent_系统架构设计说明书_V1.0.md | 92246 | 061f4a2fdce8e813abdc904d7657cd70bfee46ff46e804725d4eb462e9fa2a57 |
| Request/FinAudit_Agent_数据库设计说明书_V1.0.md | 116615 | 8f4878fe396910cc6176ddc044b4e23a1d81aa68035e2896a254bbcc171e29df |
| Request/FinAudit_Agent_API接口设计说明书_V1.0.md | 328953 | 4659754f5939f51316fa41ddc94b4a98fb57933df3f04f7092aef97e3ad2c2db |
| Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md | 84259 | 0b9c5bfb4f5de94758aa54366ef82b7a1665487717bb9f57580f8809143b596b |
| Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md | 52541 | 494f98ea9ccb39d1621e257d8473ee1848dc5bc96ea7a636a26c510c75d7fe4a |
| Request/FinAudit_Agent_测试与验收方案_V1.0.md | 51649 | 43631352a945ce56cabaeafee4d6090def7c9ca0256ecd5a135bfc2b9f52fa7d |
| Request/FinAudit_Agent_部署与运维说明书_V1.0.md | 55466 | 78023778b650260b59232ab1e77a040b512bd12b0ee8a0f7dae29228b241d481 |
| Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md | 107675 | 52a07e78f5776196f2a6fc53d873b478c3f6e3d1dc1bb7a252076fa48c365d7a |
| docs/baseline-manifest.md | 1675 | 9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11 |
| backend/app/approval_pre_meta.py | 22193 | f5ec3483e005902c4cea94ca428ffbaf71c6a3624d4ef0c77c81a7212e4fa881 |

ordered eleven-file pre-state JCS identity固定为：

- raw bytes：2025；
- SHA-256：297ac2e5092433970bd5e6ae225cdd53dd589da21116fb75c923aaa28c62ebc5；
- entry count：11；
- fields：ordinal/path/raw_bytes/raw_sha256。

其exact root为`{"entries":[...],"record_type":"CR011_R7_ELEVEN_FILE_PRE_STATE","version":1}`；entries按上表1..11排列并仅含ordinal/path/raw_bytes/raw_sha256，整体按RFC 8785 JCS编码。

approval_pre_meta.py中的_BASELINE_IDENTITY必须精确指向1675/9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11。Gate B只允许把其中byte_length与sha256两个literal re-pin到post-sync baseline manifest identity。

### 5.2 唯一允许的领域投影

每份Request只允许新增一条R7 revision row与一个R7二级投影；不得包含自身post hash。唯一语义如下：

| 文档 | 允许新增的R7投影 |
|---|---|
| SRS | startup行为零delta；证据=C1/C2→freeze→C3 |
| Architecture | parent-only role、same-process child、role-blind input、单向DAG |
| Database | schema/migration/runtime零delta；DB未授权 |
| API | route/contract/status/error零delta；无evidence API |
| Page | page/route/interaction/state零delta |
| AI/RAG | R3/R5 Policy与AI-D零delta；Provider disabled |
| Test | 12 scenario、1 Gate-B selftest child、36 Gate-C children、26 artifacts、15 negatives、2 reviews |
| Deploy | local offline only；无Docker/real env/deploy/production |
| Plan | Gate A→approval→11-file/tooling Gate B→Gate C→2 reviews→tracking |

baseline manifest恰含9个Request post identity且无self。删除各Request revision/projection须恢复pre bytes；manifest逆变换恢复1675/9733e78c...；pre_meta逆替换两literal恢复22193/f5ec3483...。

### 5.3 协调、回滚与恢复

staging唯一路径为`scripts/.cr011-r7-eleven-sync/`，completed唯一路径为`scripts/.cr011-r7-eleven-sync-completed/`，二者不得同时存在。staging closed tree只允许directories `pre/post`、files `pre/01.raw`..`pre/11.raw`、`post/01.raw`..`post/11.raw`、`prepared.jcs`、`committed.jcs`；全部必须repo内canonical fixed-local-drive、regular single-link、non-reparse、无alias，任一extra或unknown type即fail且不删除任何内容。22份raw按pre/01..11后post/01..11顺序CreateNew/WriteThrough/Flush/close/reread；valid prepared前只允许该序列prefix，写prepared中断时只允许full 22+一个invalid `prepared.jcs`，`committed.jcs`必须缺席。

CR011_R7_SYNC_PREPARED record_type/version固定为同名/1，exact keys为record_type/version/r7_decision_snapshot/pre_state/ordered_entries；11 entries恰为ordinal/path/pre_identity/post_identity/pre_relative_path/post_relative_path/live_temp_relative_path，ordinal=1..11、pre_relative_path=`pre/{ordinal:02}.raw`、post_relative_path=`post/{ordinal:02}.raw`。pre_state及pre/post identity均为RAW_IDENTITY，且必须与§5.1/live内存post/staged raw逐项一致。live temp固定为target sibling `.<filename>.cr011-r7.tmp`。CR011_R7_SYNC_COMMITTED record_type/version固定为同名/1，exact keys为record_type/version/prepared_identity/ordered_live_post_identities；prepared_identity为RAW_IDENTITY，该array恰11项、按ordinal 1..11，每项closed keys恰为ordinal/path/post_identity并逐值等于prepared。两record均closed JCS；unknown/missing/extra/identity/order漂移即invalid。

11个live target、parent与temp在每次CreateNew/read/delete/replace前后均须repo内canonical fixed-local-drive、non-reparse、无alias；parent为真实目录，live/temp为regular single-link，并保持path+FileId绑定。valid prepared且committed缺失/invalid时，写删前必须存在唯一k∈0..11：live 1..k恰为post、k+1..11恰为pre；temp只能全缺席，或k<11时仅有k+1的完整post temp，或k>0时仅有k的完整pre temp，且identity逐byte匹配prepared。任一第三种live bytes、partial/wrong temp、extra或路径漂移立即fail且零写入/删除。

恢复转移唯一：(1) prepared缺失/invalid时要求live all-pre、temp/committed缺席及上述partial tree；先删invalid prepared，再按post/11..01、pre/11..01逆序逐文件删除，最后只删空post/pre/root，禁止recursive；清理中断留下的prefix或empty-dir suffix按同序继续。(2) valid prepared+committed缺失/invalid先做上述live/temp oracle；完整temp仅逐个显式删除，再按k..1逆序从valid pre恢复并保持post-prefix/pre-suffix，验all-pre后删invalid committed，再按1..11重放post。(3) valid committed要求closed tree、all-post、temp全缺席，再原子rename到不存在的completed。(4) completed-only重启复验same root FileId、closed tree、prepared/committed/all-post后继续Gate B review/PASS；其他组合fail closed。completed永久保留且不自动清理。不声称跨文件OS事务。

## 6. 九角色approval

### 6.1 有效批准规则

角色必须恰为以下9项且顺序一致：

需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全

九角色绑定同一R7 snapshot、R6 base、scenario与11-file pre-state；缺失/重复/拒绝/placeholder/field/order/value漂移均为0/9、NOT APPROVED。

### 6.2 exact 40-field approval template

~~~text
姓名=YHBX
角色=需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全
decision=APPROVED
selected_option=AI-D-009～AI-D-014_R3_EXACT_WITH_R4_R5_R6_BASE_AND_R7_MINIMAL_SAME_RUN_REPEATABILITY
selected_decisions=[STARTUP-D-005-R7-MINIMAL-SAME-RUN-REPEATABILITY]
preserved_decisions=[STARTUP-D-001,STARTUP-D-002,STARTUP-D-003,STARTUP-D-004,STARTUP-D-006]
superseded_decisions=[STARTUP-D-005-R6]
rejected_decisions=[]
cr_revision=CR-011-R7
base_revision=CR-011-R6
base_raw_bytes=65121
base_raw_sha256=54a42ade8b20846504e56c6a004503216462f6c71807d0d21c94e74efd087ede
base_decision_preimage_bytes=60493
base_decision_snapshot_sha256=113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815
decision_snapshot_sha256=<R7_GATE_A_OUTPUT>
scenario_manifest_path=scripts/cr011-r7-scenarios.json
scenario_manifest_raw_bytes=2205
scenario_manifest_sha256=9405b63188ffd4082307dc7600485ffcb72fcc0a3b4fc8b3182b0cebb6b3995b
scenario_count=12
eleven_file_pre_state_jcs_bytes=2025
eleven_file_pre_state_digest=297ac2e5092433970bd5e6ae225cdd53dd589da21116fb75c923aaa28c62ebc5
attempt_label=CR011_R7_MIN_ATTEMPT_001
attempt_root_relative_path=build/CR011_R7_MIN_ATTEMPT_001
evidence_claim=TRUSTED_LOCKED_TOOLCHAIN_SAME_RUN_SAME_SCENARIO_C1_C2_FREEZE_C3_EXACT_REPEATABILITY
trust_boundary=TRUSTED_LOCKED_NON_HOSTILE_TOOLCHAIN
visibility_boundary=R6_TOOLHELP_SELF_PID_AND_PYTHON_VISIBLE_ONLY
samples_per_scenario=3
gate_b_guard_selftest_process_count=1
gate_c_success_process_count=36
success_artifact_count=26
negative_case_count=15
post_review_count=2
scope=CR-011-R7_BASE004_MINIMAL_SAME_RUN_STARTUP_EVIDENCE_ONLY
not_claimed=STATIC_TRUTH_OR_MEMBERSHIP_COMPLETENESS|HOSTILE_OR_COLLUDING_TOOLCHAIN|ORDER_OR_TIME_ADAPTIVE_SUBJECT_DETECTION|CROSS_RUN_UNIQUENESS_RETRY_OR_SELECTION_RESISTANCE|NATIVE_DESCENDANT_COMPLETENESS|NATIVE_OS_WINSOCK_OR_WINDOWS_NAMED_PIPE_ZERO|NATIVE_EXTENSION_DELAY_LOAD_OR_ARBITRARY_NATIVE_NEW_MODULE_ZERO|LOCAL_ADMIN_TAMPER_DELETE_REWRITE_OR_REPLAY_RESISTANCE
allowed_actions=VERIFY_R3_R4_R5_R6_AND_CURRENT_ELEVEN|SYNC_COORDINATED_RECOVERABLE_ELEVEN_FILES|BUILD_SEVEN_MINIMAL_TOOLING_FILES|RUN_GATE_B_OFFLINE_TESTS|RUN_ONE_LOCAL_36_CHILD_ATTEMPT|RUN_TWO_POST_REVIEWS|UPDATE_SECTION_9_AFTER_TWO_PASS
forbidden_scope=OBSERVED_AS_STATIC_TRUTH|HISTORY_OR_PRIOR_RUN_AS_CALIBRATION|RETRY_MAJORITY_UNION_INTERSECTION_ROLLING|CHILD_ROLE_ORDINAL_MANIFEST_EXPECTED_DIFF_OR_VERDICT_INPUT|CLAIM_HOSTILE_ADAPTIVE_NATIVE_OR_CROSS_RUN_COMPLETENESS|SECRET_VALUE_READ_PROBE_COMPARE_OR_HASH|STARTUP_TCP|STARTUP_UDP|STARTUP_DNS|STARTUP_TLS|STARTUP_HTTP|STARTUP_SOCKET|APPLICATION_WINDOWS_NAMED_PIPE_USE|PROVIDER|BUSINESS_NETWORK|DATABASE|REDIS|BROKER|CELERY_CONNECTION|REAL_ENV|REAL_DATA|DOCKER|DEPLOYMENT|CANARY|PRODUCTION_RELEASE|GLOBAL_INSTALL|COMMIT|PUSH|PR
authorized_scope=evidence_boundary_successor_only|coordinated_recoverable_eleven_file_sync|seven_offline_tooling_files|trusted_same_run_three_sample_calibration|one_local_attempt|two_independent_post_reviews
日期=2026-08-11
证据链接=本Codex task中的本条批准消息
备注=只批准R7最小同次三样本证据模型及十一文件同步；R6行为禁令与全部NOT_CLAIMED边界不变；runner只可输出CR011_R7_EVIDENCE_READY_PENDING_TWO_REVIEWS，两份独立review均PASS后root才可记录local acceptance。
~~~

template必须恰有40个unique key=value字段和唯一placeholder。首条有效批准冻结第1～8节。

## 7. 失败、清理、成功表述与非授权边界

### 7.1 fail closed

任一identity/process/EOF/protocol/cleanup/R6 gate/outcome/C1=C2/freshness/freeze/lease/order/diff/count/DAG/JCS/Schema/review/权限失败即nonzero并停。同label禁retry/改写/择优；清理partial/handles。再试需新revision+label；local-admin删除/重写/回放/择优为NOT_CLAIMED。

### 7.2 唯一成功表述

仅当26 artifacts完整、runner输出CR011_R7_EVIDENCE_READY_PENDING_TWO_REVIEWS、两review PASS且§9更新后，才允许：

CR-011-R7 retained local evidence accepted: claim=TRUSTED_LOCKED_TOOLCHAIN_SAME_RUN_SAME_SCENARIO_C1_C2_FREEZE_C3_EXACT_REPEATABILITY; attempt=CR011_R7_MIN_ATTEMPT_001; scenarios=12; Gate-C children=36 fresh; C1=C2; manifest frozen and leased before C3; C3 missing/extra/mismatch/duplicate=0; artifacts=26; retry=0; retained R6 child gates=PASS; independent reviews=2 PASS.

紧邻同段必须声明：STATIC_TRUTH_OR_MEMBERSHIP_COMPLETENESS、HOSTILE_OR_COLLUDING_TOOLCHAIN、ORDER_OR_TIME_ADAPTIVE_SUBJECT_DETECTION、CROSS_RUN_UNIQUENESS_RETRY_OR_SELECTION_RESISTANCE、NATIVE_DESCENDANT_COMPLETENESS、NATIVE_OS_WINSOCK_OR_WINDOWS_NAMED_PIPE_ZERO、NATIVE_EXTENSION_DELAY_LOAD_OR_ARBITRARY_NATIVE_NEW_MODULE_ZERO、LOCAL_ADMIN_TAMPER_DELETE_REWRITE_OR_REPLAY_RESISTANCE均为NOT_CLAIMED。

### 7.3 不升级项目状态

Gate C不升级BASE-004 PARTIAL、P0/AC/UAT/业务/API/page/DB/async/provider/Compose/deploy/production，不替代R4 persistent Gate C；commit/push/PR/release未授权，secret/real data/env不得读取。

## 8. decision snapshot与生命周期

文件strict UTF-8/LF、无BOM/NUL/U+FFFD/CR；精确§9 marker全文件一次。preimage取marker行首前bytes，trim末尾LF后加一个LF；PowerShell/Python独立算bytes与lowercase SHA-256一致。§§1–8不得含自身snapshot、Gate B post或run/review identity，且必须绑定scenario 2205/9405b631...、R3–R6/current11、40 fields、13+5 record types、12/1/36/26/15/2及NOT_CLAIMED。§9仅动态状态。首个有效approval后修改§§1–8须至少R8并重置批准。

顺序固定：Gate A双review→九角色批准→协调11-file/tooling Gate B双review→单次Gate C→双post-review→§9 acceptance→tracking。Gate A不授权Gate B/C、child、network、Provider、DB、deploy或production。

## 9. 当前状态

| item | state |
|---|---|
| lifecycle | FIX_18 GATE A CANDIDATE / DURABLE SELFTEST INTENT AND NON-OVERWRITING SYNC RECOVERY / AUTHOR POWERSHELL+INDEPENDENT PYTHON RECALC PASS / TWO FRESH REVIEWS PENDING / NOT APPROVED |
| R7 decision snapshot | 34892 / 97b357f45230b104882cebeb587a947eefe7b091b4925e2a30abddeef258c6c9 |
| author Gate A recalc | PASS；strict UTF-8/LF；marker=1；canonical=34892 bytes；R3–R6；scenario 12/12；approval 40/40 unique；negative 15/15；record types 13+5；current eleven 11/11；planned tooling/selftest/run/sync roots absent |
| R6 bound base | raw 65121/54a42ade...；decision 60493/113568b8...；Gate B PASS；Gate C BLOCKED BEFORE RUN |
| scenario payload | 2205/9405b63188ffd4082307dc7600485ffcb72fcc0a3b4fc8b3182b0cebb6b3995b；12/12 |
| eleven-file pre-state | 2025/297ac2e5092433970bd5e6ae225cdd53dd589da21116fb75c923aaa28c62ebc5；11/11 |
| approval | 0/9；NOT APPROVED；exact 40-field template not yet submitted |
| Gate B | NOT AUTHORIZED / NOT RUN；seven tooling files、guard-selftest result、staging/completed roots absent；eleven-file sync not run |
| Gate C | NOT AUTHORIZED / NOT RUN；attempt root absent；application child count=0 |
| independent reviews | PENDING / PENDING |
| evidence status | no run-inputs、manifest、scenario evidence、run summary或review record |
| claim boundary | trusted same-run repeatability only；all listed NOT_CLAIMED remain NOT_CLAIMED |
| project status | BASE-004/P0/AC/Provider/DB/Redis/Broker/deploy/production unchanged and not upgraded |
| external writes | commit/push/PR/deploy NOT AUTHORIZED / NOT RUN |
| superseded draft | FIX_17 34855/b3a0ef41...、FIX_16 31675/8367da3b...、FIX_15 31482/d04a4068...、FIX_14 30510/5637fee0...、FIX_13 first candidate 32754/948d387b...、FIX_12 647363/7661ad5d... superseded before approval；never authorized or consumed |
