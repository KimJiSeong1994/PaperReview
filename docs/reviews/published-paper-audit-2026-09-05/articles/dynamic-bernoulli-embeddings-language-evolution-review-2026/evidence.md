# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| Dynamic embeddings put time-indexed word vectors under a Gaussian random-walk prior. | §§2–3; Eqs. 5–7 | paper-reported | high |
| Context vectors are shared and dynamic word vectors model time variation. | §3 | paper-reported | high |
| The paper evaluates Senate, ACM, and arXiv corpora using held-out pseudo-likelihood. | §4; Tables 1–2 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Bernoulli embedding likelihood | model word/context co-occurrence | §2 |
| Random-walk prior | share temporal statistical strength | Eq. 5 |
| Pseudo-MAP inference | optimize with negative sampling | Eqs. 6–7 |

## Result checks
| result | source anchor | caveat |
| --- | --- | --- |
| Dynamic model outperforms reported static/slice baselines in held-out pseudo-likelihood. | Tables 1–2 | Predictive fit is not a semantic-change ground truth. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Missing-period trajectories are prior-driven interpolation. | direct inference from model | accepted | Identifies a formal boundary of the method. |
