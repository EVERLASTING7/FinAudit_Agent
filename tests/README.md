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

18 条高价值候选的原始人工复核工作单位于 `docs/testing/synthetic-benchmark-human-review-v1.md`，其结论栏仍不冒充人工签名。BOSS 后续委托 Agent 完成 local/test 技术语义复核并生成 `tests/evaluation/synthetic-benchmark-owner-delegated-review-v1.json`：12 条原样接受、6 条修订接受，全部 20 条 no_answer 重写复核；资产明确 `human_review_claimed=false`，不创建人类 UAT 或业务代表性批准。

`tests/evaluation/synthetic-benchmark-candidate-v1.json` 以该语料生成 120 条候选，提议 100 条但保持 `proposal_only`，并固定其中 50 条 `mvp_uat` 候选子集。120/100/50 的标签分布分别为 `72/24/24`、`60/20/20`、`30/10/10`；每条都绑定基准日期、角色权限、允许制度和禁止命中证据，answerable 另绑定预期证据，no_answer 另绑定缺失探针。

```powershell
backend\.venv\Scripts\python.exe scripts\generate_synthetic_policy_benchmark_assets.py --check
backend\.venv\Scripts\python.exe scripts\prepare_synthetic_benchmark_reviewed_assets.py --check
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_synthetic_policy_benchmark_assets.py
backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_synthetic_benchmark_reviewed_assets.py backend\tests\unit\test_runtime_evidence_assets.py
```

生成器对候选 ID/规范化问题重复、版本有效期矛盾、证据缺失、no_answer 探针、权限标签、跨权限边界和问题自然度执行确定性检查。生成阶段 Provider 请求为 0；owner-delegated 技术复核只允许 local/test 创建可丢弃 approved 数据集，不改变业务代表性、人工 UAT 或 AC。历史逐题运行的精确 usage 未留存，见 v1 证据；`CR-026` 批量运行随后以 5 次请求、4971 input tokens、CNY 0.002486 得到 49/50 和授权泄露 0，因 1 个 no-answer 假阳性立即停止，100 条与激活未运行。精确聚合证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v2.json`；本次授权已消耗，再次运行必须取得新的明确单次 Provider 授权。

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
- 5 条 RET-001 仅是冒烟集；多领域 120→100→50 资产已完成 owner-delegated 非人类技术复核并在最新真实运行得到 49/50，但 50 条门禁仍失败，且没有业务代表性审批、人工 UAT 或正式签署，因此仍不满足正式检索门禁。
- 固定 fixture 自身不包含可登录账号或持久目标环境；项目另有可丢弃 local/test 数据库、Worker、浏览器和 Provider 分层运行证据，不能反向把静态 fixture 标记为运行验收。
- S3～S6 负例及输入不变量的覆盖必须按各自矩阵行读取；静态资产自洽不能替代完整解析器、分块器、AI Gateway、引用校验器或正式安全验收。
- manifest、生成器与矩阵通过只证明资产静态自洽，不代表任何 AC、后续 TEST 任务或完整 TEST-001 通过。
