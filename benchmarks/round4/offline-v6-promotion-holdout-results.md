# v6 promotion 留出实验（模型会话预审）

日期：2026-10-04。

## 结论

`offline_structured_v6` 不升级为默认策略。15 篇、150 个 intent 的冻结留出已完成 6,000 次离线 MCP 回放；机械精确跨度覆盖显示，v6 相对 v2 在中文增加 4 条，在英文减少 2 条。中文的按题覆盖从 56/105 提高到 60/105，增幅没有达到预注册的 +5 个百分点，按论文聚类的 95% bootstrap 区间也跨过 0；英文则从 102/105 降到 100/105。

本轮证明了 promotion fixture、冻结、回放和预算审计链路可以在真实 PDF 上运行，但没有取得默认升级所需的质量证据。下述覆盖是机械 gold-span containment，不是语义 ESR，也不评价 45 条 insufficient 是否发生 harmful mismatch。

## Fixture 与隔离

- 15 个此前未进入 v6 开发的 paper family，150 个独立 intent；每篇固定 4 supported、3 contradicted、3 insufficient。
- 领域分布：computer science 5、particle/astrophysics 5、computational biomedicine 3、weather/climate 2。
- 风险层：35 个 table/numeric、76 个 scope limitation、50 个 condition counterexample；标签可重叠。
- authoring 候选先过滤参考文献和 acknowledgement、funding、conflict、data availability 等行政段落，再按 material、narrative、scope/condition 分层取样。
- 双语 intent 由 `gpt-5.6-sol`、medium reasoning 生成；另一组无状态请求在看不到检索结果的条件下逐篇复核。被拒绝的 slot 单独重写，已通过的 slot 不重生成。
- 这是模型会话隔离，不是可验证的双人人工独立复核。fixture audit 因而报告 `fixture_ready=true`、`promotion_eligible=false`。
- queries、gold、PDF、extraction 和代码环境已封存。seal 的 queries SHA-256 为 `ca43cf86...c6e2e3`，gold 为 `6fd6c74b...00126`，prepared 为 `97a0cdba...3764`；算法代码封存在 commit `5cbeef4` 的干净工作树上。

内部 paper ID `alexnet` 沿用了下载阶段的临时文件名，实际论文标题是 *Improving neural networks by preventing co-adaptation of feature detectors*。标题、PDF hash 和 extraction hash 才是版本身份依据。

## 执行矩阵

固定参数为 6,000 字符、5 个策略、2 种语言、150 个 intent。每个组合包含一次 first pass 和三次 warm replay，共 6,000 行。评分只预先选择 repetition 1，不按最好结果挑选。

所有 6,000 行均满足 evidence replay integrity 和字符预算。1,500 个 intent/language/policy 组合中，1,499 个的证据坐标在四次运行完全一致。唯一变化是 `fourcastnet-02` 的中文 `structured_v3`：first pass 与 warm run 的第二个段落起点不同，但四次都覆盖 gold span，未改变判定。

## 精确跨度覆盖

分母是每种语言的 105 个 answerable intent；45 个 insufficient 不进入此表。

| 策略 | 英文 | 中文 |
| --- | ---: | ---: |
| v2 | 102/105（97.1%） | 56/105（53.3%） |
| structured_v3 | 102/105（97.1%） | 57/105（54.3%） |
| offline_structured_v4 | 97/105（92.4%） | 63/105（60.0%） |
| offline_structured_v5 | 51/105（48.6%） | 60/105（57.1%） |
| offline_structured_v6 | 100/105（95.2%） | 60/105（57.1%） |

v2 与 v6 的配对变化：

| 语言 | 两者命中 | 仅 v6 命中 | 仅 v2 命中 | 两者未命中 | v6 − v2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 英文 | 99 | 1 | 3 | 2 | −1.9 pp |
| 中文 | 54 | 6 | 2 | 43 | +3.8 pp |

按 15 篇论文聚类 bootstrap，英文差值 95% 区间为 `[−4.8 pp, 0.0 pp]`，中文为 `[−1.9 pp, +9.5 pp]`。两者都不满足“点估计至少 +5 pp 且区间下界大于 0”。

中文的 6 个新增命中集中在表格标题、模型名、能量条件和图例条件：`atlas-higgs-02`、`cms-higgs-01`、`cms-higgs-05`、`gan-01`、`icecube-07`、`planck-01`。两个中文回归是 `fourcastnet-01` 和 `medpalm-02`。英文只有 `medpalm-01` 获益，但 `hyenadna-02`、`medpalm-02`、`planck-05` 回归。

四个 paper/language 层各退 1/7，即 14.3 个百分点：英文 HyenaDNA、英文 Planck、中文 FourCastNet、中文 Med-PaLM。它们超过预注册的单篇最大退步 10 个百分点。`medpalm-02` 在中英文同时回归，说明 v6 对多列、多条件表格的 material 路由仍会把完整目标表挤出最终字符预算。

这些结果也说明 v4 的中文覆盖最高不等于它可直接替代 v2：v4 英文下降 5 条，而且本轮尚无语义充分性与负例安全评分。v5 的英文 51/105 明显失败，继续保留只会增加产品复杂度。

## 运行成本

以下为三次 warm replay，p95 先对每个 intent 取中位数再跨 intent 计算。

| 语言/策略 | warm p95 | 平均初始响应 | 平均审计字节 | 平均证据字符 | 平均 passages |
| --- | ---: | ---: | ---: | ---: | ---: |
| English v2 | 86.19 ms | 26,481 B | 37,889 B | 5,535 | 3.42 |
| English v6 | 84.91 ms | 26,600 B | 37,531 B | 5,468 | 3.17 |
| 中文 v2 | 89.04 ms | 25,131 B | 35,545 B | 5,041 | 3.13 |
| 中文 v6 | 84.40 ms | 25,401 B | 35,490 B | 5,053 | 2.92 |

v6 的 p95 不高于 v2，初始响应增幅分别为 0.5% 和 1.1%，低于 15% 上限；G3 成本门槛通过。

## Promotion gate

| Gate | 判定 | 依据 |
| --- | --- | --- |
| G0 评测资格 | **未通过** | 规模、领域、配额、参考文献过滤和冻结记录通过；没有两名可验证的独立人工审阅者和外部保管链。 |
| G1 完整性 | **本次运行通过，发布级仍待 CI** | 6,000/6,000 可回放，预算越界 0，PDF/extraction hash 匹配；发布级跨平台 CI 在本报告提交后另查。 |
| G2 留出质量 | **未通过/部分不可判定** | 精确跨度代理没有达到配对改进门槛，英文回归并出现单篇 14.3 pp 退步；语义 ESR、限定句保留和 harmful mismatch 尚未由盲审评分。 |
| G3 成本 | **通过** | v6 延迟与字节开销均在 v2 的 1.15/1.5 倍门槛内。 |

已从 repetition 1 生成随机打乱的 1,500 项 blind package 和独立私钥映射，供两名人工 reviewer 评分并在有分歧时由第三人裁决。评分完成以前，不得把机械覆盖改称 ESR，也不得把 45 条 insufficient 视为安全通过。

## 决策与下一步

默认策略继续使用 v2，v6 保持实验选项。下一轮算法工作应只处理已观察到的两类问题：

1. 多列、多条件表格在最终选择阶段被挤出预算，代表样例是 `medpalm-02`。
2. v6 的条件/material 路由对普通英文叙述产生回归，代表样例是 `hyenadna-02` 和 `planck-05`。

在动算法前，先完成 blind package 的双人人工评分。若 harmful mismatch 或语义 ESR 本身不合格，应优先修正证据选择和拒答；若语义评分与机械跨度结论一致，再设计 v7，并使用另一批未开封论文验证，不能在本批留出上继续调权重。
