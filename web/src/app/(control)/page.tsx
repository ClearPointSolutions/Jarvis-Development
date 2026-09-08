import { EventFeed } from "@/components/event-feed";
import { StatusLabel } from "@/components/states";
import Link from "next/link";

export default function MissionPage() {
  return (
    <div className="page-stack">
      <header className="mission-header">
        <div>
          <p className="eyebrow">Operator workspace</p>
          <h1>Mission overview</h1>
          <p className="page-lede">Your durable development control plane.</p>
        </div>
        <StatusLabel label="DEMO · deterministic runtime" tone="neutral" />
      </header>
      <div className="mission-grid">
        <section className="content-card" aria-labelledby="organizer-title">
          <p className="eyebrow">01 / Intent</p>
          <h2 id="organizer-title">Organizer</h2>
          <p>
            Give Organizer an objective, select a published workflow, and follow
            its durable tasks, verification, and review.
          </p>
          <Link className="button" href="/runs">
            Create an objective
          </Link>
        </section>
        <section
          className="content-card graph-region"
          aria-labelledby="graph-title"
        >
          <p className="eyebrow">02 / Execution</p>
          <h2 id="graph-title">Live graph</h2>
          <div className="graph-empty">
            <p>No run selected</p>
            <small>
              Runtime nodes appear only from an authorized workflow.
            </small>
          </div>
        </section>
        <section className="content-card" aria-labelledby="run-title">
          <p className="eyebrow">03 / State</p>
          <h2 id="run-title">Current run</h2>
          <p>No run is selected.</p>
          <p>
            Open a known run from Runs to inspect its persisted event stream.
          </p>
        </section>
      </div>
      <EventFeed />
    </div>
  );
}
