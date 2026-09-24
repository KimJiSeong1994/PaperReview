# Evidence ledger

| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| TWEC fixes a compass trained on the full corpus and learns slice-specific context embeddings. | §§3–4; Eq. 1 | paper-reported | high |
| It evaluates temporal analogies and predictive likelihood on NAC-S/NAC-L. | §5; Tables 2–4 | paper-reported | high |
| Its small-corpus temporal-analogy result exceeds reported DW2V values. | Table 2 | paper-reported | high |

## Method map
| step | role | source anchor |
| --- | --- | --- |
| Compass training | learn global CBOW target matrix | §3 |
| Slice training | hold compass fixed, optimize local contexts | §3 |
| Comparison | analogy and likelihood assessments | §5 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| NAC-S MRR / MP@10 | .481 / .636 | Table 2 | Temporal-analogy configuration. |
| NAC-L aggregate result | .484 | Table 3 | Advantage depends on aggregation/task mix. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Shared coordinates alone do not establish semantic-change accuracy. | direct inference from evaluation design | accepted | Distinguishes alignment utility from semantic ground truth. |
