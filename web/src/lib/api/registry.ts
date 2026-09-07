import createClient from "openapi-fetch";
import type { paths } from "@jarvis/api";
import type {
  RegistryRecord,
  RegistryPage,
  RouteResolution,
  ValidationReport,
  RegistryWrite,
  RoutePreviewRequest,
} from "@jarvis/contracts";
import { ApiRequestError } from "./client";

export type RegistryKind = NonNullable<RegistryRecord["spec"]["kind"]>;

export function createRegistryClient(csrfToken?: string) {
  const client = createClient<paths>({
    baseUrl: globalThis.location?.origin ?? "http://localhost",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
  });
  async function unwrap<T>(result: {
    data?: unknown;
    response: Response;
  }): Promise<T> {
    if (result.data !== undefined) return result.data as T;
    const status = result.response.status;
    throw new ApiRequestError(
      status === 409
        ? "This configuration changed. Close the editor, refresh, and try again."
        : status === 401
          ? "Your session expired. Sign in again."
          : status === 422
            ? "Configuration rejected. Check field values, revision references, and the endpoint allowlist."
            : status === 403
              ? "Owner permission and a current session are required."
              : "The request failed. Refresh and try again.",
      status,
      "registry.request_failed",
    );
  }
  return {
    async list(kind: RegistryKind, after?: string): Promise<RegistryPage> {
      return unwrap(
        await client.GET("/api/v1/registry/{kind}", {
          params: {
            path: { kind },
            query: { limit: 100, ...(after ? { after } : {}) },
          },
        }),
      );
    },
    async save(
      kind: RegistryKind,
      write: RegistryWrite,
      id?: string,
    ): Promise<RegistryRecord> {
      // The two authoritative generators differ on defaults and minItems tuples.
      // Pydantic validates the submitted object; no private wire schema is used.
      const body =
        write as paths["/api/v1/registry/{kind}"]["post"]["requestBody"]["content"]["application/json"];
      return unwrap(
        id
          ? await client.PUT("/api/v1/registry/{kind}/{id}", {
              params: { path: { kind, id } },
              body,
            })
          : await client.POST("/api/v1/registry/{kind}", {
              params: { path: { kind } },
              body,
            }),
      );
    },
    async revisions(
      kind: RegistryKind,
      id: string,
      after?: string,
    ): Promise<RegistryPage> {
      return unwrap(
        await client.GET("/api/v1/registry/{kind}/{id}/revisions", {
          params: {
            path: { kind, id },
            query: { limit: 100, ...(after ? { after } : {}) },
          },
        }),
      );
    },
    async validate(kind: RegistryKind, id: string): Promise<ValidationReport> {
      return unwrap(
        await client.POST("/api/v1/registry/{kind}/{id}/validate", {
          params: { path: { kind, id } },
          body: { idempotency_key: crypto.randomUUID() },
        }),
      );
    },
    async preview(request: RoutePreviewRequest): Promise<RouteResolution> {
      const body =
        request as paths["/api/v1/routing/preview"]["post"]["requestBody"]["content"]["application/json"];
      return unwrap(await client.POST("/api/v1/routing/preview", { body }));
    },
  };
}
export type RegistryClient = ReturnType<typeof createRegistryClient>;
