"""Build a natural-Chinese retrieval development fixture before running retrieval.

The questions are manually curated against an already-opened authoring worksheet.
This is a self-reviewed development set, not an independent or blind holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from round4_span_anchored_fixture import PAPERS, review

QUESTIONS = {
    "bert": [
        (
            "How is development accuracy summarized for the selected GLUE tasks?",
            "BERT在所选GLUE任务上的开发集准确率是怎样汇总的？",
        ),
        (
            "Which systems are excluded from the comparison with earlier leaderboard and published work?",
            "BERT与此前排行榜及已发表工作比较时，排除了哪一类系统？",
        ),
        (
            "What test results do BERT Base and BERT Large obtain across the GLUE tasks?",
            "BERT基础版和大模型在GLUE各项测试中的结果分别是多少？",
        ),
        (
            "How do depth, hidden size and attention-head count affect perplexity and downstream development scores?",
            "模型层数、隐藏维度和注意力头数量变化时，困惑度与下游开发集成绩如何变化？",
        ),
        (
            "What happens under the different token-masking ablations?",
            "改变预训练时被替换、保留和随机替换词元的比例，会怎样影响微调与特征抽取结果？",
        ),
        (
            "What construction issue and majority-class baseline are reported for the problematic GLUE dataset?",
            "论文指出GLUE中的问题数据集存在哪种构造缺陷，多数类预测基线是多少？",
        ),
    ],
    "ddpm": [
        (
            "How does the diffusion model compare on CIFAR-10 using inception score, FID and negative log likelihood?",
            "扩散模型在CIFAR-10上的生成质量、分布距离和负对数似然表现如何？",
        ),
        (
            "What FID results are reported for the three LSUN 256 by 256 datasets?",
            "该方法在三个LSUN 256×256数据集上的图像质量指标分别是多少？",
        ),
        (
            "How is distortion measured in the progressive compression experiment?",
            "渐进压缩实验使用什么尺度和指标衡量失真？",
        ),
        (
            "What likelihood limitation do the authors report despite good sample quality?",
            "尽管样本质量较好，作者承认该模型在似然方面有什么不足？",
        ),
        (
            "What is the effect of learning the reverse-process variance instead of fixing it?",
            "反向过程的方差由模型学习而不是固定时，训练和样本质量会发生什么变化？",
        ),
        (
            "What are the main unconditional CIFAR-10 and 256 by 256 LSUN results claimed in the abstract?",
            "摘要对无条件CIFAR-10和高分辨率LSUN实验给出了哪些主要结果？",
        ),
    ],
    "deepvariant": [
        (
            "After retraining for SOLID and PacBio, what precision and sensitivity tradeoff is observed?",
            "针对SOLID和PacBio重新训练后，精确率与灵敏度之间呈现什么权衡？",
        ),
        (
            "How does a model trained on human data perform on mouse data compared with mouse-specific training?",
            "使用人类数据训练的模型迁移到小鼠数据后，与专门用小鼠数据训练相比表现如何？",
        ),
        (
            "How do the reported variant-calling metrics differ across sequencing technologies?",
            "不同测序技术上的变异检测指标有何差异？",
        ),
        (
            "How are reported genotype quality scores checked against observed errors?",
            "论文如何用实际错误率检验模型报告的基因型质量分数？",
        ),
        (
            "What problem does the convolutional network solve from read-pileup images?",
            "卷积神经网络从测序读段堆叠图像中学习解决什么任务？",
        ),
        (
            "How were learning rate and momentum combinations used to choose the final model?",
            "实验怎样组合学习率和动量，并据此选择最终模型？",
        ),
    ],
    "end2end-driving": [
        (
            "How much driving data had been collected and what training objective was minimized?",
            "截至论文所述日期收集了多少驾驶数据，训练时最小化的目标是什么？",
        ),
        (
            "What role does the DAVE-2 collection system play in the approach?",
            "DAVE-2的数据采集系统在整体方案中承担什么作用？",
        ),
        (
            "Which conventional driving subtasks were not trained explicitly?",
            "端到端系统没有显式训练哪些传统自动驾驶子任务？",
        ),
        (
            "How is driving autonomy calculated from interventions and elapsed time?",
            "道路测试中怎样根据人工干预次数和行驶时间计算自动驾驶比例？",
        ),
        (
            "What layer sequence and input dimensions are used by the driving network?",
            "驾驶网络接收多大尺寸的输入，并依次采用了哪些卷积层和全连接层？",
        ),
        (
            "What does the simulation test estimate before an on-road test?",
            "车辆上路测试之前，仿真测试主要估计什么能力？",
        ),
    ],
    "gat": [
        (
            "How does GAT compare with other transductive methods on the three citation networks?",
            "图注意力网络在三个引文网络上与其他传导式方法相比表现如何？",
        ),
        (
            "Where are the comparative evaluation results summarized?",
            "论文把比较实验的结果汇总在哪些表中？",
        ),
        (
            "Which datasets are used for transductive and inductive evaluation?",
            "传导式和归纳式评估分别使用了哪些数据集？",
        ),
        (
            "What implementation limitation restricts batching over multiple graphs?",
            "实现中的哪项张量运算限制了多图批处理能力？",
        ),
        (
            "What are the claimed benefits and limitations of the graph-attention building block?",
            "图注意力基本层相对已有图神经网络有哪些理论与实践优点和限制？",
        ),
        (
            "Across which four benchmarks did GAT match or reach state of the art?",
            "图注意力模型在哪四个基准上达到或匹配了当时最佳结果？",
        ),
    ],
    "gw170817": [
        (
            "What does the chronological observation table contain?",
            "按时间排列的观测结果表记录了哪些内容？",
        ),
        (
            "What X-ray limits and detections are reported after the gravitational-wave trigger?",
            "引力波触发后，不同时间的X射线观测给出了哪些上限或探测结果？",
        ),
        (
            "What gamma-ray monitoring limits are reported around the trigger time?",
            "触发时刻前后，各伽马射线仪器报告了哪些能段和通量上限？",
        ),
        (
            "Which instruments and bands continued observing the counterpart in late August?",
            "八月下旬有哪些仪器继续在什么波段观测该对应体？",
        ),
        (
            "What wavelength coverage and resolution were used in the early spectroscopic observations?",
            "早期光谱观测覆盖了哪些波长范围，采用了怎样的分辨率？",
        ),
        (
            "What radio flux limits were reported at different frequencies and times?",
            "不同时间和频率上的射电观测给出了哪些流量上限？",
        ),
    ],
    "nuts": [
        (
            "Why is approximate inference needed for the models discussed in the paper?",
            "论文讨论的模型为什么通常需要近似推断？",
        ),
        (
            "Why can the naive effective-sample-size estimator behave badly at long lags?",
            "为什么直接使用长滞后自相关估计有效样本量会产生较差结果？",
        ),
        (
            "What auxiliary variables does Hamiltonian Monte Carlo introduce?",
            "哈密顿蒙特卡洛为每个模型变量引入了什么辅助变量？",
        ),
        ("How is the leapfrog step size adapted?", "算法如何自适应设置蛙跳积分的步长？"),
        (
            "What memory problem can arise when storing the recursively doubled trajectory?",
            "保存递归倍增的轨迹时可能出现怎样的内存问题？",
        ),
        (
            "How are NUTS, random-walk Metropolis and Gibbs sampling compared qualitatively?",
            "论文从哪些方面定性比较NUTS、随机游走Metropolis和Gibbs采样？",
        ),
    ],
    "quantum-supremacy": [
        (
            "Which assumptions can make the predicted classical runtime differ from measured runtime?",
            "哪些假设可能导致经典模拟运行时间的理论预测与实际测量出现较大差异？",
        ),
        (
            "What limitations of full circuits motivate the alternative circuit variants?",
            "完整随机电路存在哪些限制，为什么需要采用其他电路变体？",
        ),
        (
            "What simulation quantities are reported for the two JUQCS implementations?",
            "两种JUQCS实现的模拟结果比较了哪些量？",
        ),
        (
            "How are the alpha quantities and their estimators compared in the simulation table?",
            "模拟表如何比较若干alpha量及其估计值？",
        ),
        (
            "What statistical uncertainty is reported for the measured fidelities?",
            "测得的保真度具有多大的统计不确定性？",
        ),
        (
            "How does the gate-failure model relate gate error rates to Pauli errors?",
            "门失效模型在把门错误率联系到具体Pauli错误时还存在哪些不足？",
        ),
    ],
}


ABSENT = {
    "bert": [
        (
            "What CMRC score is reported for Chinese reading comprehension?",
            "论文报告了BERT在中文阅读理解CMRC上的什么成绩？",
        ),
        (
            "What result is reported for a 48-layer BERT model?",
            "论文报告了48层BERT模型的什么结果？",
        ),
    ],
    "ddpm": [
        (
            "What FID is reported for 512 by 512 ImageNet generation?",
            "论文报告了512×512 ImageNet生成任务的FID吗？",
        ),
        (
            "How does the model perform on video generation?",
            "论文报告了该模型在视频生成上的表现吗？",
        ),
    ],
    "deepvariant": [
        (
            "What accuracy is reported for Oxford Nanopore RNA sequencing?",
            "论文报告了Oxford Nanopore RNA测序上的准确率吗？",
        ),
        (
            "What outcome is reported from a prospective pediatric clinical trial?",
            "论文报告了前瞻性儿科临床试验的结果吗？",
        ),
    ],
    "end2end-driving": [
        (
            "What collision rate is reported after one million autonomous miles?",
            "系统自动驾驶一百万英里后的碰撞率是多少？",
        ),
        (
            "How does a lidar-only model perform on snowy nights?",
            "仅使用激光雷达的模型在雪夜环境中表现如何？",
        ),
    ],
    "gat": [
        (
            "What test accuracy is reported on ogbn-products?",
            "论文报告了ogbn-products数据集上的测试准确率吗？",
        ),
        ("How does a one-hundred-layer GAT perform?", "一百层图注意力网络的表现如何？"),
    ],
    "gw170817": [
        (
            "What neutrino-mass limit is derived from the event?",
            "论文利用该事件推导了怎样的中微子质量上限？",
        ),
        (
            "What radio flux is reported one hundred days after the trigger?",
            "触发一百天后的射电流量是多少？",
        ),
    ],
    "nuts": [
        (
            "What GPU runtime is reported for sampling a transformer model?",
            "NUTS采样Transformer模型时的GPU运行时间是多少？",
        ),
        (
            "How does NUTS perform on a quantum-circuit posterior?",
            "NUTS在量子电路后验分布上的表现如何？",
        ),
    ],
    "quantum-supremacy": [
        (
            "What error rate is projected for a one-thousand-qubit processor?",
            "论文预测一千量子比特处理器的错误率是多少？",
        ),
        ("What carbon emissions are reported for the experiment?", "该实验报告了多少碳排放？"),
    ],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("Output already exists")
    worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
    papers, intents, cases = [], [], []
    for source in worksheet["papers"]:
        paper_id = source["paper_id"]
        title, domain, url, pages = PAPERS[paper_id]
        papers.append(
            {
                "paper_id": paper_id,
                "family_id": "natural-zh-development-" + paper_id,
                "title": title,
                "domain": domain,
                "source_url": url,
                "filename": source["filename"],
                "sha256": source["source_sha256"],
                "pages": pages,
                "edition_label": "frozen local PDF",
                "metadata_basis": "Source URL and SHA-256 fixed before retrieval.",
                "layer": "stress",
                "challenges": ["narrative", "formula", "single_page_table"],
            }
        )
        for index, (en, zh) in enumerate(QUESTIONS[paper_id], 1):
            candidate = source["candidates"][index - 1]
            intent_id = f"{paper_id}-answerable-{index:02d}"
            intents.append(
                {
                    "intent_id": intent_id,
                    "parent_intent_id": None,
                    "paper_id": paper_id,
                    "query": {"en": en, "zh": zh},
                    "claim": {
                        "en": "The paper explicitly contains the information requested by the query.",
                        "zh": "论文原文明确包含该问题所询问的信息。",
                    },
                    "equivalence_review": review(),
                }
            )
            cases.append(
                {
                    "intent_id": intent_id,
                    "paper_id": paper_id,
                    "source_sha256": source["source_sha256"],
                    "extraction_text_sha256": source["extraction_text_sha256"].removeprefix(
                        "sha256:"
                    ),
                    "reference_verdict": "supported",
                    "rationale": "Natural-query retrieval development item with an exact source span.",
                    "tags": ["table_numeric"]
                    if "Table" in candidate["quote"]
                    else ["method_definition"],
                    "spans": [
                        {
                            "span_id": "s1",
                            "unit_index": candidate["unit_index"],
                            "page": candidate["page"],
                            "start": candidate["start"],
                            "end": candidate["end"],
                            "quote": candidate["quote"],
                            "role": "result",
                        }
                    ],
                    "requirements": [
                        {
                            "requirement_id": "r1",
                            "dimension": "other",
                            "description": "Exact answer-bearing source passage",
                            "span_ids": ["s1"],
                            "visual_requirements": [],
                            "relation": "explicit answer context",
                            "derivation": None,
                        }
                    ],
                    "sufficient_sets": [["r1"]],
                    "absence_review": None,
                    "review": review(),
                }
            )
        for offset, (en, zh) in enumerate(ABSENT[paper_id], 1):
            intent_id = f"{paper_id}-insufficient-{offset:02d}"
            intents.append(
                {
                    "intent_id": intent_id,
                    "parent_intent_id": None,
                    "paper_id": paper_id,
                    "query": {"en": en, "zh": zh},
                    "claim": {"en": en, "zh": zh},
                    "equivalence_review": review(),
                }
            )
            cases.append(
                {
                    "intent_id": intent_id,
                    "paper_id": paper_id,
                    "source_sha256": source["source_sha256"],
                    "extraction_text_sha256": source["extraction_text_sha256"].removeprefix(
                        "sha256:"
                    ),
                    "reference_verdict": "insufficient",
                    "rationale": "The named configuration or outcome is outside the paper's reported scope.",
                    "tags": ["unreported_configuration", "condition_counterexample"],
                    "spans": [],
                    "requirements": [],
                    "sufficient_sets": [],
                    "absence_review": {
                        "sections_reviewed": ["complete extracted PDF snapshot"],
                        "terms_searched": [en],
                        "missing_conditions": "The requested configuration or outcome is not reported.",
                        "limitations": "AI self-review; must be independently checked before any release claim.",
                    },
                    "review": review(),
                }
            )
    queries = {
        "schema_version": "round4-0.1",
        "kind": "queries",
        "protocol_version": "0.1-draft",
        "cohort_id": "natural-zh-opened-development-20260929",
        "split": "development",
        "status": "frozen",
        "papers": papers,
        "intents": intents,
    }
    args.output_dir.mkdir(parents=True)
    query_path = args.output_dir / "queries.json"
    query_path.write_text(
        json.dumps(queries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    gold = {
        "schema_version": "round4-0.1",
        "kind": "gold",
        "protocol_version": queries["protocol_version"],
        "cohort_id": queries["cohort_id"],
        "queries_sha256": digest(query_path),
        "cases": cases,
    }
    (args.output_dir / "gold.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
