"use client";

import Link from "next/link";
import {Plus} from "lucide-react";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";
import {Skeleton} from "@/components/ui/skeleton";
import {PageHeader} from "@/components/page-header";
import {duration, formatScenario, formatTime, shortId, useInvestigations} from "@/lib/api";

export default function InvestigationsPage() {
  const {data, error, isLoading} = useInvestigations();

  return <>
    <PageHeader title="Investigations" description="Trace every simulated incident from first signal through evidence, approval, and final report." actions={<Link className="button button-primary" href="/simulate"><Plus size={16} aria-hidden="true" />New investigation</Link>} />
    {error && <p className="error-message" role="alert">Could not load investigations: {error.message}</p>}
    {isLoading && <div className="panel"><Skeleton rows={5} /></div>}
    {!isLoading && !data?.investigations.length && <Empty title="No investigations yet" action={<Link className="button button-primary" href="/simulate">Choose a simulation</Link>}>Trigger a controlled failure to watch the five agents collect and correlate live evidence.</Empty>}
    {!!data?.investigations.length && <div className="data-table-wrap"><table className="data-table"><thead><tr><th scope="col">Investigation</th><th scope="col">Scenario</th><th scope="col">Status</th><th scope="col">Started</th><th scope="col">Duration</th></tr></thead><tbody>{data.investigations.map((item) => <tr key={item.investigation_id}><td><Link className="table-link mono" href={`/investigation/${item.investigation_id}`}>{shortId(item.investigation_id)}</Link></td><td>{formatScenario(item.scenario)}</td><td><Badge status={item.status} /></td><td className="subtle">{formatTime(item.created_at)}</td><td className="subtle mono">{duration(item.created_at, item.completed_at)}</td></tr>)}</tbody></table></div>}
  </>;
}
