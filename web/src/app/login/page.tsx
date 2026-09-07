"use client";

import { useRouter } from "next/navigation";

import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  const router = useRouter();
  return (
    <main className="auth-page" id="main-content">
      <section className="auth-card" aria-labelledby="login-title">
        <div aria-hidden="true" className="auth-brand-mark">
          J
        </div>
        <p className="eyebrow">Jarvis V1</p>
        <h1 id="login-title">Sign in to Mission Control</h1>
        <p>
          Your credentials are sent only to the same-origin API and are never
          stored by the browser.
        </p>
        <LoginForm
          onAuthenticated={() => {
            const target = new URLSearchParams(window.location.search).get(
              "returnTo",
            );
            router.replace(
              target?.startsWith("/") &&
                !target.startsWith("//") &&
                !target.includes("\\")
                ? target
                : "/",
            );
          }}
        />
      </section>
    </main>
  );
}
