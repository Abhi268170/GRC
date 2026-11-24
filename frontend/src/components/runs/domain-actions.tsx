"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { isConfirmed, type RequirementInput } from "@/components/runs/requirements";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { Evaluation, EvidenceFile, RequirementState, Workspace } from "@/lib/types";

/**
 * One domain of a run: its data and what a person can do to it. Shared by the conversation page
 * and the review page, which show the same workspace in two ways.
 * `onSaved` runs after a requirement was saved or confirmed (the pages close their edit panel).
 */
export function useDomainWorkspace(runId: string, domainId: string, onSaved?: () => void) {
  const router = useRouter();
  const qc = useQueryClient();
  const key = ["workspace", runId, domainId];
  const ws = useQuery({
    queryKey: key,
    queryFn: () => api<Workspace>(`/runs/${runId}/domains/${domainId}`),
    // Poll while evidence is being read or background analysis is updating other requirements.
    refetchInterval: (q) => (q.state.data && (q.state.data.analysis_pending || q.state.data.evidence.some((e) => ["pending", "processing"].includes(e.processing_status))) ? 2500 : false),
  });
  const set = (w: Workspace) => qc.setQueryData(key, w);

  const saveRequirement = useAction(({ r, v }: { r: RequirementState; v: RequirementInput }) => api<Workspace>(`/runs/${runId}/requirements/${r.id}`, { method: "PUT", body: v }), {
    onSuccess: (w) => { set(w); onSaved?.(); toast.success("Saved. Checking other requirements in the background."); },
  });
  /** Confirms the rating as it stands (an AI suggestion becomes a verified rating). */
  const verify = useAction((e: Evaluation) => api<Workspace>(`/runs/${runId}/evaluations/${e.id}`, { method: "PUT", body: { rating: e.rating, is_na: e.is_na, na_reason: e.na_reason } }), {
    onSuccess: (w) => { set(w); onSaved?.(); },
  });
  const complete = useAction(() => api(`/runs/${runId}/domains/${domainId}/complete`, { method: "POST" }), {
    invalidate: [key, ["run", runId], ["runs"]], success: "Domain completed", onSuccess: () => router.push(`/app/runs/${runId}`),
  });
  const reopen = useAction(() => api(`/runs/${runId}/domains/${domainId}/reopen`, { method: "POST" }), { invalidate: [key, ["run", runId]] });

  async function upload(file: File): Promise<EvidenceFile | undefined> {
    const form = new FormData();
    form.append("file", file);
    try {
      const ev = await api<EvidenceFile>(`/runs/${runId}/evidence`, { form });
      await ws.refetch();
      return ev;
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  return { ws, set, saveRequirement, verify, complete, reopen, upload };
}

export type DomainWorkspace = ReturnType<typeof useDomainWorkspace>;

/** A domain can be completed once a person has confirmed every rating. */
export const allConfirmed = (w: Workspace) => w.requirements.every((r) => isConfirmed(r.evaluation));

/** "Complete domain" while the domain is open, "Reopen" once it is completed. On a phone only the icon shows, so the title keeps its room. */
export function CompleteOrReopen({ w, domain }: { w: Workspace; domain: DomainWorkspace }) {
  if (w.domain.status === "completed") {
    return w.domain.can_work && ["in_progress", "changes_requested"].includes(w.run_status)
      ? <Button variant="outline" size="sm" disabled={domain.reopen.isPending} onClick={() => domain.reopen.mutate(undefined)} aria-label="Reopen"><RotateCcw /><span className="hidden sm:inline">Reopen</span></Button> : null;
  }
  if (!w.editable) return null;
  const ready = allConfirmed(w);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span><Button size="sm" disabled={!ready || domain.complete.isPending} onClick={() => domain.complete.mutate(undefined)} aria-label="Complete domain"><CheckCircle2 /><span className="hidden sm:inline">Complete domain</span></Button></span>
      </TooltipTrigger>
      {!ready && <TooltipContent>Every requirement needs a confirmed rating</TooltipContent>}
    </Tooltip>
  );
}
