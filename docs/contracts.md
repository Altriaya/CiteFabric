# 数据与接口契约

状态：设计草案 v0.1 · 日期：2026-09-07。本文件定义拟实现行为；不是已经发布的 API。正式 JSON Schema 将由 Pydantic 模型生成，并通过 fixture 验证。

## 1. 通用约定

- 对外 JSON 字段使用 snake_case；所有时间为 RFC 3339 UTC。
- `schema_version="0.1"` 与软件版本、数据库迁移版本分别管理。
- 公共输入拒绝未知字段，枚举大小写严格；SDK 可以将完整 DOI URL 转换为标准 PaperRef。
- 未知标量使用 null；未知覆盖率为 null，不能当作 0；空列表只表示该集合目前无成员。
- UUID 用作稳定 ID；SHA-256 写成 `sha256:<64 位小写十六进制>`。
- 字符区间使用 Unicode code point 索引、0 起算、左闭右开；不是 UTF-8 字节或 JavaScript UTF-16 code unit。
- JSON 示例使用合成文本，不能用作科研结论或 benchmark 成绩。

## 2. 公共对象

下表列出必需的核心字段；标记 `?` 表示可空或可选，正式 Schema 需明确两者区别。所有不可变对象都记录 schema_version。

### 2.1 Paper 与 Edition

| 对象 | 核心字段 |
| --- | --- |
| Paper | fabric_id、created_at、edition_ids、preferred_edition_id?、relations、identity_status |
| Edition | edition_id、fabric_id、kind、version?、external_ids、metadata_snapshot_id、publication_status |
| MetadataSnapshot | snapshot_id、edition_id、title、authors、issued、venue?、field_provenance、conflicts、selection_policy_version、created_at |
| ExternalID | namespace、value、version?、source_record_ids |
| IdentityAssessment | status、scope、source_record_ids、method、checked_at、conflicts |
| PaperRelation | source_id、target_id、relation、basis、status |

Edition.kind：`preprint / journal_article / conference_paper / other / unknown`。

IdentityAssessment.status：`verified / unresolved / conflict / user_asserted`。verified 必须有精确来源记录匹配依据；只看到 DOI 字符串、DOI URL 可跳转或多个搜索结果相似不够。scope 指明核验的是哪个 ID 与哪个 metadata snapshot。verified 不意味着论文内容真实。

`publication_status` 至少表达 `unknown / active / corrected / retracted / withdrawn`，并包含观察来源与时间；来源没有字段时保留 unknown，不默认 active。

PaperRelation.relation：`is_version_of / extends / corrects / retracts / possible_duplicate`。关系中同时保留来源与 `confirmed / candidate / disputed` 状态，不能靠链接传递任意合并。

Author：`display_name` 必填，`given / family / orcid / organization` 可空；保留顺序与团体作者。日期对象 `{year, month, day}` 各自可空，month/day 的存在受前置字段约束。

### 2.2 Document 与 ExtractionSnapshot

| 对象 | 核心字段 |
| --- | --- |
| Document | document_id、edition_id、media_type、byte_length、source_hash、version_label?、binding、access、retrieval_event_ids |
| DocumentBinding | status、method、matched_identifiers、metadata_snapshot_id、checked_at、warnings |
| RetrievalEvent | event_id、document_id、provider、source_uri、retrieved_at、http_status?、etag?、license? |
| ExtractionSnapshot | extraction_id、document_id、parser、parser_version、config_hash、normalization_version、text_snapshot、text_units、text_hash、coverage、warnings |
| Coverage | source_kind、pages_total?、pages_parsed?、pages_failed、sections_searched、truncated |

DocumentBinding.status：`verified / user_asserted / unresolved / conflict`。URI 与用户指定 paper ID 只能形成待检查的关联。自动支持判断要求 binding verified；否则返回 unavailable，reason_code=document_binding_unverified。

`source_hash` 校验下载原字节。`text_hash` 校验解析后 UTF-8 文本。parser 版本变化允许产生新 extraction；不能覆盖旧 extraction 并复用其 EvidenceObject。

解析快照必须保存 `text_snapshot`：按 text_units 顺序，以单个 U+000C（换页符）连接各单元的原样 text，编码 UTF-8 后计算 text_hash；不额外添加终止换页符、不执行隐式 trim。text_unit_id 及单元边界随 extraction 固定。纯文本只有一个单元，因此其 source_hash 与 text_hash 可以相同。检索时的大小写/空白归一化生成另一个索引表示，不能改变此快照。

Access 包含 `access_type=local_user_file|open_access|restricted|unknown`、license 标识/URL、`redistribution=allowed|not_allowed|unknown`、依据来源。license 未知不等于没有限制。

### 2.3 EvidenceObject

| 字段 | 语义 |
| --- | --- |
| evidence_id | 不可变片段 ID |
| fabric_id / edition_id / document_id | 工作、版本与文件关联 |
| extraction_id / retrieval_event_id | 提取快照与获取事件 |
| source_hash / text_hash | 对应 Document 与 ExtractionSnapshot |
| locator | 原文位置，定义见下文 |
| excerpt | 指定区间的逐字提取文本 |
| excerpt_hash | excerpt UTF-8 的 SHA-256 |
| source_kind | full_text / abstract / user_text |
| grounding | status、method、checked_at、limitations |
| context_refs | 邻近上下文的不可变 passage ID |

排序相关字段放在 SearchHit 中：`{evidence, retrieval_score, retrieval_method}`，避免不同 query 改变 EvidenceObject 本身。

Locator：

```text
kind: pdf_text | html_text | plain_text | abstract | table_cell
page: integer >= 1 | null
page_label: string | null
section: string | null
text_unit_id: string
char_start: integer >= 0
char_end: integer > char_start
bbox: [x0, y0, x1, y1] | null
table_id: string | null
cell: {row, column} | null
```

`text_unit_id` 指向不可变页文本、HTML block 或纯文本单元。char 区间在该单元内解释。PDF 的 page 必填；其他类型没有页码时必须为 null。bbox 使用架构文档规定的显示页坐标；table row/column 如有，0 起算。

Grounding.status：`verified / failed / not_checked`。verified 在 0.1 指“excerpt 与保存的解析文本区间、哈希一致”。limitations 应保留文本提取可能失真、OCR 未目检等边界。

强不变量：

1. `excerpt == text_unit[char_start:char_end]`。
2. 三个哈希可分别重算；禁止将整个 PDF 的哈希写进 excerpt_hash。
3. evidence 的 document/edition 与 extraction、retrieval event 的关联必须一致。
4. excerpt 不能在验证后被省略号修改仍沿用同一 evidence_id；UI 摘要另用 preview 字段。
5. 找到证据不修改任何 claim 的支持状态。

### 2.4 ClaimAssessment 与 EvidenceReceipt

Claim：`claim_id、text、context?、language、created_at`。claim ID 对应不可变原文，修订文字创建新 claim。

ClaimAssessment：

```text
assessment_id
claim_id
edition_id
verdict
reason_code
subclaims: [{text, original_span, verdict, evidence_relations, limitations}]
evidence_relations: [{evidence_id, relation: supports|contradicts|context}]
rationale
limitations
coverage
verifier: {backend, model?, model_revision?, prompt_hash?, policy_version}
usage: {input_tokens?, output_tokens?, cost?, currency?}
created_at
```

Token 或成本不可获得时为 null；不得根据字符数伪造实际账单。rationale 保存简短可审查依据，不要求或保存模型私有思维链。

EvidenceReceipt：

```text
receipt_id
schema_version
claim_snapshot
metadata_snapshot_ids
assessment
evidence_ids
document_hashes
identity_assessments
grounding_status
verification_config_hash
created_at
supersedes_receipt_id?
```

receipt 不可变，重验证产生新记录。读取时附加的 `availability` 与 `identity_review_required` 属于当前视图，不重写原始 receipt。

supported/partially_supported/contradicted 必须关联至少一条实际 evidence；引用 ID 必须属于此次提交验证器的集合。自动语义判断还要求文档绑定与 grounding 通过。验证器未配置时，verifier.backend 为 `none`，verdict 为 unavailable。

## 3. 统一结果封装

```text
Result[T]
  schema_version
  request_id
  status: ok | partial | no_results | failed
  data: T | null
  outcomes: OperationOutcome[]
  errors: ErrorDetail[]
  warnings: Warning[]
  meta: {elapsed_ms, cache_status, stale, truncated, next_cursor?, coverage}
```

`OperationOutcome` 记录每个预期来源或工作项：`scope、id、status、code?、retryable、retry_after_seconds?、attempts、elapsed_ms、records_received、records_valid、cache_status`。来源状态可取 `ok / no_results / partial / rate_limited / unavailable / permission_denied / parse_failed / unsupported / not_configured / cancelled`。

records_received/records_valid 对非记录类工作项为 null；cache_status 为 `miss / fresh / stale / not_applicable`。多个故障同时发生时，reason_code 表达当前最先阻断的步骤，其余原因保留在 errors/warnings；无验证器和身份未确认可以同时报告。

ErrorDetail 必须有 `code、message、scope、item_id?、retryable`，message 不带凭据或未过滤的上游响应正文。

### 3.1 聚合规则

| 情况 | 顶层 status | 解释 |
| --- | --- | --- |
| 所有选定步骤完成且有结果 | ok | 仅表示本次定义的操作完成 |
| 所有选定来源成功检索但返回 0 条 | no_results | 只对这些来源与查询范围成立 |
| 一源返回空、一源 429 | partial | data 可为空；不能推断无论文 |
| 有结果但一源失败、部分记录损坏或仅有过期缓存 | partial | 返回仍可用的内容 |
| 所有选定来源均无法完成、无可用缓存 | failed | 保留全部来源错误 |
| 检索完成但没有相关段落 | no_results | 不是 claim=false |
| 语义验证完成且判为 insufficient | ok | 技术操作成功，证据不足 |
| 未配置验证器，有成功完成的 grounding/检索结果 | partial | assessment.verdict=unavailable，保留结果 |
| 未配置验证器且无其他可用结果 | failed | reason_code=verifier_not_configured |

所有选定 provider 均计入覆盖分母。用户明确未选的 provider 不计入失败，返回 selected_sources 供审查。未配置但被选中的必需 provider 不能静默跳过。

顶层只使用四种执行状态；`rate_limited` 等放入 outcomes，解决多个 provider 同时出现不同错误时无法用一个字符串表示的问题。verdict 独立于执行状态。

### 3.2 常用错误码

`invalid_argument、unknown_reference、ambiguous_reference、unsupported_identifier、provider_timeout、provider_rate_limited、provider_unavailable、authentication_required、document_unavailable、document_binding_unverified、parse_failed、ocr_required、resource_limit、unsupported_format、verifier_not_configured、verifier_timeout、invalid_verifier_output、evidence_integrity_failed、cursor_expired`。

单条 provider 404 仅表示该来源无对应记录。get_paper 若所有适用来源成功查无记录，返回 no_results；不能表述为“论文不存在”。强 ID 检索遇到某源失败时按上表 partial/failed 聚合。

## 4. 五个公共工具

下列是类型化伪签名，输入/输出最终通过生成的 Schema 固化。所有 deadline 都可由服务器配置向下覆盖，调用方不能提高服务器资源上限。

### 4.1 search_papers

```text
search_papers(
  query: string,
  filters?: {year_from?: int, year_to?: int, open_access?: bool},
  limit: int = 10,
  sources?: list[crossref|arxiv|openalex|semantic_scholar],
  sort: relevance|recent = relevance,
  evidence_ready: bool = false,
  cursor?: string
) -> Result[SearchResult]
```

query：1–2000 字符；limit：1–20；sources 不得为空或重复。cursor 后续请求必须保持 query/filters/sources/sort/evidence_ready 一致，limit 可以改变；不匹配返回 invalid_argument。

SearchResult：`papers: PaperSummary[]、selected_sources、raw_count、canonical_count、duplicates_merged、possible_duplicates、search_plan_id、exhaustive=false`。

PaperSummary：fabric_id、选定展示 Edition、标题、最多前五位作者及 authors_truncated、年份、外部 ID、来源、可用版本数、document_availability、ranking_score、ranking_method。详细字段通过 get_paper 获取；默认不下载全文。

`evidence_ready=true` 仅返回本地已成功解析且关联明确的结果；不触发批量全文下载。远端 OA 候选通过 open_access 过滤和 document_availability 表达。

### 4.2 get_paper

```text
get_paper(
  ref: string,
  edition_id?: string,
  refresh: bool = false
) -> Result[PaperDetail]
```

0.1 ref 支持 `fabric:<uuid>`、`doi:<doi>`、DOI resolver URL、`arxiv:<base-id>[vN]`、`openalex:<id>`、`s2:<id>`。PMID 在模型 namespace 中预留，但 0.1 输入返回 unsupported_identifier；不声称已有 PubMed adapter。

PaperDetail 返回版本列表、metadata snapshot、字段冲突、身份检查、文档候选及明确可执行的 next_actions。裸标题不作单篇标识，调用方应先 search。参数 edition_id 必须属于解析得到的 Paper。

版本选择：明确外部标识优先；有多个可用 Edition 的 fabric_id 用于证据或导出时必须再指定 edition_id；否则返回 ambiguous_reference 并列候选。只有单一 Edition 时可自动选择。

arXiv 无版本号 ID 通过上游解析到当时返回的具体版本，并返回 resolved_ref 与 resolved_at；缓存和 receipt 始终绑定解析后的版本。用户指定 vN 时不得静默替换成最新版本。

### 4.3 find_evidence

```text
find_evidence(
  papers: list[PaperSelector],
  query: string,
  max_passages: int = 6,
  max_chars: int = 6000,
  allow_abstract: bool = false
) -> Result[EvidenceSearchResult]

PaperSelector = {ref: string, edition_id?: string}
```

papers：1–3 项；query：1–2000 字符；max_passages：1–12；max_chars：500–16000，指所有返回 excerpt 的字符总数，其他元数据另外计入封装体大小上限。

EvidenceSearchResult：`hits、paper_outcomes、coverage、retrieval_method、retrieval_version`。默认每篇最多四条；总数服从 max_passages。预算不足时返回完整片段的子集和 truncated=true，不截断已创建的 evidence。

只有在 allow_abstract=true 时可回退摘要，状态说明全文失败原因。不同 PaperSelector 独立执行；一个下载失败保留其他论文证据。失败页与未搜索部分属于 coverage，不能藏在日志里。

### 4.4 verify_claim

```text
verify_claim(
  claim: string,
  papers: list[PaperSelector],
  evidence_ids?: list[string],
  context?: string
) -> Result[VerificationResult]
```

claim：1–4000 字符；context：最多 4000 字符；papers：1–3 项；evidence_ids：最多 12 项。提供的证据必须属于指定版本并通过完整性检查，不能直接传入用户编造的 EvidenceObject 作为已验证证据。

VerificationResult：`receipts、evidence、paper_outcomes、coverage、limitations`，按每个版本生成一份 receipt。未提供 evidence_ids 时执行有界检索；提供时记录 `coverage=supplied_evidence_only`，不声称扫描了整篇论文。

后端、模型和预算仅在本地配置设置，不允许通过 MCP tool 参数临时提供任意 endpoint/secret。默认策略要求实际语义判断，缺少后端时明确 unavailable。

### 4.5 export_citations

```text
export_citations(
  papers: list[PaperSelector],
  format: bibtex|csl_json|apa|ieee,
  receipt_ids?: list[string]
) -> Result[CitationExport]
```

papers：1–50 项；0.1 只接受 bibtex/csl_json，APA/IEEE 返回 unsupported_format，并列 available_formats。receipt_ids 提供时必须核验版本关联；外来或不匹配的 receipt 返回逐项错误。

CitationExport：`format、content、items、provenance_manifest`。每项 manifest 包含 edition_id、metadata_snapshot_id、identity_status、receipt_ids、grounding_status、claim_verdicts、retrieved_from、warnings。

没有 receipt 的条目写 `claim_assessment_status=not_checked`。引用身份已核验也不升级为 claim supported。provenance 使用并行 JSON manifest，不向标准 CSL-JSON 对象加入不兼容私有字段。

BibTeX citation key 使用稳定 ID 短前缀并处理碰撞；正确转义特殊字符、保留作者次序。缺失字段标注 warning，不由模型补写。导出默认使用已有快照，不因格式转换访问网络。

## 5. MCP / CLI / SDK 一致性

MCP 兼容基线为 2025-11-25 tools 契约；实现阶段锁定 SDK 并验证客户端协商，不宣称该日期是最新协议版本。使用对象型输出封装、outputSchema 和 structuredContent；兼容路径的 TextContent 序列化同一有界 JSON。官方文档定义了结构化输出和工具执行错误的表示。[MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

MCP 映射：

- Result.status 为 failed 时 `isError=true`；partial/no_results/ok 为 false，但正文保留所有失败项和 verdict。
- 未知工具、畸形协议请求使用协议错误；业务参数不合法以结构化工具错误返回。
- 每个响应封装最多 128 KiB UTF-8；按完整 item 边界裁减，并返回 cursor/resource URI 与 truncated。序列化 TextContent 的副本另计实际传输与 token 成本。
- 单条 receipt 超出上限时返回 receipt summary + `citefabric://receipts/<id>`；资源读取仍执行相同权限与大小预算，可按 evidence ID 分段读取。
- 暴露 `citefabric://papers/<id>`、`citefabric://evidence/<id>`、`citefabric://receipts/<id>` 资源；resource link 由同一服务器负责 resources/read，不是公开互联网链接。
- 工具对用户外部资料只读，可写本地缓存与审计记录；annotations 不承担权限校验。无 UI MCP App、无 HTTP 公网服务作为首版依赖。

拟定命令映射：

| CLI | 公共 service |
| --- | --- |
| `citefabric` / `citefabric serve` | 启动 stdio MCP |
| `citefabric search "query" --json` | search_papers |
| `citefabric paper doi:… --json` | get_paper |
| `citefabric evidence arxiv:…v2 "query" --json` | find_evidence |
| `citefabric verify "claim" --paper arxiv:…v2 --json` | verify_claim |
| `citefabric cite doi:… --format bibtex --json` | export_citations |
| `citefabric import ./paper.pdf --edition …` | 本地文档导入，不增加 MCP tool |
| `citefabric doctor --json` | 本地配置/依赖检查；加 --online 才执行联网探针 |

JSON 模式始终输出同一 Result envelope；CLI exit code：0=ok/no_results，2=输入错误，3=partial，4=failed；输入错误优先于 failed 的一般映射。Ctrl-C 按平台取消约定退出，不伪造业务结果。

SDK 使用 `async with CiteFabricClient(config) as client`，提供同名 async 方法。输入校验错误可抛公开 ValidationError；网络、解析、限流等预期失败返回 Result；未知程序错误保留异常和关联 request ID。

拟定配置优先级：显式 CLI 参数 > 环境变量 > 用户 TOML > 默认值。API key 仅支持环境变量或本地配置，不接收命令行明文参数。TOML 中配置 data_dir、providers、contact_email、资源预算及 verifier；默认数据目录通过平台目录库确定。

## 6. 内部可替换接口

```text
DiscoveryProvider
  capabilities() -> ProviderCapabilities
  search(SearchPlan, RequestContext) -> ProviderResult[SourceRecord]
  resolve(ExternalID, RequestContext) -> ProviderResult[SourceRecord]

DocumentResolver
  resolve(Edition, RequestContext) -> Result[list[DocumentCandidate]]

DocumentFetcher
  fetch(DocumentCandidate, RequestContext) -> Result[Document]

EvidenceParser
  capabilities() -> ParserCapabilities
  parse(LocalBlob, ParseOptions) -> Result[ExtractionSnapshot]

VerifierBackend
  assess(Claim, EvidenceSet, VerificationPolicy, RequestContext)
    -> Result[UntrustedAssessment]
```

RequestContext 包含 deadline、cancellation、request ID、有限预算和已解析配置引用；provider 不直接持有 MCP session。所有插件返回统一契约，经核心层校验；0.1 只注册内置适配器，第三方 entry points 在协议稳定后启用。

将 resolve/fetch/parse 分开，避免一个“EvidenceProvider”同时承担认证、下载、解析和科学判断而无法测试。

## 7. 兼容与重放

0.x 允许有记录的破坏性变更，但迁移必须显式，并保留旧 receipt 原始数据。稳定后新增可选输出字段可作为兼容演进；枚举扩展需要未知值策略和协商，不能假定所有客户端接受。

证据重放验证 document bytes、extraction text、locator、excerpt 四者；模型重跑属于新的验证任务。即使 prompt 相同，远端模型仍可能改变，因此记录 model revision（可取得时）并区分“可审计输入”和“可确定性复现输出”。

本目录的 [示例证据包](examples/evidence-bundle.json) 展示单个合成文档、提取单元、claim 和不可用语义判断。它用于验证契约关联与哈希，不能用来证明 claim verifier 已实现。
