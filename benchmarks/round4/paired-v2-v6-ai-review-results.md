# v2/v6 配对模型语义复评结果

日期：2026-10-05。输入是 [v2/v6 配对语义盲审包](paired-v2-v6-review-setup.md)：15 篇论文、150 个独立 intents、中英文各一份、300 个 A/B pair、600 个策略输出。策略身份在评分完成前隐藏。

本轮使用三个相互隔离的 `gpt-5.6-sol` medium 会话：两份初评不读取私钥或彼此结果，第三会话只处理分歧。它是可复放的 **AI 诊断复评**，不是两名独立真人评审，不能满足 G0 或单独批准默认升级。

## 运行与一致性

- 两份初评均覆盖全部 600 个 candidate；216 组完全相同的 A/B evidence 只调用一次并复制同一评分。
- 初评共有 124/600 个 candidate 在 rubric 任一字段上存在分歧，分布在 68 个 pair，逐项一致率 79.3%。
- sufficiency 一致率 583/600（97.2%）；harmful mismatch 554/600（92.3%）；limitation preservation 586/600（97.7%）。
- 第三会话完成全部 124 个分歧 candidate 的仲裁。两份初评和仲裁共得到 327 个有效结构化响应。
- 有效响应报告 1,741,930 input tokens、219,774 output tokens、合计 1,961,704 tokens；失败重试的服务端用量不在该合计中，兼容 provider 未提供可信费用。
- 批量兼容性错误通过断点续跑处理，没有丢题或选择性删除结果。非适用 limitation 的 `false` 规范化为 `null`；必须评分却返回 `null` 时保守规范化为 `false`。后者只可能降低 limitation 指标，不改变 ESR 定义。

冻结输出 SHA-256：初评 A `c6fb87138a4ef680231d8c33ee300deb533f941dcfb61718d9f81924f241afe7`，初评 B `1e2140937e3e6fedb1660cd037e9fcef950bb0ebc938819f148581985e5a7464`，仲裁 `39ffc93f5ca9c121b7adca57c8f02bd9acc762fc4cca6747e0c0a064144bbfbb`，最终评分 `44df08856acffb466081fd5806c8c8dec993c30a834da77efc9ad57e4cc0bd39`。原始评分包含受许可论文摘录，保存在被 Git 忽略的本地验证目录，不提交公开仓库。

## 主结果

ESR 分母只包括每种语言的 105 个 answerable intents；论文等权值与微平均相同，因为每篇恰有 7 个 answerable intents。

| 语言 | 指标 | v2 | v6 | v6 − v2 |
| --- | --- | ---: | ---: | ---: |
| 英文 | answerable ESR | 103/105（98.1%） | 100/105（95.2%） | **−2.9pp** |
| 英文 | 论文聚类 95% CI |  |  | **[−5.7pp, 0.0pp]** |
| 中文 | answerable ESR | 66/105（62.9%） | 65/105（61.9%） | **−1.0pp** |
| 中文 | 论文聚类 95% CI |  |  | **[−5.7pp, +3.8pp]** |

分项：

| 语言 | 指标 | v2 | v6 |
| --- | --- | ---: | ---: |
| 英文 | supported ESR | 58/60（96.7%） | 56/60（93.3%） |
| 英文 | contradicted ESR | 45/45（100%） | 44/45（97.8%） |
| 英文 | limitation preservation | 30/31（96.8%） | 30/31（96.8%） |
| 英文 | condition harmful mismatch | 1/50（2.0%） | 1/50（2.0%） |
| 英文 | insufficient harmful mismatch | 8/45（17.8%） | 6/45（13.3%） |
| 中文 | supported ESR | 35/60（58.3%） | 34/60（56.7%） |
| 中文 | contradicted ESR | 31/45（68.9%） | 31/45（68.9%） |
| 中文 | limitation preservation | 15/31（48.4%） | 15/31（48.4%） |
| 中文 | condition harmful mismatch | 1/50（2.0%） | 2/50（4.0%） |
| 中文 | insufficient harmful mismatch | 7/45（15.6%） | 7/45（15.6%） |

英文 answerable 中，100 条两者都完整，3 条仅 v2 完整，2 条两者都失败，没有 v6-only 改善。三个 v6 回归是 `hyenadna-02`、`medpalm-02`、`planck-05`，均被仲裁为 candidate recall 失败。

中文 answerable 中，61 条两者都完整，35 条两者都失败，4 条仅 v6 完整，5 条仅 v2 完整。v6 改善 `atlas-higgs-02`、`cms-higgs-05`、`icecube-07`、`planck-01`；回归 `fourcastnet-01`、`gpt3-05`、`medpalm-02`、`planck-05`、`vae-01`。

英文有 HyenaDNA、Med-PaLM、Planck 三个 family 回归 14.3pp；中文有 FourCastNet、GPT-3、Med-PaLM、VAE 四个 family 回归 14.3pp，超过 G2 的 10pp 单篇回归上限。

## 敏感性分析

为避免结论由第三会话偏好决定，另计算两个极端合并：全部分歧采用初评 A，或全部采用初评 B。英文两种情况均为 −2.9pp、区间 `[−5.7pp, 0]`；中文分别为 −1.0pp、区间 `[−5.7pp, +3.8pp]`，以及 −1.9pp、区间 `[−6.7pp, +2.9pp]`。因此“v6 未优于 v2”的方向不依赖仲裁选择。

## 结论

v6 不满足默认升级条件，也没有证据支持仅对中文启用：

- 英文绝对 ESR 很高，但 v6 相对 v2 明确退步，且存在三个超过回归预算的 paper family。
- 中文 v6 没有取得机械跨度覆盖曾暗示的收益。此前 exact-span proxy 是 v2 53.3%、v6 57.1%（+3.8pp），语义复评则是 v2 62.9%、v6 61.9%（−1.0pp）。命中 gold 字符串没有保证整份返回证据保留关系和条件。
- 中文两版的 limitation preservation 都只有 48.4%，说明主要瓶颈是跨语言条件与限定关系的证据组织；v6 的材料路由没有解决它。
- v6 在英文 insufficient harmful mismatch 上从 8 条降到 6 条，表明它具有局部安全收益；该收益不足以抵消 answerable recall 回归。

产品默认值继续保持 v2，v6 保留为实验策略。下一轮若继续改检索，不应在 v6 上微调权重；应提出新的中文语义查询/证据组装假设，并以 `medpalm-02`、`planck-05` 等双语回归作为硬回归用例。正式 promotion 仍需要两位独立真人完成同一盲审包，AI 结果只能用于确定工程方向和缩小人工重点复核范围。
