"use client";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
export default function RunsPage() {
  const router = useRouter();
  function openRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("run") ?? "");
    router.push(`/runs/${encodeURIComponent(value)}`);
  }
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Durable history</p>
        <h1>Runs</h1>
        <p>
          Open a known run to inspect its authorized event history. Run creation
          and discovery are not available yet.
        </p>
      </header>
      <form className="content-card login-form" onSubmit={openRun}>
        <div className="field-group">
          <label htmlFor="run">Run ID</label>
          <input
            id="run"
            name="run"
            required
            pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
            placeholder="UUID"
          />
        </div>
        <button className="button button-primary" type="submit">
          Open run
        </button>
      </form>
    </div>
  );
}
