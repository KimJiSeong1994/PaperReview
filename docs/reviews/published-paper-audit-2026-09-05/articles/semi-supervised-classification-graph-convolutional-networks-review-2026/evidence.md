# Evidence — Semi-Supervised Classification with Graph Convolutional Networks

## Primary source read
- arXiv:1609.02907, official HTML: https://arxiv.org/html/1609.02907

## Method anchors
- §2.1–2.2: spectral convolution is approximated with a first-order Chebyshev filter. Eq. 7 uses one shared parameter after tying coefficients.
- Eq. 8 applies the renormalized operator D-tilde^{-1/2} A-tilde D-tilde^{-1/2} to XTheta, where A-tilde=A+I.

## Result checks
- The paper evaluates semi-supervised node classification on Cora, Citeseer, and Pubmed; reported evaluation is a fixed transductive graph setting.

## Limits retained in article
- The model assumes the graph adjacency and all node features are available during training; it does not itself establish inductive generalization to separate graphs.
- The first-order approximation trades spectral-filter flexibility for a localized, efficient layer.

## Figure preservation
- Existing GCN figures and captions remain in the same order.
