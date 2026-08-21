# Synthetic Benchmark Owner-Delegated Review v2

状态：真实 50 条门禁失败并停止；100 条与激活未运行；不构成业务验收。

## 版本与边界

- 后继资产：`tests/evaluation/synthetic-benchmark-owner-delegated-review-v2.json`，SHA-256 `1AA98DCC0A35B62F991119065A88B443AF3B71645DC65389BCA3B100F0766384`。
- 前驱 v1 资产保持字节不变，SHA-256 `87F5627F0306AA4D5B89E148EB0B4C8D970E80956CFAE624F0783BB66B3DA70F`；两次 49/50 历史证据继续绑定 v1。
- 100/50 数量、case ID、标签、权限、制度语料和禁止证据均不变；只修改 `SBCV1-N-INVOICE-02` 的问题和缺失探针。
- `human_review_claimed=false`，仍不是业务代表性数据、人类 UAT、正式 AC 或 production 数据集。

## 离线根因诊断

历史失败只保留 runtime UUID，清理后无法可靠映射 source case。当前离线复核使用本机已缓存的 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，全程 `local_files_only`，Provider 调用为 0。

- 十个 `no_answer` 中，只有 `SBCV1-N-INVOICE-02` 的最高相似度 `0.663592` 越过评测阈值 `0.650000`，最接近 `SPCV1-INVOICE-V2#3.2`。
- 原问题“纸质发票原件应在开票后几天内寄达？”与允许条款中的“原票与候选票”形成语义碰撞。
- 修订问题为“发票影像归档文件需要保留多少年？”，同一离线近似模型的最高相似度降为 `0.466334`。
- 离线分数只用于确定下一次诊断候选，不是百炼分数证明；是否关闭根因必须由真实 50 条重跑确认。

## 真实 v2 运行结果

BOSS 明确授权复用现有百炼凭据后，v2 在可丢弃 PostgreSQL/Qdrant 中运行。50 条结果仍为 `49/50`，稳定失败 source case 为 `SBCV1-N-APPROVAL-01`；5 次请求、4969 input tokens、CNY 2485 microunits，授权泄露 0，零重试。Runner 按约定未运行 100 条或激活，并删除 Collection 与两个专用容器；聚合证据见 `tests/evaluation/synthetic-benchmark-runtime-evidence-v4.json`。

真实结果推翻了本版对 `SBCV1-N-INVOICE-02` 的离线归因。`SBCV1-N-APPROVAL-01` 的“代理审批授权最长天数”与允许制度中“临时提升权限必须设置明确到期时间”语义过近；后继修订见 `docs/testing/synthetic-benchmark-owner-delegated-review-v3.md`。本次单次授权已经消耗。
