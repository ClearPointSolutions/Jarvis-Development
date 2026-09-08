"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { RunControl } from "@jarvis/contracts";
import { useSession } from "@/lib/session";
import { createRuntimeClient } from "@/lib/api/runtime";
import { ApiRequestError } from "@/lib/api/client";

export function RunControls({ runId }: { runId: string }) {
  const session = useSession();
  const client = useMemo(
    () => createRuntimeClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const run = useQuery({
    queryKey: ["runtime-run", runId],
    queryFn: () => client.get(runId),
    enabled: Boolean(session.data),
    refetchInterval: 1000,
  });
  const [message, setMessage] = useState("");
  const commands = useQuery({
    queryKey: ["runtime-commands", runId],
    queryFn: () => client.commands(runId),
    enabled: Boolean(session.data),
    refetchInterval: 1000,
  });
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  async function command(kind: RunControl["kind"]) {
    if (!run.data) return;
    setBusy(true);
    try {
      const idempotencyKey = crypto.randomUUID();
      const send = async () =>
        client.command(runId, {
          kind,
          expected_run_version: (await client.get(runId)).version,
          idempotency_key: idempotencyKey,
          ...(kind === "instruction" ? { instruction } : {}),
        });
      let receipt;
      try {
        receipt = await send();
      } catch (error) {
        if (!(error instanceof ApiRequestError) || error.status !== 409)
          throw error;
        // Claim/start can race the initial projection. One fresh-version retry
        // preserves the user's command and its idempotency identity.
        receipt = await send();
      }
      setMessage(`Command ${receipt.sequence} recorded.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Command failed");
    } finally {
      await run.refetch();
      setBusy(false);
    }
  }
  if (run.isPending) return <p role="status">Loading run controls…</p>;
  if (!run.data) return <p role="alert">Run controls are unavailable.</p>;
  const value = run.data;
  const terminal = ["completed", "failed", "blocked", "cancelled"].includes(
    value.status,
  );
  return (
    <section className="content-card" aria-label="Run controls">
      <h2>Execution control</h2>
      <p>
        Actual state:{" "}
        <strong>{value.recovering ? "recovering" : value.status}</strong> ·
        Desired state: <strong>{value.desired_state}</strong>
      </p>
      {value.current_node && <p>Current node: {value.current_node}</p>}
      {value.result_summary && <p>{value.result_summary}</p>}
      <div className="button-row">
        <button
          className="button"
          disabled={
            busy ||
            terminal ||
            value.status === "paused" ||
            value.desired_state !== "running"
          }
          onClick={() => void command("pause")}
        >
          Pause
        </button>
        <button
          className="button"
          disabled={busy || value.status !== "paused"}
          onClick={() => void command("resume")}
        >
          Resume
        </button>
        <button
          className="button"
          disabled={busy || terminal || value.desired_state === "cancelled"}
          onClick={() => void command("cancel")}
        >
          Cancel
        </button>
        <button
          className="button"
          disabled={busy || !["failed", "blocked"].includes(value.status)}
          onClick={() => void command("retry")}
        >
          Retry as new run
        </button>
      </div>
      <div className="field-group">
        <label htmlFor="runtime-instruction">Instruction</label>
        <input
          id="runtime-instruction"
          value={instruction}
          maxLength={4000}
          onChange={(event) => setInstruction(event.target.value)}
        />
      </div>
      <button
        className="button"
        disabled={busy || terminal || !instruction.trim()}
        onClick={() => void command("instruction")}
      >
        Queue instruction
      </button>
      <p role="status">{message}</p>
      <ul aria-label="Command acknowledgements">
        {commands.data?.items.map((item) => (
          <li key={item.id}>
            Command {item.sequence}: {item.kind} — {item.status}
          </li>
        ))}
      </ul>
    </section>
  );
}
