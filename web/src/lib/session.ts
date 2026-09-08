"use client";

import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "@/components/app-providers";
import { ApiRequestError } from "@/lib/api/client";

export const sessionQueryKey = ["session"] as const;

export function useSession() {
  const apiClient = useApiClient();
  return useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => apiClient.getSession(),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const error = query.state.error;
      return error &&
        (!(error instanceof ApiRequestError) || error.status >= 500)
        ? 1_000
        : 30_000;
    },
  });
}
