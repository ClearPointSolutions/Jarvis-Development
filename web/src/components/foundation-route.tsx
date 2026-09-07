import { EmptyState } from "@/components/states";

const routeCopy = {
  projects: ["Projects", "No project data is available in the M2 shell."],
  workers: [
    "Workers",
    "Worker registration and connectivity are not available yet.",
  ],
  providers: [
    "Providers and models",
    "Provider configuration is not available yet.",
  ],
  debug: ["Developer views", "Runtime diagnostics are not available yet."],
  runs: ["Runs", "No durable runs have been loaded."],
  workflows: [
    "Workflows",
    "Workflow editing begins only after its approved milestone.",
  ],
  registry: ["Registry", "Configuration controls are not exposed before M3."],
  approvals: ["Approvals", "Approval review is not available yet."],
  artifacts: ["Artifacts", "No authorized artifact metadata is available."],
  health: [
    "Health",
    "Detailed dependency health arrives in a later milestone.",
  ],
  settings: ["Settings", "No mutable settings are exposed in this foundation."],
} as const;

export type FoundationRouteName = keyof typeof routeCopy;

export function FoundationRoute({ route }: { route: FoundationRouteName }) {
  const [title, description] = routeCopy[route];
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Mission Control</p>
        <h1>{title}</h1>
        <p>
          Server-authoritative data will appear here when its milestone is
          implemented.
        </p>
      </header>
      <EmptyState description={description} title="Not available yet" />
    </div>
  );
}
