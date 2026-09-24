# Evidence — HippoRAG

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| HippoRAG uses LLM OpenIE, synonymy links, and Personalized PageRank seeded by query entities to rank passages. | Gutiérrez et al., arXiv:2405.14831v3, §2 | method | high |
| On 2WikiMultiHopQA, HippoRAG (ColBERTv2) reports R@5 89.1 versus 68.2 for ColBERTv2; on HotpotQA it reports 77.7 versus 79.3. | Table 2 | result | high |
| The biological analogy motivates the design; the evaluation demonstrates graph retrieval, not general human-like long-term memory. | §§1–2, 7 | scope limitation | high |

Method map: passages → OpenIE KG + synonym edges → query entities → entity linking → PPR → passage scoring.

Primary sources read: local `arxiv-2405.14831.pdf` (31 pp.) and https://arxiv.org/html/2405.14831 (§§2–5, Table 2).
