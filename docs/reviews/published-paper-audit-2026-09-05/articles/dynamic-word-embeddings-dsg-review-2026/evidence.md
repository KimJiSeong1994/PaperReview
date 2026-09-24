# Evidence ledger

| claim | source anchor | evidence type | confidence |
| --- | --- | --- | --- |
| DSG places word and context embeddings on latent trajectories connected by diffusion. | §§2–3 | paper-reported | high |
| The paper gives filtering and smoothing variational inference algorithms. | §§4–5 | paper-reported | high |
| Results cover Google Books, State of the Union, and Twitter. | §6; Figures 2–3 | paper-reported | high |

## Method map

| step | role | source anchor |
| --- | --- | --- |
| Dynamic skip-gram | probabilistic word/context embeddings per time | §2 |
| Temporal prior | Ornstein–Uhlenbeck/diffusion linkage across time | §3 |
| Inference | online filtering or full-sequence smoothing | §§4–5 |

## Critique log

| critique | label | action | reason |
| --- | --- | --- | --- |
| Smoothing uses future observations and cannot be read as an online detector. | direct inference from method | accepted | Clarifies the scope of DSG-S. |
| A single global diffusion scale limits heterogeneous rates of change. | paper-evidenced | accepted | Discussed as a model limitation. |
