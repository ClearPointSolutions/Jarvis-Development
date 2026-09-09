import { afterEach, expect, it, vi } from "vitest";
import { createRuntimeClient } from "./runtime";
import { collectPages } from "./pagination";

afterEach(() => vi.unstubAllGlobals());

it.each([
  ["runs", 50, "/runs"],
  ["nodes", 100, "/runs/run-id/nodes?limit=100"],
  ["evidence", 1000, "/runs/run-id/events?limit=1000"],
] as const)(
  "loads %s beyond the first server page",
  async (method, size, path) => {
    const first = Array.from({ length: size }, (_, id) => ({ id }));
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: first, next_after: "cursor /+" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ id: size }], next_after: null }),
      });
    vi.stubGlobal("fetch", fetcher);
    const client = createRuntimeClient();
    const result =
      method === "runs" ? await client.runs() : await client[method]("run-id");
    expect(result.items).toHaveLength(size + 1);
    expect(result.next_after).toBeNull();
    expect(fetcher.mock.calls[1][0]).toBe(
      `/api/v1${path}${path.includes("?") ? "&" : "?"}after=cursor%20%2F%2B`,
    );
  },
);

it("does not report partial history as success after a later-page failure", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({ items: [1], next_after: 2 })
    .mockRejectedValueOnce(new Error("offline"));
  await expect(collectPages(fetcher)).rejects.toThrow("offline");
});

it("rejects repeated cursors instead of requesting pages forever", async () => {
  const fetcher = vi.fn().mockResolvedValue({ items: [1], next_after: 2 });
  await expect(collectPages(fetcher)).rejects.toThrow("repeated");
  expect(fetcher).toHaveBeenCalledTimes(2);
});
