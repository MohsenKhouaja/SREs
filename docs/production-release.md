# Production Release

The live site is `https://trysres.xyz`. Dokploy deploys the `production` branch
using `docker-compose.production.yml`; GitHub Actions validates that branch and
then checks the public site. A push to `main` does not deploy the site.

Before deploying the real-incident release, configure two different randomly
generated secrets in the existing Dokploy application's environment:

- `LAB_MONITOR_TOKEN`: private controller observation credential.
- `LAB_OPERATOR_TOKEN`: private controller mutation credential.

Retain the existing Groq, authenticated MongoDB, and PostgreSQL environment
values, including the existing `POSTGRES_DB`. The migration runs
against existing volumes and grants the sample application and lab controller
their restricted database roles.

The stack builds both `sres-trysres-sample-api:v1` and
`sres-trysres-sample-api:v2`. The v2 preparation service exits without serving
traffic; the controller swaps the sample API container only during an explicit
release incident. The controller selects only Redis and the sample API within
Compose project `sres-trysres`. Its HTTP port is private and its replacement
sample API containers do not publish host ports.

This is a publicly hosted incident lab. The controller requires access to the
Docker socket; deploy it on the disposable lab host. Existing persistent
investigation data is preserved, including explicitly labeled historical records.

After deployment, `scripts/smoke-production.sh` checks the site, backend health,
controller and dependency readiness, Groq configuration, lab page, and www
redirect. The smoke check does not inject faults or consume Groq tokens.

## Approval Lifecycle

The backend reconciles approval deadlines at startup and every five seconds.
Expired approvals close through the LLM report path without executing the
proposed operation. The outcome is `completed_with_expired_approval`; a closed
lab run can instead produce `completed_with_invalidated_approval`. A reporting
failure remains an explicit failure, never a generated fallback report.

The lab controller's automatic cleanup is independent of approval expiry. Its
audit is recorded as `automatic_cleanup`, not successful agent remediation.
Backend restarts preserve interrupted approval checkpoints; interrupted active
execution is marked failed rather than replaying infrastructure operations.
