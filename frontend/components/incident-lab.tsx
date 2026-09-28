"use client";

import {FormEvent, useState} from "react";
import {useRouter} from "next/navigation";
import useSWR from "swr";
import {CircleOff, Database, GitBranch, RotateCcw, ServerCrash} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Button} from "@/components/ui/button";
import {apiFetch} from "@/lib/api";

const scenarios = [
  {id: "redis-unavailable", title: "Redis outage", service: "Cache dependency", description: "Stop the lab Redis container.", impact: "Dependent applications make real Redis calls. An approved action starts the same observed container.", icon: ServerCrash},
  {id: "database-blocking", title: "Database blocker", service: "PostgreSQL query path", description: "Hold an exclusive lock on the users table.", impact: "Application queries wait on a real PostgreSQL session. Recovery terminates the observed blocker.", icon: Database},
  {id: "release-regression", title: "Release regression", service: "Sample API image", description: "Replace the API with a prepared image containing a product-handler defect.", impact: "The image identity changes. Recovery deploys the previously observed image.", icon: GitBranch},
];

export function IncidentLab() {
  const router = useRouter();
  const [active, setActive] = useState<string>();
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState("");
  const [symptom, setSymptom] = useState("Product requests are returning unexpected errors.");
  const [servicesSelected, setServicesSelected] = useState(["api-server"]);
  const {data: services, error: healthError, mutate} = useSWR<Record<string, string>>("/system/status", (path: string) => apiFetch(path), {refreshInterval: 8000});

  async function trigger(scenario: string) {
    setActive(scenario); setError(""); setRecovery("");
    try {
      const result = await apiFetch<{investigation_id: string}>("/lab/runs", {method: "POST", body: JSON.stringify({scenario, auto_start_investigation: true, ttl_seconds: 900})});
      router.push(`/investigation/${result.investigation_id}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start lab run"); setActive(undefined); }
  }

  async function investigate(event: FormEvent) {
    event.preventDefault();
    setActive("manual"); setError(""); setRecovery("");
    try {
      const result = await apiFetch<{investigation_id: string}>("/investigations", {method: "POST", body: JSON.stringify({services: servicesSelected, symptom, auto_start_investigation: true})});
      router.push(`/investigation/${result.investigation_id}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start investigation"); setActive(undefined); }
  }

  async function recover() {
    setActive("recover"); setError(""); setRecovery("");
    try { await apiFetch("/system/recover", {method: "POST"}); setRecovery("Known lab runs reconciled. Review each run audit for its cleanup result."); await mutate(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Recovery failed"); } finally { setActive(undefined); }
  }

  return <>
    <PageHeader title="Incident lab" description="Investigate existing symptoms or introduce one bounded infrastructure failure." actions={<Button onClick={recover} disabled={!!active}><RotateCcw size={16} aria-hidden="true" />{active === "recover" ? "Reconciling…" : "Reconcile lab"}</Button>} />
    {error && <p className="error-message" role="alert">{error}</p>}
    {recovery && <p role="status">{recovery}</p>}
    {services?.llm === "not_configured" && <p className="error-message" role="alert">Model analysis is unavailable. Configure Groq on the server before starting a run.</p>}
    <form className="manual-investigation" onSubmit={investigate}>
      <div><h2>Investigate observed behavior</h2><p>Start the same evidence workflow without introducing a fault.</p></div>
      <label>Services<select className="input" value={servicesSelected.join(",")} onChange={(event) => setServicesSelected(event.target.value.split(","))}><option value="api-server">API server</option><option value="payment-service">Payment service</option><option value="api-server,payment-service">Both services</option></select></label>
      <label>Observed symptom<input className="input" value={symptom} onChange={(event) => setSymptom(event.target.value)} minLength={3} maxLength={500} required /></label>
      <Button variant="primary" type="submit" disabled={!!active || !symptom.trim()}>{active === "manual" ? "Starting…" : "Investigate"}</Button>
    </form>
    <p>The workload sends real HTTP requests. Agents receive logs, metrics, runtime state, database activity, and release history; the injection record is kept outside model context.</p>
    <div className="scenario-list">{scenarios.map(({id, title, service, description, impact, icon: Icon}) => <section className="scenario-row" key={id}><div className="scenario-icon"><Icon size={20} aria-hidden="true" /></div><div className="scenario-copy"><h2>{title}</h2><span>{service} · {description}</span></div><p className="scenario-impact">{impact}</p><Button variant="primary" disabled={!!active} onClick={() => trigger(id)}>{active === id ? "Starting…" : "Trigger"}</Button></section>)}</div>
    <div className="section-title"><h2>Environment health</h2><p>Updated every eight seconds</p></div>
    {healthError && <p className="error-message" role="alert">Could not check environment health.</p>}
    <div className="service-grid">{services ? Object.entries(services).map(([name, status]) => <div className="service-status" key={name}>{status === "healthy" ? <span className="live-pulse" aria-hidden="true" /> : <CircleOff size={14} color="var(--warning)" aria-hidden="true" />}<strong>{name.replaceAll("_", " ")}</strong><span className="subtle">{status}</span></div>) : <span className="subtle">Checking services…</span>}</div>
  </>;
}
