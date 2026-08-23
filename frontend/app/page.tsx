import Image from "next/image";
import Link from "next/link";
import {ArrowRight, CheckCircle2, CircleDot, GitCommitHorizontal, Radar, ShieldCheck, TimerReset} from "lucide-react";

const evidence = [
  {time: "10:24:31", text: "Latency threshold breached for five minutes", source: "Prometheus", icon: Radar},
  {time: "10:24:36", text: "Checkout trace sample correlated", source: "OpenTelemetry", icon: CircleDot},
  {time: "10:24:41", text: "Error rate increased from 2.7% to 9.1%", source: "Loki", icon: TimerReset},
  {time: "10:24:47", text: "Recent deploy isolated as probable cause", source: "GitHub", icon: GitCommitHorizontal},
];

function BrandLockup() {
  return <span className="landing-brand">
    <span className="landing-brand-mark" aria-hidden="true"><Image src="/brand/logo.png" alt="" width={30} height={30} priority /></span>
    <strong>SREs</strong>
  </span>;
}

function EvidencePanel() {
  return <article className="landing-evidence" aria-label="Live incident evidence preview">
    <header className="landing-evidence-header">
      <div><span>Incident INC-4821</span><h2>Checkout latency elevated</h2><p>Today · 10:24:31 UTC</p></div>
      <span className="landing-status"><CircleDot size={13} aria-hidden="true" />Investigating</span>
    </header>
    <div className="landing-evidence-tabs" aria-label="Preview section"><span className="is-current">Evidence</span><span>Timeline</span><span>Impact</span></div>
    <ol className="landing-evidence-list">
      {evidence.map(({time, text, source, icon: Icon}) => <li key={time}><time>{time}</time><Icon size={16} aria-hidden="true" /><span>{text}</span><small>{source}</small></li>)}
    </ol>
    <footer className="landing-approval">
      <div className="landing-approval-copy"><ShieldCheck size={21} aria-hidden="true" /><span><strong>Human approval required</strong><small>Rate-limit safeguard · reversible action</small></span></div>
      <Link href="/approvals" className="landing-button landing-button-small">Review action</Link>
    </footer>
  </article>;
}

export default function HomePage() {
  return <div className="landing-page">
    <header className="landing-nav">
      <Link href="/" aria-label="SREs home"><BrandLockup /></Link>
      <nav aria-label="Landing page navigation"><a href="#how-it-works">How it works</a><a href="#proof">Evidence model</a><Link href="/approvals">Approvals</Link></nav>
      <Link className="landing-button landing-button-small" href="/investigations">Open workspace</Link>
    </header>

    <main id="main-content" className="landing-main">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="landing-intro">Autonomous incident response, governed by people.</p>
          <h1 id="landing-title">Evidence before action.</h1>
          <p className="landing-deck">SREs turns live telemetry into a defensible response—collecting what happened, proposing the safest next move, and keeping an operator in control.</p>
          <div className="landing-actions"><Link className="landing-button" href="/simulate">Start an investigation <ArrowRight size={17} aria-hidden="true" /></Link><a className="landing-text-link" href="#how-it-works">See the evidence model</a></div>
        </div>
        <div className="landing-visual">
          <Image className="landing-theme-art" src="/brand/theme.png" alt="Flowing bands of light converging through a deep blue field" fill priority sizes="(max-width: 760px) 100vw, 72vw" />
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
        <div className="landing-proof-heading"><div><h2 id="proof-title">The incident record stays intact.</h2><p>From first alert to final report, every claim remains connected to its evidence.</p></div><span className="landing-proof-state"><CheckCircle2 size={15} aria-hidden="true" />Sources verified</span></div>
        <div className="landing-artifact">
          <div><span>Investigation artifact</span><strong>trace_checkout_latency_10-24-41.json</strong><small>Correlated by SREs · 6 sources · immutable timeline</small></div>
          <pre aria-label="Investigation artifact excerpt"><code>{`{
  "incident": "INC-4821",
  "service": "checkout-api",
  "finding": "deploy correlated",
  "confidence": 0.94,
  "approval": "required"
}`}</code></pre>
        </div>
      </section>
    </main>
    <footer className="landing-footer"><BrandLockup /><p>Evidence-first incident response.</p><Link href="/settings">System settings</Link></footer>
  </div>;
}
