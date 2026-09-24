# Evidence ledger

| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| The study trains diachronic embeddings and aligns low-dimensional spaces with orthogonal Procrustes. | §§3–4 | paper-reported | high |
| It reports conformity and innovation laws across four languages and six corpora. | §§5–6; Tables 2–3 | paper-reported | high |
| SGNS is preferred for qualitative discovery in the reported evaluation. | §5; Table 1 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Time-sliced embeddings | local distributional representations | §3 |
| Orthogonal alignment | comparable temporal spaces | §4 |
| Regression analysis | relate drift to frequency/polysemy proxies | §6 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Frequency-law coefficients | −1.24 to −.30 | Table 2 | Association, not causal effect. |
| Polysemy-law coefficients | .08 to .53 | Table 3 | Conditional on the paper’s polysemy proxy. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| The reported laws are observational relationships. | paper-evidenced | accepted | The paper does not identify causal mechanisms. |
