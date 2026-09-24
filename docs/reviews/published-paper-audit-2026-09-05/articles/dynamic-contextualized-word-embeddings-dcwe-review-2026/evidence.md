# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| DCWE adds time/social offsets to BERT input embeddings before contextualization. | §§3–4; Eqs. 4–8 | paper-reported | high |
| Offsets are regularized with anchoring and temporal priors. | §4 | paper-reported | high |
| Evaluation reports MLM and sentiment-task results. | §5; Tables 1–3 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Type-level offset | encode word, time, social setting | Eqs. 4, 7–8 |
| BERT | contextualize the offset input | Eq. 6 |
| Priors | anchor and smooth offsets | §4 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Sentiment test F1 | .896 / .968 | Table 3 | Ciao/YELP task settings. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Dynamic vocabulary is limited to frequent words. | paper-evidenced | accepted | Bounds coverage of rare/new words. |
