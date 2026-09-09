import type {
  SystemHealth,
  ApprovalPage,
  ApprovalView,
  ApprovalDecisionRequest,
  RunUsage,
  CommandPage,
  JobCreate,
  ProjectCreate,
  ProjectPage,
  ProjectView,
  RunControl,
  RunPage,
  RunView,
  RunCommandReceipt,
  TaskPage,
  NodePage,
  WorkflowSpec,
  DemoDecision,
  DemoDecisionView,
  EventPage,
  IntegrationHeadPage,
} from "@jarvis/contracts";
import { ApiRequestError } from "./client";
import { collectPages } from "./pagination";

export function createRuntimeClient(csrfToken?: string) {
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`/api/v1${path}`, {
      method: body ? "POST" : "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(body
          ? {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrfToken ?? "",
            }
          : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok)
      throw new ApiRequestError(
        response.status === 409
          ? "The run changed. Refresh and try the command again."
          : "The runtime request failed. Check your session and published configuration.",
        response.status,
        "runtime.request_failed",
      );
    return response.json() as Promise<T>;
  }
  function pages<
    P extends { items: unknown[]; next_after?: string | number | null },
  >(path: string) {
    return collectPages<P>((after) =>
      request<P>(
        `${path}${after === undefined ? "" : `${path.includes("?") ? "&" : "?"}after=${encodeURIComponent(after)}`}`,
      ),
    );
  }
  return {
    health: () => request<SystemHealth>("/system/health"),
    usage: (id: string) =>
      request<RunUsage>(`/runs/${encodeURIComponent(id)}/usage`),
    approvals: (id: string) =>
      request<ApprovalPage>(`/runs/${encodeURIComponent(id)}/approvals`),
    approve: (id: string, approvalId: string, body: ApprovalDecisionRequest) =>
      request<ApprovalView>(
        `/runs/${encodeURIComponent(id)}/approvals/${encodeURIComponent(approvalId)}/decisions`,
        body,
      ),
    integrationHeads: (id: string) =>
      request<IntegrationHeadPage>(
        `/runs/${encodeURIComponent(id)}/integration-heads`,
      ),
    evidence: (id: string) =>
      pages<EventPage>(`/runs/${encodeURIComponent(id)}/events?limit=1000`),
    tasks: (id: string) =>
      pages<TaskPage>(`/runs/${encodeURIComponent(id)}/tasks`),
    nodes: (id: string) =>
      pages<NodePage>(`/runs/${encodeURIComponent(id)}/nodes?limit=100`),
    workflow: (id: string) =>
      request<WorkflowSpec>(`/runs/${encodeURIComponent(id)}/workflow`),
    decision: (id: string) =>
      request<DemoDecisionView | null>(
        `/runs/${encodeURIComponent(id)}/demo-decision`,
      ),
    decide: (id: string, body: DemoDecision) =>
      request<DemoDecisionView>(
        `/runs/${encodeURIComponent(id)}/demo-decision`,
        body,
      ),
    projects: () => pages<ProjectPage>("/projects"),
    createProject: (body: ProjectCreate) =>
      request<ProjectView>("/projects", body),
    start: (project: string, body: JobCreate) =>
      request<RunView>(`/projects/${encodeURIComponent(project)}/jobs`, body),
    runs: () => pages<RunPage>("/runs"),
    get: (id: string) => request<RunView>(`/runs/${encodeURIComponent(id)}`),
    commands: (id: string) =>
      pages<CommandPage>(`/runs/${encodeURIComponent(id)}/commands`),
    command: (id: string, body: RunControl) =>
      request<RunCommandReceipt>(
        `/runs/${encodeURIComponent(id)}/commands`,
        body,
      ),
  };
}
