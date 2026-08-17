# 真实 AI 提取质量评测入口

## 目的

`scripts/evaluate_ai_extraction.py` 只负责确定性复算三项 READY 门槛：

- 合同 13 个核心字段精确匹配率不低于 85%；
- 发票 13 个核心字段精确匹配率不低于 95%；
- 所有收到结构化响应的 Provider attempt 合法率不低于 99%。

计算通过不等于正式 AC/UAT 通过。输出始终包含 `formal_acceptance_status=NOT_DETERMINED`。

## 输入要求

输入是最大 16 MiB 的严格 UTF-8 JSON，根结构由 `AiExtractionEvaluationInput` 定义，必须包含：

- 固定 `schema_version=ai-extraction-evaluation-v1`；
- 可追踪的 dataset ID/version 和外部 `approval_ref`；
- `representative=true`；
- 至少一个合同样本、一个发票样本和一个结构化输出 attempt；
- 每个有效样本的 expected/actual 都逐项包含冻结 13 字段；
- 日期和 Decimal 使用业务 DTO 已归一化后的字符串，红票标志使用 Boolean，缺失事实使用 null；
- 无法形成严格输出的样本使用 `output_valid=false, actual=null`，其 13 个字段全部计为未命中；
- 每次收到的初始或修复响应各记一条 `structured_output_attempts`，不得删去结构失败响应。

`representative` 和 `approval_ref` 只是计算输入的追踪字段。数据是否真正代表业务、是否由有权限人员审批，必须由独立 UAT/发布治理验证，不能由实现者自行填写后视为通过。

## 运行

```powershell
$env:PYTHONPATH = 'backend'
& .\backend\.venv\Scripts\python.exe `
  .\scripts\evaluate_ai_extraction.py `
  .\path\to\approved-evaluation.json
Remove-Item Env:PYTHONPATH
```

退出码：

- `0`：三项数值门槛均通过；正式验收仍未决定；
- `1`：至少一个数值门槛失败；
- `2`：参数或输入不合法。

输出只包含 dataset 追踪字段、计数、精确分数和门槛结果，不输出文档正文、标准答案或模型原文。

## 当前状态

当前仓库没有已审批代表性合同/发票评测文件，因此该门禁为“工具已实现、正式运行 `NOT_RUN`”。受限真实 MiniMax smoke 只证明链路，不能填充或替代本评测集。
