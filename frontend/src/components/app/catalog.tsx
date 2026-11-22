"use client";

import { ArrowRight, Layers, Loader2, MessageSquareText } from "lucide-react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { CatalogItem, RunSummary } from "@/lib/types";

export function CatalogCard({ item }: { item: CatalogItem }) {
  const router = useRouter();
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
        <Button className="w-full" onClick={() => start.mutate(undefined)} disabled={start.isPending}>
          {start.isPending ? <Loader2 className="animate-spin" /> : null} Start assessment <ArrowRight />
        </Button>
      </div>
    </div>
  );
}
