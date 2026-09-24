# Evidence ledger
| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| Causal tracing corrupts subject embeddings and restores selected hidden states to measure indirect effects. | §§2–3; Eqs. 1–2 | paper-reported | high |
| ROME applies a rank-one update to a selected MLP projection. | §3.1; Eq. 2 | paper-reported | high |
| CounterFact evaluates efficacy, generalization, and specificity. | §5; Table 1 | paper-reported | high |

## Method map
| component | role | source anchor |
| --- | --- | --- |
| Corruption/restoration | locate mediating internal states | §3 |
| Key/value view of MLP | formulate local association edit | §4 |
| Rank-one update | impose desired key-to-value mapping | Eq. 6 |

## Result checks
| result | exact value | source anchor | caveat |
| --- | --- | --- | --- |
| GPT-2 XL CounterFact score | 89.2 | Table 4 | Composite for the paper’s counterfactual editing setup. |
| GPT-J CounterFact score | 91.5 | Table 4 | Same setting; not a mass-edit result. |

## Critique log
| critique | label | action | reason |
| --- | --- | --- | --- |
| A mediating site is not the unique storage site for a fact. | direct inference from intervention design | accepted | Prevents a stronger storage-locality claim than the evidence supports. |

## Independent full-text verification and corrected anchors

https://proceedings.neurips.cc/paper_files/paper/2022/file/6f1d43d5a82a37e89b0665b33bf3a182-Paper-Conference.pdf

Full text verified: AIE §2.2/Fig2; rank-one update §3.1 Eq2; GPT2XL89.2/GPTJ91.5 Table4.
