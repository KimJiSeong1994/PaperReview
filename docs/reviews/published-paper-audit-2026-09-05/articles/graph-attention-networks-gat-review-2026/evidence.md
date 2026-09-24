# Evidence — Graph Attention Networks

## Primary source read
- arXiv:1710.10903v3 (2018-02-04), official HTML: https://arxiv.org/html/1710.10903
- Title, author list, and final arXiv version are confirmed by the official record.

## Method anchors
- §2.1 / Eq. 1–4: a shared linear map W is followed by masked attention over first-order neighbors (including self); softmax normalizes coefficients within each neighborhood.
- Eq. 5 concatenates multi-head outputs in hidden layers; Eq. 6 averages heads at the prediction layer.

## Result checks
- Table 2: GAT reports 83.0±0.7 (Cora), 72.5±0.7 (Citeseer), and 79.0±0.3 (Pubmed); the GCN row is 81.5, 70.3, 79.0 respectively.
- Table 3: PPI micro-F1 is 0.973±0.002 for GAT and 0.934±0.006 for the matched constant-attention control.

## Limits retained in article
- The transductive table averages the GAT result over 100 runs but reuses older baseline values; PPI averages 10 runs (§3.4).
- The attention weights are learned feature-dependent aggregation coefficients; the paper’s experiments do not by themselves validate a causal or human-semantic interpretation.

## Figure preservation
- original.md and revised.md retain gat-fig1-attention.png then gat-fig2-tsne.png with their original captions.
