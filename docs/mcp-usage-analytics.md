# MCP usage measurement

## Scope and decisions

Add an independent admin MCP usage report, server request measurement, durable review/poster lifecycle measurement, and adapter tool telemetry. Browser analytics and search-evaluation samples must remain unchanged. This is operational measurement of client-claimed MCP traffic, not billing, proof of a particular host, people counts, or commercial adoption.

Two repositories ship together: PaperReview backend/UI and jiphyeonjeon-mcp adapter. Older adapters remain usable and their UA-labelled HTTP requests remain measurable. Local tools and validation failures require the updated adapter. No raw arguments, tokens, query strings, paper titles, or exception messages are collected.

## Shared implementation contract

Dedicated `MCP_ANALYTICS_DB_PATH` (default `data/mcp_analytics.db`), never `app_analytics_events`.

`src.analytics.mcp_usage.record_event(**fields) -> bool` and async `record_event_async(**fields) -> bool` are fail-open internal writers. Fields: `event_id` optional server UUID; `kind` request/tool/job; `name` normalized route / allowlisted tool / job kind; `status` started/succeeded/failed/cancelled/unknown; `actor_id`, `actor_role`, `invocation_id`, `job_id`, `duration_ms`, `http_status`, `adapter_version`, `client_name`, `client_version` optional; `source` ua_claim/adapter_report. Timestamps are server supplied. Duplicate lifecycle phases for the same actor and invocation/job must not double count; conflicting late starts must not overwrite terminal outcomes.

Root owns `src/analytics/mcp_context.py`, ASGI middleware wiring, auth context, review/poster hooks, deployment documentation. Backend executor owns `mcp_usage.py`, `routers/mcp_telemetry.py`, admin endpoint, backend storage/report tests. Frontend executor owns new admin MCP component/API/types/tests and admin navigation wiring. Adapter executor owns its separate repository.

Authenticated adapter ingestion: `POST /api/mcp/telemetry`, body `{invocation_id: UUID, tool_name: allowlisted string, status: started|succeeded|failed|cancelled, duration_ms?: finite nonnegative number, client_name?: bounded string, client_version?: bounded string, adapter_version?: bounded string}`. Reject extra fields. Derive actor from server authentication. Treat metadata as claims. Exclude telemetry endpoint, startup probes, admin APIs from request usage. Rate-limit ingestion; never accept client timestamps or user IDs.

Adapter business requests propagate `X-Jiphyeonjeon-Invocation-Id`, `X-Jiphyeonjeon-Tool`, optional `X-Jiphyeonjeon-Client-Name` and `X-Jiphyeonjeon-Client-Version`. Existing UA supplies adapter version. Use context-local metadata so concurrent calls cannot cross-contaminate. Tool telemetry must cover local checks and pre-handler validation failures, be bounded/fail-open, and preserve tool schemas/results/errors/cancellation and stdio output. Support opt-out.

Independent admin endpoint: `GET /api/admin/analytics/mcp?days=7|28|90&include_internal=false`. UTC storage; KST calendar-day reporting. Admin accounts excluded by default, selectable. No dependency on browser analytics DB or GA4. Empty initialized storage means measured zero; absent storage means not instrumented; storage errors mean unavailable.

Report JSON: `available`, `reason` (nullable), `window:{start,end,days,timezone}`, `measurement:{started_at,last_event_at,source_trust,tool_telemetry_available,limitations}`, `totals:{requests,active_accounts,tool_calls,tool_successes,tool_failures,tool_unknown,jobs_started,jobs_completed,jobs_failed,jobs_pending,request_error_rate,request_p95_ms,tool_p95_ms,job_p95_ms,repeat_accounts}`, `daily:[{date,requests,active_accounts,tool_calls,jobs_started,jobs_completed,jobs_failed}]`, `tools:[{name,calls,succeeded,failed,unknown,p95_ms}]`, `routes:[{name,requests,errors,p95_ms}]`, `clients:[{name,version,requests,tool_calls}]`, `versions:[{version,requests,tool_calls}]`, `jobs:[{name,started,completed,failed,pending,unknown}]`, `errors:[{kind,code,count}]`. Missing duration/rate denominators return null. Job rows use start cohorts in window with final state as of report generation; orphan terminals are unknown, never fabricated starts. Repeat accounts means meaningful usage on at least two distinct KST dates, not retention. Read/status polling and initialization do not activate accounts.

## Acceptance and verification

- Browser visits and search evaluation unchanged by MCP events.
- A multi-request tool remains one tool call; local tool and validation failure are represented when adapter telemetry reaches server.
- Started/terminal duplicates deduplicate; account scoping prevents cross-account identifier collisions.
- Failed/cancelled jobs remain durable after restart; no worker startup mutates another worker's jobs. Unclosed starts are pending (end not confirmed) for 24 hours, then unknown, derived only at read time. A later actual terminal resolves this uncertainty. HTTP timeouts do not imply worker failure.
- Invalid MCP bearer credentials cannot start an anonymous review and then strand it behind owner checks.
- Auth-derived actors only; UA/client metadata are explicitly labelled claims; no sensitive payload or unbounded labels.
- Missing DB, zero data, partial coverage and ingestion outages are represented honestly.
- Collector failure does not fail business operations; writes use bounded locking/off-loop execution.
- Backend targeted tests, existing analytics/auth/review/poster regressions, frontend tests/typecheck/build, adapter tests/lint/typecheck; independent review before publishing.

## Deployment

Backend first, adapter second. Initialize the dedicated ledger on backend startup so zero usage is distinguishable from missing setup. Do not backfill inferred tool calls or successful jobs from access logs. Release updated adapter with a version bump; already-installed adapters require upgrade/restart for tool telemetry.

## Review refinements

Lifecycle logical key is `(kind, actor_id, invocation_id|job_id)`: one start and earliest terminal, ignoring conflicting duplicate terminals and late starts. Job daily outcomes belong to the KST start-day cohort, not completion day. Orphan terminals remain unknown and do not fabricate starts. Job lifecycle source is `server_observed`; initiating MCP origin still rests on a client claim. Error codes are finite HTTP statuses or categorical outcomes, never raw exception text.

Measurement additionally includes `claimed_adapter_requests`, `requests_with_invocation_id`, `legacy_or_unattributed_requests`, and nullable `invocation_coverage` (linked requests / observed requests). This is request-link coverage, not a coverage estimate of all MCP invocations. Tool counts are observed lower bounds; invisible local calls and failed ingestion have no reliable total denominator. Active/repeat accounts use an explicit meaningful-action allowlist, excluding administrative/probe/status/telemetry traffic.

## Operations and limits

- Backend `MCP_ANALYTICS_DB_PATH` defaults to `data/mcp_analytics.db`. Startup creates schema and the measurement start timestamp; copy neither local test ledgers nor tombstones to production.
- `MCP_ANALYTICS_RETENTION_DAYS` defaults to 400, bounded to 90–3650 days. Event pruning uses the update-time index. Back up this SQLite ledger through the SQLite backup API, accounting for WAL.
- `MCP_ANALYTICS_TOMBSTONE_KEY` can pin a server-side HMAC key independently of JWT rotation. Without it, the JWT secret is used. Account deletion removes events and writes a pseudonymous tombstone, including when the ledger did not exist. Storage failure is reported as a partial deletion failure. Tombstones suppress late in-flight writes and also suppress later reuse of the same username; clearing one requires an explicit account-lifecycle decision.
- Adapter 0.1.6 adds best-effort tool lifecycle events. `JIPHYEONJEON_USAGE_TELEMETRY=0` disables those events and invocation headers. Existing server UA request observation still applies. A bounded queue may drop events during outages or shutdown; counts must be read as observed lower bounds.
- A tool success means the MCP handler and its validation/conversion returned normally. It is not a claim that a later review/figure job succeeded. A local validation tool may successfully report that a draft needs revision.
- Actual `generate_figure` calls use `/api/autofigure/method-to-svg` and are measured as `figure` jobs. Received success/failure establishes outcome; an upstream disconnect leaves the result unknown. Poster worker results are recorded even when the HTTP caller times out.
- Request duration is captured at the response boundary, with persistence detached from ASGI sending. Bounded pending writes drain on shutdown. Internal collector errors never prevent accepted background or poster work; genuine caller cancellation retains normal semantics.
- Request/tool labels are claims. Authenticated account identity comes from the user DB. Admin-account usage is excluded by default and visible with the administrator filter. No organization, revenue, billing, or installation count is inferred.

## Verification evidence

Backend unit/integration checks cover independent browser analytics, actor isolation, duplicate phases, KST start cohorts, stale and orphan jobs, success/error/unknown figure outcomes, poster completion after timeout, internal collector failure/cancellation, deletion tombstones, and missing/zero/unavailable reports. Frontend tests cover report states, filter races and navigation isolation. Browser smoke exercised actual report fixtures at 1440px and 390px with no document overflow or JavaScript errors. A real SDK JSON-RPC session against local backend ingestion observed one successful local tool plus one schema failure as two tool invocations and zero business HTTP requests.
