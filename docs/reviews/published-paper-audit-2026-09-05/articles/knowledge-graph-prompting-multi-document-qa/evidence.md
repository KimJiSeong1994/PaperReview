# Evidence — Knowledge Graph Prompting

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| KGP represents passages and document structures as graph nodes, with semantic/lexical and structure edges. | Wang et al., arXiv:2308.11730v3, §3 | method | high |
| Its traversal agent alternates evidence generation and neighbor selection under a retrieval budget. | §4, Eq. 1 | method | high |
| Graph density trades supporting-fact coverage against precision, so a graph alone does not guarantee useful context. | §3, Figure 5 | scope limitation | high |

Method map: documents → passage/page/table graph → initial seed → LLM-guided iterative neighbor traversal → retrieved context → answer.

Primary HTML read: https://arxiv.org/html/2308.11730 (§§3–5 and tables).
