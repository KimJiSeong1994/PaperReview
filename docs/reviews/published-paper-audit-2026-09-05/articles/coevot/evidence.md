# Evidence — CoEvoT: Co-Evolving Chain-of-Thought Prompting for Graph–LLM Reasoning

## Primary source read
- arXiv:2607.14114v1, official HTML: https://arxiv.org/html/2607.14114v1

## Method anchors
- Eq.4 maps frozen graph-encoder states into LLM token space. Eq.5–6 use thought-conditioned two-layer MLP prompts to residual-update each node state.
- §4.4 freezes the graph encoder and LLM; only projector and condition network are adapted.

## Result checks
- Table 1 evaluates source-to-unseen-target node classification across citation and e-commerce targets; §5.2 separately evaluates link prediction.
- Evaluation uses Arxiv or Computer as source and no additional target-dataset tuning (§5.1).

## Limits retained in article
- Results are limited to the specified GraphSAGE/LLM transfer setup and eight benchmarks; iterative token rewriting adds inference work.
- Several baseline values are reported from TEA-GLM, while GOFA is reproduced under the authors’ selected tuning setup.

## Figure preservation
- Existing CoEvoT figures and captions are retained exactly.
