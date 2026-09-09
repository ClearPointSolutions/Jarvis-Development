"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/lib/session";
import { createRuntimeClient } from "@/lib/api/runtime";
import type { ApprovalView } from "@jarvis/contracts";

export function RunApprovals({ runId }: { runId: string }) {
  const session = useSession();
  const queries = useQueryClient();
  const client = useMemo(
    () => createRuntimeClient(session.data?.csrf_token),
    [session.data?.csrf_token],
  );
  const approvals = useQuery({
    queryKey: ["runtime-approvals", runId],
    queryFn: () => client.approvals(runId),
    enabled: Boolean(session.data),
    refetchInterval: 3000,
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function decide(
    approval: ApprovalView,
    decision: "approved" | "rejected",
  ) {
    setBusy(true);
    try {
      const run = await client.get(runId);
      await client.approve(runId, approval.id, {
        decision,
        request_digest: approval.request_digest,
        expected_run_version: run.version,
        idempotency_key: crypto.randomUUID(),
      });
      setMessage(
        `Decision ${decision} recorded. The orchestrator will resume the persisted workflow.`,
      );
      await queries.invalidateQueries({
        queryKey: ["runtime-approvals", runId],
      });
      await queries.invalidateQueries({ queryKey: ["runtime-run", runId] });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="content-card run-experience-card"
      aria-label="Production approvals"
    >
      <h2>Approvals</h2>
      <p>
        Decisions authorize the exact action and source identity shown below.
      </p>
      {approvals.error && <p role="alert">Approvals could not be loaded.</p>}
      {approvals.data?.items.length === 0 && (
        <p>No approval has been requested.</p>
      )}
      {approvals.data?.items.map((approval) => (
        <article key={approval.id}>
          <h3>{approval.action_type}</h3>
          <p>Status: {approval.decision}</p>
          <p>
            Expires:{" "}
            {approval.expires_at
              ? new Date(approval.expires_at).toLocaleString()
              : "No expiry"}
          </p>
          <details>
            <summary>Review exact parameters and digest</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(approval.parameters, null, 2)}
            </pre>
            <p style={{ overflowWrap: "anywhere" }}>
              Digest: {approval.request_digest}
            </p>
          </details>
          {approval.decision === "pending" && (
            <div className="button-row">
              <button
                disabled={busy}
                onClick={() => void decide(approval, "approved")}
              >
                Approve action
              </button>
              <button
                disabled={busy}
                onClick={() => void decide(approval, "rejected")}
              >
                Reject action
              </button>
            </div>
          )}
        </article>
      ))}
      <p role="status">{message}</p>
    </section>
  );
}
