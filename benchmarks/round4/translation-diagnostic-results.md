# Round 4 第二批论文：中文查询英文改写诊断

日期：2026-09-16。源码基线：`fc1d438`。本实验使用已开封的第二批 5 篇论文、60 个双语 intent，属于 **opened self-review development**。不计入独立留出或默认策略升级证据。原始输入、改写、逐题证据、模型评分和哈希位于本机已忽略的 `output/validation/round4/translation-diagnostic-20260916/`；公开脚本为 `scripts/round4_translation_diagnostic.py`。

## 方法

只把 60 条中文问题和 intent ID 交给 Codex CLI 的 `gpt-5.5`，要求每题输出**一条忠实英文问句**。模型未接收论文、参考英文、claim、gold 或检索结果。生成后固定 `rewrites.json`；ID 与顺序均为 60/60，原问题中显式的拉丁词和数字无缺失。改写提示词 SHA-256 为 `487ed6004a3eea4161506ab41c659bc3cf5a7484c14d714519f46f48163144b2`，改写输出为 `9add5465537d328d1394e6d04df0a9ce0641800ed657f9c96717d5d21b718f71`。该硬约束检查不能证明完整语义等价：例如 `eht-12` 的原中文“中老年”与原有参考英文 “old” 本身并不完全一致；此题为 insufficient，但会影响负例解释。CLI 默认尝试 `gpt-6-astra` 时因版本不兼容失败，没有生成改写；成功运行使用的均为 `gpt-5.5`。

把既有导入工作区复制到独立目录，调用未改动的产品 `find_evidence`，在每篇固定 edition 上对原始中文、模型英文、原有参考英文执行 v2 与 `structured_v3`，共 360 次离线检索。参数均为 6 段、6000 字符、`allow_abstract=false`、`expand_query=true`、`include_context=true`。30 次 `no_results` 全部来自原始中文；没有执行错误或预算越界。对照组 240 个证据包的 locator、截取范围及文本与前次正式 MCP 运行的第一条 warm 结果逐一相同。新运行是直接产品 client 重放，没有重做 MCP 响应字节及完整模型端到端延迟测试。

候选审计在选段前重放当前词法或结构化候选通路，检查 gold 最小充分集合所需**原文坐标是否完整落入候选/最终证据**。它是严格跨度代理，不是语义 ESR：参考英文 v2 的最终跨度代理只有 33/45，而既有语义自审为 41/45。因此只能用来定位候选到选择的损失。

| 策略 | 查询 | 候选含完整 gold 跨度 | 最终包含完整 gold 跨度 | 暂定可回答 ESR |
| --- | --- | ---: | ---: | ---: |
| v2 | 原始中文 | 21/45 | 8/45 | 11/45（既有自审） |
| v2 | 模型英文 | **43/45** | 32/45 | **42/45**（本轮混合自审） |
| v2 | 原有参考英文 | 43/45 | 33/45 | 41/45（既有自审） |
| structured_v3 | 原始中文 | 21/45 | 8/45 | 11/45（既有自审） |
| structured_v3 | 模型英文 | **43/45** | 31/45 | **41/45**（本轮混合自审） |
| structured_v3 | 原有参考英文 | 43/45 | 32/45 | 40/45（既有自审） |

对模型英文的 120 个输出做同一 gold rubric 的单模型语义自审。每个策略有 33/60 个 intent 的证据集合与参考英文完全相同，沿用此前已仲裁的评分；其余 27/60 使用本轮匿名证据包评分，全部 ID、requirement、引用别名与充分集合校验通过。模型英文 v2 按论文的暂定 ESR 为 Bitcoin 9/9、EHT 8/9、Gender Shades 9/9、SPRINT 7/9、U-Net 9/9；v3 仅 EHT 降为 7/9。相对参考英文，两个策略都只有 `sprint-02` 一题由 partial 变 complete：新包中出现了强化组 `<120 mm Hg` 与标准组 `<140 mm Hg` 的显式对应。这 **不证明** 改写比参考英文更好；五篇论文、单模型复评及旧自审标签都不足以判定该 1 题差异。相同证据包的复评也曾在 `gendershades-05`、`sprint-07` 的充分性和 `eht-12` 的 mismatch 上与旧评分分歧，混合计分已避免把这些同包分歧记成算法收益。

## 失效定位与风险

单条英文改写使严格候选跨度从 21/45 到 43/45，与参考英文相同；原始中文有 15/60 个空包，两个英文条件均为 0。这是跨语言词法召回受限的直接诊断证据。候选到最终包仍有 11/45 个严格跨度集合丢失（v2 改写），尤其 SPRINT 为候选 9/9、最终 3/9；语义自审的 SPRINT 仍只有 7/9。下一项检索改进应检查条件、表头、数值和限制句如何共同进入固定预算，而不是继续扩充查询数。`structured_v3` 在改写组的 60 题中有 57 题走 lexical compatibility 路径，本轮没有证据支持升级默认策略。

15 个 insufficient intent 的 harmful mismatch 在旧参考英文自审为 6/15；模型英文的混合自审暂记 9/15，两种策略相同。新增标记为 `gendershades-11`、`gendershades-12`、`sprint-11`。它们涉及近似人群或实验条件；其中若干参考包与改写包只差排序或少量邻近段落，评分者分歧足以影响这个差值。因此 **不能把 9−6 直接归因为翻译造成的风险增加**，但也不能在未复核前放行模型预处理。应由独立审阅者对两种查询的证据包做同题配对盲评，并先明确“近似对象却无目标条件”何时计 harmful mismatch。

后续的[匿名配对自审](negative-review-selection-ablation.md)发现 41 个去重负例包中有 14 个 AI 评分分歧；前述 9/15 与 6/15 差值不稳定，不能作为风险增量结论。

本轮 CLI 共报告约 294k tokens，包含一次改写及五批语义自审；它不是生产接口的单请求费用估计。所有改写和审阅仍由同一 AI 工作流完成，且使用的是开封语料。结论是：**英文改写值得作为可关闭、可缓存的候选实验接口实现；其条件保真、insufficient 风险、延迟和费用仍需独立验证。** 在这些问题解决并通过新论文留出前，默认保持 v2，`verify_claim` 仍不可用。

本地复跑命令（需要上述已忽略的 PDF/fixture、工作区与 `rewrites.json`；输出目录必须不存在）：

```bash
UV_DEFAULT_INDEX=https://pypi.org/simple uv run --locked python scripts/round4_translation_diagnostic.py \
  --base output/validation/round4/blind-pilot-20260915 \
  --rewrites output/validation/round4/translation-diagnostic-20260916/rewrites.json \
  --output output/validation/round4/translation-diagnostic-20260916/replay-again
```
