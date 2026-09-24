# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| TimesFM tokenizes a univariate series into non-overlapping patches and forecasts output patches with a decoder-only Transformer. | §§3–4 | paper-reported | high |
| The 200M model uses input length 32 and output patch length 128. | §4; Table 6 | paper-reported | high |
| Evaluation covers Monash, Darts, and ETT benchmarks. | §5; Tables 2–4 | paper-reported | high |
## Method map
| component | role | source anchor |
| --- | --- | --- |
| Patch encoder | turn numeric context into tokens | §3 |
| Causal decoder | predict next output patch | §3 |
| Autoregression | extend beyond one output patch | §3 |
## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Monash geometric-mean score | .6846 | Table 4 | Rank changes with aggregation. |
| Darts result | third in both reported aggregates | Table 3 | Dataset aggregate, not per-series guarantee. |
## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Zero-shot claim is limited to univariate point forecasting in the paper’s evaluation. | paper-evidenced | accepted | Prevents extension to later product versions/features. |

## Independent full-text verification and corrected anchors

https://raw.githubusercontent.com/mlresearch/v235/main/assets/das24c/das24c.pdf

Full text verified: data total381.36B Table1;200M patches32/128 Table6;Monash.6846 Table4;Darts.6829/.5767 Table3.
