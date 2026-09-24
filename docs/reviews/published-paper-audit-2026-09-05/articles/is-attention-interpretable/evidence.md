# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| The study erases attention-selected representations to measure prediction changes. | §§2–3 | paper-reported | high |
| It compares attention rankings with gradient and magnitude rankings. | §4 | paper-reported | high |
| Attention has predictive but unreliable interpretive value in the evaluated classifiers. | §§4–5 | paper-reported | high |
## Method map
| component | role | source anchor |
| --- | --- | --- |
| Attention erasure | intervention on weighted inputs | §3 |
| Ranking comparison | test attention as importance proxy | §4 |
## Result checks
| result | source anchor | caveat |
| --- | --- | --- |
| Gradient rankings predict erasure impact better than magnitude rankings. | §4; Tables 2–3 | Applies to the studied architectures/tasks. |
## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Attention is not a fail-safe explanation. | paper-evidenced | accepted | Matches the authors’ conclusion. |
