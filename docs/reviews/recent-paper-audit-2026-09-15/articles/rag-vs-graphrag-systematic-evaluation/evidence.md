# RAG vs. GraphRAG — evidence ledger and revision audit

**Review date:** 2026-09-15 (Asia/Seoul). **Primary technical source:** [arXiv:2502.11371v3](https://arxiv.org/abs/2502.11371v3), submitted 2025-02-17 and revised 2026-03-04. ACM metadata identifies KDD ’26 V.2, pp. 8966–8977, DOI `10.1145/3770855.3817575`; the ACM text was not directly compared. Code observations use `haoyuhan1/RAGvsGraphRAG@d2a0c0c0deb0903d60338d3c416ccd6f9544267c` (2026-02-27 UTC), which predates v3.

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Notes |
| --- | --- | --- | --- | --- |
| The study compares vector RAG, KG, community, graph-guided text and hierarchical-summary systems. | [v3 §3.2](https://arxiv.org/pdf/2502.11371v3#page=3) | paper-reported | high | These do not share a single evidence representation. |
| Defaults include ~256-token chunks, `text-embedding-ada-002`, $k=10$, reranker, IRCoT and Llama-3.1 8B/70B generators. | [v3 §3.4](https://arxiv.org/pdf/2502.11371v3#page=3) | paper-reported | high | Same generator does not equalize retrieval context. |
| Selection routes fact/reasoning labels; Integration retrieves both and concatenates evidence. | [v3 §4.5](https://arxiv.org/pdf/2502.11371v3#page=15), Appendix G/H | paper-reported | high | Router is not an answerability/Null classifier. |
| Token matching changes aggregate comparison but leaves a Temporal gap. | [Tables 31–33](https://arxiv.org/pdf/2502.11371v3#page=20) | paper-reported | high | Matching tokens is not matching information/build/search work. |
| Pairwise summary judging reverses candidate presentation order. | [§5.3/Figure 4](https://arxiv.org/pdf/2502.11371v3#page=8) | paper-reported | high | Preference is not factuality or reference similarity. |
| Repository retrieval scripts feed common post-retrieval QA/summarization entry points. | `haoyuhan1/RAGvsGraphRAG@d2a0c0c0deb0903d60338d3c416ccd6f9544267c:README.md:L1-L96` | source-reference | medium | Snapshot cannot prove final-table reproducibility. |
| “Graph effect” is bundled with representation, context, construction and generator differences. | v3 design above | direct inference from setup | high | This is the review’s central fairness boundary. |
| New top-$k$ walkthrough: 3,631 RAG versus 9,770 Local retrieved tokens, then the token-matched outcome/Temporal contrast. | [Table 31](https://arxiv.org/pdf/2502.11371v3#page=19), [Tables 2, 32–33](https://arxiv.org/pdf/2502.11371v3#page=20) | paper-reported synthesis | high | Added to make the fairness control interpretable rather than merely cautionary. |

## Method map

| Component | Role | Input → output | Boundary | Source |
| --- | --- | --- | --- | --- |
| Retrieval family | Creates method-specific evidence | corpus/query → chunks, triples, community context, graph-guided text, summaries | unit/length/content differ | [§3](https://arxiv.org/pdf/2502.11371v3#page=3) |
| Common QA/summarization | Applies a generator after retrieval | stored evidence → answer/summary | common generator cannot make evidence equivalent | [§3.4](https://arxiv.org/pdf/2502.11371v3#page=3) |
| Selection | Chooses RAG or Local by query label | query → one path | no insufficiency label | [Appendix G](https://arxiv.org/pdf/2502.11371v3#page=18) |
| Integration | Combines two retrieval paths | RAG context + Local context → generator | executes both paths; can lengthen context | [§4.5](https://arxiv.org/pdf/2502.11371v3#page=15) |

## Exact result table

All values are the author-public v3, not asserted as ACM-VoR-identical.

| Claim | Metric/setup | Exact value | Comparator | Source/caveat |
| --- | --- | ---: | --- | --- |
| RAG leads NQ for 8B | F1 | 64.78 | Community Local 63.01 | [Table 1](https://arxiv.org/pdf/2502.11371v3#page=4) |
| HippoRAG2 leads HotpotQA for 8B | F1 | 63.01 | RAG 60.04 | Table 1 |
| HippoRAG2 leads MultiHop overall for 8B | accuracy | 70.27 | Local 69.01; RAG 67.02 | [Table 2](https://arxiv.org/pdf/2502.11371v3#page=4) |
| 8B Integration is below Local on MultiHop | overall / Null | 68.19 / 50.17 | Local 69.01 / 80.07 | [Tables 20–22](https://arxiv.org/pdf/2502.11371v3#page=17) |
| 70B Integration raises overall but lowers Null | overall / Null | 77.62 / 59.47 | Local 71.17 / 88.70 | Tables 20–22 |
| Token-matched RAG nearly matches Local | 8B MultiHop overall | 69.33 | Local 69.01 | Tables 31–33; Temporal remains lower (36.71 vs 50.60) |
| Retrieved-token imbalance | MultiHop | 3,631 vs 9,770 | RAG vs Local | [Table 31](https://arxiv.org/pdf/2502.11371v3#page=19) |

## Critique log

| Critique | Label | Action | Reason | Final prose location |
| --- | --- | --- | --- | --- |
| “GraphRAG” could be treated as one method. | paper-evidenced | retained and explained | methods differ in final evidence form | §§1–2 |
| Same top-$k$ implies a fair budget. | direct inference from setup | retained and qualified | counts use non-equivalent units | §7.1 |
| Integration is universally best. | paper-evidenced | rejected | 8B MultiHop is below Local and Null falls | §5.3 |
| LLM preference proves factuality. | paper-evidenced | rejected | preference/reference metric/factuality differ; order changes | §6.2 |
| Pinned code proves final experimental reproduction. | source-reference | softened | snapshot predates v3 and lacks final artifacts/config locks | §8.3 |

## Uncertainties

- ACM metadata is verified, but the ACM article text was not accessible for direct v3-to-VoR comparison.
- The v3 and DOI author orders differ; bibliographic entries keep the versions separate.
- Figure reuse is attributed to v3’s CC BY 4.0 record; no claim is made about an ACM figure licence.
