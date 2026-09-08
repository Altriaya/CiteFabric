# 0.1 实现状态

本文件描述实际代码。架构、契约和验收计划保留为设计目标，未完成的远期内容不能理解为已实现。

## 已实现

| 范围 | 实际实现 |
| --- | --- |
| 安装 | 单 Python 包、uv.lock、CLI 入口、wheel/sdist |
| 模型 | Pydantic 输入、领域模型、统一 Result、生成的 JSON Schema |
| 搜索 | 四源、20 条/源候选、RRF、候选集过滤、本地快照分页 |
| 身份 | 强 ID 匹配、版本区分、冲突隔离、稳定本地 ID、字段来源与历史快照 |
| 可靠性 | deadline、一次重试、Retry-After、跨进程 provider 租约、简易熔断、请求合并、缓存原始抓取时间与 stale 标识 |
| 文档 | 显式 PDF/UTF-8 文本导入；已声明 OA 候选下载；DNS/IP 绑定、逐跳重定向校验、大小限制 |
| 提取 | 可取消子进程内运行 pypdf；物理页号、文本快照、部分页覆盖信息 |
| 证据 | FTS5/BM25、片段与字符边界、三类哈希、按保存原文重放检查 |
| 验证接口 | grounding 和审计凭据；语义判断固定 unavailable |
| 引用 | 本地 BibTeX/CSL-JSON、receipt 的版本/元数据检查、独立 provenance manifest |
| 接口 | SDK、CLI、五个 stdio MCP tools、资源读取与输出大小限制 |

第二轮检索增量（`retrieval_version=2`）：有限中文科研词汇扩展、指标别名、按词汇概念覆盖重排，以及预算内同页上下文扩展。两项可选开关默认开启；不读评测标签或参考页。证据仍是快照精确切片，范围变化产生新 ID，旧证据和回执保持可读。质量标志只是启发式提示，不提供 OCR、单元格结构或科学符号纠错。重复导入现在返回已有提取快照与覆盖信息。

第三轮增加显式 `retrieval_policy="structured_v3"`：派生结构索引、表号/图号与实体条件匹配、限定段候选、紧凑原文和引用依赖。普通解释性查询继续使用词法召回。新索引按需创建；数据库 schema 1→2 有原子迁移与一致性备份，索引失败明确回退 v2。默认检索仍为 v2，语义回执仍为 unavailable。实际设计差异及实验见 [v3 设计](retrieval-v3-design.md) 和本地 `output/validation/round3/report.md`。

六篇真实论文、38 条问题的前后对比保存于本地 `output/validation/round2/`。新论文题目在检索改动前准备，但不是盲测；所有参考判断由助手审阅来源后编写，不能视为独立专家标注。英文/中文分别统计锚点覆盖，语义准确率仍为空。实验每题 12000 字符高于产品默认 6000 字符；具体消融、字符成本和未解决问题见本地报告。

## 对初始设计的调整

1. **MCP 使用官方 SDK low-level Server。** 锁定 `mcp>=1.26,<2`，通过 lockfile 固定版本。显式处理 outputSchema、structuredContent、isError 与资源分段，业务逻辑仍与 transport 分离。
2. **初期采用单文件模块。** providers、documents、storage 职责独立；待第三方适配器协议稳定再拆插件目录与独立包。
3. **跨源预印本/期刊关系保守处理。** 同一 arXiv 基础 ID 的多个版本共享 Paper，但分别存 Edition；期刊 DOI 与预印本保留已发现的关系候选，不自动合并两个工作分组。模糊标题只提示可能重复。
4. **普通缓存暂不自动驱逐。** blob 上限触发 resource_limit；receipt 会 pin 文档，但当前没有后台 LRU/GC/purge 命令。
5. **文档版本绑定优先保守。** DOI 本身不能区分接受稿和发表稿；这些候选可提供 grounding，但 binding 保持 unresolved。明确 arXiv 版本、标题和已核验书目元数据匹配后才自动确认。
6. **模型后端与引用样式按 0.2 处理。** verify_claim 产出证据审计凭据，不给虚构 supported。APA/IEEE 明确返回 unsupported_format。
7. **协议细节。** 未知工具返回工具错误；统一 envelope 的 data 为对象，输入与领域对象另有更具体的 Schema。大型资源使用有界 JSON 文本块读取。

## 后续设计项

- 语义 verifier、ClaimBench 标注与评测门槛。
- 跨实例证据包标准、显式身份 merge/split 和补偿事件。
- PMC/Europe PMC/Zotero、Citra/GROBID、OCR、图表语义。
- HTTP 条件请求、响应头动态额度校准、后台刷新、缓存自动驱逐。
- APA/IEEE、MCP HTTP、多用户隔离。
- PyPI 发布、MCP Registry 注册、人工 MCP Inspector UI 检查、远程 GitHub Actions 运行。

这些边界在 README 与接口错误中显式体现。当前版本不宣传为完整论断真值验证器或已发布服务。

## 本地验证

离线测试覆盖强 ID/版本冲突、缓存与限流、Unicode 定位、PDF 提取、hash 篡改、证据关联、CLI exit code、真实 stdio MCP 调用与下载地址校验。

低频真实搜索曾返回 Crossref/arXiv/OpenAlex 成功、Semantic Scholar 限流的 partial 响应；这证明该降级路径可工作，不是长期 SLA 或搜索质量评测。真实上游结果不作为离线 fixture。

本机真实 PDF 下载探针受到网络环境限制：系统 DNS 将 arxiv.org 解析为 `198.18.0.12`（非公网地址），下载器按设计拒绝连接。因此没有把本机自动全文下载标为实测成功；可以先用浏览器下载后显式 import，或在使用真实公网 DNS 的环境中运行。基础 PDF 子进程解析与页码定位已经由离线 PDF fixture 验证。
