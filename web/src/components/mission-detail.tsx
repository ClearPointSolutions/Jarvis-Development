"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createMissionClient } from "@/lib/api/missions";
import { useSession } from "@/lib/session";

export function MissionDetail() {
  const id = String(useParams().missionId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSession();
  const client = useMemo(
    () => createMissionClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const enabled = Boolean(session.data && id);
  const mission = useQuery({
    queryKey: ["mission", id],
    queryFn: () => client.get(id),
    enabled,
    refetchInterval: 2000,
  });
  const messages = useQuery({
    queryKey: ["mission-messages", id],
    queryFn: () => client.messages(id),
    enabled,
    refetchInterval: 1500,
  });
  const turns = useQuery({
    queryKey: ["mission-turns", id],
    queryFn: () => client.turns(id),
    enabled,
    refetchInterval: 1500,
  });
  const items = useQuery({
    queryKey: ["mission-items", id],
    queryFn: () => client.items(id),
    enabled,
    refetchInterval: 2000,
  });
  const wakeups = useQuery({
    queryKey: ["mission-wakeups", id],
    queryFn: () => client.wakeups(id),
    enabled,
    refetchInterval: 2000,
  });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [controlScope, setControlScope] = useState<
    "mission" | "team" | "global"
  >("mission");
  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["mission"] });
  }
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mission.data) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    try {
      await client.message(id, {
        body: String(data.get("message")),
        expected_version: mission.data.version,
        allow_paid_inference: Boolean(data.get("paid")),
        idempotency_key: crypto.randomUUID(),
      });
      form.reset();
      setNotice(
        "Instruction queued. Delivery is not yet behavioral compliance.",
      );
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Message failed");
    } finally {
      setBusy(false);
    }
  }
  async function revise(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mission.data) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await client.directive(id, {
        objective: String(data.get("objective")),
        constraints: String(data.get("constraints"))
          .split("\n")
          .map((v) => v.trim())
          .filter(Boolean),
        expected_version: mission.data.version,
        idempotency_key: crypto.randomUUID(),
      });
      setNotice(
        "Directive revised. In-flight replies governed by the old version will be stale.",
      );
      await refresh();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Directive update failed",
      );
    } finally {
      setBusy(false);
    }
  }
  async function start(itemId: string) {
    if (!mission.data) return;
    setBusy(true);
    try {
      const run = await client.start(id, itemId, {
        expected_mission_version: mission.data.version,
        idempotency_key: crypto.randomUUID(),
      });
      router.push(`/runs/${run.id}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Launch failed");
    } finally {
      setBusy(false);
    }
  }
  async function autonomy(enabled: boolean) {
    if (!mission.data) return;
    setBusy(true);
    try {
      await client.autonomy(id, {
        enabled,
        expected_version: mission.data.version,
        idempotency_key: crypto.randomUUID(),
      });
      setNotice(
        enabled
          ? "Bounded automatic continuation enabled."
          : "Automatic continuation disabled.",
      );
      await refresh();
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Autonomy update failed",
      );
    } finally {
      setBusy(false);
    }
  }
  async function control(action: "pause" | "resume" | "drain" | "cancel") {
    if (!mission.data) return;
    setBusy(true);
    try {
      await client.control(id, {
        scope: controlScope,
        action,
        expected_version: mission.data.version,
        idempotency_key: crypto.randomUUID(),
      });
      setNotice(`${controlScope} ${action} requested.`);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Control failed");
    } finally {
      setBusy(false);
    }
  }
  async function safePoint(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mission.data) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    try {
      await client.control(id, {
        scope: controlScope,
        action: "safe_point",
        instruction: String(data.get("instruction")),
        expected_version: mission.data.version,
        idempotency_key: crypto.randomUUID(),
      });
      form.reset();
      setNotice("Instruction queued for an eligible safe point.");
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Instruction failed");
    } finally {
      setBusy(false);
    }
  }
  if (!mission.data)
    return (
      <div className="state-card" role="status">
        Loading mission…
      </div>
    );
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">
          Mission · directive v{mission.data.directive_version} · team v
          {mission.data.team_version}
        </p>
        <h1>{mission.data.objective}</h1>
        <p>
          {mission.data.mode.toUpperCase()} · {mission.data.lifecycle} · version{" "}
          {mission.data.version}
        </p>
        <p>
          Automatic continuation: {mission.data.autonomous ? "ON" : "OFF"} ·
          Paid unattended:{" "}
          {mission.data.paid_unattended_available ? "available" : "disabled"}
        </p>
      </header>
      <section
        className="content-card"
        aria-labelledby="mission-management-state"
      >
        <h2 id="mission-management-state">Management state</h2>
        <dl className="detail-list">
          <div>
            <dt>Governing directive</dt>
            <dd>v{mission.data.directive_version}</dd>
          </div>
          <div>
            <dt>Active work snapshot</dt>
            <dd>
              {mission.data.active_work_directive_version
                ? `directive v${mission.data.active_work_directive_version}`
                : "none"}
            </dd>
          </div>
          <div>
            <dt>Next intended action</dt>
            <dd>{mission.data.next_action ?? "No action scheduled"}</dd>
          </div>
          <div>
            <dt>Basis</dt>
            <dd>{mission.data.next_action_basis ?? "No persisted basis"}</dd>
          </div>
          <div>
            <dt>Waiting reason</dt>
            <dd>{mission.data.waiting_reason ?? "Not waiting"}</dd>
          </div>
          <div>
            <dt>User action</dt>
            <dd>{mission.data.user_action_required ?? "None"}</dd>
          </div>
        </dl>
        <div className="button-row">
          <button
            className="button"
            disabled={busy}
            onClick={() => void autonomy(!mission.data.autonomous)}
          >
            Turn autonomy {mission.data.autonomous ? "off" : "on"}
          </button>
          <label>
            Control scope
            <select
              value={controlScope}
              onChange={(event) =>
                setControlScope(event.target.value as typeof controlScope)
              }
            >
              <option value="mission">Mission</option>
              <option value="team">Selected team</option>
              <option value="global">Global</option>
            </select>
          </label>
          <button
            className="button"
            disabled={busy}
            onClick={() => void control("pause")}
          >
            Pause admission
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => void control("resume")}
          >
            Resume admission
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => void control("drain")}
          >
            Drain
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => void control("cancel")}
          >
            Cancel
          </button>
        </div>
        <form className="login-form" onSubmit={safePoint}>
          <label>
            Safe-point instruction
            <textarea name="instruction" required maxLength={2000} />
          </label>
          <button className="button" disabled={busy}>
            Queue instruction
          </button>
        </form>
      </section>
      {mission.data.usage && (
        <section className="content-card" aria-labelledby="mission-resources">
          <h2 id="mission-resources">Resource window</h2>
          <p>
            UTC · {mission.data.usage.window_seconds}s window from{" "}
            {new Date(mission.data.usage.window_started_at).toLocaleString()}
          </p>
          <p>
            {mission.data.usage.unknown_liability
              ? "Unknown outcomes retain their maximum reserved liability."
              : "All recorded outcomes have known liability."}
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Reserved</th>
                  <th>Actual</th>
                  <th>Limit</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    "calls",
                    "input_tokens",
                    "output_tokens",
                    "active_jobs",
                    "wall_seconds",
                    "iterations",
                    "new_work_items",
                  ] as const
                ).map((key) => (
                  <tr key={key}>
                    <th>{key.replaceAll("_", " ")}</th>
                    <td>{mission.data.usage?.reserved[key] ?? 0}</td>
                    <td>{mission.data.usage?.actual[key] ?? 0}</td>
                    <td>
                      {mission.data.usage?.limits[
                        `max_${key}` as keyof typeof mission.data.usage.limits
                      ] ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <div className="mission-detail-grid">
        <section className="content-card">
          <h2>Manager conversation</h2>
          <div className="mission-chat">
            {messages.data?.items.map((message) => (
              <article
                key={message.id}
                className={`mission-message mission-message-${message.role}`}
              >
                <strong>{message.role}</strong>
                <span>{message.disposition}</span>
                <p>{message.body}</p>
              </article>
            ))}
            {turns.data?.items
              .filter(
                (turn) => turn.status === "stale" || turn.status === "failed",
              )
              .map((turn) => (
                <article key={turn.id} className="mission-message">
                  <strong>Manager proposal · {turn.status}</strong>
                  <p>
                    {turn.status === "stale"
                      ? `${turn.decision?.message ?? "The response"} (not applied because mission direction changed).`
                      : `Manager turn failed: ${turn.failure_code ?? "invalid response"}.`}
                  </p>
                </article>
              ))}
          </div>
          <form className="login-form" onSubmit={send}>
            <label htmlFor="manager-message">Message manager</label>
            <textarea
              id="manager-message"
              name="message"
              required
              maxLength={8000}
            />
            <label className="check-field">
              <input type="checkbox" name="paid" />
              Authorize this turn to use a configured paid provider
            </label>
            <button className="button button-primary" disabled={busy}>
              Queue manager turn
            </button>
          </form>
          {turns.data?.items.some(
            (turn) => turn.status === "queued" || turn.status === "running",
          ) && <p role="status">Manager turn is queued or running.</p>}
        </section>
        <section className="content-card">
          <h2>Proposed backlog</h2>
          {items.data?.items.length ? (
            <ol className="backlog-list">
              {items.data.items.map((item) => (
                <li key={item.id}>
                  <h3>
                    {item.key} · {item.title}
                  </h3>
                  <p>{item.objective}</p>
                  <p>
                    {item.lifecycle} · priority {item.priority} · directive v
                    {item.directive_version}
                  </p>
                  <ul>
                    {item.acceptance_criteria.map((criterion) => (
                      <li key={criterion}>{criterion}</li>
                    ))}
                  </ul>
                  {item.run_id ? (
                    <Link className="button" href={`/runs/${item.run_id}`}>
                      Open linked run evidence
                    </Link>
                  ) : (
                    <button
                      className="button"
                      disabled={busy || item.lifecycle !== "ready"}
                      onClick={() => void start(item.id)}
                    >
                      Start work item
                    </button>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p>No proposed work yet. Ask the manager to prepare a backlog.</p>
          )}
        </section>
      </div>
      <form className="content-card login-form" onSubmit={revise}>
        <h2>Goal and constraints</h2>
        <label>
          Objective
          <textarea
            name="objective"
            required
            maxLength={8000}
            defaultValue={mission.data.objective}
          />
        </label>
        <label>
          Constraints
          <textarea
            name="constraints"
            defaultValue={mission.data.constraints.join("\n")}
          />
        </label>
        <button className="button" disabled={busy}>
          Create directive version {mission.data.directive_version + 1}
        </button>
      </form>
      <section className="content-card">
        <h2>Durable wakeups</h2>
        {wakeups.data?.items.length ? (
          <ol>
            {wakeups.data.items.map((wakeup) => (
              <li key={wakeup.id}>
                {wakeup.kind} · {wakeup.status} · directive v
                {wakeup.directive_version} ·{" "}
                {wakeup.source_event_cursor == null
                  ? "no event cursor"
                  : `event ${wakeup.source_event_cursor}`}
              </li>
            ))}
          </ol>
        ) : (
          <p>No wakeups recorded.</p>
        )}
      </section>
      {notice && (
        <p className="inline-alert" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
