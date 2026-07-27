# Search SkillOpt — Activation Plan

Status of this document: analysis and proposal. It authorizes nothing. The
production gate remains default-off per `operations.md`, and nothing here
substitutes for the separate external approval and deployment system that
document requires.

## Current state

Measured against production on 2026-07-27.

| Component | State |
|---|---|
| Runtime policy gate (`app/QueryAgent/skillopt_policy.py`) | Complete. All 15 failure modes fail closed to baseline. |
| Cron runner (`src/search_eval/cron_runner.py`) | Complete and registered. Runs daily at 03:20 KST. |
| Evaluation modules (`src/search_eval/`) | Complete. `evidence_mode="measured"` supported. |
| Approval exporter (`src/search_eval/approved_policy.py`) | Complete, and deliberately locked. |
| Policy file | **Missing.** `baseline_skill.md` is documentation, not a usable policy. |
| Evaluation dataset | **8 queries.** Statistically insufficient for the approval gate. |
| Approval artifacts | **Missing.** All three. |

The pipeline is built. What is missing is the material to feed it. The cron
runner records this every night:

```json
{"missing_env": ["SKILLOPT_APPROVED_POLICY_ARTIFACT",
                 "SKILLOPT_BASELINE_EVAL",
                 "SKILLOPT_CANDIDATE_EVAL"],
 "reason": "missing_required_skillopt_artifacts", "status": "SKIPPED"}
```

Production reports `stage_modes.skillopt_policy_reason = "disabled"` — the
runtime env gate is unset, which is the intended default.

## Why `baseline_skill.md` cannot be used as a policy

It passes loader validation (all four required phrases, 1448 bytes) but is
unsuitable as prompt content:

- Line 4 states the file "is not loaded by production code in PR1". The policy
  file is injected verbatim into the QueryAnalyzer system prompt, so this
  sentence would tell the model it is not loaded.
- Lines 7–11 are development-process instructions about "v1 promotion", not
  query-analysis instructions.
- Lines 8 and 9 are near-duplicates.

Any replacement must avoid meta-commentary about its own approval status for
the same reason. Status belongs in this document, not in the policy file.

## Proposed candidate policy

`candidate_skill_v1_draft.md` in this directory. Validation: four required
phrases present, 3776 bytes (23% of the 16 KiB limit),
`sha256:457b473b68a84fb8f8d85e703925eb967655f3e7e73df189df2e986fd31975a6`.

Each rule addresses a defect found by comparing the dataset labels in
`data/search_eval/skillopt_paper_search_v0.json` against the QueryAnalyzer
prompt in `app/QueryAgent/query_analyzer.py:815-845`.

| Defect | Evidence | Rule |
|---|---|---|
| `author_search` cannot be expressed in an arXiv query | Prompt RULES specify `ti:`/`abs:` only; no `au:`. The approval selection gate requires `author_search` coverage. | arXiv `au:"Last, First"` syntax |
| `ambiguous` cannot be classified | Prompt intent enum has 8 values, none of them `ambiguous`; the test split contains an `ambiguous` query. | Treat as ambiguous without inventing an enum value |
| DBLP 2–4 keyword limit is routinely violated | Prompt says "2-4 core technical keywords only"; observed output was 5 words. `dblp_searcher.py` defends with stopword removal and 8-word truncation. | Hard limit, drop verbs and qualifiers |
| No instruction covers `must_exclude` | Labels exclude wrong-domain matches ("real estate agent memory", "computer vision attention map only"); the prompt says nothing about domain anchoring. | Add one domain-anchoring term for ambiguous queries |

One further rule — canonical-work anchoring — comes from an observed failure:
a search for "attention is all you need transformer" produced the DBLP query
"transformer self-attention neural machine translation" and missed the original
paper. Decomposing a title-shaped query into component words loses the
canonical work.

## Execution order

Steps 1–5 are prerequisites for step 6. The lock is the last gate, not the
first obstacle.

**0. Restore search sources.** OpenAlex daily credits are exhausted (limit
1000, 10 per request, `retry-after` ~11.4h) and DBLP refuses connections from
the production host. Baseline capture is impossible until these recover.
Measured fan-out is ~6.2 OpenAlex requests per search, which caps the free tier
at roughly 16 searches per day.

**1. Expand the evaluation dataset from 8 queries to 200+.** This is the
dominant cost and it is data work, not code work. Each query needs
`must_include` / `acceptable` / `must_exclude` labels applied with domain
knowledge.

The approval gate requires nDCG@10 improvement of at least +0.01. With n=8, the
minimum detectable difference is 0.05–0.15 depending on variance — five to
fifteen times the target. Required sample size for a paired t-test at α=0.05
and 80% power:

| σ of paired differences | Required n |
|---|---|
| 0.05 | 196 |
| 0.10 | 785 |
| 0.15 | 1766 |

The current test split is 2 queries. No amount of pipeline work makes the gate
passable at this sample size.

**2. Capture a baseline and score it.** A single arXiv-only capture gives a
fixed corpus that supports `evidence_mode="measured"` while other sources are
down. Limitation: this measures query generation only, not multi-source
integration.

**3. Finalize the candidate policy.** The draft exists; it should be tuned
against the expanded dataset from step 1.

**4. Stand up the external SkillOpt runner.** This is not a package install.
The repository never imports `skillopt`; `skillopt_compatibility_overlay.py`
emits adapter source as inert bytes for an external runner to execute. CI pins
`microsoft/SkillOpt` v0.2.0 by tag, commit, and tree hash for supply-chain
verification only. A separate runner environment, model credentials, and
same-domain custody evidence are required.

**5. Produce the three approval artifacts.** Once configured, the existing cron
stops reporting SKIPPED.

**6. Decide how to handle the activation lock.** Human decision — see below.

**7. Roll out.** Resolve the prefetch cache issue first.

## The activation lock

`src/search_eval/approved_policy.py` hardcodes the disabled state:

- `:213-214` — `evaluation_status: "qualified"`, `authorization_status: "not_authorized"`
- `:222-223` — `SKILLOPT_SEARCH_POLICY_ENABLED: "false"`
- `:1070` — validation rejects any value other than `"false"`

Options: (a) keep the lock and build the separate approval layer the contract
requires, (b) relax it conditionally, (c) bypass it with manual env
configuration.

Recommendation: **do not decide yet.** Steps 1–5 are unstarted, and debating
the removal of a safety interlock before there is a candidate policy or a
usable dataset inverts the order of work.

Option (b) is not recommended in any case. Tests enforce the `"false"` value,
so relaxing the lock also means removing the checks that verify it — disabling
a safeguard and its detector in the same change.

Option (a) has an unresolved dependency: `operations.md` requires a "separately
controlled production authorization and deployment system" but does not define
what that system is. That definition is itself a prerequisite.

## Rollout notes

**Prefetch cache is structurally invalidated when the policy is on.** The
prefetch path (`routers/search.py:772-782`) builds its cache key without a
`skillopt_policy` key, so `_compute_cache_key` defaults it to `"baseline"`.
Policy-on searches compute a different namespace and can never hit prefetch
entries. This is a permanent miss, not a TTL miss.

Prefetch calls `search_agent.search_with_filters` directly
(`routers/search.py:793`) and never runs query analysis, so its entries are
policy-neutral by construction. Giving prefetch its own namespace that both
modes consult is cleaner than letting policy-on searches fall back to the
baseline namespace, which also holds policy-shaped entries from user searches.

**Rollback is safe.** Policy-on and policy-off results occupy physically
distinct cache files, so disabling the gate immediately restores baseline hits
with no cross-contamination. Rollout is not free, though: enabling the policy
makes the standard-search cache cold.

**Coverage is narrow.** The policy reaches `/api/search` with `fast_mode=false`
and `use_llm_search=false` only. It does not reach the MCP path (which defaults
`fast_mode=true`), nor callers that construct searchers directly
(`routers/curriculum.py:413`, `routers/curriculum_pipeline.py:425`,
`src/related_paper_wiki.py:450`, `routers/exploration*.py`). Those paths do not
run QueryAnalyzer at all, so there is nothing for the policy to act on. Treat
this as an explicit scope boundary.

**Silent misconfiguration.** `is_skillopt_policy_enabled` accepts only
`1`, `true`, `yes`, `on`. Any other value disables the policy without an error.
Confirm activation by checking `stage_modes.skillopt_policy_reason == "enabled"`
in a search response.

## Open questions

- What is the "separately controlled production authorization and deployment
  system" that `operations.md` requires?
- Why does search carry a governance chain that deep review does not? Deep
  review activates with four environment variables and no `not_authorized`
  lock. The documents do not explain the asymmetry.
- Who labels the expanded evaluation dataset, and against which corpus?
