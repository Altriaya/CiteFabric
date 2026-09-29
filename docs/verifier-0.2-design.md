# CiteFabric 0.2 semantic verifier contract

状态：接口、Fake Backend 核验流水线与验收协议已实现。尚未接入收费或联网模型；未注入 Backend 时仍保持 `verify_claim=unavailable`。

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

## 模型接入顺序

已完成：

1. [`verifier_backend.py`](../src/citefabric/verifier_backend.py) 定义异步 `VerifierBackend` 协议、结构化结果 envelope 和只能依赖注入的 `FakeVerifierBackend`。
2. `CiteFabricClient.verify_claim` 已执行 Backend 调用、超时、Schema、atom、Evidence ID、预算和哈希校验。
3. 合法输出由确定性 policy 生成 verdict 和不可变 Receipt；非法输出、超时、无证据和未配置状态均保存 `unavailable` Receipt 与独立 reason code。
4. SDK 和 MCP handler 已用 Fake Backend 跑通，默认 CLI 仍拒答，避免测试判断被用户误启用。

下一步：

1. 实现一个显式配置的真实 provider adapter，使用结构化输出生成 `VerifierResponse`。
2. 将 provider 凭据、模型名和预算加入本地配置，默认继续为 `none`。
3. 使用现有 opened development set 调试 prompt、延迟、费用与错误恢复；冻结后才进入全新留出集。

凭据只从环境变量或本地配置读取，不进入 CLI 参数、日志、Receipt 或测试 fixture。真实模型测试使用手动 CI；普通 PR CI 使用假的确定性 backend。

## 验收

[`benchmarks/verifier_v0_2`](../benchmarks/verifier_v0_2) 固定语料规模、gold 标注规则和 promotion gate。已有 Round 4 开发论文只能用于调试，不得进入 promotion holdout。

当前实现证明核验器可以在不需要 API Key 的情况下贯通 SDK、MCP、确定性校验与 Receipt。只有真实 provider 在全新留出集通过 gate，生产 `verify_claim` 才能从默认拒答升级为语义判断。
