# Evidence — Flow Reasoning Models: Turning Flows Into Efficient Recurrent Reasoners

## Primary source read
- arXiv:2606.29150v3 PDF, 14 pages: `sources/2606.29150v3.pdf` and extracted `sources/2606.29150v3.txt`; official page https://arxiv.org/abs/2606.29150v3.

## Method anchors
- Eq.3 defines the flow objective; Eq.4 makes clean predictions recurrent carries. Fixed-Point Forcing replaces the one-pass carry with a detached rollout-derived carry while retaining the canonical flow path and supervision (Fig.3–4, §3.2).
- §3 states the stable-attractor explanation as an analysis of the induced recurrence, not a general convergence theorem.

## Result checks
- Table 1 reports peak exact solve rates: Sudoku-Extreme 99.5%, Zebra 100.0%, Maze-Unique 99.9%.
- Table 2 reports three-seed FPF means: 99.2±0.3, 99.9±0.2, 98.0±1.8. The 44× claim matches EqR’s 98.7% at a matched point on the Sudoku-Extreme FLOP frontier (Fig.1/5), not a universal speedup.

## Limits retained in article
- The experiments are Sudoku-Extreme, Zebra, and Maze-Unique; all are structured exact-solve tasks.
- Operating points are selected with validation controls; the paper reports NFE/FLOP frontiers rather than end-to-end production latency.

## Figure preservation
- Existing FRM figure URLs, order, and captions are retained.
