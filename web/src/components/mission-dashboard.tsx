"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "@/lib/session";
import { createRuntimeClient } from "@/lib/api/runtime";
import { RunExperience } from "@/components/run-experience";
import { RunControls } from "@/components/run-controls";
import { EventFeed } from "@/components/event-feed";

export function MissionDashboard({
  approvalsOnly = false,
  title,
}: {
  approvalsOnly?: boolean;
  title?: string;
}) {
  const session = useSession();
  const runs = useQuery({
    queryKey: ["runtime-runs"],
    queryFn: () => createRuntimeClient().runs(),
    enabled: Boolean(session.data),
    refetchInterval: 3000,
  });
  const [selected, setSelected] = useState("");
  const items = (runs.data?.items ?? []).filter(
    (run) => !approvalsOnly || run.status === "approval_required",
  );
  const current = items.find((run) => run.id === selected);
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Durable execution</p>
        <h1>{title ?? (approvalsOnly ? "Approvals" : "Mission overview")}</h1>
        <Link href="/runs" className="button">
          Create an objective
        </Link>
      </header>
      <section className="content-card">
        <label htmlFor="selected-run">
          {approvalsOnly ? "Run awaiting approval" : "Selected run"}
        </label>
        <select
          id="selected-run"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Select a run</option>
          {items.map((run) => (
            <option key={run.id} value={run.id}>
              {run.mode.toUpperCase()} · {run.status} · {run.id}
            </option>
          ))}
        </select>
        {runs.error && <p role="alert">Run history could not be loaded.</p>}
        {items.length === 0 && !runs.isPending && (
          <p>
            {approvalsOnly
              ? "No runs currently await approval."
              : "No runs have been created."}
          </p>
        )}
        {current && (
          <p>
            {current.mode === "demo"
              ? "DEMO · deterministic external dependencies"
              : "Real · configured runtime"}{" "}
            · {current.status}
          </p>
        )}
        {!selected && (
          <p>
            Select a run to inspect its published graph, tasks and persisted
            events.
          </p>
        )}
      </section>
      {selected && (
        <>
          <RunControls runId={selected} />
          <RunExperience runId={selected} />
          <EventFeed runId={selected} />
        </>
      )}
    </div>
  );
}
