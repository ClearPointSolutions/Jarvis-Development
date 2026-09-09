"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createRuntimeClient } from "@/lib/api/runtime";
import { useSession } from "@/lib/session";

export function ProjectHistory() {
  const session = useSession();
  const [project, setProject] = useState("");
  const projects = useQuery({
    queryKey: ["runtime-projects"],
    queryFn: () => createRuntimeClient().projects(),
    enabled: Boolean(session.data),
  });
  const runs = useQuery({
    queryKey: ["runtime-runs"],
    queryFn: () => createRuntimeClient().runs(),
    enabled: Boolean(session.data),
    refetchInterval: 5000,
  });
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Workspace</p>
        <h1>Projects</h1>
        <p>Open a project’s durable runs and accepted deliverables.</p>
        <Link className="button" href="/runs">
          Create project or objective
        </Link>
      </header>
      <section className="content-card">
        <label htmlFor="history-project">Project</label>
        <select
          id="history-project"
          value={project}
          onChange={(event) => setProject(event.target.value)}
        >
          <option value="">All projects</option>
          {projects.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        {(projects.error || runs.error) && (
          <p role="alert">Project history could not be loaded.</p>
        )}
        {runs.isPending ? (
          <p>Loading runs…</p>
        ) : (
          <ul>
            {[...(runs.data?.items ?? [])]
              .reverse()
              .filter((run) => !project || run.project_id === project)
              .map((run) => (
                <li key={run.id}>
                  <Link href={`/runs/${run.id}`}>
                    {projects.data?.items.find(
                      (item) => item.id === run.project_id,
                    )?.name ?? "Project"}{" "}
                    · Run {run.run_number}
                  </Link>
                  <p>
                    {run.mode} · {run.status} ·{" "}
                    {run.result_summary ?? "No final result yet"}
                  </p>
                </li>
              ))}
          </ul>
        )}
        {runs.data?.items.length === 0 && <p>No runs have been created.</p>}
      </section>
    </div>
  );
}
