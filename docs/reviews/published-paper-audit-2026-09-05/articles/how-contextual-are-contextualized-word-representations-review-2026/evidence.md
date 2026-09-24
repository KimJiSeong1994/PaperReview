# Evidence ledger

| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| The paper measures contextuality with self-similarity, intra-sentence similarity, and maximum explainable variance. | §§3–4; Eqs. 1–4 | paper-reported | high |
| It studies ELMo, BERT, and GPT-2 layer by layer while accounting for anisotropy. | §§4–5; Figures 1–4 | paper-reported | high |
| No layer has a single static embedding explaining over 5% of contextual variance in the reported experiment. | §5; Figure 4 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Self-similarity | contextual variation of the same word | Eq. 1 |
| Intra-sentence similarity | relation to sentence context | Eq. 2 |
| MEV | static-vector explanatory upper bound | Eq. 3 |

## Result checks
| result | source anchor | caveat |
| --- | --- | --- |
| Higher layers generally have lower anisotropy-adjusted self-similarity. | Figure 2 | Reported on the selected models/data. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| MEV is an upper-bound diagnostic, not proof that static embeddings are useless. | direct inference from definition | accepted | Prevents overclaiming. |
