# Evidence — GNNExplainer: Generating Explanations for Graph Neural Networks

## Primary source read
- arXiv:1903.03894v4, official HTML: https://arxiv.org/html/1903.03894

## Method anchors
- §3.2 / Eq.1–2 defines a prediction explanation as a compact computation subgraph and feature subset maximizing mutual information with the fixed GNN prediction.
- §4.1 / Eq.3–5 relaxes discrete subgraph search to a sigmoid adjacency mask optimized by gradient descent; §4.2 jointly learns a feature mask.

## Result checks
- The paper evaluates synthetic motif recovery and qualitative explanations, separating structural and feature masks.

## Limits retained in article
- The objective preserves a trained model prediction; it is not a causal account of the data-generating process.
- The continuous, non-convex mask optimization has no global optimum guarantee; the paper describes empirically good local minima.

## Figure preservation
- All existing GNNExplainer figure URLs and captions remain unchanged.
