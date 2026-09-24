# Evidence — Where Reasoning Matters: Rethinking Latent Reasoning in Semantic ID-based Generative Recommendation

## Primary source read
- arXiv:2607.12425v1, official HTML: https://arxiv.org/html/2607.12425v1

## Method anchors
- The paper measures position-wise information gain of autoregressive semantic-ID tokens and proposes IBA to allocate latent refinement steps under a computation budget.
- Dual-axis refinement combines vertical semantic alignment, step-conditioned modulation, and horizontal hidden-state refinement.

## Result checks
- Experiments compare fixed and learned step allocation across semantic-ID recommendation benchmarks, with accuracy–compute trade-offs and component ablations.

## Limits retained in article
- The claim concerns the tested semantic-ID backbones and datasets; information gain is an allocation signal rather than a causal proof that any token position should always receive more compute.

## Figure preservation
- Existing IBA figures and captions remain unchanged.
