# Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| The study compares contextual embeddings under equal GCD conditions across eight LSC benchmarks. | Paper §§1–3; Table 1 | paper-reported | high | Official ACL PDF and local 21-page proceedings PDF agree. |
| APD is the strongest reported GCD approach and XL-LEXEME leads the compared encoders in the reported WiC/WSI/GCD analysis. | Paper abstract; Tables 1–2 | paper-reported | high | Retained as a result for this benchmark/configuration, not a universal ranking. |
| The article separates WiC, WSI, and GCD because their evaluation paths differ. | Paper §5 | paper-reported | high | This distinction is preserved in the revised explanation. |

## Method map

| step | role | input/output | source anchor |
| --- | --- | --- | --- |
| Usage representation | encode contextual word occurrences | token embeddings | §§3–4 |
| Form-based score | compare period-specific usages | APD/PRT change scores | §4 |
| Computational annotation | evaluate usage relatedness, induced clusters, and change | WiC/WSI/GCD measures | §5 |

## Result checks

| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| XL-LEXEME + APD weighted average GCD | .751 | Table 1 | 11 benchmark-period columns; configuration-specific. |
| XL-LEXEME computational-annotator results | WiC .568; WSI ARI .339 / PUR .810; GCD .754 | Table 2 | Separate evaluation pipeline from standard GCD. |

## Critique log

| critique | label | action | reason |
| --- | --- | --- | --- |
| A score-only interpretation obscures different WiC/WSI/GCD stages. | paper-evidenced | accepted | The paper explicitly evaluates the stages separately. |
| A blog-authored evaluation checklist. | unsupported extra material | removed | It is not an explanation of the paper itself. |
