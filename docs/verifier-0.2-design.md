# CiteFabric 0.2 semantic verifier contract

状态：接口与验收协议冻结候选。它不启用模型，也不改变 0.1 的 `verify_claim=unavailable` 行为。

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

1. 定义 `VerifierBackend` 协议和一个显式配置的 provider 实现。
2. 使用结构化输出生成 `VerifierResponse`，失败输出不得进入 Receipt。
3. 校验 schema、atom 覆盖、Evidence ID allowlist、字符预算和哈希。
4. 应用确定性 verdict policy。
5. 将 `VerifierProvenance`、原始结构化输出哈希和最终 verdict 写入不可变 Receipt。
6. 为超时、限流、无效输出和未配置状态返回不同 reason code。

凭据只从环境变量或本地配置读取，不进入 CLI 参数、日志、Receipt 或测试 fixture。真实模型测试使用手动 CI；普通 PR CI 使用假的确定性 backend。

## 验收

[`benchmarks/verifier_v0_2`](../benchmarks/verifier_v0_2) 固定语料规模、gold 标注规则和 promotion gate。已有 Round 4 开发论文只能用于调试，不得进入 promotion holdout。

接入 provider 以前，本阶段完成的只是“可实现且可验收的契约”。只有全新留出集通过 gate，生产 `verify_claim` 才能从默认拒答升级为语义判断。
