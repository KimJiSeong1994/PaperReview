# Evidence — Theory-informed and interpretable graph learning for urban commuting flows

## Primary source read
- Sustainable Cities and Society article DOI: https://doi.org/10.1016/j.scs.2026.107575; official article page: https://www.sciencedirect.com/science/article/pii/S2210670726004610

## Method anchors
- PIG-GNN separates origin production and destination attraction encoders, models OD interactions, and uses soft distance-decay, Zipf, and distributional constraints.

## Result checks
- The study evaluates England Home-to-Work OD flows and reports RMSE, MAE, R², and CPC together with scaling-law consistency.

## Limits retained in article
- The physics-informed terms are empirical mobility scaling priors applied as soft penalties, not conservation-law enforcement.
- Interpretability analyses describe learned behavior on the observed OD setting and do not estimate causal impacts of transport-policy interventions.

## Figure preservation
- All PIG-GNN figure URLs, order, and source captions are preserved.

## Full paper recovered and critically checked

Official author-lab PDF,27 pages: https://urbanmorphology.studio/pdfs/zhao-et-al-2026-pig-gnn-commuting-flows.pdf

Sources: §3.2.1 Eq4/TableA8 GATv2; AppendixA1.2 EqsA3–A4 KL direction; TablesA10–A11/A17–A18 cross-dataset retraining; TablesA12–A13 feature/zero-edge experiments; Table3 oracle marginals; Table4 cumulative build-up; §3.1.1 versus §5.5/TableA14 distance mismatch; Figure12 versus Table2 sample-count discrepancy.
