import type {
  DirectiveUpdate,
  ManagementTurnPage,
  ManagementTurnView,
  MissionCreate,
  MissionMessageCreate,
  MissionMessagePage,
  MissionPage,
  MissionView,
  RunView,
  WorkItemPage,
  WorkItemStart,
} from "@jarvis/contracts";
import { ApiRequestError } from "./client";

export function createMissionClient(csrfToken?: string) {
  async function request<T>(path: string, method = "GET", body?: unknown) {
    const response = await fetch(`/api/v1/missions${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok)
      throw new ApiRequestError(
        response.status === 409
          ? "The mission changed. Refresh and try again."
          : response.status === 422
            ? "The selected team or mission input is not valid."
            : "The mission request failed.",
        response.status,
        "mission.request_failed",
      );
    return response.json() as Promise<T>;
  }
  return {
    list: () => request<MissionPage>("?limit=100"),
    create: (body: MissionCreate) => request<MissionView>("", "POST", body),
    get: (id: string) => request<MissionView>(`/${encodeURIComponent(id)}`),
    directive: (id: string, body: DirectiveUpdate) =>
      request<MissionView>(`/${encodeURIComponent(id)}/directive`, "PUT", body),
    messages: (id: string) =>
      request<MissionMessagePage>(
        `/${encodeURIComponent(id)}/messages?limit=100`,
      ),
    message: (id: string, body: MissionMessageCreate) =>
      request<ManagementTurnView>(
        `/${encodeURIComponent(id)}/messages`,
        "POST",
        body,
      ),
    turns: (id: string) =>
      request<ManagementTurnPage>(`/${encodeURIComponent(id)}/turns?limit=100`),
    items: (id: string) =>
      request<WorkItemPage>(`/${encodeURIComponent(id)}/work-items?limit=100`),
    start: (id: string, item: string, body: WorkItemStart) =>
      request<RunView>(
        `/${encodeURIComponent(id)}/work-items/${encodeURIComponent(item)}/start`,
        "POST",
        body,
      ),
  };
}
