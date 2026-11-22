"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, ApiError, errorMessage } from "./api";
import type { Me } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me"),
    // Being signed out is an answer, not a failure: don't retry it. Retry anything else (a restart, a blip).
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 60_000,
    throwOnError: false, // the shell decides what a failure means
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
