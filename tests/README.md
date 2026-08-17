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
- 5 条 RET-001 仅是冒烟集，不满足正式不少于 100 条的检索门禁。
- 没有实建账号、独立环境或环境重建演练。
- 没有运行 API、数据库、Worker、浏览器或真实/测试模型。
- S3～S6 负例及输入不变量只是静态契约，尚未经过项目解析器、分块器、AI Gateway 或引用校验器运行。
- manifest、生成器与矩阵通过只证明资产静态自洽，不代表任何 AC、后续 TEST 任务或完整 TEST-001 通过。
