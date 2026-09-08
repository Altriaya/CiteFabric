# 实施与验收计划

状态：设计草案 v0.1 · 日期：2026-09-07。工期假设为一名熟悉 Python 的开发者持续投入；不含上游申请等待、人工标注招募和社区运营。阶段按出口条件推进，不按日历强行发布。

## 1. 发布拆分

调研同时提出“0.1 有五个工具”和“0.2 才有 claim verifier”。设计采用固定接口、明确能力状态的方式协调：0.1 的 verify_claim 能生成证据审计包，但语义判断为 unavailable；0.2 才能宣传可选自动支持判断。

| 阶段 | 预计投入 | 交付 | 出口条件 |
| --- | --- | --- | --- |
| S0：契约与技术验证 | 3–5 个工作日 | Pydantic 模型、状态聚合、SQLite 迁移骨架、SDK/MCP/PDF 小型验证 | 对象关联和错误语义可用 fixtures 验证；关键依赖选型确认 |
| S1：检索与身份 | 5–7 日 | 四个 discovery adapter、限流 runtime、身份映射、search/get CLI | 重复/冲突场景正确；部分失败保留；匿名模式有可用降级 |
| S2：证据与导出 | 7–10 日 | 文档导入、受控 OA 获取、基础 PDF 提取、FTS、EvidenceObject、BibTeX/CSL-JSON | 精确版本与原文片段可重放；坏文档不污染结果 |
| S3：0.1 发布准备 | 3–5 日 | 五个 MCP tools、资源读取、SDK 示例、跨平台 CI、真实演示 | 协议与 CLI smoke 通过；文档明确不可用能力；打包安装通过 |
| S4：0.2 验证器 | 10–15 日，另计标注 | 可选模型后端、receipt 完整判断、引用样式、评测报告 | 通过校准与保留测试集；错误支持率和拒答覆盖同时报告 |

0.1 的粗估为 18–27 个开发工作日；这是排期起点。若 PDF 绑定、文本定位或安装依赖验证失败，先缩小声明的输入范围，再修订排期。

0.3 再加入 PubMed/Europe PMC、Zotero、Citra/GROBID。citation audit、research workspace、图谱、云部署在已观察到用户需求后单独立项。

## 2. S0 必须回答的技术问题

| 验证任务 | 方法 | 失败后的处理 |
| --- | --- | --- |
| 官方 MCP SDK 的结构化输出与取消行为 | 最小服务 + 真实 ClientSession stdio 调用，检查 schema/isError/取消 | 保留 transport adapter，修正版本或实现显式结果封装 |
| 基础 PDF 提取质量 | 数字原生单栏/双栏/扫描件各若干，人工对照页文本 | 限制基础能力；结构化 parser 作为 optional extra |
| 文档身份绑定 | DOI、arXiv 版本、标题、错误 PDF、不同版本 fixtures | 无法确认的文档保持 unresolved，禁止自动支持判断 |
| SQLite 多进程预算与并发 | 两个 MCP/CLI 进程共享目录，竞争 provider 租约与同 ID 写入 | 调整事务/租约；必要时限制共享目录写入方式 |
| 匿名上游实际可用性 | 低频真实 search/get 探针，不带个人 key | 更新默认来源策略；保留明确错误，不替换为空列表 |
| APA/IEEE 渲染器 | 用固定 CSL fixtures 比对作者、团体作者、非拉丁文、缺失字段 | 0.2 暂不开放相关 format，不能手写“近似 APA”冒充完成 |

这些验证是实现阶段的任务，本次设计没有声称已完成它们。

## 3. 核心测试矩阵

| 模块 | 必须覆盖的行为 |
| --- | --- |
| 身份规范化 | DOI 大小写/URL/转义/合法标点；arXiv 新旧 ID 与版本；空年份；团体作者 |
| 身份关系 | 同 DOI 跨源去重；同标题不同论文保留；预印本/期刊分版；更正/撤稿不并为原文 |
| 合并生命周期 | 旧 ID 可解析；并发唯一约束；误合并补偿；旧 receipt 不被改写 |
| 上游故障 | 429 + Retry-After 秒/日期；403；超时；错误 JSON/XML；200 内嵌 API error |
| 部分结果 | 成功空 + 失败 => partial；全部成功空 => no_results；全部失败 => failed |
| 缓存 | stale 显示；不缓存失败为空结果；密钥作用域隔离；单 waiter 取消不误伤共享请求 |
| 全文获取 | OA URL 失效；200 登录 HTML；版本不符；重定向私网；DNS 重绑定；大文件 |
| PDF 提取 | 扫描件不当作空成功；部分页失败；损坏 PDF；双栏乱序告警；解析进程超时终止 |
| 证据 | 非 ASCII 字符偏移；页号 1 起算；bbox 变换；跨页拆分；三类哈希与 quote 对齐 |
| 验证 | 不存在的 evidence ID；数字/单位不符；范围扩大；复合论断；双向证据；未配置后端 |
| 引用 | BibTeX 转义；key 碰撞；CSL 合法性；期刊引用与预印本证据明确区分 |
| 接口 | 五工具工具清单；input/output schema；MCP isError；CLI JSON/exit code；SDK 同结果 |
| 生命周期 | 迁移失败回滚；Ctrl-C 取消；stdout 无日志；租约过期恢复；缓存驱逐不删 pin 对象 |

单元与 fixture 测试不得依赖真实网络或收费模型。定时上游探针单独执行，失败报告为 provider 回归，不使离线贡献者的测试随机失败。CI 的 fixture 只使用可再分发或合成材料，并保存来源与许可说明。

## 4. 评测数据与指标定义

### 4.1 身份与检索

起步数据集目标：300 对人工标注的论文记录，包含同版重复、关联版本、相似标题非重复、错误外部 ID；另有 50 个研究查询及人工整理的相关文献池。按研究工作分割开发/测试，避免同一论文不同版本泄漏。

- 自动合并 precision：正确自动合并对数 / 全部自动合并对数；与 recall 同报。0.1 自动合并仅基于强 ID 与无冲突规则。
- 展示重复率：前 k 项中重复的同版条目数 / 返回条目数；关联版本不计为同版重复。
- Canonical Recall@20：前 20 个工作中命中的已标注相关工作 / 已标注相关工作总数。它是对构建的相关文献池的召回率，不是对全世界论文的完整召回率。
- Provider failure recovery：注入故障后，其他成功来源的有效候选被保留的比例；与错误状态正确率分别报告。

### 4.2 证据定位

起步目标：至少 30 篇允许测试使用的文档、150 个人工标注段落；包含数字原生 PDF、摘要-only、扫描件和版本差异。

- Passage Recall@6：返回最多六片段是否覆盖标注证据；多段组合支持单独标注。
- Page accuracy：正确物理页定位条数 / 有页定位输出条数；同时报告不支持定位的比例。
- Grounding integrity：所有 evidence 的字节/文本/区间检查通过率，确定性 fixtures 必须 100%。
- document binding precision：被自动确认的文档中确属目标版本的比例；未知绑定不能排除在 coverage 报告之外。

### 4.3 ClaimBench 初版

目标 400 条 claim–edition 样本，支持/部分支持/反驳/不足四类尽量均衡；每条关联人工核对的原文和语境。另设运行失败集，不把 unavailable 混入语义标签。样本按 Paper 分割开发、校准、保留测试集；两位标注者独立判断并裁决分歧。

先覆盖英文、文本直接陈述、常见数值比较。中文、跨语言推断、复杂图表和跨多篇综合结论单独报告，不在第一份成绩中混称支持。

指标同时展示计数、分母与置信区间：

- False-support share：预测 supported 但人工不认为 fully supported 的数量 / 所有预测 supported 的数量。人工 partially_supported 在这里也算错误支持。
- False-positive support rate：人工非 fully supported 却预测 supported 的数量 / 所有人工非 fully supported 的数量。与上一个分母不同，必须分开命名。
- Macro-F1：四个语义标签的宏平均；对固定可执行样本，系统 unavailable 按对应真实类的漏判计入，并另报运行成功率，避免靠故障改善分数。
- Abstention rate：insufficient_evidence 数 / 已完成语义判断数。
- Abstention precision：拒答中人工同样标注不足的数 / 拒答数。
- Decision coverage：supported/partially_supported/contradicted 数 / 所有计划评估样本数；运行失败也计入分母。

0.2 拟定晋级目标：保留测试集至少 300 条，预测 supported 至少 100 条；错误支持占比的单侧 95% Clopper–Pearson 上界不超过 5%，decision coverage 至少 40%，Macro-F1 至少 0.70。400 条起步数据不足以同时满足分割与样本数时继续扩充，不能挪用校准集。

这些是拟定门槛，不是已测成绩，也不证明所有科研领域有效。达不到时保留 experimental 标签或不发布自动判断，不能靠扩大拒答隐藏错误。

## 5. 性能与资源验收

目标环境先固定一台 4 核、8 GiB 内存开发机，记录 OS、Python、网络与依赖版本；结果注明 warm/cold cache。

| 场景 | 拟定目标 | 解释 |
| --- | --- | --- |
| 安装后本地 MCP 初始化 | p95 ≤ 2 秒 | 不含下载依赖；不应加载模型权重 |
| 已缓存的 search/get | p95 ≤ 500 ms | 固定小型数据集 |
| 网络 search | 在 12 秒预算结束后 1 秒内返回 | 慢来源降级，不保证全源完成 |
| 已解析全文 evidence 检索 | p95 ≤ 1 秒 | 100 篇规模、默认片段预算 |
| 解析与下载 | 不超过规定大小/页数/进程时限 | 触发限制必须返回 resource_limit |
| 工具定义上下文 | 发布时实测总字节与选定 tokenizer 的 token 数 | 五工具只是数量目标，不能推导必然节省倍数 |

冷启动证据获取不承诺调研演示中的“1.8 秒”。记录每阶段时间，分别评估下载、解析、索引和模型调用。

## 6. 0.1 发布检查

- 三个平台运行契约测试、SQLite/FTS5 smoke、CLI/MCP 端到端 smoke。
- 干净环境 build wheel/sdist 并本地安装，入口可用；PyPI 项目名称和 namespace 在发布前核对。
- README 给出真实查询及真实出处；合成 demo 显式标注。未实现的 verifier/OCR/APA 不写成可用功能。
- 建立贡献指南、行为准则、错误报告模板；拟采用 Apache-2.0，发布前核对依赖许可与项目归属。
- 准备 MCP Registry 所需元数据并按届时官方 schema 校验；不能把未提交的记录写成已收录。
- MCP Inspector 检查工具列表、结果与资源；并行保留自动化 stdio 集成测试。
- 生成版本变更记录、benchmark 方法与原始计数。发布、账号注册和推广消息属于后续实际发布任务。

## 7. 风险与控制

| 风险 | 对交付的影响 | 已选应对 |
| --- | --- | --- |
| 上游额度或字段变化 | 零配置体验不稳定 | provider 独立状态、capabilities、固定 fixtures + 在线探针 |
| 元数据把不同版本混在一起 | 错误身份与证据归属 | Edition 分层、冲突隔离、无法确认则 abstain |
| PDF 可提取但顺序错乱 | 找到错误段落或错误解释 | 解析质量告警、人工样本对照、结构化 adapter 后续补强 |
| 模型把相关性当支持 | 科研信任风险 | 严格 evidence 绑定、范围核对、独立评测与拒答 |
| 大量 receipt 占磁盘 | 缓存超预算 | pin 与普通 LRU 分开，显式报告容量限制 |
| 过早堆叠 provider/框架 | MVP 长期不可发布 | 按 S0–S3 出口条件交付，新增来源延后 |

## 8. 首个开发切片

进入实现时先完成一个窄闭环：两份来源 fixture → 相同 DOI 的 Edition 去重 → 显式导入合成文本/测试 PDF → 找到指定片段 → 重算哈希 → 导出 CSL-JSON 与 unavailable verifier receipt。

该切片先验证贯穿全栈的数据契约，再接真实网络。后续顺序为 runtime、四源 adapter、受控 PDF 路径、MCP 包装、真实 demo。避免在身份与证据格式尚不稳定时同时开发四套入口和大量插件。
