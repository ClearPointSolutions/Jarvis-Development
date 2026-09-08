import type {
  CommandPage,
  JobCreate,
  ProjectCreate,
  ProjectPage,
  ProjectView,
  RunControl,
  RunPage,
  RunView,
  RunCommandReceipt,
} from "@jarvis/contracts";
import { ApiRequestError } from "./client";

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
  return {
    projects: () => request<ProjectPage>("/projects"),
    createProject: (body: ProjectCreate) =>
      request<ProjectView>("/projects", body),
    start: (project: string, body: JobCreate) =>
      request<RunView>(`/projects/${encodeURIComponent(project)}/jobs`, body),
    runs: () => request<RunPage>("/runs"),
    get: (id: string) => request<RunView>(`/runs/${encodeURIComponent(id)}`),
    commands: (id: string) =>
      request<CommandPage>(`/runs/${encodeURIComponent(id)}/commands`),
    command: (id: string, body: RunControl) =>
      request<RunCommandReceipt>(
        `/runs/${encodeURIComponent(id)}/commands`,
        body,
      ),
  };
}
