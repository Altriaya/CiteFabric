# Round 4 工具操作说明

工具位于 `scripts/round4_eval.py`。只依赖已锁定的项目及开发依赖，不修改产品检索代码，不调用语义模型。所有真实评测文件建议放在已忽略的 `output/validation/round4/` 或维护者单独保管的位置，未开封的 gold 和策略映射不提交到公开仓库。

## 先跑合成契约演示

```bash
UV_DEFAULT_INDEX=https://pypi.org/simple uv run --locked python scripts/round4_synthetic.py --output-dir output/validation/round4/synthetic-demo
```

路径必须不存在；再次运行换一个目录。`UV_DEFAULT_INDEX` 用来覆盖本机可能配置的镜像，避免更改锁文件。Windows PowerShell 可以先设置 `$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"`，再执行不带前缀的 `uv run --locked ...`。

演示生成两份小型合成 PDF、6 个独立 intents 和 1 个变体，然后执行两种策略 × 两种语言 × 首遍及三次热运行，共 112 次真实 stdio MCP 查询。全部原文、gold 和评分是合成契约数据；两份 synthetic-oracle 评分用于检查合并机制，不是两个人的独立意见，也不是科研质量成绩。

输出包括 prepared/、run/journal.jsonl、run/run.json、review/items.json、review/rating-template.json、private-key.json、gold.json、两份合成评分和 scores.json。`DEMO-NOT-BENCHMARK.json` 明确标记不可用于 promotion。

## 实际工作流

以下命令中的路径是独立 pilot 的示例；公开仓库不包含受许可约束的 PDF、私有 fixture、gold 或策略映射。先根据 schema 编写 queries；固定论文和自然问题、完成等价性复核后将 queries.status 设为 frozen，再进行准备与 gold 编制。标注后若必须修改问题，则用新批次文件重新准备并重新绑定 gold，不能直接改旧哈希。

下列命令省略源覆盖前缀；若本机设置了镜像环境变量，仍需在每条命令前加 `UV_DEFAULT_INDEX=https://pypi.org/simple`，或在当前终端先执行 `export UV_DEFAULT_INDEX=https://pypi.org/simple`。

```bash
uv run --locked python scripts/round4_eval.py validate --queries PRIVATE/queries.json --input-dir data_test
uv run --locked python scripts/round4_eval.py prepare --queries PRIVATE/queries.json --input-dir data_test --output-dir output/validation/round4/pilot-prepared
```

`prepare` 不执行检索、不读取 gold。它校验 PDF hash/页数，把所有 PDF 分别导入两个全新工作区，保存确定的配置、代码/依赖哈希、导入耗时、身份和提取快照。读取 `extractions.json` 供 gold 标注使用；不同策略必须使用相同提取文本。来源身份保留 user_asserted，不把 fixture 中的版本描述当成外部机构认证。

标注者按 rubric 阅读全文并编制独立的 gold.json；queries_sha256 绑定 queries 文件原始 UTF-8 字节。不同缩进或换行也会改变哈希。

```bash
uv run --locked python scripts/round4_eval.py validate --queries PRIVATE/queries.json --gold PRIVATE/gold.json --extractions output/validation/round4/pilot-prepared/extractions.json
uv run --locked python scripts/round4_eval.py seal --prepared output/validation/round4/pilot-prepared --gold PRIVATE/gold.json --custodian CUSTODIAN_ID --output PRIVATE/seal.json
```

若有既往 Round 4 批次，validate/seal 使用可重复的 `--prior-queries PRIOR/queries.json` 检查 family 和文件哈希重叠。旧 Round 2 格式不能直接传入，需维护者先建立 paper-family 对照清单。文档实际重叠、作者是否独立不能靠字符串比对认证。

`seal` 记录 gold、queries、prepared、协议、源码、锁文件、保管人、时间和实验参数的哈希。默认封存 6000 字符、三次热运行；诊断预算须 seal/run 同时显式设置 `--max-chars 12000`。该记录不自动证明操作者此前没有看过数据，也不会把 draft 协议或 dirty 源码认证为正式发布版本。

由维护者把 **prepared 目录和 seal.json** 提供给执行者；gold 本体留在执行环境之外：

```bash
uv run --locked python scripts/round4_eval.py run --prepared output/validation/round4/pilot-prepared --seal PRIVATE/seal.json --output-dir output/validation/round4/pilot-run
```

run 没有 gold 参数，不打开 gold 文件；它使用 seal 中的哈希承诺。这里是接口和工作流隔离，没有创建容器或操作系统沙箱。要满足真正盲法，仍需维护者按协议隔离机器/目录和权限。holdout 强制提供 seal；未封存的 draft pilot 只可用于工具自测。

执行前核对代码、协议、Python/依赖和配置；执行后再次记录代码哈希。随机交错策略及题目，保存 first_pass 和三次 warm；第一条 warm 输出预先选为盲审对象，禁止挑最好的一次。已运行的准备目录禁止重复使用，以免把热索引伪装为冷启动。异常保留在逐条追加的 journal 中；不完整运行不能出评分报告。

## 盲审与评分

```bash
uv run --locked python scripts/round4_eval.py blind --run-dir output/validation/round4/pilot-run --output-dir output/validation/round4/pilot-review --private-key PRIVATE/pilot-key.json
```

只向两位输出审阅者提供 pilot-review/ 及维护者认可的 gold 评分标准、原 PDF；不要提供 run/ 或 PRIVATE/pilot-key.json。包内有自然问题、论断、论文、页码、精确原文和局部 E1/E2 别名；策略、排名分数、trace、耗时、真实证据 ID 及运行错误细节被隐藏。篇幅和原文本身可能泄露策略，因此不能保证完全盲化。空输出仍保留一个待评分 item。

两位审阅者各复制 rating-template.json，填写真实 reviewer_id，并独立完成每个 item：

- sufficiency：complete / partial / none；gold insufficient 时只能为 not_applicable。
- requirements：填写该题全部 requirement_id 对应的 present / missing / ambiguous；complete 必须满足至少一个最小充分集合。
- harmful_mismatch：true/false，并填写相应 mismatch_types；空结果不能冒充正确拒答。
- limitation_preserved：需要限定句的可回答题填 true/false，其他题填 null。
- failure_stage、evidence_aliases 和非空 rationale。输出不足时不能借原 PDF 中未返回的内容补分。不可由包内信息定位的失败阶段先标 selection；开封后再做更细的工程诊断。

```bash
uv run --locked python scripts/round4_eval.py score --run-dir output/validation/round4/pilot-run --package output/validation/round4/pilot-review/items.json --private-key PRIVATE/pilot-key.json --gold PRIVATE/gold.json --review PRIVATE/reviewer-a.json --review PRIVATE/reviewer-b.json --output output/validation/round4/pilot-scores.json
```

漏评、重复 item、错误证据别名、标注包哈希变化或未解决的评分分歧都会阻止汇总。有分歧时，第三位仲裁者提交完整评分文件，通过 `--adjudication PRIVATE/adjudication.json` 指定；只对存在分歧的条目使用仲裁结果。保留两份初评及仲裁文件，报告仲裁前一致率和分歧 item ID。

报告包含中英文各自的论文等权 ESR、supported/contradicted 分项、限定句保留、条件混淆、insufficient 分项、逐论文和领域/题型分层、按 paper family 配对 bootstrap 的 ESR 差值及 95% 区间。parent intent 变体仍有评分记录，但不进入主指标与主成本分母；双语分别报告，不累加独立样本数。

成本计规范化完整 JSON-RPC 响应 UTF-8 字节；包含 content/structuredContent 双份内容和请求 id。另计一次完整证据资源回读后的审计总字节。它不是原始管道抓包，不计请求方向流量，也不换算成 token 或费用。每个 intent 先取三次 warm 中位耗时，再求 p95。导入失败的时间缺失会单列 timed_intents，不能据较低均值批准成本 gate。

promotion 固定为 not_evaluated：评分工具不能替代独立保管证明、累计语料审查、G1 的迁移/兼容性检查及完整 gate 决策。真实 pilot 的目标是发现 failure modes；合成演示的分数不得合并进真实 pilot。
