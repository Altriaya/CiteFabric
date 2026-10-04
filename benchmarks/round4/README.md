# Round 4 冻结候选

协议仍是冻结候选；配套工具已实现，并已在 6 篇真实论文、60 个独立 intent 上完成 opened self-review 开发实验。该实验用于诊断，不是独立盲测或 promotion 结果。检索策略仍为默认 v2。

1. [评测协议](protocol.md)：pilot、开发、最终留出的阶段与隔离。
2. [Fixture Schema](fixture.schema.json)：分开的 queries/gold JSON 契约。
3. [Gold 标注与盲审规则](gold-rubric.md)：充分证据集、条件关系、反例和证据不足。
4. [Promotion gate](promotion-gate.md)：最低规模、质量、完整性和成本门槛。
5. [开发实验结果](development-results.md)：真实论文 pilot、模型查询改写和多查询融合的汇总与限制。
6. [第二批新论文自审 pilot](blind-pilot-2-results.md)：5 篇新论文、60 个双语 intent 的封存检索结果与失败分析。
7. [第二批中文改写诊断](translation-diagnostic-results.md)：在已开封的 5 篇论文上测试单条英文改写，并拆分候选召回与最终选择损失。
8. [负例配对复评与选择器消融](negative-review-selection-ablation.md)：匿名复核 insufficient 错配，并否决退步的短窗口选择原型。
9. [8 篇论文精确跨度开发实验](span-anchored-development-results.md)：完成 1,920 次 MCP 调用，并确认带英文锚点的模板中文题不能衡量跨语言泛化。
10. [自然中文多语检索实验](natural-chinese-multilingual-results.md)：比较 v2、本地 E5、RRF 与跨编码器，记录默认预算收益及 insufficient 暴露风险。
11. [v6 新论文盲测 pilot](offline-v6-new-paper-pilot.md)：6 篇此前未使用的论文、60 条双语 supported intent，验证基线不变量并量化 material 路由的收益与回归。
12. [v6 promotion 留出实验](offline-v6-promotion-holdout-results.md)：15 篇、150 条模型会话预审 fixture 和 6,000 次离线回放；v6 中文机械覆盖小幅上升、英文回归，未通过默认升级门槛。
13. [v2/v6 配对语义盲审准备](paired-v2-v6-review-setup.md)：从同一封存运行派生 300 组、600 份匿名证据结果，完成评分模板、私钥映射和完整性校验；等待双人人工评分。

开发结果页同时记录了三轴语义判断契约实验。对应公共实现为 `src/citefabric/semantic.py` 和 `scripts/semantic_contract_eval.py`；它们定义并评测未来 verifier 的输出政策，不改变 0.1 的 `verify_claim=unavailable` 行为。

JSON Schema 检查文件形状，`scripts/round4_eval.py` 额外检查以下关系；`status=frozen` 不是独立封存证明：

- 每个 ID 唯一、外键存在、gold 对 queries 一一对应、协议/批次/hash 对应。
- parent intent 无环、关联同一论文，变体不计独立样本；paper family 在各阶段不交叉。
- 原始 PDF hash、页数、提取快照 hash、unit/page 对应、`end > start`、精确 quote 切片。
- requirement 的 span 引用有效，sufficient set 的 requirement 引用有效；insufficient 没有充分集合且有完整审阅记录。表格关系和双语等价性仍需人工复核。
- 冻结时 review 记录完备、独立复核者不等于作者且声明未接触算法输出。独立性是否属实仍需维护者核实；自审允许 pilot，但禁止 promotion。
- 输出记录独立 intent 数、按论文等权指标及分层结果。分层配额、所有 gate 和人工决策仍需单独验收；工具不会自动批准 promotion。评分缺失或未解决分歧会阻止汇总，不能静默删样。

冻结 manifest 应另存 protocol/schema/rubric/gate、queries、gold、源码、依赖、工具和参数的哈希，明确封存时间、保管人与开封时间。gold 文件在评测环境外保存；盲审策略映射另行保管。最终留出开封后转入 development 并保留原始封存记录，不覆盖历史。

旧 `scripts/validate_real_papers.py` 使用合并 fixture 且只统计页/锚点，不能作为此协议的 runner。工具的实际用法与边界见 [操作说明](tooling.md)。
