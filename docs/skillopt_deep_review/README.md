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

## Continuous optimization scheduler

The live service should enable only an approved, hash-pinned policy and run a
separate scheduler that keeps the DeepReview SkillOpt artifact set healthy. The
scheduler is a guard/bookkeeping loop: it validates the dataset, execution
control, approved candidate, rollback record, and the currently enabled runtime
policy hash. It does **not** mutate production prompts or auto-promote new
policies.

Manual smoke run:

```sh
python -m src.deep_review_eval.cron_runner
```

Recommended production cron entry:

```cron
# SkillOpt DeepReview optimizer gate: daily 03:35 KST / 18:35 UTC.
35 18 * * * cd /home/ubuntu/PaperReviewAgent && set -a; [ -f .env ] && . ./.env; set +a; . venv/bin/activate && python -m src.deep_review_eval.cron_runner >> logs/skillopt_deep_review_optimizer.log 2>&1
```

Optional env overrides:

```sh
SKILLOPT_DEEP_REVIEW_DATASET=/absolute/path/to/skillopt_deep_review_v0.json
SKILLOPT_DEEP_REVIEW_CONTROL=/absolute/path/to/skillopt_execution_control_v0.json
SKILLOPT_DEEP_REVIEW_CANDIDATE_ARTIFACT=/absolute/path/to/skillopt_candidate_artifact.json
SKILLOPT_DEEP_REVIEW_ROLLBACK_RECORD=/absolute/path/to/skillopt_rollback_record.json
SKILLOPT_DEEP_REVIEW_OPTIMIZER_STRICT=true
```

A successful run emits one JSON line with `status=complete`, artifact hashes,
and the active runtime policy hash. In strict mode validation failures return a
non-zero exit code so cron/system monitoring can alert on drift.
