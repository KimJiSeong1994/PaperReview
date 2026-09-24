# Evidence — SkillOpt

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- | --- |
| SkillOpt treats one external skill document as the optimized state of a frozen target agent. | Yang et al., arXiv:2605.23904v2, §§1–3 | method | high |
| The loop uses rollout evidence, bounded add/delete/replace edits, a held-out strict-improvement gate, rejected edits, and epoch-wise slow/meta updates. | §3, Algorithm 1, Figures 1–2 | method | high |
| The paper reports best or tied performance in 52 evaluated model/benchmark/harness cells and GPT-5.5 direct-chat +23.5 points over no skill. | §4 and result tables | result | medium-high |
| The method depends on a task reward/verifier and validation split that can distinguish better edits. | §§3, 5 | scope limitation | high |

Method map: frozen target agent → scored rollout → optimizer-model reflection → bounded document edit → held-out selection → deployed best skill.

Result check: figures and captions from `original.md` are unchanged in `revised.md` (three figure URLs, original order).

Accepted editorial changes: retained method, experiments, and source-backed limits; removed no paper content. Rejected: claims that an external code audit is needed to explain the paper.

Primary URL: https://arxiv.org/abs/2605.23904
