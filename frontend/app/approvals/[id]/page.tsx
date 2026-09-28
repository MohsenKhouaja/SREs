"use client";

import Link from "next/link";
import {useParams, useRouter} from "next/navigation";
import {useEffect, useState} from "react";
import {Check, X} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Panel} from "@/components/ui/panel";
import {Skeleton} from "@/components/ui/skeleton";
import {apiFetch, formatTime, useApproval} from "@/lib/api";
import type {Finding} from "@/lib/types";
import {isApprovalOpen} from "@/lib/investigation-state";

function evidenceGroups(evidence: Record<string, unknown>): Array<[string, Finding[]]> {
  return ["logs", "metrics", "events", "hypotheses"].flatMap((key) => {
    const value = evidence[key];
    return Array.isArray(value) ? [[key, value as Finding[]] as [string, Finding[]]] : [];
  });
}

export default function ApprovalPage() {
  const {id} = useParams<{id: string}>();
  const router = useRouter();
  const {data, error, isLoading, mutate} = useApproval(id);
  const [deciding, setDeciding] = useState<"approve" | "reject">();
  const [message, setMessage] = useState("");
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (data?.status !== "pending") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [data?.status]);

  async function decide(decision: "approve" | "reject") {
    if (!data || !isApprovalOpen(data)) return;
    setDeciding(decision); setMessage("");
    try {
      await apiFetch(`/investigation/${data.investigation_id}/approval/${data.approval_id}`, {method: "POST", body: JSON.stringify({decision})});
      setMessage(decision === "approve" ? "Action approved. The agent is resuming from its checkpoint…" : "Action rejected. The investigation will close without remediation.");
      await new Promise((resolve) => setTimeout(resolve, 800));
      await mutate();
      setTimeout(() => router.push(`/investigation/${data.investigation_id}`), 900);
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : "Decision failed"); setDeciding(undefined); }
  }

  if (isLoading) return <Panel><Skeleton rows={7} /></Panel>;
  if (error || !data) return <p className="error-message" role="alert">Could not load approval request.</p>;
  const groups = evidenceGroups(data.evidence);
  const open = isApprovalOpen(data, now);
  const expired = data.status === "expired" || (data.status === "pending" && !open);
  return <>
    <PageHeader title={`Approval request · ${data.action_type.replaceAll("_", " ")}`} description={open ? "A human decision is required before the workflow can continue." : "This operation request is closed."} actions={<Badge status={expired ? "expired" : data.status} />} />
    {data.evidence_version !== 3 && <p className="error-message" role="alert">Historical approval: this action cannot execute through the infrastructure controller.</p>}
    {expired && <p className="notice" role="status">Approval expired. No operation can be executed from this request.</p>}
    {data.description && <p>{data.description}</p>}
    <div className="approval-hero"><div className="approval-field"><span>Action</span><strong>{data.action_type.replaceAll("_", " ")}</strong></div><div className="approval-field"><span>Target</span><strong className="mono">{data.target}</strong></div><div className="approval-field"><span>Proposed by</span><strong>{data.proposed_by} agent · {formatTime(data.proposed_at)}</strong></div></div>
    <Panel className="approval-reason"><h2>Why this action is proposed</h2><p>{data.reason}</p></Panel>
    {data.parameters && <Panel className="approval-reason"><h2>Frozen operation parameters</h2><pre className="raw-evidence">{JSON.stringify(data.parameters, null, 2)}</pre>{data.expires_at && <p>{open ? "Approval expires" : "Approval window closed"} {formatTime(data.expires_at)}.</p>}</Panel>}
    {(data.supporting_finding_ids?.length || data.supporting_observation_ids?.length) && <Panel className="approval-reason"><h2>Provenance references</h2><pre className="raw-evidence">{JSON.stringify({finding_ids: data.supporting_finding_ids ?? [], observation_ids: data.supporting_observation_ids ?? []}, null, 2)}</pre></Panel>}
    <div className="section-title"><h2>Evidence chain</h2><p>Read-only inputs used by the correlation agent</p></div>
    <div className="evidence-columns">{groups.map(([name, findings]) => <section className="evidence-column" key={name}><h3>{name}</h3><ul>{findings.length ? findings.map((finding, index) => <li key={index}>{typeof finding === "object" && "message" in finding ? finding.message : JSON.stringify(finding)}</li>) : <li>No evidence captured.</li>}</ul></section>)}</div>
    <div className="decision-bar"><p aria-live="polite">{message || (open ? "Approval executes exactly these frozen parameters, then verifies application behavior. Rejection performs no action." : "This approval window is closed.")}</p>{open && data.evidence_version === 3 ? <div className="decision-actions"><Button variant="danger" disabled={!!deciding} onClick={() => decide("reject")}><X size={16} aria-hidden="true" />{deciding === "reject" ? "Rejecting…" : "Reject"}</Button><Button variant="primary" disabled={!!deciding} onClick={() => decide("approve")}><Check size={16} aria-hidden="true" />{deciding === "approve" ? "Approving…" : "Approve operation"}</Button></div> : <Link className="button button-primary" href={`/investigation/${data.investigation_id}`}>Return to investigation</Link>}</div>
  </>;
}
