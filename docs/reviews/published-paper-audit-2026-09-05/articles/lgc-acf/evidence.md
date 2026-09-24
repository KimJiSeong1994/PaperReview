# Evidence — Light Graph Convolutional Collaborative Filtering With Multi-Aspect Information

## Primary source read
- IEEE Access DOI: https://doi.org/10.1109/ACCESS.2021.3061915

## Method anchors
- LGC-ACF constructs aspect-level user–attribute bipartite graphs from item knowledge, applies LightGCN propagation per aspect, and combines layer/aspect representations for inner-product recommendation.

## Result checks
- The paper reports Recall@20 and NDCG@20 on MovieLens, Amazon, and Taobao against interaction-only baselines.

## Limits retained in article
- The reported comparison gives LGC-ACF item-side aspect information that the listed interaction-only baselines do not use, so it does not isolate architecture from information advantage.
- The fusion presented as weighted aggregation is uniform in the described base form unless a learned weighting component is explicitly added.

## Figure preservation
- LGC-ACF figure URLs and captions are unchanged.
