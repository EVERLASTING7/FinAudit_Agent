# Synthetic Benchmark Owner-Delegated Review v1

状态：local/test 技术复核完成；真实 `mvp_uat` 运行失败；不构成业务验收。
日期：2026-08-17

## 来源绑定

| 资产 | 用途 | SHA-256 |
|---|---|---|
| `tests/evaluation/synthetic-policy-corpus-v1.json` | 六类虚构制度、12 个版本、36 条证据条款 | `2CE2BE5118ADAC7D185D239AFD4713D3F637BDF9D12D314D7690732A8DFAD9E3` |
| `tests/evaluation/synthetic-benchmark-candidate-v1.json` | 120 条候选、100 条提议集、固定 50 条子集 | `A5A9C179B6F344C5CDA8B50089AC85254E87BDB62694D6B9360A6F5D46327C03` |
| `tests/evaluation/synthetic-benchmark-owner-delegated-review-v1.json` | 委托语义复核后的 100/50 技术集 | `87F5627F0306AA4D5B89E148EB0B4C8D970E80956CFAE624F0783BB66B3DA70F` |

语料仅来自仓库合成资产，不包含真实个人、企业或财务数据。复核权限引用为 `BOSS-LOCAL-TEST-DELEGATION-20260817`；复核方式为 owner-delegated Agent semantic review，明确 `human_review_claimed=false`。

## 覆盖与复核结果

- 120 条候选覆盖报销、供应商、发票、合同、审批权限、审计留痕六个领域，各 20 条；标签为 `72 answerable / 24 no_answer / 24 unauthorized`。
- 100 条正式技术候选为 `60/20/20`，领域分布为 `17/17/17/17/16/16`；固定 50 条 `mvp_uat` 子集为 `30/10/10`，领域分布为 `9/9/8/8/8/8`。
- 所有用例绑定基准日期、允许制度和预期证据或禁止命中证据；覆盖有效期、制度版本、同义改写和跨权限场景。
- 8 项确定性检查均为 0 异常：重复、有效期/版本矛盾、证据完整性、no-answer 缺失探针、权限标签、问题自然度、100/50 计数和非验收边界。
- 原 18 条复核队列全部完成：12 条原样接受，6 条修订后接受；同时重写并复核全部 20 条 `no_answer` 问题，使其成为合理的业务缺失信息问题。待处理数为 0。

这只批准在 local/test 中创建可丢弃的技术评测数据集并运行门禁，不把资产升级为业务代表性数据、人类 UAT、formal AC 或 production 数据集。

## 预算与真实运行结果

批准的单次计划为 36 条款两批索引 + 50 条 `mvp_uat` + 100 条 `formal_release`，最多 152 次 Provider 请求、50000 input tokens、CNY 1 元、no-fx、no-production、零重试。运行前 UTF-8 上界估算为 16576 input tokens、CNY `0.008288`。

第一次基础接线检查在 Provider 前因 DOCX 错用 PDF-only scanner 停止，实际 Provider 请求、Token 和费用均为 0；随后改为复用仓库多格式 clean scanner。批准的付费单次运行完成 36 条款处理、两批索引并使索引达到 `ready`，但在 50 条 `mvp_uat` 质量门禁返回 `MVP-UAT-050_EVALUATION_FAILED` 后立即停止：

- 100 条 `formal_release`：`NOT_RUN`。
- 索引激活：`NOT_RUN`；临时索引清理前保持 `ready`。
- 自动重试：0；未再次调用 Provider。
- Qdrant Collection、PostgreSQL/Qdrant 专用容器：全部清理，残留 0。
- 本次失败前精确请求数、input tokens、CNY 费用和标签级指标：`UNKNOWN_NOT_PERSISTED`。可证明的安全上界为最多 52 次请求、50000 input tokens、CNY 1 元；不得把时间推测写成实际值。

失败后 runner 已增加安全失败遥测，会在未来获新授权的运行中输出请求数、Token、CNY 费用、tier、失败码和聚合指标，不输出密钥、问题、制度原文或向量。该修复不能追溯补造本次缺失数据。机器证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v1.json`。

2026-08-18，BOSS 通过 `CR-026` 另行授权同一冻结数据集采用 local/test 批量评测，硬上限为 100 次 Provider 请求、50000 input tokens、CNY 10、零重试、50 条失败即停且只有通过才可继续 100 条。production 默认仍逐题；本次 runner 固定索引 2 批、50 条 3 批、100 条 5 批。

本次真实运行在 50 条门禁按设计停止：Provider 请求 `5` 次、权威 input tokens `4971`、费用 `CNY 0.002486`，49/50 通过，授权泄露 0；`document_hit_at_5/evidence_hit_at_5/recall_at_5/MRR` 均为 1.0，`precision_at_5=0.9666666666666667`，唯一失败来自 10 个 no-answer 用例中的 1 个假阳性，`no_answer_false_positive_rate=0.1`。100 条 `formal_release` 与索引激活均 `NOT_RUN`，自动重试为 0；Qdrant Collection 已删除，专用 PostgreSQL/Qdrant 容器和确认环境变量残留为 0。精确机器证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v2.json`。

5 个批次的 Event v2 completion 已与可见索引/50 条评测事实按事务采用；但 50 条质量失败发生在 runner 的成功后置 `ai_call_logs` 投影核对之前，专用数据库随后按授权清理，因此本次投影行数明确为 `NOT_RUN / not retained`，不得从权威 Provider usage 反推或补造。本次 runner 也未保留失败 case ID；后续离线加固只允许输出合成 case ID，不输出问题文本、制度原文或向量，且不构成再次调用授权。

BOSS 随后在相同边界下再次单次授权诊断复跑。结果完全复现为 5 次请求、4971 input tokens、CNY 0.002486、49/50、授权泄露 0 与 1 个 no-answer 假阳性，100 条仍未运行。安全输出捕获 runtime case UUID `7623955c-d413-44be-ab26-82ab25e24301`，但该 UUID 由可丢弃数据库生成，runner 当时未保留到冻结 source case ID 的映射，清理后无法反查具体问题。机器证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v3.json`；runner 后续只做离线映射加固，第二次授权已消耗且未第三次调用。

## 验收边界

本轮证明了可丢弃 local/test 技术集的可追溯复核、审批状态机、真实索引链和质量失败时的安全停机。它没有证明 50/100 条质量达标、业务代表性、`formal_release`、索引激活、production、人工 UAT 或任何 AC accepted。
