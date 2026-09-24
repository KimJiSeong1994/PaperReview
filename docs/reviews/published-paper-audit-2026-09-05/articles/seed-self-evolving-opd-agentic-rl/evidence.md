# Evidence — SEED

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- | --- |
| SEED turns completed on-policy trajectories into hindsight skills, then re-scores the sampled actions with and without that skill. | Wu et al., arXiv:2607.14777v1, §§1–3 | method | high |
| The probability shift becomes a dense token-level on-policy distillation signal jointly trained with outcome RL. | §3–4 | method | high |
| The paper reports gains over GRPO across text and vision tasks, including ALFWorld 75.0→91.8 for Qwen2.5-3B. | Tables 1–3, 8 | result | high |
| Stage 1 uses externally generated initial skill annotations, and the paper does not establish return improvement from the auxiliary objective. | §2, theory/limitations sections | scope limitation | high |

Method map: on-policy rollout → trajectory analysis skill → ordinary/skill-conditioned paired scoring → gated OPD loss + GRPO → refreshed checkpoint.

Result check: the two original figure URLs and their order are unchanged. The public-code configuration audit was removed because it is not an explanation of the paper.

Primary source read: `source.pdf` (37 pages; §§2–4 and Tables 1–3, 8), with extracted `source.txt`. URL: https://arxiv.org/abs/2607.14777
