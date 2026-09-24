# Evidence — Planetary Prediction Engine: Autonomous Geospatial Prediction via Intelligent Data Selection and Foundation Model Embeddings

## Primary source read
- arXiv:2608.26088v1, official HTML: https://arxiv.org/html/2608.26088v1

## Method anchors
- §1.2 defines three stages: intelligent data selection, multimodal curation, and automated model building/prediction, with LLM tool orchestration.
- §2 evaluates nowcasting, downscaling, and spatial regression rather than one uniform dataset.

## Result checks
- Table 2: DRC Ebola Recall@10 is 83.3% [60.8,94.2] for full PPE versus approximately 73% baseline; the evaluation covers five weekly forecasts.
- Table 3: Nigeria FCG downscaling reports R² 66.1% versus 31.5% baseline, with 30-state bootstrap CIs.

## Limits retained in article
- Each task has distinct target, granularity, and split; headline cross-task comparisons should not be read as a single common benchmark.
- The paper’s agent pipeline is evaluated with constrained tool stages and curated evaluation protocols, not arbitrary unbounded web execution.

## Figure preservation
- Existing PPE figures and original captions remain unchanged.
