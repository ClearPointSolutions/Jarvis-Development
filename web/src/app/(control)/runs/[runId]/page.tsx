import { EventFeed } from "@/components/event-feed";
import { RunControls } from "@/components/run-controls";
import { RunExperience } from "@/components/run-experience";
export default async function RunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Durable history</p>
        <h1>Run event monitor</h1>
        <p>{runId}</p>
      </header>
      <RunControls runId={runId} />
      <RunExperience runId={runId} />
      <EventFeed runId={runId} />
    </div>
  );
}
