"use client";

import {useState} from "react";
import {useParams} from "next/navigation";
import {PageHeader} from "@/components/page-header";
import {Badge} from "@/components/ui/badge";
import {Panel} from "@/components/ui/panel";
import {Skeleton} from "@/components/ui/skeleton";
import {formatScenario, formatTime, shortId, useInvestigation} from "@/lib/api";

export default function ReportPage() {
  const {id} = useParams<{id: string}>();
  const {data, error, isLoading} = useInvestigation(id);
  const [tab, setTab] = useState<"report" | "evidence">("report");
  if (isLoading) return <Panel><Skeleton rows={7} /></Panel>;
  if (error || !data) return <p className="error-message" role="alert">Could not load report.</p>;
  const report = data.report_json;
  if (!report.summary) return <p className="error-message">The report is not ready. Return to the investigation while the agents finish.</p>;
  return <>
    <PageHeader title={`Report · ${shortId(id)}`} description={`${formatScenario(data.scenario)} investigation completed ${formatTime(data.completed_at)}.`} actions={<Badge status={data.status} />} />
    {data.evidence_version === 2 && <p className="notice">Historical report produced by the previous application-control workflow.</p>}
    {data.evidence_version !== 2 && data.evidence_version !== 3 && <p className="error-message" role="alert">Legacy report: findings may include scripted analysis or synthetic telemetry.</p>}
    {data.status === "remediation_failed" && <p className="error-message" role="alert">Recovery was not verified. Check the execution observations in Raw evidence.</p>}
    <div className="tabs" role="tablist" aria-label="Report views"><button className={`tab ${tab === "report" ? "is-active" : ""}`} role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>Report</button><button className={`tab ${tab === "evidence" ? "is-active" : ""}`} role="tab" aria-selected={tab === "evidence"} onClick={() => setTab("evidence")}>Raw evidence</button></div>
    {tab === "report" ? <><Panel className="report-section"><h2>Summary</h2><p>{report.summary}</p><div className="affected-list">{report.affected_services?.map((service) => <Badge status="completed" key={service}>{service}</Badge>)}</div>{data.recovery_origin && <p className="subtle">Recovery origin: {data.recovery_origin.replaceAll("_", " ")}</p>}</Panel><Panel className="report-section"><h2>Root cause</h2><p>{report.root_cause}</p></Panel><Panel className="report-section"><h2>Recommendation</h2><p>{report.recommendation}</p></Panel><div className="section-title"><h2>Timeline</h2></div><Panel className="report-section"><ol className="timeline">{report.timeline?.map((event, index) => <li key={index}><time>{formatTime(event.time)}</time><span>{event.event}</span></li>)}</ol></Panel></> : <Panel><pre className="raw-evidence">{JSON.stringify(report.evidence, null, 2)}</pre></Panel>}
  </>;
}
