# Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| The paper presents an unsupervised contextualized-representation approach to LSC. | Abstract; §3 | paper-reported | high | Confirmed in ACL Anthology record/PDF and local PDF. |
| It clusters BERT usage representations into usage types and defines ED, JSD, and APD measures. | §3 | paper-reported | high | Method description and equations retained. |
| The evaluation uses COHA/GEMS and reports positive correlations with human judgments. | §4; Tables 1–2 | paper-reported | high | The revised article keeps exact reported values and confines their claim to that setting. |

## Method map

| step | input/output | source anchor |
| --- | --- | --- |
| Usage encoding | contextual vector per target occurrence | §3.1 |
| Usage-type induction | K-means clusters and period distributions | §3.2 |
| Change scoring | ED/JSD from distributions; APD from cross-period distances | §3.3–3.4 |

## Result checks

| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Correlation with human change scores | ED .278; JSD .276; APD .285 | Table 2 | English COHA/GEMS 99-word evaluation. |

## Critique log

| critique | label | action | reason |
| --- | --- | --- | --- |
| APD is the strongest of the three reported metrics although it bypasses the usage clusters. | paper-evidenced | accepted | Important for accurately distinguishing performance from interpretive value. |
| The article should claim that usage types equal dictionary senses. | contradicted by paper | rejected | The paper itself discusses mismatches. |
