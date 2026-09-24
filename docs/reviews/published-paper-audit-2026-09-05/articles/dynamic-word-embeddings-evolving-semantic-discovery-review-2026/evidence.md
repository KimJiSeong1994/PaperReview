# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| DW2V jointly factorizes time-sliced PPMI matrices with temporal smoothness. | §§2–3; Eqs. 5, 8 | paper-reported | high |
| The optimization uses an asymmetric relaxation and block coordinate updates. | §3 | paper-reported | high |
| NYT experiments assess alignment and sparse-data robustness. | §4; Tables 4–8 | paper-reported | high |

## Method map
| step | role | source anchor |
| --- | --- | --- |
| PPMI factorization | per-time distributional fit | Eq. 5 |
| Temporal penalty | link adjacent embeddings | Eq. 5 |
| BCD | solve factor blocks | Eq. 8 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Sparse-data MRR at 0.1% | .4427 | Table 8 | Authors’ constructed alignment evaluation. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| External sports-ranking correction to a paper example. | out-of-scope supplemental audit | removed from final prose | The article should explain the paper, not present a separate external fact check. |
