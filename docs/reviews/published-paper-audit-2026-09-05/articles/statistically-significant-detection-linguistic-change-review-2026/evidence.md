# Evidence ledger

| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| The method builds frequency, syntactic, and distributional time series and applies change-point significance testing. | §§3–4; Algorithm 1 | paper-reported | high |
| Distributional embeddings are trained by period and aligned before displacement scoring. | §3.3; Eqs. 7–8 | paper-reported | high |
| Evaluation spans Google Books, Amazon reviews, Twitter, and a synthetic corpus. | §§5–6 | paper-reported | high |

## Method map

| step | role | source anchor |
| --- | --- | --- |
| Property series | frequency/POS/distributional signal per word | §3 |
| Alignment and drift | align local embedding neighborhoods and score displacement | §3.3 |
| Significance | mean-shift statistic plus permuted time-order null | §4; Algorithm 1 |

## Result checks

| result | source anchor | caveat |
| --- | --- | --- |
| Distributional method balances false positives and negatives in reported qualitative comparisons. | §5 | This is not a direct test of semantic-change ground truth. |

## Critique log

| critique | label | action | reason |
| --- | --- | --- | --- |
| The p-value applies to the constructed series, not semantic change directly. | direct inference from setup | accepted | Necessary interpretation boundary. |
