# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| PAPG constructs personas by seed mining, global distribution alignment, and group-specific adaptation. | §§3–4; Eqs. 1–12 | paper-reported | high |
| Global alignment combines importance sampling and entropic optimal transport. | §3 | paper-reported | high |
| Tables 1–4 report the comparative evaluation. | §4; Tables 1–4 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Seed personas | mine and filter narrative personas | §3.1 |
| Global alignment | resample toward human response distribution | §§3.2–3.3 |
| Group adaptation | retrieve and rewrite personas for a target group | §3.4 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| In-domain Resample mean error | .1715 | Table 1 | Uses the paper’s IPIP-aligned evaluation. |
| OOD Resample mean error | .2085 | Table 2 | Table value retained where prose differs. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Several prose and table values differ. | source-reference evidence | accepted | Article cites table values and flags the internal discrepancy as a reporting limitation. |
