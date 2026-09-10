# 真实论文检查集

下一阶段见 [Round 4 冻结候选](round4/README.md)：评测协议、fixture schema、gold rubric、promotion gate 和配套工具已经形成候选版本。已完成的 opened self-review 开发实验见 [Round 4 开发结果](round4/development-results.md)；它不属于独立盲测，也未更改默认检索策略。

`real_papers.json` 包含 BACKTIME、TDBA、TimeGuard 的 20 组中文问题、待核对论断、英文检索词、参考答案和原文锚点。页码采用从 1 开始的 PDF 物理页。

检查集基于 2026-09-08 用户提供的三个 PDF，由助手阅读原文后准备，包括 10 条 supported、8 条 contradicted、2 条 insufficient。它是小规模开发回归集，不是盲测、独立专家标注或语义准确率基准。PDF 不随项目分发；请在 `data_test/` 放置 JSON 所列文件名和哈希对应的版本。

```bash
uv run python scripts/validate_real_papers.py
uv run python scripts/check_real_papers_mcp.py RUN_DIR
```

`RUN_DIR` 替换为第一条命令打印的目录。每次运行创建新的输出目录；指定 `--output-dir` 时也必须使用不存在的路径。可用 `--data-dir` 指定隔离数据库。默认工作区是 `.citefabric/real_papers`。

运行器先检查三个文件哈希，将 PDF 首页转录的书目记录标为 `provider=user` / `user_asserted`，然后调用实际导入、检索、核验回执和引用导出流程。全部处理在本地进行。这里使用内部 Store 导入固定书目是评测准备步骤，不代表产品已有通用书目编辑 API 或在线元数据验证成功。

原文锚点和参考判断仅用于结果报告，不传给检索器。每题请求最多 6 段、12000 字符，关闭摘要回退；0.1 的每版本多样性上限实际返回最多 4 段。运行输出记录每个证据 ID、PDF 哈希、文本偏移、回执和导出来源清单。

`gold_page_hit` 表示命中指定页，`gold_anchor_hit` 表示该页所有指定文字均出现在返回片段中，二者都不能替代语义判断。Q07 没有正向证据锚点，不进入这两个指标的分母。Q20 的锚点是限制条件，用于支持保留判断。

0.1 未配置语义模型，内置回执应为 `unavailable / verifier_not_configured`。运行器不会将参考标签复制成模型判断，也不会自动生成新的人工审阅结论。MCP 脚本启动独立 stdio 服务，核对三篇本地身份解析、20 次查询与 SDK 的证据 ID 顺序一致、证据/回执资源回读和引用导出。

本次基线、人工审阅、中文补测及完整报告保存在本地 [output/validation/real_papers/report.md](../output/validation/real_papers/report.md)。这些输出不随项目分发；新运行只生成自己的运行记录。需要追踪今后的检索改进时，保留最初输出，另建运行目录，并单独标记人工补取或查询改写。

## 第二轮：跨领域扩展

`round2.json` 保留原 20 题，增加 Attention Is All You Need（15 页）、LIGO 双黑洞并合观测（16 页）、AlphaFold（10 页），总计六篇 111 页、38 题。新增题覆盖来源内部冲突、表格列、公式、置信区间、样本单位、图注与适用范围。所有页码是 PDF 物理页，AlphaFold 的物理第 2 页对应期刊第 584 页。

标签分布为 18 supported、16 contradicted、4 insufficient。Q07/Q38 无参考锚点，36 题进入覆盖分母；Q20/Q31 用限制性原文检查是否取回了适用边界。题目中的 `cohort=transfer` 表示新增领域，不代表独立盲测。参考标签只用于报告，不输入运行时检索器。

```bash
uv run python scripts/validate_real_papers.py --cases benchmarks/round2.json --data-dir .citefabric/round2 --query-language en
uv run python scripts/validate_real_papers.py --cases benchmarks/round2.json --data-dir .citefabric/round2 --query-language zh
uv run python scripts/check_real_papers_mcp.py RUN_DIR
```

两次运行分别打印自己的 `RUN_DIR`。MCP 检查读取该目录的查询语言和开关，对所有结果核对 SDK 证据顺序，并读取每个返回证据和已有回执；没有证据时跳过资源核验，也不生成语义回执。

消融使用相同命令追加 `--no-include-context`（仅词汇扩展与重排）、`--no-expand-query`（仅同页上下文），或同时追加两项（纯词法）。若指定 `--output-dir`，必须使用新路径。仅关闭开关不等于回退完整旧版本；本次真正改动前代码另存于本地 `output/validation/round2/code_before/`，旧运行保留原 manifest。

论文 SHA-256、获取地址和本地书目依据在 fixture 中。元数据绑定均为 `user_asserted`；LIGO 下载地址含 arXiv v1，但实际文件是 PRL 版式，因此登记 DOI、不猜测版本。AlphaFold 从高校镜像获取原论文 PDF。此流程未验证应用自动全文下载成功。

第二轮结果与来源审阅见本地 [report.md](../output/validation/round2/report.md)。固定六篇语料比较前后变化；FTS5 的全库统计受语料变化影响，不能把三篇语料结果和六篇语料结果直接归因于代码改动。实验预算固定为六段、12000 字符，而产品默认预算为 6000 字符。

## 第三轮：结构与紧凑上下文

保留 `round2.json` 的全部题目、参考锚点和 PDF 哈希，以相同语料分别运行 v2 和实验性 v3：

```bash
uv run python scripts/validate_real_papers.py --cases benchmarks/round2.json --data-dir .citefabric/round3 --retrieval-policy v2 --query-language zh --max-chars 6000
uv run python scripts/validate_real_papers.py --cases benchmarks/round2.json --data-dir .citefabric/round3 --retrieval-policy structured_v3 --query-language zh --max-chars 6000
```

再将语言改为 `en`、预算改为 `12000`，构成完整对照。v3 的 `--no-include-context` 与 `--no-expand-query` 分别用于关闭上下文和词汇表；后者仍保留基于查询意图的限定段查找，不能称为禁用了所有中文处理。MCP 检查使用每次打印的新输出目录。

本地第三轮最终目录为 `output/validation/round3/validated_{en,zh}_{6000,12000}`，v2 基线为 `v2_{en,zh}_{6000,12000}`。其他 pilot、compact、release 等目录是保留的开发中间结果，不作为最终结论。详见 [第三轮报告](../output/validation/round3/report.md)。

`tests/test_structured_retrieval.py` 另含 12 条条件组合、10 条限定语变体、8 条预算边界，以及 9 项工程回归。这些是合成测试，不混入真实论文的 36 题覆盖分母，也不是独立语义评测。
