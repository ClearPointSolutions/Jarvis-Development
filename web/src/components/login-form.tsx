"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { useApiClient } from "@/components/app-providers";
import { ApiRequestError } from "@/lib/api/client";
import { sessionQueryKey } from "@/lib/session";

export function LoginForm({
  onAuthenticated,
}: {
  onAuthenticated: () => void;
}) {
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSubmitting(true);
    setError(null);
    try {
      const session = await apiClient.login({
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      queryClient.setQueryData(sessionQueryKey, session);
      formElement.reset();
      onAuthenticated();
    } catch (cause) {
      setError(
        cause instanceof ApiRequestError
          ? cause.message
          : "Sign in is temporarily unavailable.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <div className="field-group">
        <label htmlFor="username">Username</label>
        <input
          autoCapitalize="none"
          autoComplete="username"
          id="username"
          maxLength={64}
          name="username"
          required
          type="text"
        />
      </div>
      <div className="field-group">
        <label htmlFor="password">Password</label>
        <input
          autoComplete="current-password"
          id="password"
          maxLength={1024}
          name="password"
          required
          type="password"
        />
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <button
        className="button button-primary"
        disabled={submitting}
        type="submit"
      >
        {submitting ? "Signing in…" : "Sign in securely"}
      </button>
    </form>
  );
}
