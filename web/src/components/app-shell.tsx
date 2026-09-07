"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { ApiRequestError } from "@/lib/api/client";
import { useApiClient } from "@/components/app-providers";
import { StatusLabel } from "@/components/states";
import { useSession } from "@/lib/session";
import { useUiStore } from "@/lib/ui-store";

const navigation = [
  { href: "/", label: "Mission" },
  { href: "/projects", label: "Projects" },
  { href: "/runs", label: "Runs" },
  { href: "/workflows", label: "Workflows" },
  { href: "/registry", label: "Registry" },
  { href: "/workers", label: "Workers" },
  { href: "/providers", label: "Providers" },
  { href: "/models", label: "Models" },
  { href: "/routing", label: "Routing" },
  { href: "/policies", label: "Policies" },
  { href: "/approvals", label: "Approvals" },
  { href: "/artifacts", label: "Artifacts" },
  { href: "/health", label: "Health" },
  { href: "/settings", label: "Settings" },
  { href: "/debug", label: "Developer" },
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
  const menuRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!sidebarOpen || !window.matchMedia("(max-width: 800px)").matches)
      return;
    const links =
      sidebarRef.current?.querySelectorAll<HTMLAnchorElement>("a[href]");
    if (!links?.length) return;
    const menu = menuRef.current;
    links[0].focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSidebar();
      }
      if (event.key === "Tab" && links) {
        if (event.shiftKey && document.activeElement === links[0]) {
          event.preventDefault();
          links[links.length - 1].focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === links[links.length - 1]
        ) {
          event.preventDefault();
          links[0].focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard);
      menu?.focus();
    };
  }, [sidebarOpen, closeSidebar]);
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function signOut() {
    setLogoutError(null);
    setSigningOut(true);
    try {
      await apiClient.logout();
      queryClient.clear();
      router.replace("/login");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) {
        queryClient.clear();
        router.replace("/login");
      } else {
        await session.refetch();
        setLogoutError(
          "Sign out could not be confirmed. Retry after the connection recovers.",
        );
      }
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="topbar">
        <button
          ref={menuRef}
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
            disabled={signingOut}
            onClick={() => void signOut()}
            type="button"
          >
            Sign out
          </button>
        </div>
      </header>

      <aside
        ref={sidebarRef}
        className={sidebarOpen ? "sidebar sidebar-open" : "sidebar"}
      >
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
          <p className="eyebrow">M3 configuration</p>
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
