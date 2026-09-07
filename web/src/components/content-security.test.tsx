import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventRow } from "./event-row";
import { sanitizeTerminalOutput } from "./read-only-terminal";
import { SafeMarkdown, safeMarkdownUrl } from "./safe-markdown";

describe("untrusted content presentation", () => {
  it("renders Markdown without raw HTML or executable URLs", () => {
    const { container } = render(
      <SafeMarkdown>
        {
          'Hello <img src=x onerror="alert(1)"> [bad](javascript:alert(1)) [good](/runs)'
        }
      </SafeMarkdown>,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("bad").closest("a")).not.toHaveAttribute("href");
    expect(screen.getByRole("link", { name: "good" })).toHaveAttribute(
      "href",
      "/runs",
    );
    expect(safeMarkdownUrl("data:text/html,boom")).toBe("");
  });

  it("strips terminal escape, OSC hyperlink, and clipboard controls", () => {
    const hostile =
      "safe\u001b]0;title\u0007\u001b]52;c;secret\u0007\u001b]8;;https://evil.example\u0007link\u001b]8;;\u0007\u001b[31m red";
    const result = sanitizeTerminalOutput(hostile);

    expect(result).toContain("safelink red");
    expect(result).not.toContain("secret");
    expect(result).not.toContain("evil.example");
    expect(result).not.toContain("\u001b");
  });

  it("renders unknown event types as inert observable facts", () => {
    render(
      <EventRow
        event={
          {
            schema_version: "1.0",
            event_id: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
            global_position: 42,
            occurred_at: "2026-09-07T15:00:00Z",
            recorded_at: "2026-09-07T15:00:01Z",
            category: "system",
            type: "system.future_minor_fact",
            severity: "warning",
            message: '<img src=x onerror="alert(1)"> remains text',
            mode: "demo",
            visibility: "owner",
            source: { kind: "api", name: "fixture" },
            correlation_id: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb30",
            data: {},
            artifact_refs: [],
          } as never
        }
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Observable event" }),
    ).toBeVisible();
    expect(screen.getByText("Unknown event type")).toBeVisible();
    expect(screen.getByText("Demo fixture")).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });
});
