# Evidence — Explaining Temporal Graph Neural Networks via Feature-induced Information Flow

## Primary source read
- arXiv:2606.27201v1 (2026-06-25), official HTML: https://arxiv.org/html/2606.27201v1

## Method anchors
- The paper decomposes event-based temporal GNN processing into event-processing, embedding, and decoding components to trace both feature-induced and event-induced-message information flow.
- Event Relevance uses the Normalized Relevance Measure framework and introduces joint relevance for event interactions.

## Result checks
- Evaluation covers Infection and Attacker synthetic settings plus ICEWS18; synthetic settings supply attribution ground truth, whereas the real data do not.

## Limits retained in article
- The result is a post-hoc attribution method for the modeled information flow; it does not establish causal effects of events in the external system.
- The modular relevance construction is architecture-dependent and its computational cost grows with the event computation graph.

## Figure preservation
- Existing temporal-GNN figure URLs, ordering, and captions are retained.
