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

## 双人复核

两位标注者分别记录 verdict、必要条件、充分 Evidence ID 集合和一句证据理由。仲裁前计算 verdict 分歧，并保留两份原始标注。仲裁不能查看产品预测。出现 PDF 提取错误、表格结构无法可靠读取或版本身份冲突时，排除样例并记录原因，不能为了凑数强行标注。

Gold evidence 必须能从 extraction snapshot 按 locator 精确回放。哈希一致只证明所评文本未改变，不证明标注意义正确。
