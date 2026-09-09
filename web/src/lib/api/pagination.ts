/** Follow server-owned cursors; never present a truncated page as complete. */
export async function collectPages<
  P extends { items: unknown[]; next_after?: string | number | null },
>(fetchPage: (after?: string | number) => Promise<P>): Promise<P> {
  const first = await fetchPage();
  const items = [...first.items];
  let cursor = first.next_after;
  const visited = new Set<string | number>();
  while (cursor !== null && cursor !== undefined) {
    if (visited.has(cursor))
      throw new Error(
        "The server repeated a history cursor. Refresh to retry.",
      );
    visited.add(cursor);
    const page = await fetchPage(cursor);
    items.push(...page.items);
    cursor = page.next_after;
  }
  return { ...first, items, next_after: null };
}
