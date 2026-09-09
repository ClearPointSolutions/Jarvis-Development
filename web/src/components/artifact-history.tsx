"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createRuntimeClient } from "@/lib/api/runtime";
import { useSession } from "@/lib/session";

export function ArtifactHistory() {
  const session = useSession();
  const [runId, setRunId] = useState("");
  const runs = useQuery({
    queryKey: ["runtime-runs"],
    queryFn: () => createRuntimeClient().runs(),
    enabled: Boolean(session.data),
  });
  const evidence = useQuery({
    queryKey: ["runtime-evidence", runId],
    queryFn: () => createRuntimeClient().evidence(runId),
    enabled: Boolean(session.data && runId),
    refetchInterval: runId ? 5000 : false,
  });
  const artifacts = Array.from(
    new Map(
      (evidence.data?.items ?? []).flatMap((event) =>
        (event.artifact_refs ?? []).map(
          (artifact) => [artifact.artifact_id, artifact] as const,
        ),
      ),
    ).values(),
  );
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Deliverables and evidence</p>
        <h1>Artifacts</h1>
        <p>
          Download authorized immutable source snapshots, test output and review
          evidence.
        </p>
      </header>
      <section className="content-card">
        <label htmlFor="artifact-run">Run</label>
        <select
          id="artifact-run"
          value={runId}
          onChange={(event) => setRunId(event.target.value)}
        >
          <option value="">Select a run</option>
          {[...(runs.data?.items ?? [])].reverse().map((run) => (
            <option key={run.id} value={run.id}>
              {run.mode} · {run.status} · {run.id}
            </option>
          ))}
        </select>
        {(runs.error || evidence.error) && (
          <p role="alert">Artifact history could not be loaded.</p>
        )}
        {runId && (
          <>
            <Link href={`/runs/${runId}`}>
              Open run and accepted integration HEAD
            </Link>
            <ul>
              {artifacts.map((artifact) => (
                <li key={artifact.artifact_id}>
                  <a href={`/api/v1/artifacts/${artifact.artifact_id}`}>
                    {artifact.relation} · {artifact.artifact_id}
                  </a>
                </li>
              ))}
            </ul>
            {evidence.isSuccess && artifacts.length === 0 && (
              <p>No artifacts recorded for this run.</p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
