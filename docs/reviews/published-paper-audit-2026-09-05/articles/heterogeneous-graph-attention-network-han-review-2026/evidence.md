# Evidence — Heterogeneous Graph Attention Network

## Primary source read
- arXiv:1903.07293v2 (2021-01-20), official HTML: https://arxiv.org/html/1903.07293
- Title, authors, venue information, and version are in lines 39–45.

## Method anchors
- §4 / Eq. 1–5: type-specific projection then meta-path-local masked node attention; multi-head outputs form each semantic-specific embedding.
- §4.2 / Eq. 7–9: semantic attention averages transformed embeddings over nodes to give one scalar weight per meta-path before softmax fusion.

## Result checks
- Table 3: on ACM at 20% labels, HAN Macro-F1 is 89.40 versus GCN 86.81; on DBLP at 80%, HAN Macro-F1 is 93.08.
- Table 3: on IMDB at 80%, HAN Macro-F1 is 54.38 and Micro-F1 58.51.

## Limits retained in article
- The evaluated meta-path sets are chosen as input for each dataset (§5.1); semantic attention weights the supplied paths, not an unconstrained path search.
- Eq. 7 averages importance across all nodes, so the semantic-level coefficient is a graph-level value rather than a node-specific coefficient.

## Figure preservation
- All HAN figure URLs, order, and original source captions remain unchanged in revised.md.
