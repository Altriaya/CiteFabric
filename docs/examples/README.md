# 合成证据包说明

[evidence-bundle.json](evidence-bundle.json) 与 [source.txt](source.txt) 组成一个技术设计示例。文本、标题、标识和时间均为演示数据，不代表真实研究或真实工具运行。

该包演示四个互相独立的状态：

- 原始文本与 excerpt 的哈希、字符区间可以重算。
- 论文与文档身份仅为 user_asserted。
- grounding 为 verified，只表示与保存文本一致。
- 未运行语义验证器，verdict 为 unavailable。

这是单对象 bundle 示例，不是工具 Result 响应，也不是正式已发布的可移植包标准。所有 UUID 使用固定演示值；生产环境应随机生成。

可在仓库根目录用 Python 标准库复核：

```python
import hashlib
import json
from pathlib import Path

root = Path("docs/examples")
bundle = json.loads((root / "evidence-bundle.json").read_text(encoding="utf-8"))
raw = (root / bundle["source_file"]).read_bytes()
sha = lambda value: "sha256:" + hashlib.sha256(value).hexdigest()
assert sha(raw) == bundle["document"]["source_hash"]

snapshot = bundle["extraction_snapshot"]
text = "\f".join(unit["text"] for unit in snapshot["text_units"])
assert text == snapshot["text_snapshot"]
assert sha(text.encode("utf-8")) == snapshot["text_hash"]
units = {unit["text_unit_id"]: unit["text"] for unit in snapshot["text_units"]}
for evidence in bundle["evidence"]:
    loc = evidence["locator"]
    excerpt = units[loc["text_unit_id"]][loc["char_start"]:loc["char_end"]]
    assert excerpt == evidence["excerpt"]
    assert sha(excerpt.encode("utf-8")) == evidence["excerpt_hash"]

assert bundle["receipt"]["assessment"]["verdict"] == "unavailable"
print("Text hashes and character offsets verified; no claim support assessed.")
```

正式实现还需验证 Schema、外键、版本关系、完整性失败路径和真实 PDF 定位；这个纯文本示例不能替代这些测试。
