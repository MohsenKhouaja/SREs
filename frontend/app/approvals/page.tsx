"use client";

import Link from "next/link";
import {PageHeader} from "@/components/page-header";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";
import {Skeleton} from "@/components/ui/skeleton";
import {formatTime, shortId, useApprovals} from "@/lib/api";

export default function ApprovalsPage() {
  const {data, error, isLoading} = useApprovals();
  return <>
    <PageHeader title="Approvals" description="Review the full evidence chain before authorizing any operational remediation." />
    {error && <p className="error-message" role="alert">Could not load approvals: {error.message}</p>}
    {isLoading && <div className="panel"><Skeleton rows={5} /></div>}
    {!isLoading && !data?.approvals.length && <Empty title="No approval requests">Approvals appear here when the correlation agent proposes a dangerous remediation.</Empty>}
    {!!data?.approvals.length && <div className="data-table-wrap"><table className="data-table"><thead><tr><th scope="col">Action</th><th scope="col">Target</th><th scope="col">Investigation</th><th scope="col">Proposed</th><th scope="col">Status</th></tr></thead><tbody>{data.approvals.map((approval) => <tr key={approval.approval_id}><td><Link className="table-link" href={`/approvals/${approval.approval_id}`}>{approval.action_type.replaceAll("_", " ")}</Link></td><td className="mono">{approval.target}</td><td><Link className="mono subtle" href={`/investigation/${approval.investigation_id}`}>{shortId(approval.investigation_id)}</Link></td><td className="subtle">{formatTime(approval.proposed_at)}</td><td><Badge status={approval.status} /></td></tr>)}</tbody></table></div>}
  </>;
}
