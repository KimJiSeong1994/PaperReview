# Evidence — How Powerful are Graph Neural Networks?

## Primary source read
- arXiv:1810.00826v3 (2019-02-22), official HTML: https://arxiv.org/html/1810.00826
- The official record confirms title, four authors, and the ICLR 2019-era final preprint version.

## Method anchors
- Lemma 2: aggregation-based GNN discrimination is upper-bounded by 1-WL.
- Theorem 3: iterative update and graph readout must be injective for WL-level discrimination under the paper’s countable-feature setting.
- §4.1 constructs GIN with sum aggregation and MLPs to meet that condition.

## Result checks
- §7 uses nine graph-classification datasets; social graphs use degree one-hots (or constant features for REDDIT), which is part of the benchmark setup.
- Evaluation is 10-fold cross-validation; the paper reports mean and standard deviation across folds and uses 5 GNN layers with 2-layer MLPs.

## Limits retained in article
- The theorem concerns discriminative power relative to 1-WL, not generalization or arbitrary continuous feature spaces.
- The test comparison includes results quoted from original papers for several non-GIN baselines, as §7 states.

## Figure preservation
- Existing figure URLs and captions are preserved exactly from original.md.
