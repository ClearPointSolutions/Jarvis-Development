import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactFlowProps } from "@xyflow/react";
import type { WorkflowLayout, WorkflowSpec } from "@jarvis/contracts";
import { WorkflowCanvas } from "./workflow-canvas";

const captured = vi.hoisted(() => ({ props: {} as ReactFlowProps }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: (props: ReactFlowProps) => {
    captured.props = props;
    return null;
  },
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

describe("workflow layout updates", () => {
  it("retains a keyboard move when a viewport callback arrives before rerender", () => {
    const spec: WorkflowSpec = {
      spec_version: "1.1",
      key: "layout-test",
      name: "Layout test",
      entrypoint: "finish",
      nodes: [
        {
          id: "finish",
          type: "finalize",
          label: "Finish",
          config: { outcome: "derive" },
        },
      ],
      edges: [],
      outputs: { result_path: "$.final" },
    };
    let current: WorkflowLayout = { nodes: { finish: { x: 0, y: 0 } } };
    render(
      <WorkflowCanvas
        spec={spec}
        layout={current}
        readOnly={false}
        selection={{ kind: "node", id: "finish" }}
        onSelect={() => {}}
        onLayout={(update) => {
          current = typeof update === "function" ? update(current) : update;
        }}
        onConnect={() => {}}
        onRemove={() => {}}
      />,
    );
    captured.props.onNodesChange?.([
      { type: "position", id: "finish", position: { x: 5, y: 0 } },
    ]);
    captured.props.onMoveEnd?.(new MouseEvent("mouseup"), {
      x: 20,
      y: 30,
      zoom: 1,
    });
    expect(current).toEqual({
      nodes: { finish: { x: 5, y: 0 } },
      viewport: { x: 20, y: 30, zoom: 1 },
    });
  });
});
