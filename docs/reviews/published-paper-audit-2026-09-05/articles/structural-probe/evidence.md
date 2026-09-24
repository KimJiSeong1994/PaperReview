# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| A learned linear map tests whether squared distances encode dependency-tree distances. | §§2–3; Eq. 1 | paper-reported | high |
| A second probe tests depth through squared norm. | §3; Eq. 2 | paper-reported | high |
| Results are reported for ELMo and BERT representations. | §5; Tables 1–3 | paper-reported | high |
## Method map
| component | role | source anchor |
| --- | --- | --- |
| Distance probe | recover unlabeled undirected tree distances | Eq. 1 |
| Depth probe | recover distance from root | Eq. 2 |
## Result checks
| result | source anchor | caveat |
| --- | --- | --- |
| Probe recovers syntactic geometry in reported contextual encoders. | Tables 1–3 | Readability does not prove model use of that information. |
## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Probe success establishes decodability, not causal use. | direct inference from setup | accepted | Preserved as the central interpretive boundary. |
