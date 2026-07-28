# Search SkillOpt — Activation Plan

Status of this document: analysis and proposal. It authorizes nothing and it is
not a record of approval.

**Decision: DEFER.** The Step -1 and Step 0 pilots ran on 2026-07-27/28 and
their measurements trip the plan's own stop conditions. Training is not
impossible, but the dataset it would require is out of proportion to the value
it could deliver. See "Pilot results" below. The execution order from Step 1
onward is deferred, not cancelled — the gates that decide it are now measured
rather than assumed.

## Pilot results

### Step -1: intent and source distribution

Aggregated from 3.3 months of production logs (2026-04-18 to 2026-07-27),
793,459 delivered papers. Only aggregate counts were extracted; no individual
query text was read, which keeps the `raw_user_logs_included: false` constraint
intact.

| Source | Calls | Papers delivered | Hit rate | Share |
|---|---|---|---|---|
| OpenAlex (4 variants) | 108,208 | 731,307 | ~53% | **92.17%** |
| Connected Papers | 25,549 | 39,734 | 8.3% | 5.01% |
| Citation/Reference collection | 1,256 | 10,508 | ~75% | 1.32% |
| **arXiv** | 1,383 | 11,910 | 55.6% | **1.50%** |
| DBLP | 25,554 | **0** | **0%** | 0% |
| Google Scholar | 3,027 | **0** | **0%** | 0% |

Two findings, one of which is larger than this project.

**arXiv carries 1.50% of delivered results.** Applying the plan's own impact
formula to an arXiv-only training result: `+0.05 × 1.50% = +0.00075` blended
nDCG. That is not a user-visible improvement.

This share understates arXiv's potential rather than its demand — arXiv is
deliberately excluded from prefetch (`routers/search.py:758`) and throttled to
one request per 3.5s by a class-level semaphore. But the sources carrying the
other 98% are the ones currently broken, so the forward-looking picture differs
from the historical one.

**DBLP and Google Scholar have delivered nothing for 3.3 months.** 25,554 and
3,027 calls respectively, zero papers from either. This is not the transient
outage it appeared to be during the same-day investigation; it is a chronic
state. It is a larger operational problem than policy training and is tracked
separately.

### Step 0: sigma, proxy correlation, cost calibration

8 dataset queries run through QueryAnalyzer under two policies, each generated
arXiv query executed live, per-query nDCG@10 scored via
`retrieval_eval.score_retrieval_results` with `evidence_mode="measured"`.

**The first round of these measurements was invalid and has been replaced.**
`query_analyzer.py:178` calls the model with `temperature=0.3`. Re-running the
*same* baseline policy twice produced a per-query standard deviation of
**0.216** — the same magnitude as the effect being measured. Every sigma
reported before this correction mixed policy effect with sampling noise and is
withdrawn.

The fix is evaluation-only greedy decoding: the measurement harness wraps
`create_chat_completion` and forces `temperature=0`. Production is untouched;
0.3 is live search behaviour and lowering it is a separate decision. A control
run with the identical policy on both arms then produced per-query differences
of exactly zero across all 8 queries, confirming the harness is deterministic
and that arXiv itself returns stable results for a stable query.

All figures below are from the deterministic harness.

| Gate | Measured | Plan's rule | Verdict |
|---|---|---|---|
| sigma | **0.204–0.231** | `> 0.15` → DEFER | **DEFER** |
| Spearman rho | **0.264–0.532** | `< 0.7` → Option C not eligible | **C disqualified** |
| Model | `gpt-5.4-mini` | pin the model | pinned |
| Tokens | 16 calls: 24,182 in / 4,538 out | measure cost | ~1,511 in + 284 out per call |

Two hand-authored variants were measured against the deployed baseline. Neither
beats it.

| Policy | nDCG@10 | vs baseline | sigma |
|---|---|---|---|
| **baseline** (deployed) | **0.5091** | — | — |
| intent-split | 0.4222 | −0.087 | 0.231 |
| aggressive | 0.3976 | −0.070 | 0.204 |

Per-query:

| Query | Baseline | Aggressive | Intent-split |
|---|---|---|---|
| author-hinton | 0.432 | **0.000** | **0.456** |
| author-bengio | 0.902 | 0.371 | 0.543 |
| graph-rag | 0.861 | 0.902 | **0.963** |
| transformer-attention | 0.048 | 0.078 | 0.123 |
| ko-llm-finetuning | 0.582 | 0.582 | **0.044** |
| method-resnet | 0.201 | 0.201 | 0.201 |
| ambiguous-agent | 0.925 | 0.925 | 0.925 |
| method-bert | 0.123 | 0.123 | 0.123 |

Required sample size at the corrected sigma, paired t-test at α=0.05 and 80%
power:

| Detectable delta | sigma=0.204 | sigma=0.231 |
|---|---|---|
| 0.05 | 131 selection / **~653 total** | 168 selection / **~840 total** |
| 0.01 (contract floor) | 3,266 / ~16,329 | 4,201 / ~21,004 |

Lower than the ~1,216 previously reported, and still far beyond the 8 queries
that exist.

### What the pilot established

**The policy does change retrieval, and the effect is now separable from
noise.** Under greedy decoding, an identical policy on both arms yields exactly
zero difference, while a rewritten arXiv strategy yields sigma 0.204–0.231. The
training premise is sound and the measurement is trustworthy — but only after
the temperature fix. Before it, both readings available (sigma = 0.0 and sigma
= 0.278) were artefacts.

**Precision-first arXiv rules destroy author queries.** Mandating title-only
fields and quoted phrases collapses author intent: Hinton to zero results,
Bengio from 0.902 to 0.371. `au:"Geoffrey Hinton" AND ti:"capsule network"` is
too narrow to match anything.

**Splitting the rules by intent fixes what it targets and breaks something
else.** A second variant kept the tight rules for topic queries and loosened
the `au:` clause for author queries. It worked where aimed — Hinton recovered
to 0.456, above baseline; Bengio to 0.543 — and it improved graph-rag and
transformer queries. But `ko-llm-finetuning` fell from 0.582 to **0.044**, one
regression large enough to erase every gain. The author-side rule was written
from evidence; its effect on a Korean-language topic query was not predicted.

This is the argument for a training loop stated concretely. Hand-editing rules
fixes the case in front of you and silently damages a case you did not check,
and 8 queries cannot surface that before deployment.

**The required dataset is out of reach.** See the corrected table above:
~653–840 queries to detect a 0.05 improvement, ~16,000–21,000 for the 0.01
contract floor. Manual curation at that scale is months of domain-expert work.

**The text-proxy reward is not usable.** rho measures 0.532 for one variant and
0.264 for the other, both below the 0.7 admission threshold. Option C is
disqualified on measurement, which is what the Architect and Critic both
predicted would happen if the correlation were measured before committing.

**The deployed baseline is the best policy measured.** At 0.5091 it beats both
hand-authored alternatives. No policy change is warranted.

### The cheaper alternative was tried and it failed

An earlier revision of this document proposed splitting the arXiv rules by
intent as a hand-authored shortcut around training: narrowing helps topic
queries and destroys author queries, eight queries were enough to show the
split, so encode the split by hand and skip the dataset.

That was tried. It is the `intent-split` row in the tables above. It fixed the
regression it targeted — Hinton from 0.000 to 0.456 — and lost more elsewhere
than it gained, ending at 0.4222 against the baseline's 0.5091.

The shortcut fails for the reason the training loop exists. Eight queries show
you which rule to write; they do not show you what that rule costs on the cases
you did not examine. `ko-llm-finetuning` dropped from 0.582 to 0.044 and nothing
in the evidence used to write the rule predicted it.

A larger dataset does not merely make the statistics valid. It is the only
thing that makes a rule change safe to reason about at all — by hand or by
optimizer.

### Reproduction

The pilot scripts live outside the repository (session scratchpad) because they
target a deferred plan. To re-run: set the four `SKILLOPT_SEARCH_POLICY_*`
variables to the policy under test, call
`QueryAnalyzer.analyze_and_prepare(query, apply_skillopt_policy=True)`, execute
`source_queries["arxiv"]` through `ArxivSearcher`, and score with
`score_retrieval_results(evidence_mode="measured", ...)`.

Three methodology notes for whoever repeats this.

Force `temperature=0` for the analyzer during evaluation. At the production 0.3,
identical policies differ by 0.216 stdev and no comparison at this sample size
means anything. Wrap `create_chat_completion` rather than editing
`query_analyzer.py:178` — production decoding is a separate decision.

Run a control first: the same policy on both arms must produce exactly zero
per-query difference. If it does not, stop and fix the harness before
interpreting any policy comparison.

Run both policies per query in an alternating order, and persist raw search
results before scoring. A first attempt ran all baselines first, arXiv HTTP
503-throttled that phase alone, and the comparison measured API availability
rather than policy effect. The searches are the expensive part; a scoring bug
should not cost them.

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

**Steps 1 onward are deferred.** Steps -1 and 0 have run; their results are
above and they trip the plan's stop conditions. What follows is retained as the
route to take if the deferral is lifted — the sizing figures in step 1 are now
measured rather than assumed.

Steps 1–6 are prerequisites for step 7. The lock is the last gate, not the
first obstacle.

**-1. Intent and source distribution audit.** Done. arXiv carries 1.50% of
delivered results; DBLP and Google Scholar carry none. See "Pilot results".

**0. Restore search sources.** OpenAlex daily credits are exhausted (limit
1000, 10 per request, `retry-after` ~11.4h) and DBLP refuses connections from
the production host. Measured fan-out is ~6.2 OpenAlex requests per search,
which caps the free tier at roughly 16 searches per day.

This is now the highest-value item in the document. DBLP and Google Scholar
have returned zero results across 28,581 calls over 3.3 months while continuing
to consume request budget and latency on every search. That is a live
degradation of the product, independent of anything to do with policy training.

**1. Expand the evaluation dataset from 8 queries to ~650–840** (revised from
~980 by the corrected σ; see 1a). This is
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

**1a. Estimate σ from a pilot before committing to a total.** Done — this is
what deferred the plan. The corrected σ is **0.204–0.231**, above the top of
the range assumed above. At that variance the dataset needs ~653–840 queries to
detect a 0.05 improvement and ~16,000–21,000 for the 0.01 contract floor. The
~980 target in this step is in the right neighbourhood for the relaxed
threshold but nowhere near the contract floor, and either figure is far beyond
the 8 queries that exist.

The σ estimate rests on 8 deterministic pairs, so its own confidence interval
is wide. It is precise enough for the decision at hand: even the optimistic end
leaves the dataset requirement two orders of magnitude above what exists.

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

- Why have DBLP and Google Scholar returned zero results across 28,581 calls
  over 3.3 months, and what does it cost to keep calling them? This is the
  highest-value open question in the document and it is not about training.
- Does splitting the arXiv rules by intent recover the author-query regression
  without training? The pilot suggests it would, on eight queries.
- What is the "separately controlled production authorization and deployment
  system" that `operations.md` requires?
- Why does search carry a governance chain that deep review does not? Deep
  review activates with four environment variables and no `not_authorized`
  lock. The documents do not explain the asymmetry. The deep review benchmark
  is two fixture items, so the asymmetry is not explained by a higher bar
  having been met there.
- Who labels the expanded evaluation dataset, and against which corpus? At
  ~650–840 queries this is the binding constraint on the whole plan.
