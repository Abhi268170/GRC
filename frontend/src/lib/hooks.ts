"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage } from "./api";
import type { MasterDataItem, Me } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export function useMasterData(category: string) {
  return useQuery({
    queryKey: ["master-data", category],
    queryFn: () => api<MasterDataItem[]>(`/master-data?category=${category}`),
    staleTime: 5 * 60_000,
  });
}

/** Mutation that shows a toast on error (and optionally on success) and invalidates queries. */
export function useAction<TIn, TOut>(
  fn: (input: TIn) => Promise<TOut>,
  opts: { invalidate?: QueryKey[]; success?: string; onSuccess?: (out: TOut) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (out) => {
      opts.invalidate?.forEach((key) => qc.invalidateQueries({ queryKey: key }));
      if (opts.success) toast.success(opts.success);
      opts.onSuccess?.(out);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}
