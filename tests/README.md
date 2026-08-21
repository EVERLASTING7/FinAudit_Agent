# TEST-001 PARTIAL / S1-S6 测试资产

本目录包含 39 条版本化合成 JSON fixture 和 14 个确定性二进制文档/图片 fixture，不包含可执行的业务测试套件。所有样本均为显著标记的合成测试数据。

## 消费方式

1. 以 `tests/fixtures/manifest.json` 为入口。
2. 消费方先验证 `dataset_version` 为 `1.6.0`、`binary_fixture_contract_version` 为 `1.0.1` 且 `synthetic` 为 `true`。
3. 按 manifest 中的固定直接子文件路径读取资产，并核对字节长度和 SHA-256。
4. JSON 资产按 `required_ids` 选择稳定样本；二进制资产按固定 `id`、场景、关联 fixture 与 P0 任务消费，不依赖数组顺序。
5. JSON fixture 必须保持 Request 已明确的最小语义：六个固定活动账号的角色/状态/职责边界、C-001 双方名称和核心业务固定验收值、七个标量安全负例的固定输入、五个结构化安全负例的输入不变量与十二类预期，以及 `RET-001-01`～`05` 的固定问题、分类、证据锚点和数值 Top-5。这只校验测试数据语义，不代表业务实现、注入防御或账号已创建。
6. 校验器不额外固定 Request 未明确的字段集、顺序、正式评测集 Schema、Provider 行为或待 CR 批准的参数。
7. 时间、随机 seed 和 UUID 由测试显式固定；金额按十进制字符串处理。

在仓库根目录执行离线校验：

```powershell
powershell -NoProfile -File scripts/verify-test-assets.ps1
powershell -NoProfile -File scripts/test-verify-test-assets.ps1
```

对隔离副本可显式指定项目根：

```powershell
powershell -NoProfile -File scripts/verify-test-assets.ps1 -ProjectRoot 'D:\path\to\isolated-copy'
```

成功输出包含 `TEST_ASSETS_VERIFY=PASS`、`P0_TASKS=86`、`FIXTURE_ITEMS=39` 和 `BINARY_ASSET_ITEMS=14`。失败返回非 0，且错误只报告文件或规则位置，不输出被检测内容。

负向自测成功输出 `NEGATIVE_CASES=39`、`ISOLATED_POSITIVE_CASE=PASS` 和 `DIRECTORY_REPARSE_CASE=PASS`；P0 矩阵任务集及精确六列宽度、manifest 的 4 个 JSON/14 个二进制集合、账号固定角色/状态/职责边界与 break-glass、C-001 金额与双方名称、重复发票元组、P-001-V2 名称/5.1 条款、超长分块例外、安全负例 ID/输入/预期、RET 固定基线、JSON/二进制版本轴，以及 JSON 数值/Boolean 与二进制 manifest 整数/数组类型篡改，在同步 manifest 哈希后仍会被对应门禁拒绝。文件符号链接需要当前 Windows 账户具备创建权限，否则必须明确输出 `REPARSE_CASE=NOT_RUN`，不能记为已覆盖。

## synthetic-non-acceptance-v1

`tests/evaluation/synthetic-non-acceptance-v1.json` 是独立的本地非验收检索资产，不进入上述固定 39 条 fixture manifest。它基于仓库中的 P-001 制度、RET-001 与安全负例生成 120 条候选，按规范化问题 SHA-256 去重为 100 条，并固定 50 条子集；覆盖 `answerable/no_answer/unauthorized`，同时携带来源清单、覆盖矩阵、证据核验和百炼 Embedding 付费预算预估。

```powershell
backend\.venv\Scripts\python.exe scripts\generate_synthetic_non_acceptance_dataset.py --check
```

该资产固定 `provider_calls_executed=0`、`index_activation=not_run`、`approval_state=not_submitted` 和空 runtime tier；它没有数据库 UUID，后续运行前必须把仓库引用映射到当次实际 Policy/Chunk 身份并重新审批。不得将其数量、静态证据或预算预估写成正式质量、索引激活、UAT、AC 或 production 证据。

## synthetic-policy-corpus-v1 / synthetic-benchmark-candidate-v1

`tests/evaluation/synthetic-policy-corpus-v1.json` 是只用于 local/test 的虚构制度语料：覆盖费用报销、供应商、发票、合同、审批权限和审计留痕 6 个领域，每个领域含两个不重叠有效版本和每版 3 条证据条款，共 `6/12/36`。语料只使用“虚构测试组织”及合成阈值，不含真实个人、企业、账户、交易或财务记录。

18 条高价值候选的原始人工复核工作单位于 `docs/testing/synthetic-benchmark-human-review-v1.md`，其结论栏仍不冒充人工签名。v1/v2 与对应失败运行保持不可改写；v3 只修订真实 v2 运行保留的失败 source case `SBCV1-N-APPROVAL-01`，继续固定 `human_review_claimed=false`，不创建人类 UAT 或业务代表性批准。

`tests/evaluation/synthetic-benchmark-candidate-v1.json` 以该语料生成 120 条候选，提议 100 条但保持 `proposal_only`，并固定其中 50 条 `mvp_uat` 候选子集。120/100/50 的标签分布分别为 `72/24/24`、`60/20/20`、`30/10/10`；每条都绑定基准日期、角色权限、允许制度和禁止命中证据，answerable 另绑定预期证据，no_answer 另绑定缺失探针。

```powershell
backend\.venv\Scripts\python.exe scripts\generate_synthetic_policy_benchmark_assets.py --check
backend\.venv\Scripts\python.exe scripts\prepare_synthetic_benchmark_reviewed_assets.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_synthetic_policy_benchmark_assets.py
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_synthetic_benchmark_reviewed_assets.py backend\tests\unit\test_runtime_evidence_assets.py
```

生成器对候选 ID/规范化问题重复、版本有效期矛盾、证据缺失、no_answer 探针、权限标签、跨权限边界和问题自然度执行确定性检查。真实 v2 运行以 5 次请求、4969 input tokens、CNY 0.002485 得到 49/50，并保留稳定失败 ID `SBCV1-N-APPROVAL-01`；v3 将该问题改为“付款审批通知邮件标题”缺失探针。新的授权收据随后固定累计 10 请求、50000 input tokens、CNY 10 和仅剩余额度可复测；真实 v3 一次完成 50/50、100/100 与可丢弃索引激活，实际 8874 input tokens、CNY 0.004439、零重试、零授权泄露/no-answer 假阳性和零资源残留。精确聚合证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v5.json`。

## public-business-benchmark-runtime-v1

`tests/evaluation/public-business-benchmark-runtime-v1.json` 只保存公开来源的计数、Hash 和运行状态；真实合同、票面、税号、当事人及标注值只位于 Git 忽略的 `data/public-benchmark/`。来源包括 CUAD、10 份官方中文政府采购合同公告及附件、Zenodo 813 份公司票据和 XFUND 50 份中文表单。

```powershell
backend\.venv\Scripts\python.exe scripts\verify_public_business_benchmark.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_public_business_benchmark_evidence.py backend\tests\unit\test_document_parser.py
```

成功复算输出 `PUBLIC_BUSINESS_BENCHMARK_RUNTIME=MEASURED_FAILED_EVIDENCE_PASS`，表示证据复算成功，不表示质量通过。当前 CUAD 12/12、490 页经 PDF 默认文本 fallback 解析成功，但冻结字段直接命中为 0；10 份中文扫描合同、50 份真实票据和 50 份中文表单因 OCR 默认关闭而失败。合同来源覆盖 9/13、发票覆盖 7/13；55 个自然重复组缺项目必需的 `invoice_code`，风险数据也没有与 15 条规则匹配的独立结果标签。因此合同 85%、发票 95%、重复、风险和完整多格式质量仍不得标记通过。

## public-windows-ocr-pilot-v1

`tests/evaluation/public-windows-ocr-pilot-v1.json` 是同一公开源上的零付费本机 OCR 技术测量。它通过 `scripts/windows-media-ocr-batch.ps1` 调用 Windows 原生 `en-US/zh-Hans-CN` OCR，由 `scripts/benchmark_public_windows_ocr.py` 在临时目录准备 77 个图片页、评分并删除临时 OCR 原文；默认 Local MVP 配置不变。

```powershell
backend\.venv\Scripts\python.exe scripts\benchmark_public_windows_ocr.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_public_windows_ocr_pilot_evidence.py
```

复算输出 `PUBLIC_WINDOWS_OCR_PILOT=MEASURED_FAILED_EVIDENCE_PASS`。20 份真实票据直接字段 `28/140 = 20%`，20 份 XFUND 中文表单实体召回 `1169/1418 = 82.4401%`，3 份中文扫描合同直接字段可见率 `7/27 = 25.9259%`。本地 `qwen3:8b` 的生产 Schema grammar 因 `\d` 不受 Ollama 0.32.5 支持而 HTTP 400，全量 JSON 模式在 300 秒超时；第三次只保留字段关键词及相邻行、最多 80 block，在 107.8 秒完成但输出未通过生产 Validator，`0/9` 字段可采用。零自动重试、零外网、零费用、零采用，进程和 listener 清理为 0。这是失败证据，不是 OCR/AI Provider 已启用或质量通过。

## public-extractbench-qualification-v1

`tests/evaluation/public-extractbench-qualification-v1.json` 绑定 LlamaIndex ExtractBench revision `f6180e917a050a84582e6366cff85b7dc1e84e58` 的 370 行/4869 页元数据、325 份真实文档，以及 8 份公开真实发票的原文 Hash。原始 JSONL、PDF 和逐字段答案只位于 Git 忽略的 `data/public-benchmark/extractbench/`。

```powershell
backend\.venv\Scripts\python.exe scripts\verify_public_extractbench_benchmark.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_invoice_extractor.py backend\tests\unit\test_public_extractbench_qualification.py
```

英文确定性标签修复后，默认 Profile 的代理精确匹配为 `48/104 = 46.1538%`，非空标注为 `32/83 = 38.5542%`；2 份扫描 PDF 仍因 OCR 关闭失败。来源直接覆盖 10/13，`is_red_invoice` 由标准类型推导，`invoice_code` 与买方税号仍是来源 Schema 缺失假设，因此正式 13 字段门禁不可计算。证据 SHA-256 为 `0A7F94B0A8941129D8A3CB759EF441FA35E074397606424504C5BC21AD2DECBC`。

## public-docubench-qualification-v1

`tests/evaluation/public-docubench-qualification-v1.json` 绑定 DocuBench revision `43a3f3bc00e591e711075678ca6d154acfedcf42` 的 72 份/448 页、12 种语言、10 种格式及人工核验 Schema/标签聚合 Hash。原文和标签值只在 `%LOCALAPPDATA%/FinAuditAgent/public-benchmark/` 的 revision 专用缓存；可用 `FINAUDIT_PUBLIC_DOCUBENCH_ROOT` 显式覆盖。

```powershell
backend\.venv\Scripts\python.exe scripts\verify_public_docubench_benchmark.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_public_docubench_qualification.py
```

当前项目支持的 65 份 PDF/JPEG/PNG/DOCX 中，34 份解析通过，23 份扫描 PDF 与 6 份图片因 OCR 关闭失败，2 份 PDF fail-closed，另记录 12 次旋转文本输出不完整警告。最佳税务发票仍缺 `invoice_code`，最佳合同仅 4/13；直立/旋转同标签样本是收据，不是重复发票。证据 SHA-256 为 `2D6F9E8F56B24FCBC8349807CB8E215A0CD8190B2C850F7ECFAA481F9887F3CB`。

## public-local-qwen-invoice-pilot-v1

`tests/evaluation/public-local-qwen-invoice-pilot-v1.json` 是不改变默认 Profile 的零费用紧凑模型测量。它复用 ExtractBench 8 份真实发票、产品 PDF Parser、Poppler、Windows Media OCR、严格 13 字段 Schema 和确定性证据回绑；Ollama 必须已经由操作者显式启动且存在 `qwen3:8b`，日常离线门禁不会运行模型。

```powershell
backend\.venv\Scripts\python.exe scripts\benchmark_local_qwen_invoice_compact.py
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_local_qwen_invoice_compact.py
```

GPU 4096/2048 context 在真实输入上均 CUDA OOM；固定纯 CPU、2048 context、最多 40 个首尾相关块后，8/8 输出结构合法。模型事实为 `81/104=77.8846%`，严格证据回绑后为 `82/104=78.8462%`，74 个非空事实绑定 74 条证据，总推理 295.203 秒。语义强化 Prompt 曾降至 76.92%，已回退且不作为证据。最终证据 SHA-256 `BC9DC120365269129BD71981E80BD93360B919860C4444297E3DE0F31E546C72`；结果低于 95%，不得启用默认 AI 或标记 AC。

## local-p2-experience-compatibility-v1

`tests/evaluation/local-p2-experience-compatibility-v1.json` 固化报告下载/制品兼容性与 local/test 可访问性技术覆盖。运行使用合成数据、可丢弃 PostgreSQL/MinIO、Chrome/Edge、Microsoft Excel、LibreOffice Calc 和 Windows Narrator；Narrator 只持久化本轮焦点时间窗的事件计数，原始 ETL、语音、转写和页面内容均不保留。

```powershell
.\scripts\verify-report-browser-gate.ps1 -Mode Report -Port 4181
.\scripts\verify-report-browser-gate.ps1 -Mode Accessibility -Port 4182
.\scripts\verify-report-artifact-compatibility.ps1 -RequireExcel -RequireLibreOffice
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_p2_compatibility_gates.py
```

成功输出包括 `REPORT_BROWSER_GATE=PASS`、`EDGE_NARRATOR_SCREEN_READER_GATE=PASS`、`ACCESSIBILITY_BROWSER_GATE=PASS` 和 `REPORT_ARTIFACT_COMPATIBILITY=PASS`。该证据关闭 Blob 原生下载、LibreOffice Calc、Edge 20 路由矩阵和 Narrator 技术运行缺口；不替代残障用户人工验收、代表性业务 UAT、production 或正式 AC。

## 二进制资产维护

生成器固定使用 Python 3.12.13，精确库版本记录在 `scripts/requirements-test-assets.txt`；下方 `python` 必须解析到该解释器，否则脚本会在生成前失败。普通校验只运行 `--check`；只有明确更新 fixture 版本时才运行会覆盖 14 个二进制文件的 `--write`。

```powershell
python -m pip install -r scripts/requirements-test-assets.txt
python scripts/generate_test_documents.py --check

# 仅在维护已评审的 fixture 版本时执行
python scripts/generate_test_documents.py --write
python scripts/generate_test_documents.py --check
```

生成器固定文档元数据、ZIP 时间戳、图片变换和输出顺序，并对使用的本机字体做指纹门禁；缺少匹配字体时会失败，不会静默生成不同字节。

`dataset_version` 只跟踪四个 JSON fixture 的语义契约；`1.6.0` 在 S5 两个注入负例基础上增加表格单元格角色覆盖和用户伪造候选 ID 两个结构化安全负例。`binary_fixture_contract_version` 单独跟踪 14 个二进制资产及其 manifest 契约；`1.0.1` 是不改变 ID、路径、场景和任务映射的正文修订。生成器从已受 Request 语义门禁保护的 `core_business.json` 读取 C-001 主体名称/税号和 P-001 名称，使 `verify-test-assets.ps1` 与 `generate_test_documents.py --check` 共同约束 JSON 和二进制内容。

## 当前限制

- 没有 Compose、CI、`conftest`、factory 或 coverage 配置。
- PDF/DOCX/PNG/JPEG 的离线检查仅验证固定清单、路径、大小、哈希和最低静态包络；它不是 PDF/DOCX 业务解析、OCR 质量、页码/坐标或上传 API 验证。
- 未在仓库中常驻 50/51 MB 或 20/21 文件边界样本；这些应在后续上传测试中按最终统一的字节单位和 API 契约临时生成。
- 5 条 RET-001 仅是冒烟集；多领域 120→100→50 资产已完成 owner-delegated 非人类技术复核，并在最新 local/test 真实运行通过 50/50、100/100 与可丢弃索引激活；它仍没有业务代表性审批、人工 UAT 或正式签署，因此不能替代正式检索验收。
- 固定 fixture 自身不包含可登录账号或持久目标环境；项目另有可丢弃 local/test 数据库、Worker、浏览器和 Provider 分层运行证据，不能反向把静态 fixture 标记为运行验收。
- S3～S6 负例及输入不变量的覆盖必须按各自矩阵行读取；静态资产自洽不能替代完整解析器、分块器、AI Gateway、引用校验器或正式安全验收。
- manifest、生成器与矩阵通过只证明资产静态自洽，不代表任何 AC、后续 TEST 任务或完整 TEST-001 通过。
