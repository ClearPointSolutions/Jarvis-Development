import createClient from "openapi-fetch";

import type {
  ApiErrorResponse,
  LoginRequest,
  LogoutResponse,
  SessionResponse,
} from "@jarvis/contracts";

type JsonResponse<T> = { content: { "application/json": T } };

// This narrow compatibility surface is replaced with the integration-owned
// generated OpenAPI `paths` type after the M2 backend branches merge.
interface BrowserApiPaths {
  "/api/v1/auth/login": {
    post: {
      requestBody: { content: { "application/json": LoginRequest } };
      responses: {
        200: JsonResponse<SessionResponse>;
        400: JsonResponse<ApiErrorResponse>;
        401: JsonResponse<ApiErrorResponse>;
        429: JsonResponse<ApiErrorResponse>;
      };
    };
  };
  "/api/v1/auth/logout": {
    post: {
      responses: {
        200: JsonResponse<LogoutResponse>;
        401: JsonResponse<ApiErrorResponse>;
        403: JsonResponse<ApiErrorResponse>;
      };
    };
  };
  "/api/v1/session": {
    get: {
      responses: {
        200: JsonResponse<SessionResponse>;
        401: JsonResponse<ApiErrorResponse>;
      };
    };
  };
}

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export interface BrowserApiClient {
  getSession(): Promise<SessionResponse>;
  login(credentials: LoginRequest): Promise<SessionResponse>;
  logout(): Promise<LogoutResponse>;
}

export type ApiFetch = (request: Request) => Promise<Response>;

function requestError(error: ApiErrorResponse | undefined, response: Response) {
  return new ApiRequestError(
    error?.error.message ?? "The request could not be completed.",
    response.status,
    error?.error.code ?? "request.failed",
    error?.error.request_id,
  );
}

export function createBrowserApiClient(
  fetchImplementation?: ApiFetch,
): BrowserApiClient {
  const client = createClient<BrowserApiPaths>({
    baseUrl: globalThis.location?.origin ?? "http://localhost",
    credentials: "same-origin",
    fetch: fetchImplementation,
    headers: { Accept: "application/json" },
  });
  let csrfToken: string | undefined;

  return {
    async getSession() {
      const result = await client.GET("/api/v1/session");
      if (!result.data) {
        csrfToken = undefined;
        throw requestError(result.error, result.response);
      }
      csrfToken = result.data.csrf_token;
      return result.data;
    },

    async login(credentials) {
      const result = await client.POST("/api/v1/auth/login", {
        body: credentials,
      });
      if (!result.data) throw requestError(result.error, result.response);
      csrfToken = result.data.csrf_token;
      return result.data;
    },

    async logout() {
      if (!csrfToken) {
        throw new ApiRequestError(
          "The session must be refreshed before signing out.",
          403,
          "csrf.missing",
        );
      }
      const result = await client.POST("/api/v1/auth/logout", {
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
      });
      csrfToken = undefined;
      if (!result.data) throw requestError(result.error, result.response);
      return result.data;
    },
  };
}
