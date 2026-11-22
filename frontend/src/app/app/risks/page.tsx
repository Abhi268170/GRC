"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useState } from "react";

import { EmptyState, ListSkeleton, PageHeader } from "@/components/app/page";
import { RiskDialog, SourceLink } from "@/components/runs/registers";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { RiskItem } from "@/lib/types";

function tone(score: number) {
  return score >= 15 ? "bg-red-500 text-white" : score >= 10 ? "bg-orange-500 text-white" : score >= 5 ? "bg-amber-400 text-amber-950" : "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300";
}

function Heatmap({ risks }: { risks: RiskItem[] }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Heat map</CardTitle></CardHeader>
      <CardContent>
        <div className="flex gap-2">
          <div className="flex w-4 items-center justify-center"><span className="-rotate-90 whitespace-nowrap text-[11px] text-muted-foreground">Likelihood</span></div>
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-1">
              {[5, 4, 3, 2, 1].flatMap((l) => [1, 2, 3, 4, 5].map((i) => {
                const n = risks.filter((r) => r.likelihood === l && r.impact === i).length;
                return (
                  <div key={`${l}-${i}`} title={`Likelihood ${l} · Impact ${i}`}
                    className={`flex aspect-square items-center justify-center rounded-md text-sm font-semibold ${n ? tone(l * i) : "bg-muted/60 text-transparent"}`}>{n || "·"}</div>
                );
              }))}
            </div>
            <p className="mt-2 text-center text-[11px] text-muted-foreground">Impact</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

const STATUS: Record<string, string> = { open: "Open", mitigating: "Mitigating", accepted: "Accepted", closed: "Closed", dismissed: "Dismissed" };

export default function RisksPage() {
  const items = useQuery({ queryKey: ["risks"], queryFn: () => api<RiskItem[]>("/risks") });
  const [filter, setFilter] = useState("active");
  const [editing, setEditing] = useState<RiskItem | null>(null);
  const all = items.data ?? [];
  const active = all.filter((r) => ["open", "mitigating"].includes(r.status));
  const shown = filter === "active" ? active : filter === "all" ? all : all.filter((r) => r.status === filter);

  return (
    <>
      <PageHeader title="Risk register" description="Risks identified from approved assessments, scored by likelihood × impact." />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0">
          <Tabs value={filter} onValueChange={setFilter} className="mb-4">
            <TabsList><TabsTrigger value="active">Active</TabsTrigger><TabsTrigger value="accepted">Accepted</TabsTrigger><TabsTrigger value="closed">Closed</TabsTrigger><TabsTrigger value="all">All</TabsTrigger></TabsList>
          </Tabs>
          {items.isLoading ? <ListSkeleton /> : shown.length === 0 ? (
            <EmptyState icon={ShieldAlert} title="No risks here" text="Risks appear when an assessment is approved." />
          ) : (
            <div className="overflow-hidden rounded-3xl bg-card">
              {shown.map((r) => (
                <button key={r.id} onClick={() => setEditing(r)} className="flex w-full items-start gap-4 border-b px-5 py-4 text-left transition last:border-0 hover:bg-muted/40">
                  <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold ${tone(r.score)}`}>{r.score}</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm font-medium">{r.title}</p>
                    <p className="line-clamp-1 text-xs text-muted-foreground">
                      <span className="capitalize">{r.category?.replace("_", " ")}</span> · L{r.likelihood} × I{r.impact} · <SourceLink runId={r.run_id} title={r.run_title} />
                    </p>
                  </div>
                  <div className="hidden w-28 shrink-0 text-right text-xs sm:block">
                    <p>{r.owner?.full_name ?? <span className="text-muted-foreground">No owner</span>}</p>
                    <p className="text-muted-foreground">{r.treatment ? r.treatment[0].toUpperCase() + r.treatment.slice(1) : "No treatment"}</p>
                  </div>
                  <Badge variant="secondary" className="shrink-0">{STATUS[r.status] ?? r.status}</Badge>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="space-y-4"><Heatmap risks={active} /></div>
      </div>
      {editing && <RiskDialog key={editing.id} item={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
