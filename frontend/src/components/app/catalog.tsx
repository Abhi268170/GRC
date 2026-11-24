"use client";

import { ArrowRight, Layers, Loader2, MessageSquareText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useAction, useMe } from "@/lib/hooks";
import type { CatalogItem, Me, RunSummary } from "@/lib/types";

/** A workspace admin has confirmed the company details. Needed once, before the first assessment. */
export function detailsConfirmed(me: Me | undefined): boolean {
  return Boolean(me?.tenant?.profile?.verified_at);
}

/** Shown instead of starting an assessment while the company details are not confirmed. */
function ConfirmFirst({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isAdmin ? "Confirm your company details first" : "Your company details aren't confirmed yet"}</DialogTitle>
          <DialogDescription>
            {isAdmin
              ? "Assessments are tailored to your company, so we ask you to check that its details are right and complete. You only do this once."
              : "Assessments are tailored to your company. A workspace admin needs to check and confirm the company details before the first assessment can start."}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          {isAdmin ? (
            <>
              <Button variant="outline" onClick={onClose}>Not now</Button>
              <Button asChild><Link href="/app/company?next=/app/assessments">Review company details <ArrowRight /></Link></Button>
            </>
          ) : (
            <Button onClick={onClose}>OK</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CatalogCard({ item }: { item: CatalogItem }) {
  const router = useRouter();
  const { data: me } = useMe();
  const [askToConfirm, setAskToConfirm] = useState(false);
  const start = useAction(() => api<RunSummary>("/runs", { body: { assessment_version_id: item.version_id } }), {
    invalidate: [["runs"]], onSuccess: (run) => router.push(`/app/runs/${run.id}`),
  });
  return (
    <div className="flex flex-col rounded-3xl bg-card p-6 transition hover:ring-2 hover:ring-brand/60">
      <div className="flex flex-wrap gap-1.5">
        {item.frameworks.map((f) => <Badge key={f} variant="secondary" className="bg-muted font-normal">{f}</Badge>)}
      </div>
      <h3 className="mt-5 text-xl font-medium tracking-tight">{item.title}</h3>
      {item.description && <p className="mt-1.5 line-clamp-3 text-sm text-muted-foreground">{item.description}</p>}
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1"><Layers className="size-3.5" /> {item.domains.length} domains</span>
        <span className="inline-flex items-center gap-1"><MessageSquareText className="size-3.5" /> {item.question_count} questions</span>
      </div>
      <p className="mt-3 line-clamp-1 text-xs text-muted-foreground">{item.domains.join(" · ")}</p>
      <div className="mt-auto pt-6">
        <Button className="w-full" onClick={() => (detailsConfirmed(me) ? start.mutate(undefined) : setAskToConfirm(true))} disabled={start.isPending || !me}>
          {start.isPending ? <Loader2 className="animate-spin" /> : null} Start assessment <ArrowRight />
        </Button>
      </div>
      {askToConfirm && <ConfirmFirst isAdmin={me?.user.platform_role === "tenant_admin"} onClose={() => setAskToConfirm(false)} />}
    </div>
  );
}
