import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@jarvis/contracts";

describe("generated shared contract", () => {
  it("provides the versioned workflow shape to TypeScript", () => {
    const workflow: WorkflowSpec = {
      spec_version: "1.0",
      key: "typed_workflow",
      name: "Typed workflow",
      entrypoint: "finish",
      nodes: [{ id: "finish", type: "finalize", label: "Finish", config: {} }],
      edges: [],
      outputs: { result_path: "$.final" },
    };

    expect(workflow.nodes[0].type).toBe("finalize");
  });
});
