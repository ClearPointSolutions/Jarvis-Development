"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { ApiRequestError } from "@/lib/api/client";
import { useSession } from "@/lib/session";

export function SessionBoundary({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.isPending)
    return <LoadingState label="Checking your secure session" />;

  if (
    session.error instanceof ApiRequestError &&
    session.error.status === 401
  ) {
    return (
      <main className="auth-page" id="main-content">
        <section className="auth-card" aria-labelledby="session-required-title">
          <p className="eyebrow">Secure boundary</p>
          <h1 id="session-required-title">Your session is required</h1>
          <p>
            This route is protected. Sign in with the locally bootstrapped owner
            account.
          </p>
          <Link className="button button-primary" href="/login">
            Go to sign in
          </Link>
        </section>
      </main>
    );
  }

  if (session.isError) {
    return (
      <main className="auth-page" id="main-content">
        <ErrorState
          message="Mission Control could not verify the current session."
          onRetry={() => void session.refetch()}
        />
      </main>
    );
  }

  return children;
}
