# Evidence — Deep GraphRAG

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- | --- |
| Deep GraphRAG uses a three-stage, global-to-local hierarchical retrieval route with beam-search dynamic re-ranking. | Li et al., arXiv:2601.11144, §§3–4 | method | high |
| Its integration module trains a compact model with dynamically weighted relevance, faithfulness, and conciseness rewards. | §5, Figure 3 | method | high |
| The paper reports NQ EM-Total 44.69 for the 72B integration condition versus 42.78 for DRIFT, and 42.36 for its 1.5B DW-GRPO condition. | Tables 1–2 | result | high |
| The reported evaluation is limited to Natural Questions and HotpotQA; weak CQ cells and omitted graph-scale details constrain generalization claims. | result tables and experimental description | scope limitation | medium-high |

Method map: document graph → Louvain hierarchy → inter-community filtering → community refinement → entity search/re-ranking → compact-model knowledge integration.

Result check: all three existing figures, their URLs, sequence, and captions are retained.

Primary source read: `source.pdf` (5 pages; §§2–4 and Tables 1–2), with extracted `source.txt`. URL: https://arxiv.org/abs/2601.11144
