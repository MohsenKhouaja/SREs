# SREs Resources

## Knowledge

- [Executable workflow specification: `backend/tests/test_workflow.py`](backend/tests/test_workflow.py)
  The shortest trustworthy statement of SREs's central promise: fan out, pause for approval, resume, and finish safely. Use first when checking the intended lifecycle.
- [Workflow implementation: `backend/app/workflow.py`](backend/app/workflow.py)
  Defines graph nodes and edges, evidence collection, approval interruption, model-proposed remediation, recovery verification, and reporting. Use for all orchestration claims.
- [Shared state contract: `backend/app/models.py`](backend/app/models.py)
  Defines the data carried through an investigation and the reducers that preserve parallel findings. Use when tracing which node reads or writes a field.
- [HTTP and streaming boundary: `backend/app/main.py`](backend/app/main.py)
  Creates the application, chooses persistence and checkpoint implementations, exposes routes, and turns event-hub messages into SSE. Use for request-lifecycle questions.
- [Evidence and reporting tools: `backend/app/tools.py`](backend/app/tools.py)
  Contains the Loki and Prometheus queries plus evidence-processing utilities. Use to trace each observation back to a live telemetry response.
- [Persistence adapters: `backend/app/store.py`](backend/app/store.py)
  Shows the common Store contract and its in-memory and MongoDB implementations. Use for durable-record and test-isolation questions.
- [Live event fan-out: `backend/app/events.py`](backend/app/events.py)
  Implements per-investigation event history and subscriber queues. Use for SSE behavior and durability trade-offs.
- [Controlled system under investigation: `sample-apps/app.py`](sample-apps/app.py)
  Implements the two sample services, real dependency calls, a real HTTP workload, logs, and request metrics. The distinct product handlers in `sample-apps/releases/` are built into separate release images.
- [Private operation boundary: `lab-controller/app/`](lab-controller/app/)
  Owns allowlisted Docker and PostgreSQL mutations, lab leases, operation journals, cleanup, and expiry. Use to distinguish observed infrastructure changes from model analysis.
- [Browser integration: `frontend/app/lab/page.tsx`](frontend/app/lab/page.tsx), [`frontend/app/investigation/[id]/page.tsx`](frontend/app/investigation/%5Bid%5D/page.tsx), and [`frontend/app/approvals/[id]/page.tsx`](frontend/app/approvals/%5Bid%5D/page.tsx)
  These three screens expose the operator's complete path. Use for UI-to-API and approval-flow questions.
- [Runtime topology: `docker-compose.yml`](docker-compose.yml)
  Wires the application, observability stack, sample services, role bootstrap, and private controller. Use for deployment-topology and privilege-boundary questions.
- [Runtime configuration: `backend/app/config.py`](backend/app/config.py), [`prometheus/prometheus.yml`](prometheus/prometheus.yml), and [`loki/loki-config.yml`](loki/loki-config.yml)
  Defines environment-driven addresses and the local observability behavior. Use for configuration and container-network questions.
- [Product and interface intent: `PRODUCT.md`](PRODUCT.md) and [`DESIGN.md`](DESIGN.md)
  State the target operator, decision-centered information hierarchy, accessibility promise, and visual constraints. Use to connect frontend implementation choices to product reasoning.
- [Repository-wide test suite: `backend/tests/`](backend/tests/) and [`frontend/tests/components.test.tsx`](frontend/tests/components.test.tsx)
  Executable evidence for what the project currently guarantees—and, equally importantly, what it does not test.
- [Project language: `CONTEXT.md`](CONTEXT.md)
  Defines the precise domain terms used by the product. Use to keep interview answers consistent with the codebase.

## Wisdom (Communities)

- No community resource selected yet.
  The current goal is repository mastery. Add a high-signal interview or agent-engineering community only when external critique would advance that goal.

## Gaps

- The repository has no production incident history, scale measurements, or architecture decision records, so production-scale claims must be presented as proposals rather than facts.
- The code and tests define intended behavior, but issue or pull-request history is not available here to explain why every trade-off was originally chosen.
