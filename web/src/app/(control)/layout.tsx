import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { SessionBoundary } from "@/components/session-boundary";

export default function ControlLayout({ children }: { children: ReactNode }) {
  return (
    <SessionBoundary>
      <AppShell>{children}</AppShell>
    </SessionBoundary>
  );
}
