# Round 4：Gold 与输出盲审规则

版本 0.1-draft。与 [protocol.md](protocol.md) 共同冻结。

## Gold 编制

每个 intent 先明确：问题/论断、目标论文版本、实验对象、模型/方法、指标及方向、比较基线、适用范围，以及回答需要的最小推理步骤。只填写与该题相关的维度，并为每一项注明必要性。

参考结论是“根据这篇论文能否支持该论断”，不是外部世界的绝对真值：

| reference_verdict | 标注条件 |
| --- | --- |
| supported | 原论文提供了满足论断全部必要条件的证据 |
| contradicted | 原论文提供直接相反、条件对应的证据；缺少支持不等于反驳 |
| insufficient | 未报告、条件缺失、证据含糊，或论文不足以推出该结论 |

问题也附一条双语待核对论断以界定任务；检索只使用 queries 中的自然问题，不能把 gold 答案拼入查询。

每份 gold 包含一个或多个**替代的最小充分证据集**。集合内所有 requirement 为 AND，不同集合为 OR。例如“表头 + 目标行 + 决定单位的脚注”组成一个集合；正文若明确完整复述同一事实，可组成另一个集合。不能要求命中唯一指定句而拒绝等价原文。

每个 requirement 记录语义条件、原文跨度、角色（定义/条件/结果/限制/反例）和跨跨度关系。表格必须记录值属于哪个行、列、单位和实验条件；附近同时出现模型名和数字不等于关系成立。派生计算须写出操作及全部输入来源，不能拿推导结果当原文引句。

跨度使用 extraction 的 unit index、unit 内 `[start, end)` Unicode 字符偏移和物理页号；UTF-8 bytes 解码后保留原始换行，不能用自动规范化换行的读法验证。每份 gold 绑定 PDF、提取文本 SHA-256，要求切片严格等于 quote。原文图表信息在当前文本快照缺失时，另记 visual_requirements（页码、描述）；该题仍可属于 answerable，但在当前文本通路下记 extraction_gap，不能删掉题目或谎造文本锚点。

insufficient 必须写明全文审阅范围（正文/附录/可获得补充材料）、搜索过的术语、缺失的关键条件及审阅局限。可附局限或相近配置片段，但不能用“未搜到”代替全文审阅。gold 为 insufficient 时充分集合为空，不用相近配置凑满。

两位审阅者对 gold 的结论、必要条件和跨度进行复核；歧义先仲裁，再封存。AI 辅助草稿可以保留，但作者、复核者、是否接触算法输出都必须如实记录。

若完全没有提取快照，`extraction_text_sha256` 必须为 null、spans 为空，并标记 extraction_gap；可回答题的 requirement 只能引用 visual_requirements。工具验证这种缺失是显式的，不能为它提供文本回放保证。对应查询的导入失败仍保留在 answerable ESR 分母。

## 输出评分

审阅者只能依据返回证据包，不能把自己读过全文的背景知识补进包内。必要时用原 PDF 核对定位、行列关系，但 PDF 中未返回的信息只可说明“缺失”，不能给完整分。

| 字段 | 取值与定义 |
| --- | --- |
| sufficiency | complete：至少一个最小充分集合全部满足；partial：有正确证据但条件/关系缺失；none：没有可用证据；not_applicable：gold 为 insufficient |
| requirement coverage | 每个必要条件标 present / missing / ambiguous；错误条件不能算 present |
| harmful_mismatch | 返回包包含貌似回答本题、实际对象/模型/指标/范围不匹配的内容，且未清楚区分；另列 wrong_dataset / wrong_model / wrong_metric / wrong_scope / wrong_version |
| replay_integrity | 所有返回证据是否通过文档、文本哈希、版本及字符跨度回放；失败是工程阻断，不是语义扣分 |
| failure_stage | import / extraction / candidate_recall / selection / budget / relation_ambiguity / language / annotation / none |

ESR 的分子是 `complete` 且无 harmful_mismatch 的 answerable intent；分母是全部 answerable intent，包括运行失败。supported 与 contradicted 各自再报 ESR。选中正确反例可以完整回答错误论断，不能因 claim 错误而期望空结果。

**高风险条件混淆率**的分母是预注册的条件反例 intent（包括可反驳与不可回答题），分子为 harmful_mismatch。同时分别报告两类分母，防止通过增加容易的未报告题稀释错误。

**限定句保留率**的分母是 gold 要求限制/适用范围的 answerable intent；分子要求限制文字及其适用对象均清楚对应。仅命中 “only” 等词不给分。

候选为空、服务超时和明确不足是不同结果，分别记录。当前 verifier 返回 unavailable，不等同于系统已判断该题 insufficient，不能计入语义判断准确率。

评分表至少包含 run_id、匿名策略 ID、intent_id、语言、两份独立评分、分歧、仲裁结果、依据的 evidence IDs、必要条件覆盖和失败阶段。保存仲裁前原始评分，报告 complete 与 harmful_mismatch 的一致率；一致率低首先复核任务/规则，不能通过修改判据提高候选分数。

## 三个标注例子（合成、非评测数据）

- “模型 A 在数据集 D 上优于 B”：只返回 A 的分数为 partial；A/B 同指标同行列条件和指标方向都明确才可能 complete。
- “该结果适用于所有年龄”：返回只研究成人的限制段可构成 contradicted 的充分证据；不能因为句子不是正向结果而判不相关。
- “模型 A 在未报告的数据集 X 上得分 90”：取回数据集 D 的 90 分不是支持，也不是 X 上的反例；应标 insufficient，若包未区分 D/X 则记 harmful_mismatch。
