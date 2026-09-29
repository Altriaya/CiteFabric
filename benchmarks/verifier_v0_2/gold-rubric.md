# Verifier 0.2 gold annotation rubric

## 标注单位

标注单位是 `claim × edition × frozen evidence bundle`。Gold 判断的是给定证据是否足以建立论断，不判断现实世界中的最终科学真相。

先把复合 claim 拆成原文中的精确原子切片，再为每个 atom 列出必要条件：对象、数据集/人群、模型/方法、版本、指标、数值、单位、方向、基线、时间、范围和因果强度。不能在拆分时翻译、修正或补充原句。

## Verdict

- `supported`：每个 atom 的全部必要条件都被同一 edition 的直接证据覆盖。近似主题、相邻实验或只覆盖部分条件不算支持。
- `contradicted`：证据在相同对象和实验范围下给出互斥结果。不同数据集、版本、基线或时间的不同结果不构成反驳。
- `insufficient_evidence`：必要条件缺失、表述含混、只有间接推断、存在未解决的证据冲突，或 evidence bundle 未覆盖该结论。
- `unavailable` 不是 gold 科学标签，只用于记录系统未成功执行。

“论文没有在给定片段中提到 X”通常是证据不足。只有论文明确给出穷尽范围并声明不存在匹配情况，才可用 absence 建立反驳。

## Contradiction 边界

- Gold 只能使用冻结 evidence bundle。标注者从整篇论文知道某论断为假，但该事实没有进入 bundle 时，仍应标为 `insufficient_evidence`。
- “指标 X 衡量 A”本身不排除 X 同时衡量 B。只有证据将定义表述为穷尽/排他，或 A 与 B 在证据给出的同一操作定义下互斥时，“X 衡量 B”才构成 `contradicted`；否则属于未建立。
- 表格范围断言必须由 bundle 中可读的全部相关行覆盖。只出现部分数据集、总结性措辞或表格引用，不能建立“每个数据集”，也不能用整表中未进入 bundle 的单元格反驳它。
- 数据集列表同理：bundle 未列出 X 只能证明 X 未被当前证据建立；只有明确、穷尽的列表且不含 X，或正文明确排除 X，才能反驳“使用了 X”。

## 双人复核

两位标注者分别记录 verdict、必要条件、充分 Evidence ID 集合和一句证据理由。仲裁前计算 verdict 分歧，并保留两份原始标注。仲裁不能查看产品预测。出现 PDF 提取错误、表格结构无法可靠读取或版本身份冲突时，排除样例并记录原因，不能为了凑数强行标注。

Gold evidence 必须能从 extraction snapshot 按 locator 精确回放。哈希一致只证明所评文本未改变，不证明标注意义正确。
