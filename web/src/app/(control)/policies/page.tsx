"use client";
import { useState } from "react";
import { RegistryPage } from "@/components/registry-page";
export default function Page() {
  const [kind, setKind] = useState<"retry_policy" | "permission_policy">(
    "retry_policy",
  );
  return (
    <>
      <nav className="registry-toolbar" aria-label="Policy registries">
        <button
          type="button"
          className="button button-secondary"
          aria-pressed={kind === "retry_policy"}
          onClick={() => setKind("retry_policy")}
        >
          Retry policies
        </button>
        <button
          type="button"
          className="button button-secondary"
          aria-pressed={kind === "permission_policy"}
          onClick={() => setKind("permission_policy")}
        >
          Permission policies
        </button>
      </nav>
      <RegistryPage key={kind} kind={kind} />
    </>
  );
}
