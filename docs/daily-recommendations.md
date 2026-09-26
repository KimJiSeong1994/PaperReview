# Daily recommendations

## Contract

Every source supplies **candidates**, not final recommendations. `src/daily_recommendations.py` is the only final publisher: trusted intake → canonical deduplication → current owner policy → local profile/ranking → bounded MMR → guarded publication. OpenClaw scores, explanations and asserted user ownership are not trusted. The notification API never serves external raw JSON.

Final files use `data/recommendations/<account_incarnation>/<run_id>.json`, schema `recommendation_delivery_v1`, producer `common_local`. The old username/date `raw.json`, grouped variants, `--papers-json`, `--related-papers-json` and `--skip-existing` paths are retired. Existing files are not migrated or served as fallback.

The product shows **Top5**, preserving `final_rank` order, with at most 12 ordered reserve items. Scores are not comparable across users or modes. “Today” means daily discovery, not publication today. Generation age and publication date are separate; artifacts become stale at 36 hours and expire without cards at 72 hours.

## Public acquisition and private inputs

Public bootstrap uses only these fixed seeds: `graph neural networks`, `information retrieval`, `urban mobility`. It never derives outbound queries or shared wiki content from bookmarks, notes, reports, private searches, or their normalized terms. **Tokenization is not anonymization.** The old mixed `data/raw/papers.json` corpus is not an acquisition source.

The collector stages `public/local_public/current-local_public-public-seeds-v1.json`, with matching-basename `.receipt.json` and `.wiki.md` sidecars. Each registered source/provenance uses one fixed `current-{source}-{provenance_id}.json` slot; `source_run_id` remains inside the hash-bound envelope. Readers do not scan historical snapshots, and repeated acquisition does not accumulate run-named files. Sidecars are not candidate envelopes. Limits are three queries × eight candidates, at most six attempts including one retry, serial acquisition, at most ten seconds per attempt and sixty seconds total. Actual provider work runs in an owned, terminable process; streaming bytes are bounded before JSON parsing.

Snapshots carry `acquisition_status` (`ready`, `empty`, `disabled`, `degraded`, `error`) and sanitized acquisition reasons. These propagate into delivery source status/degradation, including `source_error`; failed acquisition is not relabeled as healthy empty. Collector exit **3** means acquisition error and permits the workflow to continue to the common local fallback; deadline/unexpected failure exits **2** and aborts that workflow. Other completed acquisition states exit **0**. These acquisition exits are separate from evaluator exits.

Acquisition is disabled unless an operator supplies `--source-qualified`. That flag is an **operator assertion**, not evidence of provider availability, terms, privacy, cost, or useful coverage. Injected test providers are explicitly fixture evidence. No live provider qualification is implied by passing local tests.

Private bookmarks and events are local-only and bound to captured account incarnation. Original initialized accounts retain an authoritative frozen legacy-event cutoff; new or recreated accounts do not inherit unclaimed historical events. Bookmark ownership similarly distinguishes original legacy records from new incarnation-tagged records. Review-session producers capture, persist and restore incarnation so later bookmark creation retains the originating account identity, including for new accounts. Private terms never enter public candidate manifests or explanations.

## Local batch commands

These examples require a separately prepared local data directory with explicitly provisioned authoritative policy state (see below). The generation CLI never provisions that store. Do not substitute a production directory for testing.

```bash
DATA=/absolute/path/to/local-test-data
export DATA_DIR="$DATA"
export EVENTS_DB_PATH="$DATA/events.db"
export FEATURE_FLAGS_DB_PATH="$DATA/feature_flags.db"
RUN_AT=2026-09-25T00:00:00+00:00
python3 scripts/collect_related_papers_for_wiki.py \
  --candidate-root "$DATA/recommendation-candidates" \
  --final-root "$DATA/recommendations" --run-at "$RUN_AT"
python3 scripts/generate_daily_recommendations.py \
  --candidate-root "$DATA/recommendation-candidates" \
  --users-db "$DATA/users.db" --events-db "$DATA/events.db" \
  --bookmarks-db "$DATA/bookmarks.db" \
  --artifacts-dir "$DATA/recommendations" --run-at "$RUN_AT" --limit 12
```

Without qualification, the first command honestly stages no acquired papers; it does not fabricate a usable pool. Choose a current UTC run time for normal operation. `--user` can select users; `--min-score` and `--v2-min-score` are independent floors. The API's `RECOMMENDATIONS_ARTIFACTS_DIR` must point to the same final root. API account storage uses `DATA_DIR`; use consistent paths rather than relying on a release directory's relative `data/`.

The batch is sequential for at most 100 users, with a single-process/cross-process file lease, a 600-second computation budget, 10,000 post-policy candidates, 500 owned bookmark/event inputs and an MMR shortlist of 200. It performs no provider or paid-model calls. Source acquisition is a separate bounded stage. Reuse requires matching identity/run/input/config/code/policy and validated content, not merely file existence. Current identity and policy are checked again before atomic publication; policy or authority failure does not authorize an unfiltered fallback.

Final-delivery retention is limited to validated owned deliveries older than 30 days, preserving current files. Candidate staging uses fixed current slots rather than a historical scan/pruning scheme. Historical snapshots and unrelated artifacts are not deleted by this change.

## OpenClaw intake

`scripts/import_openclaw_recommendation_artifact.py` accepts a local file and explicit trusted arguments: `--candidate-root`, `--final-root`, `--source openclaw`, `--source-qualified`, `--provenance-id`, `--scope`, `--source-run-id`, and `--collected-at`. Private scope also requires `--username`, `--account-incarnation`, and `--users-db`. Files are bounded to 20 MiB, variants to 16 with aggregate caps; raw source score/reason/user fields confer no authority.

Import only stages candidates. Default batch registrations and the scheduled workflow **do not enable OpenClaw**, even if an imported file exists. A reviewed `SourceRegistration`/`TrustedReceiverPolicy` must explicitly admit a qualified source to the common programmatic generator. Local bootstrap success is not proof of qualified combined-source operation.

## API and durable user controls

- `GET /api/recommendations/notifications?limit=5`: ordered visible items including the validated abstract, independent unread/total counts, run/time/mode, state/freshness, source statuses and degradation reasons. Cards show a whitespace-normalized abstract excerpt (up to 280 characters, three visual lines) instead of the generic personalization reason; missing abstracts are disclosed, never invented or generated through a model call. Each card has a compact PDF/More toolbar; related search, all feedback actions and paper provenance remain available through More. Publication date or year is shown once. Technical diagnostics remain behind a keyboard-operable disclosure. Missing delivery is labeled as not yet generated, distinct from an empty result. Limits are 1–5. Unsafe artifacts or unavailable policy return HTTP 503, never old raw data. The UI clears cached cards on refresh failure.
- `POST /api/recommendations/feedback`: `{run_id, canonical_key, action, request_id, undo_action?}`. Actions are `hide`, `already_seen`, `topic_less`, `interested`, `undo`.
- `POST /api/recommendations/read-state`: the same identity/request fields with `action: "seen"`.
- `POST /api/recommendations/exposure`: `{run_id, canonical_key, visible_fraction, visible_ms}`. Only current visible Top5 membership qualifies; the UI requires continuous ≥50% visibility for ≥1 second in an open, visible panel.

A control succeeds only after its durable transaction. Identical request replay returns its receipt without reapplying or emitting another event; conflicting reuse returns 409. Membership is validated against the owned run. Owned undo and existing receipt replay survive delivery expiry. Hidden/already-seen cards are removed and the ordered reserve refills the view. Exposure neither marks read nor supplies a negative label; ignoring a card is not a negative label.

The UI cache lasts at most 60 seconds, refreshes on open/focus/date change, cancels stale token-session responses, and retains undo receipts after a card disappears. Durable interested/topic-less state is authoritative for preferences; mirrored recommendation-feedback analytics are excluded from profile inputs to avoid double counting or resurrecting an undone preference. Supplementary analytics failure cannot reverse a durable control acknowledgement.

## Observed seven-day outcomes (local only)

`src.recommendation_attribution.attribute_recommendation_outcome` is a best-effort hook for **committed** `save` and `review_start` operations. Producers must call it after primary success, outside an existing account guard, with the captured incarnation, stable committed outcome ID and actual paper metadata. It applies `normalize_candidate` to the bounded bibliographic identity fields, excluding private text and client canonical/run/exposure claims. Failed primary operations must not invoke the hook. Revoked/recreated identities cannot receive credit. Attribution failure returns a sanitized `unavailable`/`not_attributed` result and must not turn an already successful save into a reported failure.

The state contract associates an outcome with the deterministic last qualifying visible touch for the same incarnation/canonical paper in the preceding seven days, not an arbitrary click or mere candidate membership. Immutable receipts are keyed by `(incarnation, kind, outcome_id, canonical_key)`: one real producer ID may legitimately contain multiple papers, while replaying the same tuple retains its original receipt and adds no credit. Credit is separately deduplicated by paper/kind/exposure-day. The primary numerator unions positive visible user-days across papers and kinds; per-kind counts also count positive user-days, not independent outcomes, and must not be summed into the primary numerator. A UTC exposure day matures only when its day-end plus seven days is no later than the observation time; right-censored days are reported separately, not treated as completed failures.

The local reporting CLI requires explicit paths and times, strictly opens the provisioned policy store, captures the current authority identity and guards the metrics read:

```bash
python -m src.recommendation_attribution \
  --users-db /absolute/path/to/local-test-data/users.db \
  --events-db /absolute/path/to/local-test-data/events.db \
  --username local-test-user \
  --since 2026-09-01T00:00:00+00:00 \
  --until 2026-09-15T00:00:00+00:00 \
  --now 2026-09-23T00:00:00+00:00
```

`since`/`until` are UTC-midnight boundaries for a half-open exposure-day interval. Output contains state-reported `total`, `mature`, and `right_censored` groups: visible-user-day denominator, positive-user-day numerator, per-kind counts and rate (`null` for zero denominator). Output is private local analysis, not a public API or export artifact. No network/provider calls occur. Exit0 means report construction, not improvement or promotion; unavailable/invalid reporting returns sanitized exit2.

These are **observed associations only**. Best-effort hooks and unknown historical capture mean observed positive counts are a lower bound, but the observed rate is not necessarily a population lower bound: exposures may also be missing. Capture completeness is unknown, causality is not estimated and promotion remains false. Retention and incarnation deletion apply to the state-owned outcome/receipt records alongside bounded exposure history; reports cannot reconstruct pruned history or claim complete historical denominators. Helper/CLI authorship alone does not prove all producers are wired or the state implementation passes end-to-end tests; state/hook integration and retention/deletion verification are separate required evidence.

## Authentication, cutover and deletion

JWTs carry `account_incarnation`; current account state and role are authoritative. Initialization is atomic and required before API readiness. Old unbound JWTs are rejected, so an authorized deployment must coordinate old worker/batch shutdown and reauthentication rather than run mixed identity semantics. Account updates use incarnation CAS, not implicit recreation.

Normal policy access is strict: `RecommendationState(path, authority=users)` where `users` is the authoritative `UserDB`. Explicit first provisioning uses `RecommendationState.initialize(path, authority=users)` at API startup or a separately authorized operator provisioning step; normal reads and the generation CLI never create, adopt or repair missing state. `users.db` retains an immutable policy-store receipt binding resolved path, schema, store ID and device/inode. A missing, replaced or mismatched store fails closed even when an empty replacement database looks structurally plausible. Backup restore therefore needs separately authorized recovery, not receipt deletion or automatic reinitialization. This document does not prescribe an unimplemented recovery command. Provisioning across users/events databases is not a cross-database atomic transaction; orphaned state requires operator recovery.

Deletion revokes authority before cleanup and reserves the username until cleanup succeeds. Partial failures are retryable (503); stale identity conflicts are rejected. Cleanup leases prevent late old cleanup from deleting a replacement account. Private intake, reads, controls and final publication require the captured active identity. Incarnation-tagged asynchronous analytics must also pass authority at durable write; this is not a claim that all historical untagged event producers have acquired a universal revocation fence.

## Ranking flags and evaluation

Existing v2 opt-in rules remain unchanged: per-user `PROFILE_RANKER_ENABLED`, or the existing enabled allowlist/global flags. There is no automatic rollout. V1 and v2 share hard policy and final MMR; fallback retains exclusions and negative preferences. Cold/negative-only output is honestly labeled metadata-only, not personalized quality.

Feature-flag storage uses `FEATURE_FLAGS_DB_PATH`, falling back under `DATA_DIR`. Bind both explicitly with `EVENTS_DB_PATH` to the intended data root; selecting `--users-db` alone is not flag-store isolation evidence.

```bash
python3 scripts/evaluate_daily_recommendations.py \
  --manifest data/recommendation_eval/public_fixture_manifest.json --offline
```

The fixture is synthetic correctness evidence, not independent preference labels or a promotion decision. Evaluation separates same-candidate scorer changes from same-scorer supply changes, freezes the ordered K12 delivery reserve before current policy projection at Top5, and reports @12 only secondarily. Suppressing the first12 cannot expose ranks13 onward. Full candidate-universe presence still contributes to supply/positive-coverage diagnostics and recall denominators, never visible credit beyond the reserve. See [the current recommendation roadmap](personalized-paper-recommendation-roadmap.md) for the full qualification gates. Do not infer live usefulness, p95 latency, provider reliability, or permission to promote from fixture results.

## Scheduled operation

The workflow is scheduled at 00:00 UTC (09:00 KST); scheduling is not a freshness guarantee. It uses a 15-minute job timeout, non-cancelling concurrency, an independent remote 780-second process-group timeout with five-second kill escalation, and an 810-second SSH wait.

Required configuration:

- Secrets: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `EC2_KNOWN_HOSTS` (pinned host keys).
- Variables: `RECOMMENDATIONS_RELEASE_PATH`, `RECOMMENDATIONS_RELEASE_SHA`, `RECOMMENDATIONS_DATA_ROOT`, `RECOMMENDATIONS_PUBLIC_SOURCE_QUALIFIED`.
- A clean immutable release at the configured 40-character SHA, `venv/bin/python`, a separate writable data root, and remote GNU `timeout`.

The workflow binds child `DATA_DIR`, `EVENTS_DB_PATH` and `FEATURE_FLAGS_DB_PATH` to `RECOMMENDATIONS_DATA_ROOT`; it accepts collector exit3 before common fallback but aborts on exit2. It refuses missing/drifted configuration. It does not fetch/reset/checkout, mint a broad user JWT, run an opaque external producer, or print raw remote logs. Unique transport credential files are cleaned on success, failure, timeout and interruption. Historical remote credentials are not destructively cleaned by this change. Actual deployment, transport qualification and live source acquisition remain separate authorized operational work.
