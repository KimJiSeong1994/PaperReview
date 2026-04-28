# Daily recommendations workflow

The scheduled GitHub Actions workflow keeps PaperReviewAgent's notification API contract unchanged: recommendation notifications are still read from `data/recommendations/{user_id}/{YYYY-MM-DD}/raw.json`.

## OpenClaw-first bridge

`.github/workflows/daily-recommendations.yml` now tries the AutoResearchClaw/OpenClaw paper recommender before the local generator:

1. SSH to the OpenClaw host (`OPENCLAW_HOST`, default `52.79.96.56`) and run `scripts/run_daily.sh` in the paper-recommender project.
2. Copy the latest OpenClaw `artifacts/*/raw.json` to the PaperReviewAgent host.
3. Run `scripts/import_openclaw_recommendation_artifact.py` to validate and import it into `data/recommendations/{user_id}/{YYYY-MM-DD}/raw.json`.
4. Run `scripts/generate_daily_recommendations.py --skip-existing` so users without a valid OpenClaw artifact still receive local daily recommendations, while a successfully imported OpenClaw artifact is not overwritten.

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
