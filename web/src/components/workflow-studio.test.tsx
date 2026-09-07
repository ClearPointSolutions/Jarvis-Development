import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type {
  NodeTypeDefinition,
  WorkflowDocument,
  WorkflowDraftWrite,
  WorkflowValidationReport,
} from "@jarvis/contracts";
import type { WorkflowClient } from "@/lib/api/workflows";
import { WorkflowRequestError } from "@/lib/api/workflows";
import { AppProviders } from "./app-providers";
import { WorkflowEditor } from "./workflow-studio";
import type { WorkflowCanvas } from "./workflow-canvas";

vi.mock("./workflow-canvas", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./workflow-canvas")>()),
  WorkflowCanvas: (props: Parameters<typeof WorkflowCanvas>[0]) => (
    <div aria-label="Workflow graph">
      {props.spec.nodes.map((node) => (
        <button
          key={node.id}
          data-invalid={props.issues?.some(
            (issue) => issue.node_id === node.id,
          )}
          onClick={() => props.onSelect({ kind: "node", id: node.id })}
        >
          {node.label}
        </button>
      ))}
    </div>
  ),
}));
const timestamp = "2026-09-07T12:00:00Z";
const initial: WorkflowDocument = {
  template: {
    id: "11111111-1111-4111-8111-111111111111",
    key: "test-workflow",
    name: "Test workflow",
    description: "",
    version: 1,
    archived: false,
    created_at: timestamp,
    updated_at: timestamp,
  },
  version: {
    id: "22222222-2222-4222-8222-222222222222",
    workflow_template_id: "11111111-1111-4111-8111-111111111111",
    version: 1,
    content_hash: "a".repeat(64),
    compiler_version: "1.0.0",
    published: false,
    created_at: timestamp,
    spec: {
      spec_version: "1.1",
      key: "test-workflow",
      name: "Test workflow",
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
    },
    layout: { nodes: { finish: { x: 120, y: 80 } } },
  },
};
const router: NodeTypeDefinition = {
  type: "router",
  config_schema: { properties: {} },
  default_config: {},
  policy_schema: {},
  external_behavior: false,
  input_channels: ["results"],
  output_channels: ["results"],
  required_capabilities: [],
};
const definitions: NodeTypeDefinition[] = [
  router,
  {
    ...router,
    type: "architect",
    default_config: { max_tasks: 100 },
    config_schema: {
      properties: {
        max_tasks: {
          type: "integer",
          minimum: 1,
          maximum: 10000,
          default: 100,
        },
      },
    },
  },
];
function makeClient(overrides: Partial<WorkflowClient> = {}): WorkflowClient {
  return {
    list: vi.fn().mockResolvedValue({ items: [initial.template] }),
    nodeTypes: vi.fn().mockResolvedValue({ items: definitions }),
    create: vi.fn().mockResolvedValue(initial),
    get: vi.fn().mockResolvedValue(initial),
    save: vi
      .fn()
      .mockImplementation(async (_id, write: WorkflowDraftWrite) => ({
        ...initial,
        template: { ...initial.template, version: 2 },
        version: { ...initial.version, spec: write.spec, layout: write.layout },
      })),
    newDraft: vi.fn().mockResolvedValue({
      ...initial,
      version: { ...initial.version, id: "new-draft", version: 2 },
    }),
    validate: vi.fn().mockResolvedValue({ valid: true, issues: [] }),
    publish: vi.fn().mockResolvedValue({
      ...initial,
      version: { ...initial.version, published: true },
    }),
    archive: vi.fn().mockResolvedValue({ ...initial.template, archived: true }),
    versions: vi.fn().mockResolvedValue({ items: [initial.version] }),
    version: vi.fn().mockResolvedValue(initial),
    ...overrides,
  };
}
function setup(api = makeClient(), document = initial) {
  const onDocument = vi.fn();
  render(
    <AppProviders>
      <WorkflowEditor
        document={structuredClone(document)}
        client={api}
        definitions={definitions}
        references={[]}
        onClose={vi.fn()}
        onDocument={onDocument}
        onSaved={vi.fn()}
      />
    </AppProviders>,
  );
  return { user: userEvent.setup(), api, onDocument };
}

describe("canonical Workflow Studio", () => {
  it("preserves a local draft when another session wins the optimistic save", async () => {
    const { user, api } = setup(
      makeClient({
        save: vi
          .fn()
          .mockRejectedValue(
            new WorkflowRequestError(
              "This workflow changed in another session. Your edits are preserved.",
              409,
            ),
          ),
      }),
    );
    await user.click(screen.getByRole("button", { name: "Add Router" }));
    await user.clear(screen.getByLabelText("Node label"));
    await user.type(screen.getByLabelText("Node label"), "Local unsaved work");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("another session"),
    );
    expect(screen.getByLabelText("Node label")).toHaveValue(
      "Local unsaved work",
    );
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    expect(api.publish).not.toHaveBeenCalled();
  });
  it("displays final transactional publication rejection without claiming success", async () => {
    const report = {
      valid: false,
      issues: [
        {
          code: "reference.inactive",
          message: "Selected revision became inactive",
          node_id: "finish",
        },
      ],
    };
    const { user } = setup(
      makeClient({
        publish: vi
          .fn()
          .mockRejectedValue(
            new WorkflowRequestError("Publication rejected", 422, report),
          ),
      }),
    );
    await user.click(screen.getByRole("button", { name: "Publish version" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Publication rejected",
      ),
    );
    expect(screen.getByLabelText("Workflow validation")).toHaveTextContent(
      "Selected revision became inactive",
    );
    expect(
      screen.queryByText("Published · read only", { exact: false }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Router" })).toBeEnabled();
  });
  it("adds schema-typed nodes, connects, moves, and saves the canonical spec with separate layout", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("button", { name: "Add Architect" }));
    await user.clear(screen.getByLabelText("Max tasks"));
    await user.type(screen.getByLabelText("Max tasks"), "12");
    await user.clear(screen.getByLabelText("Node label"));
    await user.type(screen.getByLabelText("Node label"), "Plan tasks");
    await user.clear(screen.getByLabelText("Position x"));
    await user.type(screen.getByLabelText("Position x"), "420");
    await user.click(screen.getByText("Keyboard outline and connections"));
    await user.selectOptions(
      screen.getByLabelText("Connect from"),
      "architect",
    );
    await user.selectOptions(screen.getByLabelText("Connect to"), "finish");
    await user.click(screen.getByRole("button", { name: "Connect nodes" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledWith(
      initial.template.id,
      expect.objectContaining({
        expected_version: 1,
        spec: expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "architect",
              type: "architect",
              label: "Plan tasks",
              config: { max_tasks: 12 },
            }),
          ]),
          edges: [
            expect.objectContaining({
              from: "architect",
              to: "finish",
              kind: "always",
            }),
          ],
        }),
        layout: expect.objectContaining({
          nodes: expect.objectContaining({ architect: { x: 420, y: 0 } }),
        }),
      }),
    );
  });
  it("preserves edits on rejection and selects backend-addressed problems", async () => {
    const report: WorkflowValidationReport = {
      valid: false,
      issues: [
        {
          code: "graph.unreachable",
          message: "Node is unreachable",
          node_id: "router",
        },
      ],
    };
    const { user, api } = setup(
      makeClient({
        validate: vi.fn().mockResolvedValue(report),
        publish: vi
          .fn()
          .mockRejectedValue(new WorkflowRequestError("Rejected", 422, report)),
      }),
    );
    await user.click(screen.getByRole("button", { name: "Add Router" }));
    await user.click(screen.getByRole("button", { name: "Publish version" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Workflow validation")).toHaveTextContent(
        "Node is unreachable",
      ),
    );
    expect(api.publish).not.toHaveBeenCalled();
    expect(
      within(screen.getByLabelText("Workflow graph")).getByRole("button", {
        name: "Router",
      }),
    ).toHaveAttribute("data-invalid", "true");
    await user.click(
      screen.getByRole("button", { name: "Node is unreachable" }),
    );
    expect(screen.getByLabelText("Node label")).toHaveValue("Router");
    expect(screen.getByText("Unsaved changes")).toBeVisible();
  });
  it("keeps published controls disabled and requests a new numbered draft", async () => {
    const published = {
      ...initial,
      version: { ...initial.version, published: true },
    };
    const { user, api, onDocument } = setup(makeClient(), published);
    expect(screen.getByRole("button", { name: "Add Router" })).toBeDisabled();
    await user.click(
      within(screen.getByLabelText("Workflow graph")).getByRole("button", {
        name: "Finish",
      }),
    );
    expect(screen.getByLabelText("Node label")).toBeDisabled();
    expect(screen.getByLabelText("Position x")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Create new draft" }));
    await waitFor(() => expect(onDocument).toHaveBeenCalled());
    expect(api.newDraft).toHaveBeenCalledWith(
      initial.template.id,
      expect.objectContaining({
        source_version_id: initial.version.id,
        expected_version: 1,
      }),
    );
    expect(initial.version.spec.nodes[0].label).toBe("Finish");
  });
  it("builds safe nested conditions and disconnects canonical edges", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("button", { name: "Add Router" }));
    await user.click(screen.getByText("Keyboard outline and connections"));
    await user.selectOptions(screen.getByLabelText("Connect from"), "router");
    await user.selectOptions(screen.getByLabelText("Connect to"), "finish");
    await user.click(screen.getByRole("button", { name: "Connect nodes" }));
    await user.selectOptions(screen.getByLabelText("Edge kind"), "on_result");
    await user.selectOptions(
      screen.getByLabelText("Condition operator", { exact: true }),
      "and",
    );
    await user.selectOptions(
      screen.getByLabelText("Condition 1 state path"),
      "$.approval.decision",
    );
    await user.clear(
      screen.getByLabelText("Condition 1 value", { exact: true }),
    );
    await user.type(
      screen.getByLabelText("Condition 1 value", { exact: true }),
      "approved",
    );
    await user.selectOptions(
      screen.getByLabelText("Condition 2 operator"),
      "exists",
    );
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledWith(
      initial.template.id,
      expect.objectContaining({
        spec: expect.objectContaining({
          edges: [
            expect.objectContaining({
              when: {
                op: "and",
                args: [
                  { op: "eq", path: "$.approval.decision", value: "approved" },
                  { op: "exists", path: "$.node.result", value: null },
                ],
              },
            }),
          ],
        }),
      }),
    );
    await user.click(screen.getByRole("button", { name: "Disconnect edge" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenLastCalledWith(
        initial.template.id,
        expect.objectContaining({
          expected_version: 2,
          spec: expect.objectContaining({ edges: [] }),
        }),
      ),
    );
  });
  it("renders labels and descriptions as inert text", () => {
    const malicious = "<img src=x onerror=alert(1)>";
    setup(makeClient(), {
      ...initial,
      version: {
        ...initial.version,
        spec: {
          ...initial.version.spec,
          name: malicious,
          description: malicious,
          nodes: [{ ...initial.version.spec.nodes[0], label: malicious }],
        },
      },
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: malicious })).toBeVisible();
  });
});
