# Real Incident Execution: Coding Agent Handoff

Status: implemented and locally validated on 2026-09-28. This file remains the acceptance specification.
Baseline: the current uncommitted working tree, inspected on 2026-09-22.

## Objective

Replace application-level fault switches with real, bounded failures in the bundled infrastructure. Agents must diagnose observed behavior and select an operational repair using the LLM. Browser-visible evidence must accurately describe what happened.

The result remains an explicitly identified incident-response lab. Success means the implementation stands up to inspection, not that the lab's identity or audit records are hidden.

## Preserve These Properties

- Preserve all existing uncommitted work; do not reset to HEAD or replace the current Groq implementation with the old workflow.
- All five specialist agents and investigation Q&A require model execution. No canned findings, scenario-based diagnoses, substitute reports, or heuristic confidence scores.
- Keep LangGraph, MongoDB persistence/checkpoints, SSE, finding citations, and human approval.
- Deterministic calculation, schema validation, authorization, formatting, and action execution are appropriate. They do not need LLM replacements.
- Keep sample payments explicitly identified as lab records. Do not introduce a payment provider or claim financial transactions occurred.
- Keep existing history intact. Historical flag-based investigations must not be relabeled as infrastructure incidents.
- Implement the tasks in dependency order. Do not expose an unfinished fault scenario as available.

## Scope and Architecture Decisions

1. Keep Docker Compose and the two sample services. Introduce one private FastAPI lab controller using a supported Docker SDK, structured requests, and fixed operation implementations.
2. The controller alone has access to the Docker daemon. The backend accesses it through authenticated HTTP; the frontend and LLM have no daemon credentials, arbitrary commands, raw Docker APIs, or arbitrary SQL execution.
3. Scope controller operations to the configured Compose project AND an explicit resource allowlist. Labels alone are insufficient. Docker socket access remains host-privileged; document that boundary and run a hosted demo on a dedicated disposable host/VM.
4. The controller owns runtime changes to designated resources after Compose bootstrap. Do not run Compose reconciliation/build commands during an active incident. Deployment operations recreate only the sample API from fixed templates.
5. Start with one shared lab and one atomic active-run lease. Multi-tenant sandboxes, Kubernetes, production integrations, auto-remediation, and Alertmanager are outside this iteration.
6. Use three real scenarios: a stopped Redis container; a blocking PostgreSQL transaction; and a distinct sample API image containing a real code regression.
7. Keep injection ground truth in a separate controller audit collection. Monitoring tools cannot read that collection. Preserve it for operator review and evaluation.
8. Use the current backend host-network configuration initially. Publish the controller on a configurable loopback-only port, default 8010, with separate monitor and operator credentials. Never expose that port or either credential through Next.js public environment variables.

## Target Contracts

### Public backend API

| Endpoint | Purpose |
| --- | --- |
| `POST /investigations` | Start an investigation from services, symptom, and time window without injecting any fault. |
| `POST /lab/runs` | Launch an available controlled fault and optionally start the same investigation workflow. |
| `GET /lab/runs/{id}` | Operator audit of injection state, expiry, cleanup, and associated investigation. Never an agent tool. |
| `POST /lab/runs/{id}/cleanup` | Explicit operator cleanup, recorded separately from remediation. |
| Existing investigation/detail/approval/Q&A/SSE routes | Preserve their roles and update payloads for real actions. |

`POST /investigations` accepts `services`, `symptom`, `time_from`, and `time_to`. Service names come from the configured inventory, times are validated UTC timestamps, and the initial maximum lookback is five minutes. A symptom is untrusted operator context, not evidence. It does not accept a scenario or desired action.

`POST /lab/runs` accepts an enum (`redis-unavailable`, `database-blocking`, `release-regression`) and `auto_start_investigation`. Its generated investigation request uses neutral symptom text. Keep any old `/simulate/*` route only as a documented compatibility adapter to implemented new scenarios; never retain flag-based behavior behind it. Return a clear unavailable response for scenarios not yet implemented.

### Agent-visible evidence

- Logs, metrics, dependency probes, container observations, deployment events, and database activity are observations with source and timestamp.
- Include stable observation IDs, query/scope, requested interval, actual observation interval, truncation metadata, and error/empty states.
- A container observation may include state and image identity; it must exclude environment secrets and controller injection metadata.
- A database observation includes blocker/blocked relationships, database identity, PID, backend start time, wait events, and bounded query text.
- A deployment observation includes service, previous/current image identity, and actual operation timestamp. It must not include an expected root cause or label an image as the answer.
- Keep normal operational facts even when they strongly suggest a cause. Do not fabricate sanitized error messages to conceal a simulation.

### Proposed actions and execution records

Replace `clear_redis_fault`, `clear_database_delay`, and `restore_sample_v1` with a discriminated action union:

| Action | Approved parameters and preconditions |
| --- | --- |
| `start_service` | Observed Redis resource reference, expected container ID, expected stopped state. |
| `terminate_blocking_session` | Observed session reference, database, PID, backend start time, and evidence of blocking an in-scope request. |
| `rollback_release` | Sample API resource reference, expected current image ID, and approved previous image ID from release history. |

Resource references must resolve to persisted tool observations, not model-invented IDs. Store `action_id`, `approval_id`, `investigation_id`, full approved parameters, supporting finding/observation IDs, and expiry. Freeze these on approval; changing targets or images requires a new approval.

Persist execution states `requested`, `running`, `succeeded`, `failed`, `stale`, and `unknown`, plus before/after observations and verification. A successful operation acknowledgement does not imply recovered service behavior. An ambiguous timeout or crash must remain `unknown` until reconciled.

Local Docker builds may lack repository digests. Record immutable Docker image IDs (`sha256:...`) and repository digests when available; do not invent digests or treat mutable tags as immutable identity.

## Implementation Tasks

### T00: Baseline and regression inventory

Files: current backend/frontend tests, `Makefile`, `docker-compose.yml`.

- Read repository instructions; before frontend edits read `frontend/AGENTS.md` and the applicable installed Next.js guides.
- Before LangGraph edits, read the available `ecosystem-primer` and `langgraph-fundamentals` skills, plus persistence/human-in-the-loop guidance for changed checkpoint or approval behavior.
- Run existing backend and frontend suites. Record pre-existing failures separately from introduced regressions.
- Inventory current active investigations without injecting faults or deleting data. Do not rebuild the live lab during an active run.
- Capture contracts currently relied on by the UI: status values, evidence version, approvals, report JSON, and SSE types.

Done when: the agent has a recorded baseline and a scoped change list. No existing changes have been reverted.

### T01: Data contracts and historical compatibility

Files: `backend/app/models.py`, `backend/app/store.py`, `backend/app/main.py`, `frontend/lib/types.ts`; focused API/store tests.

- Introduce the investigation request, discriminated action types, observation references, execution records, lab-run records, and lease storage.
- Use `evidence_version=3` for new infrastructure-backed investigations. Read versions 2 and 3, visibly label version 2 as historical lab-control records, and preserve the current treatment of pre-version-2 data.
- Split the current `_is_current_evidence` check into explicit readable-record and executable-current-action policies. No version-2 approval may execute a new infrastructure operation.
- Remove the requirement for `scenario` from new agent state. Retain historical scenario metadata and an optional operator-facing `lab_run_id` outside the agent input projection.
- Add explicit assessment outcomes: `incident_detected`, `no_incident_observed`, and `insufficient_evidence`. Map these consistently to UI/report states; no-action must not automatically imply inconclusive.
- Add atomic compare-and-set transitions for approvals and a unique active lab lease. Replace check-then-start list scans as the concurrency guard.
- Define no-remediation terminal outcomes and a separate recovery origin (`agent_action`, `operator_cleanup`, `automatic_cleanup`, `external`, or `unverified`).

Done when: version-2 records remain readable, old actions cannot execute, and concurrent submissions cannot acquire the same lab twice. Test both the in-memory contract and Mongo atomic behavior.

### T02: Controller and backend adapter

New files: `lab-controller/app/{main,config,models,store,docker_ops}.py`, `lab-controller/{Dockerfile,requirements.txt}`, `backend/app/lab_client.py`.
Existing files: `docker-compose.yml`, `.env.example`, `backend/app/config.py`.

- Implement authenticated monitoring, lab-run, operation, and cleanup endpoints. Only monitoring endpoints are reachable through agent tool wrappers; monitoring credentials cannot mutate resources or read injection records.
- Implement read-only container inspection first, returning a bounded field allowlist.
- Resolve resources from fixed configured services, project identity, and allowed labels. Reject arbitrary container names, images, mount paths, commands, and Docker options.
- Predefine creation templates for the sample API. Do not copy arbitrary container configuration into a new release.
- Persist controller operation journals and run leases in a separate Mongo database/collection namespace. Operation keys are unique by approved action ID.
- Authenticate backend-to-controller requests with server-only credentials; redact credentials from audits and errors. Missing configuration makes affected capabilities unavailable.
- Keep the controller out of dependencies that would prevent it from starting when Redis or a sample service is broken.
- Make Compose project names, host ports, and network names overrideable so tests can use an isolated project. Remove the fixed network-name collision for integration runs.

Done when: read-only inspection works; unauthorized mutations and out-of-scope targets fail; credentials never appear in public API payloads; restarting the controller preserves operation records.

### T03: Scenario-independent investigation and observed-resource tools

Files: `backend/app/{main,workflow,tools,models,store}.py`, `backend/tests/{test_api,test_workflow,test_tools}.py`.

- Implement `POST /investigations` without invoking any injection code. Reuse it internally from the launcher.
- Replace `_observation_prompt`'s hardcoded service scope with the validated request scope and timestamps. Give the model the same capability catalog regardless of the launcher scenario.
- Add bounded tools for service runtime inspection and deployment history; add database activity inspection in T09.
- Persist observations and attach their IDs to findings. Preserve Loki/Prometheus payload provenance and record truncation; do not assert a full timeline from an eight-entry sample.
- Ensure `get_service_health` preserves actual 503 response bodies/status as unhealthy observations instead of discarding useful dependency evidence in `raise_for_status()` handling.
- Let collector agents inspect infrastructure evidence alongside logs/metrics. Do not map scenario enums, fault-record IDs, or injector state to a diagnosis or action.
- Require the correlation output to cite supporting findings and any operational resource it proposes to change.
- In live Q&A, distinguish observations from generated findings and recovery claims. Keep model failure and invalid citations explicit.

Done when: the same workflow accepts a manually started healthy investigation, an externally introduced fault, and a launcher-generated incident without receiving ground truth.

### T04: Approval and real operation execution

Files: `backend/app/{main,workflow,store,models}.py`, `backend/app/lab_client.py`, controller operation handlers.

- Keep LangGraph's pure interrupt gate. Reserve the pending approval atomically before starting its resume task; duplicate requests cannot launch duplicate remediation.
- Execute the frozen approved action, never re-derive an action from the lab scenario or let a report change the execution record.
- Revalidate resource identity and preconditions immediately before mutation. Mismatches produce `stale`, invalidate the action, and require fresh review.
- The controller journals intent before mutation and returns the same operation for duplicate action IDs.
- Reconcile interrupted operations against actual state. If attribution cannot be established, keep the outcome unknown. Do not claim exactly-once external effects from a database write alone.
- Invalidate pending approvals on cancellation, run expiry, and cleanup. Reject approval attempts for cancelled, cleaned, or historical runs.

Done when: rejection performs no operational action; replayed approvals do not repeat it; stale resources are untouched; controller/backend restarts cannot silently replay an uncertain mutation.

### T05: Redis fault and recovery, first complete milestone

Files: controller `docker_ops.py` and run handlers; `sample-apps/app.py`; backend action catalog; API/workflow/integration tests.

- Injection stops only the configured Redis container and confirms its actual stopped state before acknowledging the fault.
- Remove `redis_failure`, its route, and all conditionals that manufacture Redis errors. Dependent requests must perform real Redis operations and log the actual resulting exceptions.
- Preserve measured request/error telemetry, including failed request durations. Generate bounded real workload continuously.
- `start_service` starts the observed stopped container. It must refuse a changed container identity or a non-allowlisted target.
- Add the real Redis scenario to the launcher only when injection, model analysis, approval, execution, and T06 verification all work.

Done when: a stopped container produces real dependent failures; an approved start restores Redis and application operations; both the model audit and Docker observations substantiate the report.

### T06: Recovery verification and truthful reports

New file: `backend/app/verification.py`.
Existing files: `backend/app/workflow.py`, `sample-apps/app.py`, verification tests.

- Move `verify_recovery` into a focused module with scenario-independent checks selected by affected service and approved operation.
- For the API, verify successful `/api/users` and `/api/products` response schemas and durations.
- For payments, POST a small lab payment, validate its created ID and processed state, then GET that exact ID. An unknown record or generic 200 is failure. Expire or remove only the probe's own record.
- Initial verification policy: three consecutive successful probe rounds, five seconds apart, each expected operation under two seconds; configurable maximum verification window of 60 seconds.
- Check action postconditions too: Redis running/reachable, blocking session gone and waits cleared, or expected image running. Healthy HTTP alone is insufficient to prove the approved operation ran.
- Query fresh Prometheus observations over a window after the action. Record sample count, freshness, error fraction, and latency alongside a pre-action baseline. Counter resets after replacement must be handled using appropriate counter queries.
- Require request success and acceptable fresh telemetry for verified recovery. Missing/stale telemetry yields `unverified`, never invented zero errors. Record measured improvements only when a comparable baseline exists.
- Keep execution outcome and recovery origin authoritative outside model-written report text. A model summary must not replace a failed/stale/unknown verification result.

Done when: a control acknowledgement, unknown payment, one transient success, stale telemetry, or wrong action cannot produce verified recovery.

### T07: Cleanup, expiry, and restart reconciliation

Files: controller run/operation/store modules; backend cancel/recover handlers; `backend/app/events.py` integrations.

- Persist each fault's bounded lifetime and pre-fault resource state before injection. Initial maximum lifetime: 15 minutes, visible in the UI and configurable within an operator-defined cap.
- For failed partial injection, reconcile and restore only resources changed by that run. Persist each cleanup attempt/outcome.
- Implement a controller watchdog and startup reconciliation. Controller downtime may delay Docker cleanup; do not promise a cleanup deadline while it is stopped. Use a database-side timeout as an additional bound for held transactions.
- Rejection leaves the incident unrepaired until explicit cleanup or expiry. Cancellation stops analysis and invalidates approvals; cleanup remains a separate recorded action.
- Serialize cleanup and remediation under the same operation lock. Before cleanup, stop/invalidate the investigation's pending execution path.
- If cleanup or an external action restores health during an investigation, mark it interrupted or externally recovered; never count it as successful agent remediation.
- Do not automatically reacquire a database lock or re-break a service after controller restart. Observe, reconcile, and record the actual outcome.

Done when: expired/rejected/cancelled runs are bounded and auditable, failed cleanup retains a needs-cleanup state, and no new lab run starts against an unreconciled environment.

### T08: Redis milestone UI and inspection

Files: `frontend/app/simulate/page.tsx`, `frontend/app/investigations/page.tsx`, `frontend/app/investigation/[id]/{page.tsx,report/page.tsx}`, approval pages, `frontend/lib/{types,api,use-stream}.ts`, relevant components.

- Keep the existing design and routes where practical. The launcher lists only available implemented scenarios with accurate fault/recovery descriptions.
- Add a manual investigation form for services, symptom, and time window. Keep the launcher and manual entry point distinct.
- Display actual resource identity, requested operation, preconditions, expiry, and evidence on approval screens.
- Show operation and verification progress using real events. Tool lifecycle events must be emitted at actual execution boundaries; do not label a post-run audit replay as live tool execution.
- Distinguish model availability from a merely configured API key, and active stream connection from static decorative status.
- Show separate fault injection, agent remediation, and cleanup audit sections. Ground truth can be reviewed by the operator without being put into agent context.
- Render historical version-2 records accurately and make their old approvals non-executable.

Done when: a recruiter can start either workflow, inspect evidence/approvals, and distinguish a successful repair from rejection, failure, expiry, and cleanup using the UI and Network responses.

### T09: Real database blocking scenario

New files: controller `postgres_ops.py`; an idempotent PostgreSQL role/bootstrap script.
Existing files: `sample-apps/app.py`, `postgres/init.sql`, backend tools/action models, controller configuration/tests.

- Remove `slow_db`, `pg_sleep` injection, and the corresponding sample-app route.
- Use a dedicated lab session to begin a transaction and acquire `ACCESS EXCLUSIVE` on `users`; hold the transaction open with a deadline. An ordinary row lock will NOT block the current plain SELECT.
- Configure bounded application query/pool timeouts, and record actual wait duration and failures in `finally` paths. Do not require the controller's lock connection to use the blocked application pool.
- Introduce separate application, observation, and controller database roles. Scope observation to this lab database and session termination to approved lab resources. Existing application superuser credentials must not become the agent's tool credentials.
- Provision roles on existing volumes using an explicit idempotent bootstrap step; editing `init.sql` alone only initializes new volumes. Do not delete the user's database volume.
- Add a fixed-query tool over `pg_stat_activity`, `pg_locks`, and `pg_blocking_pids`; capture the actual blocking relationship and stable session identity.
- Execute `terminate_blocking_session` only after rechecking database, PID, backend start time, permitted role/resource scope, and the current blocking relationship. Do not look up the correct PID from injection ground truth.
- Terminate the session when necessary to end its transaction; cancelling a query is not sufficient for an idle transaction retaining locks.

Done when: the application SELECT actually blocks, the model can cite observed blocking evidence, PID reuse is rejected, and approval restores query behavior through an actual database operation.

### T10: Actual release regression and rollback

New files: `sample-apps/releases/v1/products.py`, `sample-apps/releases/v2/products.py`, `scripts/build-lab-releases.sh`.
Existing files: sample Dockerfile/app, controller Docker/release handlers, Compose, backend tools/action models.

- Extract only the product handler logic needed for two builds. Build-time selection copies one implementation to a common module; there must be no runtime `version == v2` fault branch.
- Use an actual deterministic regression in v2, such as reading a nonexistent field from a product record. Its real exception and request failure are the evidence; do not handcraft a fake stack trace.
- Build both images ahead of a run and resolve their immutable image IDs. Missing images make the scenario unavailable; the controller does not build arbitrary code or pull model-specified images.
- Regression injection recreates only the sample API from the fixed template using the second image. Record actual previous/current identity and release timestamps in ordinary deployment history.
- Preserve the service DNS alias, telemetry labels, dependency settings, and readiness behavior across recreation. Redis, PostgreSQL, Loki, Mongo, and payment containers are untouched.
- Liveness may remain healthy while the product endpoint fails; distinguish process readiness from business-operation health. Confirm requests reached the new image before acknowledging injection.
- Rollback uses the approved observed previous image ID. Journal stop/remove/create/start phases so interrupted replacements can be reconciled without guessing.
- Controller private cleanup state preserves the original template/image even if the API container is absent. No operation may remove data volumes.

Done when: image IDs genuinely change, the new code produces actual request failures, and approved rollback restores the observed previous image and verified application behavior.

### T11: End-to-end evidence and regression matrix

New files: `backend/tests/integration/`, controller tests, `scripts/verify-real-lab.*` as appropriate.
Existing files: all affected tests, `Makefile`, `pytest.ini`, frontend tests.

- Separate fast unit/contract tests, real-infrastructure tests with test-only model doubles, and opt-in real-Groq acceptance runs. Label these distinctly in results.
- Run real-infrastructure tests under a unique Compose project with separate ports/volumes. First assert all resources belong to that project. Never execute destructive test cleanup against the user's active stack.
- A test-only model double is acceptable for approval/execution failure cases. No runtime import or fallback may reference it.
- In real-Groq tests assert supported diagnoses, valid citations/targets, and grounded outcomes, not exact wording. Record failures instead of rerunning selectively to report only success.
- For every scenario test approved success, rejection, stale approval, wrong-but-permitted action, missing evidence, provider failure, cancellation/expiry, and controller restart as applicable.
- Add one externally introduced Redis incident: stop the disposable project's Redis outside the launcher and start `POST /investigations`. It must work without a fault record.
- Add a healthy investigation: populated healthy evidence permits `no_incident_observed` with no proposed action. Empty/unavailable evidence cannot count as healthy.
- Assert injection records/answer-key text are absent from every model input and tool result. Preserve ordinary release events and genuine runtime errors.
- Add fault-before-acknowledgement, crash-after-mutation, duplicate approval, concurrent launcher, database PID reuse, absent-container rollback, and cleanup-during-verification cases.
- Use browser automation to test launcher/manual flow, approvals, failure states, and audit inspection on desktop/mobile. Check no overlap, exposed credentials, or misleading live indicators.

Done when: each layer's results identify what was real, what was doubled, what failed, and what remains untested. At least one completed real-Groq approved run per implemented scenario is required for release acceptance.

### T12: Remove obsolete behavior and update documentation

Files: `README.md`, `.env.example`, `RESOURCES.md`, relevant `reference/` pages, `Makefile`, old adapters/tests.

- Delete obsolete sample simulation routes/state and unsupported action enums once all callers have migrated. Search runtime code for `redis_failure`, `slow_db`, `restore_sample_v1`, `clear_redis_fault`, and `clear_database_delay`.
- Historical readers and explicitly named test fixtures may retain old field names; do not rewrite history to pass a search check.
- Document build/bootstrap/start/cleanup procedures, controller privilege boundaries, fixture business data, verification thresholds, API changes, and the fact that workloads and incident selection are controlled.
- Explain that operation success, application recovery, and model confidence are different concepts. Do not claim a generic production SRE agent or certified root cause.
- Correct repository descriptions that still imply all work is flag-based or that provider errors produce usable fallback findings.
- Record verification artifacts with secret redaction and observation/model provenance. Do not commit credentials or publish local operational records automatically.

Done when: documented behavior matches an inspected real run and no public workflow silently falls back to the old simulation.

## Dependency Order and Milestones

| Milestone | Tasks | Completion gate |
| --- | --- | --- |
| Contracts and boundaries | T00 -> T01 -> T02 -> T03 -> T04 | Manual investigations and approved controller operations have tested contracts. |
| Redis, complete user workflow | T05 + T06 + T07 -> T08 | Real Redis outage, real Groq diagnosis, approval, actual start, verified recovery, audited cleanup. |
| Database | T09, reuse T06-T08 | Actual query blocking and approved session termination pass verification. |
| Releases | T10, reuse T06-T08 | Distinct deployed image and approved rollback pass verification. |
| Final acceptance | T11 -> T12 | All scenarios, failure paths, browser checks, and docs match the implementation. |

Run focused tests at each task, not only in T11. Land complete behavior per milestone; do not treat an endpoint rename, hidden audit field, or an LLM-written description as completion.

## Verification Commands to Establish

Retain `make test-backend`, `make test-frontend`, and `make test`. Add documented targets for controller tests, isolated infrastructure tests, real-Groq acceptance, image preparation, and role bootstrap. Opt-in suites must fail clearly when prerequisites are absent; never silently substitute fixtures.

Before finishing implementation:

- Run affected backend/controller/frontend suites and the frontend production build.
- Validate Compose configuration and isolated bootstrap without printing resolved secrets.
- Execute the scenario matrix and record passed/failed/skipped results separately.
- Inspect the browser's actual API and SSE payloads from a completed real run.
- Report changed files, implementation limits, tests run, and any unresolved acceptance failures. Do not commit, push, or deploy automatically.

## Technical References

- PostgreSQL 16 locking: https://www.postgresql.org/docs/16/explicit-locking.html
- PostgreSQL 16 session control: https://www.postgresql.org/docs/16/functions-admin.html
- Docker daemon security: https://docs.docker.com/engine/security/

These references support the lock/session-control and daemon-privilege choices. Verify exact SDK/API compatibility against the installed versions during implementation.
