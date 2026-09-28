"use client";

import Link from "next/link";
import {FormEvent, useState} from "react";
import {useParams} from "next/navigation";
import {AlertTriangle, Bot, FileText, Radio, Send, Square} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Panel} from "@/components/ui/panel";
import {Skeleton} from "@/components/ui/skeleton";
import {apiFetch, formatScenario, shortId, useInvestigation, useLabRun} from "@/lib/api";
import {useInvestigationStream} from "@/lib/use-stream";

const agentOrder = ["log", "metrics", "event", "correlation", "report"];

export default function InvestigationPage() {
  const {id} = useParams<{id: string}>();
  const {data, error, isLoading, mutate} = useInvestigation(id);
  const {data: labRun} = useLabRun(data?.lab_run_id);
  const {events, connected} = useInvestigationStream(id);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [questionError, setQuestionError] = useState("");
  const liveSteps = events.filter((event) => event.type === "agent_step" && event.step);
  const storedSteps = Object.values(data?.agents || {}).flatMap((agent) => agent.steps?.map((step) => ({agent: agent.agent_name, ...step})) || []);
  const steps = liveSteps.length ? liveSteps : storedSteps;
  const pending = data?.approvals?.find((approval) => approval.status === "pending");
  const finished = ["completed", "completed_with_rejection", "no_incident_observed", "inconclusive", "remediation_failed"].includes(data?.status || "");
  const terminal = finished || ["failed", "cancelled"].includes(data?.status || "");

  async function cancel() { await apiFetch(`/investigation/${id}/cancel`, {method: "POST"}); await mutate(); }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setAsking(true); setQuestionError("");
    try {
      await apiFetch(`/investigation/${id}/questions`, {method: "POST", body: JSON.stringify({question: trimmed})});
      setQuestion("");
      await mutate();
    } catch (caught) {
      setQuestionError(caught instanceof Error ? caught.message : "Could not ask Groq");
    } finally { setAsking(false); }
  }

  if (isLoading) return <><PageHeader title="Loading investigation" description="Retrieving agent state and evidence." /><Panel><Skeleton rows={7} /></Panel></>;
  if (error || !data) return <p className="error-message" role="alert">Could not load investigation: {error?.message || "Not found"}</p>;

  return <>
    <PageHeader title={`${formatScenario(data.scenario)} · ${shortId(id)}`} description={data.symptom || "Model analysis of recorded lab observations."} actions={<><Badge status={data.status} />{finished ? <Link href={`/investigation/${id}/report`} className="button button-primary"><FileText size={16} aria-hidden="true" />View report</Link> : !terminal && <Button variant="danger" onClick={cancel}><Square size={14} aria-hidden="true" />Cancel</Button>}</>} />
    {data.evidence_version === 2 && <p className="notice">Historical investigation: this record used application-level lab controls. Its approval cannot execute through the current controller.</p>}
    {data.evidence_version !== 2 && data.evidence_version !== 3 && <p className="error-message" role="alert">Legacy investigation: findings may include scripted analysis or synthetic telemetry.</p>}
    {data.error && <p className="error-message" role="alert">Analysis stopped: {data.error}</p>}
    {data.status === "inconclusive" && <p className="notice">The collected evidence did not support a diagnosis. No remediation was executed.</p>}
    {data.status === "no_incident_observed" && <p className="notice">Populated recent observations did not show a supported incident. No remediation was proposed.</p>}
    {data.status === "remediation_failed" && <p className="error-message" role="alert">Recovery was not verified. Inspect the report for the failed checks.</p>}
    {pending && <div className="notice"><div><strong><AlertTriangle size={16} aria-hidden="true" /> Approval required</strong><span>{pending.action_type.replaceAll("_", " ")} on {pending.target}</span></div><Link href={`/approvals/${pending.approval_id}`} className="button button-primary">Review evidence</Link></div>}
    <div className="agent-rail" aria-label="Agent statuses">{agentOrder.map((agent) => <div className="agent-chip" key={agent}><span>{agent} agent</span><Badge status={data.agents?.[agent]?.status || "waiting"} /></div>)}</div>
    {labRun && <Panel className="audit-agent"><div className="panel-heading"><h2>Lab run audit</h2><Badge status={labRun.status} /></div><div className="approval-hero"><div className="approval-field"><span>Run</span><strong className="mono">{shortId(labRun.run_id)}</strong></div><div className="approval-field"><span>Expires</span><strong>{new Date(labRun.expires_at).toLocaleString()}</strong></div><div className="approval-field"><span>Recovery origin</span><strong>{data.recovery_origin || "None recorded"}</strong></div></div><details className="audit-run"><summary>Injection and cleanup record</summary><pre className="raw-evidence">{JSON.stringify({fault: labRun.fault, cleanup: labRun.cleanup}, null, 2)}</pre></details></Panel>}
    <div className="investigation-grid">
      <Panel className="stream-panel"><div className="panel-heading"><h2>Agent activity</h2><span className={`connection ${connected ? "is-live" : ""}`}><Radio size={13} aria-hidden="true" />{connected ? "Live" : "Reconnecting"}</span></div><div className="step-list" aria-live="polite">{steps.length ? steps.map((event, index) => <div className="step" key={`${event.agent}-${index}`}><span className="step-agent">{event.agent}</span><span className="step-copy">{event.step}</span></div>) : <div className="step-placeholder">Waiting for the first agent event. The simulator warms up telemetry before analysis begins.</div>}</div></Panel>
      <Panel className="findings-panel"><div className="panel-heading"><h2>Current findings</h2><span className="subtle">{Object.values(data.agents || {}).reduce((count, agent) => count + (agent.findings?.length || 0), 0)} captured</span></div>{agentOrder.map((agent) => <section className="finding-group" key={agent}><h3>{agent} agent</h3>{data.agents?.[agent]?.findings?.length ? data.agents[agent].findings.map((finding, index) => <p className="finding-item" id={finding.finding_id ? `finding-${finding.finding_id}` : undefined} key={finding.finding_id || index}>{finding.message}</p>) : <p className="finding-item">No finding yet.</p>}</section>)}</Panel>
    </div>
    <div className="section-title"><h2>Groq audit trail</h2><p>Model inputs, bounded tool calls, and validated outputs</p></div>
    <div className="audit-list">{agentOrder.map((agent) => {
      const runs = data.agents?.[agent]?.llm_runs || [];
      return <Panel className="audit-agent" key={agent}><div className="audit-agent-heading"><div><Bot size={16} aria-hidden="true" /><strong>{agent} agent</strong></div><Badge status={data.agents?.[agent]?.execution_mode || "waiting"} /></div>{runs.length ? runs.map((run) => <details className="audit-run" key={run.run_id}><summary><span>{run.provider} · {run.model}</span><span>{Math.round(run.latency_ms)} ms · {run.usage?.total_tokens || 0} tokens</span></summary><div className="audit-body"><h3>System prompt</h3><pre>{run.input.system_prompt}</pre><h3>User input</h3><pre>{run.input.user_prompt}</pre>{run.tool_calls.length > 0 && <><h3>Tool calls</h3><pre>{JSON.stringify(run.tool_calls, null, 2)}</pre></>}<h3>Validated output</h3><pre>{JSON.stringify(run.output, null, 2)}</pre>{run.error && <p className="audit-error">{run.error}</p>}</div></details>) : <p className="audit-empty">No model run yet.</p>}</Panel>;
    })}</div>
    <div className="section-title"><h2>Ask about this investigation</h2><p>Answers use only the evidence above</p></div>
    <Panel className="question-panel">
      <form className="question-form" onSubmit={ask}><label className="sr-only" htmlFor="investigation-question">Question</label><input className="input" id="investigation-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What evidence supports the proposed root cause?" disabled={asking} /><Button variant="primary" type="submit" disabled={asking || !question.trim() || Object.values(data.agents || {}).every((agent) => !agent.findings?.length)}><Send size={15} aria-hidden="true" />{asking ? "Asking Groq…" : "Ask Groq"}</Button></form>
      {questionError && <p className="error-message" role="alert">{questionError}</p>}
      <div className="question-history">{data.questions?.length ? data.questions.map((item) => <article className="question-answer" key={item.question_id}><p className="question-copy">{item.question}</p><p>{item.answer}</p><footer><span>Groq · {item.llm_run.model}</span>{item.citations.map((citation) => <a key={citation} href={`#finding-${citation}`}>Evidence {citation.slice(0, 8)}</a>)}</footer></article>) : <p className="audit-empty">Questions and cited answers will appear here.</p>}</div>
    </Panel>
  </>;
}
