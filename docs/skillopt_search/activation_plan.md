# Search SkillOpt — Activation Plan

Status of this document: analysis and proposal. It authorizes nothing and it is
not a record of approval.

## Current state

Measured against production on 2026-07-27.

| Component | State |
|---|---|
| Runtime policy gate (`app/QueryAgent/skillopt_policy.py`) | Complete. Every failure mode fails closed to baseline. |
| Cron runner (`src/search_eval/cron_runner.py`) | Complete and registered. Runs daily at 03:20 KST. |
| Evaluation modules (`src/search_eval/`) | Complete. `evidence_mode="measured"` supported. |
| Approval exporter (`src/search_eval/approved_policy.py`) | Complete, and deliberately locked. |
| Reward adapter | **Mock only.** Reward is a marker-string check; it never runs a search. |
| Policy file | Hand-authored `candidate_skill_v1_draft.md`. `baseline_skill.md` is documentation, not a usable policy. |
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

### The runtime gate is open; the approval chain is not

On 2026-07-27 the four runtime environment variables were set manually in
production against `candidate_skill_v1_draft.md`, and the service now reports
`stage_modes.skillopt_policy_reason = "enabled"`.

This is worth stating precisely, because it is easy to overclaim:

- The **runtime gate** (`load_skillopt_policy_from_env`) only checks the four
  env vars and the file's hash, scope, and required phrases. It does not
  consult any approval artifact, which is why manual activation works.
- The **approval chain** is untouched. No candidate was trained, no acceptance
  manifest exists, no approval artifact was exported, and the lock in
  `approved_policy.py` was not modified. The cron still reports SKIPPED.
- The active policy is **hand-authored, not SkillOpt-trained**, and its effect
  on search quality is unmeasured — steps 1 and 4 below are what would measure
  it.

What has been observed is that the policy changes query generation in the
intended direction: an author query now yields
`au:"Hinton, Geoffrey" AND ((ti:capsule OR ti:networks) OR ...)`, which returns
19 arXiv results led by the author's capsule papers. That is evidence the
mechanism works, not evidence that retrieval quality improved.

Rollback is a single env change plus a restart. Policy-on and policy-off
results occupy separate cache namespaces, so disabling the gate restores
baseline hits with no cross-contamination.

`operations.md` states that external production deployment is a no-go without a
separately controlled authorization system. That system still does not exist,
and the manual activation above did not go through one.

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

## Candidate policy

`candidate_skill_v1_draft.md` in this directory — currently the active policy.
Validation: four required phrases present, 3776 bytes (23% of the 16 KiB
limit), `sha256:457b473b68a84fb8f8d85e703925eb967655f3e7e73df189df2e986fd31975a6`.

Each rule addresses a defect found by comparing the dataset labels in
`data/search_eval/skillopt_paper_search_v0.json` against the QueryAnalyzer
prompt in `app/QueryAgent/query_analyzer.py:815-845`.

| Defect | Evidence | Rule |
|---|---|---|
| `author_search` cannot be expressed in an arXiv query | Prompt RULES specify `ti:`/`abs:` only; no `au:`. The approval selection gate requires `author_search` coverage. | arXiv `au:"Last, First"` syntax |

The `au:` form was checked against the live arXiv API rather than assumed.
`au:"Hinton, Geoffrey"` and `au:"Geoffrey Hinton"` both return 58 results — the
index normalises the quoted phrase, so the comma form is not a broken query.
The bare `au:hinton` the repository uses elsewhere
(`arxiv_searcher.py:381`) returns 769, so the quoted form deliberately trades
recall for precision on author-intent queries. Whether that trade helps nDCG is
one of the things step 1 would measure.
| `ambiguous` cannot be classified | Prompt intent enum has 8 values, none of them `ambiguous`; the test split contains an `ambiguous` query. | Treat as ambiguous without inventing an enum value |
| DBLP 2–4 keyword limit is routinely violated | Prompt says "2-4 core technical keywords only"; observed output was 5 words. `dblp_searcher.py` defends with stopword removal and 8-word truncation. | Hard limit, drop verbs and qualifiers |
| No instruction covers `must_exclude` | Labels exclude wrong-domain matches ("real estate agent memory", "computer vision attention map only"); the prompt says nothing about domain anchoring. | Add one domain-anchoring term for ambiguous queries |

One further rule — canonical-work anchoring — comes from an observed failure:
a search for "attention is all you need transformer" produced the DBLP query
"transformer self-attention neural machine translation" and missed the original
paper. Decomposing a title-shaped query into component words loses the
canonical work.

## Execution order

Steps 1–6 are prerequisites for step 7. The lock is the last gate, not the
first obstacle.

**0. Restore search sources.** OpenAlex daily credits are exhausted (limit
1000, 10 per request, `retry-after` ~11.4h) and DBLP refuses connections from
the production host. Baseline capture is impossible until these recover.
Measured fan-out is ~6.2 OpenAlex requests per search, which caps the free tier
at roughly 16 searches per day.

**1. Expand the evaluation dataset from 8 queries to roughly 1000.** This is
the dominant cost and it is data work, not code work. Each query needs
`must_include` / `acceptable` / `must_exclude` labels applied with domain
knowledge.

The approval gate requires nDCG@10 improvement of at least +0.01. With n=8, the
minimum detectable difference is 0.05–0.15 depending on variance — five to
fifteen times the target. Required sample size for a paired t-test at α=0.05
and 80% power:

| σ of paired differences | Required n **in the evaluated split** |
|---|---|
| 0.05 | 196 |
| 0.10 | 785 |
| 0.15 | 1766 |

These are per-split figures, and the gate scores the `selection` split, which
the dataset defines as 20% of the total (`train 0.6 / selection 0.2 /
test 0.2`). A 200-query dataset yields only 40 selection queries — a fifth of
what the most optimistic variance assumption needs. Reaching 196 in the
selection split requires **roughly 980 queries in total**, and that is the
optimistic case: at σ=0.10 it would take about 3900.

**1a. Estimate σ from a pilot before committing to a total.** The table spans a
20x range in required sample size, and nothing in the repository indicates
which end applies. Label 30–50 queries first, score baseline against candidate,
and measure the variance of the paired differences. That single number collapses
the range and tells you what the real dataset target is. Skipping this means
either overbuilding by thousands of queries or discovering mid-project that the
target was far too low.

The current test split is 2 queries. No amount of pipeline work makes the gate
passable at this sample size.

**2. Capture a baseline and score it.** A single arXiv-only capture gives a
fixed corpus that supports `evidence_mode="measured"` while other sources are
down. Limitation: this measures query generation only, not multi-source
integration.

**3. Finalize the candidate policy.** The draft exists; it should be tuned
against the expanded dataset from step 1.

**4. Write a real reward adapter.** The repository has no working reward
function. The adapter it emits (`skillopt_compatibility_overlay.py`,
`ADAPTER_BYTES`) declares itself "Deterministic mock-only" and its `rollout()`
is:

```python
passed = _SUCCESS_MARKER in skill_content
return [{"hard": int(passed), "soft": float(passed), ...}]
```

The reward is whether the skill text contains a marker string. It never runs a
search and never computes nDCG. Training against this adapter would optimize
for inserting that marker. The mock exists to prove the adapter interface
matches SkillOpt v0.2.0's `EnvAdapter` / `SplitDataLoader` contracts — it is a
compatibility check, not a training environment.

A real adapter must run QueryAnalyzer with the candidate skill, execute the
resulting source queries, and score the results through
`retrieval_eval.score_retrieval_results`. It therefore depends on step 1 (the
labelled dataset) and step 2 (a capture to score against), and is paired with
them rather than following step 3.

**5. Stand up the external SkillOpt runner.** This is not a package install.
The repository never imports `skillopt`; `skillopt_compatibility_overlay.py`
emits adapter source as inert bytes for an external runner to execute. CI pins
`microsoft/SkillOpt` v0.2.0 by tag, commit, and tree hash for supply-chain
verification only. A separate runner environment, model credentials, and
same-domain custody evidence are required.

**6. Produce the three approval artifacts.** Once configured, the existing cron
stops reporting SKIPPED.

**7. Decide how to handle the activation lock.** Human decision — see below.

**8. Roll out.** Resolve the prefetch cache issue first.

Steps 0 and 1 have no dependency on each other and can run in parallel. Source
recovery is infrastructure work; dataset labelling is not blocked by it until
step 2 needs a capture.

## The activation lock

`src/search_eval/approved_policy.py` hardcodes the disabled state:

- `:213-214` — `evaluation_status: "qualified"`, `authorization_status: "not_authorized"`
- `:222-223` — `SKILLOPT_SEARCH_POLICY_ENABLED: "false"`
- `:1070` — validation rejects any value other than `"false"`

Options: (a) keep the lock and build the separate approval layer the contract
requires, (b) relax it conditionally, (c) bypass it with manual env
configuration.

Recommendation: **do not decide yet.** Steps 1–6 are unstarted, and debating
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
