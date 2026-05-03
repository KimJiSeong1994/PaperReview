# Daily recommendations workflow

The scheduled GitHub Actions workflow keeps PaperReviewAgent's notification API contract unchanged: recommendation notifications are still read from `data/recommendations/{user_id}/{YYYY-MM-DD}/raw.json`.

The workflow runs every day at **09:00 KST** (`00:00 UTC`) and now starts with a related-paper collection pass before generating recommendation artifacts.

## Related-paper collection and LLM wiki build

Before OpenClaw import and local recommendation generation, `.github/workflows/daily-recommendations.yml` runs:

```bash
python scripts/collect_related_papers_for_wiki.py \
  --bookmarks-db data/bookmarks.db \
  --papers-json data/raw/papers.json \
  --wiki-dir data/llm-wiki \
  --report-dir data/related-papers \
  --max-queries 10 \
  --per-query 8 \
  --top 24
```

This pass:

1. extracts seed queries from recent bookmark topics, titles, notes, and bookmarked paper titles;
2. collects related papers from OpenAlex;
3. reviews candidates with deterministic signals such as search rank, recency, citations, abstract availability, DOI/arXiv identifiers, and PDF availability;
4. merges reviewed papers back into `data/raw/papers.json` so local recommendations have a fresh candidate pool;
5. writes an LLM-readable daily wiki page to `data/llm-wiki/daily/{YYYY-MM-DD}.md` plus `data/llm-wiki/latest.md`;
6. writes a machine-readable review report to `data/related-papers/{YYYY-MM-DD}.json`.

The generated wiki is intentionally markdown-first so later agents can reuse it as a research memory layer: collection queries, review criteria, top reviewed papers, and next-agent instructions are preserved in one daily page.

## OpenClaw-first bridge

`.github/workflows/daily-recommendations.yml` now tries the AutoResearchClaw/OpenClaw paper recommender before the local generator:

1. SSH to the OpenClaw host (`OPENCLAW_HOST`, default `52.79.96.56`) and run `scripts/run_daily.sh` in the paper-recommender project.
2. Copy the latest OpenClaw `artifacts/*/raw.json` to the PaperReviewAgent host.
3. Run `scripts/collect_related_papers_for_wiki.py` on the PaperReviewAgent host to refresh `data/raw/papers.json` and build the daily LLM wiki page.
4. Run `scripts/import_openclaw_recommendation_artifact.py` to validate and import it into `data/recommendations/{user_id}/{YYYY-MM-DD}/raw.json`.
5. Run `scripts/generate_daily_recommendations.py --skip-existing` so users without a valid OpenClaw artifact still receive local daily recommendations, while a successfully imported OpenClaw artifact is not overwritten.

If the OpenClaw run, copy, or import fails, the workflow logs only the failure state and continues with the local generator. Raw recommendation JSON is not printed to GitHub logs.

## Required artifact shape

The OpenClaw `raw.json` import is intentionally minimal and compatible with `src.recommendations_artifacts.load_recommendation_artifact`:

- root JSON value must be an object;
- `user_id` must be a path-safe identifier (`A-Z`, `a-z`, `0-9`, `_`, `-`, max 64 chars);
- `variants` must be a non-empty object;
- at least one variant must contain a paper object with a non-empty `title`.

The destination date is resolved from an explicit `--date`, then `raw.run_at`, then the source parent directory (`YYYY-MM-DD`), then current UTC date as a last resort.

## Operational secrets

The workflow reuses the existing PaperReviewAgent EC2 secrets and supports optional OpenClaw overrides:

- `OPENCLAW_HOST` (default `52.79.96.56`)
- `OPENCLAW_USER` (default `ubuntu`)
- `OPENCLAW_PROJECT_DIR` (default `/home/ubuntu/.openclaw/workspace/projects/paper-recommender`)
- `OPENCLAW_SSH_KEY` (falls back to `EC2_SSH_KEY`)


## Personalized ranker v2 rollout

The local generator now supports an opt-in `daily_profile_ranker_v2` mode.
The default remains `daily_content_v1`; v2 is activated only when one of these
safe rollout paths is true:

- per-user `PROFILE_RANKER_ENABLED` DB override is enabled, or
- `PROFILE_RANKER_ALLOWED_USERS` contains the username and `PROFILE_RANKER_ENABLED=true`, or
- `PROFILE_RANKER_GLOBAL_ENABLED=true` and `PROFILE_RANKER_ENABLED=true`.

The v2 ranker consumes only privacy-safe event terms such as
`normalized_terms`; raw query/title/abstract text is not used as profile input.
If v2 fails for a user, the batch falls back to v1 for that user and records
`v2_failed` / `v1_fallback` counts in the CLI summary.

Related-paper JSON reports can be passed with `--related-papers-json`; this
adds a bounded source-confidence/review-score signal without reading LLM Wiki
markdown into the ranker.

The notification API also accepts explicit feedback/read-state events via:

- `POST /api/recommendations/feedback`
- `POST /api/recommendations/read-state`

These endpoints record event-bus signals for future ranking iterations without
changing the current artifact read path.
