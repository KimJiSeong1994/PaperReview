# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| PCM uses partial correlation over cross mappings to remove observed mediated influences. | §§2–3; Eqs. 1–5 | paper-reported | high |
| Evaluation includes logistic systems, networks, DREAM4, plankton, and air-pollution data. | §§4–5 | paper-reported | high |
## Method map
| component | role | source anchor |
| --- | --- | --- |
| MCM | reconstruct cross-mapped states | §2 |
| PCM | condition on mediated cross-map | Eq. 5 |
## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Chain MCM vs PCM score | .8681 / .1871 | Figure 3b–c | Illustrates a synthetic chain. |
## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Removal targets observed mediation, not arbitrary hidden paths. | direct inference from conditioning set | accepted | Limits direct-causality interpretation. |

## Independent full-text verification and corrected anchors

https://publications.pik-potsdam.de/pubman/item/item_24303_2/component/file_24313/24303oa.pdf

Full publication text verified: chain .8681/.1871 and loop .8052/.4467 Fig3b–c; DREAM4 AUC Fig4b.
