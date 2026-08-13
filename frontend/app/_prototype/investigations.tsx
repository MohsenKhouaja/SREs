// PROTOTYPE — Three investigations-home variants, switchable via ?variant=, on the existing / route.

import Link from "next/link";
import {ArrowUpRight, BookOpen, Clock3, FileCheck2, Plus, Radio, ShieldCheck} from "lucide-react";
import {Badge} from "@/components/ui/badge";
import {duration, formatScenario, formatTime, shortId} from "@/lib/api";
import type {Investigation} from "@/lib/types";

function InvestigationLink({item, className}: {item: Investigation; className?: string}) {
  return <Link className={className} href={`/investigation/${item.investigation_id}`} aria-label={`Open ${formatScenario(item.scenario)} investigation`}><ArrowUpRight size={17} aria-hidden="true" /></Link>;
}

function EditorialMeta({item}: {item: Investigation}) {
  return <div className="prototype-meta"><Badge status={item.status} /><span>{formatTime(item.created_at)}</span><span className="mono">{duration(item.created_at, item.completed_at)}</span></div>;
}

export function JournalIndex({items, usingSamples}: {items: Investigation[]; usingSamples: boolean}) {
  const [lead, ...rest] = items;
  return <div className="editorial-prototype variant-journal">
    <header className="prototype-masthead">
      <div><span>Investigations</span><span>{usingSamples ? "Sample edition" : `${items.length} in the archive`}</span></div>
      <h1>The incident record.</h1>
      <div className="prototype-intro"><p>A clear account of every signal, conclusion, and human decision.</p><Link className="button prototype-primary" href="/simulate"><Plus size={15} />New investigation</Link></div>
    </header>

    <section className="journal-lead" aria-labelledby="journal-lead-title">
      <div className="journal-art"><img src="/art/wayfinder-atmosphere.png" alt="" /></div>
      <div className="journal-lead-copy">
        <div className="prototype-section-label"><span>Current briefing</span><Radio size={14} aria-hidden="true" /></div>
        <h2 id="journal-lead-title">{formatScenario(lead.scenario)}</h2>
        <p>The latest investigation is assembling a durable evidence trail across metrics, logs, and agent findings.</p>
        <EditorialMeta item={lead} />
        <Link className="prototype-text-link" href={`/investigation/${lead.investigation_id}`}>Read the investigation <ArrowUpRight size={16} /></Link>
      </div>
    </section>

    <section className="journal-archive" aria-labelledby="journal-archive-title">
      <div className="journal-section-heading"><h2 id="journal-archive-title">Recent record</h2><span>Newest first</span></div>
      {rest.map((item, index) => <article className="journal-row" key={item.investigation_id}>
        <span className="journal-ordinal">{String(index + 2).padStart(2, "0")}</span>
        <div><h3>{formatScenario(item.scenario)}</h3><span className="mono">{shortId(item.investigation_id)}</span></div>
        <EditorialMeta item={item} />
        <InvestigationLink item={item} />
      </article>)}
    </section>
  </div>;
}

export function FocusedBriefing({items, usingSamples}: {items: Investigation[]; usingSamples: boolean}) {
  const active = items.find((item) => !["completed", "cancelled", "failed"].includes(item.status)) || items[0];
  const completed = items.filter((item) => item.status === "completed").length;
  return <div className="editorial-prototype variant-briefing">
    <header className="briefing-header">
      <div><h1>Good morning.</h1><p>Here is what needs your attention across the incident workspace.</p></div>
      <Link className="button prototype-primary" href="/simulate"><Plus size={15} />Start investigation</Link>
    </header>

    <div className="briefing-layout">
      <section className="briefing-focus" aria-labelledby="briefing-focus-title">
        <div className="briefing-art"><img src="/art/wayfinder-atmosphere.png" alt="" /></div>
        <div className="briefing-focus-copy">
          <div className="prototype-section-label"><span>{usingSamples ? "Preview focus" : "Needs attention"}</span><Clock3 size={14} /></div>
          <h2 id="briefing-focus-title">{formatScenario(active.scenario)}</h2>
          <p>Follow the evidence chain from the first system signal to the current operational decision.</p>
          <EditorialMeta item={active} />
          <Link className="prototype-dark-action" href={`/investigation/${active.investigation_id}`}>Open live briefing <ArrowUpRight size={16} /></Link>
        </div>
      </section>

      <aside className="briefing-summary" aria-label="Workspace summary">
        <div className="briefing-summary-head"><BookOpen size={18} /><span>Desk note</span></div>
        <p>{completed ? `${completed} investigations have reached a complete, reviewable report.` : "No report has closed yet. The current evidence chain remains active."}</p>
        <dl><div><dt>Open records</dt><dd>{items.length - completed}</dd></div><div><dt>Filed reports</dt><dd>{completed}</dd></div></dl>
      </aside>
    </div>

    <section className="briefing-list" aria-labelledby="briefing-list-title">
      <div className="journal-section-heading"><h2 id="briefing-list-title">All investigations</h2><span>{items.length} records</span></div>
      {items.map((item) => <article key={item.investigation_id}>
        <div className="briefing-date"><span>{new Date(item.created_at).toLocaleDateString(undefined, {day: "2-digit"})}</span><small>{new Date(item.created_at).toLocaleDateString(undefined, {month: "short"})}</small></div>
        <div><h3>{formatScenario(item.scenario)}</h3><span className="mono">Case {shortId(item.investigation_id)}</span></div>
        <Badge status={item.status} />
        <InvestigationLink item={item} />
      </article>)}
    </section>
  </div>;
}

export function EvidenceDesk({items, usingSamples}: {items: Investigation[]; usingSamples: boolean}) {
  const selected = items[0];
  return <div className="editorial-prototype variant-desk">
    <header className="desk-header"><div><h1>Investigation desk</h1><p>Evidence, decisions, and reports in one continuous record.</p></div><Link className="button prototype-primary" href="/simulate"><Plus size={15} />New</Link></header>
    <div className="desk-layout">
      <section className="desk-index" aria-labelledby="desk-index-title">
        <div className="desk-index-heading"><h2 id="desk-index-title">Case index</h2><span>{usingSamples ? "Preview" : `${items.length} total`}</span></div>
        {items.map((item, index) => <Link className={`desk-index-row ${index === 0 ? "is-selected" : ""}`} href={`/investigation/${item.investigation_id}`} key={item.investigation_id}>
          <span className="mono">{shortId(item.investigation_id)}</span>
          <strong>{formatScenario(item.scenario)}</strong>
          <Badge status={item.status} />
        </Link>)}
      </section>

      <article className="desk-dossier">
        <div className="desk-art"><img src="/art/wayfinder-atmosphere.png" alt="" /></div>
        <div className="desk-dossier-head"><span className="mono">Case {shortId(selected.investigation_id)}</span><Badge status={selected.status} /></div>
        <h2>{formatScenario(selected.scenario)}</h2>
        <p className="desk-dek">A working dossier that makes the current system state and the evidence behind it readable in one pass.</p>
        <dl className="desk-facts">
          <div><dt><Clock3 size={15} />Opened</dt><dd>{formatTime(selected.created_at)}</dd></div>
          <div><dt><ShieldCheck size={15} />Decision</dt><dd>{selected.status === "awaiting_approval" ? "Human review required" : "Evidence gathering"}</dd></div>
          <div><dt><FileCheck2 size={15} />Elapsed</dt><dd className="mono">{duration(selected.created_at, selected.completed_at)}</dd></div>
        </dl>
        <Link className="prototype-dark-action" href={`/investigation/${selected.investigation_id}`}>Enter dossier <ArrowUpRight size={16} /></Link>
      </article>
    </div>
  </div>;
}
