"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";

import { useApiClient } from "@/components/app-providers";
import { StatusLabel } from "@/components/states";
import { sessionQueryKey, useSession } from "@/lib/session";
import { useUiStore } from "@/lib/ui-store";

const navigation = [
  { href: "/", label: "Mission" },
  { href: "/projects", label: "Projects" },
  { href: "/runs", label: "Runs" },
  { href: "/workflows", label: "Workflows" },
  { href: "/registry", label: "Registry" },
  { href: "/approvals", label: "Approvals" },
  { href: "/artifacts", label: "Artifacts" },
  { href: "/health", label: "Health" },
  { href: "/settings", label: "Settings" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const session = useSession();
  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const closeSidebar = useUiStore((state) => state.closeSidebar);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function signOut() {
    setLogoutError(null);
    try {
      await apiClient.logout();
      queryClient.removeQueries({ queryKey: sessionQueryKey });
      router.replace("/login");
    } catch {
      setLogoutError("Sign out failed. Your session remains active.");
    }
  }

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="topbar">
        <button
          aria-controls="primary-navigation"
          aria-expanded={sidebarOpen}
          aria-label="Toggle navigation"
          className="menu-button"
          onClick={toggleSidebar}
          type="button"
        >
          <span aria-hidden="true">☰</span>
        </button>
        <Link className="brand" href="/" onClick={closeSidebar}>
          <span aria-hidden="true" className="brand-mark">
            J
          </span>
          <span>
            <strong>Jarvis</strong>
            <small>Mission Control</small>
          </span>
        </Link>
        <div className="topbar-session">
          <StatusLabel label="Protected session" tone="good" />
          <span className="session-user">{session.data?.user.username}</span>
          <button
            className="text-button"
            onClick={() => void signOut()}
            type="button"
          >
            Sign out
          </button>
        </div>
      </header>

      <aside className={sidebarOpen ? "sidebar sidebar-open" : "sidebar"}>
        <nav aria-label="Primary" id="primary-navigation">
          <p className="nav-section-label">Control plane</p>
          <ul>
            {navigation.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={active ? "nav-link nav-link-active" : "nav-link"}
                    href={item.href}
                    onClick={closeSidebar}
                  >
                    <span aria-hidden="true" className="nav-marker" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="sidebar-note">
          <p className="eyebrow">M2 foundation</p>
          <p>
            Runtime execution remains server-authoritative and is not simulated
            here.
          </p>
        </div>
      </aside>

      {sidebarOpen ? (
        <button
          aria-label="Close navigation"
          className="sidebar-scrim"
          onClick={closeSidebar}
          type="button"
        />
      ) : null}

      <main className="app-main" id="main-content" tabIndex={-1}>
        {logoutError ? (
          <p className="inline-alert" role="alert">
            {logoutError}
          </p>
        ) : null}
        {children}
      </main>
    </div>
  );
}
