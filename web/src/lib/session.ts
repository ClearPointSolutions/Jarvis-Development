"use client";

import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "@/components/app-providers";

export const sessionQueryKey = ["session"] as const;

export function useSession() {
  const apiClient = useApiClient();
  return useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => apiClient.getSession(),
    refetchOnWindowFocus: true,
    refetchInterval: 30_000,
  });
}
