"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { createRuntimeClient } from "@/lib/api/runtime";
import { useSession } from "@/lib/session";

export function OperationsPage() {
  const session = useSession();
  const health = useQuery({
    queryKey: ["system-health"],
    queryFn: () => createRuntimeClient().health(),
    enabled: Boolean(session.data),
    refetchInterval: 5000,
  });
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Operations</p>
        <h1>Health</h1>
        <p>
          Control-plane health and real execution readiness are separate. A
          working login does not prove a coding worker can run.
        </p>
      </header>
      {health.isPending && <p role="status">Loading operational state…</p>}
      {health.error && (
        <p role="alert">
          Operational state is unavailable. Check the API and database
          connection.
        </p>
      )}
      {health.data && (
        <section className="content-card">
          <h2>Services and queue</h2>
          <dl>
            <dt>Control plane</dt>
            <dd>{health.data.control_plane}</dd>
            <dt>Database</dt>
            <dd>{health.data.database}</dd>
            <dt>Orchestrator</dt>
            <dd>{health.data.orchestrator}</dd>
            <dt>Real execution</dt>
            <dd>{health.data.execution}</dd>
            <dt>Runtime mode</dt>
            <dd>{health.data.runtime_mode}</dd>
            <dt>Runtime manifest</dt>
            <dd>{health.data.runtime_manifest}</dd>
            <dt>Selected worker</dt>
            <dd>{health.data.worker}</dd>
            <dt>Provider capability</dt>
            <dd>{health.data.provider}</dd>
            <dt>Repository binding</dt>
            <dd>{health.data.repository_binding}</dd>
            <dt>Verification broker</dt>
            <dd>{health.data.verification_broker}</dd>
            <dt>Instances accepting work</dt>
            <dd>{health.data.accepting_instances}</dd>
            <dt>Last heartbeat</dt>
            <dd>{health.data.last_heartbeat_at ?? "Not observed"}</dd>
            <dt>Expired unreleased leases</dt>
            <dd>{health.data.expired_active_leases}</dd>
            {Object.entries(health.data.run_counts).map(([state, count]) => (
              <div key={state}>
                <dt>{state}</dt>
                <dd>{count} runs</dd>
              </div>
            ))}
          </dl>
          {health.data.execution_reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
          <p>
            Heartbeat freshness threshold:{" "}
            {health.data.heartbeat_stale_after_seconds} seconds.
          </p>
          <p>Observed {health.data.observed_at}</p>
          <Link href="/runs">Inspect run history and controls</Link>
        </section>
      )}
      <section className="content-card">
        <h2>Dependency evidence</h2>
        <p>
          Provider and worker checks are recorded with each run. Inspect its
          activity and dependency health for the exact observation time.
        </p>
        <Link href="/workers">Worker configuration</Link> ·{" "}
        <Link href="/providers">Provider configuration</Link>
      </section>
    </div>
  );
}
