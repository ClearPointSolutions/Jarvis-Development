"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type {
  ApiErrorResponse,
  NormalizedEvent,
  RunEventSnapshotResponse,
} from "@jarvis/contracts";
import { EventRow } from "@/components/event-row";
import { StatusLabel } from "@/components/states";
import { ApiRequestError } from "@/lib/api/client";
import { mergeEvent, parseStreamEvent } from "@/lib/api/events";
import { sessionQueryKey } from "@/lib/session";

async function snapshot(runId: string): Promise<RunEventSnapshotResponse> {
  const response = await fetch(
    `/api/v1/runs/${encodeURIComponent(runId)}/event-snapshot`,
    { credentials: "same-origin", headers: { Accept: "application/json" } },
  );
  if (!response.ok) {
    const error = (await response
      .json()
      .catch(() => null)) as ApiErrorResponse | null;
    throw new ApiRequestError(
      error?.error.message ?? "Run data is unavailable.",
      response.status,
      error?.error.code ?? "request.failed",
    );
  }
  return response.json() as Promise<RunEventSnapshotResponse>;
}

export function EventFeed({ runId }: { runId?: string }) {
  const client = useQueryClient();
  const [connection, setConnection] = useState("Waiting for a run");
  const recoveryCursor = useRef<number | undefined>(undefined);
  const [generation, setGeneration] = useState(0);
  const projection = useQuery({
    queryKey: ["run-projection", runId],
    queryFn: () => snapshot(runId!),
    enabled: !!runId,
    refetchInterval: 15_000,
  });
  const events = useQuery<NormalizedEvent[]>({
    queryKey: ["run-events", runId],
    queryFn: () => [],
    enabled: false,
    initialData: [],
  });
  const ready = projection.isSuccess;
  useEffect(() => {
    if (
      projection.error instanceof ApiRequestError &&
      projection.error.status === 401
    )
      void client.invalidateQueries({ queryKey: sessionQueryKey });
  }, [projection.error, client]);
  useEffect(() => {
    if (!runId || !ready) return;
    const key = ["run-events", runId];
    const history = client.getQueryData<NormalizedEvent[]>(key) ?? [];
    const after =
      recoveryCursor.current ?? history.at(-1)?.global_position ?? 0;
    recoveryCursor.current = undefined;
    const source = new EventSource(
      `/api/v1/runs/${encodeURIComponent(runId)}/events/stream?after=${after}`,
    );
    let stopped = false;
    source.onopen = () => {
      setConnection("Live");
      void client.invalidateQueries({ queryKey: ["run-projection", runId] });
    };
    source.onerror = () => {
      if (stopped) return;
      setConnection("Reconnecting");
      void client.invalidateQueries({ queryKey: sessionQueryKey });
    };
    source.addEventListener("jarvis.event", (message) => {
      try {
        const event = parseStreamEvent((message as MessageEvent<string>).data);
        client.setQueryData<NormalizedEvent[]>(key, (previous = []) =>
          mergeEvent(previous, event),
        );
        void client.invalidateQueries({ queryKey: ["run-projection", runId] });
      } catch (error) {
        stopped = true;
        source.close();
        setConnection(
          error instanceof Error ? error.message : "Invalid event envelope",
        );
      }
    });
    source.addEventListener("stream.reset", (message) => {
      stopped = true;
      source.close();
      try {
        const reset = JSON.parse((message as MessageEvent<string>).data) as {
          reason?: string;
        };
        if (reset.reason === "unsupported_schema") {
          setConnection(
            "Unsupported event schema. Update Mission Control before reconnecting.",
          );
          return;
        }
        client.setQueryData(key, []);
        setConnection("Recovering from the authoritative projection");
        void client
          .fetchQuery({
            queryKey: ["run-projection", runId],
            queryFn: () => snapshot(runId),
            staleTime: 0,
          })
          .then((current) => {
            recoveryCursor.current = current.read_cursor;
            setGeneration((value) => value + 1);
          })
          .catch(() => setConnection("Recovery failed. Reconnect to retry."));
      } catch {
        setConnection("Invalid stream reset");
      }
    });
    return () => {
      stopped = true;
      source.close();
    };
  }, [runId, ready, client, generation]);
  return (
    <section className="activity-panel" aria-labelledby="activity-title">
      <div className="section-heading">
        <h2 id="activity-title">Activity</h2>
        <StatusLabel
          label={runId ? connection : "No run selected"}
          tone={connection === "Live" ? "good" : "neutral"}
        />
      </div>
      {!runId ? (
        <p>
          Select a run to follow persisted events. No execution is active in
          this view.
        </p>
      ) : (
        <>
          {projection.isPending ? (
            <p role="status">Loading authorized run projection…</p>
          ) : null}
          {projection.isError ? (
            <p role="alert">
              {projection.error instanceof ApiRequestError
                ? projection.error.message
                : "Run data is unavailable."}
            </p>
          ) : null}
          {projection.data ? (
            <dl className="projection">
              <div>
                <dt>Run status</dt>
                <dd data-testid="run-status">{projection.data.status}</dd>
              </div>
              <div>
                <dt>Last event position</dt>
                <dd data-testid="projection-position">
                  {projection.data.last_event_position}
                </dd>
              </div>
              <div>
                <dt>Run sequence</dt>
                <dd data-testid="run-sequence">
                  {projection.data.last_run_sequence}
                </dd>
              </div>
            </dl>
          ) : null}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              void projection.refetch();
              setGeneration((value) => value + 1);
            }}
          >
            Reconnect and refresh
          </button>
          <div
            className="activity-list"
            role="region"
            tabIndex={0}
            aria-label="Persisted run events"
          >
            {events.data.length ? (
              events.data.map((event) => (
                <EventRow event={event} key={event.event_id} />
              ))
            ) : (
              <p>No events have been received.</p>
            )}
          </div>
          <p className="fixture-disclaimer">
            Latest 200 received events. Projection values are read from the
            server.
          </p>
        </>
      )}
    </section>
  );
}
