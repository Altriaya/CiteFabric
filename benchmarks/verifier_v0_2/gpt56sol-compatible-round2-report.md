# GPT-5.6-sol compatible provider · Round 2 开发实验

实验日期：2026-09-29。该实验使用已经开封的 Round 2 开发集，`promotion_eligible=false`、`independence_verified=false`，不能作为上线 promotion 证据。

## 冻结配置

- 输入：`benchmarks/round2.json`，SHA-256 为 `0e87c71441b11070ee2716918576e03492c39271eaa7c98a4738a14a3fafb5a7`。
- Evidence：`output/validation/offline_round2_zh_v4_20260921` 中的冻结 bundle。
- Provider：`openai_compatible` Chat Completions；密钥与 Base URL 只保存在本机配置中。
- 模型：`gpt-5.6-sol`；reasoning effort：`medium`。
- Prompt：`openai-semantic-verifier-v1`，SHA-256 为 `decaf1b0940bd64127ebb397cb57bf52cc097ac9f92280f3ef15f02f0f991f49`。
- Gold 在全部调用完成后才用于评分，没有发送给模型。

兼容 provider 的 Responses 端点会静默忽略复杂 JSON Schema。第一次 37 条运行因此全部产生 `invalid_model_output`，没有生成语义 verdict。实现随后改为 Chat Completions，并把无 `$ref` 的严格 Schema 同时放入 `response_format` 和模型可见输入；本地仍使用同一个 Pydantic contract 拒绝任何字段偏差。Q01、Q35 哨兵通过后才开始最终批次。

## 执行结果

38 条中有 37 条具备冻结 evidence。最终批次首轮完成 36 条；Q36 一次 schema failure，按协议固定重试一次后成功。Q38 没有冻结 evidence，未请求模型。

| 口径 | 正确数 | 准确率 | 说明 |
| --- | ---: | ---: | --- |
| Round 2 原始 gold | 29/37 | 78.4% | 保留历史标签，不回写 |
| 应用 Q05/Q09/Q35 边界仲裁 | 32/37 | 86.5% | 已开封开发集分析 |
| Evidence 完整子集 | 32/32 | 100% | 排除五条已确认缺失 gold anchor 的 retrieval failure |

按边界仲裁后的三分类指标：Macro-F1 `0.8482`；`supported` precision `1.0`、recall `0.7222`；`contradicted` precision/recall 均为 `1.0`；`insufficient_evidence` precision `0.5455`、recall `1.0`。没有错误 `supported`，也没有错误 `contradicted`。

五条剩余分歧均为旧 gold `supported`、模型 `insufficient_evidence`：

- Q14：缺少摘要中的 `signal dilution` 和 `training-loss degeneration`；`gold_page_hit=false`、`gold_anchor_hit=false`。
- Q17：缺少表 3 的 `17.607 14.201` 与 `18.048 39.303`；两个 gold check 均为 false。
- Q18：缺少 `without any clean reference set`；两个 gold check 均为 false。
- Q33：命中第 2 页，但片段没有 `0.96`、`2.8`、`median backbone` 和 `95%` 的完整锚点；`gold_anchor_hit=false`。
- Q37：缺少图 2a 的 `3,144 protein chains` 和 `overall median is 1.46`；两个 gold check 均为 false。

因此这五条不能用于指责 verifier 漏判支持；它们测到的是 evidence selection 没有把支持论断所需的关键句或表格值送入 verifier。若仍按全包计分，每篇最低准确率为 TimeGuard `4/7`（57.1%）和 AlphaFold `3/5`（60%），会直接失败 promotion gate。

## 运行特征与限制

- 37 条有效 verdict 的中位延迟为 `9.461s`，nearest-rank p95 为 `21.425s`，最大值 `33.653s`。
- 有效输出记录 332,531 input tokens、47,242 output tokens，其中 105 reasoning tokens；平均每题约 8,987 input tokens。
- 第三方 provider 没有返回可审计价格，因此费用完整性门槛未满足。
- token 合计不含被本地拒绝的无效输出；Q36 的首次失败和前期兼容调试调用仍可能产生实际费用。
- 该语料、rubric 和失败分析均已开封，所有结果只能指导开发。

## 决策

保留 `gpt-5.6-sol`、`medium` 和严格本地校验。当前 verifier 的主要观察是保守：它没有在证据缺失时制造支持或反驳。下一项改进应针对 evidence sufficiency，重点覆盖摘要关键句、指定表格单元格、图注数值和复合论断的全部条件；不能通过要求 verifier 猜测未提供的原文来提高旧 gold 准确率。

修复 retrieval 后须建立新的 fixture 验证这五类证据完整性。最终上线仍需使用协议要求的全新、独立、至少 12 篇论文和 100 条 claim 的封存留出集。
