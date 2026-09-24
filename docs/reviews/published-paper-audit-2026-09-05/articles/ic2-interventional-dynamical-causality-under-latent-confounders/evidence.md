# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| IC2 constructs intervention surrogates from delay-embedding/cross-mapping neighborhoods. | §§2–3 | paper-reported | high |
| It separates observational and constructed-interventional components with dual orthogonal decomposition. | §§3–4 | paper-reported | high |
| The paper reports results on 32 structures and real-world systems. | §§5–6; Figures 2–7 | paper-reported | high |
## Method map
| step | role | source anchor |
| --- | --- | --- |
| Delay embedding | reconstruct dynamical state | §2 |
| Neighbor cross mapping | build intervention surrogate | §3 |
| Decomposition/VAE | derive CIC and iCIC | §4 |
## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| Synthetic 32-structure AUC | .91 | Figure 2 | Constructed intervention, not randomized intervention data. |
| Plankton AUROC | .938 | Figure 6 | Domain-specific reported result. |
## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| Constructed neighbors are a surrogate for intervention. | direct inference from method | accepted | Defines the claim’s formal boundary. |
