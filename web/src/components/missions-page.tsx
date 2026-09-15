"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { createMissionClient } from "@/lib/api/missions";
import { createRegistryClient } from "@/lib/api/registry";
import { createRuntimeClient } from "@/lib/api/runtime";
import { useSession } from "@/lib/session";

export function MissionsPage() {
  const session = useSession();
  const router = useRouter();
  const missionClient = useMemo(
    () => createMissionClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const registry = useMemo(
    () => createRegistryClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const enabled = Boolean(session.data);
  const missions = useQuery({
    queryKey: ["missions"],
    queryFn: missionClient.list,
    enabled,
  });
  const projects = useQuery({
    queryKey: ["runtime-projects"],
    queryFn: () => createRuntimeClient().projects(),
    enabled,
  });
  const teams = useQuery({
    queryKey: ["registry", "team_template"],
    queryFn: () => registry.list("team_template"),
    enabled,
  });
  const [mode, setMode] = useState<"demo" | "real">("demo");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setNotice("");
    try {
      const mission = await missionClient.create({
        project_id: String(data.get("project")),
        objective: String(data.get("objective")),
        constraints: String(data.get("constraints"))
          .split("\n")
          .map((value) => value.trim())
          .filter(Boolean),
        mode,
        team_template_revision_id: String(data.get("team")),
        idempotency_key: crypto.randomUUID(),
      });
      router.push(`/missions/${mission.id}`);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Mission creation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  const teamOptions = (teams.data?.items ?? []).filter(
    (record) =>
      record.spec.kind === "team_template" &&
      record.spec.mode === mode &&
      record.enabled &&
      !record.archived,
  );
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Persistent teams</p>
        <h1>Missions</h1>
        <p>
          Create a continuing goal, converse with its manager, then explicitly
          start bounded work.
        </p>
      </header>
      <form className="content-card login-form" onSubmit={create}>
        <h2>Create mission</h2>
        <label htmlFor="mission-project">Project</label>
        <select id="mission-project" name="project" required defaultValue="">
          <option value="" disabled>
            Select project
          </option>
          {projects.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <label htmlFor="mission-mode">Mode</label>
        <select
          id="mission-mode"
          value={mode}
          onChange={(event) => setMode(event.target.value as "demo" | "real")}
        >
          <option value="demo">DEMO — deterministic manager and worker</option>
          <option value="real">Real — configured provider and worker</option>
        </select>
        <TeamSelect
          name="team"
          label="Fixed development team"
          records={teamOptions}
        />
        <label htmlFor="mission-objective">Continuing objective</label>
        <textarea
          id="mission-objective"
          name="objective"
          required
          maxLength={8000}
        />
        <label htmlFor="mission-constraints">Constraints, one per line</label>
        <textarea
          id="mission-constraints"
          name="constraints"
          maxLength={8000}
        />
        <button className="button button-primary" disabled={busy}>
          Create persistent mission
        </button>
        {notice && <p role="alert">{notice}</p>}
      </form>
      <section className="content-card">
        <h2>Mission history</h2>
        {missions.data?.items.length ? (
          <ul>
            {missions.data.items.map((mission) => (
              <li key={mission.id}>
                <Link href={`/missions/${mission.id}`}>
                  {mission.objective}
                </Link>{" "}
                · {mission.mode} · {mission.lifecycle}
              </li>
            ))}
          </ul>
        ) : (
          <p>No missions yet.</p>
        )}
      </section>
    </div>
  );
}

function TeamSelect({
  name,
  label,
  records,
}: {
  name: string;
  label: string;
  records: { revision_id: string; display_name: string }[];
}) {
  return (
    <label>
      {label}
      <select name={name} required defaultValue="">
        <option value="" disabled>
          Select {label.toLowerCase()}
        </option>
        {records.map((record) => (
          <option key={record.revision_id} value={record.revision_id}>
            {record.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
