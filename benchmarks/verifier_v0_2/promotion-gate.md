# Verifier 0.2 promotion gate

只有语料资格与性能检查全部通过，`verify_claim` 才能默认启用语义 verdict。评分器返回 `decision=pass|fail` 和逐项失败原因。

## 语料资格

- 运行前封存，retrieval、verifier 代码、模型和 prompt 均已冻结。
- 独立维护、双人标注并完成盲态仲裁。
- 至少 12 篇、100 条 claim、每类至少 20 条、每篇至少 5 条、至少 4 个领域。
- 中英文论文和中英文 claim 均有覆盖。
- 与所有开发集无论文或 paper-family 重叠。

## 默认性能门槛

| 指标 | 门槛 |
| --- | ---: |
| 三分类 Macro-F1 | ≥ 0.85 |
| 错误 `supported` / 所有预测 `supported` | ≤ 2% |
| 数值、单位、数据集、模型、人群、范围、时间、比较或否定样例的错误支持 | 0 |
| `insufficient_evidence` recall | ≥ 0.90 |
| 单篇论文最低准确率 | ≥ 0.70 |
| `unavailable` 比例 | ≤ 2% |
| Evidence ID 合法、grounding、Receipt 存在与回放 | 100% |
| p95 verifier 延迟 | ≤ 30 秒 |
| token/费用记录完整率 | 100% |

平均费用上限由发布负责人在封存前写入 `thresholds.mean_cost_usd_max`；未设置时仍强制完整记录费用，但不据费用决定 pass/fail。门槛一旦随 seal 固定，不得在看到结果后放宽。

任何 critical false support 都直接失败，即使 Macro-F1 仍达标。失败后的样例可进入开发集；修复后必须在未开封的新最终留出集上重新 promotion。
