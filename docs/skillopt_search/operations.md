# G006 SkillOpt Approval v3 Operations Contract

## G007 Phase 6 observability operator contract

`src.search_eval.skillopt_observability` exposes a pure, deterministic evidence
contract. `build_attempt_summary(...)` accepts concrete validated v2 run
capabilities plus exact coordinator `status.json`, `stage_journal.json`, and
`heartbeat.json` mappings. The resulting `skillopt-attempt-observability-v1`
summary contains only bounded IDs, hashes, timestamps, counts, compatibility
classification, recomputed freshness, privacy booleans, and default-off
authorization facts.

The active lifecycle remains `skillopt-run-request-v2` / `skillopt-run-result-v2`
with `skillopt-orchestrator-status-v2`, `skillopt-orchestrator-journal-v2`, and
`skillopt-orchestrator-heartbeat-v2`. `approved-skillopt-policy-v3` remains
evaluation approval only and is not deployment authorization. Observability does
not alter either boundary.

The conceptual evidence ladder is
`fixture < compatibility < measured_research < shadow < production`. This phase
derives compatibility evidence only and rejects caller attempts to construct any
other class. Production remains unsupported, and Wave 3 cannot begin without
explicit external authority. Operators must treat any alert envelope as a no-go.

The fixed alert vocabulary is `stale_heartbeat`,
`repeated_compatibility_failure`, `revision_drift`, `budget_breach`,
`privacy_finding`, `release_holdout_leak`, and `authorization_misuse`. Every alert
has fixed severity, `owner=skillopt-operations`, bounded retention/deletion periods,
a summary hash, and optional sanitized exception digest and quarantine reference.
Exception text is never persisted. Label cardinality is capped at seven. The JSON
operator envelope performs no network, provider, subprocess, runtime, production,
or deployment action.

```bash
python -m pytest -q tests/test_skillopt_observability.py
```

## Scope and hard safety boundary

This is the operator contract for the implemented G006 approval-v3 SkillOpt
search path. The scope is QueryAnalyzer standard-search evaluation on
public or synthetic inputs. The repository coordinator validates and publishes
sealed artifacts; it is not a SkillOpt training runner or a production
deployment controller.

The coordinator, acceptance loader, and approval exporter must remain:

- credential-free;
- network-free and provider-free;
- subprocess-free;
- limited to public or synthetic data;
- free of raw user logs, personally identifying data, and secrets; and
- unable to enable `use_llm_search`, HyDE, RelevanceFilter, DeepReview, runtime
  traffic, or production configuration.

Rendered commands, generated benchmark modules, and external-runner metadata
are inert bytes inside this boundary. Repository code must not execute a
rendered command, import a generated module, call a provider, or source a
generated environment.

**External production deployment is a no-go.** No request, result,
acceptance manifest, `approved-skillopt-policy-v3` artifact, optimizer record,
shadow artifact, canary handoff, or reward entry authorizes production traffic
or an external deployment. A separately controlled production authorization
and deployment system is required outside this contract.

## Authoritative chain: v2 run evidence to v3 approval

The only authoritative request/result schemas are
`skillopt-run-request-v2` and `skillopt-run-result-v2`. Both are exact-key,
canonical-JSON, hash-identified contracts. Legacy request/result v1 documents
cannot be inferred, relabeled, converted, or auto-upgraded.

The exact authoritative request input set is:

- dataset, execution control, and baseline skill;
- generated environment archive, full dependency lock, and rendered config;
- compatibility profile and passed compatibility report;
- pristine-source, overlay, and staging manifests;
- runner identity and same-domain custody evidence; and
- ACL snapshot, immutable-store receipt, and trusted authority policy.

The v0 materialization manifest is deliberately absent. Adding
`materialization_manifest` to a v2 request is an exact-key schema failure. The
v0 materializer and `skillopt-candidate-generation-manifest-v0` are fixture/dev
characterization only. Their operational classification is `authority=none`
and `authorization_status=not_authorized`; candidate-generation v0 also
enforces `evidence_class=fixture`, `authoritative_use=false`,
`status=fixture_only_not_exportable`, and `requires_approved_export=false`.
Neither v0 artifact participates in authoritative request, acceptance,
approval, optimizer, reward, shadow, or canary chains. It cannot be relabeled or
upgraded into one of those chains.

The result must bind the exact sealed request bytes and identity, all upstream
and execution identities, output paths and bytes, usage/privacy receipts,
sanitized log digests, budget use, same-domain attestation identities, and the
candidate/evaluation/input lineage. The terminal result statuses are
`succeeded`, `failed`, `timed_out`, and `cancelled`. Every status must remain
inside the request's retry, timeout, budget, privacy, and receipt boundaries.
A non-success result cannot contain `best_skill`.

Paths are interpreted only under the absolute run root. Absolute child paths,
`..` traversal, symlink components, path substitution, duplicate JSON keys,
noncanonical JSON, hash or size drift, and unknown keys fail closed.

## External authority and evidence checks

Every authoritative operation requires an external deployment-owned context at
the absolute path named by `SKILLOPT_AUTHORITY_CONTEXT_PATH`. A request or API
call cannot provide or override a coordinator root. The canonical context pins:

- the coordinator root, namespace, and coordinator ID;
- the trusted authority policy's absolute path, exact bytes, identity, SHA-256,
  and size; and
- the issuer, verifier, and store allowlists, which must exactly match the
  trusted policy.

The request's trusted policy must be byte-for-byte identical to that external
pin. The implemented validator also requires and verifies:

- compatibility profile/report, runner, and custody identities against policy
  allowlists;
- custody issuer/verifier separation, identity, validity window, and ACL hash;
- ACL identity, validity window, `immutable=true`, distinct principals,
  coordinator/store/issuer/verifier bindings, and source/overlay object-version
  bindings;
- immutable-store receipt identity and validity window,
  `immutable=true`, `verified=true`, `retention_mode=governance-compliance`,
  subject runner, ACL hash, source/overlay immutable versions, and exact
  source/overlay/staging/runner/custody cross-bindings;
- usage receipt identity, request/status/runner/issuer binding, allowlist
  membership, time interval, cost, and token counts; and
- privacy receipt identity, request/status/runner/issuer binding, allowlist
  membership, freshness relative to the request/result interval, redaction
  report hash, and exact privacy-field agreement with the result.

These checks are implemented and required now; they are not deferred to PR3 or
PR4. They validate the supplied evidence and its external exact-byte pins. They
do not contact an external store or prove that an external store enforced its
claimed retention, ACL, immutability, or custody behavior.

Wave3 cryptographic trust roots and signature verification remain unsupported.
The authority policy must contain `wave3_trust_roots=[]`, the request must use
`wave3_crypto_required=false`, and the implementation verifies same-domain
identity/custody evidence rather than a cryptographic signature. Nonempty trust
roots fail closed and must not be described as verified.

## Coordinator modes

`python -m src.search_eval.orchestrator` requires exactly one mode:

- **`--dry-run`:** validate the sealed v2 request and authority evidence, create
  the request snapshot and durable lifecycle, and finish as
  `dry_run_complete`. It performs no external execution and produces no result,
  consumption record, candidate, or acceptance manifest.
- **`--import-result PATH`:** validate the sealed result at the exact requested
  `result_manifest_path`, publish canonical hash-bound local snapshots from the
  held bytes, write the coordinator-global consumption record, and commit the
  matching import terminal state.
- **`--cancel`:** cancel before any external execution or import and finish as
  `cancelled`. This action has no result or acceptance manifest.

The stable run-root lock is acquired before the authority-derived global
request lock. Concurrent callers therefore cannot publish competing lifecycle
or consumption outcomes for the same request. A busy lock returns a nonterminal
`busy` status; `busy` is not a durable terminal state.

The coordinator never imports the production policy loader, writes approval or
reward artifacts, spawns a process, or changes runtime policy configuration.

## Durable lifecycle and acceptance eligibility

The lifecycle begins with `requested -> running` for dry-run or import work.
The complete set of durable terminal states is:

| State | Source | Consumption record | Acceptance manifest |
|---|---|---:|---:|
| `dry_run_complete` | successful `--dry-run` validation | no | no |
| `candidate_ready` | validated imported result with `status=succeeded` | yes | yes |
| `failed` | validated imported result with `status=failed` | yes | no |
| `timed_out` | validated imported result with `status=timed_out` | yes | no |
| `cancelled` | validated imported result with `status=cancelled`, or explicit `--cancel` | import: yes; explicit cancel: no | no |
| `quarantined` | invalid/tampered input, publication failure, impossible lifecycle, or replay conflict | no new successful consumption | no usable acceptance |

`dry_run_complete` is terminal for the dry-run action but is not a consumed
external result. A later exact import may continue the same run as
`requested -> running -> dry_run_complete -> requested -> running -> <import
terminal>`. Repeating the same dry run or explicit cancellation is idempotent.

Only `candidate_ready` may carry non-null `acceptance_manifest_path` and
`acceptance_manifest_hash` fields. Failed, timed-out, and cancelled imports may
retain canonical evidence, evaluation, sanitized-summary, and receipt snapshots
for terminal provenance, but they have no `best_skill` and no acceptance
manifest. A stale manifest file left by a later incident is not an acceptance
capability: the loader requires the matching `candidate_ready` status, journal,
heartbeat, and coordinator consumption record.

The CLI may print an error envelope containing `state=failed` when validation
raises before a durable transition. Operators must distinguish that process
result from a durable `failed` status committed from a validated sealed result.

## Candidate acceptance and approved policy

A succeeded import publishes canonical local snapshots:

- `artifacts/run_request.json` and `artifacts/run_result.json`;
- every request input under `artifacts/evidence/`;
- `artifacts/accepted_best_skill.md`,
  `artifacts/accepted_evaluation.json`, and
  `artifacts/accepted_sanitized_summary.json`;
- accepted usage and privacy receipts; and
- `artifacts/acceptance_manifest.json` with schema
  `skillopt-acceptance-manifest-v2`.

Downstream callers must pass the canonical acceptance manifest and absolute run
root to `load_accepted_skillopt_candidate(...)`. The loader revalidates the
external authority context at actual use time; the sealed v2 request/result;
every evidence, output, and receipt snapshot; request/result identities and
sizes; compatibility, custody, authority, and receipt identities; the
candidate binding; the coordinator-global consumption record; and the exact
status/journal/heartbeat publication chain. It returns an immutable
`AcceptedSkillOptCandidate` only for a succeeded, `candidate_ready` import.

The approval exporter accepts no arbitrary `best_skill_path` and derives the
accepted policy bytes from that loader. It binds the evaluation dataset,
execution control, and baseline directly to the accepted v2 request; no
materialization manifest is an approval input. The selection threshold is at
least `+0.01 nDCG@10`, with the implemented selection, holdout, guardrail, and
evaluation-evidence checks.

The persisted approval schema is exactly `approved-skillopt-policy-v3` in the
canonical `approved_policy_artifact.json`. Authoritative consumers must load it
with `load_validated_approved_skillopt_policy(...)`, which fully replays the v2
acceptance chain and verifies the canonical sibling `best_skill.md` and disabled
`runtime_env.sh` before returning the frozen
`ValidatedApprovedSkillOptPolicy`. Nested mapping values are copied on access;
raw dictionaries are not capabilities, and downstream optimizer/reward/canary
consumers reload the persisted file before use.

Release evaluation has a separate deployment trust anchor:
`SKILLOPT_RELEASE_HOLDOUT_AUTHORITY_CONTEXT_PATH`. Its exact canonical
`release_holdout_authority_context_v1` schema pins issuer/evaluator/verifier
allowlists, immutable store root/ID/namespace/object prefix, required
`governance-compliance` retention, store-receipt issuer, ACL issuer/hash, and
`valid_from`/`expires_at`, sealed by `context_hash`. Callers cannot select these
values in the evaluation request. Manifest sealing/loading, precommit, terminal
publication, replay, and approval loading resolve or recheck the current
context; rotation quarantines an in-flight generation and invalidates persisted
approval capabilities. The v3 artifact stores only absolute state/manifest/
record paths plus generation, evaluation, and context identities needed for
full descriptor-held replay. Raw paths or decoded mappings are not release
capabilities. These controls remain same-domain Wave1-2 integrity evidence;
Wave3 signatures and independent cryptographic trust roots remain intentionally
out of scope.

There is no approval auto-upgrade, converter, shape inference, or version
relabeling. Approval v2 and earlier files are audit-only and cannot enter v3
consumers. Regenerate the v2 request/import/acceptance evidence and export a new
v3 approval.

The continuous optimizer receives only a narrow opaque receipt for that v3
approval. The receipt carries the approved artifact file/schema hashes, skill,
baseline, dataset, execution-control, rollback, and default-off anchors. It
contains no release capability, holdout result, metrics, thresholds, evaluator,
generation identity, labels, rankings, prompts, or per-query detail. The
optimizer cannot rotate or observe a release generation and cannot use release
feedback as reward. It atomically commits an idempotent reward-memory row before
atomically publishing a terminal `complete` summary and manifest; an identical
retry against the same output root and `run_id` resumes under a descriptor-held
run-directory lease. Recovery accepts only the prepared transaction journal's
exact request fingerprint, staged artifact bytes, and one matching committed
reward row, then publishes any missing commit marker, summary, and manifest
without appending again. Conflicting, duplicated, unexpected, symlinked, or
inode-replaced recovery state fails closed without overwriting evidence.

Every approval artifact remains
`evaluation_status=qualified`, `authorization_status=not_authorized`, and
`SKILLOPT_SEARCH_POLICY_ENABLED=false`. Fixture evidence is explicitly fixture
evidence; measured evidence must provide its required capture identity, capture
hash, and positive measured latency. Neither form authorizes deployment.

## Operation-scoped authority snapshot and rotation

After acquiring the stable run-root lock, the coordinator resolves one immutable
`AuthorityContext` snapshot. That snapshot contains the external context hash,
coordinator root/namespace/ID, exact trusted-policy bytes and pins, and the
allowlists. The same object is used for request capture, namespace selection,
result publication, consumption, and the terminal transition. The current
external context is resolved again at authority-checked commit boundaries; an
identity, byte, root, namespace, or policy change raises
`AuthorityContextRotationError` instead of mixing old and new authority.

For an uncommitted terminal transaction, the coordinator snapshots
`status.json`, `stage_journal.json`, and `heartbeat.json` before mutation. On
authority rotation it restores those exact lifecycle bytes, restores or removes
the transaction's explicitly tracked quarantine/incident artifact, and removes
only the consumption record written by that transaction if its bytes are still
owned. An already-committed winner under a new authority root is not removed.
Publication snapshots written before the terminal transaction may remain on
disk, but without the matching committed terminal lifecycle and consumption
record they are not consumable acceptance authority.

For a previously consumed terminal import, exact replay validates the immutable
record and can recover a compatible partial lifecycle or repair a terminal
heartbeat inside the same authority-checked transaction. On authority rotation
during that replay/recovery, the attempted lifecycle repair is rolled back, the
original consumption record and prior lifecycle bytes remain unchanged, no
record is created under the rotated authority, and only a replay/rotation
incident is recorded in the original namespace before the error is raised.

Malformed replay after consumption records an incident and returns or recovers
the recorded terminal result when that record is still provable. A conflicting
request, result, or replacement action cannot replace the consumed record; it
produces a replay incident and a quarantined invocation status. Recovery never
edits sealed request/result, accepted output, receipt, or evidence bytes.

## Quarantine and incident handling

Quarantine is required for unreadable/noncanonical artifacts, unsupported
versions, request/result mismatch, path or symlink violations, hash/size drift,
invalid authority/evidence/receipt bindings, privacy disagreement, resource-cap
violations, unsafe candidate content, impossible lifecycle state, publication
failure, or replay conflict.

Quarantine metadata records the reason and, when safely readable, only the
source hash and size; `suspect_content_persisted=false`. Suspect bytes must not be
copied into acceptance, approval, optimizer, reward, shadow, canary, runtime, or
production trees. Do not paste suspected secrets or personal data into tickets
or logs.

Authority rotation is recorded as an incident, not silently converted into
content authorization. Replay incidents are stored in the authority namespace
with the request/result hashes, run root, reason, and prior record reference.

## Ownership and operating no-go checks

| Activity | Responsible | Accountable | Consulted |
|---|---|---|---|
| v2 request/result schema and coordinator | Evaluation tooling maintainer | Search platform maintainer | Security/privacy reviewer |
| External context, policy pins, ACL/custody/store evidence, and allowlists | Deployment authority owner | Search platform owner | Security/privacy reviewer |
| Dataset provenance and public/synthetic classification | Search quality owner | Data/privacy owner | Evaluation tooling maintainer |
| Import, quarantine, and replay incident handling | Evaluation tooling maintainer | Search platform maintainer | Deployment authority owner |
| Offline evaluation and v3 approval export | Search quality evaluator | Search quality owner | Data/privacy owner |

Missing `SKILLOPT_AUTHORITY_CONTEXT_PATH`, an invalid or rotated authority pin,
private input, credential requirement, network/provider/subprocess requirement,
nonempty Wave3 trust roots, signature-verification claim, enabled runtime policy,
or external production deployment request is a no-go.

## Operator checklist

Before any mode:

- [ ] Inputs are public or synthetic; raw user logs, PII, secrets, and
      credentials are absent.
- [ ] `SKILLOPT_AUTHORITY_CONTEXT_PATH` is absolute and points to the intended
      canonical context; the coordinator root is real and the policy/allowlists
      are externally pinned.
- [ ] Request/result artifacts are canonical v2, and no v0 materialization or
      candidate-generation manifest is offered as authority.
- [ ] Run root and all referenced paths are contained, nonsymlinked, immutable
      for the operation, and hash/size pinned.
- [ ] No network, provider SDK, external command, or subprocess is required by
      the repository operation.

After the action:

- [ ] The durable state is one of `dry_run_complete`, `candidate_ready`,
      `failed`, `timed_out`, `cancelled`, or `quarantined`.
- [ ] Only `candidate_ready` has a non-null acceptance manifest binding.
- [ ] Journal, status, heartbeat, result, and consumption-record identities
      agree for the applicable state.
- [ ] Approval, optimizer, reward, shadow, and canary consumers use the typed v3
      loader and do not accept raw mappings or v0 materialization provenance.
- [ ] `authorization_status=not_authorized` and
      `SKILLOPT_SEARCH_POLICY_ENABLED=false` remain unchanged.
- [ ] No runtime traffic, external production deployment, credential, network,
      provider, or subprocess action occurred.

## Verification expectations

Credential-free tests must cover exact-key/version rejection, canonical JSON,
every request evidence byte binding, external authority and allowlist pins,
custody/ACL/store/usage/privacy identity-freshness-cross-binding checks, path and
symlink rejection, all terminal import states, acceptance eligibility,
idempotency and global locking, interruption/recovery, authority rotation
rollback, consumed replay incident preservation, typed v3 approval reload,
legacy no-upgrade behavior, and default-off/no-production behavior.

Verification is invalid if it accesses the network, invokes an external runner,
reads credentials, treats a v0 fixture as authority, enables runtime policy, or
changes production configuration.
