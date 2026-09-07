import type {
  WorkflowArchiveRequest,
  WorkflowCommand,
  WorkflowCreateRequest,
  WorkflowDocument,
  WorkflowDraftWrite,
  WorkflowNewDraft,
  WorkflowTemplatePage,
  WorkflowTemplateRecord,
  WorkflowValidateRequest,
  WorkflowValidationReport,
  WorkflowVersionPage,
  NodeTypePage,
} from "@jarvis/contracts";
import { ApiRequestError } from "./client";

export class WorkflowRequestError extends ApiRequestError {
  constructor(
    message: string,
    status: number,
    readonly validation?: WorkflowValidationReport,
  ) {
    super(message, status, "workflow.request_failed");
  }
}

/** The wire payloads are generated from Pydantic; the canvas has no wire schema. */
export function createWorkflowClient(csrfToken?: string) {
  const root = "/api/v1/workflow-templates";
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    const response = await fetch(`${root}${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as {
        error?: { details?: { validation?: WorkflowValidationReport } };
      } | null;
      throw new WorkflowRequestError(
        response.status === 409
          ? "This workflow changed in another session. Your edits are preserved. Reopen the current version before saving again."
          : response.status === 422
            ? "The server rejected this workflow. Validate the draft to see the affected nodes and edges."
            : response.status === 401
              ? "Your session expired. Sign in again."
              : response.status === 403
                ? "Owner permission and a current session are required."
                : "The workflow request failed. Your edits are preserved; try again.",
        response.status,
        payload?.error?.details?.validation,
      );
    }
    return response.json() as Promise<T>;
  }
  const page = (after?: string) =>
    `?limit=100${after ? `&after=${encodeURIComponent(after)}` : ""}`;
  const idPath = (id: string) => `/${encodeURIComponent(id)}`;
  return {
    list: (after?: string) => request<WorkflowTemplatePage>(page(after)),
    nodeTypes: () => request<NodeTypePage>("/node-types"),
    create: (body: WorkflowCreateRequest) =>
      request<WorkflowDocument>("", "POST", body),
    get: (id: string) => request<WorkflowDocument>(idPath(id)),
    save: (id: string, body: WorkflowDraftWrite) =>
      request<WorkflowDocument>(`${idPath(id)}/draft`, "PUT", body),
    newDraft: (id: string, body: WorkflowNewDraft) =>
      request<WorkflowDocument>(`${idPath(id)}/draft`, "POST", body),
    validate: (id: string, body: WorkflowValidateRequest) =>
      request<WorkflowValidationReport>(`${idPath(id)}/validate`, "POST", body),
    publish: (id: string, body: WorkflowCommand) =>
      request<WorkflowDocument>(`${idPath(id)}/publish`, "POST", body),
    archive: (id: string, body: WorkflowArchiveRequest) =>
      request<WorkflowTemplateRecord>(idPath(id), "PUT", body),
    versions: (id: string, after?: string) =>
      request<WorkflowVersionPage>(`${idPath(id)}/versions${page(after)}`),
    version: (id: string, versionId: string) =>
      request<WorkflowDocument>(
        `${idPath(id)}/versions/${encodeURIComponent(versionId)}`,
      ),
  };
}
export type WorkflowClient = ReturnType<typeof createWorkflowClient>;
