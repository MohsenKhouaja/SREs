# Incident Response

This context describes the language used by the system that investigates real, bounded failures in its local incident lab and requests human authorization for remediation.

## Language

**Incident**:
An observable production disruption that requires investigation.
_Avoid_: Alert, problem, ticket

**Scenario**:
A controlled infrastructure failure used to create an Incident: Redis Unavailable, Database Blocking, or Release Regression.
_Avoid_: Test case, incident type

**Investigation**:
One traceable run in which specialist Agents collect Evidence, correlate it, and produce a Report.
_Avoid_: Job, workflow, session

**Agent**:
One specialist participant in an Investigation: Log, Metrics, Event, Correlation, or Report.
_Avoid_: Bot, worker

**Finding**:
A timestamped observation produced by one Agent from an identifiable source.
_Avoid_: Result, fact

**Evidence**:
The complete set of Findings used to support a Root Cause and a proposed Remediation.
_Avoid_: Data, context

**Root Cause**:
The failure that best explains the collected Evidence for an Incident.
_Avoid_: Diagnosis, hypothesis

**Remediation**:
A potentially dangerous operational action proposed to recover an affected service.
_Avoid_: Fix, command

**Approval**:
The explicit human decision that either authorizes or rejects one Remediation.
_Avoid_: Confirmation, consent

**Report**:
The final, durable account of an Investigation, including Root Cause, Evidence, recommendation, affected services, and timeline.
_Avoid_: Summary, output
