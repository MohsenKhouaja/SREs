"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {AlertTriangle, FileText, Radio, Square} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Panel} from "@/components/ui/panel";
import {Skeleton} from "@/components/ui/skeleton";
import {apiFetch, formatScenario, shortId, useInvestigation} from "@/lib/api";
import {useInvestigationStream} from "@/lib/use-stream";

const agentOrder = ["log", "metrics", "event", "correlation", "report"];

export default function InvestigationPage() {
  const {id} = useParams<{id: string}>();
  const {data, error, isLoading, mutate} = useInvestigation(id);
  const {events, connected} = useInvestigationStream(id);
  const steps = events.filter((event) => event.type === "agent_step" && event.step);
  const pending = data?.approvals?.find((approval) => approval.status === "pending");
  const finished = data?.status === "completed" || data?.status === "completed_with_rejection";

  async function cancel() { await apiFetch(`/investigation/${id}/cancel`, {method: "POST"}); await mutate(); }

  if (isLoading) return <><PageHeader title="Loading investigation" description="Retrieving agent state and evidence." /><Panel><Skeleton rows={7} /></Panel></>;
  if (error || !data) return <p className="error-message" role="alert">Could not load investigation: {error?.message || "Not found"}</p>;

  return <>
    <PageHeader title={`${formatScenario(data.scenario)} · ${shortId(id)}`} description="Live specialist analysis with a durable evidence chain." actions={<><Badge status={data.status} />{finished ? <Link href={`/investigation/${id}/report`} className="button button-primary"><FileText size={16} aria-hidden="true" />View report</Link> : <Button variant="danger" onClick={cancel}><Square size={14} aria-hidden="true" />Cancel</Button>}</>} />
    {pending && <div className="notice"><div><strong><AlertTriangle size={16} aria-hidden="true" /> Approval required</strong><span>{pending.action_type.replaceAll("_", " ")} on {pending.target}</span></div><Link href={`/approvals/${pending.approval_id}`} className="button button-primary">Review evidence</Link></div>}
    <div className="agent-rail" aria-label="Agent statuses">{agentOrder.map((agent) => <div className="agent-chip" key={agent}><span>{agent} agent</span><Badge status={data.agents?.[agent]?.status || "waiting"} /></div>)}</div>
    <div className="investigation-grid">
      <Panel className="stream-panel"><div className="panel-heading"><h2>Agent activity</h2><span className={`connection ${connected ? "is-live" : ""}`}><Radio size={13} aria-hidden="true" />{connected ? "Live" : "Reconnecting"}</span></div><div className="step-list" aria-live="polite">{steps.length ? steps.map((event, index) => <div className="step" key={`${event.agent}-${index}`}><span className="step-agent">{event.agent}</span><span className="step-copy">{event.step}</span></div>) : <div className="step-placeholder">Waiting for the first agent event. The simulator warms up telemetry before analysis begins.</div>}</div></Panel>
      <Panel className="findings-panel"><div className="panel-heading"><h2>Current findings</h2><span className="subtle">{Object.values(data.agents || {}).reduce((count, agent) => count + (agent.findings?.length || 0), 0)} captured</span></div>{agentOrder.map((agent) => <section className="finding-group" key={agent}><h3>{agent} agent</h3>{data.agents?.[agent]?.findings?.length ? data.agents[agent].findings.map((finding, index) => <p className="finding-item" key={index}>{finding.message}</p>) : <p className="finding-item">No finding yet.</p>}</section>)}</Panel>
    </div>
  </>;
}
