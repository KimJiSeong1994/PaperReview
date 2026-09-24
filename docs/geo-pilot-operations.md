# GEO pilot operations

The GEO pilot is a bounded editorial record. It does not publish content, submit URLs for indexing, fetch provider data, apply edits, or roll back posts automatically.

## Files and ownership

- `data/blog/geo-comparisons.json` is the source for the GraphRAG and GNN comparison blocks. `scripts/sync_geo_comparisons.py` validates it and generates the Python and TypeScript projections.
- `data/blog/geo-pilot.json` records no more than five existing, published member pages and the exact fields changed.
- `data/blog/geo-pilot-observation.json` is the manual observation record. Unavailable provider data remains `null`; it is never recorded as zero.
- `data/blog/posts.json` remains the published-content source. The pilot tools do not write it.

All commands resolve repository files from the script location, so they work from any current directory.

## Local validation

Run the checks before reviewing a change:

```bash
python scripts/sync_geo_comparisons.py --check
python scripts/validate_geo_pilot.py data/blog/geo-pilot.json data/blog/geo-pilot-observation.json
pytest -q tests/test_geo_comparisons.py tests/test_geo_pilot_manifest.py tests/test_blog_series_sync.py
```

If comparison prose changes, regenerate both projections and review the diff:

```bash
python scripts/sync_geo_comparisons.py
git diff -- routers/geo_comparisons_generated.py web-ui/src/seo/geoComparisons.generated.ts
```

The comparison command fails on a missing source, malformed cell, unpublished or wrong-series slug, unsafe source URL, missing generated file, or byte drift. Runtime reads only literal assignments from the generated Python file and compares both the embedded digest and projected payload digest with the canonical JSON source. It never executes the generated module. A missing, malformed, or mismatched source/projection produces the empty-comparison fallback, while CI treats the same condition as a failure.

## Manifest hashes and review

Each field value uses this exact digest:

```python
sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
```

The value includes JSON string quotes when it is a string. An `updated_at` edit is valid only when the same slug also has a real `excerpt`, `content`, or `deep_content` change. A draft may record a pending semantic review. Only an independent review backed by primary-paper evidence may be marked `approved`; the validator requires those approvals before a non-draft state.

## Observation boundaries

- A verified `Googlebot` or `Bingbot` index recrawl anchors a URL. Answer-fetch user agents such as `ChatGPT-User` and `Claude-User` do not.
- A deployed observation requires the approved non-draft manifest, the same deployment timestamp, all expected hub/page URLs, and matching recrawl/deadline lifecycle fields. The checked-in draft remains undeployed even though its semantic reviews are approved.
- The first review point is 28 days after the latest clean URL anchor. Reporting delay may justify exactly one extension to at most anchor + 56 days, and the record always stops no later than deployment + 70 days.
- The four source IDs are fixed: nginx answer fetches, AI referrers, GSC AI, and Bing AI. Each stores independent baseline and follow-up status/window/measurements in its provider timezone. Unavailable status requires null window and measurements; observed zero remains numeric zero. Counts are non-negative JSON integers and reject booleans, fractions, NaN, and infinities. Only `pages_per_session` is a finite non-negative ratio.
- Account direction is derived from equal-duration, ordered, non-overlapping baseline/follow-up values. Each available account period must identify the canonical site property, `page` dimension, and the exact pilot URL cohort; whole-property totals and foreign or partial URL scopes fail validation. Only GSC impressions and Bing citations/cited pages can support directional expansion review. Here `cited_pages` means the distinct cited URLs inside the fixed pilot cohort, stored as an integer; it is not Bing's fractional “Average Cited Pages” UI value. Grounding-query sample counts, nginx fetches, referrers, and reader outcomes cannot substitute for account evidence. The evaluator compares plain values and makes no lift, significance, or causal claim.
- Nginx weekly aggregates use contiguous, non-overlapping UTC `[start,end)` windows through the decision time. Missing periods are `partial_coverage`; empty or future-dated records cannot satisfy completeness.
- Reader outcomes have an explicit `available`, `partial_coverage`, `insufficient_data`, or `excluded` status and use only page views, sessions, pages per session, and landing sessions. Available records require all four values; unavailable values remain null.
- `decision_at` and `disposition` are populated together. `evaluate_disposition(observation, manifest, as_of=...)` returns the eligible disposition, reason code, and derived account directions. This proves internal record consistency only; it does not prove external truth.
- Evidence references must be bounded HTTPS references without query or fragment components, or safe repository-relative artifacts. Do not store secrets, raw IPs, raw queries, cookies, or authorization material.

The observation ends with `expansion_candidate`, `inconclusive`, or `rollback_recommended`. Complete timely evidence may be evaluated at the exact deployment + 70-day ceiling; incomplete evidence is inconclusive there, and no later time can expand. These are editorial dispositions, not causal or statistical claims.

## Rollback planning

`plan_rollback()` returns a plan and never writes files. For every edited field, it compares the current canonical value hash with `applied_hash`. If any field differs, it returns `rollback_conflict` with no updates, preserving concurrent edits. When all fields match, the plan contains only the target slug/field pairs and their recorded `before_value`; unrelated posts and fields remain untouched.

An operator must review and apply any plan through the existing locked, atomic post-writing path. Keep the manifest and observation evidence after rollback. `rolled_back` requires every `result_hash` to equal its `before_hash` and every current target value to match. `rollback_conflict` requires conflict evidence and permits no restored result hashes.
