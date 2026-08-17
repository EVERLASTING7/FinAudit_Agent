# 代表性性能证据评测入口

## 目的

`scripts/evaluate_representative_performance.py` 只负责确定性复算 `PRODUCT_REQUIREMENTS.md` §8.2 的 READY 门槛：

- 普通列表请求 P95 不高于 800 ms；
- 上传受理请求 P95 不高于 3 s，且不等待长任务完成；
- 单张清晰发票处理 P95 不高于 30 s；
- 二十页合同处理并生成 Markdown 的 P95 不高于 120 s；
- 单次 Top-5 检索 P95 不高于 2 s；
- 完整 RAG 响应 P95 不高于 15 s；
- 至少三个审核任务并行，结果不丢失且不重复采用；
- 同一参考条件下连续至少三轮全部通过。

数值通过不等于正式 AC/UAT 通过。输出始终包含 `formal_acceptance_status=NOT_DETERMINED`。

## 输入要求

输入是最大 16 MiB 的严格 UTF-8 JSON，根结构由 `RepresentativePerformanceEvaluationInput` 定义，必须包含：

- 固定 `schema_version=representative-performance-evaluation-v1`；
- evidence set ID/version、外部 `approval_ref` 和 `representative=true`；
- 参考环境、候选应用版本、硬件、模型、文档和并发 Profile；
- 至少三轮按 `round_number=1..N` 排列、时间不重叠且 `evidence_ref` 唯一的运行；
- 每轮六类工作负载的正整数毫秒原始样本及未成功样本数；
- 每轮上传是否等待长任务，以及并行审核任务数、丢失结果数和重复采用数。

P95 与现有 `local-performance-baseline-v2` 使用同一 nearest-rank 算法：对升序样本取 `ceil(0.95 * N)` 位。任一失败、超时或未形成约定结果的样本必须计入 `unsuccessful_sample_counts`，并使该轮失败，不能用快速错误响应压低 P95。评测器要求所有提交轮次通过，不会从多轮中挑选最佳三轮；原始输入文件、日志和引用凭据仍需由正式证据存储保留。

`representative`、`approval_ref` 和各类 Profile 只是计算输入的追踪字段。实现者填写这些字段不能证明审批真实、样本有代表性或环境属于正式参考环境，必须由独立 UAT/发布治理核验。

## 运行

```powershell
$env:PYTHONPATH = 'backend'
& .\backend\.venv\Scripts\python.exe `
  .\scripts\evaluate_representative_performance.py `
  .\path\to\approved-performance-evidence.json
Remove-Item Env:PYTHONPATH
```

退出码：

- `0`：全部提交轮次的数值与并发门槛均通过；正式验收仍未决定；
- `1`：至少一轮门槛失败；
- `2`：参数或输入不合法。

输出包含 evidence set/Profile 追踪字段、每轮样本数、未成功样本数、P95、阈值和并发结果，不输出原始样本、文档正文、模型响应或凭据。Profile 与引用字段只能填写非密钥标识或说明。

## 当前状态

当前仓库没有已审批的正式参考环境、代表性文档/查询集或连续三轮正式运行输入，因此该门禁为“工具已实现、正式运行 `NOT_RUN`”。既有 `local-performance-baseline-v2` 的小型合成结果不能填充清晰发票、二十页合同、Top-5 或完整 RAG 的正式证据。
