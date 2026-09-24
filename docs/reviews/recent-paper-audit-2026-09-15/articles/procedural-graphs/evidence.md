# Evidence audit — Procedural Graphs

**Review date:** 2026-09-15 (Asia/Seoul)  
**Article mode:** deep academic paper review; revision/polish.  
**Primary version:** Lu, Chen, Wu, & Arık, *Procedural Graphs: Self-Evolving Execution Structures for LLM Agents*, arXiv:2609.09153v1, submitted 2026-09-08. [arXiv record](https://arxiv.org/abs/2609.09153v1) · [versioned PDF](https://arxiv.org/pdf/2609.09153v1).  
**Retrieval sufficiency:** sufficient for method reconstruction, tables, and bounded criticism. No author repository, code artifact, or reproduced experiment was available in the source bundle; do not convert that finding into “no code exists.”

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Review boundary |
| --- | --- | --- | --- | --- |
| The v1 preprint lists Yuxing Lu, Yicheng Chen, Shanchan Wu, and Sercan Ö. Arık; it was submitted 2026-09-08. | [arXiv record](https://arxiv.org/abs/2609.09153v1) | paper metadata | high | Preprint status, not venue publication. |
| A PG is `G=(V,R,E,Phi)` whose edges join procedures and carry `condition`, `guidance`, and `pitfalls`. | [§3.1](https://arxiv.org/pdf/2609.09153v1#page=3) | paper-reported | high | These fields are natural-language attributes, not enforced constraints. |
| The inference path exact-matches the latest procedure, uses outgoing 2-hop context on success or full graph on failure, and passes a 3-step recent window to the guidance LLM. | [§3.2](https://arxiv.org/pdf/2609.09153v1#page=4) | paper-reported | high | The 3-step window limits guidance input; it does not prove the solver itself only sees three steps. |
| Graph revision is between episodes/batches: train traces → candidate edits → structural checks → held-out validation → retained or rejected checkpoint. | [§3.3, Algorithm 1](https://arxiv.org/pdf/2609.09153v1#page=5), [Appendix B.6](https://arxiv.org/pdf/2609.09153v1#page=23) | paper-reported | high | “Online evolution” means incremental between training batches, not mutation inside a test episode. |
| The gate accepts a candidate when its measured validation score is at least the cached checkpoint score. | [Eq. 5, Algorithm 1](https://arxiv.org/pdf/2609.09153v1#page=5) | paper-reported | high | It establishes nondecrease of the cached validation observation, not monotone generalization. |
| A generic graph validator checks graph shape/path-to-terminal properties, not tool-schema validity, policy compliance, or solver obedience. | [Appendix B.6](https://arxiv.org/pdf/2609.09153v1#page=23) | paper-evidenced plus direct inference | high | Keep “soft guidance” distinct from constrained execution. |
| Table 1 gives 19 wins, 2 ties, 3 losses against the strongest baseline across 24 cells; the paper reports a one-sided exact sign-test p=4.3e-4. | [§5.1, Table 1](https://arxiv.org/pdf/2609.09153v1#page=7) | paper-reported | high | Not a claim that all individual cells are significant; cells share benchmarks/models. |
| Construction modes jointly vary initialization, batch schedule, feedback cadence, validation, and rejection memory. | [Table 2, Appendix D.2](https://arxiv.org/pdf/2609.09153v1#page=9) | direct inference from setup | high | Treat results as configuration comparisons, not one-factor ablations. |
| Table 3 compares no graph, full raw, full generative, and local generative. | [§5.5, Table 3](https://arxiv.org/pdf/2609.09153v1#page=10) | paper-reported | high | No local-raw cell; graph localization and generative transformation are not fully factorially separated. |
| The EnterpriseArena returned graph has 85% test survival, while the observed Round 7 intermediate test score is 95%; the paper deliberately reports the returned graph. | [§5.4, Table 11](https://arxiv.org/pdf/2609.09153v1#page=9) | paper-reported | high | Each split has 20 episodes; accept/reject decisions can hinge on one or two episodes. |
| Guidance can decrease solver steps while increasing total tokens. | [§5.5, Table 3](https://arxiv.org/pdf/2609.09153v1#page=10), [Tables 9–10](https://arxiv.org/pdf/2609.09153v1#page=29) | paper-reported | high | Tokens and steps are distinct resources; EnterpriseArena’s Tools/Mo is another distinct measure. |
| Figure 5 round labels require caution: prose/Table 11, rather than the crop’s internal labels, ground the article’s narrative. | [Appendix E.3](https://arxiv.org/pdf/2609.09153v1#page=34), [Table 11](https://arxiv.org/pdf/2609.09153v1#page=32) | paper-evidenced source discrepancy | high | The article preserves the sourced figure and names the conflict. |

## Method map

| Component / step | Role | Input → output | Assumption | Source anchor |
| --- | --- | --- | --- | --- |
| PG representation | Store connected procedure knowledge | procedure nodes/edges → textual transition properties | Natural-language guidance adequately represents the needed transition | [§3.1](https://arxiv.org/pdf/2609.09153v1#page=3) |
| Localization | Find current graph context | latest action → exact node match → 2-hop outgoing subgraph | Action and node names align; fallback full graph is usable | [§3.2](https://arxiv.org/pdf/2609.09153v1#page=4) |
| Guidance | Translate graph into current advice | subgraph + query + recent trace → text guidance | Solver can follow the generated guidance | [§3.2](https://arxiv.org/pdf/2609.09153v1#page=5) |
| Candidate construction | Propose edits after a train batch | high/low scored traces + rejections → add/delete edits | Refiner identifies useful topology/attribute changes | [§3.3](https://arxiv.org/pdf/2609.09153v1#page=5) |
| Structural validation | Reject malformed candidates | graph edits → valid graph/path-to-terminal | Graph well-formedness is sufficient to proceed to empirical evaluation | [Appendix B.6](https://arxiv.org/pdf/2609.09153v1#page=23) |
| Held-out gate | Retain checkpoints | candidate score vs. cached score → adopt/reject | Repeated validation selection tracks useful improvement | [Algorithm 1](https://arxiv.org/pdf/2609.09153v1#page=23) |

## Exact result table

| Result claim | Metric / dataset / setup | Exact value | Comparator | Source anchor | Caveat |
| --- | --- | ---: | --- | --- | --- |
| Main aggregate | 4 LLMs × 6 benchmarks | 19 wins / 2 ties / 3 losses | strongest baseline per cell | [§5.1](https://arxiv.org/pdf/2609.09153v1#page=7) | Aggregate direction, not cellwise significance. |
| Construction study | HotpotQA test F1 | Mode 5: 78.79 | unguided 71.21 | [Table 2](https://arxiv.org/pdf/2609.09153v1#page=9) | Separate construction-study setup. |
| Construction study | MultiChallenge Overall | Mode 3: 92.86 | unguided 87.50; Mode 5 91.07 | [Table 2](https://arxiv.org/pdf/2609.09153v1#page=9) | Expert evolution, not scratch, is the best cell. |
| Usage ablation | ALFWorld success | local generative 81.53 | no graph 72.58; full generative 54.48 | [Table 3](https://arxiv.org/pdf/2609.09153v1#page=10) | No local-raw control. |
| Usage cost | GDPval tokens/steps | local 367,738 / 18.57 | no graph 275,638 / 28.20 | [Table 3](https://arxiv.org/pdf/2609.09153v1#page=10) | Fewer steps with 33.4% more tokens. |
| EnterpriseArena main | Full survival: Claude / Gemini Pro / Flash / Grok | PG 58 / 34 / 0 / 40% | baseline 44 / 6 / 0 / 26% | [Table 8](https://arxiv.org/pdf/2609.09153v1#page=26) | Flash life span rises but full survival remains 0%. |
| EnterpriseArena evolution | Returned graph test full survival | 85% | baseline 0%; Round 7 observed 95% | [§5.4, Table 11](https://arxiv.org/pdf/2609.09153v1#page=9) | 20 episodes/split; no test-based checkpoint selection. |

## Critique log

| Critique | Label | Action | Reason | Final-prose location |
| --- | --- | --- | --- | --- |
| PG is an execution constraint that prevents off-graph actions. | direct inference from setup | corrected | The final solver remains generative and receives text guidance. | §§2.2, 4.2 |
| Validation acceptance proves generalization improves every round. | direct inference from setup | softened | Gate uses repeatedly consulted held-out score and accepts ties. | §§4.3, 9.1 |
| Scratch or expert initialization is universally best. | paper-evidenced | corrected | Table 2 has the best result in different modes by dataset. | §6.2 |
| Fewer solver steps mean cheaper operation. | paper-evidenced | corrected | Tables 3/9/10 show increased tokens in several comparisons. | §7 |
| Report the best intermediate EnterpriseArena test round. | paper-evidenced | rejected | The paper returns the retained Round 9 graph and warns this would select on test. | §8.2 |
| No official implementation exists. | speculative | rejected | Official sources examined did not expose one; that cannot establish nonexistence. | §9.2 |

## Source-reference status

No cross-repository implementation is cited. The local primary PDF and current arXiv record establish the review’s claims. At the 2026-09-15 audit, the arXiv record/PDF did not expose an author code or artifact link in the reviewed source set; the article therefore says an official implementation was **not verified/found in this review**, not that no code exists.

## Checklist outcome

`revised.md` retains all original attributed figure URLs and citations, uses the v1 source for numerical claims, clearly labels direct inference, contains a References section, and introduces no speculative critique.
