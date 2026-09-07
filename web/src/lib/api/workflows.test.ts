import { afterEach, describe, expect, it, vi } from "vitest";
import { createWorkflowClient, WorkflowRequestError } from "./workflows";

afterEach(() => vi.unstubAllGlobals());
describe("workflow contract client", () => {
  it("sends same-origin CSRF-protected generated create commands", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ template: {}, version: {} }), {
          status: 201,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    const body = {
      key: "workflow",
      name: "Workflow",
      idempotency_key: "replayable-command",
    };
    await createWorkflowClient("csrf-test").create(body);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/workflow-templates",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "X-CSRF-Token": "csrf-test",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify(body),
      }),
    );
  });
  it("preserves addressed server validation and emits a useful conflict error", async () => {
    const validation = {
      valid: false,
      issues: [
        {
          code: "graph.unreachable",
          message: "Node is unreachable",
          node_id: "review",
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ error: { details: { validation } } }), {
            status: 422,
          }),
        )
        .mockResolvedValueOnce(new Response("{}", { status: 409 })),
    );
    const client = createWorkflowClient();
    await expect(
      client.publish("workflow", {
        expected_version: 1,
        idempotency_key: "command-1",
      }),
    ).rejects.toEqual(expect.objectContaining({ validation, status: 422 }));
    await expect(
      client.publish("workflow", {
        expected_version: 1,
        idempotency_key: "command-2",
      }),
    ).rejects.toThrow(WorkflowRequestError);
  });
});
