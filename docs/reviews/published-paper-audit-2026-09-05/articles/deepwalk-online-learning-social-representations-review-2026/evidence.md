# Evidence — DeepWalk: Online Learning of Social Representations

## Primary source read
- arXiv:1403.6652v2 (2014-06-27), official HTML: https://arxiv.org/html/1403.6652
- Identity and version are confirmed by the arXiv abstract record; the KDD DOI is 10.1145/2623330.2623732.

## Method anchors
- §3.1–3.3: a truncated random walk selects a neighbor at each step; the walks form the training stream for a language-model objective.
- §3.2 explicitly motivates the walk-as-sentence analogy from the power-law frequency pattern; Algorithm 1/2 specifies the walk generation and SkipGram learning.

## Result checks
- Table 2, BlogCatalog: micro-F1 is 36.00 at 10% labels for DeepWalk versus 31.06 for SpectralClustering; at 70% labels the latter is 41.66 versus 41.50.
- Table 3, Flickr: at 3% labels DeepWalk has micro-F1 35.9 versus 31.63 for SpectralClustering. Table 4, YouTube: at 1% labels it has 37.95 versus 23.90 for EdgeCluster.

## Limits retained in article
- The classification evaluation varies the labeled-node fraction and is not a temporal link-prediction study.
- The paper presents incremental updates as an online-learning property; the reported tables establish classification results on the three named social networks.

## Figure preservation
- original.md and revised.md retain deepwalk-fig1-karate.png, deepwalk-fig2-powerlaw.png, and deepwalk-fig3-overview.png in the original order and captions.
