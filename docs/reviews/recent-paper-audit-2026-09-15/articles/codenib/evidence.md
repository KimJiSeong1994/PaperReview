# CodeNib — evidence ledger and revision audit

**Review date:** 2026-09-15 (Asia/Seoul). **Primary scope:** [arXiv:2607.25431v1](https://arxiv.org/abs/2607.25431v1), submitted 2026-07-28. It is a v1 preprint. Current official repository state must not be substituted for the paper experiment; the original article’s fixed `61a9ab2` source snapshot is retained as a bounded supplementary reference.

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Notes |
| --- | --- | --- | --- | --- |
| CodeNib builds lexical, dense and structural views per commit and maps output to source ranges. | [§§1, 3–5](https://arxiv.org/html/2607.25431v1#S1) | paper-reported | high | A manifest records status/capabilities; it is not a transaction manager. |
| Q1–Q5 separately measure retrieval, indexing, navigation, maintenance and context delivery. | [§9](https://arxiv.org/html/2607.25431v1#S9) | paper-reported | high | They do not form one aggregate agent-success metric. |
| Static navigation matches normalized live locations on 632/1,000 requests; median live/static ratio is 4.72× on that subset. | [§9.4](https://arxiv.org/html/2607.25431v1#S9.SS4) | paper-reported | high | Location equality is deliberately weaker than full provider interchangeability. |
| Graph/vector updates match rebuilds on 15/33 and 28/31 transitions; matching medians are 8.67× and 25.44×. | [§9.5](https://arxiv.org/html/2607.25431v1#S9.SS5) | paper-reported | high | Verification is performed after timing, offline. |
| Selected policies preserve a defined localization margin with 50–87% fewer trajectory tokens. | [§9.7](https://arxiv.org/html/2607.25431v1#S9.SS7), Appendix H | paper-reported | high | Selection minimizes token use among policy arms passing its margin; it is not a patch-success result. |
| Current CodeNib repository exists and is mutable. | [official repository](https://github.com/sysevol-ai/CodeNib) | official artifact | medium | Do not infer paper-version equivalence from current HEAD. |
| View skew can matter for combined calls. | §§3.4, 6.4, 7.1 | direct inference from setup | high | Views update independently and staleness is signalled, not atomically committed. |
| New request walkthrough separates manifest lookup, ranked evidence, symbol locations, and Eager/Compact history delivery. | [§§4.1–4.2, 5.4, 7.1–7.4](https://arxiv.org/html/2607.25431v1#S4) | paper-reported synthesis | high | Added to explain why Q5 changes delivery/history as well as retrieval. |

## Method map

| Component | Role | Input → output | Assumption/boundary | Source |
| --- | --- | --- | --- | --- |
| View compiler | Materializes lexical/dense/structural state | commit checkout → manifest-linked views | commit/source-address link is maintained | [§§5–6](https://arxiv.org/html/2607.25431v1#S5) |
| Query planner | Serves ranked candidates | request → source-linked blocks | Q1 invokes plans directly; routing quality is not tested | [§7.2](https://arxiv.org/html/2607.25431v1#S7.SS2) |
| Static/live navigation | Serves locations | symbol request → normalized locations | equality drops metadata/end positions | [§§4.2, 9.4](https://arxiv.org/html/2607.25431v1#S4.SS2) |
| Delta maintenance | Repairs/reuses selected views | commit transition → updated graph/vector | matching check happens after timer | [§6.4](https://arxiv.org/html/2607.25431v1#S6.SS4) |
| Context policy | Moves evidence into bounded history | retrieval/history → trajectory | token total excludes many cost/latency dimensions | [§7.4](https://arxiv.org/html/2607.25431v1#S7.SS4) |

## Exact result table

| Result claim | Metric/setup | Exact value | Comparator | Caveat/source |
| --- | --- | ---: | --- | --- |
| Dense retrieval range | file/symbol Recall@10 across 5 embedders | 0.705–0.820 / 0.422–0.638 | reranker file up to 0.858 | [§9.2](https://arxiv.org/html/2607.25431v1#S9.SS2); reranking costs seconds/query |
| HNSW local speed | FAISS search mean | 0.0268 ms | Flat 0.910 ms | §9.3; whole dense-query median is 45.1 ms |
| Navigation compatibility | normalized location matches | 632 / 1,000 | — | §9.4; 4.72× only matching subset |
| Graph maintenance | matching transitions / speedup median | 15 / 33; 8.67× | rebuild | §9.5 |
| Vector maintenance | matching transitions / speedup median | 28 / 31; 25.44× | rebuild | §9.5 |
| Context delivery | selected-policy grep/read tokens | 12.9–49.9% | paired grep/read | §9.7; ΔAnswerRecall@5 −0.009 to +0.067 |

## Critique log

| Critique | Label | Action | Reason | Final prose location |
| --- | --- | --- | --- | --- |
| Headline speedups could be read as all transitions. | paper-evidenced | retained and qualified | only rebuild-matching subset receives the ratio | Executive Summary, §§8, 10 |
| Static navigation replaces live LSP. | paper-evidenced | rejected | only 63.2% normalized match; semantic gaps remain | §§3, 7, 10 |
| Token reduction proves lower total cost. | direct inference from setup | softened | reported token accounting excludes cache/prefill/latency/price | §9, §10 |
| Current official code proves v1 result reproduction. | source-reference | rejected | repository HEAD has progressed; paper artifacts/version controls still bound claim | §10.3 |
| System improves issue-resolution/patch quality. | paper-evidenced | omitted | outside evaluation scope | §10.1, conclusion |

## Uncertainties

- No newer arXiv version was available on 2026-09-15; all conclusions are v1-specific.
- The paper does not report an end-to-end combined state where matching maintenance, navigation compatibility and selected context policy all hold simultaneously.
- The original uses direct-extracted paper figures. The arXiv page displays a non-exclusive distribution licence; this audit does not establish reuse permission from that fact alone.
