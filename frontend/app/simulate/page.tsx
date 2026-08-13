"use client";

import {useState} from "react";
import {useRouter} from "next/navigation";
import useSWR from "swr";
import {CircleOff, Database, GitBranch, RotateCcw, ServerCrash} from "lucide-react";
import {PageHeader} from "@/components/page-header";
import {Button} from "@/components/ui/button";
import {apiFetch} from "@/lib/api";

const scenarios = [
  {id: "redis-failure", title: "Redis failure", service: "Cache dependency", description: "Disconnect Redis from both sample services.", impact: "Expect connection errors, elevated latency, and a spike in HTTP 500 responses.", icon: ServerCrash},
  {id: "slow-db", title: "Slow database", service: "PostgreSQL query path", description: "Raise user-query latency to eight seconds.", impact: "Expect database duration and API request p95 to move together.", icon: Database},
  {id: "bad-deployment", title: "Bad deployment", service: "Version v2", description: "Switch both sample services to a broken release.", impact: "Expect the deployment event to precede an HTTP 500 ratio above 80%.", icon: GitBranch},
];

export default function SimulatePage() {
  const router = useRouter();
  const [active, setActive] = useState<string>();
  const [error, setError] = useState("");
  const {data: services, mutate} = useSWR<Record<string, string>>("/system/status", (path: string) => apiFetch(path), {refreshInterval: 8000});

  async function trigger(scenario: string) {
    setActive(scenario); setError("");
    try {
      const result = await apiFetch<{investigation_id: string}>(`/simulate/${scenario}`, {method: "POST", body: JSON.stringify({auto_start_investigation: true})});
      router.push(`/investigation/${result.investigation_id}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start simulation"); setActive(undefined); }
  }

  async function recover() {
    setActive("recover"); setError("");
    try { await apiFetch("/system/recover", {method: "POST"}); await mutate(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Recovery failed"); } finally { setActive(undefined); }
  }

  return <>
    <PageHeader title="Simulation control" description="Introduce one controlled failure, then let Wayfinder investigate live observability data." actions={<Button onClick={recover} disabled={!!active}><RotateCcw size={16} aria-hidden="true" />{active === "recover" ? "Recovering…" : "Recover all"}</Button>} />
    {error && <p className="error-message" role="alert">{error}</p>}
    <div className="scenario-list">{scenarios.map(({id, title, service, description, impact, icon: Icon}) => <section className="scenario-row" key={id}><div className="scenario-icon"><Icon size={20} aria-hidden="true" /></div><div className="scenario-copy"><h2>{title}</h2><span>{service} · {description}</span></div><p className="scenario-impact">{impact}</p><Button variant="primary" disabled={!!active} onClick={() => trigger(id)}>{active === id ? "Starting…" : "Trigger"}</Button></section>)}</div>
    <div className="section-title"><h2>Environment health</h2><p>Updated every eight seconds</p></div>
    <div className="service-grid">{services ? Object.entries(services).map(([name, status]) => <div className="service-status" key={name}>{status === "healthy" ? <span className="live-pulse" aria-hidden="true" /> : <CircleOff size={14} color="var(--warning)" aria-hidden="true" />}<strong>{name.replaceAll("_", " ")}</strong><span className="subtle">{status}</span></div>) : <span className="subtle">Checking services…</span>}</div>
  </>;
}
