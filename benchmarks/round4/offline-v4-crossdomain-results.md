# 离线 v4 跨领域复放诊断

日期：2026-09-21。状态：**拒绝作为统一候选或默认策略**。

本次使用 Round 4 第二批的 5 个 paper families（Bitcoin、EHT、Gender Shades、SPRINT、U-Net）、60 个冻结 intent 和本地 PDF，在新建隔离工作区中执行 v2、`structured_v3` 与 `offline_structured_v4`。运行器在完成检索前只读取 queries、抽取快照和运行参数；`run.json` 记录 `gold_access` 为未读取 gold。运行完成后，才由 `scripts/round4_exact_span_coverage.py` 打开 gold，检查返回 evidence 的页码和字符偏移是否完整包含预标注 span。

这一批的历史查询、gold 和先前结果已经开封，且作者、执行者与标注者不是独立人，因此它是冻结候选的**跨领域复放诊断**，不是新的 blind holdout，也不能用于 promotion。

## 运行完整性

- 5 papers × 60 intents × 2 languages × 3 policies ×（首次 + 3 次 warm）= 1,440 次 MCP 调用。
- 1,440/1,440 evidence 回放通过；预算越界和导入/执行失败均为 0。
- 每个策略的每种语言取预先规定的第一次 warm 重复（`repetition=1`）做后验跨度审计。

## 机械 exact-span 覆盖

分母是 45 个 answerable intent。一个 intent 只有在至少一个预定义 sufficient set 的所有 requirement span 都被某段返回 evidence 完整包含时才计入。此数值不是 semantic ESR：它不判断推理、否定、范围、错误对象、视觉表格含义或 insufficient 的 harmful mismatch。

| 语言 | v2 | structured_v3 | offline_structured_v4 |
| --- | ---: | ---: | ---: |
| English | 33/45 | 32/45 | **25/45** |
| 中文 | 8/45 | 8/45 | **9/45** |

v4 的英文退步来自 EHT 的 7/9 → 2/9，以及 SPRINT 的 3/9 → 0/9；相对 v2 的 8 条英文净变化全部是损失（EHT-02/03/04/05/08，SPRINT-07/08/09）。中文唯一净增益是 EHT-09。Bitcoin 和 U-Net 均保持英文 9/9；SPRINT 的中文仍为 0/9。

| 指标（第一次 warm，60 个双语请求） | v2 | structured_v3 | offline_structured_v4 |
| --- | ---: | ---: | ---: |
| English 平均 MCP 响应字节 | 25,869 | 29,195 | 26,923 |
| 中文平均 MCP 响应字节 | 20,552 | 23,259 | 22,175 |
| English no_results | 0 | 0 | 0 |
| 中文 no_results | 15 | 15 | 13 |

## 决策

独立中文术语与实体通道确实带来有限中文候选收益，但其 RRF 融合改变英文精确检索排序，且中文增益远不足以抵消跨论文英文回归。`offline_structured_v4` 保持为默认关闭的诊断接口，v2 继续是默认。

下一项候选不得再用这 5 篇论文调节权重。应先分离语言路由：英文请求直接保留 v2，中文请求才允许进入本地术语扩展候选；随后以新的、未开封的本地论文和封存 gold 做盲测。表格单元格/表头/条件完整性仍是独立的结构解析课题。

复放产物位于本地 `output/validation/round4/offline-v4-crossdomain-20260921/`；其 `run/` 不含 gold，后验审计在 `exact-span-coverage.json`。
