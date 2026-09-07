import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "./app-providers";
import { LoginForm } from "./login-form";
import { SessionBoundary } from "./session-boundary";
import type { BrowserApiClient } from "@/lib/api/client";
import { ApiRequestError } from "@/lib/api/client";

const session = {
  user: {
    id: "01992f3e-7e4d-7e8a-a32d-4f82a1e1cb29",
    username: "owner",
    role: "owner" as const,
  },
  csrf_token: "csrf-token-with-more-than-thirty-two-characters",
  idle_expires_at: "2026-09-07T17:00:00Z",
  absolute_expires_at: "2026-09-08T17:00:00Z",
};

function client(overrides: Partial<BrowserApiClient> = {}): BrowserApiClient {
  return {
    getSession: vi.fn().mockResolvedValue(session),
    login: vi.fn().mockResolvedValue(session),
    logout: vi.fn().mockResolvedValue({ revoked: true }),
    ...overrides,
  };
}

describe("session and login boundaries", () => {
  it("shows a loading status, then protected content", async () => {
    let resolveSession: (value: typeof session) => void = () => undefined;
    const pending = new Promise<typeof session>((resolve) => {
      resolveSession = resolve;
    });
    render(
      <AppProviders apiClient={client({ getSession: () => pending })}>
        <SessionBoundary>
          <h1>Protected content</h1>
        </SessionBoundary>
      </AppProviders>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Checking your secure session",
    );
    resolveSession(session);
    expect(
      await screen.findByRole("heading", { name: "Protected content" }),
    ).toBeVisible();
  });

  it("does not expose protected content after a 401", async () => {
    render(
      <AppProviders
        apiClient={client({
          getSession: vi
            .fn()
            .mockRejectedValue(
              new ApiRequestError("Sign in required", 401, "auth.required"),
            ),
        })}
      >
        <SessionBoundary>
          <p>secret project</p>
        </SessionBoundary>
      </AppProviders>,
    );

    expect(
      await screen.findByRole("heading", { name: "Your session is required" }),
    ).toBeVisible();
    expect(screen.queryByText("secret project")).not.toBeInTheDocument();
  });

  it("provides labeled keyboard-operable login fields", async () => {
    const apiClient = client();
    const authenticated = vi.fn();
    render(
      <AppProviders apiClient={apiClient}>
        <LoginForm onAuthenticated={authenticated} />
      </AppProviders>,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Username"), "owner");
    await user.type(screen.getByLabelText("Password"), "synthetic-password");
    await user.click(screen.getByRole("button", { name: "Sign in securely" }));

    await waitFor(() => expect(authenticated).toHaveBeenCalledOnce());
    expect(apiClient.login).toHaveBeenCalledWith({
      username: "owner",
      password: "synthetic-password",
    });
  });
});
