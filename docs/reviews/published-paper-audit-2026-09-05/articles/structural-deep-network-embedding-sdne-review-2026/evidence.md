# Evidence — Structural Deep Network Embedding

## Primary source read
- KDD 2016 paper PDF, 10 pages: `/Users/jiseong/Library/Mobile Documents/com~apple~CloudDocs/PaperWiki/PaperWiki/raw/30 Graph Representation Learning/papers/direct-607648d2d4c6-rfp0191-wangAemb.pdf`; extracted `/tmp/sdne.txt`; DOI https://doi.org/10.1145/2939672.2939753.

## Method anchors
- Definitions 2–3 distinguish direct-edge first-order proximity from similarity of adjacency neighborhoods (second-order).
- §4 uses an autoencoder reconstruction term with higher penalty on nonzero adjacency entries, then adds a supervised first-order proximity loss; the combined semi-supervised objective is the core model.

## Result checks
- §5 evaluates multi-label classification, reconstruction, link prediction, and visualization; Table 2 supplies dataset statistics and later tables give task-specific results.

## Limits retained in article
- The input is each vertex’s adjacency row, so the original architecture is tied to a fixed graph and cannot directly accept a new-node feature vector without reconstructing that input space.
- The link-prediction experiment uses the paper’s held-out-edge construction; it is not a chronological forecasting claim.

## Figure preservation
- SDNE figure URLs, order, and captions are unchanged.
