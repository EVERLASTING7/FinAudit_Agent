# CR-026：local/test 批量检索评测授权

状态：APPROVED / CONSUMED
记录日期：2026-08-18
批准来源：BOSS 当前对话明确允许批处理、复用现有百炼密钥并将请求上限调整为 100；CR-025 Local MVP 常驻运行仍不启用 AI Provider

## 决定

- 本次单次 `local/test` 运行固定 `minimax-m3-bailian-qwen37-local-v2`、`qwen3.7-text-embedding`、1024 维和单批最多 20 条；常驻 Local MVP 仍保持 `AI_PROVIDER_CALLS_ENABLED=false`。
- 受保护 benchmark runner 可以在未来获批的单次 `local/test` 运行中把多个评测问题放入同一 Embedding 请求；每个问题仍产生独立检索结果，批次 completion 与该评测运行的全部结果在同一 PostgreSQL 事务采用。
- 本次运行上限为 Provider 请求 100、input tokens 50000、费用 CNY 10，禁止汇率换算、production、自动扩容和重试。
- 先执行固定 50 条 `mvp_uat`；失败立即停止。只有 50 条通过，才允许执行固定 100 条 `formal_release`。
- 禁止输出密钥、向量、问题全文、制度原文或其他原始敏感文本。

## 实现边界

- Production 和普通 Worker 默认继续逐题调用；只有本次 runner 显式设置评测批次 20。
- 冻结数据集、复核结论、模型、维度、索引成员与质量阈值均不修改。
- 冻结调用计划为索引 2 次、50 条 3 次、100 条 5 次，完整成功最多 10 次；50 条失败最多 5 次。
- 该技术评测不构成业务代表性、人类 UAT、production 或正式 AC 接受。
- 本次授权消耗后，任何再次真实运行仍必须由 BOSS 重新明确密钥复用、数据集、环境、请求/Token/费用上限和失败停止条件；仅存在 `.env`、代码或本 CR 不得视为后续授权。

## 验证

- Provider 前必须通过 runner 单测、Ruff、mypy、完整离线门禁和 PostgreSQL current-head 双轮门禁。
- 运行后必须核对 Event v2、请求数、Provider 权威 Token/CNY 费用、50→100 顺序和专用 PostgreSQL/Qdrant 清理。
- Provider 前离线代码、完整质量门禁和数据库合同均已通过。

## 运行结果

- 实际请求 5 次、input tokens 4971、费用 CNY 0.002486，均低于授权上限；自动重试 0。
- 50 条结果为 49/50、授权泄露 0；1 个 no-answer 假阳性使质量门禁失败。
- runner 按约定立即停止；100 条、索引激活和任何新增 Provider 请求均未执行。
- Event v2 completion 已随索引和 50 条结果事务采用；成功路径后置 `ai_call_logs` 投影核对因质量失败未运行，投影行数未保留且不得补造。
- 本次未保留失败 case ID；后续 runner 已离线加固为只输出合成 case ID，仍禁止输出问题、制度原文或向量，且不授权重跑。
- Qdrant Collection、专用 PostgreSQL/Qdrant 容器和确认环境变量残留为 0。
- 本次单次授权已经消耗；任何再次真实调用都需要新的明确授权。

## 第二次单次诊断复跑

- BOSS 随后使用同一硬边界再次明确授权一次运行，并允许只输出合成失败 case ID。
- 结果再次为 5 次请求、4971 input tokens、CNY 0.002486、49/50、授权泄露 0、1 个 no-answer 假阳性；100 条、激活和重试仍未运行。
- 捕获的 `7623955c-d413-44be-ab26-82ab25e24301` 是可丢弃数据库生成的 runtime case UUID；本次 runner 未同时保留冻结资产的稳定 case ID，数据库清理后无法映射到问题，不得把该 UUID 描述为已定位源用例。
- Runner 已在离线阶段补充 runtime UUID→冻结 source case ID 映射，未来授权运行只输出稳定合成 case ID，不输出问题文本、制度原文或向量；该加固不授权第三次调用。
- 第二次单次授权已经消耗，专用 Collection、容器和确认环境变量残留为 0。
