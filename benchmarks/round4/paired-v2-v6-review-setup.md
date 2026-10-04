# v2/v6 配对语义盲审准备记录

日期：2026-10-05。该记录只说明盲审材料和评分链路已准备完成，不包含人工语义评分，也不构成默认版本升级结论。

## 范围

- 输入沿用已封存的 v6 promotion 留出运行：15 篇、150 个独立 intents、中英文各一份。
- 每个 intent/语言形成一个 A/B pair，共 300 pairs、600 evidence candidates。
- 只保留 v2 和 `offline_structured_v6`；v3/v4/v5 不进入本次版本决策。
- 每组内的 A/B 顺序以及 pair 顺序均由固定随机种子生成；策略身份、真实 evidence ID、trace、耗时和内部分数只保存在私钥中。
- 评审包包含冻结的 reference verdict、必要条件说明和最小充分集合，使两位评审者可以按照同一 rubric 评分。它不会向评审者显示 A/B 对应的策略。
- 300 组中有 216 组的 A/B evidence 列表逐字段完全相同；它们仍代表 432 个策略输出，但每位评审者只需作一次语义判断并把同一评分填入 A/B。因此每位评审者实际面对 384 份不同 evidence 判断，而不是 600 份不同内容。

## 完整性结果

`scripts/round4_paired_review.py validate` 已通过：

- pairs：300；
- candidates：600；
- 每组恰好包含 A/B 两个候选；
- 216 组标记 `candidate_evidence_identical=true`，其余 84 组需要分别判断 A/B；
- 每个 intent/语言只出现一次；
- 私钥 candidate 映射与公开包完全对应；
- run、gold、package 哈希绑定通过；
- 公开结构中没有 policy/policies 字段或完整内部策略值。

哈希：

| 对象 | SHA-256 |
| --- | --- |
| frozen run | `d10b7da5b825cd17f69d41c79964f064167f8b7a740eec73afc8c5b2d87ce664` |
| frozen gold | `6fd6c74b916368f79267da6ead01fa7853ab6e865f79da2926ed3ead6b300126` |
| reviewer package | `560bdde8240a65a232ec1139856b89c539ff3d1956e82f2a43105c557efe270f` |
| rating template | `a9405afe17dc22a27eee885e3be368cbc0034fa3ab36d7bd5b9969e43ee6669b` |
| private mapping | `bef7abbaa2c27d85c4dee819b7ac39963e575547eb8ff9a3e3f832605447dcc5` |

实际材料保存在被 Git 忽略的本地验证目录：

```text
output/validation/round4/v6-promotion-20261004/
├── paired-review-v2-v6/
│   ├── items.json
│   └── rating-template.json
└── private/
    └── paired-v2-v6-key.json
```

私钥不得交给初评者。两名初评者分别复制模板、填写真实 reviewer ID 和独立性声明，并在不知道另一人评分的条件下完成全部候选。只有分歧候选采用第三人的仲裁结果；原始评分保留。

## 尚未产生的结果

当前不能报告 semantic ESR、harmful mismatch 或 limitation preservation，因为这些指标需要两份独立人工评分。评分器会拒绝缺项、相同 reviewer ID、未声明独立、看过私钥、看过另一份评分或未解决分歧的输入。

人工评分完成后运行 `round4_paired_review.py score`，即可得到中英文分开的 v2/v6 ESR、supported/contradicted 分项、限定条件保留、有害错配、论文聚类配对区间、评审一致率和分歧清单。该报告只完成 G2 的语义证据输入；正式 promotion 仍须综合 G0、G1、G3 并作明确决策。
