# Evidence — From Local to Global

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| Microsoft GraphRAG builds an entity-relation graph, applies hierarchical Leiden community detection, pre-computes community reports, and maps/reduces partial answers at query time. | Edge et al., arXiv:2404.16130v2, §§3–4 | method | high |
| Its evaluation separates comprehensiveness, diversity, empowerment, and directness rather than treating one score as universal answer quality. | §§5–6 | result framing | high |
| The paper does not show that graph indexing dominates source-text summarization for every metric or question type. | result tables and discussion | scope limitation | high |

Method map: documents → extracted graph → Leiden hierarchy → community reports → query-specific map answers → reduce answer.

Primary local PDF read: `arxiv-2404.16130.pdf` (26 pages; §§3–6 and result tables).
