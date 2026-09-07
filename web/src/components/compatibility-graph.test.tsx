import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompatibilityGraph } from "./compatibility-graph";

describe("React Flow compatibility", () => {
  it("renders typed nodes and initializes with a typed edge", async () => {
    const initialized = vi.fn();
    render(<CompatibilityGraph onInit={initialized} />);

    expect(screen.getByLabelText("Workflow compatibility graph")).toBeVisible();
    expect(screen.getByText("Organizer")).toBeInTheDocument();
    expect(screen.getByText("Finalize")).toBeInTheDocument();
    await waitFor(() => expect(initialized).toHaveBeenCalledOnce());
    expect(initialized.mock.calls[0][0].getEdges()).toEqual([
      expect.objectContaining({
        id: "organizer-finalize",
        source: "organizer",
        target: "finalize",
      }),
    ]);
  });
});
