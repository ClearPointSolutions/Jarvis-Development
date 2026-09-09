"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/session";
import { createRuntimeClient } from "@/lib/api/runtime";
import { createWorkflowClient } from "@/lib/api/workflows";

export function RuntimeRuns() {
  const session = useSession();
  const router = useRouter();
  const client = useMemo(
    () => createRuntimeClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const projects = useQuery({
    queryKey: ["runtime-projects"],
    queryFn: client.projects,
    enabled: Boolean(session.data),
  });
  const workflows = useQuery({
    queryKey: ["runtime-workflows"],
    queryFn: () => createWorkflowClient().list(),
    enabled: Boolean(session.data),
  });
  const runs = useQuery({
    queryKey: ["runtime-runs"],
    queryFn: client.runs,
    enabled: Boolean(session.data),
    refetchInterval: 2000,
  });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"demo" | "real">("demo");
  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await client.createProject({
        slug: String(data.get("slug")),
        name: String(data.get("name")),
        idempotency_key: crypto.randomUUID(),
      });
      await projects.refetch();
      setMessage("Project created.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Project creation failed",
      );
    } finally {
      setBusy(false);
    }
  }
  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const run = await client.start(String(data.get("project")), {
        workflow_version_id: String(data.get("workflow")),
        objective: String(data.get("objective")),
        mode,
        ...(mode === "demo"
          ? {
              demo_fixture: {
                scenario: String(data.get("scenario")) as
                  "canonical" | "infrastructure" | "review" | "provider",
              },
            }
          : {}),
        priority: 0,
        idempotency_key: crypto.randomUUID(),
      });
      router.push(`/runs/${run.id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Run start failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Durable execution</p>
        <h1>Runs</h1>
        <p>
          Start an immutable published workflow and inspect its durable history.
          External nodes require a configured runtime adapter.
        </p>
      </header>
      <form className="content-card login-form" onSubmit={createProject}>
        <h2>Create project</h2>
        <label htmlFor="project-name">Project name</label>
        <input id="project-name" name="name" required maxLength={160} />
        <label htmlFor="project-slug">Project slug</label>
        <input
          id="project-slug"
          name="slug"
          required
          pattern="[a-z0-9](?:[a-z0-9]|-){0,79}"
        />
        <button className="button" disabled={busy}>
          Create project
        </button>
      </form>
      <form className="content-card login-form" onSubmit={start}>
        <h2>Start run</h2>
        <p>
          Local deterministic mode. No real worker or provider adapters are
          enabled in demo mode.
        </p>
        <label htmlFor="run-project">Project</label>
        <select id="run-project" name="project" required defaultValue="">
          <option value="" disabled>
            Select project
          </option>
          {projects.data?.items.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        <label htmlFor="run-workflow">Published workflow</label>
        <select id="run-workflow" name="workflow" required defaultValue="">
          <option value="" disabled>
            Select published workflow
          </option>
          {workflows.data?.items
            .filter(
              (workflow) =>
                workflow.current_published_version_id && !workflow.archived,
            )
            .map((workflow) => (
              <option
                key={workflow.id}
                value={workflow.current_published_version_id ?? ""}
              >
                {workflow.name}
              </option>
            ))}
        </select>
        <label htmlFor="run-mode">Execution mode</label>
        <select
          id="run-mode"
          value={mode}
          onChange={(event) => setMode(event.target.value as "demo" | "real")}
        >
          <option value="demo">DEMO — deterministic fixtures</option>
          <option value="real">Real — configured providers and worker</option>
        </select>
        {mode === "real" && (
          <p>
            Requires a real published workflow and matching server-side
            infrastructure configuration.
          </p>
        )}
        {mode === "demo" && (
          <>
            <label htmlFor="demo-scenario">DEMO scenario</label>
            <select id="demo-scenario" name="scenario" defaultValue="canonical">
              <option value="canonical">Test failure, retry, success</option>
              <option value="infrastructure">
                Worker infrastructure recovery
              </option>
              <option value="review">Reviewer feedback and retry</option>
              <option value="provider">Provider transient recovery</option>
            </select>
          </>
        )}
        <label htmlFor="run-objective">Objective</label>
        <textarea
          id="run-objective"
          name="objective"
          required
          maxLength={8000}
        />
        <button className="button button-primary" disabled={busy}>
          Start run
        </button>
      </form>
      <p role="status">{message}</p>
      <section className="content-card">
        <h2>Run history</h2>
        {runs.isError ? (
          <p role="alert">Run history is unavailable.</p>
        ) : runs.isPending ? (
          <p>Loading runs…</p>
        ) : runs.data.items.length === 0 ? (
          <p>No runs yet.</p>
        ) : (
          <ul>
            {runs.data.items.map((run) => (
              <li key={run.id}>
                <Link href={`/runs/${run.id}`}>Run {run.id}</Link> ·{" "}
                {run.recovering ? "recovering" : run.status} · desired{" "}
                {run.desired_state}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
