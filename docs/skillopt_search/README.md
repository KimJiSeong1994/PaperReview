# SkillOpt Paper Search Scaffolding

This directory documents the PR1 foundation for applying Microsoft SkillOpt to Jiphyeonjeon paper search.

PR1 intentionally avoids production search behavior changes. It adds:

- a baseline QueryAnalyzer search skill description;
- a synthetic/public benchmark fixture;
- an execution-control matrix;
- candidate artifact metadata checks;
- rollback metadata checks.

The v1 scope is QueryAnalyzer standard search only. `use_llm_search`, HyDE prompt optimization, and RelevanceFilter prompt optimization are later phases and are excluded from v1 promotion metrics.

See also:

- `data/search_eval/skillopt_paper_search_v0.json`
- `data/search_eval/skillopt_execution_control_v0.json`
- `data/search_eval/skillopt_candidate_artifact_example.json`
- `src/search_eval/skillopt_contract.py`

## Runtime application gate

The runtime hook is now wired only into the standard `/api/search` QueryAnalyzer path.
Generic `SearchAgent.smart_search`, `SearchAgent.llm_context_search`, `search_with_context`, HyDE,
RelevanceFilter, and `use_llm_search=true` paths do not receive the SkillOpt policy block.

Production remains default-off. To apply an externally approved SkillOpt candidate policy, all of
these environment gates must be present:

- `SKILLOPT_SEARCH_POLICY_ENABLED=true`
- `SKILLOPT_SEARCH_POLICY_PATH=/absolute/path/to/approved_skillopt_policy.md`
- `SKILLOPT_SEARCH_POLICY_HASH=sha256:<sha256-of-policy-file-bytes>`
- optional `SKILLOPT_SEARCH_POLICY_SCOPE=query_analyzer_standard_search`

When enabled, the policy file must be UTF-8, a regular file, under 16 KiB, hash-pinned, and must
state the v1 safety invariants: QueryAnalyzer standard search only, no `use_llm_search`, no HyDE,
and no RelevanceFilter prompt promotion. Invalid configuration fails closed: no policy is injected,
a warning is logged, and baseline QueryAnalyzer behavior continues. Cache keys include the validated
policy hash so policy and baseline results cannot reuse each other's 24-hour analysis cache entries.

## Real SkillOpt training / approval pipeline

The repo now includes a dev-only bridge for the upstream Microsoft SkillOpt trainer.
SkillOpt itself remains an optional external dependency; production does not import it.

1. Materialize the SkillOpt-compatible benchmark tree with
   `src.search_eval.skillopt_materializer.materialize_skillopt_search_benchmark(...)`.
   The generated tree follows the upstream custom benchmark contract: split data,
   `skillopt/envs/jiphyeonjeon_search/{dataloader.py,rollout.py,adapter.py}`, seed
   `initial.md`, and a YAML config.
2. In a SkillOpt checkout, register `JiphyeonjeonSearchAdapter` using the manifest's
   registration snippet, then run the manifest's `python scripts/train.py --config ...`
   command. The expected optimizer output is a `best_skill.md` artifact.
3. Score baseline and candidate production-like retrieval outputs with
   `src.search_eval.retrieval_eval.score_retrieval_results(...)`. The approval gate
   requires candidate `nDCG@10` to improve baseline, MRR/Recall guardrails not to
   regress, latency/token/cost estimates not to regress, and the wrong-paper handoff
   rate not to regress.
4. Export the approved `best_skill.md` with
   `src.search_eval.approved_policy.export_approved_skillopt_policy(...)`. This writes
   `best_skill.md`, `approved_policy_artifact.json`, and `runtime_env.sh` containing the
   exact `SKILLOPT_SEARCH_POLICY_*` environment variables consumed by the runtime gate.

### Selection split coverage requirement

The live SkillOpt trainer evaluates candidate edits on the generated `selection` split
before any offline retrieval approval/export. Upstream SkillOpt names this same split
`val`, so the materializer mirrors `selection/items.json` to `val/items.json`.

The selection/val gate must include at least two public/synthetic queries and must cover
both:

- `author_search` with a high-confidence author+concept canonical paper-title anchor;
- `method_search` with a high-confidence method/architecture canonical paper-title anchor.

This prevents a method-search improvement from being rejected solely because the gate
only exercises author search, and prevents aggregate retrieval metrics from hiding a
selection-critical canonical-title recall miss. Approved exports persist
`selection_gate` evidence, including the required intent coverage and per-query
`nDCG@10`/`Recall@10` pass status.

Approved exports also persist `holdout_gate` evidence for the independent `test`
split. Selection and holdout evidence are separately hash-bound. The holdout gate
requires each public/synthetic test query to avoid baseline regressions in
`nDCG@10` and `Recall@10`, so global improvements cannot mask an independent
holdout collapse.

Dataset and execution-control identifiers are canonical self-hashes. Reward-memory
duplicate detection and append run under one cross-process lock, and iteration
artifacts are staged before the positive reward append so partial failures remain
retryable without committing reward.

CI uses deterministic fixture retrieval outputs to verify the materialization, scorer,
and approval/export contract without live APIs. A live SkillOpt run still requires the
external `skillopt` package, model credentials, and production-like search result captures.

## Continuous optimization operating loop

After an approved `best_skill.md` has been exported, the continuous optimizer can
record one safe post-approval iteration without changing production behavior:

1. Load the persisted `approved_policy_artifact.json` with
   `src.search_eval.continuous_optimizer.load_approved_policy_artifact_from_path(...)`.
2. Build an optimizer decision with
   `build_optimizer_decision_record(...)`. The decision is accepted only when the
   approved artifact, baseline/candidate eval payloads, dataset, execution-control
   file, baseline skill, and materialization manifest all match their recorded
   hashes. Eval payload hashes include every key, so hidden extra fields cannot
   bypass approval lineage.
3. Append reward memory with `append_reward_memory_entry(...)`. This API reloads
   the persisted approved artifact from disk, verifies both schema and file hashes,
   rejects duplicate `run_id` / duplicate approved artifact entries, and rejects
   rolled-back, quarantined, rejected, hash-mismatched, or holdout-leaked outcomes.
4. Create the next iteration seed with `build_next_iteration_seed(...)`. The next
   baseline is the accepted candidate hash, and a different holdout generation id
   is required so repeated optimization cannot train against the same holdout
   feedback.
5. Optionally create a live-canary handoff with `build_live_canary_handoff(...)`.
   The handoff remains `rollout_fraction=0.0` and only records manual approval
   evidence, artifact freshness, expiry, and rollback SLA. It does not enable live
   rollout by itself.

For a single dev/eval bookkeeping step, use
`run_continuous_optimization_iteration(...)`. It writes:

- `optimizer_decision.json`
- `reward_memory_entry.json`
- `next_iteration_seed.json`
- optional `live_canary_handoff.json`
- `continuous_iteration_manifest.json`

The iteration manifest binds all operating artifacts by path and SHA-256 hash.
It is intentionally a bookkeeping/orchestration layer only: SkillOpt training,
production traffic collection, and runtime policy enablement remain external and
manual-gated.

## Candidate generation provenance boundary

Actual SkillOpt training still runs outside this repository, but the repo now
owns the provenance boundary for candidate generation. After an external
SkillOpt run produces `best_skill.md`, record the run with
`src.search_eval.skillopt_candidate_generation.record_candidate_generation_manifest(...)`.

The generated `candidate_generation_manifest.json` binds:

- the materialized benchmark manifest path and hash;
- materialization source hashes for dataset/control/baseline skill;
- the generated `best_skill.md` path and hash;
- the external runner, command, run id, completion time, and explicit
  `raw_user_logs_included=false` / `pii_included=false` evidence;
- `requires_approved_export=true`, because generated candidates still need the
  offline approval/export gate before runtime use or reward-memory updates.

This wrapper intentionally does not reimplement SkillOpt or launch model-backed
training. It records a reproducible boundary between the external optimizer and
this repository's approval pipeline.

## Operator summary artifact

`run_continuous_optimization_iteration(...)` now writes both machine-verifiable
and operator-friendly artifacts. In addition to the manifest, it emits
`continuous_iteration_summary.json`, which summarizes:

- run id and reward delta;
- candidate/baseline/approved artifact hashes;
- reward-memory append status and entry hash;
- next baseline hash and holdout generation rotation;
- live canary state, approver, approval/expiry timestamps, rollback SLA, and
  `rollout_fraction=0.0` when a handoff is present.

The summary remains hash-bound by the iteration manifest, so it is safe to use as
an operator-facing packet without weakening the underlying JSON artifact checks.
