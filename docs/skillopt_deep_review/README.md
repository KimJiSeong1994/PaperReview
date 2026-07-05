# SkillOpt for Deep Review

This is the DeepReview-specific SkillOpt rollout surface. It mirrors the paper
search SkillOpt safety model while keeping review semantics separate from search
retrieval metrics.

## Scope

V0 scope is `deep_review_analysis_prompt` only.

Allowed:
- add hash-pinned guidance to the per-paper DeepReview analysis prompt;
- improve evidence grounding, methodological coverage, limitations, and author
  questions;
- keep the generated prompt partitioned by the policy hash.

Blocked:
- changing paper loading, workspace/session ownership, report serving, or
  persistence behavior;
- bypassing fact verification, advisor validation, schema checks, or loud
  failure semantics;
- enabling rollout without an approved hash-bound artifact and explicit env
  gate.

## Runtime gate

Production runtime uses `app.DeepAgent.skillopt_policy` only. It does not import
`src.deep_review_eval`.

Required env for rollout:

```sh
SKILLOPT_DEEP_REVIEW_POLICY_ENABLED=true
SKILLOPT_DEEP_REVIEW_POLICY_PATH=/absolute/path/to/best_skill.md
SKILLOPT_DEEP_REVIEW_POLICY_HASH=sha256:<digest>
SKILLOPT_DEEP_REVIEW_POLICY_SCOPE=deep_review_analysis_prompt
```

If the env is absent, DeepReview uses the exact baseline prompt. If env is
present but invalid, the policy fails closed: the request continues with the
baseline prompt and logs a warning.

## Dev/eval artifacts

- `data/deep_review_eval/skillopt_deep_review_v0.json` — benchmark contract.
- `data/deep_review_eval/skillopt_execution_control_v0.json` — rollout control.
- `data/deep_review_eval/skillopt_candidate_artifact_example.json` — hash-bound candidate approval example.
- `data/deep_review_eval/skillopt_rollback_record_example.json` — rollback record that forces the runtime flag off.
- `docs/skillopt_deep_review/baseline_skill.md` — baseline policy text.
- `src/deep_review_eval/contract.py` — dev-only artifact validation helpers.

V0 approval should compare baseline vs candidate on review-quality criteria such
as methodology coverage, evidence grounding, limitation specificity,
reproducibility assessment, and hallucination/fabrication bans. Do not reuse
search metrics like nDCG@10 as the primary DeepReview reward.
