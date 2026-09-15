# Round 4 第二批新论文自审 pilot

运行日期：2026-09-15。冻结源码：`46ffb9e1b51048e1bc1cb4449625145e52e77454`。本批次在生成任何检索输出以前固定论文、双语查询、待核对论断和 gold，并以 SHA-256 seal 绑定查询、gold、提取快照、依赖、协议和运行参数。它由同一 AI 操作者编题、标注、运行和仲裁，`independence_verified=false`，因此是**预注册、自审 pilot**，不是独立 blind evaluation，也不具备 promotion 资格。

## 语料与任务

本批使用 5 个此前未参与 CiteFabric 开发的 paper families，每篇 12 个独立 intent，共 60 个；每个 intent 分别运行等价的中英文查询。Gold 包含 30 个 supported、15 个 contradicted、15 个 insufficient，45 个可回答案例共绑定 50 个可回放文本跨度和 112 个必要条件。

| Paper | 领域 | 版本 | 主要挑战 |
| --- | --- | --- | --- |
| *Bitcoin: A Peer-to-Peer Electronic Cash System* | 分布式系统 | [bitcoin.org PDF](https://bitcoin.org/bitcoin.pdf) | 叙述、公式、图 |
| *First M87 EHT Results I* | 天文学 | [arXiv:1906.11238v1](https://arxiv.org/abs/1906.11238) | 长文、公式、图、特殊字符 |
| *Gender Shades* | 算法公平性 | [PMLR 81](https://proceedings.mlr.press/v81/buolamwini18a.html) | 多级表头、交叉群体数值 |
| *A Randomized Trial of Intensive versus Standard Blood-Pressure Control* | 临床医学 | [DOI 10.1056/NEJMoa1511939](https://doi.org/10.1056/NEJMoa1511939) | 治疗组、风险比、显著性、排除人群 |
| *U-Net* | 生物医学成像 | [arXiv:1505.04597v1](https://arxiv.org/abs/1505.04597v1) | 图、表格、模型结构 |

主设置保持协议默认值：`max_chars=6000`、`max_passages=6`、`allow_abstract=false`、`expand_query=true`，v2 与 `structured_v3` 使用独立工作区和相同 PDF/抽取快照。每个双语查询执行一次 first pass 和三次交错 warm repetition，总计 960 次 MCP 调用。

输出先随机化为 240 个匿名 A/B 条目。Reviewer A 做保守的精确 gold-span 覆盖审计；Reviewer B 依据 evidence package、gold requirements 和三轴语义规则判断充分性、条件关系与 mismatch。两条轨迹的 sufficiency 一致率为 79.17%，harmful-mismatch 一致率为 88.33%；97/240 个条目需要语义自仲裁。该分歧说明自动 span 审计不能替代语义审阅，也说明本轮分数仍需独立人工复核。

## 主结果

ESR 的分母只含 45 个 answerable intents；双语不合并成 90 个独立样本。

| 语言 | 策略 | Answerable ESR | Supported ESR | Contradicted ESR | 限定句保留 | 条件反例 harmful mismatch |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| English | v2 | **41/45 (91.1%)** | 27/30 | 14/15 | 15/15 | 0/20 |
| English | structured_v3 | 40/45 (88.9%) | 26/30 | 14/15 | 15/15 | 0/20 |
| 中文 | v2 | 11/45 (24.4%) | 5/30 | 6/15 | 6/15 | 1/20 |
| 中文 | structured_v3 | 11/45 (24.4%) | 6/30 | 5/15 | 6/15 | 1/20 |

按 paper family 聚类的配对 bootstrap 显示：英文 `v3-v2 = -2.22pp`，95% CI `[-6.67pp, 0]`；中文差值 `0pp`，95% CI `[-6.67pp, +6.67pp]`。只有 3 个 intent 的配对结论不同：英文 `eht-04` 由 v2 complete 变为 v3 partial；中文 v3 在 `gendershades-03` 得一例、在 `eht-09` 失一例。

英文结果存在明显论文差异。v2/v3 在 Bitcoin、Gender Shades 和 U-Net 均为 9/9；SPRINT 均为 6/9；EHT 为 8/9 与 7/9。SPRINT 的失败集中在复合纳入条件、治疗组到目标值的显式映射，以及严重不良事件表格中的指标/显著性绑定。v3 的额外英文失败是 EHT 多观测日结果只召回“结构稳定”，没有保留“环直径和宽度稳定”的精确限定。

中文 ESR 在五篇论文上都很低：v3 分别为 EHT 0/9、Bitcoin 2/9、SPRINT 2/9、Gender Shades 3/9、U-Net 4/9。失败不是单篇版式异常，而是中文概念无法稳定召回英文原文；数字或英文缩写较多的 U-Net 略好。v3 的结构化选择无法弥补候选阶段缺少跨语言同义词这一问题。

15 个 insufficient intents 中，两种策略在中英文均有 6/15 的 responsive-looking mismatch。典型情况包括：用 M87 的 1.3 mm 环直径回答 Sgr A* 或 0.87 mm 问题；用 U-Net 的显微镜 IOU 回答 3D CT 或荧光免疫细胞问题；用 SPRINT 的 `<120 mm Hg` 组回答未报告的 `<110 mm Hg` 组。这些 evidence package 不能自动解释为 supported，必须由语义层识别对象、数据集、版本和范围错配。

## 完整性与成本

960 次调用全部通过文档/版本/offset 回放，导入或执行失败为 0，预算越界为 0。当前结果没有发现跨论文或跨 edition 绑定。

| 语言 | 指标 | v2 | structured_v3 | v3/v2 |
| --- | --- | ---: | ---: | ---: |
| English | 平均初始响应 bytes | 24,679 | 28,004 | 1.135× |
| English | 平均完整审计 bytes | 36,009 | 39,538 | 1.098× |
| English | warm p95 | 21.64 ms | 22.37 ms | 1.034× |
| 中文 | 平均初始响应 bytes | 19,398 | 22,106 | 1.140× |
| 中文 | 平均完整审计 bytes | 27,683 | 30,604 | 1.106× |
| 中文 | warm p95 | 21.48 ms | 21.85 ms | 1.018× |

本轮 AI 辅助编题、gold 草拟和语义审阅约使用 839k 模型 tokens；其中语义盲审约 483k。该成本不属于 MCP 检索 G3，但表明当前模型审阅流程还不能直接作为低成本生产 verifier。

## 结论与后续约束

本 pilot 不支持把 `structured_v3` 设为默认。英文质量没有正向增益，中文质量则暴露出跨语言召回的系统性失败。成本和完整性满足当前 pilot 的工程约束，但不能抵消 G2 质量门槛未通过。

该批次开封后转为 development。下一轮应先冻结一个可缓存、可审计、失败时回退原查询的中文到英文语义改写接口，在本批 opened 数据上做诊断和消融；改写产生的英文查询必须保留数据集、模型、指标、数值、单位、方向、基线、时间和范围条件。完成失败分析后再冻结新的候选算法，并使用全新的论文留出集验证，不能继续把本批成绩当作泛化或 promotion 证据。
