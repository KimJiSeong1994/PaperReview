# Evidence — CausalRAG

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| CausalRAG builds an LLM-extracted entity-relation graph, seeds retrieval with query-near nodes, expands it, and selects a causal path for answer context. | Wang et al., ACL 2025, §§3–4 | method | high |
| The published paper reports faithfulness 78.00, context recall 49.46, and context precision 92.86 for CausalRAG on its OpenAlex evaluation. | Figure 3 / results table | result | high |
| The graph relations are textual, LLM-extracted causal descriptions; the study does not establish causal identification through interventions or a structural causal model. | §§3, 6–7 | scope limitation | high |
| Automated question generation and RAGAS/GPT-based evaluation, missing component ablations, and cost reporting bound the evidence. | experimental setup and discussion | scope limitation | high |

Method map: paper corpus → entity/relation graph → semantic seed nodes → k-node, s-hop expansion → LLM path selection and summary → answer.

Result check: all four original figures, their URLs, captions, and ordering remain intact.

Primary PDF read: https://aclanthology.org/2025.findings-acl.1165.pdf
