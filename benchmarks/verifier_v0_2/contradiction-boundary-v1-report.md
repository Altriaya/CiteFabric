# Contradiction boundary v1 实验报告

实验日期：2026-09-29。该实验使用已经开封的 Round 2 开发集，`promotion_eligible=false`、`independence_verified=false`。它用于校准 verifier 的 contradiction 边界和检查真实 provider 集成，不能作为默认上线的 promotion 证据。

## 冻结条件

- 输入：`benchmarks/round2.json`，SHA-256 为 `0e87c71441b11070ee2716918576e03492c39271eaa7c98a4738a14a3fafb5a7`。
- Evidence：`output/validation/offline_round2_zh_v4_20260921` 中已冻结的 evidence bundle。
- 主模型：QuickRouter `gpt-5.5-2026-04-23`。
- 第二模型：QuickRouter `gpt-5.4-2026-03-05`，只复核主模型与旧 gold 分歧的三条。
- Prompt：`openai-semantic-verifier-v1`，SHA-256 为 `752eb60a8299a556431cd598f88a5b7e17af46cc124c19ee8bc3b1280dec591e`。
- Gold 在所有模型调用完成以后才用于评分，没有发送给模型。

## 边界集结果

12 条样例全部完成。相对 Round 2 旧 gold，主模型命中 9/12（75%）；所有分歧都是旧 gold 为 `contradicted`、模型为 `insufficient_evidence`，没有错误的 `supported` 或错误的 `contradicted`。

| Case | 旧 gold | GPT-5.5 | GPT-5.4 复核 | 开发集仲裁 |
| --- | --- | --- | --- | --- |
| Q05 | contradicted | insufficient | insufficient | insufficient |
| Q09 | contradicted | insufficient | insufficient | insufficient |
| Q35 | contradicted | insufficient | insufficient | insufficient |

仲裁只依据冻结 evidence bundle：

- Q05 的片段没有包含判断“每个数据集”所需的全部表格单元格。
- Q09 的片段没有给出穷尽的数据集列表，也没有明确排除 ETTm1。
- Q35 定义了 pLDDT 的结构置信度用途，但没有排他地声明它不能衡量生物功能。

据此补充并冻结 `gold-rubric.md` 的 contradiction 边界。按该规则对开发集重新仲裁，主模型为 12/12。该数字是开发集诊断结果，不能用于 promotion。一次 Claude Sonnet 4.6 交叉模型尝试因 provider unavailable 而没有产生判断，不计作支持或反对票。

主模型 12 条调用的中位延迟为 9.429 秒，nearest-rank p95 为 12.457 秒；共记录 38,182 input tokens、9,436 output tokens，其中 3,441 reasoning tokens。QuickRouter 没有返回可审计价格，因此费用完整性门槛尚未满足。

## Round 2 全量运行状态

随后在同一 provider、模型、prompt 和冻结 evidence 上计划运行全部 38 条。Q01–Q14 完成，Q15–Q37 因 QuickRouter 返回 `local:insufficient_quota` 而 unavailable，Q38 没有冻结 evidence，所以没有发起模型请求。对 Q15–Q37 的固定批次重试仍为 23/23 quota unavailable。

因此本次全量运行没有完成，不能报告 38 条准确率，也不能通过 promotion gate。当前只有以下局部诊断：

- Q01–Q14 相对旧 gold 为 11/14（78.6%）。
- 应用已经完成的 Q05、Q09 开发集仲裁后为 13/14（92.9%）。
- 完成的 14 条中没有错误的 `supported` 或错误的 `contradicted`；三个分歧全部是模型保守返回 `insufficient_evidence`。
- Q14 的 bundle 能证明评估了 10 种训练阶段和 3 种推理阶段防御，但没有保留“training-loss degeneration”，对“channel-level signal dilution”也只有间接描述。这个分歧应归入 evidence sufficiency / retrieval 问题，在新的 retrieval fixture 中修复和复测，不能通过放宽 verifier 规则消除。
- 已完成 14 条的中位延迟为 7.800 秒，nearest-rank p95 为 26.851 秒；共记录 46,141 input tokens、10,329 output tokens，其中 2,947 reasoning tokens。

## 决策

保留保守三分类策略和新的 contradiction 边界。Q05、Q09、Q35 的原 Round 2 文件不回写，仲裁标签只用于已开封开发集分析。恢复 provider 配额后，仅对因 provider failure 未完成的 Q15–Q37 按同一冻结配置重试，并把重试 manifest 与原运行一起保存；不得用重试结果替换已经完成的 Q01–Q14。

完成当前 38 条开发运行后，下一项工程实验是构造 evidence sufficiency fixture，覆盖摘要关键句、表格完整行列、穷尽列表和复合论断条件。最终上线判断仍必须使用协议要求的全新、独立、至少 12 篇论文和 100 条 claim 的封存留出集。
