"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useState } from "react";

import {
  createBrowserApiClient,
  type BrowserApiClient,
} from "@/lib/api/client";

const ApiClientContext = createContext<BrowserApiClient | null>(null);

export function AppProviders({
  apiClient,
  children,
}: {
  apiClient?: BrowserApiClient;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: false,
            staleTime: 15_000,
          },
          mutations: { retry: false },
        },
      }),
  );
  const [client] = useState(() => apiClient ?? createBrowserApiClient());

  return (
    <ApiClientContext.Provider value={client}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ApiClientContext.Provider>
  );
}

export function useApiClient(): BrowserApiClient {
  const client = useContext(ApiClientContext);
  if (!client) throw new Error("API client must be used inside AppProviders");
  return client;
}
