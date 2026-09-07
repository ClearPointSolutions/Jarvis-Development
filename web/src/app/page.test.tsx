import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("foundation page", () => {
  it("states the current non-decorative scope", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: "Mission Control foundation" }),
    ).toBeVisible();
    expect(
      screen.getByText(/controls arrive in later milestones/i),
    ).toBeVisible();
  });
});
