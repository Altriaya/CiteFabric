# CiteFabric

**从论文找到原文证据，把版本和出处一起带走。**

CiteFabric 帮你从研究问题找到论文、确认具体版本，再定位论文中的原文段落。每条证据都保留页码、原文位置和来源信息，可以回放，也可以随引用一起导出。

CiteFabric searches scholarly literature and retrieves source passages from local PDFs or supported open full text. Each result stays linked to its paper edition and citation.

可通过 Codex 或其他 MCP 客户端、命令行和 Python 使用。

[PyPI 安装包](https://pypi.org/project/citefabric/) · [GitHub v0.1.0](https://github.com/Altriaya/CiteFabric/releases/tag/v0.1.0) · [问题反馈](https://github.com/Altriaya/CiteFabric/issues)

## 适合这些工作

- 写作前确认论文里具体报告了什么结果，以及结果出现在哪个版本。
- 在本地论文库里查找方法、指标、实验条件或限制原文。
- 在 Codex 等 MCP 客户端中检索论文，并保留可追溯的证据和引用。

## 能做什么

- 从 Crossref、arXiv、OpenAlex 和 Semantic Scholar 搜索论文元数据。
- 区分同一论文的不同版本；导入本地 PDF，或获取支持的开放全文。
- 返回带页码和原文位置的证据片段，并记录文档哈希。
- 回放证据记录，导出 BibTeX 或 CSL-JSON 引用及出处清单。

论文元数据搜索需要联网；导入的 PDF 和本地证据库保存在你的 CiteFabric 数据目录。搜索来源的可用性和匿名额度由各服务提供方决定。

## 安装

需要 Python 3.11 或更高版本。建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install citefabric==0.1.0
```

确认安装：

```bash
citefabric doctor --json
```

## 试用

搜索论文，查看版本，再定位一段原文：

```bash
citefabric search "memory in language model agents" --limit 5 --json
citefabric paper arxiv:1810.04805v2 --json
citefabric evidence arxiv:1810.04805v2 "SQuAD v1.1 Test F1 93.2" --json
```

导入自己的 PDF：

```bash
citefabric --data-dir ./paper-library import ./paper.pdf --json
```

继续检索时使用导入结果中的论文和版本 ID：

```bash
citefabric --data-dir ./paper-library evidence FABRIC_ID "query" --edition EDITION_ID --json
citefabric --data-dir ./paper-library cite FABRIC_ID --format bibtex --json
```

## 连接 Codex

在安装 CiteFabric 的虚拟环境中，找到 `citefabric` 可执行文件的绝对路径，然后添加 stdio MCP 服务：

```bash
codex mcp add citefabric -- /absolute/path/to/.venv/bin/citefabric serve
codex mcp list
```

Windows 下可执行文件位于 `.venv\\Scripts\\citefabric.exe`。其他 MCP 客户端请按其配置格式启动 `citefabric serve`。更多背景见 [Codex MCP 文档](https://developers.openai.com/learn/docs-mcp)。

## 证据的范围

CiteFabric 保留来源和原文位置，帮助你检查证据从哪篇论文、哪个版本、哪一页取得。**0.1.0 不判断一段文字在语义上是否支持或反驳某个论断。**请阅读原文，并自行判断证据是否充分。

PDF 提取读取文本层；扫描件 OCR 和可靠的表格行列关系尚未支持。图表、表格和上下文依赖需要结合原 PDF 核对。

## 开发与研究

- [架构说明](docs/architecture.md)
- [实现说明](docs/implementation.md)
- [贡献指南](CONTRIBUTING.md)
- [Round 4 实验记录](benchmarks/round4/README.md)

实验记录用于分析和改进，不代表 CiteFabric 0.1.0 的准确率承诺。

Apache-2.0 License
