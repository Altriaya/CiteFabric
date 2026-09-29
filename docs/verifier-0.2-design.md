# CiteFabric 0.2 semantic verifier contract

状态：接口、Fake Backend、OpenAI Responses API adapter 与验收协议已实现。真实 provider 必须显式启用；默认仍保持 `verify_claim=unavailable`。当前仓库环境未配置 API key，因此尚无真实 GPT-5.5 评分结果。

## 目标

0.2 只回答一个受限问题：**给定某一论文版本、一个论断和一组已落地的原文证据，这些证据是支持、反驳，还是不足以判断该论断？** 它不判断全学界共识，也不允许模型联网补充证据。

模型只产生结构化观察，最终 verdict 由确定性代码导出：

- `supported`：每个原子论断的全部关键条件均被同版本证据直接覆盖。
- `contradicted`：至少一个原子论断存在同对象、同条件、同范围的直接冲突。
- `insufficient_evidence`：没有直接冲突，但至少一个必要条件缺失或含混。

技术故障使用 `unavailable`，不得伪装成 `insufficient_evidence`。

## 冻结契约

[`verifier_contract.py`](../src/citefabric/verifier_contract.py) 定义模型边界：

1. `VerifierRequest` 固定 claim、edition、原子论断和最多 6 条、合计最多 6000 字符的证据。
2. 原子论断必须是原 claim 中按顺序、不重叠的精确字符切片，防止拆分时悄悄改写数字或限定条件。
3. Evidence 必须来自同一 edition，excerpt 哈希和 locator 长度必须一致。
4. `VerifierResponse` 为每个 atom 返回现有 `SemanticAssessment` 三轴观察。
5. 应用层要求 atom 完整、有序，引用 ID 必须来自输入 allowlist，之后才执行三分类策略。
6. `VerifierProvenance` 固定 provider、模型/修订、prompt 与输入输出哈希、策略版本、重试、延迟和 token/费用字段；后续接入模型时写入 EvidenceReceipt。

生成的 0.2 Schema 位于 [`schemas/0.2`](../schemas/0.2)。0.1 公共 Schema 和现有 MCP 工具没有变化。

论文正文和 evidence excerpt 一律作为不可信数据。后端提示词必须把指令与证据分隔，并明确忽略正文内的操作要求；模型无权调用工具、联网、变更证据或选择另一版本论文。

## 模型接入状态

已完成：

1. [`verifier_backend.py`](../src/citefabric/verifier_backend.py) 定义异步 `VerifierBackend` 协议、结构化结果 envelope 和只能依赖注入的 `FakeVerifierBackend`。
2. `CiteFabricClient.verify_claim` 已执行 Backend 调用、超时、Schema、atom、Evidence ID、预算和哈希校验。
3. 合法输出由确定性 policy 生成 verdict 和不可变 Receipt；非法输出、超时、无证据和未配置状态均保存 `unavailable` Receipt 与独立 reason code。
4. SDK 和 MCP handler 已用 Fake Backend 跑通，默认 CLI 仍拒答，避免测试判断被用户误启用。
5. [`openai_verifier.py`](../src/citefabric/openai_verifier.py) 使用 Responses API 的严格 JSON Schema 输出，禁用工具与服务端存储，并映射认证、限流、超时、服务故障和非法输出。
6. provider、模型快照、reasoning effort、输出预算与凭据已加入配置；`doctor` 只报告凭据是否存在，不输出凭据值。
7. [`openai_verifier_dev_run.py`](../scripts/openai_verifier_dev_run.py) 对已冻结开发证据执行可复现实验，保存输入哈希、响应 ID、token、费用与 Receipt，并确保 gold 不进入模型请求。

adapter 当前固定默认模型为 `gpt-5.5-2026-04-23`，价格计算按 2026-09-29 查阅的官方模型页版本化。OpenAI 官方文档说明 GPT-5.5 支持 Responses API 与 Structured Outputs；Responses API 的严格结构化输出通过 `text.format` 提交 JSON Schema：

- <https://developers.openai.com/api/docs/models/gpt-5.5>
- <https://developers.openai.com/api/docs/guides/structured-outputs>

下一步是使用真实凭据运行六条 opened-development pilot，检查结构化输出可靠性、三类错误、延迟和费用。prompt 冻结后才进入全新留出集。

凭据只从环境变量或本地配置读取，不进入 CLI 参数、日志、Receipt 或测试 fixture。真实模型测试使用手动 CI；普通 PR CI 使用假的确定性 backend。

## 验收

[`benchmarks/verifier_v0_2`](../benchmarks/verifier_v0_2) 固定语料规模、gold 标注规则和 promotion gate。已有 Round 4 开发论文只能用于调试，不得进入 promotion holdout。

当前实现与模拟 HTTP 测试证明核验器可以贯通 SDK、MCP、真实 API 协议形状、确定性校验与 Receipt；这不等于真实模型准确率。只有真实 provider 在全新留出集通过 gate，生产 `verify_claim` 才能从默认拒答升级为语义判断。
