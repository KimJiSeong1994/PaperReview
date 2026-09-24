# Evidence — Graph-of-Agents

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| GoA selects agents with model cards, samples relevance-weighted edges, passes messages in both directions, then pools responses. | Yun et al., ICLR 2026, §§3.1–3.4 | method | high |
| The paper reports 3-agent GoA results on six benchmarks and shows MMLU-Pro accuracy 54.78 with 11 calls for GoA_Max versus MoA 53.33 with 19 calls. | Table 1–2 | result | high |
| The graph is an inference-time prompt orchestration design; its message passing is not a learned graph neural operation. | §3 | scope clarification | high |
| Small margins, limited evaluation pools, and no reported variance constrain broad claims that three agents generally dominate larger ensembles. | Tables 1–5, experimental setup | scope limitation | high |

Method map: query + model cards → top-k agent nodes → pairwise response evaluation/edge pruning → bidirectional message prompts → max/mean graph pooling.

Result check: two original figures and captions are preserved in order.

Primary HTML read: https://arxiv.org/html/2604.17148
