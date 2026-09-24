# Evidence — Can Classic GNNs Be Strong Baselines for Graph-level Tasks?

## Primary source read
- arXiv:2502.09263v3 (2025-11-01), official HTML: https://arxiv.org/html/2502.09263v3
- Identity check: title and authors are at HTML lines 52–56; ICML 2025 is stated in the abstract record.

## Method anchors
- §3 / Eq. 6–12: GNN+ augments message passing with edge features, BN, dropout, residual connection, FFN, and positional encoding. The composition is explicit in Eq. 11.
- §4 / Table 1: 14 datasets span GNN Benchmark, LRGB, and OGB; Table 2 labels results as five-seed mean±s.d.

## Result checks
- Abstract and §1 report: at least one enhanced GCN/GIN/GatedGCN is top-three on all 14 datasets and first on 8.
- Table 2: GatedGCN+ reaches 98.712±0.137 on MNIST and 77.218±0.381 on CIFAR10; GCN+ needs 7 s/epoch versus GraphGPS 21 s on ZINC (the timing comparison is task-specific).

## Limits retained in article
- The result evaluates enhanced models, not unmodified classic GNNs: FFN and positional encoding are part of the reported framework.
- The paper itself limits the result to the covered graph-level benchmarks (§7); it does not establish that GT global attention has no use on tasks outside them.

## Figure preservation
- original.md and revised.md retain gnnplus-fig1-tasks.png then gnnplus-fig2-architecture.png with the existing captions.
