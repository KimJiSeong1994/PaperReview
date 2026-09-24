# Evidence — Inductive Representation Learning on Large Graphs

## Primary source read
- arXiv:1706.02216v4 (2018-09-10), official HTML: https://arxiv.org/html/1706.02216
- Title and authors: lines 46–55. This is the revised preprint; the paper notes corrected earlier PPI values.

## Method anchors
- Algorithm 1 (§3.1): initialize from node features, aggregate sampled neighbor representations, concatenate self and neighborhood, transform and L2-normalize.
- §3.1: fixed-size uniform neighbor sampling bounds a batch at O(product of sample sizes); the reported practical setting uses K=2 and S1×S2≤500.
- Eq. 1: the unsupervised objective contrasts random-walk co-occurring nodes against negative samples; §3.3 compares mean, LSTM, and pooling aggregators.

## Result checks
- Table 1: supervised GraphSAGE-LSTM reports micro-F1 0.832 (citation), 0.954 (Reddit), and 0.612 (PPI); GraphSAGE-GCN reports 0.772, 0.930, 0.500.
- The experiments explicitly predict unseen nodes; PPI is the entirely unseen-graph condition (§4).

## Limits retained in article
- The inductive claim depends on features or constructed structural features being available for unseen nodes.
- LSTM aggregation is applied to a random neighbor order and therefore is not permutation invariant (§3.3).

## Figure preservation
- original.md and revised.md retain all existing GraphSAGE figure URLs, order, and source captions.
