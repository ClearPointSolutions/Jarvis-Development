import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RegistryRecord, RegistryWrite } from "@jarvis/contracts";
import { AppProviders } from "./app-providers";
import { RegistryEditor, RegistryPage } from "./registry-page";
import { defaultSpec } from "./registry-fields";
import type { RegistryClient } from "@/lib/api/registry";

const provider: RegistryRecord = {
  id: "11111111-1111-4111-8111-111111111111",
  revision_id: "22222222-2222-4222-8222-222222222222",
  revision: 1,
  version: 1,
  key: "demo",
  display_name: "Demo provider",
  description: "Local deterministic provider",
  enabled: true,
  archived: false,
  spec: defaultSpec("provider_connection") as RegistryWrite["spec"],
  content_hash: "hash",
  created_at: "2026-09-07T12:00:00Z",
  updated_at: "2026-09-07T12:00:00Z",
  health: "unknown",
  secret_status: "configured",
};
const model: RegistryRecord = {
  ...provider,
  id: "33333333-3333-4333-8333-333333333333",
  revision_id: "44444444-4444-4444-8444-444444444444",
  key: "utility",
  display_name: "Utility model",
  spec: {
    ...defaultSpec("model_profile"),
    kind: "model_profile",
    provider_revision_id: provider.revision_id,
    model_identifier: "demo-model",
    purposes: ["utility"],
    context_limit: 32000,
    output_limit: 4096,
  },
};
function client(overrides: Partial<RegistryClient> = {}): RegistryClient {
  return {
    list: vi.fn().mockImplementation(async (kind) => ({
      items: [provider, model].filter((record) => record.spec.kind === kind),
    })),
    save: vi.fn().mockResolvedValue(provider),
    revisions: vi.fn().mockResolvedValue({ items: [provider] }),
    validate: vi.fn().mockResolvedValue({
      valid: true,
      network_checked: false,
      health: "unknown",
    }),
    preview: vi.fn().mockResolvedValue({
      route_revision_id: provider.revision_id,
      decision: "deny",
      reasons: ["No eligible candidate"],
      candidates: [],
      snapshot_hash: "deterministic-hash",
    }),
    ...overrides,
  };
}
function editor(
  kind: Parameters<typeof defaultSpec>[0],
  api: RegistryClient,
  record?: RegistryRecord,
) {
  const saved = vi.fn();
  render(
    <AppProviders>
      <RegistryEditor
        kind={kind}
        record={record}
        client={api}
        onCancel={vi.fn()}
        onSaved={saved}
      />
    </AppProviders>,
  );
  return saved;
}
async function identity(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Stable key"), "new-config");
  await user.type(screen.getByLabelText("Display name"), "New configuration");
}

describe("M3 registry editors", () => {
  it("lets workers retire a pinned historical model revision absent from current choices", async () => {
    const api = client();
    const historical = "55555555-5555-4555-8555-555555555555";
    const worker: RegistryRecord = {
      ...provider,
      spec: {
        kind: "worker",
        execution_host_label: "Local demo",
        model_binding: {
          mode: "control_plane",
          allowed_profile_revision_ids: [historical],
        },
      },
    };
    editor("worker", api, worker);
    const user = userEvent.setup();
    await user.click(
      screen.getByLabelText(`Pinned model revision ${historical}`),
    );
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledWith(
      "worker",
      expect.objectContaining({
        spec: expect.objectContaining({
          model_binding: {
            mode: "control_plane",
            allowed_profile_revision_ids: [],
          },
        }),
      }),
      provider.id,
    );
  });
  it("creates a worker with keyboard-accessible fields and independent capabilities", async () => {
    const api = client();
    const saved = editor("worker", api);
    const user = userEvent.setup();
    expect(screen.getByLabelText("Stable key")).toHaveFocus();
    await identity(user);
    await user.type(
      screen.getByLabelText("Capabilities (comma separated)"),
      "code, review",
    );
    await user.clear(screen.getByLabelText("Maximum concurrency"));
    await user.type(screen.getByLabelText("Maximum concurrency"), "3");
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(api.save).toHaveBeenCalledWith(
      "worker",
      expect.objectContaining({
        expected_version: 0,
        spec: expect.objectContaining({
          capabilities: ["code", "review"],
          max_concurrency: 3,
        }),
      }),
      undefined,
    );
  });
  it("rejects incompatible legacy worker binding before mutation", async () => {
    const api = client();
    editor("worker", api);
    const user = userEvent.setup();
    await identity(user);
    await user.selectOptions(
      screen.getByLabelText("Adapter"),
      "openhands_ssh_v1",
    );
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "exactly one worker-managed",
    );
    expect(api.save).not.toHaveBeenCalled();
  });
  it("never populates secret references and clears write-only values after rejected saves", async () => {
    const api = client({
      save: vi.fn().mockRejectedValue(new Error("Configuration rejected")),
    });
    editor("provider_connection", api, provider);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Replace secret reference");
    expect(input).toHaveValue("");
    await user.type(input, "secret:synthetic-reference");
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Configuration rejected",
    );
    expect(input).toHaveValue("");
    expect(api.save).toHaveBeenCalledWith(
      "provider_connection",
      expect.objectContaining({
        expected_version: 1,
        secret_ref: "secret:synthetic-reference",
      }),
      provider.id,
    );
    expect(document.body.textContent).not.toContain(
      "secret:synthetic-reference",
    );
  });
  it("validates model limits and preserves explicit unknown pricing", async () => {
    const api = client();
    editor("model_profile", api, model);
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Output token limit"));
    await user.type(screen.getByLabelText("Output token limit"), "40000");
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "must not exceed",
    );
    expect(api.save).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Pricing status")).toHaveValue("unknown");
  });
  it("edits ordered candidates and refuses an empty route", async () => {
    const api = client();
    editor("route_policy", api);
    const user = userEvent.setup();
    await identity(user);
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "at least one candidate",
    );
    await user.selectOptions(
      screen.getByLabelText("Add candidate"),
      model.revision_id,
    );
    await user.clear(screen.getByLabelText("Priority 1"));
    await user.type(screen.getByLabelText("Priority 1"), "7");
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledWith(
      "route_policy",
      expect.objectContaining({
        spec: expect.objectContaining({
          candidates: [{ profile_revision_id: model.revision_id, priority: 7 }],
        }),
      }),
      undefined,
    );
  });
  it("creates independent retry rules and conservative permission defaults", async () => {
    const api = client();
    editor("retry_policy", api);
    const user = userEvent.setup();
    await identity(user);
    await user.click(screen.getByRole("button", { name: "Add retry rule" }));
    await user.click(screen.getByLabelText("Allow failover"));
    await user.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => expect(api.save).toHaveBeenCalled());
    expect(api.save).toHaveBeenCalledWith(
      "retry_policy",
      expect.objectContaining({
        spec: expect.objectContaining({
          rules: [
            expect.objectContaining({
              failure_class: "provider.transient",
              allow_failover: true,
            }),
          ],
        }),
      }),
      undefined,
    );
    expect(defaultSpec("permission_policy")).toMatchObject({
      unknown_action: "deny",
      destructive_action: "deny",
      shell: "deny",
    });
  });
  it("shows real validation and historical revision details without live probe claims", async () => {
    const api = client({
      list: vi.fn().mockResolvedValue({ items: [provider] }),
    });
    render(
      <AppProviders>
        <RegistryPage kind="provider_connection" client={api} />
      </AppProviders>,
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Validate Demo provider" }),
    );
    expect(await screen.findByLabelText("Validation result")).toHaveTextContent(
      "No live network probe",
    );
    await user.click(
      screen.getByRole("button", { name: "History Demo provider" }),
    );
    const history = await screen.findByRole("region", {
      name: "Revision history",
    });
    await waitFor(() =>
      expect(within(history).getByText(/Revision 1/)).toBeVisible(),
    );
    expect(screen.getAllByText("Configured · masked")[0]).toBeVisible();
    expect(document.body.textContent).not.toContain("$0.00");
  });
});
