# Evidence — RAGU

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| RAGU separates typed extraction from consolidation through deduplication, summarization, and Leiden community detection. | arXiv:2607.11683, §§3–4 | method | high |
| Meno-Lite-0.1 is a 7B compact in-pipeline model; the paper reports a 12.5% relative harmonic-mean improvement over Qwen2.5-32B for KG construction. | §5, Table 1 | result | high |
| On the medical GraphRAG-Bench setting, the paper reports evidence recall up to 0.84, versus at most 0.76 for compared methods. | §6, result tables | result | high |
| The language-skill versus world-knowledge explanation is a motivating hypothesis evaluated on the selected model family and tasks, not a general scaling law. | introduction and experiments | scope limitation | medium-high |

Method map: typed entity/relation extraction → DBSCAN consolidation → graph/community construction → multi-step retrieval → compact domain-adapted LLM.

Result check: three original figures and their captions are retained in the same sequence.

Primary HTML read: https://arxiv.org/html/2607.11683
