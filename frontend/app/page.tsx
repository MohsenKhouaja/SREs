"use client";

import Link from "next/link";
import {Plus} from "lucide-react";
import {useEffect, useState} from "react";
import {Badge} from "@/components/ui/badge";
import {Empty} from "@/components/ui/empty";
import {Skeleton} from "@/components/ui/skeleton";
import {PageHeader} from "@/components/page-header";
import {PrototypeSwitcher} from "@/components/prototype-switcher";
import {EvidenceDesk, FocusedBriefing, JournalIndex} from "@/app/_prototype/investigations";
import {duration, formatScenario, formatTime, shortId, useInvestigations} from "@/lib/api";
import type {Investigation} from "@/lib/types";

const variants = [
  {key: "A", name: "Journal index"},
  {key: "B", name: "Focused briefing"},
  {key: "C", name: "Evidence desk"},
];

const now = Date.now();
const sampleInvestigations: Investigation[] = [
  {investigation_id: "8a72cc91-preview", incident_id: "inc-1402", scenario: "checkout-latency", status: "investigating", created_at: new Date(now - 8 * 60_000).toISOString(), updated_at: new Date(now).toISOString(), completed_at: null, report_json: {}, report_markdown: ""},
  {investigation_id: "c91d2b38-preview", incident_id: "inc-1398", scenario: "database-connection-exhaustion", status: "awaiting_approval", created_at: new Date(now - 42 * 60_000).toISOString(), updated_at: new Date(now).toISOString(), completed_at: null, report_json: {}, report_markdown: ""},
  {investigation_id: "f440b861-preview", incident_id: "inc-1381", scenario: "payment-service-errors", status: "completed", created_at: new Date(now - 28 * 60 * 60_000).toISOString(), updated_at: new Date(now).toISOString(), completed_at: new Date(now - 27.5 * 60 * 60_000).toISOString(), report_json: {}, report_markdown: ""},
  {investigation_id: "d110e74a-preview", incident_id: "inc-1376", scenario: "inventory-cache-stale", status: "completed_with_rejection", created_at: new Date(now - 52 * 60 * 60_000).toISOString(), updated_at: new Date(now).toISOString(), completed_at: new Date(now - 51.7 * 60 * 60_000).toISOString(), report_json: {}, report_markdown: ""},
];

function CurrentHome() {
  const {data, error, isLoading} = useInvestigations();
  return <>
    <PageHeader title="Investigations" description="Trace every simulated incident from first signal through evidence, approval, and final report." actions={<Link className="button button-primary" href="/simulate"><Plus size={16} aria-hidden="true" />New investigation</Link>} />
    {error && <p className="error-message" role="alert">Could not load investigations: {error.message}</p>}
    {isLoading && <div className="panel"><Skeleton rows={5} /></div>}
    {!isLoading && !data?.investigations.length && <Empty title="No investigations yet" action={<Link className="button button-primary" href="/simulate">Choose a simulation</Link>}>Trigger a controlled failure to watch the five agents collect and correlate live evidence.</Empty>}
    {!!data?.investigations.length && <div className="data-table-wrap"><table className="data-table"><thead><tr><th scope="col">Investigation</th><th scope="col">Scenario</th><th scope="col">Status</th><th scope="col">Started</th><th scope="col">Duration</th></tr></thead><tbody>{data.investigations.map((item) => <tr key={item.investigation_id}><td><Link className="table-link mono" href={`/investigation/${item.investigation_id}`}>{shortId(item.investigation_id)}</Link></td><td>{formatScenario(item.scenario)}</td><td><Badge status={item.status} /></td><td className="subtle">{formatTime(item.created_at)}</td><td className="subtle mono">{duration(item.created_at, item.completed_at)}</td></tr>)}</tbody></table></div>}
  </>;
}

export default function HomePage() {
  const {data, error, isLoading} = useInvestigations();
  const [variant, setVariant] = useState("A");

  useEffect(() => {
    const readVariant = () => {
      const requested = new URL(window.location.href).searchParams.get("variant")?.toUpperCase();
      setVariant(variants.some((item) => item.key === requested) ? requested! : "A");
    };
    readVariant();
    window.addEventListener("popstate", readVariant);
    return () => window.removeEventListener("popstate", readVariant);
  }, []);

  if (process.env.NODE_ENV === "production") return <CurrentHome />;

  const items = data?.investigations.length ? data.investigations : sampleInvestigations;
  const usingSamples = !data?.investigations.length;

  function selectVariant(next: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("variant", next.toLowerCase());
    window.history.replaceState({}, "", url);
    setVariant(next);
  }

  return <>
    {error && <p className="prototype-data-note" role="status">Live API unavailable—showing sample investigations for visual review.</p>}
    {isLoading && <p className="prototype-data-note" role="status">Loading live investigations; sample records are shown meanwhile.</p>}
    {variant === "A" && <JournalIndex items={items} usingSamples={usingSamples} />}
    {variant === "B" && <FocusedBriefing items={items} usingSamples={usingSamples} />}
    {variant === "C" && <EvidenceDesk items={items} usingSamples={usingSamples} />}
    <PrototypeSwitcher variants={variants} current={variant} onSelect={selectVariant} />
  </>;
}
