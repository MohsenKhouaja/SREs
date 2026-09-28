import Image from "next/image";
import Link from "next/link";
import {ArrowRight, CircleDot, GitCommitHorizontal, Menu, Radar, ShieldCheck, TimerReset} from "lucide-react";

const evidence = [
  {time: "01", text: "Read measured request rates and durations", source: "Prometheus", icon: Radar},
  {time: "02", text: "Inspect recorded requests and errors", source: "Loki", icon: CircleDot},
  {time: "03", text: "Compare observations using original timestamps", source: "Event analysis", icon: TimerReset},
  {time: "04", text: "Evaluate causes and explain evidence gaps", source: "Groq", icon: GitCommitHorizontal},
];

const provenance = [
  {source: "Measured signals", observation: "The lab sends real HTTP requests. Their responses and durations produce the logs and metrics agents inspect."},
  {source: "Model analysis", observation: "Groq interprets observations and proposes a supported lab action. Missing evidence can leave an investigation inconclusive."},
  {source: "Reviewable records", observation: "Open an investigation to inspect model inputs, tool responses, findings, and the human decision."},
];

function BrandLockup() {
  return <span className="landing-brand">
    <span className="landing-brand-mark" aria-hidden="true"><Image src="/brand/logo.png" alt="" width={30} height={30} priority /></span>
    <strong>SREs</strong>
  </span>;
}

function EvidencePanel() {
  return <article className="landing-evidence" aria-label="Investigation workflow guide">
    <header className="landing-evidence-header">
      <div><span>Inside an investigation</span><h2>From observations to a decision</h2><p>Start a run to collect evidence from the lab.</p></div>
      <span className="landing-status"><CircleDot size={13} aria-hidden="true" />Workflow guide</span>
    </header>
    <div className="landing-evidence-context"><strong>What the agents do</strong><span>Results appear in your investigation</span></div>
    <ol className="landing-evidence-list">
      {evidence.map(({time, text, source, icon: Icon}) => <li key={time}><time>{time}</time><Icon size={16} aria-hidden="true" /><span>{text}</span><small>{source}</small></li>)}
    </ol>
    <footer className="landing-approval">
      <div className="landing-approval-copy"><ShieldCheck size={21} aria-hidden="true" /><span><strong>Human review required</strong><small>Approve a proposed lab action before execution</small></span></div>
    </footer>
  </article>;
}

export default function HomePage() {
  return <div className="landing-page">
    <header className="landing-nav">
      <Link href="/" aria-label="SREs home"><BrandLockup /></Link>
      <nav aria-label="Landing page navigation"><a href="#how-it-works">How it works</a><a href="#proof">Supporting evidence</a></nav>
      <div className="landing-nav-actions">
        <details className="landing-mobile-menu">
          <summary><Menu size={18} aria-hidden="true" /><span>Menu</span></summary>
          <nav aria-label="Mobile navigation"><a href="#how-it-works">How it works</a><a href="#proof">Supporting evidence</a><Link href="/lab">Incident lab</Link><Link href="/investigations">Workspace</Link></nav>
        </details>
        <Link className="landing-button landing-button-small landing-workspace-link" href="/investigations">Open workspace</Link>
      </div>
    </header>

    <main id="main-content" className="landing-main">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="landing-intro">AI-assisted incident response, with people in control.</p>
          <h1 id="landing-title">Evidence before action.</h1>
          <p className="landing-deck">SREs is an evidence-first incident response platform where specialized agents analyze observability data, identify likely root causes, and propose remediations that require human approval before execution.</p>
          <p className="landing-mobile-signal"><Radar size={16} aria-hidden="true" /><span>Inspect the observations behind each finding.</span></p>
          <div className="landing-actions"><Link className="landing-button" href="/lab">Open the incident lab <ArrowRight size={17} aria-hidden="true" /></Link><a className="landing-text-link" href="#proof">See the supporting evidence</a></div>
          <p className="landing-action-note">This lab injects faults into bundled sample services and requires a working Groq connection. Every suggested fix still needs human approval.</p>
        </div>
        <div className="landing-visual">
          <Image className="landing-theme-art" src="/art/sres-atmosphere.png" alt="A quiet mineral landscape framing an incident evidence excerpt" fill priority sizes="(max-width: 760px) 100vw, 72vw" />
          <EvidencePanel />
        </div>
      </section>

      <section className="landing-method" id="how-it-works" aria-labelledby="method-title">
        <div className="landing-method-lead"><h2 id="method-title">From warning to informed action.</h2><p>SREs gathers the clues behind a service problem, explains the most likely cause, and recommends what a person can safely do next.</p><Link className="landing-text-link" href="/lab">See an investigation in action <ArrowRight size={16} aria-hidden="true" /></Link></div>
        <ol className="landing-steps">
          <li><span>1</span><div><h3>Start a lab incident</h3><p>Choose a controlled fault. Agents inspect the resulting requests, metrics, and logs.</p></div></li>
          <li><span>2</span><div><h3>Investigate</h3><p>Bring the clues together to explain what changed and identify the most likely cause.</p></div></li>
          <li><span>3</span><div><h3>Approve</h3><p>Recommend a safe response, then wait for a person to approve or reject it.</p></div></li>
        </ol>
      </section>

      <section className="landing-proof" id="proof" aria-labelledby="proof-title">
        <div className="landing-proof-heading"><div><h2 id="proof-title">See the evidence behind every recommendation.</h2><p>Each finding stays linked to the data that supports it, so people can understand why the system suggested a cause instead of trusting a hidden AI decision.</p></div><span className="landing-proof-state"><ShieldCheck size={15} aria-hidden="true" />A person makes the final decision</span></div>
        <ol className="landing-proof-chain" aria-label="How investigation evidence is collected">
          {provenance.map(({source, observation}, index) => <li key={source}><span className="landing-proof-index">0{index + 1}</span><div><strong>{source}</strong><p>{observation}</p></div></li>)}
          <li className="landing-proof-result"><span className="landing-proof-index">04</span><div><strong>Recovery checks</strong><p>After an approved control change, SREs tests application request paths and records whether they succeed within the lab latency limit.</p></div></li>
        </ol>
        <div className="landing-artifact">
          <div><span>Your investigation record</span><strong>Inspect the model and its evidence.</strong><small>Model failures stop analysis. Approved lab actions start the observed Redis container, terminate an observed database blocker, or roll back an observed release.</small></div>
          <Link className="landing-text-link" href="/investigations">Browse actual investigations <ArrowRight size={16} /></Link>
        </div>
      </section>
    </main>
    <footer className="landing-footer"><BrandLockup /><p>Incident response backed by evidence.</p><a href="#proof">Supporting evidence</a><Link href="/investigations">Open workspace</Link></footer>
  </div>;
}
