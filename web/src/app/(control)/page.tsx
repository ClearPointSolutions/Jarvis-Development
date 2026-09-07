import { DemoBadge, StatusLabel } from "@/components/states";
import { ReadOnlyTerminal } from "@/components/read-only-terminal";
import { SafeMarkdown } from "@/components/safe-markdown";

export default function MissionPage() {
  return (
    <div className="page-stack">
      <header className="mission-header">
        <div>
          <p className="eyebrow">Operator workspace</p>
          <h1>Mission overview</h1>
          <p className="page-lede">
            A secure, observable shell for the durable Jarvis control plane.
          </p>
        </div>
        <StatusLabel label="Foundation ready" tone="good" />
      </header>

      <section aria-labelledby="boundary-title" className="metric-grid">
        <h2 className="sr-only" id="boundary-title">
          Architecture boundaries
        </h2>
        <article className="metric-card">
          <p>Execution authority</p>
          <strong>LangGraph</strong>
          <span>Never inferred from UI state</span>
        </article>
        <article className="metric-card">
          <p>Durable state</p>
          <strong>PostgreSQL</strong>
          <span>Events persist before delivery</span>
        </article>
        <article className="metric-card">
          <p>Browser boundary</p>
          <strong>Secret free</strong>
          <span>Opaque, HttpOnly session only</span>
        </article>
      </section>

      <section aria-labelledby="fixture-title" className="fixture-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Rendering safety check</p>
            <h2 id="fixture-title">Inert output preview</h2>
          </div>
          <DemoBadge />
        </div>
        <p className="fixture-disclaimer">
          This marked fixture verifies presentation only. It is not runtime
          activity.
        </p>
        <div className="fixture-grid">
          <div className="content-card">
            <h3>Sanitized summary</h3>
            <SafeMarkdown>
              {
                "**No hidden reasoning.** Mission Control displays declared summaries and [safe links](/runs)."
              }
            </SafeMarkdown>
          </div>
          <ReadOnlyTerminal
            output={
              "$ python -m pytest\nNo execution attached to this demo fixture."
            }
          />
        </div>
      </section>
    </div>
  );
}
