import Image from "next/image";
import Link from "next/link";
import {ArrowRight, CircleDot, GitCommitHorizontal, Menu, Radar, ShieldCheck, TimerReset} from "lucide-react";

const evidence = [
  {time: "10:24:31", text: "Latency threshold breached for five minutes", source: "Prometheus", icon: Radar},
  {time: "10:24:36", text: "Checkout trace sample correlated", source: "OpenTelemetry", icon: CircleDot},
  {time: "10:24:41", text: "Error rate increased from 2.7% to 9.1%", source: "Loki", icon: TimerReset},
  {time: "10:24:47", text: "Recent deploy isolated as probable cause", source: "GitHub", icon: GitCommitHorizontal},
];

const provenance = [
  {source: "Prometheus", observation: "Checkout p95 remained above the incident threshold for five minutes.", contribution: "+0.40"},
  {source: "OpenTelemetry", observation: "Slow traces converge on the checkout-api deployment path.", contribution: "+0.32"},
  {source: "GitHub", observation: "Release v2.8.4 completed ninety seconds before the first breach.", contribution: "+0.22"},
];

function BrandLockup() {
  return <span className="landing-brand">
    <span className="landing-brand-mark" aria-hidden="true"><Image src="/brand/logo.png" alt="" width={30} height={30} priority /></span>
    <strong>SREs</strong>
  </span>;
}

function EvidencePanel() {
  return <article className="landing-evidence" aria-label="Illustrative incident evidence preview">
    <header className="landing-evidence-header">
      <div><span>Illustrative incident · INC-4821</span><h2>Checkout latency elevated</h2><p>Today · 10:24:31 UTC</p></div>
      <span className="landing-status"><CircleDot size={13} aria-hidden="true" />Investigating</span>
    </header>
    <div className="landing-evidence-context"><strong>Evidence excerpt</strong><span>4 correlated signals · read-only preview</span></div>
    <ol className="landing-evidence-list">
      {evidence.map(({time, text, source, icon: Icon}) => <li key={time}><time>{time}</time><Icon size={16} aria-hidden="true" /><span>{text}</span><small>{source}</small></li>)}
    </ol>
    <footer className="landing-approval">
      <div className="landing-approval-copy"><ShieldCheck size={21} aria-hidden="true" /><span><strong>Human approval required</strong><small>Rate-limit safeguard · reversible action</small></span></div>
      <span className="landing-preview-label">No action taken</span>
    </footer>
  </article>;
}

export default function HomePage() {
  return <div className="landing-page">
    <header className="landing-nav">
      <Link href="/" aria-label="SREs home"><BrandLockup /></Link>
      <nav aria-label="Landing page navigation"><a href="#how-it-works">How it works</a><a href="#proof">Evidence model</a></nav>
      <div className="landing-nav-actions">
        <details className="landing-mobile-menu">
          <summary><Menu size={18} aria-hidden="true" /><span>Menu</span></summary>
          <nav aria-label="Mobile navigation"><a href="#how-it-works">How it works</a><a href="#proof">Evidence model</a><Link href="/simulate">Safe simulation</Link><Link href="/investigations">Workspace</Link></nav>
        </details>
        <Link className="landing-button landing-button-small landing-workspace-link" href="/investigations">Open workspace</Link>
      </div>
    </header>

    <main id="main-content" className="landing-main">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="landing-intro">Controlled incident response, accountable at every step.</p>
          <h1 id="landing-title">Evidence before action.</h1>
          <p className="landing-deck">SREs turns live telemetry into a defensible response—collecting what happened, proposing a bounded next move, and keeping an operator in control.</p>
          <p className="landing-mobile-signal"><Radar size={16} aria-hidden="true" /><span><strong>10:24:31 UTC</strong> · threshold breach corroborated by four sources</span></p>
          <div className="landing-actions"><Link className="landing-button" href="/simulate">Run a safe simulation <ArrowRight size={17} aria-hidden="true" /></Link><a className="landing-text-link" href="#proof">Inspect the evidence model</a></div>
          <p className="landing-action-note">Simulations introduce a controlled failure in the sample environment. Production actions always require an operator.</p>
        </div>
        <div className="landing-visual">
          <Image className="landing-theme-art" src="/art/sres-atmosphere.png" alt="A quiet mineral landscape framing an incident evidence excerpt" fill priority sizes="(max-width: 760px) 100vw, 72vw" />
          <EvidencePanel />
        </div>
      </section>

      <section className="landing-method" id="how-it-works" aria-labelledby="method-title">
        <div className="landing-method-lead"><h2 id="method-title">A system that proves before it acts.</h2><p>Every recommendation carries its source, sequence, expected impact, and guardrail. Operators see the whole argument—not just an answer.</p><Link className="landing-text-link" href="/simulate">Explore controlled simulations <ArrowRight size={16} aria-hidden="true" /></Link></div>
        <ol className="landing-steps">
          <li><span>1</span><div><h3>Signal</h3><p>Detect a meaningful change across metrics, logs, traces, and recent deploys.</p></div></li>
          <li><span>2</span><div><h3>Evidence</h3><p>Correlate sources into one timestamped account with confidence and provenance.</p></div></li>
          <li><span>3</span><div><h3>Decision</h3><p>Propose a bounded action, expose its risk, and wait for accountable approval.</p></div></li>
        </ol>
      </section>

      <section className="landing-proof" id="proof" aria-labelledby="proof-title">
        <div className="landing-proof-heading"><div><h2 id="proof-title">See how the finding earns its confidence.</h2><p>Each contribution remains attached to its source. Confidence reflects corroboration in this illustrative incident—not an unexplained model score.</p></div><span className="landing-proof-state"><ShieldCheck size={15} aria-hidden="true" />Human decision remains final</span></div>
        <ol className="landing-proof-chain" aria-label="Source-to-finding provenance">
          {provenance.map(({source, observation, contribution}, index) => <li key={source}><span className="landing-proof-index">0{index + 1}</span><div><strong>{source}</strong><p>{observation}</p></div><span className="landing-proof-contribution"><small>Confidence contribution</small>{contribution}</span></li>)}
          <li className="landing-proof-result"><span className="landing-proof-index">04</span><div><strong>Correlated finding</strong><p>Release v2.8.4 is the probable cause. Proposed rollback remains bounded and approval-gated.</p></div><span className="landing-proof-contribution"><small>Combined confidence</small>0.94</span></li>
        </ol>
        <div className="landing-artifact">
          <div><span>Illustrative investigation artifact</span><strong>trace_checkout_latency_10-24-41.json</strong><small>Every contribution links back to timestamped source evidence.</small></div>
          <pre aria-label="Investigation artifact excerpt"><code>{`{
  "incident": "INC-4821",
  "service": "checkout-api",
  "finding": "deploy correlated",
  "confidence": 0.94,
  "evidence": [0.40, 0.32, 0.22],
  "approval": "operator_required"
}`}</code></pre>
        </div>
      </section>
    </main>
    <footer className="landing-footer"><BrandLockup /><p>Evidence-first incident response.</p><a href="#proof">Evidence model</a><Link href="/investigations">Open workspace</Link></footer>
  </div>;
}
