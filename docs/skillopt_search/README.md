# SkillOpt Paper Search Scaffolding

This directory documents the offline foundation for applying Microsoft SkillOpt
to Jiphyeonjeon paper search, including the PR0-PR2 artifact-only automation
boundary and the PR2.5 accepted-import-to-approval trust chain.

PR1 intentionally avoids production search behavior changes. It adds:

- a baseline QueryAnalyzer search skill description;
- a synthetic/public benchmark fixture;
- an execution-control matrix;
- candidate artifact metadata checks;
- rollback metadata checks.

The v1 scope is QueryAnalyzer standard search only. `use_llm_search`, HyDE prompt optimization, and RelevanceFilter prompt optimization are later phases and are excluded from v1 promotion metrics.

See also:

- `docs/skillopt_search/operations.md` — PR0-PR2.5 safety, ownership, lifecycle,
  recovery, quarantine, and operator contract;
- `data/search_eval/skillopt_paper_search_v0.json`
- `data/search_eval/skillopt_execution_control_v0.json`
- `data/search_eval/skillopt_candidate_artifact_example.json`
- `src/search_eval/skillopt_contract.py`

## PR0-PR2 automation boundary

The repository-side automation foundation is deliberately uncredentialed and
default-off. It may construct a versioned, hash-bound handoff request in dry-run
mode or validate an externally produced result in import-only mode. It does not
launch SkillOpt, access a provider or network, approve a candidate, append reward,
set runtime policy environment variables, or change production traffic.

Operators and implementers must follow
[`operations.md`](operations.md). In particular, an imported result remains
untrusted until its exact request identity, declared runner metadata, paths,
hashes, resource caps, privacy flags, sanitized log digests, and attestation
fields are internally consistent. Signature-backed runner provenance is not
verified until PR3. Invalid imports are quarantined and never proceed to
evaluation or runtime use.

Use `python -m src.search_eval.orchestrator` for the credential-free coordinator
CLI. Successful imports atomically publish canonical, hash-bound local candidate
and summary copies under `artifacts/accepted_*`; downstream evaluation must use those fixed
copies, not the external runner's mutable source paths recorded for provenance.
Every authoritative operation resolves one deployment-owned canonical context
from `SKILLOPT_AUTHORITY_CONTEXT_PATH`. That context pins the coordinator root,
namespace and ID, the exact trusted-policy path/bytes/identity, and issuer,
verifier, and store allowlists. Missing or changed pins fail closed; requests and
API calls cannot select or override that authority.

PR2.5 closes the next trust boundary: offline approval accepts only the canonical
`artifacts/acceptance_manifest.json` published by that coordinator. The exporter
revalidates the sealed request/result, accepted snapshot, request/result IDs, and
the dataset, execution-control, and baseline hashes used by the
evaluation. There is no `best_skill_path` argument that can bypass this chain.

The authoritative consumer schema is `approved-skillopt-policy-v2`. Operators
must use its fully revalidating loader, which replays the canonical v2 acceptance
manifest, sealed request/result, evidence and output snapshots,
compatibility/custody identities, authority policy/store receipt, usage/privacy
receipts, and disabled runtime-policy bytes before returning a typed object.

Raw dictionaries are never approval capabilities, even when their fields and
hashes look self-consistent. Existing v0/v1 approvals, `best_skill_path`,
`external_run`, version relabels, and synthesized acceptance hashes fail closed.
Rerun sealed import and approval to produce v2; there is no auto-upgrade or
v0-to-v2 converter.

## Runtime application gate

The runtime hook is now wired only into the standard `/api/search` QueryAnalyzer path.
Generic `SearchAgent.smart_search`, `SearchAgent.llm_context_search`, `search_with_context`, HyDE,
RelevanceFilter, and `use_llm_search=true` paths do not receive the SkillOpt policy block.

Production remains default-off. To apply an externally approved SkillOpt candidate policy, all of
these environment gates must be present:

G004 artifacts are not production authorization and require a separate external approval and deployment system.

- `SKILLOPT_SEARCH_POLICY_ENABLED=true`
- `SKILLOPT_SEARCH_POLICY_PATH=/absolute/path/to/approved_skillopt_policy.md`
- `SKILLOPT_SEARCH_POLICY_HASH=sha256:<sha256-of-policy-file-bytes>`
- optional `SKILLOPT_SEARCH_POLICY_SCOPE=query_analyzer_standard_search`

When enabled, the policy file must be UTF-8, a regular file, under 16 KiB, hash-pinned, and must
state the v1 safety invariants: QueryAnalyzer standard search only, no `use_llm_search`, no HyDE,
and no RelevanceFilter prompt promotion. Invalid configuration fails closed: no policy is injected,
a warning is logged, and baseline QueryAnalyzer behavior continues. Cache keys include the validated
policy hash so policy and baseline results cannot reuse each other's 24-hour analysis cache entries.

## Manual external SkillOpt training / approval pipeline

The repo now includes a dev-only bridge for the upstream Microsoft SkillOpt trainer.
SkillOpt itself remains an optional external dependency; production does not import it.
The commands below are manual instructions for a separately controlled external
environment. The PR0-PR2 repository coordinator treats rendered commands and
generated modules as inert artifacts and never executes or imports them.

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
   requires each split baseline record's `evaluated_skill_hash` to match the pinned
   baseline skill and each candidate record's hash to match the accepted candidate.
   It then
   requires candidate `nDCG@10` to improve baseline by at least `+0.01`, MRR/Recall guardrails not to
   regress, latency/token/cost estimates not to regress, and the wrong-paper handoff
   rate not to regress.
4. Import the sealed external result through `src.search_eval.orchestrator`, then
   export only its canonical `acceptance_manifest.json` with
   `src.search_eval.approved_policy.export_approved_skillopt_policy(...)`. The API
   requires both `acceptance_manifest_path` and its `run_root`; it derives the
   accepted `best_skill.md` internally. This writes
   `best_skill.md`, `approved_policy_artifact.json`, and a disabled `runtime_env.sh`
   template containing the exact policy path/hash/scope with
   `SKILLOPT_SEARCH_POLICY_ENABLED=false`. PR2.5 and the 0% handoff never generate
   an enabled environment; PR6 must create any separately reviewed rollout manifest.

PR2.5 verifies repository-local consistency, not external-runner authenticity.
The attestation reference remains descriptive until PR3 verifies a signature or
trusted statement against an approved runner identity. Do not treat
v2 approval artifacts as deployment authorization; approver identity, expiry, shadow evidence,
canary routing, telemetry, and rollback automation remain later gates.

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

Approved exports also persist nominal `holdout_gate` evidence for the `test` split.
Selection and test-split evidence are separately hash-bound. The gate
requires each public/synthetic test query to avoid baseline regressions in
`nDCG@10` and `Recall@10`, so global improvements cannot mask a test-split
collapse.

This does not prove optimizer blindness to test data: the current materialized
split tree is visible to the external runner. PR3 must validate an upstream
invocation that cannot read the sealed test inputs, and PR4 must release and bind
those inputs only after selection succeeds. Until then, `holdout_gate` is nominal
test-split evidence, not an independent holdout or production approval claim.

Persisted v2 approval artifacts explicitly state `evaluation_status=qualified` and
`authorization_status=not_authorized`. Their `evaluation_evidence` marks CI/demo
records as `fixture`; measured records require a capture ID/hash and positive
latency measurement. Fixture evidence validates the pipeline only and cannot
authorize runtime use.

Dataset and execution-control identifiers are canonical self-hashes. Reward-memory
duplicate detection and append run under one cross-process lock, and iteration
artifacts are staged before the positive reward append so partial failures remain
retryable without committing reward.

CI uses deterministic fixture retrieval outputs to verify the materialization, scorer,
and approval/export contract without live APIs. A live SkillOpt run still requires the
external `skillopt` package and separately authorized model credentials. Those
requirements do not apply to credential-free PR0-PR2 dry runs or validation of
synthetic imported fixtures. Production-like captures are a later privacy-reviewed
evaluation input, not a coordinator precondition.

## Canonical v2 post-approval bookkeeping loop

After an approved `best_skill.md` has been exported, the continuous optimizer can
record one safe post-approval iteration without changing production behavior:

1. Load the persisted `approved_policy_artifact.json` with
   `src.search_eval.continuous_optimizer.load_approved_policy_artifact_from_path(...)`.
2. Build an optimizer decision with
   `build_optimizer_decision_record(...)`. The decision is accepted only when the
   approved artifact, baseline/candidate eval payloads, dataset, execution-control
   file, and baseline skill all match their recorded
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

## Legacy candidate-generation characterization

The `skillopt-candidate-generation-manifest-v0` helper remains readable only for
fixture/dev characterization. It is deprecated with `authority=none`,
`evidence_class=fixture`, `authorization_status=not_authorized`, and
`authoritative_use=false`. It is not exported from the authoritative package
surface and cannot feed approval, reward, optimizer, shadow, or canary
consumers. For historical fixture work only, record a run with
`src.search_eval.skillopt_candidate_generation.record_candidate_generation_manifest(...)`.
Likewise, v0 materialization remains byte-compatible for fixture/dev replay only;
it is not measured compatibility evidence, trusted provenance, or authorization.

The generated `candidate_generation_manifest.json` binds:

- the materialized benchmark manifest path and hash;
- materialization source hashes for dataset/control/baseline skill;
- the generated `best_skill.md` path and hash;
- the external runner, command, run id, completion time, and explicit
  `raw_user_logs_included=false` / `pii_included=false` evidence;
- `requires_approved_export=false`, which prevents this legacy fixture from
  entering approval or any upgrade path.

This wrapper intentionally does not reimplement SkillOpt or launch model-backed
training. It records a reproducible fixture boundary only.

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
