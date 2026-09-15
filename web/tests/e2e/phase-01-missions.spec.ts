import { expect, type Page, test } from "@playwright/test";

const ids = {
  user: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
  project: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb30",
  mission: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb31",
  manager: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb32",
  developer: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb33",
  reviewer: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb34",
  profile: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb35",
  worker: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb36",
  workflow: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb37",
  team: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb40",
  item: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb38",
  run: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb39",
};

async function fixture(page: Page) {
  let created = false;
  let planned = false;
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: { id: ids.user, username: "demo-owner", role: "owner" },
        csrf_token: "browser-fixture-csrf",
        idle_expires_at: "2026-09-14T22:00:00Z",
        absolute_expires_at: "2026-09-15T22:00:00Z",
      }),
    }),
  );
  await page.route("**/api/v1/projects*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: ids.project, slug: "fixture", name: "Fixture project" }],
        next_after: null,
      }),
    }),
  );
  await page.route("**/api/v1/workflow-templates*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: ids.workflow,
            key: "fixture",
            name: "Fixed development team",
            version: 1,
            archived: false,
            current_published_version_id: ids.workflow,
          },
        ],
        next_after: null,
      }),
    }),
  );
  const role = (id: string, responsibility: string) => ({
    id,
    revision_id: id,
    revision: 1,
    version: 1,
    key: responsibility,
    display_name: `${responsibility} role`,
    description: "",
    enabled: true,
    archived: false,
    spec: {
      kind: "agent_role",
      responsibility,
      purpose:
        responsibility === "manager"
          ? "mission_manager"
          : responsibility === "developer"
            ? "code"
            : "reviewer",
      instructions: "Bounded responsibility",
    },
    content_hash: "a".repeat(64),
    created_at: "2026-09-14T20:00:00Z",
    updated_at: "2026-09-14T20:00:00Z",
  });
  await page.route("**/api/v1/registry/agent_role*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          role(ids.manager, "manager"),
          role(ids.developer, "developer"),
          role(ids.reviewer, "reviewer"),
        ],
        next_after: null,
      }),
    }),
  );
  await page.route("**/api/v1/registry/model_profile*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...role(ids.profile, "profile"),
            display_name: "DEMO manager/reviewer",
            spec: {
              kind: "model_profile",
              purposes: ["mission_manager", "reviewer"],
            },
          },
        ],
        next_after: null,
      }),
    }),
  );
  await page.route("**/api/v1/registry/worker*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...role(ids.worker, "worker"),
            display_name: "Exclusive developer",
            spec: { kind: "worker", max_concurrency: 1 },
          },
        ],
        next_after: null,
      }),
    }),
  );
  await page.route("**/api/v1/registry/team_template*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...role(ids.team, "team"),
            display_name: "Fixed development team",
            spec: {
              kind: "team_template",
              mode: "demo",
              manager_role_revision_id: ids.manager,
              manager_profile_revision_id: ids.profile,
              developer_role_revision_id: ids.developer,
              developer_worker_revision_id: ids.worker,
              reviewer_role_revision_id: ids.reviewer,
              reviewer_profile_revision_id: ids.profile,
              workflow_version_id: ids.workflow,
            },
          },
        ],
        next_after: null,
      }),
    }),
  );
  await page.route("**/api/v1/missions**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const mission = {
      id: ids.mission,
      project_id: ids.project,
      objective: "Ship a durable feature",
      constraints: ["Keep evidence"],
      lifecycle: "active",
      mode: "demo",
      version: planned ? 2 : 1,
      directive_version: 1,
      team_version: 1,
      created_at: "2026-09-14T20:00:00Z",
      updated_at: "2026-09-14T20:00:00Z",
    };
    if (
      url.pathname.endsWith(`/work-items/${ids.item}/start`) &&
      method === "POST"
    ) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: ids.run,
          job_id: ids.item,
          project_id: ids.project,
          workflow_version_id: ids.workflow,
          run_number: 1,
          retry_of_run_id: null,
          thread_id: ids.run,
          status: "queued",
          desired_state: "running",
          mode: "demo",
          version: 0,
          recovering: false,
          current_node: null,
          result_summary: null,
          claimable_at: "2026-09-14T20:00:00Z",
          started_at: null,
          completed_at: null,
          last_event_position: 0,
          last_run_sequence: 0,
          last_event_at: null,
        }),
      });
    } else if (url.pathname.endsWith("/messages") && method === "POST") {
      planned = true;
      await route.fulfill({
        contentType: "application/json",
        status: 202,
        body: JSON.stringify({
          id: ids.item,
          status: "queued",
          directive_version: 1,
          team_version: 1,
          created_at: "2026-09-14T20:00:00Z",
        }),
      });
    } else if (url.pathname.endsWith("/messages")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: planned
            ? [
                {
                  id: ids.item,
                  sequence: 1,
                  role: "user",
                  identity: ids.user,
                  body: "Prepare the backlog",
                  directive_version: 1,
                  disposition: "delivered",
                  created_at: "2026-09-14T20:00:00Z",
                },
                {
                  id: ids.manager,
                  sequence: 2,
                  role: "manager",
                  identity: "mission-manager",
                  body: "One bounded item is ready.",
                  directive_version: 1,
                  disposition: "delivered",
                  created_at: "2026-09-14T20:00:01Z",
                },
              ]
            : [],
          next_after: null,
        }),
      });
    } else if (url.pathname.endsWith("/turns")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [], next_after: null }),
      });
    } else if (url.pathname.endsWith("/work-items")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: planned
            ? [
                {
                  id: ids.item,
                  key: "DEV-001",
                  title: "Implement durable feature",
                  objective: "Implement and verify it",
                  acceptance_criteria: ["Tests pass", "Review evidence exists"],
                  priority: 0,
                  dependencies: [],
                  lifecycle: "ready",
                  directive_version: 1,
                  team_version: 1,
                  job_id: null,
                  run_id: null,
                  created_at: "2026-09-14T20:00:01Z",
                },
              ]
            : [],
          next_after: null,
        }),
      });
    } else if (url.pathname === "/api/v1/missions" && method === "POST") {
      created = true;
      await route.fulfill({
        contentType: "application/json",
        status: 201,
        body: JSON.stringify(mission),
      });
    } else if (url.pathname === `/api/v1/missions/${ids.mission}`) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(mission),
      });
    } else {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: created ? [mission] : [],
          next_after: null,
        }),
      });
    }
  });
}

test("Phase 1 mission creation, durable manager backlog, and explicit linked run", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/missions");
  await page.getByLabel("Project").selectOption(ids.project);
  await page.getByLabel("Fixed development team").selectOption(ids.team);
  await page.getByLabel("Continuing objective").fill("Ship a durable feature");
  await page.getByRole("button", { name: "Create persistent mission" }).click();
  await expect(page).toHaveURL(`/missions/${ids.mission}`);
  await page.getByLabel("Message manager").fill("Prepare the backlog");
  await page.getByRole("button", { name: "Queue manager turn" }).click();
  await expect(page.getByText("One bounded item is ready.")).toBeVisible();
  await expect(
    page.getByText("DEV-001 · Implement durable feature"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start work item" }).click();
  await expect(page).toHaveURL(`/runs/${ids.run}`);
});
