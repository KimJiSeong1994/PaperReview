# Evidence — Heterogeneous Graph Neural Network

## Primary source read
- ACM DOI record: https://doi.org/10.1145/3292500.3330961; authors’ code repository identifies the KDD 2019 paper: https://github.com/chuxuzhang/KDD2019_HetGNN

## Method anchors
- HetGNN uses random-walk-with-restart sampling by neighbor type, type-specific content encoders, type-level neighborhood aggregation, and attention to combine content with typed neighborhoods.
- Training uses a graph-context objective with negative sampling.

## Result checks
- The original paper evaluates link prediction, recommendation, node classification/clustering, and inductive classification/clustering over academic and review graphs.

## Limits retained in article
- The inductive mechanism still requires the new node’s usable content/structural inputs. Content-feature preprocessing and the task-specific sampling design are part of the reported system.
- Results vary by task; a link-prediction gain does not imply the same ordering in transductive clustering.

## Figure preservation
- HetGNN figure URLs, sequence, and captions are unchanged.
