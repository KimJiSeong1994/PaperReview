# Evidence — LightRAG

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| LightRAG extracts entities and relations, then uses low-level and high-level keywords for dual-level graph retrieval. | Guo et al., EMNLP 2025, §§3–4 | method | high |
| The published version reports quality and efficiency experiments, including query time, insertion time, and storage. | §§5–6 and efficiency tables | result | high |
| The method’s accuracy and update behavior depend on LLM-generated graph quality and the evaluated corpus/task settings. | §§5–7 | scope limitation | high |

Method map: chunking → entity/relation graph → low/high-level keywords → local/global retrieval → answer context.

Primary PDF read: https://aclanthology.org/2025.findings-emnlp.568.pdf
