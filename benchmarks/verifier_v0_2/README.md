# Verifier 0.2 evaluation

本目录定义 CiteFabric 0.2 语义核验器的冻结候选协议。它与 Round 4 retrieval 评测分开：retrieval 负责找出候选原文，verifier 负责判断固定论断与固定证据之间的关系。

文件：

- [protocol.md](protocol.md)：数据冻结、运行与开封顺序。
- [gold-rubric.md](gold-rubric.md)：支持、反驳、证据不足的标注准则。
- [promotion-gate.md](promotion-gate.md)：语料资格、指标和发布门槛。
- [fixture.schema.json](fixture.schema.json)：合并后的封存评测报告 Schema。

生成 Schema：

```bash
uv run python scripts/verifier_promotion_gate.py schema \
  --output benchmarks/verifier_v0_2/fixture.schema.json
```

评分：

```bash
uv run python scripts/verifier_promotion_gate.py score \
  --input PRIVATE_EVALUATION.json \
  --output output/verifier-v0.2/promotion-report.json
```

评分器只执行机械统计和 gate 判断，不创建 gold，也不能证明独立性。`independence_verified` 等字段必须由实际保管和审阅记录支持。
