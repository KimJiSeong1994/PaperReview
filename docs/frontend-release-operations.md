# Frontend release storage and rollback

## CI execution scope

CI keeps the three required check names (`backend`,
`skillopt-v020-exact-source`, `frontend-build`). A change-detection job selects
which checks apply; skipped checks remain visible rather than leaving branch
protection waiting for a workflow that never starts.

- `backend-core`, `offline-optimizer`, and `poster-browser` always run in
  parallel without waiting for change detection. `scripts/ci_shards.py` owns
  the explicit offline optimizer and two real-browser file inventories.
  Runtime SkillOpt policy/authorization tests and every unlisted/new test
  default to core. Every shard collects the original full suite before
  selection; the stable `backend` required check audits equal collection
  snapshots and an exact, disjoint executed node-ID union.
- Each shard uploads raw `.coverage` (including hidden files) and execution
  receipts. `backend` requires all three successful jobs and complete receipts
  and coverage inputs. Each raw coverage database must measure exactly the
  repository's full Python source inventory under `routers`, `app`, and `src`,
  including unexecuted files; partial, wrong, or extra source sets fail closed.
  It combines coverage, then enforces the unchanged 15%
  threshold across `routers`, `app`, and `src` once. Missing, cancelled, failed,
  or skipped jobs cannot pass. Unexpected test skips fail too; only the
  existing optional exact-upstream fixture skips are allowed on Linux CI.
  Local non-Linux audits additionally allow the one Linux-only `renameat2`
  contract skip; they do not prove Linux sandbox or atomic-exchange execution.
  Chromium and
  its SUID sandbox checks run in `poster-browser`; missing browser execution
  cannot silently pass. The exact-source job still enforces its own policy.
- Same-run partial retries and aggregate-only retries accept successful shard
  receipts from earlier attempts only for the exact same SHA and workflow run
  ID. Receipt and current attempts must be positive numbers, with no future
  receipts accepted. Successful shard uploads overwrite their same-name
  artifacts on retry; failed shards do not upload. This does not reuse
  validation across separate runs or from PR validation for a main push.
- Exact-source SkillOpt verification runs when shared `src/`, `app/`, or
  `tools/` code, evaluation data, baseline documentation, tests, shared fixtures,
  Python dependencies/configuration, or CI definition changes. The pinned
  source checks and upstream execution tests are unchanged.
- Frontend PR checks run for `web-ui/` or CI definition changes. Every main push
  still builds and uploads a fresh frontend artifact. `npm run build` runs
  `tsc -b`; a second standalone TypeScript invocation is unnecessary.
- CI dependency installs explicitly select uv's CPU-only PyTorch backend;
  production dependency installation is unchanged. Python jobs use uv's
  dependency cache and installer. Superseded PR runs are
  cancelled, but main runs and serialized production deployment are not.

Deployment accepts a skipped SkillOpt check only when change detection
explicitly reports that component unaffected. Failed/cancelled checks, a
failed detector, and a missing successful frontend build block deployment.
Preflight, readiness, durable recovery state and rollback are not removed.
Test durations are printed to distinguish real execution cost from setup cost;
timing improvements must be measured on GitHub runners, not inferred from
local test speed.

## Production release storage

Production keeps `web-ui/dist` as a real directory because both Nginx and the
Python SSR path read it directly. A deployment extracts and validates the full
artifact in a sibling directory, then uses Linux
`renameat2(RENAME_EXCHANGE)` to atomically exchange it with `dist`. The active
path therefore remains present throughout promotion and rollback.

Each successful replacement retains two items beside `dist`:

- `.dist.previous.<release-id>` is the complete frontend that was active
  immediately before that release.
- `.frontend-releases/<release-id>.json` records the exact active and previous
  paths, source SHA, and activation or rollback state.

Rollback is journaled in two phases. Before the exchange the helper records
`rollback_intent`, verifies that `dist` is still the release named by the
activation marker, and verifies the saved identity of the previous tree. It
then copies the failed release's hashed assets into the rollback target so
clients that already loaded its HTML can still fetch their chunks. Existing
asset names are reused only when their bytes match; a same-name collision with
different bytes stops rollback. After the atomic exchange, the journal becomes
`rolled_back`. Retrying either an interrupted or completed rollback verifies
the recorded tree identities and succeeds without another exchange. A journal
from an older deployment cannot replace a newer active release.

Promotion also persists `prepared` and `promotion_intent` before the atomic
exchange. The workflow writes the deterministic journal path into its
per-release bundle before it invokes promotion, so a killed helper or broken
SSH session cannot lose the rollback pointer. Rollback recognizes the complete
persisted states on either side of the exchange: old active plus new stage,
new active plus old stage, and new active plus old previous directory. An
explicit rollback retains both releases' hashed assets and converges each
state to the same verified `rolled_back` result. Preflight is deliberately
read-only: `prepared`, `promotion_intent`, `activated`, and `rollback_intent`
journals block a new deployment without changing the active, staged, or
previous frontend. This prevents a frontend-only repair from being paired with
an unrelated backend checkout. After backend and content readiness pass, the
workflow finalizes the journal as `verified`; `verified` and `rolled_back`
journals do not block later preflights.

Before backend checkout, CI creates `.deploy-state/in-progress.json` and a
release-specific recovery directory inside the application checkout. The
recovery directory keeps the previous Git SHA, previous health-attestation
record, expected frontend journal path, and exact copies of the frontend,
readiness, and state helpers. Creation is exclusive under a lock. An existing
marker blocks a new attempt before checkout, and a blocked attempt cannot
overwrite or clear the marker owned by another release.

Clearing the marker does not delete its release-specific recovery directory.
These records are retained for diagnosis and, like frontend previous trees,
need a separately reviewed retention policy.

The CI rollback step first proves that the marker belongs to its own release.
Only a fully verified normal deployment or a successful paired frontend and
backend rollback clears that marker; every failure retains it for diagnosis.
If a host or SSH session dies after backend checkout but before frontend
promotion creates a journal, the durable record still identifies the previous
SHA and helper bytes. The next deployment remains blocked until an operator
uses that paired recovery evidence. The workflow never guesses a backend
checkout or automatically adopts the frontend left by an interrupted run.

The CI rollback step runs on failure and, on a best-effort basis, cancellation.
If promotion wrote its pointer but the expected journal is missing, rollback
fails closed instead of silently skipping the frontend. GitHub may terminate
all work immediately during force cancellation, so the durable marker and the
read-only preflight gate remain the recovery backstop.

The workflow does not prune either item. Storage use will grow with each
deployment until a separate, reviewed retention policy is introduced. Never
remove `web-ui/dist`, and do not remove the previous directory named by the
current release journal while it remains the rollback target.

Remote bundles use
`/tmp/paperreview-deploy-deploy-<workflow-run-id>-<run-attempt>`. A retry of the
same commit therefore has its own archive, helper scripts, rollback SHA, and
frontend journal pointer. Failed automated rollback bundles remain for
diagnosis. Successful deployment bundles are removed.

Before changing production, a queued workflow checks whether its target commit
is already an ancestor of a different deployed commit. Such a stale run exits
without promoting or rolling back anything. Readiness after restart attests the
full backend Git revision and systemd `MainPID` reported by `/health`, while
the workflow separately verifies that the systemd main process uses the
explicit single-worker command. The initial preflight omits revision and PID
requirements only when the older running backend does not expose those fields.
Preflight writes that capability decision, plus any reported revision and PID,
to `backend.previous.health.json` inside the per-release remote bundle. When
the old backend supports attestation, preflight requires its reported revision
to equal the saved rollback Git SHA and its reported PID to equal systemd's
`MainPID`; rollback requires both again after restart.

The first deployment of this contract may roll back to a legacy backend whose
health response has neither field. That one migration case is recorded as
`legacy` and rollback verifies the checked-out Git SHA on disk, systemd's live
`MainPID`, the explicit single-worker command, healthy JSON, and the exact SSR
and blog API content. It cannot attest the revision or PID from the legacy
process response itself. Partial or malformed attestation fields fail
preflight rather than being treated as legacy. Once the previous deployment
supports both fields, rollback uses full process attestation automatically.
