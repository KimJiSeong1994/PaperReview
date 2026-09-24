# Evidence — Hypergraph Neural Networks

## Primary source read
- arXiv:1809.09401, official HTML: https://arxiv.org/html/1809.09401

## Method anchors
- §3 / Eq.1–4 defines incidence matrix H, vertex/hyperedge degrees, and the normalized hypergraph Laplacian.
- Eq.10–11 define hyperedge convolution and stacked HGNN layers through Dv^-1/2 H W De^-1 H^T Dv^-1/2 XTheta.
- §3 implementation constructs visual-data hyperedges by each point and its K nearest neighbors.

## Result checks
- The paper evaluates citation-network classification and visual-object classification; it explicitly presents GCN as the two-vertex-hyperedge special case.

## Limits retained in article
- The reported high-order relation depends on the supplied hypergraph construction; in the visual task this is kNN construction.
- Eq.9 says W is initialized to identity, and the core layer learns Theta; claims about learned hyperedge weighting need this distinction.

## Figure preservation
- Existing HGNN figure URLs, sequence, and captions are retained.
