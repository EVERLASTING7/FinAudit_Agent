# Synthetic Benchmark Owner-Delegated Review v3

状态：local/test 技术门禁已按 50→100→激活通过；不构成业务代表性、人类 UAT、正式 AC 或 production 验收。

## 版本与证据

- 后继资产：`tests/evaluation/synthetic-benchmark-owner-delegated-review-v3.json`，SHA-256 `AE9B525F2703C22D1A11EDC1FAC28EC52214CF5D306F67CE86F87F522C60E2FA`。
- 前驱 v2 保持字节不变，SHA-256 `1AA98DCC0A35B62F991119065A88B443AF3B71645DC65389BCA3B100F0766384`。
- v2 真实失败证据：`tests/evaluation/synthetic-benchmark-runtime-evidence-v4.json`，SHA-256 `61DE05137F7487EF6884FE849BF550D819E79E509F86D10D027F9AEACF4B4D20`。
- v3 授权收据：`tests/evaluation/synthetic-benchmark-v3-run-authorization-v1.json`，SHA-256 `120618F65F519700E10EC0FB9CAFC94B44B03EE757FAE0A78D732126A2720B72`。
- v3 真实运行证据：`tests/evaluation/synthetic-benchmark-runtime-evidence-v5.json`，SHA-256 `94D645E131832EAA874A248172E333C366586E62F8633948B77712C15138C8CC`。
- 100/50 数量、case ID、标签、权限、制度语料和 v2 发票问题修订均保持不变；本版只修改 `SBCV1-N-APPROVAL-01`。
- `human_review_claimed=false`，仍不是业务代表性数据、人类 UAT、正式 AC 或 production 数据集。

## 稳定根因与修订

真实百炼 v2 运行保留了稳定失败 source case：`SBCV1-N-APPROVAL-01`。原问题询问“代理审批授权最长可以持续多少天”，而允许条款 `SPCV1-APPROVAL-V2#5.2` 明确要求临时提升权限设置到期时间；虽然条款没有最长天数，Embedding 仍会把二者判为高度相关。

修订问题为“按2026-06-30有效制度，付款审批通知是否规定统一的邮件标题格式？”，缺失探针为“付款审批通知邮件标题”。本机离线多语种模型的最高近似从 `0.547008` 降为 `0.453996`；该值只用于碰撞排序，不是百炼分数证明。

## 真实 v3 运行结果

BOSS 在 2026-08-20 明确授权复用仓库既有百炼凭据，按累计最多 10 次请求、50000 input tokens、CNY 10、允许在剩余额度内修复复测的边界执行。运行前零费用预检完成 Alembic head、可丢弃 PostgreSQL/Qdrant、随机 loopback 端口和清理闭环，Provider 请求为 0。

正式运行一次通过且未触发重试：50 条 `mvp_uat` 为 50/50，100 条 `formal_release` 为 100/100，两层 `no_answer_false_positive_rate=0`、`authorization_leak_count=0`；36 个索引成员完成 1024 维向量化，索引在清理前为 `active`。累计 10 次请求、8874 input tokens、CNY 4439 microunits（0.004439 元），10 条成功调用审计投影为 20 个 Event v2 事件；数据库终态核对 2 个独立审批数据集、2 个通过运行和 150 条评测结果。Collection、临时容器、网络及受管环境变量残留均为 0，运行没有输出凭据明文。

本结果只关闭 owner-delegated 合成技术集的 local/test 质量门禁和可丢弃索引激活验证。资产仍固定 `human_review_claimed=false`；业务代表性数据、人类 UAT、production Profile、正式 AC 和真实长期索引激活不由本证据证明。
