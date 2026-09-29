# CiteFabric

**Trace research claims to the exact evidence you retrieved.**

CiteFabric 提供多源论文搜索、版本身份、可重放文本证据和引用溯源，支持 Python SDK、CLI 和五个 MCP 工具。

**当前状态：已发布 GitHub v0.1.0，尚未发布到 PyPI。** 本版本没有语义论断验证器，相关段落不等于支持论断。

## 从源码运行

需要 Python 3.11+ 和 uv。

```bash
uv sync --locked
uv run citefabric doctor --json
uv run citefabric search "memory in language model agents" --json
```

默认启用 Crossref、arXiv、OpenAlex、Semantic Scholar，不要求 API key。匿名额度和可用性因来源而异；某个来源失败时，其他来源结果仍会返回，同时显示 `partial` 与具体原因。

```bash
uv run citefabric search "agent memory" --sources crossref,arxiv --limit 5 --json
uv run citefabric paper arxiv:1706.03762v7 --json
uv run citefabric evidence arxiv:1706.03762v7 "attention mechanism" --json
uv run citefabric cite arxiv:1706.03762v7 --format bibtex --json
```

网络示例依赖上游可用性。`cite` 使用已解析的本地元数据，不隐式联网。

## 离线演示与本地文档

```bash
uv run python examples/offline_demo.py
```

该演示导入明确标为合成数据的文本，检索片段、生成审计凭据、导出 CSL-JSON 与 provenance；不联网、不调用模型。工作区保留在 `.citefabric/demo`，返回的证据 ID 可再次读取。

导入自己的 PDF 或 UTF-8 文本：

```bash
uv run citefabric --data-dir .citefabric/my-project import ./paper.pdf --json
```

使用返回的 `fabric_id` 和 `edition_id` 继续操作；已知版本时也可在 import 时指定 `--edition`。手动关联不等于已独立核验论文身份。

```bash
uv run citefabric --data-dir .citefabric/my-project evidence FABRIC_ID "query" --edition EDITION_ID --json
uv run citefabric --data-dir .citefabric/my-project verify "claim" --paper FABRIC_ID --edition EDITION_ID --json
```

默认配置下 verify 返回 `unavailable / verifier_not_configured`，但凭据会保留真实原文、定位、文档哈希和 grounding 状态。

主线已提供 0.2 开发用的依赖注入 `VerifierBackend`、确定性 Fake Backend 和显式启用的 OpenAI Responses API adapter。真实 adapter 使用严格结构化输出，只把冻结的 claim 与 evidence bundle 交给模型；最终 verdict 仍由本地确定性策略生成。Fake Backend 不能通过普通 CLI 配置启用，真实 provider 默认也保持关闭。设计与当前进度见 [0.2 verifier 设计](docs/verifier-0.2-design.md)。

`find_evidence` 的 `query_rewrite="english_faithful"` 是默认关闭的实验接口。它只在调用方配置受审计的改写器时使用英文候选；会记录原问句、改写、模型、提示词版本和校验结果。数字、比较符号、拉丁术语或显式否定词丢失时，改写被拒绝并回退原问题。该校验不证明完整语义等价，也不启用语义 verdict。

## MCP 配置

`uv run citefabric` 或 `uv run citefabric serve` 启动 stdio MCP。客户端配置示例：

```json
{
  "mcpServers": {
    "citefabric": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/CiteFabric", "run", "citefabric"]
    }
  }
}
```

桌面客户端不能继承 shell PATH 时，把 command 改为 uv 的绝对路径。

| 工具 | 行为 |
| --- | --- |
| `search_papers` | 四源搜索、保守去重、来源状态、快照分页 |
| `get_paper` | 身份解析、版本、字段来源和冲突 |
| `find_evidence` | 有界词法检索、原文偏移、物理页号与哈希 |
| `verify_claim` | 生成审计凭据；0.1 不给出语义支持判断 |
| `export_citations` | 本地 BibTeX/CSL-JSON 与独立溯源 manifest |

资源地址为 `citefabric://papers/{id}`、`citefabric://evidence/{id}`、`citefabric://receipts/{id}`。paper 资源 ID 不含 `fabric:` 前缀。超大结果通过临时 `citefabric://results/{id}` 返回有界 JSON 文本块，按 `next_uri` 读取并拼接后解析。

## Python SDK

```python
import asyncio
from pathlib import Path
from citefabric import CiteFabricClient, Config

async def main():
    async with CiteFabricClient(Config(data_dir=Path(".citefabric/research"))) as client:
        result = await client.search_papers("agent memory", limit=5)
        print(result.model_dump_json(indent=2))

asyncio.run(main())
```

已有事件循环的 Notebook 中使用 `await main()`。CLI/MCP 调用同一套 application services。

## 配置

默认读取平台用户配置目录下的 `citefabric/config.toml`，也可用 `CITEFABRIC_CONFIG` 指定配置文件。优先级为显式 CLI 参数 > 环境变量 > TOML > 默认值。

```toml
sources = ["crossref", "arxiv", "openalex", "semantic_scholar"]
search_timeout = 12
request_timeout = 8
verifier_timeout = 30
verifier_provider = "none"
verifier_model = "gpt-5.5-2026-04-23"
verifier_reasoning_effort = "medium"
verifier_max_output_tokens = 4096
max_pages = 300
offline = false
# contact_email = "your-contact@example.org"
```

可选环境变量：

- `CITEFABRIC_DATA_DIR`：本地工作区。
- `CITEFABRIC_OPENALEX_API_KEY`、`CITEFABRIC_SEMANTIC_SCHOLAR_API_KEY`：来源凭据。
- `CITEFABRIC_CONTACT_EMAIL`：Crossref 联系信息。
- `CITEFABRIC_SOURCES`：逗号分隔的来源列表。
- `CITEFABRIC_OFFLINE=true`：仅使用本地数据与缓存。
- `CITEFABRIC_VERIFIER_PROVIDER=openai`：显式启用 OpenAI 语义 verifier。
- `CITEFABRIC_OPENAI_API_KEY`：verifier 凭据；未设置时也会读取标准 `OPENAI_API_KEY`。
- `CITEFABRIC_VERIFIER_MODEL`、`CITEFABRIC_VERIFIER_REASONING_EFFORT`：固定模型快照与推理强度。

凭据不通过命令行传入，也不会出现在 doctor 输出中。`doctor --online` 才会执行联网探针。

在已经封存的 Round 2 开发证据上运行小规模真实模型实验：

```bash
uv run python scripts/openai_verifier_dev_run.py --preflight
CITEFABRIC_OPENAI_API_KEY=... uv run python scripts/openai_verifier_dev_run.py
```

默认 pilot 固定 6 条、覆盖 5 篇论文和三种 verdict；使用 `--case Q01` 可缩小范围，使用 `--all` 才运行全部 38 条。runner 会保存输入文件哈希、模型/提示词版本、完整 Receipt、token 与费用。该数据集已经用于开发，结果只用于调试，不能作为 promotion 证据。

CLI 退出码：0=ok/no_results，2=参数错误，3=partial，4=failed。`--json` 输出完整业务 Result；命令语法错误使用 CLI 自身的 stderr 诊断。

## 当前边界

- 基础 PDF 文本层提取，不包含 OCR、可靠表格/图像理解或猜测的章节/bbox；扫描件显式失败。
- PDF 页号从 1 开始，表示物理页。哈希和文本偏移检查不证明论文结论正确，也不能排除 PDF 提取失真。
- 版本分别存储；不把预印本的页码或判断转移到期刊版。多版本选择需要 edition_id。
- 自动文档绑定仅在明确 arXiv 版本、标题与权威元数据匹配时通过；其他候选仍可检索，但显示未独立确认。
- 默认最多三篇论文、六个片段、6000 个原文字符；每版本最多四个种子片段。支持有限中文科研词汇扩展，尚无通用翻译或跨语言语义检索。
- APA/IEEE、其他模型后端、Zotero/PMC、手动身份合并/拆分、自动 LRU 与独立人工评测基准属于后续工作。
- blob 缓存默认上限 2 GiB；当前达到上限时明确报错，不自动删除历史证据。

实际实现与长期设计的差异见 [实现说明](docs/implementation.md)。

## 真实论文流程检查

已准备 BACKTIME、TDBA、TimeGuard 的 [20 条问题与论断检查集](benchmarks/README.md)，覆盖方法、指标方向、表格数值、反例与证据不足。将对应 PDF 放入 `data_test/` 后运行：

```bash
uv run python scripts/validate_real_papers.py
# 将 RUN_DIR 替换为上一条命令打印的输出目录
uv run python scripts/check_real_papers_mcp.py RUN_DIR
```

这会在 `.citefabric/real_papers` 中导入本地论文，保存证据、回执与 BibTeX/CSL 引用，并检查真实 MCP 调用。参考答案来自原文审阅；它们不是内置 verifier 的自动判断。运行结果中的页码/文字锚点命中率也不是语义准确率。

第二轮增加 Transformer、LIGO 引力波观测和 AlphaFold，共六篇、111 页、[38 条问题与论断](benchmarks/round2.json)。复跑与消融命令见 [检查集说明](benchmarks/README.md)。本地对比报告位于 `output/validation/round2/report.md`，不随包分发。

`find_evidence` 默认启用 `expand_query=True` 和 `include_context=True`：前者使用可审计的有限词汇表扩展查询，并按词汇概念覆盖重排；后者在字符预算内补全同页上下文并合并重叠片段。扩展生成新的证据 ID，保留原始文本、偏移和旧回执。它无法补回未检索到的页面，也不解析表格单元格。

结果中的 `query_plan` 记录扩展词，`rerank_method` 记录重排方式，`quality_flags` 提示可疑表格或字体。`retrieval_score` 是种子片段的 BM25 分数，`lexical_concept_coverage` 是词汇覆盖比例，均不是语义置信度；`seed_passage_ids` 是索引片段 ID，不是证据资源地址。CLI 用 `--no-expand-query --no-include-context` 可关闭这两项；SDK/MCP 使用对应布尔参数。

## 实验性 v3 检索

现已提供 `retrieval_policy="structured_v3"`，默认仍为 `v2`。v3 对表格、图注、成本比较和适用范围问题使用结构块召回与条件排序；普通解释性问题沿用词法路径，并补取正文明确引用的表格。原文快照与既有回执保持不变。

```bash
uv run citefabric --data-dir .citefabric/my-project evidence FABRIC_ID "query" --edition EDITION_ID --retrieval-policy structured_v3 --max-chars 6000 --json
uv run python scripts/validate_real_papers.py --cases benchmarks/round2.json --data-dir .citefabric/round3 --retrieval-policy structured_v3 --query-language zh --max-chars 6000
```

SDK/MCP 的 `find_evidence` 同样接收 `retrieval_policy`。v3 先在至多 6000 字符内选择紧凑原文，有明确上下文缺口且调用者预算更大时才扩展。`selection_trace` 记录候选、引用关系、缺项和预算；`bundles` 关联同一提取快照中的证据及候选角色。它不认证行列语义，不自动判断论断成立。

首次打开旧工作区会将数据库 schema 1 升至 2，并在工作区 `backups/` 保存一致性备份；新结构索引按需构建，失败时明确回退 v2。旧版本程序不支持 schema 2，回退时使用备份或隔离工作区。

第三轮同一六篇、38 题的最终结果：6000 字符下，英文锚点 34/36 → 36/36、中文 28/36 → 33/36；12000 字符下，英文 35/36 → 36/36、中文 29/36 → 33/36。后者平均返回字符减少约 41%–42%。这些是开发回归结果，不是独立盲测或语义准确率。详细诊断、消融和剩余问题见本地 `output/validation/round3/report.md`，设计与实现边界见 [v3 设计](docs/retrieval-v3-design.md)。

`retrieval_policy="offline_structured_v4"` 是默认关闭的中文离线诊断策略：它分开检索原中文、有限术语表和显式实体，并在 `query_plan.channel_trace` 中保留每个通道的查询与候选数。它不联网也不调用模型。当前六篇论文的开发实验存在锚点回归，因此 v2 仍是默认策略；结论和复放位置见 [离线 v4 实验](docs/offline-v4-experiment.md)。

## 开发与文档

```bash
uv run pytest -q
uv run ruff check src tests examples scripts
uv run ruff format --check src tests examples scripts
uv run mypy src
uv run python scripts/export_schemas.py --check
uv build
```

离线测试包含真实 stdio MCP 子进程和 PDF 解析进程。macOS、Windows、Linux 与 Python 3.11/3.13 的远程矩阵及公网 arXiv 黄金路径均已通过，范围和证据见 [0.1 发布验收](docs/release-readiness-0.1.md)。

[架构](docs/architecture.md) · [契约](docs/contracts.md) · [0.2 verifier 设计](docs/verifier-0.2-design.md) · [Verifier 评测协议](benchmarks/verifier_v0_2) · [0.1 Schema](schemas/0.1) · [0.2 Schema](schemas/0.2) · [贡献指南](CONTRIBUTING.md) · [Apache-2.0 许可](LICENSE)
