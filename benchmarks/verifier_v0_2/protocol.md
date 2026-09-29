# Verifier 0.2 frozen evaluation protocol

协议版本：`verifier-promotion-v1`。状态：冻结候选，尚未执行 promotion holdout。

## 角色与数据隔离

1. 语料维护者选择全新论文，保存原字节哈希与提取快照哈希。论文不得与 Round 2、Round 4 或 provider 开发集重叠。
2. 两位标注者独立阅读论文并标注 claim、verdict、必要条件和充分证据；在看到系统输出以前完成仲裁。
3. 执行者只取得论文、claim 和候选 evidence bundle。模型请求中不得出现 verdict、gold Evidence ID、标注理由或风险答案。
4. 在运行前冻结 retrieval 版本、verifier 代码提交、provider、模型标识/修订、prompt 哈希、策略版本、预算和 gate 阈值。
5. 完成所有预测并封存 Receipt 后才开封 gold。开封后该批次转为只读，任何修复都必须使用新的最终留出集验证。

同一个人或同一个模型可以协助开发集，但这种结果必须记录为 `independence_verified=false`，不能通过 promotion gate。

## 文件分离

私有评测至少保存四份不可变文件：

- `inputs.json`：paper、claim、atom 和 evidence，不含 gold。
- `gold.json`：双人标注、分歧、仲裁 verdict 和充分 evidence sets。
- `predictions.json`：原始结构化输出、最终 verdict、延迟、费用和 Receipt ID。
- `seal.json`：前三者在适当阶段的 SHA-256、代码提交和完整冻结配置。

评分前可将必要字段合并为 `PromotionEvaluation`。合并文件含 gold，因此不得交给 verifier backend。

## 语料构成

- 至少 12 篇论文、100 条 claim，每篇至少 5 条。
- 至少 4 个研究领域；中英文论文和中英文 claim 均需出现。
- `supported`、`contradicted`、`insufficient_evidence` 各至少 20 条。
- 覆盖数值、单位、数据集、模型、人群、范围、时间、比较、否定、表格、跨语言、复合论断和缺失证据。
- 同一事实的措辞变体放在同一 paper family，不能跨 train/holdout 泄漏。

## 运行规则

- 每条 claim 固定一个 edition；不能把预印本证据转移到期刊版。
- Evidence ID、excerpt、locator、source hash 和 extraction hash 在运行前固定。
- 重试最多 3 次，只针对传输或 schema 失败；不得根据 gold 选择重试。
- 无效结构化输出、超时和 provider 不可用记为 `unavailable`。
- 所有判断必须产生 Receipt；Receipt 回放必须重新得到相同 evidence 和配置哈希。
